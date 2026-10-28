/* Batch edits stay local. Preparation still confirms exactly one frozen item. */
let batchRevision=null;
function batchDraft(row){
 const get=name=>row.querySelector(`[data-field="${name}"]`).value;
 return {id:row.dataset.batchId,patch:{title:get('title'),caption:get('caption').trim(),tags:normalizeTags(get('tags').split(/[\s,，]+/u).filter(Boolean)),settings:{ai_declaration:get('ai'),visibility:row.dataset.visibility}}};
}
function batchCounters(){
 let invalid=0,missing=0;
 $$('#batchRows [data-batch-id]').forEach(row=>{
  const {patch}=batchDraft(row),errors=contentIssues(patch),needs=contentIssues(patch,true);
  if(errors.length)invalid++;if(needs.length)missing++;
  row.querySelector('.batch-counts').textContent=`标题 ${patch.title.length}/20 · 正文含标签 ${composeCaption(patch.caption,patch.tags).length}/1000 · 标签 ${patch.tags.length}/10 · ${patch.settings.visibility}`;
  row.querySelector('.batch-errors').textContent=needs.join('；');
 });
 $('#saveBatch').disabled=invalid>0;
 $('#batchValidation').textContent=invalid?`${invalid} 篇超出平台字数或标签限制，请修改后保存`:missing?`${missing} 篇仍需确认标题或 AI 声明，可先保存进度`:'';
}
function openBatchEdit(){
 const rows=pickedRows();if(!rows.length)return toast('请先勾选要设置的视频');
 batchRevision=S.preparation_revision;
 $('#batchAi').value='';$('#batchVisibility').value='';
 $('#batchEditSummary').textContent=`共 ${rows.length} 篇 · 标题最多 20 字，正文含话题最多 1000 字，话题最多 10 个`;
 $('#batchRows').innerHTML=rows.map((r,i)=>{const a=asset(r.asset_id);return `<section class="batch-row" data-batch-id="${esc(a.id)}" data-visibility="${esc(a.settings.visibility)}"><h3>${i+1}. ${esc(a.name)} <small>${esc(r.at)}</small></h3><p class="muted">${esc(a.title_source||'请核对原稿或成片标题')}</p><div class="batch-fields"><label>标题<input data-field="title" value="${esc(a.title||'')}" aria-label="第${i+1}篇标题"></label><label>内容 AI 声明<select data-field="ai" aria-label="第${i+1}篇 AI 声明">${Object.entries(aiLabels).map(([key,label])=>`<option value="${key}" ${a.settings.ai_declaration===key?'selected':''}>${label}</option>`).join('')}</select></label><label class="batch-wide">正文<textarea data-field="caption" rows="2" aria-label="第${i+1}篇正文">${esc(a.caption||'')}</textarea></label><label class="batch-wide">标签（空格或逗号分隔）<input data-field="tags" value="${esc((a.tags||[]).join(' '))}" aria-label="第${i+1}篇标签"></label></div><p class="batch-counts muted"></p><p class="batch-errors validation"></p></section>`;}).join('');
 batchCounters();$('#batchDialog').showModal();
}
$('#batchEdit').onclick=openBatchEdit;
$('#batchRows').addEventListener('input',batchCounters);
$('#batchRows').addEventListener('change',batchCounters);
$('#applyBatchCommon').onclick=()=>{
 const ai=$('#batchAi').value,visibility=$('#batchVisibility').value;
 if(!ai&&!visibility)return toast('先选择要统一应用的设置');
 $$('#batchRows [data-batch-id]').forEach(row=>{if(ai)row.querySelector('[data-field="ai"]').value=ai;if(visibility)row.dataset.visibility=visibility;});
 batchCounters();toast('已应用到下方各篇，保存后生效');
};
$('#batchRematch').onclick=()=>action(async()=>{
 const rows=$$('#batchRows [data-batch-id]'),button=$('#batchRematch');button.disabled=true;
 try{
  const results=await Promise.all(rows.map(row=>{const {id,patch}=batchDraft(row);return api('tags',{id,title:patch.title,caption:patch.caption});}));
  results.forEach((r,i)=>rows[i].querySelector('[data-field="tags"]').value=r.tags.join(' '));batchCounters();
 }finally{button.disabled=false;}
});
$('#batchForm').onsubmit=e=>{e.preventDefault();action(async()=>{
 const items=$$('#batchRows [data-batch-id]').map(batchDraft);
 const errors=items.flatMap(({patch},i)=>contentIssues(patch).map(e=>`第 ${i+1} 篇：${e}`));
 if(errors.length)throw Error(errors.join('；'));
 await api('edit/batch',{items,revision:batchRevision});$('#batchDialog').close();await refresh();toast(`已保存 ${items.length} 篇设置`);
});};
