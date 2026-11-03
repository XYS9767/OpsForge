import { toast, $ } from '../core/ui.js';
import { api } from '../core/api.js';
import { saveDraft } from '../learning/controller.js';
import { startLab, pollLab } from '../practice/controller.js';
import { render } from '../views/shell.js';
import { S, timers } from '../core/state.js';
import { adoptDraft } from '../learning/drafts.js';
import { readStorage, writeStorage, removeStorage } from '../core/storage.js';
let selection = 0;
let listRequest = 0, editorSequence = 0;
export function cancelQuestionSelection(){selection++;}

export async function loadList(){
  const request=++listRequest;
  const p=new URLSearchParams({...S.filters,page:S.listPage,size:25});
  const current=()=>request===listRequest&&String(p)===String(new URLSearchParams({...S.filters,page:S.listPage,size:25}));
  try{
    const data=await api('questions?'+p);
    if(!current())return false;
    S.list=data.items;S.total=data.total;return true;
  }catch(error){if(current())throw error;return false;}
}

export async function selectQuestion(id,save=true,allowed=()=>true){
  const ticket=++selection;
  if(save)await saveDraft();
  if(ticket!==selection||!allowed())return;
  let data;
  try{data=await api('question?id='+encodeURIComponent(id));}catch(e){if(!save)data=await api('question?id=scenario:permissions:beginner');else throw e;}
  if(ticket!==selection||!allowed())return;
  clearInterval(timers.labPoll);
  S.q=data.question;S.draft=data.draft;S.hintIndex=0;S.lab=null;S.log=[];S.checks=null;
  await adoptDraft(S.q.id,data.draft);
  if(ticket!==selection)return;
  S.selectedFile=Object.keys(S.draft.files)[0]||null;S.pane='task';S.page='work';
  const hasArtifacts=Array.isArray(S.q.exercise?.deliverables)&&S.q.exercise.deliverables.length>0;
  S.tab=['single_choice','multiple_choice','true_false','fill_blank'].includes(S.q.question_format)?'text':S.q.type==='scenario'?'terminal':S.q.type==='code'||hasArtifacts?'code':'text';
  writeStorage('localStorage','opsforge-question',S.q.id);render();
  const savedLab=readStorage('localStorage','opsforge-lab-'+S.q.id);
  if(savedLab){
    try{const restored=await api('lab?id='+encodeURIComponent(savedLab));if(ticket!==selection)return;if(restored.qid===S.q.id){S.lab=restored;S.checks=restored.checks;render();if(restored.mode==='real')pollLab(restored);return;}}catch(error){if(ticket!==selection)return;if(error.status!==404)throw error;removeStorage('localStorage','opsforge-lab-'+S.q.id);}
  }
  const current=await api('lab/current?qid='+encodeURIComponent(S.q.id));
  if(ticket!==selection)return;
  if(current.lab){S.lab=current.lab;S.checks=current.lab.checks;writeStorage('localStorage','opsforge-lab-'+S.q.id,S.lab.id);render();if(S.lab.mode==='real')pollLab(S.lab);return;}
  if(S.q.type==='scenario')await startLab('simulation',false,false,true);
}

export async function questionModal(edit=false){
  const editor=++editorSequence;
  const initial=edit&&S.q?{...S.q,id:S.q.id.startsWith('custom-')?S.q.id:'custom-'+S.q.id,files:S.draft.files,answer:''}:{id:'custom-'+Date.now(),title:'',category:'自定义',type:'interview',level:1,body:'',answer:'',hints:[],rubric:[]};
  const panel=document.createElement('div');panel.className='modal-backdrop';
  panel.dataset.editor=String(editor);
  panel.innerHTML=`<div class="modal"><div class="row between"><h2>${edit?'编辑题目副本':'新增自定义题目'}</h2><button data-action="close-modal">关闭</button></div><p class="muted">题目与答案保存在同一个对象中；相同 custom- 编号更新时保留旧版本，更新后重新审校。</p><textarea id="question-json" spellcheck="false"></textarea><div class="row" style="margin-top:16px"><button class="primary" data-action="save-question">保存题目</button></div></div>`;
  const question=S.q;
  document.body.append(panel);
  const input=panel.querySelector('#question-json'),save=panel.querySelector('[data-action="save-question"]');
  input.value=JSON.stringify(initial,null,2);
  panel.editorBaseline=input.value;
  if(edit){
    input.disabled=true;save.disabled=true;input.value='正在加载完整题目…';
    try{
      const data=await api('question/edit?id='+encodeURIComponent(question.id));
      if(!panel.isConnected)return;
      input.value=JSON.stringify({...data.question,id:initial.id},null,2);panel.editorBaseline=input.value;input.disabled=false;save.disabled=false;
    }catch(error){if(panel.isConnected)input.value=error.message;toast(error.message);}
  }
}

export function closeModal(panel){
  const input=panel.querySelector('#question-json');
  if(input&&!input.disabled&&input.value!==panel.editorBaseline&&!confirm('关闭后将放弃尚未保存的题目内容，确定关闭？'))return;
  if(panel.dataset.saving&&!confirm('保存请求仍在处理中，关闭窗口不会取消此次保存。确定关闭？'))return;
  panel.remove();
}

export async function saveQuestion(button){
  const panel=button.closest('.modal-backdrop'),input=panel.querySelector('#question-json');
  if(panel.dataset.saving)return;
  const q=JSON.parse(input.value),editor=Number(panel.dataset.editor),question=S.q,page=S.page;
  const current=()=>editor===editorSequence&&S.q===question&&S.page===page;
  panel.dataset.saving='true';button.disabled=true;input.disabled=true;
  try{
    const data=await api('import',{questions:[q]});
    toast(`已保存 ${data.imported} 道题，进入待审校区`);
    if(!panel.isConnected||!current())return;
    panel.remove();
    const boot=await api('bootstrap');
    if(!current())return;
    S.boot=boot;await loadList();
    if(current())await selectQuestion(data.ids[0]);
  }finally{
    delete panel.dataset.saving;button.disabled=false;input.disabled=false;
  }
}
