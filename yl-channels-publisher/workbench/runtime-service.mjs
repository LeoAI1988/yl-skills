import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {appendReceipt} from './publish-history.mjs';
import {ingestCapture,analyticsSummary} from './analytics-store.mjs';

const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const read=async file=>JSON.parse(await fs.readFile(file,'utf8'));
async function write(file,value){const temp=file+'.'+randomUUID()+'.tmp';await fs.writeFile(temp,JSON.stringify(value,null,2));await fs.rename(temp,file);}

// Reconcile only jobs already submitted by an explicit workbench action. Never start a task here.
export function createRuntimeService({root,driver,ingest=ingestCapture,summary=analyticsSummary,clock=()=>Date.now()}) {
  const jobRoot=path.join(root,'output','workbuddy-jobs');
  let syncing=null, timer=null, lastState=null;
  async function reconcile() {
    if(syncing)return syncing;
    syncing=(async()=>{
      const dirs=await fs.readdir(jobRoot,{withFileTypes:true}).catch(e=>{if(e.code==='ENOENT')return [];throw e;});
      for(const dir of dirs){
        if(!dir.isDirectory() || !/^[0-9a-f-]{36}$/i.test(dir.name))continue;
        const folder=path.join(jobRoot,dir.name),meta=await read(path.join(folder,'job.json')).catch(()=>null);
        if(!meta || meta.id!==dir.name)continue;
        const file=path.join(folder,'integration.json');
        let integration=await read(file).catch(()=>({jobId:meta.id,receipts:{}}));
        const final=await fs.readFile(path.join(folder,'result.json'),'utf8').catch(()=>null);
        const fingerprint=final===null?null:digest(final);
        const unchanged=integration.finalFingerprint===fingerprint;
        const retry=unchanged&&integration.status==='rejected'&&(integration.attempts||0)<3&&clock()>=(integration.nextRetryAt||0);
        if(unchanged && fingerprint && integration.finished && !retry)continue;
        const job=await driver.poll(meta.id);
        if(job.kind==='publish'){
          for(const item of job.results||[]){
            const status=['published','scheduled','failed'].includes(item.state)?item.state:'unknown';
            const receipt={batchId:job.batchId,seq:item.seq,status,platformId:item.platformId||null,observedAt:item.observedAt||null,evidence:item.evidence||null,error:item.reviewNote?'后续回执存在差异，已保留此前核验的发布结果；请核对 WorkBuddy 中的说明。':status==='failed'?'本条执行失败，请核对 WorkBuddy 中的结果。':status==='unknown'?'本条尚未取得完整后台回执。':null};
            const key=digest(receipt);
            if(integration.receipts?.[item.seq]===key)continue;
            await appendReceipt(root,{...receipt,receiptId:job.id+'/'+item.seq+'/'+key});
            integration.receipts={...integration.receipts,[item.seq]:key};
          }
        }
        if(job.kind==='capture' && job.state==='completed' && fingerprint && (!unchanged||retry)){
          integration.attempts=(unchanged?integration.attempts||0:0)+1;
          try {await ingest(root,job.jobDir);integration.status='imported';integration.message='本轮有效采集已入库，列表与复盘大屏已更新。';}
          catch {integration.status='rejected';integration.nextRetryAt=clock()+30000;integration.message=integration.attempts<3?'本轮采集尚未完成入库，原有数据仍保留；稍后会自动重试归档。':'本轮采集未通过导入校验，原有数据仍保留。请在 WorkBuddy 核对结果后重新采集。';}
        }
        integration={...integration,jobId:job.id,finalFingerprint:fingerprint,finished:!!fingerprint&&['completed','attention'].includes(job.state),updatedAt:new Date().toISOString()};
        await write(file,integration);
      }
    })();
    try{await syncing;}finally{syncing=null;}
  }
  async function status(force=false){
    let syncError=false;
    try{await reconcile();}catch{syncError=true;}
    const state=await driver.status(force), job=state.activeJob||state.lastJob;
    const integration=job?.id?await read(path.join(jobRoot,job.id,'integration.json')).catch(()=>null):null;
    const data=await summary(root);
    lastState={...state,lastCaptureAt:data.latestCapturedAt||null,
      integration:integration?.status?{jobId:job.id,status:integration.status,message:integration.message}:null,
      ...(syncError?{integration:{jobId:job?.id||null,status:'rejected',message:'本轮回执暂未完成归档；原有数据保留，请稍后刷新核对。'}}:{})};
    return lastState;
  }
  return {status,reconcile,
    configure:body=>driver.configure(body),connect:()=>driver.connect(),callback:body=>driver.callback(body),
    start:async body=>{await reconcile();return driver.start(body);},
    acknowledge:async (id,body)=>{await reconcile();return driver.acknowledge(id,body);},
    startPolling(){if(!timer){timer=setInterval(()=>void status().catch(()=>{}),15000);timer.unref();}},
    close(){if(timer)clearInterval(timer);timer=null;}
  };
}
