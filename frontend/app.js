import { toast, safe, $ } from './modules/core/ui.js';
import { api } from './modules/core/api.js';
import { loginView, boot, startupError } from './modules/core/session.js';
import { loadList, selectQuestion, questionModal, saveQuestion, closeModal } from './modules/bank/controller.js';
import { saveDraft, submit, progress, attemptModal, restartPractice } from './modules/learning/controller.js';
import { archiveBlob, transferFiles, downloadTransfer } from './modules/bank/archive.js';
import { loadStudy, studyAction } from './modules/study/controller.js';
import { startLab, stopLab, runCommand } from './modules/practice/controller.js';
import { startExamClock, finishExam, syncExam, retryExamReport, loadExamHistory, examHistoryAction, navigateExam, checkpointExam } from './modules/exams/controller.js';
import { render } from './modules/views/shell.js';
import { S, timers } from './modules/core/state.js';
import { showDraftConflict, downloadDraft, recoveryDialog, validateNewFile } from './modules/learning/drafts.js';
import { curriculumAction, loadCurriculum } from './modules/bank/curriculum.js';
import { loadNotes, notesAction } from './modules/learning/notes.js';

document.addEventListener('click',e=>{
  const b=e.target.closest('[data-action]');if(!b||b.disabled)return;
  if(e.detail>1&&['submit','self-rating'].includes(b.dataset.action))return;
  safe(async()=>{
    const a=b.dataset.action;
    if(a==='nav'){
      await saveDraft();S.page=b.dataset.page;render();
      if(S.page==='work'){
        const q=S.q;
        if(q){const fresh=await api('question?id='+encodeURIComponent(q.id));if(S.q===q)q.learning=fresh.question.learning;}
        await loadList();if(S.page==='work')render();
      }
      if(S.page==='progress')await progress();if(S.page==='study')await loadStudy();if(S.page==='modules')await loadCurriculum();if(S.page==='exam')await loadExamHistory();
      if(S.page==='notes')await loadNotes();
    }
    else if(a.startsWith('notes-'))await notesAction(a,b);
    else if(a.startsWith('catalog-'))await curriculumAction(a,b);
    else if(a.startsWith('study-'))await studyAction(a,b);
    else if(a==='pane'){S.pane=b.dataset.pane;if(S.pane==='list')await loadList();render();}
    else if(a==='tab'){S.tab=b.dataset.tab;render();}
    else if(a==='select')await selectQuestion(b.dataset.id);
    else if(a==='attempt')await attemptModal(b.dataset.id);
    else if(a==='save'){await saveDraft();toast('已保存');}
    else if(a==='draft-conflict')await showDraftConflict();
    else if(a==='download-draft')downloadDraft();
    else if(a==='recover-drafts')await recoveryDialog();
    else if(a==='favorite'){
      const id=S.q.id,draft=S.draft,enabled=!draft.favorite;b.disabled=true;
      try{
        await api('favorite',{id,enabled});draft.favorite=enabled;
        if(S.q?.id===id)S.draft.favorite=enabled;
        S.boot=await api('bootstrap');
      }finally{if(b.isConnected)b.disabled=false;render();}
    }
    else if(a==='prev'||a==='next'){S.listPage+=a==='next'?1:-1;await loadList();render();}
    else if(a==='module'){await saveDraft();S.filters={module:b.dataset.module};S.listPage=1;await loadList();S.page='work';S.pane='list';render();}
    else if(a==='random'){const q=await api('random',{filters:S.filters});await selectQuestion(q.id);}
    else if(a==='variant'){const q=await api('random',S.q?.type==='scenario'?{mode:'scenario',scenario:S.q.id.split(':')[1]}:{mode:'generated',template:S.q?.template});await selectQuestion(q.id);}
    else if(a==='hint'){const id=S.q.id;const d=await api('hint',{id,version:S.q.version||1,index:S.hintIndex});if(id!==S.q.id)return;S.hintIndex++;const p=document.createElement('div');p.className='hint';p.textContent=d.hint;$('#hints').append(p);}
    else if(a==='practice-restart')await restartPractice();
    else if(a.startsWith('exam-history-')||a==='exam-retake')await examHistoryAction(a,b);
    else if(a==='submit')await submit();
    else if(a==='self-rating')await submit(b.dataset.rating);
    else if(a==='start-lab'){const mode=$('#env-mode').value;if(!mode)throw Error('请选择要创建的工作区类型');await startLab(mode==='simulation'?'simulation':'real',mode==='docker',mode==='cluster');}
    else if(a==='stop-lab')await stopLab();
    else if(a==='run-command')await runCommand();
    else if(a==='clear-terminal'){S.log=[];render();}
    else if(a==='fill-command'){$('#command').value=b.dataset.command;$('#command').focus();}
    else if(a==='file'){S.selectedFile=b.dataset.file;render();}
    else if(a==='new-file'){const name=prompt('文件路径，例如 main.go 或 chart/values.yaml');if(name){validateNewFile(name,S.draft.files);Object.defineProperty(S.draft.files,name,{value:'',enumerable:true,writable:true,configurable:true});S.selectedFile=name;render();await saveDraft();}}
    else if(a==='delete-file'){if(S.selectedFile&&confirm('删除当前草稿文件？')){delete S.draft.files[S.selectedFile];S.selectedFile=Object.keys(S.draft.files)[0];render();await saveDraft();}}
    else if(a==='run-code'){
      const command=$('#run-code-command').value,question=S.q,lab=S.lab;
      await saveDraft();if(S.q!==question||S.lab!==lab)return;
      if(lab?.mode!=='real')throw Error('先创建真实工作区，再运行代码');
      if(question.exercise&&question.automatic_grading&&(!command.trim()||command.trim()===(question.run||'').trim())){
        if(S.exam?.ids.includes(question.id)){await checkpointExam();toast('本题验收快照已保存，交卷后显示结果');}
        else {await submit();$('#feedback')?.scrollIntoView({block:'nearest'});}
      }else{
        if(!command.trim())throw Error('请输入运行命令');
        const result=await api('lab/files',{id:lab.id,files:S.draft.files});
        if(S.q!==question||S.lab!==lab)return;if(result.exit_code)throw Error(result.output);
        S.tab='terminal';await runCommand('cd /workspace\n'+command,120);
      }
    }
    else if(a==='cloud-scene'){await selectQuestion(`scenario:${b.dataset.provider}:beginner`);S.tab='resources';render();}
    else if(a==='cloud-command')await runCommand(b.dataset.command);
    else if(a==='cloud-cidr')await runCommand('cloud network allow '+$('#cidr').value);
    else if(a==='show-favorites'||a==='show-wrong'){S.filters={[a==='show-favorites'?'favorite':'wrong']:'1'};S.listPage=1;await loadList();S.page='work';S.pane='list';render();}
    else if(['exam-prev','exam-next','exam-jump'].includes(a))await navigateExam(a,b.dataset.id);
    else if(a==='exam-check'){await checkpointExam();toast('本题验收快照已保存，交卷后显示结果');}
    else if(a==='exam-resume'){await checkpointExam();S.page='exam';render();}
    else if(a==='exam-start'){
      const countNode=$('#exam-count'),minutesNode=$('#exam-minutes');
      if(!countNode.reportValidity()||!minutesNode.reportValidity())return;
      const count=Number(countNode.value),minutes=Number(minutesNode.value);
      if(!Number.isInteger(count)||!Number.isInteger(minutes)||count<1||count>50||minutes<1||minutes>180)throw Error('请输入有效的题数和时长');
      const selectedFormat=$('#exam-type').value;
      const filters={module:$('#exam-module').value,level:$('#exam-level').value,...(selectedFormat==='generated'?{type:'generated'}:{format:selectedFormat})};
      b.disabled=true;
      try{await saveDraft();const exam=await api('exam/start',{count,minutes,filters});syncExam(exam,exam.server_time);await selectQuestion(exam.ids[0],false);startExamClock();}
      finally{if(b.isConnected)b.disabled=false;}
    }
    else if(a==='exam-finish')await finishExam();
    else if(a==='exam-report-retry')await retryExamReport();
    else if(a==='pending-bank'||a==='published-bank'){await saveDraft();S.filters=a==='pending-bank'?{review:'pending'}:{};S.listPage=1;await loadList();S.page='work';S.pane='list';render();}
    else if(a==='review-question'){const note=prompt('请填写核对依据（至少 12 字）：适用版本、实际验证结果或官方资料。此操作会把当前题目发布到练习和考试。');if(note){await api('review',{id:S.q.id,version:S.q.version,note});S.boot=await api('bootstrap');await selectQuestion(S.q.id);toast('已审校发布');}}
    else if(a==='export'||a==='archive'){
      b.disabled=true;const label=b.textContent;
      try{
        if(a==='archive'){
          const blob=await archiveBlob((section,count)=>{b.textContent=`正在归档 ${section}：${count}`;});
          const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='OpsForge-full-archive.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),5000);
        }else{downloadTransfer(await transferFiles(count=>{b.textContent=`正在导出自定义题：${count}`;}));}
        toast(a==='archive'?'资料归档已导出；完整恢复请使用数据库备份':'迁移文件已准备好；导入后需要审校');
      }finally{b.disabled=false;b.textContent=label;}
    }
    else if(a==='import')$('#import-file').click();
    else if(a==='new-question')questionModal();
    else if(a==='edit-question')questionModal(true);
    else if(a==='close-modal')closeModal(b.closest('.modal-backdrop'));
    else if(a==='save-question')await saveQuestion(b);
    else if(a==='logout'){await saveDraft();await api('logout',{});S.boot=null;loginView();}
  });
});
$('#app').innerHTML='<div class="loading">正在连接实训平台…</div>';
boot().catch(startupError);
