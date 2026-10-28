const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(__dirname+'/web/app.js','utf8');
const fn=src.slice(src.indexOf('async function api('),src.indexOf('\nfunction toast('));
async function scenario(responses){
 const calls=[],meta={content:'old'};
 const ctx={fetch:async(url,opts)=>{calls.push({url,token:opts?.headers?.['X-CSRF-Token']});const next=responses.shift();if(next instanceof Error)throw next;return {ok:next.status===200,status:next.status,json:async()=>next.data};},$:()=>meta,performance:{now:()=>0}};
 vm.createContext(ctx);vm.runInContext(fn+';this.call=api;',ctx);
 let error,result;try{result=await ctx.call('publish',{confirmed:true});}catch(e){error=e.message;}
 return {calls,meta,error,result};
}
(async()=>{
 let r=await scenario([{status:403,data:{code:'csrf_expired'}},{status:200,data:{csrf_token:'fresh'}},{status:200,data:{result:'accepted'}}]);
 assert.equal(r.result,'accepted');assert.equal(r.calls.length,3);assert.equal(r.calls[2].token,'fresh');
 for(const entry of [{status:403,data:{code:'origin_rejected',error:'wrong origin'}},{status:400,data:{error:'bad request'}},new Error('network disconnected')]){
  r=await scenario([entry]);assert.equal(r.calls.length,1);assert.ok(r.error);
 }
 r=await scenario([{status:403,data:{code:'csrf_expired'}},{status:200,data:{csrf_token:'fresh'}},{status:403,data:{code:'csrf_expired',error:'still expired'}}]);
 assert.equal(r.calls.length,3);assert.equal(r.error,'still expired');
 r=await scenario([{status:403,data:{code:'csrf_expired'}},{status:200,data:{}}]);assert.equal(r.calls.length,2);assert.ok(r.error);
 console.log('6 session recovery cases passed; no ambiguous request retried');
})().catch(e=>{console.error(e);process.exitCode=1;});
