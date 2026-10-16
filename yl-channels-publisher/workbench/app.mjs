import {moveSlot, localDate, validatePlan, toMarkdown, EXECUTION_MODELS} from './plan-core.mjs';

const $ = s => document.querySelector(s);
const esc = s => String(s??'').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const preferences=await fetch('/api/preferences').then(r=>{if(!r.ok)throw new Error('无法读取本机配置');return r.json();});
const state = {
  sources: [{id:crypto.randomUUID(), path:'', res:null}],
  scanning:false,
  count: 6,
  slots: [],
  defaults: { loc:'不显示位置', orig:true, act:'不参与活动', tags:'' },
  goods: [...(preferences.products||[]),'不挂商品'],
  goodsUsed: new Set(),
};

const TAGS = (preferences.tags||[]).map(t=>t.startsWith('#')?t:'#'+t).join(' ');

/* ---------- 时间轴 ---------- */
function parseTime(s){ const [h,m]=s.split(':').map(Number); return h*60+m; }
function fmtTime(min){ min=((min%1440)+1440)%1440; return String(Math.floor(min/60)).padStart(2,'0')+':'+String(min%60).padStart(2,'0'); }
function calcTimes(){
  const n = state.count, a = parseTime($('#startTime').value), b = parseTime($('#endTime').value);
  if (n<2 || !Number.isFinite(a) || !Number.isFinite(b) || b<=a || b-a<n-1) return [];
  const gap = (b-a)/(n-1);
  return Array.from({length:n},(_,i)=>Math.round(a+gap*i));
}

/* ---------- 来源 ---------- */
function renderSources(){
  $('#srcs').innerHTML = state.sources.map((s,i)=>{
    const r = s.res;
    let meta = '';
    if (r) {
      if (!r.ok) meta = `<span class="bad">⚠ ${esc(r.error)}</span>`;
      else {
        const miss = r.missingCover?.length||0;
        meta = `共 <b>${r.count}</b> 条成片` +
          (miss ? `　<span class="bad">· ${miss} 条未找到同名封面</span>` : '　· 封面全部匹配') + (r.warnings?.length ? `<br><span class="bad">${r.warnings.map(esc).join('；')}</span>` : '');
      }
    }
    const dis = state.sources.length<=1 || state.scanning?'disabled':'';
    return `<div class="src">
      <div class="src-head">
        <div class="field"><label>文件夹 ${i+1}${i>0?'　<span style="color:#c3cad2;font-weight:400">（可选，用于视频分散在多个文件夹时）</span>':''}</label>
          <input type="text" data-i="${i}" class="srcPath" ${state.scanning?'disabled':''} placeholder="请输入成片文件夹的完整路径" value="${esc(s.path)}">
        </div>
        
        <button class="sm srcClear" data-i="${i}" ${dis}>移除</button>
      </div>
      ${meta?`<div class="src-meta">${meta}</div>`:''}
    </div>`;
  }).join('');
}

/* ---------- 时间点 ---------- */
function syncSlots(){
  const times = calcTimes();
  if (!times.length) { renderTimeline(); return; }
  if (state.slots.length === times.length && state.slots.every((s,i)=>s.time===fmtTime(times[i]))) return;
  const old = state.slots;
  // 时间点数量变化时，按序号保留已有选择，避免改条数就把已配好的全冲掉
  state.slots = times.map((t,i)=> Object.assign(
    { srcIdx:0, video:null, goods:'默认', orig:null, loc:null, act:null, title:null },
    old[i]||{}
  , { time: fmtTime(t) }));
  renderSlots();
}
function renderTimeline(){
  const times = calcTimes();
  $('#timeline').innerHTML = times.map((t,i)=>{
    const s = state.slots[i];
    const n = s?.video ? esc(s.video.name.replace(/\.[^.]+$/,'').replace(/_最终版.*$/,'')) : '<span style="color:#c3cad2">待选</span>';
    return `<div class="tl-item"><div class="tl-time">${fmtTime(t)}</div><div class="tl-bar"></div><div class="tl-lbl">${n}</div></div>`;
  }).join('');
  const gap = times.length>1 ? ((times[1]-times[0])/60).toFixed(1) : '0';
  $('#tlHint').textContent = times.length
    ? `均匀分布，共 ${times.length} 条，间隔 ${gap} 小时（${fmtTime(times[0])} → ${fmtTime(times[times.length-1])}）`
    : '结束时间需晚于起始时间';
}

function allVideos(){ return state.sources.flatMap((s,i)=> (s.res?.ok? s.res.items.map(v=>({...v, srcIdx:i, sourceId:s.id, sourcePath:s.res.path})) : [])); }

function renderSlots(){
  // 视频下拉按文件夹分组；同文件夹内按序号排（1、2、3…10），便于按顺序排片
  const groups = state.sources
    .map((s,i)=>({ i, id:s.id, ok: s.res?.ok, name: (s.path||'').split(/[\\\/]/).filter(Boolean).pop()||`文件夹 ${i+1}`, items: (s.res?.items)||[] }))
    .filter(g=>g.ok && g.items.length);
  const opts = groups.length
    ? groups.map(g=>`<optgroup label="文件夹 ${g.i+1} · ${esc(g.name)}（${g.items.length} 条）">${
        g.items.map(v=>`<option value="${vkey(g.id, v.idx)}">${esc(v.name.replace(/\.[^.]+$/,''))}${v.cover?'':'　⚠ 无封面'}</option>`).join('')
      }</optgroup>`).join('')
    : '<option value="">— 先扫描文件夹 —</option>';

  $('#slots').innerHTML = state.slots.map((s,i)=>{
    const ovr = s.orig===null&&s.loc===null&&s.act===null&&s.goods==='默认'&&s.title===null;
    const title = s.video ? (s.title || s.video.draftTitle || '') : '';
    return `<tr data-i="${i}">
      <td class="tcell">${s.time}</td>
      <td class="order-cell"><button class="drag-handle" draggable="true" aria-label="拖动第 ${i+1} 条调整顺序，也可按 Alt 加上下方向键" title="拖动调整顺序 · Alt + ↑ / ↓">⠿</button><div class="move-buttons"><button class="move-up" aria-label="上移第 ${i+1} 条" ${i===0?'disabled':''}>↑</button><button class="move-down" aria-label="下移第 ${i+1} 条" ${i===state.slots.length-1?'disabled':''}>↓</button></div></td>
      <td class="pick"><select class="sPick"><option value="">— 选择视频 —</option>${opts}</select>
        <div class="rowline">${s.video ? esc(title) : '<span style="color:#c3cad2">未选</span>'}</div></td>
      <td><button class="sm preview-video" ${s.video?'':'disabled'}>▶ 预览</button></td>
      <td>${s.video ? (s.video.cover?'<span class="tag ok">已匹配</span>':'<span class="tag miss">缺</span>') : '<span class="tag none">—</span>'}</td>
      <td><select class="sGoods">${['默认',...state.goods].map(g=>`<option ${g===s.goods?'selected':''}>${esc(g)}</option>`).join('')}</select></td>
      <td><div class="ovr"><button class="sm ovrBtn" data-a="reset">${ovr?'跟随默认':'已改'}</button><button class="sm ovrBtn" data-a="edit">调整…</button></div></td>
    </tr>`;
  }).join('');

  // 下拉重建后回填选中态
  const picks = $('#slots').querySelectorAll('.sPick');
  state.slots.forEach((s,i)=>{ if (s.video) picks[i].value = curKey(s); });

  renderTimeline();
  renderIssues();
}
function vkey(si, vi){ return si + '|' + vi; }
function curKey(s){ return s.video ? vkey(s.video.sourceId, s.video.idx) : ''; }

function renderIssues(){
  const miss = state.slots.filter(s=>!s.video).length;
  const noCov = state.slots.filter(s=>s.video && !s.video.cover).length;
  const noIdx = state.slots.filter(s=>s.video && s.video.srcIdx>0).length;
  const parts = [];
  if (miss) parts.push(`<b>${miss}</b> 个时间点还没选视频`);
  if (noCov) parts.push(`<b>${noCov}</b> 条选中视频没匹配到封面，发布前需手动补`);
  if (noIdx) parts.push(`有 ${noIdx} 条引用的是第 2/3 个文件夹`);
  $('#issues').innerHTML = parts.length ? `<div class="warnbox">${parts.join('　·　')}</div>` : (state.slots.length?`<div class="hint" style="margin-top:10px">✓ ${state.slots.length} 个时间点均已配齐视频与封面</div>`:'');
}

/* ---------- 交互 ---------- */
$('#addSrc').onclick = () => { if(state.sources.length>=3) return; state.sources.push({id:crypto.randomUUID(),path:'',res:null}); renderSources(); };
$('#srcs').addEventListener('input', e => {
  if (e.target.classList.contains('srcPath')) { const source = state.sources[+e.target.dataset.i]; source.path = e.target.value; source.res = null; clearSourceSelection(source.id); renderSlots(); }
});
$('#srcs').addEventListener('click', e => {
  const t = e.target;
  if (t.classList.contains('srcClear')) { const removed = state.sources.splice(+t.dataset.i,1)[0]; clearSourceSelection(removed.id); renderSources(); renderSlots(); }
});

function clearSourceSelection(id) {
  state.slots.forEach(s => { if(s.video?.sourceId === id) { s.video=null; s.title=null; } });
}

$('#scanBtn').onclick = async () => {
  const paths = state.sources.map(s=>s.path.trim()).filter(Boolean);
  if (!paths.length) { $('#status').textContent = '请先填写至少一个文件夹地址'; return; }
  state.scanning = true; renderSources(); $('#addSrc').disabled = true;
  $('#scanBtn').disabled = true;
  $('#scanBtn').innerHTML = '<span class="spin"></span> 扫描中…';
  try {
    const r = await fetch('/api/scan', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({paths}) });
    const data = await r.json();
    if(!r.ok || !Array.isArray(data.results)) throw new Error(data.error || '扫描服务返回异常');
    let k = 0;
    state.sources.forEach(s => { if (s.path.trim() && data.results[k]) s.res = data.results[k++]; });
    // 自动分配视频到空时间点：优先有封面的成片
    const pool = allVideos();
    state.slots.forEach(s => { if(s.video) { const found = pool.find(v=>v.full===s.video.full && v.sourceId===s.video.sourceId); s.video=found || null; if(!found) s.title=null; } });
    const used = new Set(state.slots.filter(s=>s.video).map(s=>s.video.full));
    const ready = pool.filter(v=>v.cover&&!used.has(v.full)), bare = pool.filter(v=>!v.cover&&!used.has(v.full));
    const pickOrder = [...ready, ...bare];
    state.slots.forEach(s => { if (!s.video && pickOrder.length) { s.video = pickOrder.shift(); s.srcIdx = s.video.srcIdx; } });
    renderSources(); renderSlots();
    const bad = state.sources.filter(s=>s.res && !s.res.ok);
    $('#status').textContent = bad.length ? '部分文件夹读取失败' : `扫描完成 · ${allVideos().length} 条成片`;
  } catch (err) {
    $('#status').textContent = '扫描失败：' + err.message;
  }
  state.scanning = false; renderSources(); $('#addSrc').disabled = false;
  $('#scanBtn').disabled = false;
  $('#scanBtn').textContent = '扫描文件夹';
};

$('#countChips').innerHTML = [2,3,4,5,6,7,8].map(n=>`<button class="chip ${n===state.count?'on':''}" data-n="${n}">${n} 条</button>`).join('');
$('#countChips').onclick = e => {
  const c = e.target.closest('.chip'); if(!c) return;
  state.count = +c.dataset.n;
  document.querySelectorAll('#countChips .chip').forEach(x=>x.classList.toggle('on', +x.dataset.n===state.count));
  syncSlots();
};
$('#startTime').oninput = syncSlots;
$('#endTime').oninput = syncSlots;
$('#date').oninput = () => {};

$('#slots').addEventListener('change', e => {
  const tr = e.target.closest('tr'); if(!tr) return;
  const i = +tr.dataset.i, s = state.slots[i], t = e.target;
  if (t.classList.contains('sPick')) {
    s.title = null;
    if (!t.value) { s.video = null; s.srcIdx = 0; }
    else {
      s.video = allVideos().find(v => vkey(v.sourceId,v.idx)===t.value) || null;
    }
  }
  if (t.classList.contains('sGoods')) s.goods = t.value;
  renderSlots();
});

$('#slots').addEventListener('click', e => {
  const b = e.target.closest('.ovrBtn'); if(!b) return;
  const i = +b.closest('tr').dataset.i, s = state.slots[i];
  if (b.dataset.a === 'reset') { s.goods='默认'; s.orig=null; s.loc=null; s.act=null; s.title=null; renderSlots(); }
  else openOverride(i);
});

function openOverride(i){
  const s = state.slots[i];
  const d = state.defaults;
  const v = s.video;
  $('#copyBtn').hidden = true;
  const html = `
    <div class="row" style="margin-bottom:12px">
      <div class="field" style="flex:1;min-width:150px"><label>商品</label>
        <select id="ov_goods">${['默认',...state.goods].map(g=>`<option ${g===(s.goods||'默认')?'selected':''}>${esc(g)}</option>`).join('')}</select></div>
    </div>
    <div class="row">
      <div class="field" style="flex:1;min-width:130px"><label>位置</label>
        <select id="ov_loc"><option ${(s.loc??d.loc)==='不显示位置'?'selected':''}>不显示位置</option></select></div>
      <div class="field" style="flex:1;min-width:120px"><label>声明原创</label>
        <select id="ov_orig"><option value="1" ${(s.orig??d.orig)?'selected':''}>勾选</option><option value="0" ${!(s.orig??d.orig)?'selected':''}>不勾选</option></select></div>
      <div class="field" style="flex:1;min-width:130px"><label>活动</label>
        <select id="ov_act"><option ${(s.act??d.act)==='不参与活动'?'selected':''}>不参与活动</option></select></div>
    </div>
    <div class="field" style="margin-top:12px"><label>短标题（留空则沿用审查稿标题）</label>
      <input type="text" id="ov_title" value="${esc(s.title||'')}" placeholder="${esc(v?.draftTitle||'例如：光有AI不够 还要自己的系统')}"></div>
    <div class="hint" style="margin-top:10px">描述 = 短标题 + 空格 + 默认标签串　·　覆盖后该行标记为「已改」</div>`;
  $('#dlgTitle').textContent = `调整 ${s.time} 这一条`;
  $('#dlgBody').innerHTML = html;
  $('#dlgSave').onclick = () => {
    s.goods = $('#ov_goods').value;
    s.loc = $('#ov_loc').value;
    s.orig = $('#ov_orig').value === '1';
    s.act = $('#ov_act').value;
    s.title = $('#ov_title').value.trim() || null;
    renderSlots(); $('#dlg').close();
  };
  $('#dlg').showModal();
}

/* ---------- 默认设置 ---------- */
const tagChoices = (TAGS.match(/#[^#\s]+/g) || []).map(name=>({name,selected:true}));
function updateTags() {
  const selected = tagChoices.filter(tag=>tag.selected);
  state.defaults.tags = selected.map(tag=>tag.name).join(' ');
  $('#dTags').value = state.defaults.tags;
  $('#dTags').title = state.defaults.tags || '未选择标签';
  $('#tagSelectionCount').textContent = `已选 ${selected.length} / ${tagChoices.length} 个标签`;
  $('#tagOptions').querySelectorAll('input').forEach((input,index)=>{
    input.checked=tagChoices[index].selected;
    input.closest('label').classList.toggle('is-selected',input.checked);
  });
}
function renderTagChoices() {
  $('#tagOptions').innerHTML = tagChoices.map((tag,index)=>`<label class="tag-option"><input type="checkbox" data-tag-index="${index}" ${tag.selected?'checked':''}><span>${esc(tag.name)}</span></label>`).join('');
  updateTags();
}
$('#toggleTags').onclick=()=>{
  const panel=$('#tagsPanel'); panel.hidden=!panel.hidden;
  $('#toggleTags').setAttribute('aria-expanded',String(!panel.hidden));
  $('#toggleTags').textContent=panel.hidden?'展开标签 ▾':'收起标签 ▴';
};
$('#tagOptions').addEventListener('change',e=>{
  if(!e.target.matches('input[type="checkbox"]')) return;
  tagChoices[Number(e.target.dataset.tagIndex)].selected=e.target.checked;
  updateTags();
});
$('#selectAllTags').onclick=()=>{tagChoices.forEach(tag=>tag.selected=true);updateTags();};
$('#clearTags').onclick=()=>{tagChoices.forEach(tag=>tag.selected=false);updateTags();};
function addTag() {
  const text=$('#newTag').value.trim().replace(/^[#＃]+/,'').trim();
  if(!text || /[\s#＃]/u.test(text)) { $('#tagMessage').textContent='请输入一个完整标签，不含空格；多个标签请分别添加。'; return; }
  const name='#'+text, existing=tagChoices.find(tag=>tag.name.toLowerCase()===name.toLowerCase());
  if(existing) { existing.selected=true; $('#tagMessage').textContent=`${existing.name} 已存在，已为你勾选。`; }
  else { tagChoices.push({name,selected:true}); $('#tagMessage').textContent=`已添加并勾选 ${name}`; }
  $('#newTag').value=''; renderTagChoices(); $('#newTag').focus();
}
$('#addTag').onclick=addTag;
$('#newTag').onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();addTag();}};
renderTagChoices();
$('#executorModel').innerHTML=EXECUTION_MODELS.map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join('');
$('#executorModel').value='Space Bunny';
$('#dOrig').onchange = e => state.defaults.orig = e.target.value==='1';
$('#dLoc').onchange = e => state.defaults.loc = e.target.value;
$('#dAct').onchange = e => state.defaults.act = e.target.value;

/* ---------- 清单 ---------- */
function buildPlan(){
  const d = state.defaults;
  const rows = state.slots.map((s,i)=>{
    const goods = s.goods === '默认' ? (d.__goods || '不挂商品') : s.goods;
    return {
      time: s.time,
      seq: i+1,
      video: s.video ? s.video.full : null,
      videoRel: s.video ? s.video.rel : null,
      source: s.video?.sourcePath || null,
      cover: s.video ? s.video.cover : null,
      draftTitle: s.video ? s.video.draftTitle : null,
      title: (s.title || s.video?.draftTitle || '').replace(/／/g,' ').trim() || null,
      goods: (goods==='默认'||goods==='不挂商品') ? null : goods,
      loc: s.loc ?? d.loc,
      original: s.orig ?? d.orig,
      activity: s.act ?? d.act,
      tags: d.tags,
    };
  });
  return { date: $('#date').value, count: state.count, start: $('#startTime').value, end: $('#endTime').value,
           execution:{driver:'WorkBuddy',model:$('#executorModel').value,thinking:'极致',contextWindow:'模型默认'},
           defaults: {...d}, sources: state.sources.map(s=>({path:s.path, count:s.res?.count||0})), rows };
}


function showPreview(){
  const plan = buildPlan();
  $('#copyBtn').hidden = false;
  const md = toMarkdown(plan);
  $('#dlgTitle').textContent = '发布清单预览';
  $('#dlgBody').innerHTML = `<pre style="white-space:pre-wrap;font:12.5px/1.75 ui-monospace,Consolas,monospace;background:#f7f8fa;padding:14px;border-radius:8px;border:1px solid var(--line)">${esc(md)}</pre>`;
  $('#dlgSave').onclick = async () => { if(await savePlan(plan, md)) $('#dlg').close(); };
  $('#copyBtn').onclick = () => { navigator.clipboard.writeText(md); $('#copyBtn').textContent='已复制'; setTimeout(()=>$('#copyBtn').textContent='复制 Markdown',1500); };
  $('#dlg').showModal();
}
async function savePlan(plan, md){
  const errors = validatePlan(plan);
  if(errors.length) { $('#status').textContent = '请先补齐：' + errors.join('；'); return false; }
  $('#saveBtn').disabled = true; $('#dlgSave').disabled = true;
  try {
    const r = await fetch('/api/save', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({plan})});
    const result = await r.json();
    if(!r.ok || !result.ok) throw new Error(result.error || '保存失败');
    $('#status').textContent = '清单已保存，可在“发布记录”查看本轮排期（尚未发布）。';
    window.dispatchEvent(new CustomEvent('publication-saved',{detail:{id:result.id}}));
    return true;
  } catch(err) { $('#status').textContent = '保存失败：' + err.message; return false; }
  finally { $('#saveBtn').disabled=false; $('#dlgSave').disabled=false; }
}
async function publishPlan(plan){
  updatePublishAvailability();
  if(!workBuddyReady || publishing){$('#status').textContent=$('#publishBtn').title;return false;}
  const errors = validatePlan(plan);
  if(errors.length) { $('#status').textContent = '请先补齐：' + errors.join('；'); return false; }
  publishing=true;
  awaitingPublishStatus=true;
  updatePublishAvailability();
  const btnText = $('#publishBtn').textContent;
  $('#publishBtn').textContent = '排队中…';
  try {
    const r = await fetch('/api/publish', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({plan})});
    const result = await r.json();
    if(!r.ok || !result.ok) throw new Error(result.error || '排队失败');
    workBuddyRuntime={...workBuddyRuntime,activeJob:result.job||{status:'submitted'}};
    $('#status').textContent = `WorkBuddy 已接收本轮 ${result.rows} 条任务，可在“发布记录”查看实际进展。`;
    window.dispatchEvent(new CustomEvent('publication-saved',{detail:{id:result.id}}));
    return true;
  } catch(err) { $('#status').textContent = '排队失败：' + err.message; return false; }
  finally { publishing=false;awaitingPublishStatus=true;$('#publishBtn').textContent = btnText;updatePublishAvailability();window.dispatchEvent(new CustomEvent('workbuddy-status-requested')); }
}
let workBuddyReady=false,workBuddyRuntime=null,publishing=false,awaitingPublishStatus=false;
function updatePublishAvailability(){
  const connected=Boolean(workBuddyRuntime?.available&&workBuddyRuntime.capabilities?.publish);
  const busy=Boolean(workBuddyRuntime?.activeJob);
  const modelMatches=Boolean(workBuddyRuntime?.assistantModel&&workBuddyRuntime.assistantModel===$('#executorModel').value);
  workBuddyReady=connected&&!busy&&modelMatches&&!awaitingPublishStatus;
  $('#publishBtn').disabled=!workBuddyReady||publishing;
  $('#publishBtn').title=publishing?'正在提交本轮发布任务':busy?'已有 WorkBuddy 任务，请先核对本轮结果':awaitingPublishStatus?'正在核对最新任务状态':connected&&!modelMatches?'顶部模型须与 WorkBuddy 本地助理当前模型一致':workBuddyReady?'按已确认排期启动发布':(workBuddyRuntime?.message||'请先连接 WorkBuddy');
}
$('#publishBtn').disabled=true;
$('#publishBtn').title='正在检查 WorkBuddy 连接';
window.addEventListener('workbuddy-runtime',e=>{
  workBuddyRuntime=e.detail||null;
  awaitingPublishStatus=false;
  updatePublishAvailability();
});
$('#executorModel').addEventListener('change',updatePublishAvailability);
$('#previewBtn').onclick = showPreview;
$('#saveBtn').onclick = () => { const p = buildPlan(); savePlan(p, toMarkdown(p)); };
$('#publishBtn').onclick = () => {
  if(!workBuddyReady||publishing){$('#status').textContent=$('#publishBtn').title;return;}
  const check=validatePlan(buildPlan());
  if(check.length){$('#status').textContent='请先补齐：'+check.join('；');return;}
  if(!confirm('将由 WorkBuddy 按当前清单逐条核对，并提交到视频号的定时发布队列。\n\n确认本轮清单与目标账号后开始？')) return;
  publishPlan(buildPlan());
};
$('#dlgX').onclick = () => $('#dlg').close();


/* Reorder complete video cards, preserving the fixed time positions. */
let dragging = null;
function reorder(from, to) {
  if(from === to) return;
  state.slots = moveSlot(state.slots,from,to);
  renderSlots();
  $('#status').textContent = `已移到第 ${to+1} 个时间点 ${state.slots[to].time}，视频设置随之移动`;
  $('#slots').querySelectorAll('.drag-handle')[to]?.focus();
}
function clearDrop() { $('#slots').querySelectorAll('tr').forEach(row=>row.classList.remove('drop-before','drop-after','dragging')); }
$('#slots').addEventListener('dragstart',e=>{
  const handle=e.target.closest('.drag-handle');
  if(!handle) return;
  dragging=+handle.closest('tr').dataset.i;
  e.dataTransfer.effectAllowed='move';
  e.dataTransfer.setData('text/plain',String(dragging));
  handle.closest('tr').classList.add('dragging');
});
$('#slots').addEventListener('dragover',e=>{
  if(dragging===null) return;
  const row=e.target.closest('tr'); if(!row) return;
  e.preventDefault(); e.dataTransfer.dropEffect='move'; clearDrop();
  const box=row.getBoundingClientRect();
  row.classList.add(e.clientY < box.y+box.height/2 ? 'drop-before' : 'drop-after');
});
$('#slots').addEventListener('drop',e=>{
  if(dragging===null) return;
  e.preventDefault();
  const row=e.target.closest('tr');
  if(row) {
    const box=row.getBoundingClientRect();
    let insert=+row.dataset.i+(e.clientY>=box.y+box.height/2 ? 1 : 0);
    if(dragging<insert) insert--;
    reorder(dragging,Math.max(0,Math.min(state.slots.length-1,insert)));
  }
  dragging=null; clearDrop();
});
$('#slots').addEventListener('dragend',()=>{dragging=null;clearDrop();});
$('#slots').addEventListener('keydown',e=>{
  if(!e.target.closest('.drag-handle') || !e.altKey || !['ArrowUp','ArrowDown'].includes(e.key)) return;
  e.preventDefault();
  const from=+e.target.closest('tr').dataset.i;
  const to=from+(e.key==='ArrowUp'?-1:1);
  if(to>=0 && to<state.slots.length) reorder(from,to);
});
$('#slots').addEventListener('click',e=>{
  const button=e.target.closest('button'), row=e.target.closest('tr'); if(!button||!row) return;
  const index=+row.dataset.i;
  if(button.classList.contains('move-up')) reorder(index,index-1);
  if(button.classList.contains('move-down')) reorder(index,index+1);
  if(button.classList.contains('preview-video')) openVideo(index);
});

const player=$('#videoPlayer');
function openVideo(index) {
  const slot=state.slots[index], video=slot.video; if(!video) return;
  $('#videoTitle').textContent=slot.title || video.draftTitle || video.name;
  $('#videoName').textContent=video.name;
  $('#videoError').textContent='';
  if(!video.previewUrl) { $('#status').textContent='请重新扫描文件夹以启用预览'; return; }
  player.src=video.previewUrl;
  player.poster=video.coverUrl || '';
  player.playbackRate=1;
  $('#videoSpeed').value='1';
  $('#videoDlg').showModal();
  player.play().catch(()=>{});
}
player.addEventListener('error',()=>{ $('#videoError').textContent='无法播放：文件可能已移动、服务已重启或浏览器不支持该编码。请重新扫描；可用本机播放器核对该文件。'; });
$('#videoClose').onclick=()=>$('#videoDlg').close();
$('#videoDlg').addEventListener('close',()=>{player.pause();player.removeAttribute('src');player.removeAttribute('poster');player.load();$('#videoError').textContent='';});
$('#videoBack').onclick=()=>{if(Number.isFinite(player.duration)) player.currentTime=Math.max(0,player.currentTime-10);};
$('#videoForward').onclick=()=>{if(Number.isFinite(player.duration)) player.currentTime=Math.min(player.duration,player.currentTime+10);};
$('#videoSpeed').onchange=e=>{player.playbackRate=Number(e.target.value);};

/* ---------- init ---------- */
for (const prefix of ['start', 'end']) {
  const hour = $(`#${prefix}Hour`), minute = $(`#${prefix}Minute`), input = $(`#${prefix}Time`);
  const option = n => { const value=String(n).padStart(2,'0'); return `<option value="${value}">${value}</option>`; };
  hour.innerHTML = Array.from({length:17},(_,i)=>option(i+6)).join('');
  minute.innerHTML = [0,10,20,30,40,50].map(option).join('');
  [hour.value, minute.value] = input.value.split(':');
  const updateTime = () => {
    const latest=hour.value==='22';
    for(const choice of minute.options) choice.disabled=latest&&choice.value!=='00';
    if(latest) minute.value='00';
    input.value = `${hour.value}:${minute.value}`; syncSlots();
  };
  hour.onchange = minute.onchange = updateTime;
}
const d = new Date(); d.setDate(d.getDate()+1);
$('#date').value = localDate(d);
renderSources(); syncSlots();
