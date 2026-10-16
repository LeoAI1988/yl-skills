/** Official WorkBuddy Local Assistant adapter. No desktop credential extraction. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const MEMBER=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');

const BASE='https://www.workbuddy.cn/openapi/v2';
const SCOPES=['user.localassistant.readable','user.localassistant.invokable'];
const CALLBACK='http://127.0.0.1:8713/auth/workbuddy/callback';
const fail=(message,status=503,code='WORKBUDDY_NOT_READY')=>Object.assign(new Error(message),{status,code});
const exists=async p=>!!p && !!(await fs.stat(p).catch(()=>null))?.isFile();
const inside=(base,file)=>{const r=path.relative(base,file);return r!==''&&!r.startsWith('..'+path.sep)&&r!=='..'&&!path.isAbsolute(r);};
const redactStatus=(error)=>error?.code==='WORKBUDDY_AUTH_REQUIRED'?'WorkBuddy 授权已失效，请重新连接。':'暂时无法连接 WorkBuddy，请稍后重试。';

// Secrets only cross stdin/stdout between this server and its hidden DPAPI helper.
// They never appear in process arguments, HTTP status responses, or application logs.
export function windowsDpapi(mode,input) {
  if(process.platform!=='win32') return Promise.reject(fail('本机缺少 Windows 凭据加密支持。'));
  if(!['protect','unprotect'].includes(mode)) return Promise.reject(new Error('Invalid protection operation'));
  const action=mode==='protect'
    ? '$bytes=[Text.Encoding]::UTF8.GetBytes($inputData);$sealed=[Security.Cryptography.ProtectedData]::Protect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser);[Console]::Out.Write([Convert]::ToBase64String($sealed))'
    : '$bytes=[Convert]::FromBase64String($inputData);$plain=[Security.Cryptography.ProtectedData]::Unprotect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser);[Console]::Out.Write([Text.Encoding]::UTF8.GetString($plain))';
  const command='$ErrorActionPreference="Stop";Add-Type -AssemblyName System.Security;$inputData=[Console]::In.ReadToEnd();'+action;
  return new Promise((resolve,reject)=>{
    const child=spawn('powershell.exe',['-NoProfile','-NonInteractive','-Command',command],{windowsHide:true,stdio:['pipe','pipe','pipe']});
    let output='',done=false;const timer=setTimeout(()=>{child.kill();finish(fail('凭据加密服务未及时响应。'));},10000);
    function finish(error){if(done)return;done=true;clearTimeout(timer);error?reject(error):resolve(output);}
    child.stdout.on('data',b=>{output+=b.toString('utf8');if(output.length>1024*1024){child.kill();finish(fail('凭据文件超出大小限制。'));}});
    child.stderr.resume();child.on('error',()=>finish(fail('无法启动 Windows 凭据加密服务。')));
    child.on('close',code=>finish(code===0?null:fail('无法解锁本机 WorkBuddy 授权，请重新连接。')));
    child.stdin.on('error',()=>{});child.stdin.end(input,'utf8');
  });
}

export function createWorkBuddyRunner({root,expectedAccount,fetchImpl=globalThis.fetch,protect=windowsDpapi,
  secretFile=path.join(os.homedir(),'.config','yl-toolbox','publishing','workbuddy-openapi.dpapi'),clock=()=>Date.now()}={}) {
  if(!root)throw new Error('root is required');
  if(typeof expectedAccount!=='string'||!expectedAccount.trim())throw new Error('请在个人配置中指定预期视频号账号');
  root=path.resolve(root);const jobRoot=path.join(root,'output','workbuddy-jobs');
  let vaultPromise=null,authPending=null,live=null,active=null,submitting=false,refreshing=null;
  const jobs=new Map();let connection=null,recovery=null;
  const configurationFingerprint=v=>crypto.createHash('sha256').update(JSON.stringify([v.clientId||'',v.assistantModel||'',v.configurationId||'',v.authorizationId||''])).digest('hex');
  function recover(){
    if(recovery)return recovery;recovery=(async()=>{
    for(const dir of await fs.readdir(jobRoot,{withFileTypes:true}).catch(()=>[])){
      if(!dir.isDirectory()||!/^[0-9a-f-]{36}$/i.test(dir.name))continue;
      const job=await loadJob(dir.name).catch(()=>null);
      if(job&&!job.trackingReleasedAt&&['submitting','submitted','running','unknown','attention'].includes(job.state))active=job.id;
    }
    try{const c=JSON.parse(await fs.readFile(path.join(jobRoot,'connection.json'),'utf8'));if(await verifiedEvidence(c.folder,c.evidence))connection=c;}catch{}
    })();return recovery;
  }
  async function vault(){
    if(!vaultPromise)vaultPromise=(async()=>{
      try {const text=await fs.readFile(secretFile,'utf8');return JSON.parse(await protect('unprotect',text));}
      catch(e){if(e.code==='ENOENT')return {};throw fail('无法读取本机 WorkBuddy 授权，请重新配置。');}
    })();
    return vaultPromise;
  }
  async function save(value){
    const ciphertext=await protect('protect',JSON.stringify(value));
    await fs.mkdir(path.dirname(secretFile),{recursive:true});
    const temp=secretFile+'.'+crypto.randomUUID()+'.tmp';
    await fs.writeFile(temp,ciphertext,{encoding:'utf8',mode:0o600});
    await fs.rename(temp,secretFile);vaultPromise=Promise.resolve(value);live=null;
  }
  async function request(route,{method='GET',token,body,form=false}={}){
    let response;
    try{response=await fetchImpl(BASE+route,{method,headers:{Accept:'application/json',...(token?{Authorization:'Bearer '+token}:{}),...(body?{'Content-Type':form?'application/x-www-form-urlencoded':'application/json'}:{})},body:body?(form?new URLSearchParams(body).toString():JSON.stringify(body)):undefined,signal:AbortSignal.timeout(15000),redirect:'error'});}
    catch{throw fail('WorkBuddy 连接暂时中断；请先核对任务记录，再决定是否重试。',503,'WORKBUDDY_TRANSPORT');}
    let data;try{data=await response.json();}catch{throw fail('WorkBuddy 返回了无法识别的结果。');}
    if(!response.ok || (data.code!==undefined && data.code!==0)){
      const auth=[401,403].includes(response.status)||['invalid_grant','invalid_token','access_denied','forbidden'].includes(data.error);
      throw fail(auth?'WorkBuddy 授权未完成或已失效，请重新连接。':'WorkBuddy 暂时未接受请求，请稍后核对。',auth?401:502,auth?'WORKBUDDY_AUTH_REQUIRED':'WORKBUDDY_API_ERROR');
    }
    return data;
  }
  async function access(){
    let v=await vault();if(!v.accessToken)throw fail('请先完成 WorkBuddy 官方授权。',401,'WORKBUDDY_AUTH_REQUIRED');
    if(v.expiresAt && v.expiresAt<=clock()+60000){
      if(refreshing)return refreshing;
      refreshing=(async()=>{
      if(!v.refreshToken)throw fail('WorkBuddy 授权已到期，请重新连接。',401,'WORKBUDDY_AUTH_REQUIRED');
      const r=await request('/token',{method:'POST',form:true,body:{grant_type:'refresh_token',refresh_token:v.refreshToken,client_id:v.clientId,client_secret:v.clientSecret}});
      if(!r.access_token)throw fail('WorkBuddy 未返回有效授权，请重新连接。',401,'WORKBUDDY_AUTH_REQUIRED');
      v={...v,accessToken:r.access_token,refreshToken:r.refresh_token||v.refreshToken,expiresAt:clock()+Number(r.expires_in||3600)*1000,scope:r.scope||v.scope};await save(v);return v;
      })();try{return await refreshing;}finally{refreshing=null;}
    }
    return v;
  }
  async function configure({clientId,clientSecret,redirectUri=CALLBACK,assistantModel=''}={}){
    await recover();if(active||submitting)throw fail('请先核对本轮任务，再修改连接设置。',409);
    if(typeof clientId!=='string'||!clientId.trim()||typeof clientSecret!=='string'||!clientSecret.trim())throw fail('请填写开放平台应用 ID 和应用密钥。',400);
    if(clientId.length>512||clientSecret.length>8192)throw fail('应用配置长度异常。',400);
    let uri;try{uri=new URL(redirectUri);}catch{throw fail('授权回调地址格式不正确。',400);}
    if(uri.username||uri.password||uri.hash||uri.search||!(['https:'].includes(uri.protocol)||(uri.protocol==='http:'&&['127.0.0.1','localhost'].includes(uri.hostname))))throw fail('回调地址须使用 HTTPS 或本机回环地址。',400);
    if(assistantModel&&!['Space Bunny','GLM 5.3 Flash','DeepSeek v4.1 Flash'].includes(assistantModel))throw fail('请选择工作台支持的模型。',400);
    const v={clientId:clientId.trim(),clientSecret:clientSecret.trim(),redirectUri:uri.href,assistantModel:String(assistantModel||'').trim(),configurationId:crypto.randomUUID()};
    await save(v);authPending=null;connection=null;
    await fs.unlink(path.join(jobRoot,'connection.json')).catch(e=>{if(e.code!=='ENOENT')throw fail('连接配置已更新，请重新进行视频号连接检查。');});
    return {configured:true,redirectUri:v.redirectUri,assistantModel:v.assistantModel};
  }
  async function connect(){
    const v=await vault();if(!v.clientId||!v.clientSecret)throw fail('请先在 WorkBuddy 开放平台创建应用并填写应用配置。',400,'WORKBUDDY_APP_REQUIRED');
    const state=crypto.randomBytes(32).toString('base64url'),verifier=crypto.randomBytes(48).toString('base64url');
    authPending={state,verifier,expiresAt:clock()+10*60*1000};
    const u=new URL(BASE+'/authorize');u.search=new URLSearchParams({response_type:'code',client_id:v.clientId,redirect_uri:v.redirectUri||CALLBACK,scope:SCOPES.join(' '),state,code_challenge:crypto.createHash('sha256').update(verifier).digest('base64url'),code_challenge_method:'S256'}).toString();
    return {authorizeUrl:u.href,expiresAt:authPending.expiresAt,redirectUri:v.redirectUri||CALLBACK};
  }
  async function callback({code,state,error}={}){
    const p=authPending;if(!p||p.expiresAt<clock()||typeof state!=='string'||!/^[-_A-Za-z0-9]+$/.test(state)||state.length!==p.state.length||!crypto.timingSafeEqual(Buffer.from(state),Buffer.from(p.state)))throw fail('授权链接已过期或校验失败，请重新连接。',400,'WORKBUDDY_OAUTH_STATE');
    authPending=null;if(error)throw fail('WorkBuddy 授权未完成，请重新连接。',400,'WORKBUDDY_OAUTH_DECLINED');
    if(typeof code!=='string'||!code||code.length>8192)throw fail('未收到有效授权码。',400);
    const v=await vault(),r=await request('/token',{method:'POST',form:true,body:{grant_type:'authorization_code',code,redirect_uri:v.redirectUri||CALLBACK,client_id:v.clientId,client_secret:v.clientSecret,code_verifier:p.verifier}});
    if(!r.access_token)throw fail('未取得有效 WorkBuddy 授权。',401,'WORKBUDDY_AUTH_REQUIRED');
    await save({...v,accessToken:r.access_token,refreshToken:r.refresh_token||'',expiresAt:clock()+Number(r.expires_in||3600)*1000,scope:r.scope||'',authorizationId:crypto.randomUUID()});
    connection=null;
    return {connected:true,...await status(true)};
  }
  async function verifiedEvidence(folder,file){
    if(typeof folder!=='string'||typeof file!=='string'||!path.isAbsolute(file))return false;
    const actual=await fs.realpath(file).catch(()=>null),base=await fs.realpath(folder).catch(()=>null),allowed=await fs.realpath(jobRoot).catch(()=>null);
    return !!actual&&!!base&&!!allowed&&inside(allowed,base)&&inside(base,actual)&&/\.(png|jpe?g|webp)$/i.test(actual)&&(await fs.stat(actual)).size>0;
  }
  async function status(force=false){
    await recover();
    const installed=await exists(path.join(process.env.ProgramFiles||'','WorkBuddy','WorkBuddy.exe'));
    let v;try{v=await vault();}catch{return {driver:'WorkBuddy',installed,available:false,authentication:'required',channelsConnection:'unverified',capabilities:{publish:false,capture:false,connectionCheck:false},activeJob:active,message:'需重新配置 WorkBuddy 官方连接。'};}
    let online=false,auth=v.accessToken?'authorized':'required',message='需完成 WorkBuddy 官方授权及视频号连接验证。';
    if(v.accessToken){
      if(!force&&live&&clock()-live.at<15000){online=live.online;auth=live.auth;message=live.message;}
      else {try{v=await access();const result=await request('/localassistant',{token:v.accessToken});online=result.data?.online===true;message=online?'WorkBuddy 已连接，可检查视频号登录并采集数据。':'请打开 WorkBuddy 并让本地助理保持在线。';}
      catch(e){auth=e.code==='WORKBUDDY_AUTH_REQUIRED'?'required':'unverified';message=redactStatus(e);}live={online,auth,message,at:clock()};}
    }
    const scopes=new Set(String(v.scope||'').split(/\s+/)),canInvoke=SCOPES.every(s=>scopes.has(s));
    const ready=online&&auth==='authorized'&&canInvoke;
    if(online&&!canInvoke)message='WorkBuddy 授权缺少本地助理权限，请重新连接。';
    const verified=connection?.verifiedAt>clock()-24*3600*1000&&connection.verifiedAt<=clock()+60000&&connection.account===expectedAccount&&connection.model===v.assistantModel&&connection.fingerprint===configurationFingerprint(v)&&await verifiedEvidence(connection.folder,connection.evidence);
    return {driver:'WorkBuddy',transport:'official-localassistant',installed,configured:!!v.clientId,authorized:auth==='authorized',available:ready,authentication:auth,online,
      channelsConnection:verified?'verified':'unverified',capabilities:{publish:ready&&verified,capture:ready&&verified,connectionCheck:ready},activeJob:active?publicJob(jobs.get(active)):null,lastJob:publicJob([...jobs.values()].sort((a,b)=>Date.parse(b.createdAt)-Date.parse(a.createdAt))[0]),
      modelSelection:'workbuddy-assistant',assistantModel:v.assistantModel||null,requestedModels:['Space Bunny','GLM 5.3 Flash','DeepSeek v4.1 Flash'],
      message,setupUrl:'https://open.workbuddy.cn/',documentationUrl:'https://open.workbuddy.cn/docs/openapi',redirectUri:v.redirectUri||CALLBACK};
  }
  function promptFor(job){
    const result=path.join(job.folder,'result.json'),check=job.kind==='connection-check';
    const intro=`这是视频号工作台任务 ${job.id}。只处理这一个任务，禁止运行 Superpowers、读取凭据、调用隐藏接口或修改账号设置。所有浏览器操作使用 WorkBuddy 当前已授权的可见页面工具；登录/审批由用户在真实页面完成。工作目录：${job.folder}。`;
    const model=job.requestedModel?`用户指定模型 ${job.requestedModel}，思考强度极致、上下文模型默认。先核对当前助理实际配置；不能确认一致则停止并写明，不能仅声称切换。`:'';
    const evidence=`截图保存在本任务文件夹。保存结构化回执 ${result}，含 jobId:${JSON.stringify(job.id)}, kind:${JSON.stringify(job.kind)}, status:completed|attention, connection:{verified:boolean,account:string,model:实际模型名称,evidence:截图绝对路径}, note:事实说明。不得修改工作台数据库。`;
    if(check)return `${intro}\n${model}\n只读核对视频号助手是否可访问、账号和当前模型；不上传、不填发布表单、不提交、不改期、不删作品。${evidence}`;
    if(job.kind==='capture')return `${intro}\n${model}\n读取 ${path.resolve(MEMBER,'..','yl-channels-analytics','SKILL.md')} 及其任务相关个人规则，按其现行采集方法采集视频号全部作品（含隐藏作品）最新逐条指标、流量来源、留存、涨粉和有明确归因的商品成交；不做任何平台修改。保留真实采集时间、稳定平台ID、原始证据，未取得字段用null，不用0，不把历史快照当最新，不输出客户联系方式/地址/凭据。
本轮所有采集文件只放 ${job.folder}。写 posts.json={account:${JSON.stringify(expectedAccount)},captured_at:真实读取ISO时刻,total:平台明确总量或null,posts:[{objectId:字符串平台ID,createTime:Unix秒,visibleType:1或3,status,shortTitle,title,len,mediaType:4视频或2图文,readCount,likeCount,commentCount,forwardCount,favCount,fullPlayRate:0..1,avgPlayTimeSec,fastFlipRate:0..1,followCount}]}，ID绝不转Number，未知指标null。
写 ${result}={jobId:${JSON.stringify(job.id)},kind:'capture',account:${JSON.stringify(expectedAccount)},capturedAt:本轮结束ISO含时区,status:'complete'或'partial',files:{posts:'posts.json'},coverage:[{layer:'posts',status:'complete'或'partial'或'not_available',checkedCount:去重条数,expectedCount:平台明确总量或null,reason:覆盖说明}],evidence:{source:实际工具或连接名称,readOnly:true,completedAt:含时区ISO,paginationExhausted:boolean,includesHidden:boolean}}。
仅当已遍历所有分页及隐藏作品且expectedCount=checkedCount=posts.length=posts.total时用complete。部分真实数据可写partial；完全未读取到则attention且不可假造文件。files只能任务内相对路径，不可绝对路径或../；不得用旧文件改采集时间，不直接改工作台数据库。
尽量采集以下可见层，缺权限或字段则在coverage如实写未取得，不假造：
accountDaily文件={account,captured_at,range:{start:'YYYY-MM-DD',end:'YYYY-MM-DD'},fans_trend:{errCode:0,data:{add:[],reduce:[],netAdd:[],total:[]}},new_post_total_data:{errCode:0,data:{totalData:{browse:[],like:[],comment:[],forward:[],fav:[],follow:[],ringset:[],snscover:[],statusref:[],forwardAggregation:[]}}}}，各数组逐日对齐，未知用null；coverage checkedCount为自然日数。
orders文件={account,captured_at,total_orders:N,orders:[{order_id:字符串,status_str:实际状态,is_pay_done:boolean,create_time:'YYYY-MM-DD HH:mm',pay_ts:Unix秒或null,pay_price_fen:整数分,refund_fen:已取得值或null,products:[{product_id:字符串,title,cnt,sale_channel:关联账号或null}]}]}。不得采集或输出任何buyer/buyer_nick/phone/address/customer_note等客户字段。多商品订单不擅自分摊。
attribution文件={account,captured_at,rows:[{publication_id:经核实平台字符串ID,product_id:字符串,product:名称,orders:整数,amount:人民币元,scope:'platform_window_reference',evidence:官方导出或可见页面核验方式}]}，只能真实视频归因，不能用标题相似度认ID或把全店成交硬分配给视频。
files增加对应的accountDaily/orders/attribution相对文件名，每个提供层都有同名coverage条目。全部层complete且计数相符才result complete，否则partial，各层时间均为本轮实际采集时间。`;
    return `${intro}\n${model}\n用户在工作台已确认本批发布。读取 ${path.join(MEMBER,'SKILL.md')} 和 ${job.manifest}；先核对账号、已发作品和定时队列，严格按清单视频/封面/标题/标签/商品/时刻逐条执行，时间过期或结果不明立即停止该条，不改立即发布，不重复提交。每条提交前后都保存progress.json（与最终result.json同样jobId、kind与items结构），保留本批已完成条目。提交后必须回到后台核验并截图。${evidence}\n发布回执另含 items:[{seq:清单行号,video:清单原路径,at:原定日期加时刻YYYY-MM-DD HH:mm,goods:清单商品或null,platformId:真实平台字符串ID或空,observedAt:实际后台核验ISO含时区,state:scheduled|published|reviewing|failed|unknown,evidence:后台截图绝对路径,note:事实}]。同视频不同时间/商品按seq分别回执。无有效截图、ID、实际核验时间或对应关系一律unknown。任务完成不等于发布成功。`;
  }
  async function saveJob(job){await fs.mkdir(job.folder,{recursive:true});await fs.writeFile(path.join(job.folder,'job.json'),JSON.stringify(job,null,2),'utf8');}
  async function start({kind,plan,batchId,model,manifest}={}){
    await recover();
    if(!['publish','capture','connection-check'].includes(kind))throw fail('不支持此任务类型。',400);
    if(submitting||active)throw fail('已有 WorkBuddy 任务，请先核对本轮结果。',409,'WORKBUDDY_BUSY');
    submitting=true;
    try{
      const s=await status(true);if(!s.available||!s.capabilities[kind==='connection-check'?'connectionCheck':kind])throw fail(kind==='publish'&&s.available?'请先完成视频号连接检查，再提交发布。':s.message);
      model=model||s.assistantModel;
      if(!model||s.assistantModel!==model)throw fail('请先在 WorkBuddy 本地助理中选好'+(model?' '+model:'模型')+'，并在连接设置中确认同一模型。',409,'WORKBUDDY_MODEL_MISMATCH');
      if(kind==='publish'&&(!Array.isArray(plan?.rows)||!plan.rows.length||!manifest||!(await exists(manifest))))throw fail('本批发布清单不完整，请重新保存。',400);
      const id=crypto.randomUUID(),folder=path.join(jobRoot,id),job={id,kind,batchId:batchId||null,requestedModel:model||null,manifest:manifest||null,folder,state:'submitting',createdAt:new Date(clock()).toISOString(),platformVerified:false,configurationFingerprint:configurationFingerprint(await vault())};
      jobs.set(id,job);active=id;await saveJob(job);
      if(plan)await fs.writeFile(path.join(folder,'queue.json'),JSON.stringify(plan,null,2),'utf8');
      const v=await access();
      try{const result=await request('/localassistant/message',{method:'POST',token:v.accessToken,body:{content:promptFor(job),msg_type:'text'}});if(!result.data?.message_id)throw fail('WorkBuddy 未返回任务回执，请先核对本地助理。');job.remoteMessageId=result.data.message_id;job.state='submitted';await saveJob(job);}
      catch(e){job.state=e.code==='WORKBUDDY_AUTH_REQUIRED'?'rejected':'unknown';job.note=job.state==='unknown'?'提交结果尚不明确，请先核对 WorkBuddy 本地助理，避免重复。':'官方授权未通过，本任务未提交。';await saveJob(job);if(job.state==='rejected')active=null;throw e;}
      return {id,kind,batchId:job.batchId,remoteMessageId:job.remoteMessageId,state:job.state,platformVerified:false};
    }finally{submitting=false;}
  }
  async function loadJob(id){
    if(!/^[0-9a-f-]{36}$/i.test(id||''))throw fail('任务不存在。',404);
    if(jobs.has(id))return jobs.get(id);
    const folder=path.join(jobRoot,id);let job;try{job=JSON.parse(await fs.readFile(path.join(folder,'job.json'),'utf8'));}catch{throw fail('任务不存在。',404);}
    if(job.id!==id||path.resolve(job.folder)!==folder)throw fail('任务记录不一致。',409);jobs.set(id,job);return job;
  }
  function publicJob(job){return job?{id:job.id,kind:job.kind,status:job.state,summary:job.state==='completed'?'本轮执行已结束，结果已核对。':job.state==='attention'?'本轮需要核对，请查看逐条结果。':job.state==='unknown'?'提交结果不明，请先在 WorkBuddy 核对。':job.state==='rejected'?'官方未接受本轮请求，任务未执行。':'WorkBuddy 正在处理本轮任务。'}:null;}
  async function acknowledge(id,{confirmed=false}={}){
    if(!confirmed)throw fail('请先在 WorkBuddy 核对本轮已停止或已执行完毕。',400);
    const job=await loadJob(id);job.trackingReleasedAt=new Date(clock()).toISOString();await saveJob(job);if(active===id)active=null;
    return {id,released:true,state:job.state,message:'已解除本地任务锁；既有发布结果保留，WorkBuddy 中的任务不会被此操作停止。'};
  }
  async function poll(id){
    const job=await loadJob(id);
    const read=async name=>{try{const file=path.join(job.folder,name);if((await fs.stat(file)).size>2*1024*1024)return null;const r=JSON.parse(await fs.readFile(file,'utf8'));return r?.jobId===job.id&&r.kind===job.kind?r:null;}catch{return null;}};
    const result=await read('result.json'),progress=await read('progress.json');
    if(result||progress){
      const saved=await vault();
      if(job.kind==='connection-check'&&job.configurationFingerprint===configurationFingerprint(saved)&&result?.connection?.verified===true&&result.connection.account===expectedAccount&&result.connection.model&&result.connection.model===saved.assistantModel&&await verifiedEvidence(job.folder,result.connection.evidence)){
        connection={verifiedAt:Date.parse(job.createdAt),account:result.connection.account,model:result.connection.model,folder:job.folder,evidence:result.connection.evidence,fingerprint:configurationFingerprint(saved)};
        await fs.writeFile(path.join(jobRoot,'connection.json'),JSON.stringify(connection,null,2),'utf8');
      }
      if(job.kind==='publish'){
        const plan=JSON.parse(await fs.readFile(path.join(job.folder,'queue.json'),'utf8')),rows=plan.rows,items=[];
        for(let index=0;index<rows.length;index++){const row=rows[index],seq=row.seq??index+1;
          const at=row.at||row.datetime||row.publishAt||(plan.date&&row.time?plan.date+' '+row.time:row.time);
          const match=data=>(Array.isArray(data?.items)?data.items:[]).filter(i=>i.video===row.video&&i.at===at&&(i.seq===undefined||i.seq===seq));
          let merged=job.results?.find(i=>i.seq===seq)||null;
          // Merge progress before the final snapshot so even an unpolled valid receipt is retained.
          // Confirmed platform facts are monotonic; contradictory receipts are annotations only.
          for(const [source,data] of [['progress',progress],['final',result]]){
            const matches=match(data);if(!matches.length)continue;
            const item=matches.length===1?matches[0]:null;
            const observed=Date.parse(item?.observedAt||''),goodsMatches=!Object.hasOwn(row,'goods')||item?.goods===(row.goods??null);
            const good=item&&['scheduled','published','reviewing'].includes(item.state)&&typeof item.platformId==='string'&&item.platformId.trim()&&/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(item.observedAt||'')&&observed>=Date.parse(job.createdAt)-60000&&observed<=clock()+60000&&goodsMatches&&await verifiedEvidence(job.folder,item.evidence);
            if(['scheduled','published'].includes(merged?.state)){
              let reviewNote=null;
              if(!good){if(source==='final')reviewNote='最终回执缺少有效核验信息，已保留此前确认的发布结果。';}
              else if(item.platformId!==merged.platformId)reviewNote='回执的平台作品 ID 不一致，已保留此前确认的作品 ID 和发布结果。';
              else if(item.state==='reviewing'||merged.state==='published'&&item.state==='scheduled'){
                // A stale progress snapshot may legitimately precede the saved final result.
                if(source==='final')reviewNote='最终回执状态与此前确认结果不一致，已保留此前确认的发布结果。';
              }else merged={...merged,...item,seq};
              if(reviewNote)merged={...merged,reviewNote};
              continue;
            }
            const failed=item?.state==='failed'&&goodsMatches&&merged?.state!=='reviewing';
            merged=good?{...item,seq}:failed?{seq,video:row.video,at,goods:row.goods??null,state:'failed',platformId:null,verifiedAbsent:item.verifiedAbsent===true&&Number.isFinite(observed)&&observed>=Date.parse(job.createdAt)-60000&&observed<=clock()+60000&&await verifiedEvidence(job.folder,item.evidence),note:'WorkBuddy 回执本条未完成，重试前仍需核对平台。'}:{seq,video:row.video,at,state:'unknown',note:'缺少与清单对应的有效后台回执。'};
          }
          items.push(merged||{seq,video:row.video,at,state:'unknown',note:'缺少与清单对应的有效后台回执。'});
        }
        job.results=items;job.platformVerified=items.length>0&&items.every(i=>['scheduled','published'].includes(i.state));job.state=result?(job.platformVerified?'completed':'attention'):'running';
      }else if(job.kind==='connection-check'&&result){job.state=job.state==='completed'||connection?.folder===job.folder?'completed':'attention';}
      else if(result){job.state=['complete','partial'].includes(result.status)?'completed':'attention';job.captureFiles=Object.values(result.files||{}).filter(f=>typeof f==='string'&&!path.isAbsolute(f)&&inside(job.folder,path.resolve(job.folder,f))).map(f=>path.resolve(job.folder,f));job.capturedAt=result.capturedAt||null;}
      await saveJob(job);if(result&&active===id&&job.state==='completed')active=null;
    }
    // Inspect only message types; no raw assistant prose reaches business UI.
    let needsInput=false;
    if(job.remoteMessageId&&['submitted','running','unknown'].includes(job.state)){try{const v=await access(),r=await request('/localassistant/message?message_id='+encodeURIComponent(job.remoteMessageId),{token:v.accessToken});needsInput=(r.data?.messages||[]).some(m=>['permission_request','ask_question','question'].includes(m.msg_type));}catch{}}
    return {id:job.id,kind:job.kind,batchId:job.batchId,state:job.state,status:job.state,summary:publicJob(job).summary,needsInput,remoteMessageId:job.remoteMessageId||null,platformVerified:job.platformVerified,results:job.results||[],jobDir:job.folder,captureFiles:job.captureFiles||[],capturedAt:job.capturedAt||null};
  }
  return {status,configure,connect,callback,start,poll,acknowledge};
}
