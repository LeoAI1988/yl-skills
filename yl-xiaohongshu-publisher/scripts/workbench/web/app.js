const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={preparing:'自动匹配标题与封面',duplicate_review:'疑似重复 · 待深度排查',duplicate_checking:'查重尚未完成',ready:'待发布',history:'此前已提交',excluded:'已排除',queued:'等待准备',uploading:'准备中',awaiting_manual:'等待你到小红书提交',scheduled:'已提交定时',published:'已公开',reviewing:'审核中',failed:'未完成',unknown:'待核对',verified_absent:'已确认未提交',released:'已恢复待准备',attention:'需要你处理',item_failed:'本篇未上传 · 可单独重试',choosing:'选择视频文件',not_uploaded:'未上传',not_started:'未开始',duplicate:'已核实旧作 · 未重复上传',duplicate_pending:'疑似重复 · 本篇未发',connecting:'连接浏览器',checking:'核对重复',filling:'填写内容',submitting:'正在提交',verifying:'核对结果',paused:'已暂停'};
const aiLabels={unknown:'待确认',none:'内容未使用 AI 创作',contains_ai:'含 AI 生成或辅助创作'};
const blockingStates=['running','stopping','awaiting_manual','attention','verified_absent'];
function effectiveAi(a){const value=a.settings?.ai_declaration;return value&&value!=='unknown'?value:(S?.preparation_defaults?.ai_declaration||'unknown');}
function needsAutoFields(a){return !a.cover||contentIssues({...a,settings:{...a.settings,ai_declaration:effectiveAi(a)}},true).length>0;}

let S=null,page=1,tab='library',picked=new Set(),editing=null,tags=[],busy=false,toastTimer,scanNotices=new Set(),draggingSlot=null,pendingConfirmation=null,timeEdit=null,serverClock=null;
async function api(path,body){
 const post=body!==undefined;
 const send=()=>fetch('/api/'+path,post?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':$('meta[name="csrf-token"]').content},body:JSON.stringify(body)}:{});
 let r=await send(),data=await r.json();
 // Only retry an explicit rejection made before any handler or side effect.
 // Network errors, ambiguous responses and all other failures are never retried.
 if(post&&r.status===403&&data.code==='csrf_expired'){
  const session=await fetch('/api/session',{cache:'no-store'}),fresh=await session.json();
  if(!session.ok||typeof fresh.csrf_token!=='string'||!fresh.csrf_token)throw Error('工作台连接恢复失败，请刷新页面后重试；本次操作尚未执行');
  $('meta[name="csrf-token"]').content=fresh.csrf_token;
  r=await send();data=await r.json();
 }
 if(!r.ok)throw Error(data.error||'操作未完成');
 if(path==='state')serverClock={ms:Date.parse(data.server_time),tick:performance.now()};
 return post?data.result:data;
}
function toast(t){$('#toast').textContent=t;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),4500);}
async function action(fn){if(busy)return;busy=true;try{await fn();}catch(e){toast(e.message);}finally{busy=false;}}
function asset(id){return S.assets.find(a=>a.id===id);}
function title(a){return a?.title||a?.name||'素材已不可用';}
function ready(){return S.assets.filter(a=>a.state==='ready');}
function filtered(){const q=$('#search').value.toLowerCase(),folder=$('#sourceFilter').value.toLowerCase().replaceAll('\\','/');return ready().filter(a=>(title(a)+' '+a.name).toLowerCase().includes(q)&&(!folder||a.video.toLowerCase().replaceAll('\\','/').startsWith(folder+'/'))).sort((a,b)=>a.date.localeCompare(b.date)||a.id.localeCompare(b.id));}
function selected(){return ready().filter(a=>a.selected);}
function executorName(){return $('#executorModel').selectedOptions[0]?.textContent||'GPT-Astra';}
function effortName(){return $('#executorEffort').selectedOptions[0]?.textContent||'高';}
function limits(){return {title:20,caption:1000,tags:10,...S?.limits};}
// Unicode case-fold exceptions keep topic identity aligned with Python normalize_tags.
const tagCaseFold={"\u00b5":"\u03bc","\u00df":"ss","\u0149":"\u02bcn","\u017f":"s","\u01f0":"j\u030c","\u0345":"\u03b9","\u0390":"\u03b9\u0308\u0301","\u03b0":"\u03c5\u0308\u0301","\u03c2":"\u03c3","\u03d0":"\u03b2","\u03d1":"\u03b8","\u03d5":"\u03c6","\u03d6":"\u03c0","\u03f0":"\u03ba","\u03f1":"\u03c1","\u03f5":"\u03b5","\u0587":"\u0565\u0582","\uab70":"\u13a0","\uab71":"\u13a1","\uab72":"\u13a2","\uab73":"\u13a3","\uab74":"\u13a4","\uab75":"\u13a5","\uab76":"\u13a6","\uab77":"\u13a7","\uab78":"\u13a8","\uab79":"\u13a9","\uab7a":"\u13aa","\uab7b":"\u13ab","\uab7c":"\u13ac","\uab7d":"\u13ad","\uab7e":"\u13ae","\uab7f":"\u13af","\uab80":"\u13b0","\uab81":"\u13b1","\uab82":"\u13b2","\uab83":"\u13b3","\uab84":"\u13b4","\uab85":"\u13b5","\uab86":"\u13b6","\uab87":"\u13b7","\uab88":"\u13b8","\uab89":"\u13b9","\uab8a":"\u13ba","\uab8b":"\u13bb","\uab8c":"\u13bc","\uab8d":"\u13bd","\uab8e":"\u13be","\uab8f":"\u13bf","\uab90":"\u13c0","\uab91":"\u13c1","\uab92":"\u13c2","\uab93":"\u13c3","\uab94":"\u13c4","\uab95":"\u13c5","\uab96":"\u13c6","\uab97":"\u13c7","\uab98":"\u13c8","\uab99":"\u13c9","\uab9a":"\u13ca","\uab9b":"\u13cb","\uab9c":"\u13cc","\uab9d":"\u13cd","\uab9e":"\u13ce","\uab9f":"\u13cf","\uaba0":"\u13d0","\uaba1":"\u13d1","\uaba2":"\u13d2","\uaba3":"\u13d3","\uaba4":"\u13d4","\uaba5":"\u13d5","\uaba6":"\u13d6","\uaba7":"\u13d7","\uaba8":"\u13d8","\uaba9":"\u13d9","\uabaa":"\u13da","\uabab":"\u13db","\uabac":"\u13dc","\uabad":"\u13dd","\uabae":"\u13de","\uabaf":"\u13df","\uabb0":"\u13e0","\uabb1":"\u13e1","\uabb2":"\u13e2","\uabb3":"\u13e3","\uabb4":"\u13e4","\uabb5":"\u13e5","\uabb6":"\u13e6","\uabb7":"\u13e7","\uabb8":"\u13e8","\uabb9":"\u13e9","\uabba":"\u13ea","\uabbb":"\u13eb","\uabbc":"\u13ec","\uabbd":"\u13ed","\uabbe":"\u13ee","\uabbf":"\u13ef","\u13f8":"\u13f0","\u13f9":"\u13f1","\u13fa":"\u13f2","\u13fb":"\u13f3","\u13fc":"\u13f4","\u13fd":"\u13f5","\u1c80":"\u0432","\u1c81":"\u0434","\u1c82":"\u043e","\u1c83":"\u0441","\u1c84":"\u0442","\u1c85":"\u0442","\u1c86":"\u044a","\u1c87":"\u0463","\u1c88":"\ua64b","\u1e96":"h\u0331","\u1e97":"t\u0308","\u1e98":"w\u030a","\u1e99":"y\u030a","\u1e9a":"a\u02be","\u1e9b":"\u1e61","\u1f50":"\u03c5\u0313","\u1f52":"\u03c5\u0313\u0300","\u1f54":"\u03c5\u0313\u0301","\u1f56":"\u03c5\u0313\u0342","\u1f80":"\u1f00\u03b9","\u1f81":"\u1f01\u03b9","\u1f82":"\u1f02\u03b9","\u1f83":"\u1f03\u03b9","\u1f84":"\u1f04\u03b9","\u1f85":"\u1f05\u03b9","\u1f86":"\u1f06\u03b9","\u1f87":"\u1f07\u03b9","\u1f90":"\u1f20\u03b9","\u1f91":"\u1f21\u03b9","\u1f92":"\u1f22\u03b9","\u1f93":"\u1f23\u03b9","\u1f94":"\u1f24\u03b9","\u1f95":"\u1f25\u03b9","\u1f96":"\u1f26\u03b9","\u1f97":"\u1f27\u03b9","\u1fa0":"\u1f60\u03b9","\u1fa1":"\u1f61\u03b9","\u1fa2":"\u1f62\u03b9","\u1fa3":"\u1f63\u03b9","\u1fa4":"\u1f64\u03b9","\u1fa5":"\u1f65\u03b9","\u1fa6":"\u1f66\u03b9","\u1fa7":"\u1f67\u03b9","\u1fb2":"\u1f70\u03b9","\u1fb3":"\u03b1\u03b9","\u1fb4":"\u03ac\u03b9","\u1fb6":"\u03b1\u0342","\u1fb7":"\u03b1\u0342\u03b9","\u1fbe":"\u03b9","\u1fc2":"\u1f74\u03b9","\u1fc3":"\u03b7\u03b9","\u1fc4":"\u03ae\u03b9","\u1fc6":"\u03b7\u0342","\u1fc7":"\u03b7\u0342\u03b9","\u1fd2":"\u03b9\u0308\u0300","\u1fd3":"\u03b9\u0308\u0301","\u1fd6":"\u03b9\u0342","\u1fd7":"\u03b9\u0308\u0342","\u1fe2":"\u03c5\u0308\u0300","\u1fe3":"\u03c5\u0308\u0301","\u1fe4":"\u03c1\u0313","\u1fe6":"\u03c5\u0342","\u1fe7":"\u03c5\u0308\u0342","\u1ff2":"\u1f7c\u03b9","\u1ff3":"\u03c9\u03b9","\u1ff4":"\u03ce\u03b9","\u1ff6":"\u03c9\u0342","\u1ff7":"\u03c9\u0342\u03b9","\ufb00":"ff","\ufb01":"fi","\ufb02":"fl","\ufb03":"ffi","\ufb04":"ffl","\ufb05":"st","\ufb06":"st","\ufb13":"\u0574\u0576","\ufb14":"\u0574\u0565","\ufb15":"\u0574\u056b","\ufb16":"\u057e\u0576","\ufb17":"\u0574\u056d"};
function tagKey(value){return value.toLowerCase().replace(/./gu,c=>tagCaseFold[c]||c);}
function normalizeTags(values){const seen=new Set();return values.map(t=>t.trim().replace(/^#+/,'').trim()).filter(t=>{const key=tagKey(t);if(seen.has(key))return false;seen.add(key);return true;});}
function composeCaption(caption,tagList){tagList=normalizeTags(tagList);const body=String(caption||'').trim();return body+(tagList.length?(body?'\n\n':'')+tagList.map(t=>'#'+t).join(' '):'');}
function contentIssues(a,requireReady=false){const l=limits(),errors=[];if(String(a.title||'').length>l.title)errors.push(`标题超过 ${l.title} 字`);if(composeCaption(a.caption,a.tags||[]).length>l.caption)errors.push(`正文与标签合计超过 ${l.caption} 字`);if(normalizeTags(a.tags||[]).length>l.tags)errors.push(`标签超过 ${l.tags} 个`);if(requireReady&&!String(a.title||'').trim())errors.push('请先确认原稿标题');if(requireReady&&!['none','contains_ai'].includes(a.settings?.ai_declaration))errors.push('请先确认内容 AI 声明');return errors;}
function blockingJob(){return S.jobs.find(j=>blockingStates.includes(j.state));}
function serverNow(){return serverClock?serverClock.ms+Math.max(0,performance.now()-serverClock.tick):Date.parse(S.server_time);}
function localStamp(ms){return new Date(ms+8*3600000).toISOString().slice(0,16).replace('T',' ');}
function timeProblem(r,current=serverNow()){
 const at=Date.parse(r.at.replace(' ','T')+'+08:00'),policy=S.schedule_policy||{},lead=policy.lead_minutes??60,days=policy.window_days??14;
 if(!Number.isFinite(at))return '计划时间格式无效，请修改时间';
 if(at<current+lead*60000)return `原定 ${r.at}，距当前 ${localStamp(current)} 不足 ${lead} 分钟；请改到 ${localStamp(Math.ceil((current+lead*60000)/60000)*60000)} 或之后（本地预检）`;
 if(at>current+days*86400000)return `原定 ${r.at}，超过本地未来 ${days} 天范围；请改到 ${localStamp(current+days*86400000)} 或之前`;
 return '';
}
function valid(r,current=serverNow()){return asset(r.asset_id)?.state==='ready'&&!timeProblem(r,current);}
function confirmationTimeIssue(rows){const row=rows.find(r=>timeProblem(r));return row?`《${title(asset(row.asset_id))}》${timeProblem(row)}。本批次尚未上传。`:'';}
function updateConfirmationTime(){
 if(!pendingConfirmation||!$('#confirmDialog').open)return;
 const problem=confirmationTimeIssue(pendingConfirmation.rows);
 $('#confirmTimeStatus').textContent=problem||`当前 ${localStamp(serverNow())} · 本地预检至少提前 ${S.schedule_policy?.lead_minutes??60} 分钟；页面停留期间会持续检查时间。`;
 $('#confirmTimeStatus').classList.toggle('invalid',!!problem);
 $('#confirmPublish').disabled=busy||!!problem;
 $('#confirmPublish').textContent=problem?'请先修改排期':'确认并发布整批';
}
function switchTab(next){tab=next;$$('nav button').forEach(b=>b.classList.toggle('active',b.dataset.tab===next));$$('.page').forEach(p=>p.classList.toggle('active',p.id===next));window.scrollTo({top:0,behavior:'smooth'});render();}
function render(){
 const counts={ready:ready().length,submitted:S.assets.filter(a=>['history','scheduled','published','reviewing'].includes(a.state)).length,excluded:S.assets.filter(a=>a.state==='excluded').length};
 $('#account').textContent=S.account||'账号未设置';$('#connection').textContent=S.executor.available?'批量执行器已就绪':'准备助手未连接';$('#executorModel').disabled=!!S.executor.running;$('#executorEffort').disabled=!!S.executor.running;if(document.activeElement!==$('#accountInput'))$('#accountInput').value=S.account||'';
 $('#stats').innerHTML=`<div class="stat"><strong>${counts.ready}</strong><span>待发布视频</span></div><div class="stat"><strong>${S.plan.filter(r=>asset(r.asset_id)?.state==='ready').length}</strong><span>本地排期</span></div><div class="stat"><strong>${counts.submitted}</strong><span>已提交记录</span></div>`;
 $('#chosenCount').textContent=selected().length;$('#planCount').textContent=visiblePlan().length;$('#jobCount').textContent=S.jobs.length;$('#readyCount').textContent=counts.ready;
 $('#selectionSummary').textContent=`已选择 ${selected().length} 条视频，生成排期后可逐条调整`;
 const current=$('#sourceFilter').value;$('#sourceFilter').innerHTML='<option value="">全部文件夹</option>'+S.folders.map(p=>`<option value="${esc(p)}">${esc(p.split(/[\\/]/).pop())}</option>`).join('');$('#sourceFilter').value=current;
 $('#folders').innerHTML=S.folders.map((f,i)=>`<div class="folder-row"><span class="folder-icon">▱</span><span class="path" title="${esc(f)}">${esc(f)}</span><button data-rescan="${i}">重新扫描</button><button data-remove="${i}" class="text" title="仅移除来源入口，已导入视频和原文件都会保留">移除</button></div>`).join('');
 const running=Object.values(S.scans||{}).filter(x=>x.state==='running');$('#scanState').textContent=running.length?'正在扫描视频、标题和封面，请稍候…':'';
 Object.entries(S.scans||{}).forEach(([id,x])=>{if(x.state!=='running'&&!scanNotices.has(id)){scanNotices.add(id);toast(x.state==='done'?`扫描完成：发现 ${x.found} 条，新增 ${x.added} 条`:`扫描未完成：${x.error}`);}});
 renderLiveStatus();if(tab==='library')renderAssets();if(tab==='schedule')renderPlan();if(tab==='jobs')renderJobs();
}
function renderAssets(){renderDedup();const list=filtered(),pages=Math.max(1,Math.ceil(list.length/12));page=Math.max(1,Math.min(page,pages));$('#assets').innerHTML=list.slice((page-1)*12,page*12).map(a=>`<article class="asset-card ${a.selected?'selected':''}"><label class="selector"><input type="checkbox" data-select="${esc(a.id)}" ${a.selected?'checked':''} aria-label="选择 ${esc(title(a))}"></label>${a.cover?`<img class="cover" loading="lazy" src="/media?id=${encodeURIComponent(a.id)}&kind=cover" data-preview="${esc(a.id)}" alt="${esc(title(a))}的封面">`:`<div class="cover-empty" data-preview="${esc(a.id)}">▷</div>`}<span class="duration">${Math.floor(a.duration/60)}:${String(Math.floor(a.duration%60)).padStart(2,'0')}</span><div class="card-body"><div class="card-title" title="${esc(title(a))}">${esc(title(a))}</div><div class="card-meta"><span title="${esc(a.date_basis)}">${esc(a.date)}</span><span>${esc(a.id)}</span></div><div class="card-foot"><span class="badge ${a.cover?'':'gray'}">${a.cover?'已有封面':'无封面'}</span><div><button data-preview="${esc(a.id)}">预览</button><button data-edit="${esc(a.id)}">设置</button></div></div></div></article>`).join('')||'<div class="empty"><strong>这里还没有待发布视频</strong>添加文件夹，或换一个筛选条件。</div>';$('#pageLabel').textContent=`${page} / ${pages} · 共 ${list.length} 条`;$('#prevPage').disabled=page===1;$('#nextPage').disabled=page===pages;}
function savePicked(){try{localStorage.setItem('xhs-picked-slots',JSON.stringify([...picked]));}catch{}}
function restorePicked(){try{const saved=JSON.parse(localStorage.getItem('xhs-picked-slots')||'[]');if(Array.isArray(saved))picked=new Set(saved.filter(x=>typeof x==='string'));}catch{}}
function visiblePlan(){const start=$('#startDate').value||S.preferences.start_date||'';return S.plan.filter(r=>!start||r.at.slice(0,10)>=start);}
function pickedRows(){return visiblePlan().filter(r=>picked.has(r.slot)&&asset(r.asset_id)?.state==='ready');}
function timeIssue(r){return `《${title(asset(r.asset_id))}》${timeProblem(r)}`;}
function renderPlan(){
 const visible=visiblePlan();
 picked=new Set([...picked].filter(slot=>visible.some(r=>r.slot===slot&&asset(r.asset_id)?.state==='ready')));savePicked();
 $('#planCount').textContent=visible.length;
 const groups={};visible.forEach(r=>(groups[r.at.slice(0,10)]??=[]).push(r));
 const options=ready().sort((a,b)=>a.date.localeCompare(b.date)),used=new Map(S.plan.map(r=>[r.asset_id,r.at]));
 $('#plan').innerHTML=Object.entries(groups).map(([day,rows])=>`<div class="day"><div class="day-head"><strong>${day} <small>${new Date(day+'T12:00:00').toLocaleDateString('zh-CN',{weekday:'long'})}</small></strong><div class="tools"><small>${rows.length} 条</small>${daySelectButton(day,rows)}</div></div>${rows.map(r=>{const a=asset(r.asset_id),ok=valid(r),movable=a.state==='ready'&&!S.executor.running;return `<div class="plan-row" data-plan-slot="${esc(r.slot)}" data-movable="${movable}"><button class="drag-handle" draggable="${movable}" data-drag-slot="${esc(r.slot)}" ${movable?'':'disabled'} aria-label="拖动 ${esc(title(a))}" title="拖动调整位置；也可按 Alt + 上下方向键">⠿</button><input type="checkbox" data-slot="${esc(r.slot)}" ${picked.has(r.slot)?'checked':''} ${a.state==='ready'?'':'disabled'} aria-label="选择 ${esc(r.at)}"><button class="plan-time" data-time-slot="${esc(r.slot)}" ${movable?'':'disabled'} aria-label="修改 ${esc(title(a))} 的发布时间：${esc(r.at)}" title="点击修改这一篇的发布时间">${r.at.slice(11)}<small>修改时间</small></button><div class="plan-content"><select data-replace="${esc(r.slot)}" aria-label="${esc(r.at)}发布的视频" ${movable?'':'disabled'}>${(a.state==='ready'?options.filter(o=>o.id===a.id||!used.has(o.id)):[a]).map(o=>{const taken=used.has(o.id)&&o.id!==a.id;return `<option value="${esc(o.id)}" ${o.id===a.id?'selected':''} ${taken?'disabled':''}>${taken?'[已排期 '+esc(used.get(o.id).slice(5))+'] ':''}${esc(title(o))}</option>`;}).join('')}</select>${a.state!=='ready'||!ok?`<span class="state ${a.state==='scheduled'?'good':'warn'}">${a.state==='ready'?timeIssue(r):labels[a.state]}</span>`:''}<div class="plan-meta">标题 ${String(a.title||'').length}/20 · 标签 ${(a.tags||[]).length}/10 · ${esc(aiLabels[effectiveAi(a)]||'按个人默认')}</div>${a.state==='ready'?`<button class="field-status ${needsAutoFields(a)?'needs-fields':'fields-ready'}" data-edit="${esc(a.id)}">${needsAutoFields(a)?'发布时自动匹配 · 查看':'设置已齐全 · 查看'}</button>`:''}</div><div class="plan-actions"><button data-preview="${esc(a.id)}" title="预览视频">视频</button><button data-cover="${esc(a.id)}" ${a.cover?'':'disabled'} title="${a.cover?'点击预览封面':'没有对应封面'}">封面</button><button data-edit="${esc(a.id)}" ${movable?'':'disabled'}>设置</button></div></div>`;}).join('')}</div>`).join('')||'<div class="empty"><strong>给选中的视频安排时间</strong>选择开始日期与每天条数，再点击“生成排期”。</div>';
 $('#scheduleSummary').textContent=visible.length?`${visible.length} 篇 · ${Object.keys(groups).length} 天 · 从所选开始日期显示 · 拖动 ⠿ 调整视频顺序`:'排期会自动保存';const rows=pickedRows(),issues=rows.filter(r=>needsAutoFields(asset(r.asset_id))),locked=blockingJob(),invalidTime=rows.find(r=>!valid(r));
 $('#batchSummary').textContent=S.dedup_busy?'正在本地查重，完成后可发布':locked?(locked.state==='awaiting_manual'?'上一篇等待你到小红书提交；提交后到“准备与核对”核对结果':'有未完成记录，请到“准备与核对”处理'):!S.account?'请先填写预期账号':!S.executor.available?'准备助手未连接：未找到本机 Codex；请检查安装后刷新':!rows.length?'可多选视频，一次检查标题、正文、标签和 AI 声明':issues.length?`已选择 ${rows.length} 篇，将自动匹配 ${issues.length} 篇的标题或封面，无需离开页面`:invalidTime?timeIssue(invalidTime):`已选择 ${rows.length} 篇 · 一次确认，按顺序提交并核验`;
 $('#batchEdit').disabled=!rows.length;
 $('#clearPicked').disabled=!rows.length;
 $('#publish').textContent=`确认发布 ${rows.length||''} 篇 →`;
 $('#publish').disabled=!!S.dedup_busy||!rows.length||!!S.executor.running||!!locked||!S.executor.available||!S.account||!!invalidTime;

}
function renderJobs(){
 const needsAttention=j=>['running','stopping','attention'].includes(j.state)||(j.results||[]).some(r=>['unknown','awaiting_manual'].includes(r.state));
 const current=S.jobs.filter((j,i)=>i===0||needsAttention(j)),older=S.jobs.filter((j,i)=>i>0&&!needsAttention(j));
 $('#jobsList').innerHTML=current.map(jobCard).join('')+(older.length?`<details class="panel"><summary>历史执行记录（${older.length} 次）</summary><p class="muted">以下是各次尝试当时的结果；视频当前是否已提交，请看上方最新结果及下方已核验记录。</p>${older.map(jobCard).join('')}</details>`:'')||'<div class="empty"><strong>还没有发布任务</strong>在排期中选中视频，一次确认整批发布。</div>';
 $('#history').innerHTML=S.assets.filter(a=>['history','scheduled','published','reviewing'].includes(a.state)).map(a=>`<div class="record"><time>${esc(a.scheduled_at)}</time><div>${esc(title(a))}</div><span class="badge">${esc(labels[a.state]||a.state)}</span></div>`).join('')||'<p class="muted">无历史记录</p>';
 const excluded=S.assets.filter(a=>['excluded','duplicate','duplicate_pending'].includes(a.state));$('#excludedCount').textContent=excluded.length;$('#excluded').innerHTML=excluded.map(a=>`<div class="record"><span>本次未发</span><div>${esc(title(a))}<p>${esc(a.dedup_evidence||a.dedup)}</p></div><span class="badge gray">${esc(labels[a.state])}</span></div>`).join('');
}
async function refresh(){S=await api('state');render();}
function editDraft(){return {title:$('#editTitle').value,caption:$('#editCaption').value.trim(),tags:normalizeTags(tags),settings:{collection:$('#editCollection').value.trim(),visibility:$('#editVisibility').value,allow_download:$('#editDownload').checked,location:false,activity:false,ai_declaration:$('#editAiDeclaration').value}};}
function editCounters(){const a=editDraft(),l=limits(),total=composeCaption(a.caption,tags).length,errors=contentIssues(a);$('#titleCounter').textContent=`${a.title.length}/${l.title}`;$('#captionCounter').textContent=`正文 ${a.caption.length} 字`;$('#captionTotal').textContent=`正文与标签合计 ${total}/${l.caption} 字（包含标签符号、间隔与换行）`;$('#tagCounter').textContent=`已选 ${tags.length}/${l.tags}`;$('#titleCounter').classList.toggle('invalid',a.title.length>l.title);$('#captionTotal').classList.toggle('invalid',total>l.caption);$('#tagCounter').classList.toggle('invalid',tags.length>l.tags);$('#editValidation').textContent=errors.join('；');$('#saveEdit').disabled=errors.length>0;}
function tagUI(){tags=normalizeTags(tags);$('#tagPool').innerHTML=normalizeTags([...tags,...(S.tag_pool||[])]).map(t=>`<button type="button" data-tag="${esc(t)}" aria-pressed="${tags.includes(t)}" class="${tags.includes(t)?'selected':''}">#${esc(t)}</button>`).join('');editCounters();}
function addTag(){const t=$('#newTag').value.trim().replace(/^#+/,'').trim();if(!t)return toast('请输入相关标签');if(/[\s#\x00-\x1f]/u.test(t))return toast('请一次添加一个标签，不包含空格或 #');if(tags.some(x=>tagKey(x)===tagKey(t)))return toast('这个标签已经添加（忽略大小写）');if(tags.length>=limits().tags)return toast(`最多添加 ${limits().tags} 个标签`);tags.push(t);$('#newTag').value='';tagUI();}
function openEdit(id){const a=asset(id);if(a.state!=='ready')return toast('这篇内容已锁定，请先在准备记录中核对');editing=id;tags=normalizeTags(a.tags||[]);$('#editTitle').value=a.title||'';$('#titleSource').textContent='标题来源：'+(a.title_source||'尚未确认，请对照原稿或成片填写');$('#editCaption').value=a.caption||'';$('#editCover').value=a.cover||'';$('#collectionOptions').innerHTML=(S.collections||[]).map(c=>`<option value="${esc(c)}"></option>`).join('');$('#editCollection').value=a.settings.collection||'';$('#editVisibility').value=a.settings.visibility||'公开';$('#editDownload').checked=!!a.settings.allow_download;$('#editAiDeclaration').value=a.settings.ai_declaration||'unknown';$('#newTag').value='';tagUI();$('#editDialog').showModal();}
function preview(id){const a=asset(id);$('#previewTitle').textContent=title(a);$('#previewVideo').src='/media?id='+encodeURIComponent(id);$('#previewPath').textContent=a.video;$('#previewDialog').showModal();}
function previewCover(id){const a=asset(id);if(!a.cover)return toast('这条视频没有对应封面');$('#coverTitle').textContent=title(a)+' · 封面';$('#coverPreviewImage').alt=title(a)+'的封面';$('#coverPreviewImage').src='/media?id='+encodeURIComponent(id)+'&kind=cover';$('#coverNote').textContent='发布时使用这张已有封面';$('#coverDialog').showModal();}
function openTimeEdit(slot){
 const row=S.plan.find(r=>r.slot===slot);if(!row||asset(row.asset_id)?.state!=='ready'||S.executor.running||blockingJob())return toast('这篇内容当前不能修改排期');
 timeEdit={slot,revision:S.plan_revision,rows:S.plan.map(r=>({...r}))};
 $('#timeTitle').textContent=title(asset(row.asset_id));$('#timeValue').value=row.at.replace(' ','T');$('#timeValidation').textContent='';$('#timeDialog').showModal();
}
async function movePlan(source,target,placement){try{await api('plan/move',{source,target,placement,revision:S.plan_revision});await refresh();toast('顺序已保存，发布时间保持不变');}catch(e){await refresh();throw e;}}
function clearDrag(){draggingSlot=null;$$('.dragging,.drop-before,.drop-after').forEach(el=>el.classList.remove('dragging','drop-before','drop-after'));}
document.addEventListener('dragstart',e=>{const handle=e.target.closest('[data-drag-slot]');if(!handle||handle.disabled||busy)return e.preventDefault();draggingSlot=handle.dataset.dragSlot;e.dataTransfer.setData('text/plain',draggingSlot);e.dataTransfer.effectAllowed='move';handle.closest('.plan-row').classList.add('dragging');});
document.addEventListener('dragover',e=>{const row=e.target.closest('.plan-row[data-movable="true"]');if(!draggingSlot||!row||row.dataset.planSlot===draggingSlot)return;e.preventDefault();e.dataTransfer.dropEffect='move';$$('.drop-before,.drop-after').forEach(el=>el.classList.remove('drop-before','drop-after'));row.classList.add(e.clientY<row.getBoundingClientRect().top+row.offsetHeight/2?'drop-before':'drop-after');if(e.clientY<90)window.scrollBy(0,-18);else if(e.clientY>innerHeight-90)window.scrollBy(0,18);});
document.addEventListener('drop',e=>{const row=e.target.closest('.plan-row[data-movable="true"]');if(!draggingSlot||!row)return;e.preventDefault();const source=draggingSlot,target=row.dataset.planSlot,placement=e.clientY<row.getBoundingClientRect().top+row.offsetHeight/2?'before':'after';clearDrag();if(source!==target)action(()=>movePlan(source,target,placement));});
document.addEventListener('dragend',clearDrag);
document.addEventListener('keydown',e=>{const handle=e.target.closest('[data-drag-slot]');if(!handle||handle.disabled||!e.altKey||!['ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();const rows=visiblePlan().filter(r=>asset(r.asset_id).state==='ready'),i=rows.findIndex(r=>r.slot===handle.dataset.dragSlot),j=i+(e.key==='ArrowUp'?-1:1);if(j<0||j>=rows.length)return;action(async()=>{await movePlan(rows[i].slot,rows[j].slot,e.key==='ArrowUp'?'before':'after');document.querySelector(`[data-drag-slot="${rows[j].slot}"]`)?.focus();});});
async function scan(folder){if(!folder.trim())throw Error('请先粘贴文件夹地址');await api('scan',{folder});$('#folderInput').value='';await refresh();toast('已开始扫描，完成后视频会显示在列表中');}
document.addEventListener('click',e=>{const b=e.target.closest('button,[data-preview]');if(!b)return;
 if(b.dataset.selectDay){toggleDay(b.dataset.selectDay);return;}
 if(b.dataset.clearReview)return action(async()=>{const result=await api('dedup/clear',{group:b.dataset.clearReview,id:b.dataset.reviewId||null,revision:S.dedup_revision});await refresh();toast(`已记住人工核对结果，恢复 ${result.released.length} 条可选视频`);});
 if(b.dataset.deep)return action(async()=>{await api('dedup',{group:b.dataset.deep});await refresh();});
 if(b.id==='checkDuplicates')return action(async()=>{await api('dedup',{});await refresh();});
 if(b.dataset.tab)return switchTab(b.dataset.tab);
 if(b.dataset.returnPlan){picked=new Set(visiblePlan().filter(r=>asset(r.asset_id)?.state==='ready').map(r=>r.slot));return switchTab('schedule');}
 if(b.dataset.close)return $('#'+b.dataset.close).close();
 if(b.dataset.timeSlot)return openTimeEdit(b.dataset.timeSlot);
 if(b.dataset.edit)return openEdit(b.dataset.edit);
 if(b.dataset.preview)return preview(b.dataset.preview);
 if(b.dataset.cover)return previewCover(b.dataset.cover);
 if(b.dataset.tag){const t=b.dataset.tag;if(tags.includes(t))tags=tags.filter(x=>x!==t);else if(tags.length<limits().tags)tags.push(t);else return toast(`最多添加 ${limits().tags} 个标签`);return tagUI();}
 if(b.dataset.rescan)return action(()=>scan(S.folders[+b.dataset.rescan]));
 if(b.dataset.remove)return action(async()=>{await api('folder/remove',{folder:S.folders[+b.dataset.remove]});await refresh();toast('已移除来源入口，已导入视频和原文件均保留');});
 if(b.dataset.verify)return action(async()=>{await api('verify',{id:b.dataset.verify});await refresh();});
 if(b.dataset.release)return action(async()=>{const r=await api('release',{id:b.dataset.release});await refresh();toast(`已恢复 ${r.released} 条，可重新排期`);});
 if(b.id==='stopJob')return action(async()=>{await api('stop',{});await refresh();});
});
document.addEventListener('change',e=>{const el=e.target;
 if(el.dataset.select)action(async()=>{await api('select',{ids:[el.dataset.select],selected:el.checked});await refresh();});
 if(el.dataset.slot){if(el.checked)picked.add(el.dataset.slot);else picked.delete(el.dataset.slot);renderPlan();}
 if(el.dataset.replace)action(async()=>{try{await api('plan/replace',{slot:el.dataset.replace,asset_id:el.value,revision:S.plan_revision});toast('已更换视频');}finally{await refresh();}});
});
$('#timeForm').onsubmit=e=>{e.preventDefault();action(async()=>{
 if(!timeEdit)return;const at=$('#timeValue').value.replace('T',' '),changed=timeEdit.rows.find(r=>r.slot===timeEdit.slot),problem=timeProblem({...changed,at});
 if(problem){$('#timeValidation').textContent=problem;return;}
 const rows=timeEdit.rows.map(r=>r.slot===timeEdit.slot?{...r,at}:r);
 try{await api('plan',{rows,revision:timeEdit.revision});$('#timeDialog').close();await refresh();toast('已修改这一篇的时间，其余排期保持不变');}catch(e){$('#timeValidation').textContent=e.message;}
});};
$('#timeDialog').addEventListener('close',()=>{timeEdit=null;});
$('#folderForm').onsubmit=e=>{e.preventDefault();action(()=>scan($('#folderInput').value));};
$('#accountForm').onsubmit=e=>{e.preventDefault();action(async()=>{await api('account',{account:$('#accountInput').value.trim()});await refresh();toast('预期账号已保存，准备时会核对平台账号');});};
$('#search').oninput=()=>{page=1;renderAssets();};$('#sourceFilter').onchange=()=>{page=1;renderAssets();};
$('#prevPage').onclick=()=>{page--;renderAssets();};$('#nextPage').onclick=()=>{page++;renderAssets();};
$('#selectAll').onclick=()=>action(async()=>{await api('select',{ids:filtered().map(a=>a.id),selected:true});await refresh();});
$('#clearSelection').onclick=()=>action(async()=>{await api('select',{ids:ready().map(a=>a.id),selected:false});await refresh();});
$('#goSchedule').onclick=()=>{if(!selected().length)return toast('请先选择要发布的视频');switchTab('schedule');};
function scheduleFields(){return {count:+$('#dailyCount').value,start_time:$('#startHour').value+':'+$('#startMinute').value,end_time:$('#endHour').value+':'+$('#endMinute').value};}
let rhythmRequest=0;
async function rhythm(){const request=++rhythmRequest;$('#arrange').disabled=true;try{const t=await api('times?'+new URLSearchParams(scheduleFields()));if(request!==rhythmRequest)return;$('#rhythmDescription').textContent=`模板首条 ${t[0]} · 末条 ${t[t.length-1]} · 每天 ${t.length} 条`;$('#rhythmDescription').classList.remove('invalid');$('#timeChips').innerHTML=t.map(x=>`<span>${x}</span>`).join('');$('#arrange').disabled=false;}catch(e){if(request!==rhythmRequest)return;$('#rhythmDescription').textContent=e.message;$('#rhythmDescription').classList.add('invalid');$('#timeChips').innerHTML='';}}
['dailyCount','startHour','startMinute','endHour','endMinute'].forEach(id=>$('#'+id).onchange=rhythm);
$('#startDate').onchange=()=>{if(S)renderPlan();};
$('#arrange').onclick=()=>action(async()=>{const ids=selected().map(a=>a.id);if(!ids.length)throw Error('请先在“选择视频”中勾选视频');await api('arrange',{ids,date:$('#startDate').value,...scheduleFields()});picked.clear();await refresh();toast('排期和发布节奏已保存');});
$('#selectEligible').onclick=()=>{picked=new Set(visiblePlan().filter(r=>asset(r.asset_id)?.state==='ready').map(r=>r.slot));renderPlan();};
$('#clearPicked').onclick=()=>{picked.clear();renderPlan();};
$('#editForm').onsubmit=e=>{e.preventDefault();action(async()=>{const draft=editDraft(),errors=contentIssues(draft);if(errors.length)throw Error(errors.join('；'));await api('edit',{id:editing,patch:{...draft,cover:$('#editCover').value.trim().replace(/^"|"$/g,'')}});$('#editDialog').close();await refresh();toast('已保存这篇内容的设置');});};
$('#editTitle').oninput=editCounters;$('#editCaption').oninput=editCounters;$('#editAiDeclaration').onchange=editCounters;
$('#addTag').onclick=addTag;$('#newTag').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();addTag();}};
$('#rematch').onclick=()=>action(async()=>{const matched=normalizeTags((await api('tags',{id:editing,title:$('#editTitle').value})).tags);if(matched.length>limits().tags)throw Error('匹配标签超过上限，请手动选择');tags=matched;tagUI();});
$('#previewDialog').addEventListener('close',()=>{$('#previewVideo').pause();$('#previewVideo').removeAttribute('src');$('#previewVideo').load();});
$('#coverDialog').addEventListener('close',()=>$('#coverPreviewImage').removeAttribute('src'));
function openPublishConfirmation(){const rows=pickedRows();if(!rows.length)return toast('请先选择待发布内容');const timeError=confirmationTimeIssue(rows);if(timeError)return toast(timeError);if(!S.account||blockingJob())return toast('请先填写账号，并处理未完成的任务');if(!S.preparation_revision)return toast('请刷新工作台后重新检查内容');const errors=rows.flatMap(r=>contentIssues({...asset(r.asset_id),title:''},false));if(errors.length)return toast(errors.join('；'));$('#confirmAccount').textContent=`账号：${S.account} · 本次 ${rows.length} 篇 · Codex / ${executorName()} / ${effortName()}推理`;$('#confirmItems').innerHTML=rows.map(r=>{const a=asset(r.asset_id);return `<div class="record"><time>${esc(r.at)}</time><div>${esc(a.title||a.name)}${!a.title?' · 标题将在队列中自动匹配':''}<p>${esc(composeCaption(a.caption,a.tags||[]))}</p><p>${esc(a.settings.visibility)} · ${a.settings.allow_download?'允许下载（页面支持时）':'不允许下载（页面支持时）'} · ${esc(a.settings.collection||'不添加合集')} · ${a.cover?'已有封面':'将自动匹配本片封面或提取原帧'}</p><p>AI 声明：${esc(aiLabels[a.settings.ai_declaration==='unknown'?S.preparation_defaults?.ai_declaration:a.settings.ai_declaration]||'未配置：本篇将单独留待处理')}</p></div></div>`;}).join('');pendingConfirmation=Object.freeze({rows:Object.freeze(rows.map(r=>Object.freeze({...r}))),mode:'batch_publish',auto_prepare:true,slots:Object.freeze(rows.map(r=>r.slot)),revision:S.preparation_revision,model:$('#executorModel').value,reasoning_effort:$('#executorEffort').value});$('#confirmDialog').showModal();updateConfirmationTime();};
$('#confirmDialog').addEventListener('close',()=>{pendingConfirmation=null;});
$('#confirmPublish').onclick=()=>action(async()=>{const confirmed=pendingConfirmation;if(!confirmed)throw Error('请重新打开确认窗口检查内容');$('#confirmPublish').disabled=true;try{try{S=await api('state');if(S.preparation_revision!==confirmed.revision)throw Error('内容或排期已变化，请重新核对整批明细');const timeError=confirmationTimeIssue(confirmed.rows);if(timeError)throw Error(timeError);const {rows,...request}=confirmed;await api('publish',{...request,confirmed:true});}catch(e){$('#confirmDialog').close();pendingConfirmation=null;try{await refresh();}catch{}throw Error(e.message+'；请重新检查内容或排期，再打开确认窗口。不会自动重试。');}$('#confirmDialog').close();confirmed.slots.forEach(slot=>picked.delete(slot));savePicked();await refresh();switchTab('jobs');}finally{if($('#confirmDialog').open)updateConfirmationTime();else $('#confirmPublish').disabled=false;}});
(async()=>{try{S=await api('state');restorePicked();$('#executorModel').innerHTML=S.executor.models.map(m=>`<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('');$('#executorModel').value=S.executor.default.model;$('#executorEffort').innerHTML=S.executor.reasoning_efforts.map(r=>`<option value="${r.id}">${r.name}</option>`).join('');$('#executorEffort').value=S.executor.default.reasoning_effort;$('#dailyCount').innerHTML=Array.from({length:10},(_,i)=>`<option value="${i+1}">${i+1} 篇 / 天</option>`).join('');$('#dailyCount').value=S.preferences.count||1;$('#startDate').value=S.preferences.start_date;['start','end'].forEach(prefix=>{['Hour','Minute'].forEach(part=>{$('#'+prefix+part).innerHTML=Array.from({length:part==='Hour'?24:6},(_,i)=>String(part==='Hour'?i:i*10).padStart(2,'0')).map(v=>`<option value="${v}">${v}</option>`).join('');});const [h,m]=(S.preferences[prefix+'_time']||(prefix==='start'?'10:00':'20:00')).split(':');$('#'+prefix+'Hour').value=h;$('#'+prefix+'Minute').value=m;});render();await rhythm();setInterval(async()=>{if(busy||draggingSlot||$$('dialog[open]').length)return;try{const fresh=await api('state'),changed=JSON.stringify(fresh.assets)!==JSON.stringify(S.assets)||JSON.stringify(fresh.jobs)!==JSON.stringify(S.jobs)||JSON.stringify(fresh.scans)!==JSON.stringify(S.scans)||JSON.stringify(fresh.dedup_status)!==JSON.stringify(S.dedup_status)||fresh.dedup_busy!==S.dedup_busy||fresh.plan_revision!==S.plan_revision||fresh.account!==S.account||JSON.stringify(fresh.executor)!==JSON.stringify(S.executor);const previousTimes=S.plan.map(r=>valid(r,Date.parse(S.server_time)));S=fresh;if(changed||(tab==='schedule'&&S.plan.some((r,i)=>valid(r)!==previousTimes[i])))render();else if(S.executor.running){renderLiveStatus();if(tab==='jobs')renderJobs();}}catch{}},3500);}catch(e){toast('工作台连接失败：'+e.message);}})();

setInterval(updateConfirmationTime,1000);

function daySelectButton(day,rows){
 const eligible=rows.filter(r=>asset(r.asset_id)?.state==='ready'),n=eligible.filter(r=>picked.has(r.slot)).length;
 return `<button data-select-day="${esc(day)}" ${!eligible.length||S.executor.running||S.dedup_busy?'disabled':''} aria-label="${esc(day)} ${n&&n===eligible.length?'取消当日全选':'全选当天待发布'}">${n&&n===eligible.length?'取消全选':'全选当天'} <small>${n}/${eligible.length}</small></button>`;
}
function toggleDay(day){
 if(S.executor.running||S.dedup_busy)return;
 const rows=visiblePlan().filter(r=>r.at.slice(0,10)===day&&asset(r.asset_id)?.state==='ready'),all=rows.every(r=>picked.has(r.slot));
 rows.forEach(r=>all?picked.delete(r.slot):picked.add(r.slot));renderPlan();
}
function renderDedup(){
 const status=S.dedup_status||{},groups=S.dedup_groups||[],locked=!!S.dedup_busy||!!blockingJob();
 const held=S.assets.filter(a=>['duplicate_pending','duplicate_review'].includes(a.state)||a.state==='duplicate_checking'&&!S.dedup_busy);
 const excluded=S.assets.filter(a=>['excluded','duplicate','history','scheduled','published','reviewing'].includes(a.state));
 $('#dedupStatus').textContent=status.message?status.message+(status.state==='running'&&status.total?`（${status.completed}/${status.total}）`:''):'首次使用请查重；添加文件夹后自动检查。本地历史不等于平台全部历史。';
 $('#checkDuplicates').disabled=locked;
 $('#deepAll').disabled=locked||!groups.length;
 $('#dedupCount').textContent=held.length;
 const clearButton=(g,id='')=>`<button data-clear-review="${esc(g.id)}" data-review-id="${esc(id)}" ${locked?'disabled':''}>${id?'已核对此视频，不重复':'整组已核对，均不重复'}</button>`;
 const card=(a,g=null)=>`<div class="dedup-item"><strong>${esc(title(a))}</strong><span class="badge gray">${esc(labels[a.state]||a.state)}</span><small>${esc(a.video)}</small><small>${esc(dedupReason(a.dedup_evidence||''))}</small><div class="tools"><button data-preview="${esc(a.id)}">预览视频</button>${g&&!g.error&&g.pairs?.length&&a.state==='duplicate_review'&&!a.dedup_error?clearButton(g,a.id):''}</div></div>`;
 $('#dedupGroups').innerHTML=groups.map(g=>`<article class="dedup-group"><div class="section-head"><strong>疑似重复组 · ${g.ids.length} 条</strong><div class="tools"><button data-deep="${esc(g.id)}" ${locked?'disabled':''}>深度排查</button>${!g.error&&g.pairs?.length&&g.ids.every(id=>asset(id)?.state==='duplicate_review'&&!asset(id)?.dedup_error)?clearButton(g):''}</div></div><p class="muted">${esc(dedupReason(g.error||g.pairs?.map(p=>p.reason).filter((x,i,a)=>a.indexOf(x)===i).join('；')||'需要重新检查文件'))}</p>${g.ids.map(id=>asset(id)).filter(Boolean).map(a=>card(a,g)).join('')}</article>`).join('')+held.filter(a=>a.state==='duplicate_pending'||!groups.some(g=>g.ids.includes(a.id))).map(a=>`<article class="dedup-group">${card(a)}<p class="muted">${a.state==='duplicate_pending'?'此前平台疑似旧作，需要核对原平台记录；本地抽帧不能解除这个限制。':'文件检查尚未完成，请重新查重。'}</p></article>`).join('');
 $('#dedupEmpty').hidden=!!held.length;
 $('#dedupExcluded').innerHTML=excluded.map(a=>card(a)).join('')||'<p class="muted">暂无排除或已提交记录</p>';
 $('#dedupExcludedCount').textContent=excluded.length;
}

function dedupReason(value){
 if(String(value).includes('timed out after'))return '本条视频解码超时，暂留待查；其他视频继续处理。可单独点击深度排查重试。';
 if(String(value).includes('WinError 2')||String(value).includes('No such file'))return '原视频文件已移动或不存在，请恢复原文件后重新查重。';
 return value;
}

// The confirmation authorizes source-bound matching inside the batch.
$('#publish').onclick=()=>action(async()=>openPublishConfirmation());
