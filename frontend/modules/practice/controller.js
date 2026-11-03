import { toast, safe, $ } from '../core/ui.js';
import { api } from '../core/api.js';
import { render } from '../views/shell.js';
import { S, timers, markLearningStarted } from '../core/state.js';
import { writeStorage, removeStorage } from '../core/storage.js';

const starts=new Map();
export function labStarting(qid){return starts.has(qid);}

export function startLab(mode,docker=false,cluster=false,resume=false){
  const qid=S.q.id;
  if(starts.has(qid))return starts.get(qid);
  const question=S.q,oldLab=S.lab;
  const operation=Promise.resolve().then(async()=>{
    const lab=await api('lab/start',{id:question.id,mode,docker,cluster,replace_id:oldLab?.id,resume});
    if(lab.cleanup_pending)toast('新工作区已创建，旧工作区仍在后台清理');
    lab.environment=lab.environment||(cluster?'cluster':docker?'docker':mode);
    writeStorage('localStorage','opsforge-lab-'+question.id,lab.id);
    if(S.q!==question)return;
    S.lab=lab;S.checks=lab.checks;S.log=[];
    if(lab.mode==='real'&&!resume)markLearningStarted();
    if(lab.mode==='real')pollLab(lab);
  }).finally(()=>{starts.delete(qid);if(S.q===question)render();});
  starts.set(qid,operation);
  render();
  return operation;
}

export async function stopLab(){
  if(labStarting(S.q.id))throw Error('工作区正在创建，请等待完成');
  const question=S.q,lab=S.lab;
  if(lab){try{const stopped=await api('lab/stop',{id:lab.id});if(!stopped.stopped){toast('工作区正在清理，后台会继续重试');return;}}catch(error){if(error.status!==404)throw error;}}
  removeStorage('localStorage','opsforge-lab-'+question.id);
  if(S.q!==question||S.lab!==lab)return;
  S.lab=null;S.checks=null;clearInterval(timers.labPoll);render();toast('工作区已销毁，已保存草稿仍保留');
}

export function pollLab(lab){
    clearInterval(timers.labPoll);
    const sid=lab.id;let polling=false;
    const timer=setInterval(()=>safe(async()=>{
      if(polling)return;
      if(S.lab?.id!==sid){clearInterval(timer);return;}
      polling=true;
      try{
        const state=await api('lab/status?id='+sid);
        if(S.lab?.id!==sid){clearInterval(timer);return;}
        if($('#lab-phase'))$('#lab-phase').textContent=state.ready?'真实工作区已就绪':state.reason||state.phase;
        if(state.ready){clearInterval(timer);S.lab.ready=true;toast('真实工作区已就绪，可执行命令');}
        if(['Failed','Succeeded'].includes(state.phase)){clearInterval(timer);toast('工作区已结束，请查看部署日志后重建');}
      }catch(e){clearInterval(timer);if(S.lab?.id===sid)throw e;}finally{polling=false;}
    }),3500);
    timers.labPoll=timer;
}

export async function runCommand(command,timeout=20){
  if(S.busy)return;
  const c=typeof command==='string'?command:$('#command')?.value.trim();
  if(!c)return;
  if(!S.lab)throw Error('请先创建实验环境');
  S.busy=true;S.commandHistory.push(c);S.historyIndex=S.commandHistory.length;S.log.push({kind:'cmd',text:'student@opsforge ❯ '+c});
  if($('#command'))$('#command').value='';
  const labId=S.lab.id;render();
  try{
    const data=await api('lab/command',{id:labId,command:c,timeout});
    if(S.lab?.id!==labId)return;
    markLearningStarted();
    S.log.push({kind:'out',text:data.output||'(命令完成，无输出)'});
    if(data.state)S.lab.state=data.state;if(data.checks)S.checks=data.checks;
  }finally{S.busy=false;render();const out=$('#terminal-output');if(out)out.scrollTop=out.scrollHeight;$('#command')?.focus();}
}
