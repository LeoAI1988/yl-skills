// Local workbench; platform actions run through the official WorkBuddy adapter.
import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { validatePlan, toMarkdown } from './plan-core.mjs';
import {saveBatch} from './publish-history.mjs';
import {createPortalApi} from './portal-api.mjs';
import {createWorkBuddyRunner} from './workbuddy-runner.mjs';
import {createRuntimeService} from './runtime-service.mjs';
import {loadConfiguration} from './configuration.mjs';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const VIDEO_EXT = new Set(['.mp4', '.mov', '.mkv', '.m4v']);
const IMAGE_EXT = new Set(['.png', '.jpg', '.jpeg', '.webp']);
const SKIP_DIR = /^(素材原件|素材|原片|原件|cache|temp|缓存)$/i;
const MIME = { '.svg':'image/svg+xml', '.html':'text/html; charset=utf-8', '.css':'text/css; charset=utf-8', '.mjs':'text/javascript; charset=utf-8', '.ico':'image/x-icon', '.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.webp':'image/webp', '.mp4':'video/mp4', '.m4v':'video/mp4', '.mov':'video/quicktime', '.mkv':'video/x-matroska' };

// 成片名里除了标题还会挂状态词和版本号，而且两者可能交替出现：
//   1-3-实战营_最终版_v7.mp4
//   1-3-实战营_YL剪辑待审_v2_CFR.mp4      ← 状态在版本号前面，还有 CFR 后缀
//   01_做容易的事_剪辑版_v8.mp4           ← 二次剪辑批次的统一状态词
// 封面命名也不统一：
//   4-2-课程-体系_封面_v2.png
//   1-3-实战营_黑底黄字人像封面_v5.png    ← 「封面」前带修饰词
//   封面.png                              ← 通用名，文件名里没有标题（述品视频逐条目录常见）
// 统一归一化成「序号-标题」，才能把视频和封面配上。
const STATUS_SUFFIX = /(?:YL剪辑待审|待审|预览|审核版|最终版|final|成片|cut|CFR|剪辑版)/i;

export function baseKey(name) {
  let stem = path.parse(name).name;
  // 先剥封面整段（含前面所有修饰词）
  stem = stem.replace(/[_-][^-_]*(?:封面|cover)[_-]?v?\d*$/i, '');
  // 再循环剥「状态词 / 版本号」，两者会交替出现，必须反复剥到不动点
  for (let prev = null; prev !== stem;) {
    prev = stem;
    stem = stem.replace(/[_-]v\d+$/i, '');
    stem = stem.replace(new RegExp(`[_-]${STATUS_SUFFIX.source}$`, 'i'), '');
  }
  return stem.replace(/[_-]+$/, '').trim();
}
const version = name => +(name.match(/[_-]v(\d+)(?=\.[^.]+$)/i)?.[1] || 0);

// 通用名封面：文件名剥掉版本号后只剩「封面 / cover」，没有标题，无法按名字配对。
// 只有当它与成片同目录、且该目录按 baseKey 归并后只有这一条成片时，归属才唯一，
// 才允许自动匹配；一个目录里有多条不同成片时保持缺封面，留给人工确认，不猜。
function isGenericCover(name) {
  const stem = path.parse(name).name.replace(/[_-]?v?\d+$/i, '').replace(/^[_-]+|[_-]+$/g, '');
  return /^(?:封面|cover)$/i.test(stem);
}

// 封面可能和成片同目录，也可能被批量收进成片目录下的封面子目录（如 切片/4-1/封面_20261016_v1/），
// 还可能只叫「封面.png」这类通用名（见 isGenericCover）。
// 同目录优先，其次子目录；同层内版本号高的优先；同名可配对时通用名封面不参与，避免覆盖精确匹配。
function coverCandidates(v, files, siblingVideoKeys) {
  const images = files.filter(f =>
    IMAGE_EXT.has(f.ext) && /封面|cover/i.test(f.name) && baseKey(f.name) === baseKey(v.name));
  if (!images.length && siblingVideoKeys === 1) {
    images.push(...files.filter(f => f.dir === v.dir && IMAGE_EXT.has(f.ext) && isGenericCover(f.name)));
  }
  const rank = f => f.dir === v.dir ? 0 : 1;
  return images.sort((a, b) => rank(a) - rank(b) || version(b.name) - version(a.name));
}

async function walk(dir, depth, out, warnings) {
  if (depth > 4) { warnings.add('部分目录超过 4 层，未扫描'); return; }
  if (out.length >= 800) { warnings.add('达到 800 个文件上限，请缩小扫描范围'); return; }
  let entries;
  try { entries = await fsp.readdir(dir, { withFileTypes:true }); }
  catch { warnings.add(`无法读取目录：${dir}`); return; }
  for (const e of entries) {
    if (out.length >= 800) { warnings.add('达到 800 个文件上限，请缩小扫描范围'); break; }
    if (e.name.startsWith('.') || e.name.startsWith('~$') || e.isSymbolicLink()) continue;
    const full = path.join(dir, e.name);
    if (e.isDirectory()) { if (!SKIP_DIR.test(e.name)) await walk(full, depth + 1, out, warnings); continue; }
    const ext = path.extname(e.name).toLowerCase();
    if (VIDEO_EXT.has(ext) || IMAGE_EXT.has(ext) || ext === '.md') {
      try { out.push({ dir, name:e.name, full, ext, size:(await fsp.stat(full)).size }); }
      catch { warnings.add(`文件无法读取：${full}`); }
    }
  }
}

function relatedDraft(video, documents, siblingVideos) {
  const key = baseKey(video.name);
  const local = documents.filter(d => d.dir === video.dir);
  const declared = local.filter(d => d.finals.includes(video.name.toLowerCase()));
  if (declared.length === 1) return declared[0];
  const named = local.filter(d => path.parse(d.name).name.replace(/[_-](?:审查稿|审稿).*$/, '') === key);
  if (named.length === 1) return named[0];
  if (local.length === 1 && new Set(siblingVideos.filter(v => v.dir === video.dir).map(v => baseKey(v.name))).size === 1) return local[0];
  return null;
}

export async function scanOne(inputPath) {
  if (typeof inputPath !== 'string' || !path.isAbsolute(inputPath.trim().replace(/^["']|["']$/g, ''))) return { path:inputPath, ok:false, error:'请输入完整的绝对文件夹路径' };
  const resolved = path.resolve(inputPath.trim().replace(/^["']|["']$/g, ''));
  try { if (!(await fsp.stat(resolved)).isDirectory()) throw new Error(); }
  catch { return { path:resolved, ok:false, error:'文件夹不存在或无权访问' }; }
  const files = [], warnings = new Set();
  await walk(resolved, 0, files, warnings);
  const allVideos = files.filter(f => VIDEO_EXT.has(f.ext));
  const documents = [];
  for (const f of files.filter(f => f.ext === '.md')) {
    if (f.size > 2 * 1024 * 1024) { warnings.add(`审查稿过大，未解析：${f.name}`); continue; }
    try {
      const text = await fsp.readFile(f.full, 'utf8');
      const finals = [...text.matchAll(/最终视频[：:]\s*[`"“]?([^\r\n`"”]+?\.(?:mp4|mov|mkv|m4v))/gi)].map(m => m[1].trim().toLowerCase());
      documents.push({ ...f, text, finals });
    } catch { warnings.add(`审查稿无法读取：${f.name}`); }
  }
  const groups = new Map();
  for (const v of allVideos) {
    const key = v.dir + '|' + baseKey(v.name);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(v);
  }
  // 每个目录里按 baseKey 归并后的成片条数：同一成片的多个版本算一条，
  // 通用名封面只在「目录里只有一条成片」时才自动匹配。
  const videoKeysByDir = new Map();
  for (const v of allVideos) {
    if (!videoKeysByDir.has(v.dir)) videoKeysByDir.set(v.dir, new Set());
    videoKeysByDir.get(v.dir).add(baseKey(v.name));
  }
  const picked = [];
  for (const group of groups.values()) {
    const declared = group.filter(v => documents.some(d => d.dir === v.dir && d.finals.includes(v.name.toLowerCase())));
    if (declared.length > 1) warnings.add(`多个审查稿指定不同版本，需人工核对：${baseKey(group[0].name)}`);
    picked.push((declared.length === 1 ? declared : group).sort((a,b) => version(b.name)-version(a.name) || a.name.localeCompare(b.name, 'zh-CN', {numeric:true}))[0]);
  }
  picked.sort((a,b) => Number(!/_最终版|_final/i.test(a.name))-Number(!/_最终版|_final/i.test(b.name)) || a.name.localeCompare(b.name, 'zh-CN', {numeric:true}));

  const items = picked.map((v,i) => {
    const covers = coverCandidates(v, files, videoKeysByDir.get(v.dir)?.size || 0);
    // 没有独立封面文件时，退到同目录的预览图（切片类目录常见：切片预览.jpg 里每个切片一格）
    const previews = covers.length ? [] : files.filter(f => f.dir === v.dir && IMAGE_EXT.has(f.ext) && /预览|preview|contact|sheet/i.test(f.name));
    const doc = relatedDraft(v, documents, allVideos);
    const block = doc?.text.split(/^##\s+/m).find(b => b.startsWith('三项内容分析'));
    const raw = block?.match(/标题匹配[：:]\s*(.+)/)?.[1]?.split(/来自完整主旨|来自完整|。|效率[：:]|新增价值[：:]/)[0].trim();
    const title = raw && !/^(前半|后半)/.test(raw) ? raw.replace(/／/g, ' ').replace(/\s+/g, ' ').trim() : null;
    // 文件名本身当标题兜底（切片类审查稿没有「标题匹配」字段）
    const fallbackTitle = path.parse(v.name).name.replace(/^\d+_/, '').replace(/[_-](最终版|待审|预览).*$/, '').trim();
    return {
      idx:i+1, name:v.name, full:v.full,
      rel:path.relative(resolved,v.full).replace(/\\/g,'/'),
      sizeMB:+(v.size/1048576).toFixed(1),
      cover:covers[0]?.full || null,
      previews:previews.map(f=>f.full),
      draftTitle:title, draft:title ? {title,raw,source:doc.full} : null,
      nameTitle:fallbackTitle || null,
    };
  });
  return { path:resolved, ok:true, count:items.length, items, missingCover:items.filter(i=>!i.cover).map(i=>i.rel), warnings:[...warnings], scannedAt:new Date().toISOString() };
}

function send(res, code, data) {
  res.writeHead(code, {'Content-Type':'application/json; charset=utf-8', 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'});
  res.end(JSON.stringify(data));
}
async function readBody(req) {
  if (!req.headers['content-type']?.startsWith('application/json')) throw Object.assign(new Error('需要 JSON 请求'), {status:415});
  const chunks = []; let size = 0;
  for await (const chunk of req) { size += chunk.length; if (size > 1024*1024) throw Object.assign(new Error('请求超过 1 MB'), {status:413}); chunks.push(chunk); }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw Object.assign(new Error('JSON 格式错误'), {status:400}); }
}

async function streamFile(req, res, file) {
  const stat = await fsp.stat(file);
  if (!stat.isFile()) return send(res,404,{error:'文件不存在'});
  const size = stat.size;
  let start = 0, end = size - 1, status = 200;
  if (req.headers.range) {
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range);
    if (!m || (!m[1] && !m[2])) { res.writeHead(416, {'Content-Range':`bytes */${size}`}); return res.end(); }
    if (!m[1]) start = Math.max(0, size - Number(m[2]));
    else { start = Number(m[1]); if(m[2]) end = Math.min(end,Number(m[2])); }
    if (start > end || start >= size) { res.writeHead(416, {'Content-Range':`bytes */${size}`}); return res.end(); }
    status = 206;
  }
  const headers = {'Content-Type':MIME[path.extname(file).toLowerCase()] || 'application/octet-stream', 'Content-Length':Math.max(0,end-start+1), 'Accept-Ranges':'bytes', 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'};
  if(status === 206) headers['Content-Range'] = `bytes ${start}-${end}/${size}`;
  res.writeHead(status,headers);
  if(req.method === 'HEAD' || !size) return res.end();
  const stream = fs.createReadStream(file, {start,end});
  res.on('close', () => stream.destroy());
  stream.on('error', () => res.destroy());
  stream.pipe(res);
}

export function createWorkbenchServer({ root, runtime = null, staticRoot = ROOT, preferences = {} } = {}) {
  if(!root)throw new Error('必须指定核心之外的工作目录');
  root=path.resolve(root);
  const core=path.resolve(ROOT,'../..'),rel=path.relative(core,root);
  if(!rel||(!rel.startsWith('..'+path.sep)&&rel!=='..'&&!path.isAbsolute(rel)))throw new Error('工作目录不能在共享核心内');
  const media = new Map(), byPath = new Map();
  let publishing=false;
  const portalApi=createPortalApi({root,send,readBody,streamFile,runtime});
  const register = async file => {
    const real = await fsp.realpath(file);
    let token = byPath.get(real);
    if (!token) { token=randomUUID(); byPath.set(real,token); media.set(token,real); }
    return `/api/media/${token}`;
  };
  const server = http.createServer(async (req,res) => {
    try {
      const authority = `127.0.0.1:${server.address().port}`;
      const oauthReturn=req.method==='GET' && req.url.split('?')[0]==='/auth/workbuddy/callback';
      if (req.headers.host !== authority || (!oauthReturn && ((req.headers.origin && req.headers.origin !== `http://${authority}`) || req.headers['sec-fetch-site'] === 'cross-site'))) return send(res,403,{error:'仅允许本机工作台页面访问'});
      const url = new URL(req.url, `http://${authority}`);
      const pathname = decodeURIComponent(url.pathname);
      if(pathname === '/api/health') return send(res,200,{app:'yl-channels-publisher-workbench',version:2});
      if(pathname==='/api/preferences' && req.method==='GET')return send(res,200,{products:preferences.products||[],tags:preferences.tags||[]});
      if(await portalApi(req,res,url))return;
      if(pathname === '/api/scan' && req.method === 'POST') {
        const body = await readBody(req);
        if(!Array.isArray(body.paths) || !body.paths.length || body.paths.length > 3 || body.paths.some(p=>typeof p!=='string')) return send(res,400,{error:'需要 1～3 个文件夹路径'});
        const results = [];
        for (const p of body.paths) {
          const result = await scanOne(p);
          for(const item of result.items || []) {
            item.previewUrl = await register(item.full);
            if(item.cover) item.coverUrl = await register(item.cover);
          }
          results.push(result);
        }
        return send(res,200,{results});
      }
      if(pathname === '/api/save' && req.method === 'POST') {
        const body = await readBody(req);
        const errors = validatePlan(body.plan);
        if(errors.length) return send(res,400,{error:errors.join('；')});
        for(const row of body.plan.rows) {
          if(!byPath.has(await fsp.realpath(row.video)) || !byPath.has(await fsp.realpath(row.cover))) return send(res,400,{error:'文件未经过扫描，请重新扫描后保存'});
        }
        const saved=await saveBatch(root,body.plan);
        return send(res,200,{ok:true,id:saved.id,json:saved.json,markdown:saved.markdown});
      }
      if(pathname === '/api/publish' && req.method === 'POST') {
        const body = await readBody(req);
        if(publishing)return send(res,409,{error:'本轮发布正在提交，请勿重复点击。'});
        publishing=true;
        try {
        const driverStatus=runtime ? await runtime.status() : null;
        if(!driverStatus?.available || !driverStatus.capabilities?.publish) return send(res,503,{ok:false,error:driverStatus?.message || 'WorkBuddy 网页执行连接尚未就绪；请先保存清单，不会创建虚假的发布队列。'});
        if(driverStatus.activeJob)return send(res,409,{error:'已有 WorkBuddy 任务，请先核对本轮结果。'});
        if(driverStatus.assistantModel!==body.plan?.execution?.model)return send(res,409,{error:'顶部模型与 WorkBuddy 本地助理模型不一致，请先调整。'});
        const errors = validatePlan(body.plan);
        if(errors.length) return send(res,400,{error:errors.join('；')});
        for(const row of body.plan.rows) {
          if(!byPath.has(await fsp.realpath(row.video)) || !byPath.has(await fsp.realpath(row.cover))) return send(res,400,{error:'文件未经过扫描，请重新扫描后再发布'});
        }
        const saved=await saveBatch(root,body.plan,'planned');
        const job=await runtime.start({kind:'publish',plan:body.plan,batchId:saved.id,model:body.plan.execution?.model,manifest:saved.markdown});
        return send(res,202,{ok:true,id:saved.id,json:saved.json,markdown:saved.markdown,job,rows:body.plan.rows.length});
        } finally {publishing=false;}
      }
      if(pathname === '/api/queue' && req.method === 'GET') {
        const todo = path.join(root,'output','待发布.json');
        try { return send(res,200,JSON.parse(await fsp.readFile(todo,'utf8'))); }
        catch { return send(res,200,{status:'empty'}); }
      }
      if(!['GET','HEAD'].includes(req.method)) return send(res,405,{error:'不支持此方法'});
      if(pathname.startsWith('/api/media/')) {
        const file=media.get(pathname.slice('/api/media/'.length));
        if(!file) return send(res,404,{error:'预览已失效，请重新扫描'});
        return await streamFile(req,res,file);
      }
      const staticFiles = new Set(['/index.html','/app.mjs','/plan-core.mjs','/portal.css','/portal.mjs','/favicon.ico']);
      const route = pathname === '/' ? '/index.html' : pathname;
      if(!staticFiles.has(route)) return send(res,404,{error:'文件不存在'});
      return await streamFile(req,res,path.join(staticRoot,route));
    } catch(err) {
      if(res.headersSent) return res.destroy();
      return send(res,err.status || (err.code === 'ENOENT' ? 404 : err instanceof URIError ? 400 : 500),{error:err.code === 'ENOENT' ? '文件已移动或删除，请重新扫描' : err.message});
    }
  });
  return server;
}

export async function startConfigured(options={}) {
  const config=await loadConfiguration(options);
  const root=config.workspace;
  const driver=createWorkBuddyRunner({root,expectedAccount:config.expectedAccount});
  const runtime=createRuntimeService({root,driver});
  const server=createWorkbenchServer({root,runtime,preferences:config});
  server.on('error',()=>{console.error('工作台服务启动失败，请核对端口和配置。');process.exitCode=1;});
  server.on('close',()=>runtime.close());
  server.listen(8713,'127.0.0.1',()=>{runtime.startPolling();console.log('视频号工作台：http://127.0.0.1:8713');});
  return server;
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const index=process.argv.indexOf('--config');
  await startConfigured({configFile:index>=0?process.argv[index+1]:undefined}).catch(()=>{console.error('请先配置个人 profile 的 publishing.channels.config_file；工作目录必须在核心之外。');process.exitCode=1;});
}
