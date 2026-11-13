import { api } from './api.js';
import { loadList, selectQuestion } from '../bank/controller.js';
import { startExamClock, syncExam, restoreExamReport } from '../exams/controller.js';
import { readStorage, storageUnavailable } from './storage.js';
import { $, esc, toast } from './ui.js';
import { S, timers } from './state.js';

export function loginView(){
  S.sessionEpoch++;S.csrf='';
  document.querySelectorAll('.modal-backdrop').forEach(panel=>panel.remove());
  clearInterval(timers.labPoll);clearInterval(timers.examClock);
  clearTimeout(timers.saveTimer);S.exam=null;S.finishing=false;S.boot=null;
  S.examReport=null;S.examReportId=null;S.examReportError='';S.examDraftRefresh=null;
  S.examHistory=null;
  $('#app').innerHTML=`<div class="login"><div class="login-art"><div class="brand"><div class="brand-mark">of</div><div><strong>OpsForge</strong><small>云栈实训 · DevOps Practice Lab</small></div></div><div class="eyebrow" style="margin-top:70px">LEARN BY DOING</div><h1>把问题查清楚。<br>把技术练扎实。</h1><p>从第一条 Linux 命令，到跨组件故障排查。<br>题目、终端与代码，在同一个工作台。</p><div class="terminal-preview">$ kubectl get pods<br><span style="color:#9cafc7">NAME &nbsp; READY &nbsp; STATUS<br>your-next-step &nbsp; 1/1 &nbsp; Running</span><br>$ _</div></div><div class="login-form"><form id="login-form"><div class="eyebrow" style="color:#0d9c7d">YOUR PRACTICE WORKSPACE</div><h2>进入实训工作台</h2><p class="muted">按模块选题，也可以从一个真实问题开始。</p><label for="password">平台访问密码</label><input id="password" type="password" required minlength="12" autocomplete="current-password" placeholder="输入部署时设置的访问密码"><button class="primary">进入工作台 →</button><div id="login-error" class="error" style="font-size:12px;margin-top:15px"></div><p class="muted">个人练习平台 · 进度持久保存<br>参考答案默认隐藏，需要时再展开。</p></form></div></div>`;
  $('#login-form').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{const d=await api('login',{password:$('#password').value});S.csrf=d.csrf;await boot();}catch(err){const node=$('#login-error');if(node)node.textContent=err.message;else startupError(err);}finally{b.disabled=false;}};
}

export function startupError(error){
  if(error.status===401){loginView();return;}
  if($('.task-body')){toast(error.message);return;}
  $('#app').innerHTML=`<main class="page"><section class="card"><h2>暂时无法加载工作台</h2><p>${esc(error.message||'连接失败，请稍后重试')}</p><button class="primary" id="startup-retry">重新连接</button><p class="muted">重试不会清空学习记录或本地草稿。</p></section></main>`;
  $('#startup-retry').onclick=async event=>{
    event.currentTarget.disabled=true;
    try{await boot();}catch(next){startupError(next);}
  };
}

export async function boot(){
  S.boot=await api('bootstrap');S.csrf=S.boot.csrf;
  syncExam(S.boot.exam,S.boot.server_time);
  await restoreExamReport();
  await loadList();
  const remembered=readStorage('localStorage','opsforge-question');
  await selectQuestion(remembered||'scenario:permissions:beginner',false);
  startExamClock();
  if(storageUnavailable){const note=document.createElement('p');note.className='notice';note.textContent='浏览器存储受限，请确认服务器保存成功，并及时下载未同步草稿。';document.querySelector('#app').prepend(note);}
}
