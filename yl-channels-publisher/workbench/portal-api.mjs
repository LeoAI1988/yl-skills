import fs from 'node:fs/promises';
import path from 'node:path';
import {loadAnalytics,listPosts,postDetail,analyticsSummary,refreshHistory} from './analytics-store.mjs';
import {publicationHistory} from './publish-history.mjs';

const inactive={driver:'WorkBuddy',available:false,capabilities:{publish:false,capture:false},activeJob:null,message:'WorkBuddy 网页执行连接尚未就绪；可独立使用排期、发布记录和历史数据。'};
export function createPortalApi({root,send,readBody,streamFile,runtime}) {
  const state=async()=>({...inactive,...(runtime ? await runtime.status() : {})});
  return async function portalApi(req,res,url) {
    const pathname=decodeURIComponent(url.pathname), params=Object.fromEntries(url.searchParams);
    if(req.method==='POST' && pathname==='/api/workbuddy/config') {
      if(!runtime?.configure){send(res,503,{error:'WorkBuddy 连接模块未加载'});return true;}
      send(res,200,await runtime.configure(await readBody(req)));return true;
    }
    if(req.method==='POST' && pathname==='/api/workbuddy/connect') {
      await readBody(req);
      if(!runtime?.connect){send(res,503,{error:'WorkBuddy 连接模块未加载'});return true;}
      send(res,200,await runtime.connect());return true;
    }
    if(req.method==='POST' && pathname==='/api/workbuddy/check') {
      const body=await readBody(req);
      if(!runtime?.start){send(res,503,{error:'WorkBuddy 连接模块未加载'});return true;}
      const job=await runtime.start({kind:'connection-check',model:body.model});
      send(res,202,{ok:true,job,message:'正在只读核对 WorkBuddy 的视频号连接与账号。'});return true;
    }
    if(req.method==='POST' && pathname==='/api/workbuddy/acknowledge') {
      const body=await readBody(req);
      if(!runtime?.acknowledge){send(res,503,{error:'WorkBuddy 连接模块未加载'});return true;}
      if(body.confirmed!==true || typeof body.id!=='string'){send(res,400,{error:'请先明确确认该任务在 WorkBuddy 中已停止或完成。'});return true;}
      send(res,200,await runtime.acknowledge(body.id,{confirmed:true}));return true;
    }
    if(req.method==='GET' && pathname==='/auth/workbuddy/callback') {
      let ok=false;
      try {if(!runtime?.callback)throw new Error();await runtime.callback(params);ok=true;}catch{}
      res.writeHead(ok?200:400,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"});
      res.end(`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>WorkBuddy 连接</title><body style="font:16px/1.8 system-ui;background:#faf8f4;color:#26231e;padding:10vh 8vw"><h1>${ok?'WorkBuddy 授权已完成':'本次授权尚未完成'}</h1><p>${ok?'请回到工作台检查视频号连接；确认账号后即可从网页启动任务。':'请回到工作台重新生成授权链接，并核对应用回调地址及授权范围。'}</p><a href="/">返回视频号工作台</a></body></html>`);return true;
    }
    if(req.method==='GET' && pathname==='/api/runtime') {send(res,200,await state());return true;}
    if(req.method==='GET' && pathname==='/api/history') {send(res,200,await publicationHistory(root,await loadAnalytics(root)));return true;}
    if(req.method==='GET' && pathname==='/api/analytics/summary') {send(res,200,await analyticsSummary(root));return true;}
    if(req.method==='GET' && pathname==='/api/analytics/posts') {send(res,200,await listPosts(root,params));return true;}
    if(req.method==='GET' && pathname.startsWith('/api/analytics/posts/')) {
      const post=await postDetail(root,pathname.slice('/api/analytics/posts/'.length));
      send(res,post?200:404,post || {error:'未找到这条作品'});return true;
    }
    if(req.method==='POST' && pathname==='/api/analytics/reload') {
      await readBody(req);
      const result=await refreshHistory(root);
      send(res,200,{...result,ok:true,message:'已重读已登记的本地采集数据；采集时间保留原值。'});return true;
    }
    if(req.method==='POST' && pathname==='/api/analytics/refresh') {
      const body=await readBody(req), status=await state();
      if(!status.available || !status.capabilities?.capture){send(res,503,{ok:false,error:status.message});return true;}
      const job=await runtime.start({kind:'capture',model:body.model});
      send(res,202,{ok:true,job,message:'已开始后台采集，完成后更新数据。'});return true;
    }
    if(req.method==='GET' && pathname==='/api/analytics/export') {
      const data=await loadAnalytics(root);
      const date=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
      const format=params.format==='csv'?'csv':'json';
      res.setHeader('Content-Disposition',`attachment; filename="channels-${date}.${format}"`);
      res.setHeader('Cache-Control','no-store');
      res.setHeader('X-Content-Type-Options','nosniff');
      if(format==='json') {
        res.setHeader('Content-Type','application/json; charset=utf-8');
        res.end(JSON.stringify(data,null,2));
      } else {
        const keys=[...new Set((data.posts||[]).flatMap(p=>Object.keys(p.metrics||{})))];
        const cell=v=>{let s=v===null||v===undefined?'':String(v);if(typeof v==='string' && /^[\s]*[=+@-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
        const fields=['id','title','publishedAt','visibility','contentType','latestCapturedAt','captureStatus'];
        const rows=[['作品标识','标题','发布时间','可见性','内容类型','实际采集时间','覆盖状态',...keys],...(data.posts||[]).map(p=>[...fields.map(k=>p[k]),...keys.map(k=>p.metrics?.[k])])];
        res.setHeader('Content-Type','text/csv; charset=utf-8');
        res.end('\uFEFF'+rows.map(r=>r.map(cell).join(',')).join('\r\n'));
      }
      return true;
    }
    if(['GET','HEAD'].includes(req.method) && pathname==='/reports/current') {
      const file=path.join(root,'data','review.html');
      try {await fs.access(file);} catch{send(res,404,{error:'复盘大屏尚未生成，请先重读历史数据'});return true;}
      res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'");
      res.setHeader('Referrer-Policy','no-referrer');
      await streamFile(req,res,file);return true;
    }
    return false;
  };
}
