import { inlineRich, safe, esc } from '../core/ui.js';
import { api } from '../core/api.js';
import { saveDraft } from '../learning/controller.js';
import { render } from '../views/shell.js';
import { S, timers } from '../core/state.js';
import { adoptDraft, preserveDraft } from '../learning/drafts.js';
import { readStorage, writeStorage, removeStorage } from '../core/storage.js';

let historyRequest=0,reportRequest=0,retakePending=null,retaking=false;
let navigating=false;
export function examBannerView(){
  if(!S.exam)return '';
  const index=S.exam.ids.indexOf(S.q?.id),active=S.page==='work'&&index>=0;
  return `<div class="exam-banner"><b>模拟考试进行中</b><span id="exam-time"></span><span class="exam-answer-notice">答案与提示在交卷后开放</span><div class="spacer"></div>${active?`<button data-action="exam-prev" ${index===0?'disabled':''}>← 上一题</button><strong data-exam-position>第 ${index+1} / ${S.exam.ids.length} 题</strong><button data-action="exam-next" ${index===S.exam.ids.length-1?'disabled':''}>下一题 →</button>`:''}<details class="exam-card"><summary>答题卡 · ${S.exam.ids.length} 题</summary><section aria-label="考试答题卡"><p>点击题号切换，切换前自动保存答案；蓝色为当前题。</p><div class="exam-questions">${S.exam.ids.map((id,i)=>`<button data-action="exam-jump" data-id="${esc(id)}" aria-label="转到第 ${i+1} 题" ${active&&i===index?'class="active" aria-current="step"':''}>${i+1}</button>`).join('')}</div></section></details><button data-action="exam-resume">返回试卷</button><button data-action="exam-finish">交卷</button></div>`;
}
export async function navigateExam(action,id){
  const exam=S.exam;
  if(!exam||navigating||S.finishing)return;
  const index=exam.ids.indexOf(S.q?.id);
  const target=action==='exam-jump'?id:exam.ids[index+(action==='exam-next'?1:-1)];
  if(!exam.ids.includes(target))return;
  navigating=true;
  const app=document.querySelector('#app');
  app.inert=true;app.setAttribute('aria-busy','true');
  try{
    await checkpointExam();
    const {selectQuestion}=await import('../bank/controller.js');
    await selectQuestion(target,true,()=>S.exam?.id===exam.id&&!S.finishing);
  }finally{
    navigating=false;app.inert=false;app.removeAttribute('aria-busy');
    const control=document.querySelector(`[data-action="${action==='exam-jump'?'exam-next':action}"]:not(:disabled)`);
    control?.focus({preventScroll:true});
  }
}
export async function checkpointExam(){
  const exam=S.exam,question=S.q;
  await saveDraft();
  if(exam&&S.exam?.id===exam.id&&question===S.q&&exam.ids.includes(question?.id)
      &&(question.exercise||question.type==='scenario')){
    await api('exam/check',{id:exam.id,qid:question.id,revision:S.draftContext.revision});
  }
}
export function examHistoryView(){
  const h=S.examHistory;
  return `<section class="card" data-exam-history><h3>历史试卷与原卷重考</h3><p>重考保留原题顺序和版本，清空新一轮作答并重置本卷实验；原成绩不变。旧版试卷未记录时长时按 30 分钟重考。</p><button data-action="exam-history-refresh">刷新历史试卷</button>${S.exam?'<p class="notice">当前试卷进行中；历史报告仍可查看，须交卷后才能重考。若已在另一页面交卷，请刷新历史试卷。</p>':''}${h?`<table><thead><tr><th>试卷时间</th><th>时长</th><th>操作</th></tr></thead><tbody>${h.items.map(e=>`<tr><td>${new Date((e.created||e.deadline)*1000).toLocaleString('zh-CN')}${e.source_exam_id?' · 重考':''}<br><small>${esc(e.id)}</small></td><td>${e.duration_minutes?e.duration_minutes+' 分钟':'旧记录未记录'}</td><td><div class="row wrap"><button data-action="exam-history-report" data-id="${esc(e.id)}">查看报告</button><button data-action="exam-retake" data-id="${esc(e.id)}" ${retaking?'disabled':''} title="${S.exam?'请先完成当前考试；点击可重新核实状态':'以原题开始一次新考试'}">原卷重考</button></div></td></tr>`).join('')}</tbody></table><div class="row"><button data-action="exam-history-prev" ${h.page<=1?'disabled':''}>上一页</button><span>共 ${h.total} 份 · 第 ${h.page} 页</span><button data-action="exam-history-next" ${h.page*20>=h.total?'disabled':''}>下一页</button></div>`:'<p>点击刷新读取历史试卷。</p>'}</section>`;
}
export async function loadExamHistory(page=1){
  const ticket=++historyRequest;
  const requestedExam=S.exam?.id;
  const [data,fresh]=await Promise.all([api('exam/history?page='+page),api('bootstrap')]);
  if(ticket!==historyRequest)return;
  const activeBefore=S.exam?.id;
  if(requestedExam===S.exam?.id){S.boot=fresh;syncExam(fresh.exam,fresh.server_time);startExamClock();}
  S.examHistory=data;
  if(S.page==='exam'){
    if(activeBefore!==S.exam?.id){render();return;}
    const section=document.querySelector('[data-exam-history]');
    if(section)section.outerHTML=examHistoryView();
  }
}
export async function examHistoryAction(action,button){
  if(action==='exam-history-refresh')return loadExamHistory();
  if(action==='exam-history-prev'||action==='exam-history-next')return loadExamHistory((S.examHistory?.page||1)+(action.endsWith('next')?1:-1));
  const id=button.dataset.id;
  if(action==='exam-history-report'){
    const ticket=++reportRequest;
    const origin=document.querySelector('main.page');
    button.disabled=true;
    try{
      const report=await api('exam/result?id='+encodeURIComponent(id));
      if(ticket!==reportRequest||S.page!=='exam'||!origin?.isConnected)return;
      S.examReport=report;S.examReportId=id;S.examReportError='';
      writeStorage('sessionStorage','opsforge-last-exam',id);S.page='exam';render();
      document.querySelector('#exam-report')?.scrollIntoView({block:'start'});
    }finally{if(button.isConnected)button.disabled=false;}
    return;
  }
  if(retaking)return;
  if(!confirm('按原题顺序与版本重新考试？新一轮答案为空，本卷旧实验将重置，原成绩保留。'))return;
  retaking=true;button.disabled=true;
  try{
    const fresh=await api('bootstrap');
    S.boot=fresh;syncExam(fresh.exam,fresh.server_time);startExamClock();
    if(S.exam&&!retakePending){throw Error('当前试卷仍在进行，请先交卷，再开始原卷重考。');}
    if(!retakePending||retakePending.id!==id){
      await saveDraft();
      retakePending={id,request_id:Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('')};
    }
    const exam=await api('exam/retake',retakePending);
    if(exam.finished){retakePending=null;await loadExamHistory();return;}
    for(const qid of exam.ids)removeStorage('localStorage','opsforge-lab-'+qid);
    syncExam(exam,exam.server_time);startExamClock();
    const {selectQuestion,loadList}=await import('../bank/controller.js');
    await selectQuestion(exam.ids[0],false);await loadList();
    retakePending=null;
  }catch(error){
    if(error.status===409)retakePending=null;
    throw error;
  }finally{retaking=false;if(button.isConnected)button.disabled=false;render();}
}

export function examReportView(){
  const data=S.examReport;
  if(!data&&!S.examReportId)return '';
  return `<div class="card" data-exam-report>${data?`<h3>本次考试报告</h3><p class="muted">试卷编号：${esc(data.id)}</p><h2 data-exam-score>${data.score_status==='final'?`卷面成绩：${data.score} / 100 分`:`已评得分：${data.earned_points??0} / 100 分 · 待评 ${data.pending_count??0} 题`}</h2><p data-exam-classification><strong class="tag ${data.grade_band==='excellent'||data.grade_band==='passed'?'green':'amber'}">${esc(data.grade_label||'待评')}</strong><span class="tag ${data.late?'amber':''}">${esc(data.submission_label||'正常交卷')}</span></p><p>自动评分 ${data.automatic_points??0} 分；文字面试自评 ${data.self_review_points??0} 分；待评部分 ${data.pending_points??0} 分。</p><p>${esc(data.scoring_rule||'旧记录尚未生成百分制成绩。')}</p><p>点击题目查看本次作答、验收依据及参考答案。未同步的答案可从“未同步草稿”下载保留。</p><table><thead><tr><th>题号 / 题目</th><th>得分 / 满分</th><th>判定与依据</th></tr></thead><tbody>${data.results.map(r=>`<tr><td><button class="flat" data-action="attempt" data-id="${r.attempt_id}">${r.number}. ${inlineRich(r.title)}</button></td><td>${r.points===null?'待评':r.points} / ${r.max_points}</td><td>${esc(r.method)} · ${r.passed===null?'待评':r.passed?'通过':'未通过'}<br>${esc(r.message||'')}</td></tr>`).join('')}</tbody></table>`:'<h3>考试报告尚未加载</h3>'}${S.examReportError?`<p class="notice">${esc(S.examReportError)}</p>`:''}<button data-action="exam-report-retry">重新读取报告</button></div>`;
}

export async function restoreExamReport(){
  const id=readStorage('sessionStorage','opsforge-last-exam');
  if(!id)return;
  S.examReportId=id;
  try{S.examReport=await api('exam/result?id='+encodeURIComponent(id));S.examReportError='';}
  catch{S.examReportError='暂时无法读取上次考试报告，可在模拟考试页重试。';}
}

async function restorePractice(){
  const pending=S.examDraftRefresh;
  if(!pending)return;
  const {question,context}=pending;
  if(S.q!==question||S.draftContext!==context){S.examDraftRefresh=null;return;}
  const normal=await api('question?id='+encodeURIComponent(question.id));
  if(S.q===question&&S.draftContext===context){
    await preserveDraft(context);
    if(S.q===question&&S.draftContext===context)await adoptDraft(question.id,normal.draft);
  }
  if(S.examDraftRefresh===pending)S.examDraftRefresh=null;
}

export async function retryExamReport(){
  const id=S.examReportId;if(!id)return;
  try{
    const data=await api('exam/result?id='+encodeURIComponent(id));
    const fresh=await api('bootstrap');
    if(id!==S.examReportId)return;
    S.examReport=data;
    S.boot=fresh;syncExam(fresh.exam,fresh.server_time);startExamClock();
    await restorePractice();
    S.examReportError='';
  }catch(error){S.examReportError='报告或普通练习暂时无法刷新：'+error.message;}
  render();
}

export function syncExam(exam, serverTime){
  if(!exam){S.exam=null;clearInterval(timers.examClock);return;}
  const ids=exam.ids||JSON.parse(exam.payload).ids;
  S.exam={id:exam.id,ids,deadline:exam.deadline,clockDeadline:performance.now()+Math.max(0,exam.deadline-serverTime)*1000};
}
export function startExamClock(){clearInterval(timers.examClock);timers.examClock=setInterval(updateExamTime,1000);}
export function updateExamTime(){
  if(!S.exam)return;
  const sec=Math.max(0,Math.ceil((S.exam.clockDeadline-performance.now())/1000));
  const clock=document.querySelector('#exam-time');
  if(clock)clock.textContent=Number.isFinite(sec)?`剩余 ${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`:'正在同步考试时间';
  if(sec===0&&!S.finishing)safe(()=>finishExam(true));
}
export async function finishExam(automatic=false){
  if(S.finishing)return;
  if(!S.exam){await retryExamReport();return;}
  const exam=S.exam,context=S.draftContext,question=S.q;
  reportRequest++;
  S.finishing=true;
  const {cancelQuestionSelection}=await import('../bank/controller.js');
  cancelQuestionSelection();
  const app=document.querySelector('#app'),wasInert=app.inert;
  app.inert=true;app.setAttribute('aria-busy','true');
  try{
    let data;
    try{data=await api('exam/result?id='+encodeURIComponent(exam.id));}
    catch(error){if(error.status!==409)throw error;}
    if(!data&&!automatic&&(!Number.isFinite(exam.clockDeadline)||performance.now()<exam.clockDeadline))await saveDraft();
    await preserveDraft(context);
    if(!data)data=await api('exam/finish',{id:exam.id,automatic});
    if(S.exam?.id!==exam.id)return;
    S.examReport=data;S.examReportId=exam.id;S.examReportError='';
    writeStorage('sessionStorage','opsforge-last-exam',exam.id);
    S.examDraftRefresh=question&&S.q===question&&S.draftContext===context?{question,context}:null;
    syncExam(null);
    S.page='exam';render();document.querySelector('#exam-report')?.scrollIntoView({block:'start'});
    try{
      const fresh=await api('bootstrap');
      S.boot=fresh;syncExam(fresh.exam,fresh.server_time);startExamClock();
      await restorePractice();
      await loadExamHistory();
    }
    catch(error){S.examReportError='交卷已成功，普通练习暂时无法恢复：'+error.message;}
    render();
  }catch(error){
    if(automatic&&error.status===409){const fresh=await api('bootstrap');syncExam(fresh.exam,fresh.server_time);}
    throw error;
  }finally{S.finishing=false;app.inert=wasInert;app.removeAttribute('aria-busy');}
}
