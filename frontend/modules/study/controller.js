import { S, completions, masteries, learningLabel } from '../core/state.js';
import { $, esc, options, safe, toast } from '../core/ui.js';
import { api } from '../core/api.js';
import { render } from '../views/shell.js';
import { oralMarkdown } from './markdown.js';

const state={items:[],module:'',completion:'',mastery:'',favorites:false,index:0,loaded:false,request:0};
export async function loadStudy(){
  const request=++state.request;
  const params=new URLSearchParams({module:state.module,completion:state.completion,mastery:state.mastery,favorite:state.favorites?'1':'',paged:'1'});
  const items=[];let next='';
  do{
    params.set('after',next);const data=await api('study?'+params);
    if(request!==state.request)return;
    items.push(...data.items);next=data.next;
  }while(next);
  state.items=items;state.index=0;state.loaded=true;
  if(S.page==='study')render();
}
export function studyView(){
  const q=state.items[state.index];
  return `<main class="page oral-page"><div class="page-heading"><div><div class="eyebrow">INTERVIEW NOTES</div><h1>口述背题</h1><p>先自己说一遍，再展开答案。用自己的话讲清楚，比逐字背下来更重要。</p></div><button class="primary" data-action="study-export">导出当前范围 .md</button></div><div class="card row wrap oral-controls"><label>技术模块 <select id="study-module">${options(S.boot.modules.map(m=>[m.id,m.name]),state.module,'全部口述题')}</select></label><label>完成状态<select id="study-completion">${options(Object.entries(completions),state.completion,'全部完成状态')}</select></label><label>掌握状态<select id="study-mastery">${options(Object.entries(masteries),state.mastery,'全部掌握状态')}</select></label><label class="oral-check"><input type="checkbox" id="study-favorites" ${state.favorites?'checked':''}>只背收藏题</label><span class="muted">${state.items.length} 道口述题 · Markdown 阅读排版</span></div>
  ${!state.loaded?'<div class="loading">正在读取口述题…</div>':!q?'<div class="card empty">此范围暂无可背的口述题。可以切换模块，或先收藏口述题。</div>':`
  <article class="oral-document markdown"><div class="row between"><span class="oral-category">${esc(q.category)} · L${q.level} · ${learningLabel(q)}</span><button class="small" data-action="study-favorite">${q.favorite?'★ 已收藏':'☆ 收藏此题'}</button></div>
  ${oralMarkdown('# '+q.title)}<p class="oral-meta">题号 ${esc(q.id)} · v${q.version} · ${state.index+1} / ${state.items.length}</p>
  ${oralMarkdown(q.body||'')}
  <blockquote>先试着说出结论，再补一个例子或处理方法。没有做过的项目，不要说成亲身经历。</blockquote>
  <details id="oral-answer" class="oral-answer"><summary>展开口述参考答案</summary><div id="oral-content"></div></details>
  <hr><p class="muted">收藏不会因为答对或背完而取消。可以反复打开、反复练习。</p></article>
  <div class="oral-pagination row"><button data-action="study-prev" ${state.index===0?'disabled':''}>← 上一题</button><button data-action="study-random">随机一题</button><button data-action="study-next" ${state.index===state.items.length-1?'disabled':''}>下一题 →</button></div>`}</main>`;
}
export function bindStudy(){
  if(S.page!=='study')return;
  for(const key of ['completion','mastery'])$('#study-'+key).onchange=e=>{state[key]=e.target.value;safe(loadStudy);};
  $('#study-module').onchange=e=>{state.module=e.target.value;safe(loadStudy);};
  $('#study-favorites').onchange=e=>{state.favorites=e.target.checked;safe(loadStudy);};
  const details=$('#oral-answer'),q=state.items[state.index];
  if(details)details.addEventListener('toggle',()=>{if(details.open)safe(async()=>{
    const data=await api('answer',{id:q.id,version:q.version});
    if(!details.isConnected||data.id!==q.id||data.version!==q.version)return;
    $('#oral-content').innerHTML=oralMarkdown('## 面试时可以这样说\n\n'+data.answer)+(data.references?.length?oralMarkdown('### 核对资料\n\n'+data.references.map((u,i)=>`- [资料 ${i+1}](${u})`).join('\n')):'');
  });});
}
export async function studyAction(action,button){
  if(action==='study-export'){
    const params=new URLSearchParams({module:state.module,completion:state.completion,mastery:state.mastery,favorite:state.favorites?'1':'',paged:'1'});
    const chunks=[];let next='',data;
    if(button)button.disabled=true;
    try{
      do{params.set('after',next);data=await api('study/export?'+params);chunks.push(data.content);next=data.next;}while(next);
    }finally{if(button?.isConnected)button.disabled=false;}
    const url=URL.createObjectURL(new Blob(chunks,{type:'text/markdown;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download=data.filename;link.click();
    setTimeout(()=>URL.revokeObjectURL(url),5000);toast(`已导出 ${data.count} 道口述题`);return;
  }
  const q=state.items[state.index];if(!q)return;
  if(action==='study-favorite'){
    if(button)button.disabled=true;
    try{
      const enabled=!q.favorite;await api('favorite',{id:q.id,enabled});q.favorite=enabled;
      if(S.q?.id===q.id)S.draft.favorite=Number(enabled);
      if(state.favorites&&!enabled){state.items=state.items.filter(item=>item.id!==q.id);state.index=Math.max(0,Math.min(state.index,state.items.length-1));}
      S.boot=await api('bootstrap');
    }finally{if(button?.isConnected)button.disabled=false;render();}
    return;
  }
  else if(action==='study-next')state.index=Math.min(state.index+1,state.items.length-1);
  else if(action==='study-prev')state.index=Math.max(0,state.index-1);
  else if(action==='study-random')state.index=Math.floor(Math.random()*state.items.length);
  render();
}
