import {test} from 'node:test';
import assert from 'node:assert/strict';
import {originalDecision,toMarkdown,moveSlot} from '../plan-core.mjs';

test('short original exception retains the request and reason, without rounding across five seconds',()=>{
  const short=originalDecision(true,4.999);
  assert.equal(short.original,false);assert.equal(short.originalRequested,true);
  assert.match(short.originalReason,/不足 5 秒/);
  assert.equal(originalDecision(true,5).original,true);
  assert.equal(originalDecision(false,12).original,false);
  for(const duration of [null,undefined,NaN,Infinity,0,-1,'4.9']){
    const result=originalDecision(true,duration);
    assert.equal(result.durationSeconds,null);assert.equal(result.original,true);
    assert.match(result.originalReason,/未取得/);
  }
});
test('moving video settings retains originality decision and leaves time slots fixed',()=>{
  const rows=[{time:'11:00',video:'short.mp4',...originalDecision(true,4.9)},{time:'14:00',video:'long.mp4',...originalDecision(true,8.2)}];
  const moved=moveSlot(rows,0,1);
  assert.equal(moved[1].video,'short.mp4');assert.equal(moved[1].time,'14:00');
  assert.equal(moved[1].original,false);assert.equal(moved[1].durationSeconds,4.9);
  const md=toMarkdown({date:'2099-10-17',rows:moved});
  assert.match(md,/不足 5 秒/);assert.match(md,/主表单完整日期和时间/);assert.match(md,/不得从计划复制实际值/);
});
