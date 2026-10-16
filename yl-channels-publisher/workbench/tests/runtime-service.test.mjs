import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {createRuntimeService} from '../runtime-service.mjs';
import {saveBatch,publicationHistory} from '../publish-history.mjs';
import {createWorkbenchServer} from '../server.mjs';

async function fixture(t,kind){
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'channels-reconcile-'));
  t.after(async()=>{assert.ok(path.resolve(root).startsWith(path.resolve(os.tmpdir())+path.sep));await fs.rm(root,{recursive:true,force:true});});
  const id=randomUUID(),jobDir=path.join(root,'output','workbuddy-jobs',id);
  await fs.mkdir(jobDir,{recursive:true});
  const job={id,kind,jobDir,state:'running',results:[]};
  await fs.writeFile(path.join(jobDir,'job.json'),JSON.stringify(job));
  const driver={poll:async()=>job,status:async()=>({activeJob:job.state==='completed'?null:{id,kind,status:job.state},lastJob:{id,kind,status:job.state}})};
  const service=extra=>createRuntimeService({root,driver,summary:async()=>({latestCapturedAt:'2026-10-12T10:09:03+08:00'}),...extra});
  const finish=async value=>{job.state='completed';await fs.writeFile(path.join(jobDir,'result.json'),JSON.stringify(value));};
  return {root,job,driver,service,finish};
}

test('逐条回执幂等归档，重启后保留已成功条目并按平台ID归并',async t=>{
  const f=await fixture(t,'publish');
  const saved=await saveBatch(f.root,{date:'2099-01-01',rows:[{seq:1,title:'第一条标题',video:'one.mp4',time:'08:00'},{seq:2,title:'第二条标题',video:'two.mp4',time:'09:00'}]},'queued');
  f.job.batchId=saved.id;
  f.job.results=[{seq:1,state:'scheduled',platformId:'99999999999999999999',observedAt:new Date().toISOString(),evidence:'validated-screenshot'},{seq:2,state:'unknown'}];
  await f.service().reconcile();await f.service().reconcile();
  let h=await publicationHistory(f.root,{posts:[{id:'99999999999999999999',title:'相同作品',publishedAt:'2099-01-01T08:00:00+08:00'}]});
  assert.equal(h.summary.historicalPosts,0);assert.equal(h.summary.confirmedWorkbenchPosts,1);
  assert.equal((await fs.readdir(path.join(f.root,'data','receipts'))).length,2);
  f.job.results[1]={seq:2,state:'failed'};await f.finish({items:f.job.results});await f.service().reconcile();
  h=await publicationHistory(f.root);assert.equal(h.batches[0].counts.failed,1);assert.equal(h.batches[0].counts.scheduled,1);
});

test('未完成采集不导入；完整回执重启后只导入一次，导入失败明确返回',async t=>{
  const f=await fixture(t,'capture');let imports=0;
  const ingest=async()=>{imports++;};
  await f.service({ingest}).reconcile();assert.equal(imports,0);
  await f.finish({status:'partial'});
  const first=await f.service({ingest}).status();assert.equal(imports,1);assert.equal(first.integration.status,'imported');
  const second=await f.service({ingest}).status();assert.equal(imports,1);assert.equal(second.lastCaptureAt,'2026-10-12T10:09:03+08:00');
  await f.finish({status:'partial',revision:2});
  const rejected=await f.service({ingest:async()=>{throw new Error('PRIVATE RAW CONTENT');}}).status();
  assert.equal(rejected.integration.status,'rejected');assert.ok(!JSON.stringify(rejected).includes('PRIVATE RAW CONTENT'));
});

test('并发状态刷新不会重复入库',async t=>{
  const f=await fixture(t,'capture');await f.finish({status:'complete'});let imports=0;
  const service=f.service({ingest:async()=>{imports++;}});
  await Promise.all([service.status(),service.status(),service.status()]);assert.equal(imports,1);
});

test('文件暂时不可用时自动重试本轮归档，不会重新启动采集',async t=>{
  const f=await fixture(t,'capture');await f.finish({status:'complete'});let attempts=0,now=100000;
  const service=f.service({clock:()=>now,ingest:async()=>{if(++attempts===1)throw new Error('temporary lock');}});
  assert.equal((await service.status()).integration.status,'rejected');assert.equal(attempts,1);
  await service.status();assert.equal(attempts,1);now+=30001;
  assert.equal((await service.status()).integration.status,'imported');assert.equal(attempts,2);
});

test('解锁接口需要明确确认，配置和授权状态走适配器且不泄漏私有字段',async t=>{
  const f=await fixture(t,'connection-check');let acknowledges=0;
  f.driver.acknowledge=async(id,body)=>{assert.equal(id,f.job.id);assert.equal(body.confirmed,true);acknowledges++;return {released:true};};
  const runtime=f.service(),server=createWorkbenchServer({root:f.root,runtime});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>server.close(r)));
  const base='http://127.0.0.1:'+server.address().port;
  const post=body=>fetch(base+'/api/workbuddy/acknowledge',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  assert.equal((await post({id:f.job.id})).status,400);assert.equal(acknowledges,0);
  assert.equal((await post({id:f.job.id,confirmed:true})).status,200);assert.equal(acknowledges,1);
  assert.equal((await fetch(base+'/output/workbuddy-jobs/'+f.job.id+'/job.json')).status,404);
});
