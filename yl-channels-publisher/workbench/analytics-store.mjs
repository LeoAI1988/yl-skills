import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const CODE=path.dirname(fileURLToPath(import.meta.url));
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import * as publicationHistory from './publish-history.mjs';

const run = promisify(execFile);
const caches = new Map();
const imports = new Map();

async function annotateOrigins(root,value) {
  const ids=typeof publicationHistory.confirmedPublicationIds==='function'
    ? await publicationHistory.confirmedPublicationIds(root) : new Set();
  const posts=value.posts.map(p=>({...p,origin:ids.has(p.id || p.publication_id)?'workbench':'historical'}));
  return {...value,posts,summary:{...value.summary,workbenchPostCount:posts.filter(p=>p.origin==='workbench').length,
    historicalPostCount:posts.filter(p=>p.origin==='historical').length}};
}

export async function loadAnalytics(root) {
  const base = path.resolve(root);
  // Requests during a rebuild continue using the previous completed import.
  if (imports.has(base) && caches.has(base)) return annotateOrigins(base,caches.get(base).value);
  const filename = path.join(base, 'data', 'analytics.json');
  let stat;
  try { stat = await fs.stat(filename); }
  catch (error) {
    if (error.code !== 'ENOENT') throw error;
    return {schemaVersion:1,importedAt:null,captures:[],coverage:[{item:'历史资料',status:'not_available',reason:'尚未导入历史资料。'}],posts:[],products:[],attribution:[],summary:{postCount:0,latestPostCount:0,latestCapturedAt:null,liveRefreshAvailable:false}};
  }
  const cache = caches.get(base);
  if (cache && cache.mtimeMs === stat.mtimeMs && cache.size === stat.size) return annotateOrigins(base,cache.value);
  const value = JSON.parse(await fs.readFile(filename, 'utf8'));
  if (value.schemaVersion !== 1 || !Array.isArray(value.posts)) throw new Error('历史资料格式不受支持');
  caches.set(base, {mtimeMs:stat.mtimeMs,size:stat.size,value});
  return annotateOrigins(base,value);
}

function queryValue(query, key) {
  return String(typeof query?.get === 'function' ? query.get(key) ?? '' : query?.[key] ?? '').trim();
}

function pageInteger(value, fallback, max) {
  if (!/^\d+$/.test(value)) return fallback;
  return Math.max(1, Math.min(max, Number(value)));
}

export async function listPosts(root, query = {}) {
  const data = await loadAnalytics(root);
  let items = data.posts;
  const search = (queryValue(query, 'q') || queryValue(query, 'search')).toLocaleLowerCase();
  if (search) items = items.filter(p => `${p.title}\n${p.description || ''}`.toLocaleLowerCase().includes(search));
  for (const [key, field] of [['visibility','visibility'],['contentType','contentType'],['origin','origin'],['captureStatus','captureStatus'],['topic','topic']]) {
    const value = queryValue(query, key);
    if (value && value !== 'all') items = items.filter(p => p[field] === value);
  }
  const from = queryValue(query, 'from'), to = queryValue(query, 'to');
  if (/^\d{4}-\d{2}-\d{2}$/.test(from)) items = items.filter(p => p.publishedAt.slice(0,10) >= from);
  if (/^\d{4}-\d{2}-\d{2}$/.test(to)) items = items.filter(p => p.publishedAt.slice(0,10) <= to);
  const product = queryValue(query, 'productId');
  if (product && product !== 'all') items = items.filter(p => p.attribution?.some(a => a.product_id === product));
  if (queryValue(query, 'hasSales') === 'true') items = items.filter(p => p.attribution?.length);
  const allowedSorts = new Set(['publishedAt','latestCapturedAt','title','views','likes','comments','shares','recommendations','follows','completionPct','threeSecPct','watchSeconds','durationSeconds']);
  const sort = allowedSorts.has(queryValue(query, 'sort')) ? queryValue(query, 'sort') : 'publishedAt';
  const direction = queryValue(query, 'direction') === 'asc' || queryValue(query, 'order') === 'asc' ? 1 : -1;
  items = [...items].sort((a,b) => {
    const av = ['publishedAt','latestCapturedAt','title'].includes(sort) ? a[sort] : a.metrics[sort];
    const bv = ['publishedAt','latestCapturedAt','title'].includes(sort) ? b[sort] : b.metrics[sort];
    if (av == null) return bv == null ? a.id.localeCompare(b.id) : 1;
    if (bv == null) return -1;
    const delta = typeof av === 'number' ? av-bv : String(av).localeCompare(String(bv), 'zh-CN');
    return delta*direction || b.publishedAt.localeCompare(a.publishedAt) || a.id.localeCompare(b.id);
  });
  const total = items.length;
  const pageSize = pageInteger(queryValue(query,'pageSize'),25,200);
  const page = pageInteger(queryValue(query,'page'),1,Math.max(1,Math.ceil(total/pageSize)));
  // Full manuscripts and complete snapshot history belong in the per-work detail response.
  const visible = items.slice((page-1)*pageSize,page*pageSize).map(({transcript,snapshots,...item}) => ({...item,transcriptAvailable:!!transcript?.full,snapshotCount:snapshots?.length || 0}));
  return {items:visible,total,page,pageSize,latestCapturedAt:data.summary.latestCapturedAt,coverage:data.coverage};
}

export async function postDetail(root, id) {
  if (typeof id !== 'string') return null;
  const data = await loadAnalytics(root);
  return data.posts.find(p => p.id === id) || null;
}

export async function analyticsSummary(root) {
  const data = await loadAnalytics(root);
  return {...data.summary, importedAt:data.importedAt, captures:data.captures, coverage:data.coverage,
    products:data.products, attribution:data.attribution, accountDaily:data.accountDaily || [], metricNotes:data.metricNotes || {},
    attributionReferences:data.attributionReferences || {}};
}

export async function refreshHistory(root) {
  const base = path.resolve(root);
  if (imports.has(base)) return imports.get(base);
  // Load the last completed result before acquiring the in-process rebuild lock.
  await loadAnalytics(base);
  if (imports.has(base)) return imports.get(base);
  const task = runImport(base,[],false);
  imports.set(base,task);
  try { return await task; }
  finally { if(imports.get(base)===task) imports.delete(base); }
}

async function runImport(base,args,isCapture) {
  const config = JSON.parse(await fs.readFile(path.join(base,'analytics-config.json'),'utf8'));
  try {
    const {stdout} = await run(config.python,['-B','-X','utf8',config.importer||path.join(CODE,'scripts','import-history.py'),'--root',base,...args],
      {cwd:base,windowsHide:true,timeout:180000,maxBuffer:1024*1024,encoding:'utf8'});
    const result = JSON.parse(stdout.trim().split(/\r?\n/).at(-1));
    caches.delete(base);
    return result;
  } catch (error) {
    // Never send collector stderr or raw customer data to the browser.
    const message=isCapture?'本轮采集未通过导入校验，旧数据和快照仍保留。':'本地资料重新整理失败，旧数据仍保留。';
    throw new Error(error.killed?'资料整理超时，旧数据仍保留。':message,{cause:error});
  }
}

export async function ingestCapture(root,jobDir) {
  const base=path.resolve(root);
  if(typeof jobDir!=='string' || !path.isAbsolute(jobDir)) throw new Error('采集工作目录必须是完整路径。');
  await loadAnalytics(base);
  // Unlike local re-imports, distinct real capture jobs must queue, never coalesce away.
  const previous=imports.get(base);
  const task=(async()=>{
    if(previous) {try {await previous;} catch {/* A failed previous job must not swallow this capture. */}}
    return runImport(base,['--ingest',path.resolve(jobDir)],true);
  })();
  imports.set(base,task);
  try{return await task;}
  finally{if(imports.get(base)===task) imports.delete(base);}
}
