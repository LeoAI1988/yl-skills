'use strict';
const transcripts=JSON.parse(document.getElementById('transcript-data').textContent);
const side=document.getElementById('side');
function closeTranscript(){side.hidden=true;document.querySelectorAll('.tlink.active').forEach(x=>x.classList.remove('active'));}
document.addEventListener('click',e=>{
  const button=e.target.closest('.tlink');if(!button)return;
  const data=transcripts[button.dataset.id];
  document.querySelectorAll('.tlink.active').forEach(x=>x.classList.remove('active'));
  button.classList.add('active');
  document.getElementById('dlgtitle').textContent=button.textContent;
  document.getElementById('dlgsource').textContent=data?.full?'全文':'';
  document.getElementById('dlgbody').textContent=data?.full||data?.reason||'全文待补充。';
  document.getElementById('dlgbody').scrollTop=0;side.hidden=false;
});
document.getElementById('close').addEventListener('click',closeTranscript);
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeTranscript();});
