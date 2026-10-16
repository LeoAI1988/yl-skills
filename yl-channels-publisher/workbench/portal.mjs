// Four independent views share a page; switching never rebuilds publishing inputs.
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {panel:'publish', runtime:null, batches:[], summary:null, page:1, pageSize:25, total:0, direction:'desc', request:0, historyRequest:0, capturing:false, checking:false, acknowledging:false, ackJobId:null, reportLoaded:false};
const formats = new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2});
const metricLabels = {views:'播放量',likes:'点赞',comments:'评论',shares:'分享',favorites:'收藏',recommendations:'推荐',follows:'新增关注',completionPct:'完播率',threeSecPct:'3 秒留存率',watchSeconds:'平均观看时长（秒）',durationSeconds:'视频时长（秒）',unfollows:'取消关注',orders:'订单数',buyers:'成交人数',revenue:'成交金额',goodsClicks:'商品点击',profileVisits:'主页访问',exposures:'曝光',clicks:'点击',forward:'转发',readCount:'阅读量',fastFlipPct:'快速划走率',forwardTimeline:'转发朋友圈',forwardChat:'转发聊天',ringSetCount:'设为铃声',snsCoverCount:'设为朋友圈封面',statusReferenceCount:'设为状态',forwardAggregationCount:'合集转发',yesterdayViews:'昨日播放',wecomLinkClicks:'企业微信链接点击',wecomContactAdds:'企业微信添加',wecomLinkClickUv:'企业微信点击人数',wecomContactAddUv:'企业微信添加人数'};
const mainMetrics = ['views','likes','comments','shares','favorites','recommendations','follows','completionPct','threeSecPct','watchSeconds','durationSeconds'];
const statusLabels = {published:'已发布',scheduled:'已预约',failed:'失败',unknown:'待核验',blocked:'暂未执行',planned:'仅保存清单',running:'执行中',queued:'等待执行',completed:'执行完成',partial:'部分完成',cancelled:'已取消',imported:'历史导入',public:'公开',hidden:'已隐藏'};
const originLabels = {workbench:'工作台',platform:'历史作品',historical:'历史作品',history:'历史作品',import:'历史导入',imported:'历史导入',legacy:'历史作品',local:'已有记录',manual:'手动记录'};
const knownMetric = key => metricLabels[key] || '其他已采集指标';
const empty = (v) => v === undefined || v === null || v === '';
function num(value){if(empty(value))return '—';const n=Number(value);return Number.isFinite(n)?formats.format(n):String(value);}
function metricValue(key,value){if(empty(value))return '—';return key.endsWith('Pct')?`${num(value)}%`:num(value);}
function dateTime(value){if(!value)return '尚未采集';const str=String(value);if(/^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$/.test(str))return str.replace('T',' ');const d=new Date(value);return Number.isNaN(d.getTime())?str:d.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});}
function shortDate(value){return value?dateTime(value).slice(0,10).replaceAll('/','-'):'日期待确认';}
function badge(value, fallback='待核验'){const key=String(value||'unknown');return `<span class="portal-badge ${Object.hasOwn(statusLabels,key)?key:'unknown'}">${esc(statusLabels[key]||fallback)}</span>`;}
function origin(value){return originLabels[value]||'来源待确认';}
function businessText(value){if(empty(value))return '';if(typeof value==='string'||typeof value==='number')return String(value);if(Array.isArray(value))return value.map(businessText).filter(Boolean).join('；');if(typeof value==='object')return String(value.message||value.label||value.summary||value.note||value.reason||'');return '';}
function coverageText(coverage){if(!coverage)return '采集范围待确认';if(typeof coverage==='string')return coverage;if(Array.isArray(coverage))return coverage.map(businessText).filter(Boolean).join('；')||'采集范围待确认';const parts=[];for(const key of ['summary','message','note','statusLabel'])if(businessText(coverage[key]))parts.push(businessText(coverage[key]));for(const key of ['gaps','missing','warnings','limitations'])if(businessText(coverage[key]))parts.push(`待补充：${businessText(coverage[key])}`);if(!parts.length&&coverage.hiddenIncluded===true)parts.push('已纳入隐藏作品');if(!parts.length&&coverage.hiddenIncluded===false)parts.push('隐藏作品尚未完整采集');return [...new Set(parts)].join(' · ')||'详细采集范围见复盘说明';}
function feedback(id,message='',isError=false){const element=$(id);element.textContent=message;element.classList.toggle('is-error',isError);}
function loadingEmpty(title,description=''){return `<div class="portal-empty"><strong>${esc(title)}</strong>${esc(description)}</div>`;}
function stats(target,items){$(target).innerHTML=items.map(([label,value,note])=>`<div class="portal-stat"><div class="portal-stat-label">${esc(label)}</div><div class="portal-stat-value">${esc(num(value))}</div><div class="portal-stat-note">${esc(note||'')}</div></div>`).join('');}
function renderCoverage(coverage){for(const target of ['tracking','review']){const details=$(`#${target}Gaps`);if(!Array.isArray(coverage)||!coverage.length){details.hidden=true;continue;}details.hidden=false;const missing=coverage.filter(item=>item.status!=='complete').length;details.querySelector('summary').textContent=`采集范围与缺口 · ${missing} 项待补充`;details.querySelector('div').innerHTML=coverage.map(item=>`<p><strong>${esc(item.item||'采集范围')} · ${item.status==='complete'?'已采集':'待补充'}</strong><br>${esc(businessText(item))}</p>`).join('');}}
async function api(path,options={}){const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),30000);try{const response=await fetch(path,{cache:'no-store',...options,signal:controller.signal,headers:{Accept:'application/json',...(options.body?{'Content-Type':'application/json'}:{}),...options.headers}});let data;try{data=await response.json();}catch{throw new Error('工作台返回的内容无法读取，请稍后重试。');}if(!response.ok||data?.ok===false)throw new Error(data?.message||data?.error||`请求未完成（${response.status}）`);return data;}catch(error){if(error.name==='AbortError')throw new Error('读取超时，请检查工作台服务后重试。');throw error;}finally{clearTimeout(timer);}}

async function refreshRuntime(){try{state.runtime=await api('/api/runtime');renderRuntime();window.dispatchEvent(new CustomEvent('workbuddy-runtime',{detail:state.runtime}));}catch{state.runtime=null;$('#portalRuntime').className='portal-runtime';$('#portalRuntimeText').textContent='暂时无法读取 WorkBuddy 状态，请确认工作台服务正在运行。';$('#trackingCapture').disabled=true;window.dispatchEvent(new CustomEvent('workbuddy-runtime',{detail:{available:false,capabilities:{publish:false,capture:false},message:'暂时无法读取 WorkBuddy 状态。'}}));}renderConnectionState();}
function jobInfo(){return activeJobInfo()||state.runtime?.lastJob||null;}
function activeJobInfo(){const raw=state.runtime?.activeJob;return typeof raw==='string'?{id:raw,status:'submitted'}:raw;}
function renderRuntime(){
  const runtime=state.runtime,job=activeJobInfo();
  const jobStatus=job?.status||job?.state;
  const modelMismatch=runtime?.assistantModel&&runtime.assistantModel!==$('#executorModel').value;
  const jobActive=job&&!['completed','failed','cancelled','succeeded','acknowledged'].includes(jobStatus);
  const canCapture=runtime?.available===true&&runtime?.capabilities?.capture===true&&!modelMismatch;
  $('#portalRuntime').className=`portal-runtime${runtime?.available?' is-connected':''}${jobActive?' is-active':''}`;
  $('#portalRuntimeText').textContent=runtime?.message||(runtime?.available?'WorkBuddy 已连接':'WorkBuddy 尚未连接，可先查看已有记录和历史数据。');
  $('#trackingCapture').disabled=!canCapture||Boolean(jobActive)||state.capturing;
  $('#trackingCapture').textContent=state.capturing||jobActive&&job.kind==='capture'?'正在采集…':'采集最新数据';
  $('#trackingCapture').title=modelMismatch?'请将顶部模型与 WorkBuddy 本地助理当前模型保持一致':canCapture?'从视频号读取最新可用数据':'WorkBuddy 采集连接尚未就绪';
  const displayJob=jobInfo();
  $('#portalJob').hidden=!displayJob;
  if(displayJob){
    const displayStatus=displayJob.status||displayJob.state;
    const uncertain=['attention','unknown'].includes(displayStatus);
    $('#portalJob').classList.toggle('needs-review',uncertain);
    $('#portalJobTitle').textContent=({'connection-check':'视频号连接检查',capture:'作品数据采集',publish:'本轮发布任务'})[displayJob.kind]||'WorkBuddy 任务';
    $('#portalJobState').textContent=({submitting:'正在提交',submitted:'已提交',running:'执行中',queued:'等待执行',completed:'任务结束',attention:'需要核对',unknown:'结果待确认',failed:'任务失败',cancelled:'已取消',acknowledged:'已核对'})[displayStatus]||'状态待确认';
    $('#portalJobSummary').textContent=businessText(displayJob.summary)||businessText(displayJob.note)||'正在等待 WorkBuddy 的可核验结果。';
    $('#portalJobHint').textContent=uncertain?'请先在 WorkBuddy 中核对任务是否结束或停止；结果未确认时，不要重复提交。':displayJob.kind==='connection-check'?'此任务只读核对视频号账号、模型与工具，不上传、不发布。':'任务结束不等于平台操作成功，具体状态以作品回执与真实采集时间为准。';
  }
  const canAcknowledge=Boolean(job?.id)&&['unknown','attention'].includes(jobStatus);
  $('#portalAcknowledge').hidden=!canAcknowledge;
  const nextAckId=job?.id||null;
  if(state.ackJobId!==nextAckId){state.ackJobId=nextAckId;$('#portalAckConfirmed').checked=false;feedback('#portalAckNotice');}
  $('#portalAckButton').disabled=!canAcknowledge||!$('#portalAckConfirmed').checked||state.acknowledging;
  const integrationCandidate=displayJob?.integration||runtime?.integration;
  const integration=integrationCandidate&&(!integrationCandidate.jobId||integrationCandidate.jobId===displayJob?.id)?integrationCandidate:null;
  if(displayJob&&integration?.status==='rejected'){
    $('#portalJob').classList.add('needs-review');
    $('#portalJobState').textContent=displayJob.kind==='capture'?'采集结果未入库':'任务回执未完成归档';
    $('#portalJobHint').textContent=businessText(integration.message)||(displayJob.kind==='capture'?'采集结果尚未通过校验，已有数据保持原样，请核对本轮结果。':'本轮回执暂未完成归档，请稍后刷新并核对平台结果，不要重复提交。');
  }else if(displayJob?.kind==='capture'&&integration?.status==='imported'){
    $('#portalJobHint').textContent=businessText(integration.message)||'已核验并导入本轮采集结果；实际采集时间和覆盖范围见数据跟踪。';
  }
  renderConnectionState();
}

async function showPanel(name){if(!['publish','history','tracking','review'].includes(name))return;state.panel=name;for(const tab of document.querySelectorAll('.portal-nav [role=tab]')){const active=tab.dataset.panel===name;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;}for(const panel of document.querySelectorAll('.portal-panel'))panel.hidden=panel.id!==`panel-${name}`;document.body.classList.toggle('portal-wide',name==='review'&&$('#reviewExpand').dataset.expanded==='true');if(name==='history')await loadHistory();if(name==='tracking')await Promise.all([loadSummary(),loadPosts()]);if(name==='review')await Promise.all([loadSummary(),loadReport()]);}
for(const tab of document.querySelectorAll('.portal-nav [role=tab]')){tab.addEventListener('click',()=>void showPanel(tab.dataset.panel));tab.addEventListener('keydown',event=>{const tabs=[...document.querySelectorAll('.portal-nav [role=tab]')];let index=tabs.indexOf(tab);if(event.key==='ArrowRight')index=(index+1)%tabs.length;else if(event.key==='ArrowLeft')index=(index+tabs.length-1)%tabs.length;else if(event.key==='Home')index=0;else if(event.key==='End')index=tabs.length-1;else return;event.preventDefault();tabs[index].focus();void showPanel(tabs[index].dataset.panel);});}

async function loadHistory(){const request=++state.historyRequest;$('#historyRefresh').disabled=true;if(!state.batches.length)$('#historyList').innerHTML=loadingEmpty('正在整理发布记录…');feedback('#historyNotice');try{const data=await api('/api/history');if(request!==state.historyRequest)return;state.batches=Array.isArray(data.batches)?data.batches:[];const totals={published:0,scheduled:0,failed:0,unknown:0,planned:0};for(const batch of state.batches){if(batch.counts)for(const key of Object.keys(totals))totals[key]+=Number(batch.counts[key])||0;else for(const row of batch.rows||[])if(Object.hasOwn(totals,row.status))totals[row.status]++;}stats('#historyStats',[['已发布',totals.published,'平台确认后的作品'],['已预约',totals.scheduled,'尚未到发布时点'],['待核验 / 失败',totals.unknown+totals.failed,`待核验 ${num(totals.unknown)} · 失败 ${num(totals.failed)}`],['仅保存清单',totals.planned,'不计入已发布']]);$('#historyList').innerHTML=state.batches.length?state.batches.map((batch,index)=>{const historical=/histor|import|legacy|platform/.test(batch.origin||'');const date=shortDate(batch.date||batch.createdAt);const c=batch.counts||{};return `<article class="portal-batch"><div class="portal-batch-date"><strong>${esc(date.match(/\d{2}$/)?.[0]||'—')}</strong><span>${esc(date.slice(0,7))}</span></div><div class="portal-batch-main"><div class="portal-batch-title"><h3>${esc(date)} · ${historical?'历史作品归档':'工作台发布批次'}</h3>${badge(batch.status)}</div><p class="portal-batch-meta">${historical?'按发布日期归组':`建立于 ${esc(dateTime(batch.createdAt))}`}${batch.model?` · ${esc(batch.model)}`:''} · ${esc(num(batch.count??batch.rows?.length))} 条</p><div class="portal-batch-counts">${[['published','已发布'],['scheduled','已预约'],['planned','清单'],['unknown','待核验'],['failed','失败']].filter(([key])=>Number(c[key])>0).map(([key,label])=>`<span><strong>${esc(num(c[key]))}</strong>${label}</span>`).join('')||'<span>打开查看作品与执行状态</span>'}</div></div><button type="button" class="sm" data-batch="${index}">查看明细 ↗</button></article>`;}).join(''):loadingEmpty('暂时没有发布记录','保存的清单与导入的历史作品会显示在这里。');}catch(error){feedback('#historyNotice',error.message,true);if(!state.batches.length)$('#historyList').innerHTML=loadingEmpty('记录暂时未能载入','点击“刷新记录”重试。');}finally{$('#historyRefresh').disabled=false;}}
$('#historyRefresh').addEventListener('click',()=>void loadHistory());
$('#historyList').addEventListener('click',event=>{const button=event.target.closest('[data-batch]');if(!button)return;const batch=state.batches[Number(button.dataset.batch)];if(!batch)return;showDetail('发布记录明细',`<p class="portal-detail-title">${esc(shortDate(batch.date||batch.createdAt))} · ${esc(origin(batch.origin))}</p><p class="portal-detail-intro">${badge(batch.status)}　${esc(num(batch.count??batch.rows?.length))} 条${batch.model?` · ${esc(batch.model)}`:''}。清单中的安排不代表已经发布，状态以执行回执和平台核验为准。</p><h3>本轮作品</h3><div class="portal-table-shell"><table class="portal-table"><thead><tr><th>顺序</th><th>作品</th><th>时间</th><th>状态</th><th>商品</th></tr></thead><tbody>${(batch.rows||[]).map((row,index)=>`<tr><td>${esc(row.seq??index+1)}</td><td>${esc(row.title||'标题待补充')}${row.error?`<p class="portal-post-sub">${esc(businessText(row.error))}</p>`:''}</td><td>${esc(row.time||'—')}</td><td>${badge(row.status)}</td><td>${esc(typeof row.goods==='object'?businessText(row.goods)||row.goods?.name||row.goods?.title||'—':row.goods||'—')}</td></tr>`).join('')||'<tr><td colspan="5">暂无作品明细</td></tr>'}</tbody></table></div>`);});

async function loadSummary(){try{const data=await api('/api/analytics/summary');state.summary=data;const total=data.total??data.postCount,hidden=data.hidden??data.hiddenCount,videos=data.videos??data.videoCount,images=data.images??data.imageCount;stats('#trackingStats',[['全部作品',total,`最后已知隐藏 ${num(hidden)} 条`],['视频作品',videos,`另有图文 ${num(images)} 条`],['累计播放',data.views,`最近同批采集 ${num(data.latestPostCount??total)} 条作品`],['累计新增关注',data.follows,'同批作品累计值，不含未返回旧记录']]);const latest=`最近采集：${dateTime(data.latestCapturedAt)}`;$('#trackingTimestamp').textContent=latest;$('#reviewTimestamp').textContent=latest;const coverage=!empty(data.latestPostCount)?`最近采集 ${num(data.latestPostCount)} 条 · 仅留历史 ${num(data.historicalOnlyCount)} 条待核验`:coverageText(data.coverage);$('#trackingCoverage').textContent=coverage;$('#reviewCoverage').textContent=coverage;renderCoverage(data.coverage);}catch(error){if(state.panel==='review')feedback('#reviewNotice',`统计信息暂时无法载入：${error.message}`,true);else feedback('#trackingNotice',`统计信息暂时无法载入：${error.message}`,true);}}
function postParams(){return new URLSearchParams({search:$('#trackingSearch').value.trim(),visibility:$('#trackingVisibility').value,contentType:$('#trackingType').value,from:$('#trackingFrom').value,to:$('#trackingTo').value,hasSales:$('#trackingSales').value,captureStatus:$('#trackingCaptureStatus').value,page:String(state.page),pageSize:String(state.pageSize),sort:$('#trackingSort').value,direction:state.direction});}
async function loadPosts(){if($('#trackingFrom').value&&$('#trackingTo').value&&$('#trackingFrom').value>$('#trackingTo').value){feedback('#trackingNotice','发布起始日期不能晚于结束日期，请调整日期范围。',true);return;}const request=++state.request;$('#trackingRows').setAttribute('aria-busy','true');feedback('#trackingNotice');if(!$('#trackingRows').children.length)$('#trackingRows').innerHTML='<tr><td colspan="14"><div class="portal-empty">正在读取作品数据…</div></td></tr>';try{const data=await api(`/api/analytics/posts?${postParams()}`);if(request!==state.request)return;const items=Array.isArray(data.items)?data.items:[];state.total=Number(data.total)||0;state.page=Number(data.page)||state.page;state.pageSize=Number(data.pageSize)||state.pageSize;$('#trackingRows').innerHTML=items.length?items.map(post=>`<tr><td><button type="button" class="portal-link-button" data-post="${esc(post.id)}">${esc(post.title||'标题待补充')}</button><p class="portal-post-sub">${post.contentType==='image'?'图文':post.contentType==='video'?'视频':'类型待确认'} · ${esc(origin(post.origin))}${post.topic?` · ${esc(businessText(post.topic))}`:''}</p></td><td><div class="portal-post-date">${esc(shortDate(post.publishedAt))}</div>${badge(post.visibility,'状态待确认')}${post.captureStatus==='not_in_latest_capture'?'<p class="portal-capture-stale">仅留历史 · 当前待核</p>':post.captureStatus==='latest'?'<p class="portal-post-sub">最近采集已返回</p>':'<p class="portal-post-sub">采集范围待核</p>'}</td>${mainMetrics.map(key=>`<td>${esc(metricValue(key,post.metrics?.[key]))}${!empty(post.metrics?.[key])&&key.endsWith('Seconds')?' 秒':''}</td>`).join('')}<td>${esc(post.latestCapturedAt?dateTime(post.latestCapturedAt):'—')}</td></tr>`).join(''):`<tr><td colspan="14">${loadingEmpty(state.total?'这一页没有作品':'暂无符合条件的作品',$('#trackingSearch').value?'可以调整搜索词或筛选条件。':'导入历史数据或采集后，作品会显示在这里。')}</td></tr>`;$('#trackingPageInfo').textContent=`共 ${num(state.total)} 条 · 第 ${state.page} / ${Math.max(1,Math.ceil(state.total/state.pageSize))} 页`;$('#trackingPrevious').disabled=state.page<=1;$('#trackingNext').disabled=state.page*state.pageSize>=state.total;if(data.latestCapturedAt)$('#trackingTimestamp').textContent=`最近采集：${dateTime(data.latestCapturedAt)}`;if(data.coverage)renderCoverage(data.coverage);}catch(error){if(request!==state.request)return;feedback('#trackingNotice',error.message,true);$('#trackingRows').innerHTML=`<tr><td colspan="14">${loadingEmpty('作品数据暂时无法载入','请点击“重读已有数据”重试。')}</td></tr>`;$('#trackingPageInfo').textContent='读取未完成';$('#trackingPrevious').disabled=true;$('#trackingNext').disabled=true;}finally{if(request===state.request)$('#trackingRows').removeAttribute('aria-busy');}}
let searchTimer;$('#trackingSearch').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.page=1;void loadPosts();},300);});for(const id of ['trackingVisibility','trackingType','trackingSort','trackingFrom','trackingTo','trackingSales','trackingCaptureStatus'])$('#'+id).addEventListener('change',()=>{state.page=1;void loadPosts();});$('#trackingDirection').addEventListener('click',()=>{state.direction=state.direction==='desc'?'asc':'desc';$('#trackingDirection').textContent=state.direction==='desc'?'↓ 降序':'↑ 升序';$('#trackingDirection').setAttribute('aria-label',state.direction==='desc'?'当前降序，点击切换升序':'当前升序，点击切换降序');state.page=1;void loadPosts();});$('#trackingPrevious').addEventListener('click',()=>{if(state.page>1){state.page--;void loadPosts();}});$('#trackingNext').addEventListener('click',()=>{if(state.page*state.pageSize<state.total){state.page++;void loadPosts();}});
$('#trackingReload').addEventListener('click',async()=>{const button=$('#trackingReload');button.disabled=true;feedback('#trackingNotice','正在重新读取已有数据…');try{const result=await api('/api/analytics/reload',{method:'POST',body:'{}'});await Promise.all([loadSummary(),loadPosts()]);feedback('#trackingNotice',result.message||'已有数据已重新载入；这一步不会向视频号采集新数据。');state.reportLoaded=false;}catch(error){feedback('#trackingNotice',error.message,true);}finally{button.disabled=false;}});
$('#trackingCapture').addEventListener('click',async()=>{if(!state.runtime?.available||!state.runtime?.capabilities?.capture||state.capturing)return;state.capturing=true;renderRuntime();feedback('#trackingNotice','正在请求 WorkBuddy 采集最新数据…');try{const result=await api('/api/analytics/refresh',{method:'POST',body:JSON.stringify({model:$('#executorModel').value})});await refreshRuntime();await Promise.all([loadSummary(),loadPosts()]);feedback('#trackingNotice',result.message||'已提交采集请求，完成后这里会更新采集时间。');state.reportLoaded=false;}catch(error){feedback('#trackingNotice',error.message,true);}finally{state.capturing=false;renderRuntime();}});

function showDetail(title,html){$('#portalDetailTitle').textContent=title;$('#portalDetailBody').innerHTML=html;if(!$('#portalDetail').open)$('#portalDetail').showModal();$('#portalDetailBody').scrollTop=0;}
$('#portalDetailClose').addEventListener('click',()=>$('#portalDetail').close());$('#portalDetail').addEventListener('click',event=>{if(event.target!==$('#portalDetail'))return;const rect=$('#portalDetail').getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)$('#portalDetail').close();});
let detailRequest=0;
$('#trackingRows').addEventListener('click',async event=>{const button=event.target.closest('[data-post]');if(!button)return;const request=++detailRequest;showDetail('作品数据详情',loadingEmpty('正在读取作品详情…'));try{const response=await api(`/api/analytics/posts/${encodeURIComponent(button.dataset.post)}`);if(request!==detailRequest)return;const post=response.item||response.post||response;renderPostDetail(post);}catch(error){if(request===detailRequest)showDetail('作品数据详情',loadingEmpty('详情暂时无法载入',error.message));}});
function renderPostDetail(post){
  const metrics=post.metrics&&typeof post.metrics==='object'?post.metrics:{};
  const keys=[...mainMetrics,...Object.keys(metrics).filter(key=>!mainMetrics.includes(key))];
  const snapshots=Array.isArray(post.snapshots)?post.snapshots:[];
  const snapshotKeys=[...new Set(snapshots.flatMap(snapshot=>Object.keys(snapshot.metrics||{})))];
  const transcript=typeof post.transcript==='string'?post.transcript:post.transcript?.full||post.transcript?.text||post.transcript?.body||'';
  const attribution=Array.isArray(post.attribution)?post.attribution:[];
  const attributionHTML=attribution.length?'<h3>商品成交归因</h3><div class="portal-table-shell"><table class="portal-table"><thead><tr><th>商品</th><th>订单</th><th>金额</th><th>观察日期</th><th>口径说明</th></tr></thead><tbody>'+attribution.map(item=>'<tr><td>'+esc(item.product||item.name||'商品待确认')+'</td><td>'+esc(num(item.orders))+'</td><td>'+esc(num(item.amount))+'</td><td>'+esc(shortDate(item.observedDate||item.capturedAt))+'</td><td>'+esc(item.note||'归因口径待确认')+(item.evidence?'<p class="portal-post-sub">'+esc(item.evidence)+'</p>':'')+'</td></tr>').join('')+'</tbody></table></div>':'<h3>商品成交归因</h3><p class="portal-detail-intro">尚无已核验的本条作品成交归因，不能据此判断没有成交。</p>';
  showDetail('作品数据详情',
    '<p class="portal-detail-title">'+esc(post.title||'标题待补充')+'</p>'+
    '<p class="portal-detail-intro">'+badge(post.visibility,'状态待确认')+'　'+esc(shortDate(post.publishedAt))+' · '+esc(origin(post.origin))+(post.topic?' · '+esc(businessText(post.topic)):'')+'<br>最近采集：'+esc(dateTime(post.latestCapturedAt))+'</p>'+
    (post.captureNote?'<div class="portal-note">'+esc(post.captureNote)+'</div>':'')+
    '<h3>全部已有指标</h3><div class="portal-metric-grid">'+keys.map(key=>'<div class="portal-metric"><span>'+esc(knownMetric(key))+'</span><strong>'+esc(typeof metrics[key]==='object'&&!empty(metrics[key])?businessText(metrics[key])||'待补充':metricValue(key,metrics[key]))+'</strong></div>').join('')+'</div>'+
    attributionHTML+
    '<h3>采集历史 · '+esc(num(snapshots.length))+' 次</h3>'+
    (snapshots.length?'<div class="portal-table-shell"><table class="portal-table"><thead><tr><th>采集时间</th>'+snapshotKeys.map(key=>'<th>'+esc(knownMetric(key))+'</th>').join('')+'</tr></thead><tbody>'+snapshots.map(snapshot=>'<tr><td>'+esc(dateTime(snapshot.capturedAt||snapshot.timestamp||snapshot.latestCapturedAt))+'</td>'+snapshotKeys.map(key=>'<td>'+esc(metricValue(key,snapshot.metrics?.[key]))+'</td>').join('')+'</tr>').join('')+'</tbody></table></div><p class="portal-footnote">每一行是当次采集的指标快照。累计值的变化可能来自补录或平台修正，不能直接当作每日新增。</p>':'<p class="portal-detail-intro">当前尚无可对比的多次采集记录。</p>')+
    (post.description?'<h3>发布描述</h3><div class="portal-transcript">'+esc(post.description)+'</div>':'')+
    (transcript?'<h3>作品正文 / 转录</h3><div class="portal-transcript">'+esc(transcript)+'</div>':'<p class="portal-footnote">'+esc(post.transcript?.reason||'尚未采集本条作品的完整正文或转录。')+'</p>')
  );
}

async function loadReport(force=false){if(state.reportLoaded&&!force)return;$('#reviewLoading').hidden=false;$('#reviewLoading').textContent='正在载入复盘大屏…';feedback('#reviewNotice');try{const response=await fetch('/reports/current',{cache:'no-store',method:'HEAD'});if(!response.ok)throw new Error(response.status===404?'当前还没有可查看的复盘报告。':'复盘大屏暂时无法载入，请稍后重试。');await response.body?.cancel();$('#reviewFrame').src=`/reports/current${force?`?v=${Date.now()}`:''}`;state.reportLoaded=true;}catch(error){$('#reviewLoading').textContent='复盘大屏尚未就绪';feedback('#reviewNotice',error.message,true);}}
$('#reviewFrame').addEventListener('load',()=>{if($('#reviewFrame').getAttribute('src'))$('#reviewLoading').hidden=true;});$('#reviewFrame').addEventListener('error',()=>{state.reportLoaded=false;$('#reviewLoading').textContent='复盘大屏载入失败';feedback('#reviewNotice','请点击“刷新复盘”重试。',true);});$('#reviewReload').addEventListener('click',async()=>{const button=$('#reviewReload');button.disabled=true;await Promise.all([loadSummary(),loadReport(true)]);button.disabled=false;});$('#reviewExpand').addEventListener('click',()=>{const expanded=$('#reviewExpand').dataset.expanded!=='true';$('#reviewExpand').dataset.expanded=String(expanded);$('#reviewExpand').textContent=expanded?'恢复标准宽度':'宽屏查看';$('#reviewExpand').setAttribute('aria-pressed',String(expanded));document.body.classList.toggle('portal-wide',expanded);});

function connectionStatus(){return state.runtime?.status&&typeof state.runtime.status==='object'?state.runtime.status:state.runtime||{};}
function renderConnectionState(){
  const status=connectionStatus(),job=activeJobInfo(),jobStatus=job?.status||job?.state;
  const busy=job&&!['completed','failed','cancelled','succeeded','acknowledged'].includes(jobStatus);
  const modelMismatch=status.assistantModel&&status.assistantModel!==$('#executorModel').value;
  $('#workbuddySettings').textContent=status.authorized?'WorkBuddy 设置':'连接 WorkBuddy';
  $('#workbuddyConnect').disabled=!status.configured;
  $('#workbuddyCheck').disabled=status.capabilities?.connectionCheck!==true||Boolean(busy)||state.checking||Boolean(modelMismatch);
  $('#workbuddyCheck').textContent=state.checking||busy&&job.kind==='connection-check'?'正在检查视频号…':'检查视频号连接';
  $('#workbuddyCheck').title=modelMismatch?'顶部模型须与 WorkBuddy 当前助理模型保持一致':status.capabilities?.connectionCheck?'只读核对账号、模型和视频号工具，不发布作品':'先完成 WorkBuddy 授权并保持助理在线';
  $('#workbuddyConnectionState').textContent=status.channelsConnection==='verified'&&status.available?'视频号连接已核验，可以使用已开放的发布与采集功能。':status.authorized?(status.online?'已授权且助理在线，请点击“检查视频号连接”完成只读核验。':'已授权，请打开 WorkBuddy 并保持本地助理在线。'):status.configured?'应用配置已保存，下一步生成授权链接。':'填写已有应用的配置，保存后完成 WorkBuddy 授权。';
}

$('#workbuddySettings').addEventListener('click',async()=>{$('#workbuddyDialog').showModal();feedback('#workbuddyConfigNotice');await refreshRuntime();const model=state.runtime?.assistantModel;if([...$('#workbuddyAssistantModel').options].some(option=>option.value===model))$('#workbuddyAssistantModel').value=model;});
$('#workbuddyClose').addEventListener('click',()=>$('#workbuddyDialog').close());
$('#workbuddyDialog').addEventListener('close',()=>{$('#workbuddyClientId').value='';$('#workbuddyClientSecret').value='';});
$('#workbuddyConfigForm').addEventListener('submit',async event=>{
  event.preventDefault();const clientId=$('#workbuddyClientId').value.trim(),clientSecret=$('#workbuddyClientSecret').value.trim(),assistantModel=$('#workbuddyAssistantModel').value;
  if(!clientId||!clientSecret){feedback('#workbuddyConfigNotice','请填写应用 Client ID 和 Client Secret。',true);return;}
  $('#workbuddySaveConfig').disabled=true;feedback('#workbuddyConfigNotice','正在保存本机配置…');
  try{await api('/api/workbuddy/config',{method:'POST',body:JSON.stringify({clientId,clientSecret,assistantModel})});$('#workbuddyClientId').value='';$('#workbuddyClientSecret').value='';$('#workbuddyAuthorizeLink').hidden=true;$('#workbuddyAuthorizeLink').removeAttribute('href');await refreshRuntime();feedback('#workbuddyConfigNotice','本机配置已保存，点击“生成授权链接”继续。');}
  catch{feedback('#workbuddyConfigNotice','配置未保存成功，请检查应用信息与工作台服务后重试。',true);}
  finally{$('#workbuddyClientSecret').value='';$('#workbuddySaveConfig').disabled=false;}
});
$('#workbuddyConnect').addEventListener('click',async()=>{
  $('#workbuddyConnect').disabled=true;feedback('#workbuddyConfigNotice','正在准备 WorkBuddy 授权…');
  try{const result=await api('/api/workbuddy/connect',{method:'POST',body:'{}'});const url=new URL(result.authorizeUrl);if(url.protocol!=='https:'||url.hostname!=='www.workbuddy.cn'||url.pathname!=='/openapi/v2/authorize'||url.username||url.password)throw new Error('授权链接未通过校验。');$('#workbuddyAuthorizeLink').href=url.href;$('#workbuddyAuthorizeLink').hidden=false;feedback('#workbuddyConfigNotice','点击右侧授权链接，在 WorkBuddy 页面完成授权后返回这里。');}
  catch{feedback('#workbuddyConfigNotice','授权链接暂时无法生成，请确认应用配置后重试。',true);}
  finally{renderConnectionState();}
});

let polling=false;async function poll(){if(document.hidden||polling)return;polling=true;try{const previousJob=state.runtime?.activeJob;const previousCapture=state.runtime?.lastCaptureAt;await refreshRuntime();const newCapture=previousCapture!==state.runtime?.lastCaptureAt;const finished=previousJob&&!state.runtime?.activeJob;if(state.panel==='history')await loadHistory();else if(state.panel==='tracking')await Promise.all([loadSummary(),loadPosts()]);else if(state.panel==='review'){await loadSummary();if(newCapture||finished)await loadReport(true);}}finally{polling=false;}}
setInterval(()=>void poll(),15000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)void poll();});void refreshRuntime();

window.addEventListener('publication-saved',()=>{if(state.panel==='history')void loadHistory();});
window.addEventListener('workbuddy-status-requested',()=>void refreshRuntime());
$('#workbuddyCheck').addEventListener('click',async()=>{
  if(state.runtime?.capabilities?.connectionCheck!==true||state.checking)return;
  state.checking=true;renderConnectionState();feedback('#workbuddyConfigNotice','正在请求只读检查视频号账号、模型与可用工具…');
  try{const result=await api('/api/workbuddy/check',{method:'POST',body:JSON.stringify({model:$('#executorModel').value})});await refreshRuntime();feedback('#workbuddyConfigNotice',result.message||'已提交视频号连接检查，等待 WorkBuddy 返回核验结果。');}
  catch(error){feedback('#workbuddyConfigNotice',error.message||'连接检查暂时无法开始，请检查 WorkBuddy 状态后重试。',true);}
  finally{state.checking=false;renderConnectionState();}
});
$('#workbuddyRefreshStatus').addEventListener('click',async()=>{$('#workbuddyRefreshStatus').disabled=true;await refreshRuntime();$('#workbuddyRefreshStatus').disabled=false;feedback('#workbuddyConfigNotice',state.runtime?.message||'连接状态已更新。');});
$('#trackingReset').addEventListener('click',()=>{clearTimeout(searchTimer);$('#trackingSearch').value='';for(const id of ['trackingVisibility','trackingType','trackingSales','trackingCaptureStatus'])$('#'+id).value='all';$('#trackingFrom').value='';$('#trackingTo').value='';state.page=1;void loadPosts();});


$('#executorModel').addEventListener('change',()=>renderRuntime());

$('#portalAckConfirmed').addEventListener('change',()=>renderRuntime());
$('#portalAckButton').addEventListener('click',async()=>{
  const job=activeJobInfo(),status=job?.status||job?.state;
  if(!job?.id||!['unknown','attention'].includes(status)||!$('#portalAckConfirmed').checked||state.acknowledging)return;
  state.acknowledging=true;renderRuntime();feedback('#portalAckNotice','正在解除本机工作台占用…');
  try{await api('/api/workbuddy/acknowledge',{method:'POST',body:JSON.stringify({id:job.id,confirmed:true})});$('#portalAckConfirmed').checked=false;await refreshRuntime();}
  catch(error){feedback('#portalAckNotice',error.message||'占用尚未解除，请稍后重试。',true);}
  finally{state.acknowledging=false;renderRuntime();}
});
