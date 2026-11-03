import { api } from '../core/api.js';
import { inlineRich, rich, esc, $ } from '../core/ui.js';
import { S } from '../core/state.js';
import { selectQuestion } from '../bank/controller.js';

let query='',kind='all',page=1,sequence=0,noteRequest=0;
export function notesView(){
  return `<main class="page notes-page"><div class="page-heading"><div><h1>我的笔记</h1><p>当前笔记随题目继续编辑；历史笔记保留提交当时的内容。重新练习会清空当前笔记，已提交的历史笔记保留。</p></div></div><form id="notes-search-form" class="card row wrap"><label>搜索<input id="notes-search" maxlength="200" placeholder="题目、模块或笔记内容" value="${esc(query)}"></label><label>来源<select id="notes-kind">${[['all','全部笔记'],['current','当前笔记'],['history','历史提交笔记']].map(([v,t])=>`<option value="${v}" ${kind===v?'selected':''}>${t}</option>`).join('')}</select></label><button class="primary" type="submit">搜索</button></form><div id="notes-results" aria-live="polite"><div class="loading">正在读取笔记…</div></div></main>`;
}
export function bindNotes(){
  const form=$('#notes-search-form');
  if(form)form.onsubmit=e=>{e.preventDefault();query=$('#notes-search').value.trim();kind=$('#notes-kind').value;page=1;loadNotes();};
}
export async function loadNotes(){
  const ticket=++sequence,root=$('#notes-results');if(!root)return;
  try{
    const d=await api('notes?'+new URLSearchParams({search:query,kind,page}));
    if(ticket!==sequence||S.page!=='notes'||!root.isConnected)return;
    page=d.page;
    root.innerHTML=`${d.exam_hidden?'<p class="notice">当前考试涉及题目的旧笔记暂不可查看，交卷后恢复。</p>':''}<p class="muted">共 ${d.total} 条笔记</p>${d.items.length?d.items.map(n=>`<article class="card note-entry"><div class="row between"><span class="tag">${n.kind==='current'?'当前笔记':'历史提交笔记'}</span><span class="muted">${new Date(n.updated*1000).toLocaleString('zh-CN')}</span></div><h3>${inlineRich(n.title)}</h3><p class="muted">${esc(n.category)}</p><pre class="note-preview">${esc(n.preview)}</pre><button data-action="notes-open" data-kind="${n.kind}" data-id="${esc(n.id)}">查看完整笔记</button></article>`).join(''):'<div class="card empty">暂无匹配笔记。在题目左侧填写「我的笔记」并保存后，即可在这里找到。</div>'}<div class="row between"><button data-action="notes-prev" ${page<=1?'disabled':''}>上一页</button><span>${page} / ${Math.max(1,Math.ceil(d.total/d.size))}</span><button data-action="notes-next" ${page*d.size>=d.total?'disabled':''}>下一页</button></div>`;
  }catch(e){if(root.isConnected&&ticket===sequence)root.innerHTML=`<div class="card error">${esc(e.message)} <button data-action="notes-retry">重试</button></div>`;}
}
export async function notesAction(action,button){
  if(action==='notes-prev'||action==='notes-next'){page+=action==='notes-next'?1:-1;return loadNotes();}
  if(action==='notes-retry')return loadNotes();
  if(action==='notes-question'){button.closest('.modal-backdrop')?.remove();return selectQuestion(button.dataset.qid);}
  if(action!=='notes-open')return;
  const ticket=++noteRequest,listSequence=sequence,root=$('#notes-results');
  button.disabled=true;
  let n;
  try{
    ({note:n}=await api('note?'+new URLSearchParams({kind:button.dataset.kind,id:button.dataset.id})));
  }finally{if(button.isConnected)button.disabled=false;}
  if(ticket!==noteRequest||listSequence!==sequence||S.page!=='notes'||!root?.isConnected)return;
  document.querySelector('[data-notes-modal]')?.remove();
  const panel=document.createElement('div');panel.className='modal-backdrop';panel.dataset.notesModal='';
  panel.innerHTML=`<div class="modal"><div class="row between"><h2>${n.kind==='current'?'当前笔记':'历史提交笔记'}</h2><button data-action="close-modal">关闭</button></div><h3>${inlineRich(n.title)}</h3><p class="muted">${new Date(n.updated*1000).toLocaleString('zh-CN')}${n.version?' · v'+n.version:''}</p><div class="note-content prose">${rich(n.notes)}</div><button data-action="notes-question" data-qid="${esc(n.qid)}">打开题目${n.kind==='current'?'继续编辑':''}</button>${n.kind==='history'?'<p class="muted">此处为历史快照，打开题目不会把旧笔记写入当前草稿。</p>':''}</div>`;
  document.body.append(panel);
}
