import {test} from 'node:test';
import assert from 'node:assert/strict';
import {publishAvailability, workBuddyHandoff} from '../plan-core.mjs';

const ready={configured:true,authorized:true,online:true,available:true,assistantModel:'Space Bunny',capabilities:{publish:true,connectionCheck:true}};
test('handoff uses the exact saved batch and retains plan settings without mutation',()=>{
  const saved={id:'batch-latest',markdown:'/plans/latest.md',json:'/plans/latest.json'};
  const plan={date:'2099-10-17',execution:{model:'GLM 5.3 Flash'},rows:[{time:'11:00',goods:'Product A'},{time:'20:00',goods:'Product B'}]};
  const before=JSON.stringify(plan);
  const prompt=workBuddyHandoff(saved,plan);
  for(const value of [...Object.values(saved),plan.date,'共 2 条','GLM 5.3 Flash','不需要等待开放平台应用审核','避免重复发布','不擅自顺延','保存清单不等于发布成功'])assert.ok(prompt.includes(value),value);
  assert.equal(JSON.stringify(plan),before);
});
test('handoff cannot be generated for an unsaved or incomplete manifest',()=>{
  for(const saved of [null,{}, {id:'old',json:'old.json'}, {markdown:'old.md',json:'old.json'}])assert.throws(()=>workBuddyHandoff(saved,{}),/清单尚未保存/);
});
test('missing authorization offers setup without permitting a publish',()=>{
  const result=publishAvailability({...ready,authorized:false},'Space Bunny');
  assert.equal(result.ready,false);
  assert.equal(result.disabled,false);
  assert.equal(result.action,'connect');
  assert.match(result.reason,/尚未完成.*授权/);
});
test('each unmet prerequisite blocks publication even with a stale publish capability',()=>{
  for(const change of [{configured:false},{authorized:false},{online:false},{available:false},{assistantModel:null},{assistantModel:'GLM 5.3 Flash'},{capabilities:{publish:false,connectionCheck:true}}]){
    const result=publishAvailability({...ready,...change},'Space Bunny');
    assert.equal(result.ready,false,JSON.stringify(change));
    assert.equal(result.action,'connect');
    assert.equal(result.disabled,false);
  }
  assert.equal(publishAvailability(null,'Space Bunny').ready,false);
});
test('active, unknown and submitting tasks remain locked against duplicate submission',()=>{
  for(const state of ['submitted','running','unknown','attention']){
    const result=publishAvailability({...ready,activeJob:{state}},'Space Bunny');
    assert.equal(result.ready,false);assert.equal(result.disabled,true);
  }
  for(const options of [{publishing:true},{awaitingStatus:true}]){
    const result=publishAvailability(ready,'Space Bunny',options);
    assert.equal(result.ready,false);assert.equal(result.disabled,true);
  }
});
test('verified connection and matching model enable the real publish action',()=>{
  const result=publishAvailability(ready,'Space Bunny');
  assert.equal(result.ready,true);assert.equal(result.action,'publish');assert.equal(result.disabled,false);
});
