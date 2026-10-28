import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createWorkBuddyRunner} from '../workbuddy-runner.mjs';

const temporary=[];
const fakeProtect=async(op,input)=>op==='protect'?Buffer.from(input).toString('base64'):Buffer.from(input,'base64').toString();
async function setup(){
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'channels-official-adapter-'));temporary.push(root);
  const calls=[];let mode='normal';
  const fetchImpl=async(url,options)=>{calls.push({url,options});
    if(mode==='network-failure'&&options.method==='POST'&&url.endsWith('/message'))throw new Error('secret-must-not-escape');
    if(mode==='auth-failure'&&options.method==='POST'&&url.endsWith('/message'))return {ok:false,status:401,json:async()=>({error:'invalid_token'})};
    let data=url.endsWith('/token')?{access_token:'TEST_ACCESS',refresh_token:'TEST_REFRESH',expires_in:3600,scope:'user.localassistant.readable user.localassistant.invokable'}
      :url.endsWith('/localassistant')?{code:0,data:{online:true}}
      :options.method==='POST'?{code:0,data:{message_id:'official-message-001'}}
      :{code:0,data:{messages:[{message_id:'reply',role:'assistant',msg_type:'text',content:['任务已完成，发布成功']}]}};
    return {ok:true,status:200,json:async()=>data};
  };
  const opts={root,expectedAccount:"Test Account",secretFile:path.join(root,'secrets.dpapi'),protect:fakeProtect,fetchImpl},runner=createWorkBuddyRunner(opts);
  return {root,calls,runner,opts,setMode:v=>mode=v};
}
async function authorize(ctx){
  await ctx.runner.configure({clientId:'TEST_CLIENT',clientSecret:'TEST_SECRET',assistantModel:'Space Bunny'});
  const info=await ctx.runner.connect(),url=new URL(info.authorizeUrl);
  await ctx.runner.callback({code:'TEST_CODE',state:url.searchParams.get('state')});return url;
}
async function verify(ctx){
  const job=await ctx.runner.start({kind:'connection-check',model:'Space Bunny'}),folder=path.join(ctx.root,'output','workbuddy-jobs',job.id),image=path.join(folder,'connection.png');
  await fs.writeFile(image,'test-fixture-image');
  await fs.writeFile(path.join(folder,'result.json'),JSON.stringify({jobId:job.id,kind:'connection-check',status:'completed',connection:{verified:true,account:'Test Account',model:'Space Bunny',evidence:image}}));
  assert.equal((await ctx.runner.poll(job.id)).state,'completed');return folder;
}
async function publicationFixture(){
  const c=await setup();await authorize(c);await verify(c);
  const manifest=path.join(c.root,'plan.md');await fs.writeFile(manifest,'test');
  const job=await c.runner.start({kind:'publish',model:'Space Bunny',manifest,plan:{date:'2026-10-17',rows:[{seq:1,video:path.join(os.tmpdir(),'receipt.mp4'),time:'10:00',goods:'A'}]}});
  const folder=path.join(c.root,'output','workbuddy-jobs',job.id),evidence=path.join(folder,'proof.png');await fs.writeFile(evidence,'fixture');
  const item={seq:1,video:path.join(os.tmpdir(),'receipt.mp4'),at:'2026-10-17 10:00',actualAt:'2026-10-17 10:00',goods:'A',state:'scheduled',platformId:'confirmed-platform-id',observedAt:new Date().toISOString(),evidence};
  const write=async(name,receipt)=>fs.writeFile(path.join(folder,name+'.json'),JSON.stringify({jobId:job.id,kind:'publish',items:[receipt]}));
  return {...c,job,item,write};
}

test('wrong or absent observed schedule cannot be promoted to a successful publication',async()=>{
  for(const actualAt of [null,'2026-10-17 13:00','2026-10-18 10:00']){
    const c=await publicationFixture();await c.write('result',{...c.item,actualAt});
    const result=await c.runner.poll(c.job.id);
    assert.equal(result.state,'attention');assert.equal(result.platformVerified,false);
    assert.equal(result.results[0].state,'unknown');assert.equal(result.results[0].actualAt,actualAt);
    assert.match(result.results[0].note,/日期或时间/);
    assert.equal((await c.runner.status()).activeJob.id,c.job.id);
    // Correcting the receipt for the same task resolves the mismatch, without another submission.
    const submissions=c.calls.filter(call=>call.options.method==='POST'&&call.url.endsWith('/message')).length;
    await c.write('result',c.item);
    assert.equal((await c.runner.poll(c.job.id)).platformVerified,true);
    assert.equal(c.calls.filter(call=>call.options.method==='POST'&&call.url.endsWith('/message')).length,submissions);
  }
});
test('a later conflicting schedule retains prior facts but keeps the task pending review',async()=>{
  const c=await publicationFixture();await c.write('progress',c.item);await c.runner.poll(c.job.id);
  await c.write('result',{...c.item,actualAt:'2026-10-17 13:00'});
  const result=await c.runner.poll(c.job.id);
  assert.equal(result.results[0].platformId,c.item.platformId);
  assert.equal(result.results[0].actualAt,c.item.actualAt);
  assert.equal(result.results[0].conflictingActualAt,'2026-10-17 13:00');
  assert.equal(result.platformVerified,false);assert.equal(result.state,'attention');
  assert.equal((await c.runner.status()).activeJob.id,c.job.id);
});
test('unconfigured driver does not invent a queue or expose secrets',async()=>{
  const c=await setup(),s=await c.runner.status();assert.equal(s.available,false);assert.equal(s.capabilities.publish,false);
  await assert.rejects(c.runner.start({kind:'publish'}),e=>e.status===503);assert.equal(c.calls.length,0);
  assert.equal(await fs.stat(path.join(c.root,'output')).catch(()=>null),null);
});
test('OAuth state and PKCE, protected storage, callback replay rejection',async()=>{
  const c=await setup();await c.runner.configure({clientId:'TEST_CLIENT',clientSecret:'TEST_SECRET'});
  const info=await c.runner.connect(),u=new URL(info.authorizeUrl);assert.equal(u.origin,'https://www.workbuddy.cn');assert.equal(u.pathname,'/openapi/v2/authorize');assert.equal(u.searchParams.get('code_challenge_method'),'S256');
  await assert.rejects(c.runner.callback({code:'X',state:'wrong'}),e=>e.code==='WORKBUDDY_OAUTH_STATE');assert.equal(c.calls.length,0);
  const state=u.searchParams.get('state');await c.runner.callback({code:'OK',state});
  const body=new URLSearchParams(c.calls[0].options.body);assert.equal(body.get('client_secret'),'TEST_SECRET');assert.ok(body.get('code_verifier'));
  await assert.rejects(c.runner.callback({code:'OK',state}),e=>e.code==='WORKBUDDY_OAUTH_STATE');
  const s=JSON.stringify(await c.runner.status());for(const secret of ['TEST_SECRET','TEST_ACCESS','TEST_REFRESH'])assert.equal(s.includes(secret),false);
  assert.equal((await fs.readFile(c.opts.secretFile,'utf8')).includes('TEST_SECRET'),false);
});
test('online alone is not a Channels connection, and requested model is enforced',async()=>{
  const c=await setup();await authorize(c);const s=await c.runner.status();assert.equal(s.online,true);assert.equal(s.capabilities.connectionCheck,true);assert.equal(s.capabilities.publish,false);assert.equal(s.capabilities.capture,false);
  await assert.rejects(c.runner.start({kind:'connection-check',model:'GLM 5.3 Flash'}),e=>e.code==='WORKBUDDY_MODEL_MISMATCH');
  await verify(c);const ready=await c.runner.status();assert.equal(ready.capabilities.capture,true);assert.equal(ready.capabilities.publish,true);
});
test('official submit sends text only and assistant prose cannot prove publication',async()=>{
  const c=await setup();await authorize(c);await verify(c);
  const manifest=path.join(c.root,'plan.md');await fs.writeFile(manifest,'test');
  const job=await c.runner.start({kind:'publish',model:'Space Bunny',batchId:'b1',manifest,plan:{date:'2026-10-17',rows:[{video:path.join(os.tmpdir(),'video.mp4'),time:'10:00'}]}});
  assert.equal(job.remoteMessageId,'official-message-001');assert.equal(job.state,'submitted');
  const post=c.calls.filter(c=>c.options.method==='POST'&&c.url.endsWith('/message')).at(-1),body=JSON.parse(post.options.body);assert.deepEqual(Object.keys(body).sort(),['content','msg_type']);
  const result=await c.runner.poll(job.id);assert.equal(result.state,'submitted');assert.equal(result.platformVerified,false);
  await assert.rejects(c.runner.start({kind:'capture'}),e=>e.code==='WORKBUDDY_BUSY');
  const reloaded=createWorkBuddyRunner(c.opts);assert.equal((await reloaded.status()).activeJob.id,job.id);
});
test('ambiguous POST is retained and not silently retried',async()=>{
  const c=await setup();await authorize(c);c.setMode('network-failure');
  await assert.rejects(c.runner.start({kind:'connection-check',model:'Space Bunny'}),e=>e.code==='WORKBUDDY_TRANSPORT'&&!e.message.includes('secret-must-not-escape'));
  assert.ok((await c.runner.status()).activeJob);
  assert.equal(c.calls.filter(c=>c.url.endsWith('/message')&&c.options.method==='POST').length,1);
});
test('capture prompt and result use importer contract',async()=>{
  const c=await setup();await authorize(c);await verify(c);const job=await c.runner.start({kind:'capture',model:'Space Bunny'});
  const post=c.calls.filter(c=>c.options.method==='POST'&&c.url.endsWith('/message')).at(-1),content=JSON.parse(post.options.body).content;assert.ok(content.includes("files:{posts:'posts.json'}"));assert.ok(content.includes('paginationExhausted'));
  const folder=path.join(c.root,'output','workbuddy-jobs',job.id);await fs.writeFile(path.join(folder,'result.json'),JSON.stringify({jobId:job.id,kind:'capture',status:'partial',files:{posts:'posts.json',bad:'../outside.json'}}));
  const result=await c.runner.poll(job.id);assert.deepEqual(result.captureFiles,[path.join(folder,'posts.json')]);assert.equal(result.platformVerified,false);
});
test('progress matches repeated videos by schedule and rejects missing platform evidence',async()=>{
  const c=await setup();await authorize(c);await verify(c);const manifest=path.join(c.root,'plan.md');await fs.writeFile(manifest,'test');
  const job=await c.runner.start({kind:'publish',model:'Space Bunny',manifest,plan:{date:'2026-10-17',rows:[{seq:1,video:path.join(os.tmpdir(),'same.mp4'),time:'10:00',goods:'A'},{seq:2,video:path.join(os.tmpdir(),'same.mp4'),time:'12:00',goods:'B'}]}});
  const folder=path.join(c.root,'output','workbuddy-jobs',job.id),evidence=path.join(folder,'proof.png');await fs.writeFile(evidence,'fixture');
  const item={seq:1,video:path.join(os.tmpdir(),'same.mp4'),at:'2026-10-17 10:00',actualAt:'2026-10-17 10:00',goods:'A',state:'scheduled',platformId:'real-id-1',observedAt:new Date().toISOString(),evidence};
  await fs.writeFile(path.join(folder,'progress.json'),JSON.stringify({jobId:job.id,kind:'publish',items:[item]}));
  let result=await c.runner.poll(job.id);assert.equal(result.state,'running');assert.equal(result.results[0].state,'scheduled');assert.equal(result.results[1].state,'unknown');assert.equal('messages' in result,false);
  await fs.writeFile(path.join(folder,'result.json'),JSON.stringify({jobId:job.id,kind:'publish',items:[{...item,seq:2,at:'2026-10-17 12:00',goods:'B',platformId:''}]}));
  result=await c.runner.poll(job.id);assert.equal(result.results[0].state,'scheduled');assert.equal(result.results[1].state,'unknown');assert.equal(result.platformVerified,false);assert.equal(result.state,'attention');
  assert.equal((await c.runner.status()).activeJob.id,job.id);assert.equal((await createWorkBuddyRunner(c.opts).status()).activeJob.id,job.id);
  await assert.rejects(c.runner.start({kind:'capture'}),e=>e.code==='WORKBUDDY_BUSY');
});
test('invalid or weaker final receipts cannot erase confirmed scheduled facts',async()=>{
  const c=await publicationFixture();await c.write('progress',c.item);await c.runner.poll(c.job.id);
  for(const patch of [{evidence:''},{observedAt:null},{platformId:''},{state:'failed'},{state:'reviewing'}]){
    await c.write('result',{...c.item,...patch});const result=await c.runner.poll(c.job.id),receipt=result.results[0];
    assert.equal(receipt.state,'scheduled');assert.equal(receipt.platformId,c.item.platformId);assert.equal(receipt.evidence,c.item.evidence);assert.equal(receipt.observedAt,c.item.observedAt);assert.ok(receipt.reviewNote);assert.equal(result.platformVerified,true);
  }
  const restored=await createWorkBuddyRunner(c.opts).poll(c.job.id);assert.equal(restored.results[0].platformId,c.item.platformId);assert.equal(restored.results[0].state,'scheduled');
});
test('a valid published receipt cannot be downgraded by a valid scheduled final receipt',async()=>{
  const c=await publicationFixture();await c.write('progress',{...c.item,state:'published'});await c.runner.poll(c.job.id);
  await c.write('result',c.item);const result=await c.runner.poll(c.job.id);
  assert.equal(result.results[0].state,'published');assert.equal(result.results[0].platformId,c.item.platformId);assert.ok(result.results[0].reviewNote);assert.equal(result.state,'completed');
});
test('a valid final published receipt upgrades scheduled only for the same platform ID',async()=>{
  const c=await publicationFixture();await c.write('progress',c.item);await c.runner.poll(c.job.id);
  await c.write('result',{...c.item,state:'published'});const result=await c.runner.poll(c.job.id);
  assert.equal(result.results[0].state,'published');assert.equal(result.results[0].platformId,c.item.platformId);assert.equal(result.results[0].reviewNote,undefined);assert.equal(result.platformVerified,true);
  // Re-reading the older progress snapshot must not create a spurious downgrade warning.
  assert.equal((await c.runner.poll(c.job.id)).results[0].reviewNote,undefined);
});
test('a conflicting platform ID is an annotation and cannot replace a confirmed publication',async()=>{
  const c=await publicationFixture();await c.write('progress',c.item);await c.runner.poll(c.job.id);
  await c.write('result',{...c.item,state:'published',platformId:'different-platform-id'});const result=await c.runner.poll(c.job.id);
  assert.equal(result.results[0].state,'scheduled');assert.equal(result.results[0].platformId,c.item.platformId);assert.ok(result.results[0].reviewNote.includes('ID'));assert.equal(result.platformVerified,true);
});
test('unpolled valid progress survives an invalid final snapshot on the first poll',async()=>{
  const c=await publicationFixture();await c.write('progress',c.item);await c.write('result',{...c.item,evidence:''});
  const result=await c.runner.poll(c.job.id);assert.equal(result.results[0].state,'scheduled');assert.equal(result.results[0].platformId,c.item.platformId);assert.ok(result.results[0].reviewNote);assert.equal(result.platformVerified,true);
});
test('matched failed result is recorded but stays locked until explicit acknowledgement',async()=>{
  const c=await setup();await authorize(c);await verify(c);const manifest=path.join(c.root,'plan.md');await fs.writeFile(manifest,'test');
  const job=await c.runner.start({kind:'publish',model:'Space Bunny',manifest,plan:{date:'2026-10-17',rows:[{seq:1,video:path.join(os.tmpdir(),'failed.mp4'),time:'10:00',goods:null}]}});
  const folder=path.join(c.root,'output','workbuddy-jobs',job.id);await fs.writeFile(path.join(folder,'result.json'),JSON.stringify({jobId:job.id,kind:'publish',items:[{seq:1,video:path.join(os.tmpdir(),'failed.mp4'),at:'2026-10-17 10:00',goods:null,state:'failed'}]}));
  const result=await c.runner.poll(job.id);assert.equal(result.results[0].state,'failed');assert.equal(result.results[0].verifiedAbsent,false);assert.equal(result.platformVerified,false);assert.equal((await c.runner.status()).activeJob.id,job.id);
  await c.runner.acknowledge(job.id,{confirmed:true});assert.equal((await c.runner.status()).activeJob,null);assert.equal((await c.runner.poll(job.id)).results[0].state,'failed');
});
test('acknowledge requires explicit confirmation and preserves unknown result',async()=>{
  const c=await setup();await authorize(c);c.setMode('network-failure');await assert.rejects(c.runner.start({kind:'connection-check',model:'Space Bunny'}));
  const id=(await c.runner.status()).activeJob.id;await assert.rejects(c.runner.acknowledge(id),e=>e.status===400);
  const ack=await c.runner.acknowledge(id,{confirmed:true});assert.equal(ack.state,'unknown');assert.equal((await c.runner.status()).activeJob,null);
  assert.equal((await createWorkBuddyRunner(c.opts).status()).activeJob,null);
});
test('new configuration or authorization cannot reuse old connection proof',async()=>{
  const c=await setup();await authorize(c);const folder=await verify(c),id=path.basename(folder),cacheFile=path.join(c.root,'output','workbuddy-jobs','connection.json'),oldProof=await fs.readFile(cacheFile,'utf8');
  await c.runner.configure({clientId:'DIFFERENT_APP',clientSecret:'OTHER_TEST_SECRET',assistantModel:'Space Bunny'});
  assert.equal(await fs.stat(cacheFile).catch(()=>null),null);
  const info=await c.runner.connect();await c.runner.callback({code:'NEW_AUTH',state:new URL(info.authorizeUrl).searchParams.get('state')});
  // Even a stale cache restored from disk cannot authorize the new configuration.
  await fs.writeFile(cacheFile,oldProof);const reloaded=createWorkBuddyRunner(c.opts);
  assert.equal((await reloaded.status()).channelsConnection,'unverified');await reloaded.poll(id);assert.equal((await reloaded.status()).capabilities.publish,false);
});
test('restored proof requires expected account, model, and existing evidence',async()=>{
  const c=await setup();await authorize(c);const folder=await verify(c),cacheFile=path.join(c.root,'output','workbuddy-jobs','connection.json'),proof=JSON.parse(await fs.readFile(cacheFile,'utf8'));
  for(const patch of [{account:'其他账号'},{model:'GLM 5.3 Flash'},{evidence:path.join(folder,'missing.png')}]){
    await fs.writeFile(cacheFile,JSON.stringify({...proof,...patch}));assert.equal((await createWorkBuddyRunner(c.opts).status()).channelsConnection,'unverified');
  }
  await fs.writeFile(cacheFile,JSON.stringify(proof));assert.equal((await createWorkBuddyRunner(c.opts).status()).channelsConnection,'verified');
  await fs.unlink(proof.evidence);assert.equal((await c.runner.status()).channelsConnection,'unverified');
});
test('officially rejected submission is shown as not executed',async()=>{
  const c=await setup();await authorize(c);c.setMode('auth-failure');await assert.rejects(c.runner.start({kind:'connection-check',model:'Space Bunny'}),e=>e.code==='WORKBUDDY_AUTH_REQUIRED');
  const s=await c.runner.status();assert.equal(s.activeJob,null);assert.equal(s.lastJob.status,'rejected');assert.ok(s.lastJob.summary.includes('任务未执行'));assert.equal(s.lastJob.summary.includes('正在'),false);
});
test.after(async()=>{for(const target of temporary){assert.ok(path.resolve(target).startsWith(path.resolve(os.tmpdir())+path.sep));await fs.rm(target,{recursive:true,force:true});}});
