import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {saveBatch,appendReceipt,publicationHistory} from '../publish-history.mjs';
import {createWorkbenchServer} from '../server.mjs';

const plan={date:'2099-12-01',count:2,rows:[{seq:1,title:'这是一条真实标题',video:'one.mp4',cover:'one.png',time:'08:00'},{seq:2,title:'这是第二条标题',video:'two.mp4',cover:'two.png',time:'10:00'}]};
test('历史轮次持久保存，未取得回执不推断发布成功',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'channels-history-'));
  try{
    const first=await saveBatch(root,plan), second=await saveBatch(root,plan,'queued');
    assert.notEqual(first.id,second.id);
    let h=await publicationHistory(root);
    assert.equal(h.batches.find(b=>b.id===first.id).status,'planned');
    assert.equal(h.batches.find(b=>b.id===second.id).status,'unknown');
    assert.equal(h.summary.confirmedWorkbenchPosts,0);
    await assert.rejects(()=>appendReceipt(root,{batchId:first.id,seq:1,status:'published'}));
    await assert.rejects(()=>appendReceipt(root,{batchId:first.id,seq:9,status:'failed'}));
    await appendReceipt(root,{batchId:first.id,seq:1,status:'scheduled',platformId:'99999999999999999999',observedAt:new Date().toISOString(),evidence:'fixture-platform-screenshot'});
    h=await publicationHistory(root,{posts:[{id:'99999999999999999999',platformId:'99999999999999999999',publishedAt:'2099-12-01T08:00:00+08:00',title:'相同标题'},{id:'other',publishedAt:'2099-12-01T09:00:00+08:00',title:'相同标题',visibility:'hidden'}]});
    assert.equal(h.summary.confirmedWorkbenchPosts,1);
    assert.equal(h.summary.historicalPosts,1);
    assert.equal(h.batches.find(b=>b.origin==='historical').rows[0].visibility,'hidden');
    assert.equal(h.batches.find(b=>b.id===first.id).rows[0].platformId,'99999999999999999999');
    // A process reopening the same root gets the same record identities.
    assert.equal((await publicationHistory(root)).batches.find(b=>b.id===first.id).rows[0].status,'scheduled');
    await appendReceipt(root,{batchId:first.id,seq:1,status:'unknown'});
    assert.equal((await publicationHistory(root)).batches.find(b=>b.id===first.id).rows[0].status,'scheduled');
  }finally{await fs.rm(root,{recursive:true,force:true});}
});

test('忙碌或模型不匹配的发布请求不创建批次',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'channels-gate-'));
  const state={available:true,capabilities:{publish:true},assistantModel:'Space Bunny',activeJob:{id:'busy'}};
  const server=createWorkbenchServer({root,runtime:{status:async()=>state}});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const base=`http://127.0.0.1:${server.address().port}`;
  const post=()=>fetch(base+'/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan:{...plan,execution:{model:'GLM 5.3 Flash'}}})});
  try{assert.equal((await post()).status,409);state.activeJob=null;assert.equal((await post()).status,409);await assert.rejects(()=>fs.access(path.join(root,'output')));}
  finally{await new Promise(r=>server.close(r));assert.ok(root.startsWith(os.tmpdir()+path.sep));await fs.rm(root,{recursive:true,force:true});}
});

test('无连接时不创建假发布队列，门户保持本机读取边界',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'channels-api-'));
  const server=createWorkbenchServer({root});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const base=`http://127.0.0.1:${server.address().port}`;
  try{
    let r=await fetch(base+'/api/runtime');assert.equal((await r.json()).available,false);
    r=await fetch(base+'/api/history');assert.equal((await r.json()).batches.length,0);
    r=await fetch(base+'/api/analytics/posts');assert.equal((await r.json()).total,0);
    r=await fetch(base+'/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan})});assert.equal(r.status,503);
    await assert.rejects(()=>fs.access(path.join(root,'output')));
    r=await fetch(base+'/api/history',{headers:{Origin:'https://example.invalid'}});assert.equal(r.status,403);
    r=await fetch(base+'/analytics-config.json');assert.equal(r.status,404);
    r=await fetch(base+'/data/analytics.json');assert.equal(r.status,404);
    r=await fetch(base+'/api/analytics/posts/not-found');assert.equal(r.status,404);
  }finally{await new Promise(r=>server.close(r));await fs.rm(root,{recursive:true,force:true});}
});
