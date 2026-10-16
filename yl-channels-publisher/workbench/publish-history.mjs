import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash, randomUUID} from 'node:crypto';
import {toMarkdown} from './plan-core.mjs';

const confirmed = new Set(['published','scheduled']);
const safeStatus = value => ['planned','queued','running','published','scheduled','failed','unknown','blocked'].includes(value) ? value : 'unknown';
const hash = value => createHash('sha256').update(value).digest('hex').slice(0,24);
const stamp = () => new Date().toISOString();
async function readJson(file) { return JSON.parse((await fs.readFile(file,'utf8')).replace(/^\uFEFF/,'')); }

// A manifest is a plan, never evidence that the platform accepted it.
export async function saveBatch(root, plan, status='planned') {
  const id=randomUUID(), createdAt=stamp();
  const outDir=path.join(root,'output');
  await fs.mkdir(outDir,{recursive:true});
  const base=`发布清单_${plan.date}_${plan.rows.length}条_${Date.now()}_${id.slice(0,8)}`;
  const json=path.join(outDir,base+'.json'), markdown=path.join(outDir,base+'.md');
  const record={schemaVersion:3,batchId:id,status,createdAt,plan};
  await fs.writeFile(json,JSON.stringify(record,null,2),{encoding:'utf8',flag:'wx'});
  try { await fs.writeFile(markdown,toMarkdown(plan),{encoding:'utf8',flag:'wx'}); }
  catch(error) { await fs.unlink(json).catch(()=>{}); throw error; }
  return {id,json,markdown,record};
}

export async function listManifestRecords(root) {
  const dir=path.join(root,'output');
  let files; try {files=await fs.readdir(dir);} catch(e){if(e.code==='ENOENT')return [];throw e;}
  const records=[];
  for(const file of files.filter(f=>f.endsWith('.json') && f!=='待发布.json')) {
    try {
      const record=await readJson(path.join(dir,file));
      if(!Array.isArray(record.plan?.rows))continue;
      records.push({...record,batchId:record.batchId || 'legacy-'+hash(file),file});
    } catch { /* Incomplete or unrelated files are not promoted to publication records. */ }
  }
  return records;
}

export async function appendReceipt(root, receipt) {
  // This is for an authorized runner, never for interpreting a model's free-form success text.
  if(!receipt || typeof receipt.batchId!=='string' || !Number.isInteger(receipt.seq))throw new Error('发布回执缺少轮次或条目');
  const batch=(await listManifestRecords(root)).find(b=>b.batchId===receipt.batchId);
  if(!batch || !batch.plan.rows.some((r,i)=>(r.seq??i+1)===receipt.seq))throw new Error('发布回执对应的条目不存在');
  const status=safeStatus(receipt.status);
  if(confirmed.has(status) && (typeof receipt.platformId!=='string' || !receipt.platformId.trim() || !receipt.observedAt || !Number.isFinite(Date.parse(receipt.observedAt)) || !receipt.evidence)) throw new Error('成功回执需要作品标识、核对时间及证据');
  const dir=path.join(root,'data','receipts'); await fs.mkdir(dir,{recursive:true});
  const entry={...receipt,status,recordedAt:stamp()};
  const file=path.join(dir,receipt.receiptId ? `receipt-${hash(String(receipt.receiptId))}.json` : `${Date.now()}-${randomUUID()}.json`);
  try {await fs.writeFile(file,JSON.stringify(entry,null,2),{flag:'wx'});}
  catch(error){if(error.code==='EEXIST' && receipt.receiptId)return readJson(file);throw error;}
  return entry;
}

async function receipts(root) {
  const dir=path.join(root,'data','receipts'); let files;
  try {files=await fs.readdir(dir);} catch(e){if(e.code==='ENOENT')return [];throw e;}
  const rows=[];
  for(const file of files.filter(f=>f.endsWith('.json'))) {try{rows.push(await readJson(path.join(dir,file)));}catch{}}
  return rows.sort((a,b)=>String(a.recordedAt).localeCompare(String(b.recordedAt)));
}

export async function confirmedPublicationIds(root) {
  const latest=latestReceipts(await receipts(root));
  return new Set([...latest.values()].filter(e=>confirmed.has(e.status)&&typeof e.platformId==='string'&&e.platformId&&e.observedAt&&e.evidence).map(e=>e.platformId));
}

function latestReceipts(events) {
  const latest=new Map();
  for(const event of events){
    const key=`${event.batchId}/${event.seq}`,previous=latest.get(key);
    // A later incomplete message cannot erase a verified submission fact.
    if(confirmed.has(previous?.status) && (!confirmed.has(event.status) || previous.status==='published'&&event.status==='scheduled'))continue;
    latest.set(key,event);
  }
  return latest;
}

async function submissionStates(root) {
  const result=new Map(),folder=path.join(root,'output','workbuddy-jobs');
  for(const name of await fs.readdir(folder).catch(()=>[])){
    if(!/^[0-9a-f-]{36}$/i.test(name))continue;
    const job=await readJson(path.join(folder,name,'job.json')).catch(()=>null);
    if(job?.kind==='publish'&&job.batchId)result.set(job.batchId,job.state);
  }
  return result;
}

function counts(rows) {return Object.fromEntries(['published','scheduled','failed','unknown','planned','queued','running','blocked'].map(k=>[k,rows.filter(r=>r.status===k).length]));}
function batchStatus(rows) {
  const states=new Set(rows.map(r=>r.status));
  if(states.size===1)return rows[0]?.status || 'planned';
  if(states.has('running'))return 'running';
  if(states.has('unknown'))return 'unknown';
  if(states.has('failed') || states.has('blocked'))return 'partial';
  if([...states].every(s=>confirmed.has(s)))return 'completed';
  return 'partial';
}

export async function publicationHistory(root, analytics={posts:[]}) {
  const [records, events, jobs]=await Promise.all([listManifestRecords(root),receipts(root),submissionStates(root)]);
  const latest=latestReceipts(events);
  const matchedIds=new Set();
  const batches=records.map(b=>{
    const rows=b.plan.rows.map((r,i)=>{
      const seq=r.seq??i+1, event=latest.get(`${b.batchId}/${seq}`);
      // Legacy queued files have no executor or receipt. They remain pending confirmation.
      const jobState=jobs.get(b.batchId);
      const submittedState=jobState ? ({submitted:'queued',running:'running',rejected:'blocked'}[jobState]||'unknown') : b.status==='planned'?'planned':'unknown';
      let status=event ? safeStatus(event.status) : submittedState;
      if(confirmed.has(status) && !(typeof event?.platformId==='string' && event.platformId && event.observedAt && event.evidence))status='unknown';
      if(confirmed.has(status))matchedIds.add(event.platformId);
      return {id:`${b.batchId}/${seq}`,seq,title:r.title || '未填写标题',time:r.time,goods:r.goods||null,status,platformId:event?.platformId||null,error:event?.error||null,observedAt:event?.observedAt||null};
    });
    return {id:b.batchId,createdAt:b.createdAt,date:b.plan.date,status:batchStatus(rows),origin:'workbench',count:rows.length,counts:counts(rows),rows,model:b.plan.execution?.model || 'Space Bunny'};
  });
  const groups=new Map();
  for(const p of analytics.posts || []) {
    const platformId=p.platformId || p.id;
    if(platformId && matchedIds.has(platformId))continue;
    const date=String(p.publishedAt||p.date||'日期未知').slice(0,10);
    if(!groups.has(date))groups.set(date,[]);
    groups.get(date).push({id:p.id || p.publication_id,seq:0,title:p.title,time:String(p.publishedAt||'').slice(11,16),status:'published',platformId:platformId||null,goods:null,visibility:p.visibility,origin:'historical',capturedAt:p.latestCapturedAt});
  }
  for(const [date,rows] of groups) {
    rows.sort((a,b)=>String(a.time).localeCompare(String(b.time))).forEach((r,i)=>r.seq=i+1);
    batches.push({id:'historical-'+date,createdAt:date,date,status:'published',origin:'historical',count:rows.length,counts:counts(rows),rows,model:null,note:'历史作品按发布日期归组；原始发布轮次及发布入口未记录。'});
  }
  batches.sort((a,b)=>String(b.createdAt||b.date).localeCompare(String(a.createdAt||a.date)));
  return {batches,summary:{totalBatches:batches.filter(b=>b.origin==='workbench').length,historicalDays:groups.size,historicalPosts:[...groups.values()].reduce((n,r)=>n+r.length,0),confirmedWorkbenchPosts:batches.filter(b=>b.origin==='workbench').reduce((n,b)=>n+b.counts.published+b.counts.scheduled,0)},note:'保存清单不等于发表；历史导入按日期展示，不能还原未知的原始轮次。'};
}
