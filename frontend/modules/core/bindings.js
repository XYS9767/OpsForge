import { toast, rich, highlight, safe, $, esc } from './ui.js';
import { api } from './api.js';
import { loadList } from '../bank/controller.js';
import { scheduleSave } from '../learning/controller.js';
import { runCommand } from '../practice/controller.js';
import { render } from '../views/shell.js';
import { S } from './state.js';
import { bindStudy } from '../study/controller.js';
import { bindCurriculum } from '../bank/curriculum.js';

export function bindInputs(){
  bindStudy();
  bindCurriculum();
  document.querySelectorAll('[data-action="cloud-command"],[data-action="cloud-cidr"]').forEach(b=>b.disabled=S.busy);
  const answer=$('#answer-panel');
  if(answer)answer.addEventListener('toggle',async()=>{
    if(!answer.open)return;
    const id=S.q.id, version=S.q.version||1;
    const target=$('#answer-content');target.textContent='正在加载此题参考答案…';
    try{
      const d=await api('answer',{id,version});
      if(S.q.id!==d.id||(S.q.version||1)!==d.version)return;
      target.innerHTML=rich(d.answer)+(d.explanation?rich(d.explanation):'')+(d.rubric.length?`<div class="section-label">评分要点</div><ul class="rubric">${d.rubric.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'')+(d.references?.length?`<div class="section-label">核对资料</div>${d.references.map(u=>`<p><a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(u)}</a></p>`).join('')}`:'')+(d.notice?`<div class="notice">${esc(d.notice)}</div>`:'')+`<div class="muted">对应题目 ${esc(d.id)} · v${d.version}</div>`;
    }catch(e){target.textContent=e.message;}
  });
  if($('#search'))$('#search').onkeydown=async e=>{if(e.key==='Enter'){S.filters.search=e.target.value;S.listPage=1;await safe(async()=>{await loadList();render();});}};
  for(const [id,key] of [['filter-module','module'],['filter-type','format'],['filter-level','level'],['filter-completion','completion'],['filter-mastery','mastery']]){
    if($('#'+id))$('#'+id).onchange=e=>safe(async()=>{S.filters[key]=e.target.value;S.listPage=1;await loadList();render();});
  }
  if($('#filter-mark'))$('#filter-mark').onchange=e=>safe(async()=>{delete S.filters.favorite;delete S.filters.wrong;if(e.target.value)S.filters[e.target.value]='1';S.listPage=1;await loadList();render();});
  if($('#notes'))$('#notes').oninput=e=>{S.draft.notes=e.target.value;scheduleSave();};
  if($('#text-answer'))$('#text-answer').oninput=e=>{S.draft.text=e.target.value;scheduleSave();};
  const runInput=$('#run-code-command'),runButton=document.querySelector('[data-action="run-code"]');
  if(runInput&&runButton){
    const update=()=>{
      const assessment=S.q.exercise&&S.q.automatic_grading&&(!runInput.value.trim()||runInput.value.trim()===(S.q.run||'').trim());
      runButton.textContent=assessment?(S.exam?.ids.includes(S.q.id)?'保存并验收本题':'提交并验收'):'同步并运行';
      runButton.disabled=S.lab?.mode!=='real'||(!assessment&&!runInput.value.trim());
      runButton.title=S.lab?.mode!=='real'?'先从网页创建可用的真实隔离工作区':assessment?'执行本题验收并保存结果':!runInput.value.trim()?'请按题目验收方法填写运行命令':'';
    };
    runInput.oninput=update;update();
  }
  document.querySelectorAll('input[name="choice"]').forEach(el=>el.onchange=e=>{S.draft.text=e.target.value;if($('#text-answer'))$('#text-answer').value=e.target.value;scheduleSave();});
  document.querySelectorAll('input[name="format-choice"]').forEach(el=>el.onchange=()=>{
    const values=[...document.querySelectorAll('input[name="format-choice"]:checked')].map(node=>node.value);
    S.draft.text=JSON.stringify(S.q.question_format==='multiple_choice'?values:(values[0]||''));scheduleSave();
  });
  document.querySelectorAll('input[data-blank-id]').forEach(el=>el.oninput=()=>{
    S.draft.text=JSON.stringify(Object.fromEntries([...document.querySelectorAll('input[data-blank-id]')].map(node=>[node.dataset.blankId,node.value])));scheduleSave();
  });
  if($('#code')){
    $('#code').oninput=e=>{S.draft.files[S.selectedFile]=e.target.value;$('#line-numbers').textContent=e.target.value.split('\n').map((_,i)=>i+1).join('\n');$('#code-highlight').innerHTML=highlight(e.target.value);scheduleSave();};
    $('#code').onscroll=e=>{$('#line-numbers').scrollTop=e.target.scrollTop;$('#code-highlight').scrollTop=e.target.scrollTop;$('#code-highlight').scrollLeft=e.target.scrollLeft;};
    $('#code').onkeydown=e=>{if(e.key==='Tab'){e.preventDefault();const t=e.target;const start=t.selectionStart;t.setRangeText('    ',start,t.selectionEnd,'end');t.dispatchEvent(new Event('input'));}};
  }
  if($('#command'))$('#command').onkeydown=e=>{
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();safe(runCommand);}
    if(e.key==='ArrowUp'&&!e.target.value.includes('\n')){e.preventDefault();S.historyIndex=Math.max(0,S.historyIndex-1);e.target.value=S.commandHistory[S.historyIndex]||'';}
    if(e.key==='ArrowDown'&&!e.target.value.includes('\n')){e.preventDefault();S.historyIndex=Math.min(S.commandHistory.length,S.historyIndex+1);e.target.value=S.commandHistory[S.historyIndex]||'';}
  };
  if($('#import-file'))$('#import-file').onchange=e=>safe(async()=>{
    const file=e.target.files[0];if(!file)return;if(file.size>20000000)throw Error('文件不能超过 20MB');
    const d=JSON.parse(await file.text());const result=await api('import',Array.isArray(d)?{questions:d}:d);toast(`已导入 ${result.imported} 道题，均待审校`);S.boot=await api('bootstrap');await loadList();render();
  });
}

export function bindSplitter(){
  const el=$('.splitter');if(!el)return;
  el.onpointerdown=e=>{el.setPointerCapture(e.pointerId);el.onpointermove=ev=>document.documentElement.style.setProperty('--left',Math.max(290,Math.min(innerWidth*.5,ev.clientX))+'px');el.onpointerup=()=>el.onpointermove=null;};
}
