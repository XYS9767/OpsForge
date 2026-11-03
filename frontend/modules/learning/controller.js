import { inlineRich, safe, $, esc, rich } from '../core/ui.js';
import { api } from '../core/api.js';
import { S, timers, learningLabel } from '../core/state.js';

import { saveDraft } from './drafts.js';
export { saveDraft, scheduleSave } from './drafts.js';

let restartPending=null;
const newRequestId=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');
export async function restartPractice(){
  if(S.restarting||!S.q)return;
  const question=S.q,context=S.draftContext,epoch=S.sessionEpoch;
  if(!confirm('重新练习会清空本轮答案与笔记、恢复初始代码模板，并销毁本题旧实验。历史提交和收藏保留。确定继续？'))return;
  S.restarting=true;
  document.querySelectorAll('[data-action="practice-restart"]').forEach(b=>b.disabled=true);
  try{
    if(!restartPending||restartPending.context!==context){
      await saveDraft();
      if(S.q!==question||S.draftContext!==context)return;
      restartPending={context,body:{id:question.id,scope:context.scope,revision:context.revision,request_id:newRequestId()}};
    }
    const result=await api('practice/restart',restartPending.body);
    const {removeStorage}=await import('../core/storage.js');
    removeStorage('localStorage','opsforge-lab-'+question.id);
    if(epoch!==S.sessionEpoch)return;
    S.boot=await api('bootstrap');
    if(S.q===question&&S.draftContext===context){
      const {selectQuestion,loadList}=await import('../bank/controller.js');
      await selectQuestion(result.id,false);await loadList();
    }
    restartPending=null;
  }catch(error){
    if(error.status===409)restartPending=null;
    throw error;
  }finally{
    S.restarting=false;
    const {render}=await import('../views/shell.js');render();
  }
}

let submitting=false;
let pendingSubmit=null;
let progressBefore=0;
let progressTrail=[];
let progressRequest=0;

function assessmentDetails(result){
  const checks=Array.isArray(result.checks)?result.checks:[];
  return `${checks.length?`<ul>${checks.map(c=>`<li>${c.passed?'✓':'✕'} ${esc(c.label)}</li>`).join('')}</ul>`:''}${result.output?`<details><summary>查看执行验收输出</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(result.output)}</pre></details>`:''}`;
}

export async function submit(rating){
  if(submitting)return;
  submitting=true;S.submitting=true;
  const buttons=[...document.querySelectorAll('[data-action="submit"], [data-action="self-rating"]')];
  buttons.forEach(b=>b.disabled=true);
  try{
  const question=S.q, context=S.draftContext;
  await saveDraft();
  if(S.q!==question||S.draftContext!==context)return;
  const body={id:question.id,version:question.version||1,answer:context.draft.text,self_rating:rating,lab:S.lab?.id,draft_revision:context.revision,draft_scope:context.scope};
  const signature=JSON.stringify(body);
  if(!pendingSubmit||pendingSubmit.signature!==signature)pendingSubmit={signature,id:Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('')};
  const result=await api('submit',{...body,request_id:pendingSubmit.id});
  pendingSubmit=null;
  if(S.q!==question||S.draftContext!==context)return;
  question.learning={completion:'submitted',mastery:result.passed===true?'mastered':result.passed===false?'review':'unrated'};
  document.querySelectorAll('[data-learning-status]').forEach(node=>node.textContent=learningLabel(question));
  const node=$('#feedback');if(node)node.innerHTML=`<div class="feedback ${result.passed===true?'success':result.passed===false?'error':''}">${esc(result.method)} · ${esc(result.message||(result.passed?'全部验收项通过':'尚有验收项未完成'))}${assessmentDetails(result)}</div>`;
  S.boot=await api('bootstrap');
  if(S.page==='modules')await (await import('../bank/curriculum.js')).loadCurriculum();
  for(const [name,value] of Object.entries({count:S.boot.count,mastered:S.boot.stats.mastered,attempts:S.boot.stats.attempts})){
    const counter=document.querySelector('[data-stat="'+name+'"]');if(counter)counter.textContent=Number(value).toLocaleString();
  }
  }finally{
    submitting=false;S.submitting=false;
    document.querySelectorAll('[data-action="submit"], [data-action="self-rating"]').forEach(b=>b.disabled=false);
  }
}

export async function progress(reset=true){
  if(reset){progressBefore=0;progressTrail=[];}
  const request=++progressRequest, node=$('#progress-content');
  if(!node)return;
  let d;
  try{d=await api('progress?before='+progressBefore);}
  catch(error){if(request===progressRequest&&node===$('#progress-content'))throw error;return;}
  if(request!==progressRequest||node!==$('#progress-content'))return;
  node.innerHTML=d.attempts.length?`<table><thead><tr><th>题目</th><th>评价方式</th><th>结果</th><th>时间</th></tr></thead><tbody>${d.attempts.map(a=>`<tr><td><button class="flat" data-action="attempt" data-id="${a.id}">${inlineRich(a.title)} · v${a.version}</button></td><td>${esc(a.result.method)}</td><td><span class="tag ${a.result.passed?'green':'amber'}">${a.result.passed===null?(a.result.stage==='awaiting_execution'?'待执行验收':'待自评'):a.result.passed?'已掌握':'待复习'}</span></td><td>${new Date(a.created*1000).toLocaleString('zh-CN')}</td></tr>`).join('')}</tbody></table>`:'<div class="empty">还没有提交记录。完成一次练习后，记录会出现在这里。</div>';

  const controls=document.createElement('div');controls.className='row';
  const label=document.createElement('span');label.textContent=`共 ${d.total} 条记录 · 第 ${progressTrail.length+1} 页`;controls.append(label);
  for(const [name,disabled,change] of [
    ['上一页',!progressTrail.length,()=>{progressBefore=progressTrail.pop();}],
    ['下一页',!d.next,()=>{progressTrail.push(progressBefore);progressBefore=d.next;}]
  ]){
    const button=document.createElement('button');button.textContent=name;button.disabled=disabled;
    button.onclick=()=>safe(async()=>{
      const states=[...controls.querySelectorAll('button')].map(b=>[b,b.disabled]);
      states.forEach(([b])=>b.disabled=true);
      const oldBefore=progressBefore,oldTrail=[...progressTrail],ticket=progressRequest+1;
      change();
      try{await progress(false);}
      catch(error){if(ticket===progressRequest){progressBefore=oldBefore;progressTrail=oldTrail;}throw error;}
      finally{if(controls.isConnected)states.forEach(([b,disabled])=>b.disabled=disabled);}
    });
    controls.append(button);
  }
  node.append(controls);
}

export async function attemptModal(id){
  const data=await api('attempt?id='+encodeURIComponent(id));const q=data.question;
  const panel=document.createElement('div');panel.className='modal-backdrop';
  panel.innerHTML=`<div class="modal"><div class="row between"><h2>本次作答 · v${q.version}</h2><button data-action="close-modal">关闭</button></div><h3>${inlineRich(q.title)}</h3><div class="prose">${rich(q.body)}</div><h3>我的回答</h3><div class="prose">${rich(data.answer||'本次没有提交文字')}</div><p data-attempt-result>${esc(data.result.method)} · ${esc(data.result.message||'')}</p><details class="answer-panel"><summary>本次题目对应的参考答案 · 默认隐藏</summary><div class="prose"></div></details><p class="muted">保存于本次提交的题目快照，不会随题库更新替换。</p></div>`;
  const saved=document.createElement('section');
  saved.innerHTML='<h3>本次提交文件与笔记</h3>';
  if(data.submission){
    for(const [name,content] of Object.entries(data.submission.files||{})){
      const label=document.createElement('h4'),pre=document.createElement('pre');label.textContent=name;pre.textContent=content;
      pre.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto';saved.append(label,pre);
    }
    const notes=document.createElement('p');notes.textContent=data.submission.notes||'本次没有提交笔记';saved.append(notes);
    if(!Object.keys(data.submission.files||{}).length)saved.append(document.createTextNode('本次没有提交文件。'));
  }else{saved.append(document.createTextNode('旧记录未保存当时的文件与笔记，无法用当前草稿代替。'));}
  panel.querySelector('.modal').append(saved);
  document.body.append(panel);const details=panel.querySelector('details');
  panel.querySelector('[data-attempt-result]').insertAdjacentHTML('afterend',assessmentDetails(data.result));
  if(!q.exercise&&!q.automatic_grading&&(!data.exam_id||q.type==='interview')&&['source','interview','case','practice','code'].includes(q.type)){
    for(const [rating,label] of [['mastered','本次作答：已掌握'],['review','本次作答：待复习']]){
      const button=document.createElement('button');button.textContent=label;button.dataset.attemptRating=rating;
      button.onclick=()=>safe(async()=>{
        const ratingButtons=[...panel.querySelectorAll('[data-attempt-rating]')];
        ratingButtons.forEach(b=>b.disabled=true);
        try{
          const updated=await api('attempt/rating',{id,rating});
          data.result=updated.result;
          panel.querySelector('[data-attempt-result]').textContent=`${data.result.method} · ${data.result.passed?'已掌握':'待复习'} · ${data.result.message||''}`;
          button.textContent='已记录本次作答评价';
          const reportResult=S.examReport?.results.find(item=>item.attempt_id===Number(id));
          if(reportResult){
            S.examReport=await api('exam/result?id='+encodeURIComponent(S.examReport.id));
            const {examReportView}=await import('../exams/controller.js');
            const reportNode=$('#exam-report');
            if(reportNode)reportNode.innerHTML=examReportView();
          }
          if($('#progress-content'))await progress(false);
          S.boot=await api('bootstrap');
        }finally{ratingButtons.forEach(b=>b.disabled=false);}
      });
      panel.querySelector('.modal').append(button);
    }
  }
  details.addEventListener('toggle',()=>{if(details.open)safe(async()=>{
    const a=await api('attempt/answer?id='+encodeURIComponent(id));
    if(a.id!==q.id||a.version!==q.version)throw Error('历史答案版本不匹配');
    details.querySelector('div').innerHTML=rich(a.answer)+rich(a.explanation);
  });});
}
