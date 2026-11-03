import { S, timers, markLearningStarted } from '../core/state.js';
import { api } from '../core/api.js';
import { $, esc, safe } from '../core/ui.js';
import { readStorage, writeStorage } from '../core/storage.js';

const token = () => Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');
// A new document always owns a new key, even when an opener cloned sessionStorage.
// Keep the previous owner only as a recovery preference for this tab's reloads.
const previousWriter = readStorage('sessionStorage','opsforge-writer');
const writer = token();
const resumesTab = ['reload','back_forward'].includes(performance.getEntriesByType('navigation')[0]?.type);
writeStorage('sessionStorage','opsforge-writer', writer);
let ignored;
try{ignored=JSON.parse(readStorage('sessionStorage','opsforge-ignored-drafts')||'[]');}catch{ignored=[];}
if(!Array.isArray(ignored))ignored=[];
function dismiss(record){
  if(record&&!ignored.includes(record.token))ignored.push(record.token);
  writeStorage('sessionStorage','opsforge-ignored-drafts',JSON.stringify(ignored));
}
let database;
// Retain a synchronous copy until IndexedDB accepts it or the server saves it.
// This also protects completed-exam drafts when persistent browser storage fails.
const memoryBackups=new Map();
const content = draft => ({text:draft.text||'', notes:draft.notes||'', files:draft.files||{}});
const serialize = draft => JSON.stringify(content(draft));

function db(){
  if(!database) database=new Promise((resolve,reject)=>{
    const request=indexedDB.open('opsforge-unsaved-drafts',1);
    request.onupgradeneeded=()=>request.result.createObjectStore('drafts',{keyPath:'key'});
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(request.error);
  });
  return database;
}
async function transaction(mode,run){
  const database=await db();
  return new Promise((resolve,reject)=>{
    const tx=database.transaction('drafts',mode);
    const request=run(tx.objectStore('drafts'));
    tx.oncomplete=()=>resolve(request?.result);
    tx.onerror=()=>reject(tx.error);
    tx.onabort=()=>reject(tx.error||Error('本地草稿写入中断'));
  });
}
async function removeBackup(record){
  if(!record)return;
  if(memoryBackups.get(record.key)?.token===record.token)memoryBackups.delete(record.key);
  const database=await db();
  await new Promise((resolve,reject)=>{
    const tx=database.transaction('drafts','readwrite'), store=tx.objectStore('drafts');
    const get=store.get(record.key);
    get.onsuccess=()=>{if(get.result?.token===record.token)store.delete(record.key);};
    tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);
  });
  // Retire this tab's earlier reload copies too, without touching newer tokens.
  for(const predecessor of record.predecessors||[])await removeBackup(predecessor);
}
function status(ctx,message){
  ctx.status=message;
  if(S.draftContext===ctx){const node=$('.save-state');if(node)node.textContent=message;}
}
function backup(ctx){
  const record={key:writer+'|'+ctx.scope+'|'+ctx.id,id:ctx.id,scope:ctx.scope,
    revision:ctx.revision,draft:JSON.parse(serialize(ctx.draft)),token:token(),updated:Date.now(),
    predecessors:ctx.retireRecovered&&ctx.recovered ?
      [...(ctx.recovered.predecessors||[]),{key:ctx.recovered.key,token:ctx.recovered.token}] : []};
  ctx.backup=record;
  memoryBackups.set(record.key,record);
  ctx.localWrite=(ctx.localWrite||Promise.resolve()).catch(()=>{}).then(()=>transaction('readwrite',store=>store.put(record)));
  ctx.localWrite.then(()=>{ctx.localError=false;if(memoryBackups.get(record.key)?.token===record.token)memoryBackups.delete(record.key);},()=>{ctx.localError=true;status(ctx,'本地备份失败，内容仅保留在本页，请保存或下载，勿关闭页面');});
  return ctx.localWrite;
}

export async function adoptDraft(id,draft){
  clearTimeout(timers.saveTimer);
  const ctx={id,scope:draft.scope,revision:draft.revision,draft,baseline:serialize(draft),status:'✓ 已保存',conflict:false};
  S.draft=draft;S.draftContext=ctx;
  try{
    const records=(await transaction('readonly',store=>store.getAll())).filter(r=>r.id===id&&r.scope===draft.scope&&!ignored.includes(r.token));
    const priority = record => record.key.startsWith(writer+'|') ? 2 :
      previousWriter && record.key.startsWith(previousWriter+'|') ? 1 : 0;
    records.sort((a,b)=>priority(b)-priority(a)||b.updated-a.updated);
    const saved=records[0];
    if(saved&&serialize(saved.draft)!==ctx.baseline){
      ctx.recovered=saved;
      ctx.retireRecovered=saved.key.startsWith(writer+'|') ||
        (resumesTab && previousWriter && saved.key.startsWith(previousWriter+'|'));
      Object.assign(draft,content(saved.draft));
      ctx.revision=saved.revision;
      ctx.conflict=saved.revision!==draft.revision;
      status(ctx,ctx.conflict?'已恢复本地草稿；服务器有新版本，请处理冲突':'已恢复未同步草稿，请保存');
      await backup(ctx);
    }else if(saved){await removeBackup(saved);}
  }catch{status(ctx,'本地备份不可用，请确认保存成功后再离开');}
  return ctx;
}

export function hasUnsavedDraft(){
  const ctx=S.draftContext;
  return !!ctx&&(!!ctx.saving||ctx.conflict||serialize(ctx.draft)!==ctx.baseline);
}

export function scheduleSave(){
  const ctx=S.draftContext;if(!ctx)return;
  status(ctx,'草稿已修改，正在保存…');
  backup(ctx);
  clearTimeout(timers.saveTimer);
  timers.saveTimer=setTimeout(()=>safe(saveDraft),700);
}

export function validateNewFile(name,files){
  const parts=name.split('/'), normalized=parts.filter(part=>part&&part!=='.').join('/');
  if(!name||Array.from(name).length>150||name.startsWith('/')||name.includes('\\')||name.includes('\0')||parts.includes('..')||!normalized)
    throw Error('文件必须使用工作区内的相对路径，最长 150 字符');
  const names=Object.keys(files).map(path=>path.split('/').filter(part=>part&&part!=='.').join('/'));
  if(names.includes(normalized))throw Error('文件已存在，或存在指向同一文件的路径');
  if(names.some(path=>path.startsWith(normalized+'/')||normalized.startsWith(path+'/')))
    throw Error('文件路径不能同时作为其他文件的目录');
  if(normalized==='.opsforge-sync.json'||normalized.startsWith('.opsforge-sync.json/'))
    throw Error('此路径用于工作区同步记录，请使用其他文件名');
  if(names.length>=30)throw Error('文件数量最多 30');
  const encoder=new TextEncoder();
  const size=Object.entries(files).reduce((total,[path,value])=>total+encoder.encode(path).length+encoder.encode(value).length,encoder.encode(name).length);
  if(size>500000)throw Error('文件内容与路径合计最多 500000 字节（UTF-8）');
}

export async function saveDraft(){
  clearTimeout(timers.saveTimer);
  const ctx=S.draftContext;if(!ctx)return;
  if(ctx.saving){await ctx.saving;return saveDraft();}
  if(ctx.conflict)throw Error('草稿存在版本冲突，请点击“处理冲突”；本地内容仍保留');
  const snapshot=serialize(ctx.draft);
  if(snapshot===ctx.baseline){
    // Explicitly accepting the server content must also retire its old local copy.
    const record=ctx.backup, recovered=ctx.recovered;
    try{
      await ctx.localWrite;
      await removeBackup(record);if(ctx.retireRecovered)await removeBackup(recovered);
      dismiss(recovered);if(ctx.recovered===recovered)ctx.recovered=null;
    }catch{status(ctx,'本地备份清理失败，请重试保存后再离开');throw Error('本地备份清理失败');}
    if(serialize(ctx.draft)!==ctx.baseline)return saveDraft();
    status(ctx,'✓ 已保存');return;
  }
  // Claim the save slot before waiting for IndexedDB, so double clicks cannot race.
  ctx.saving=(async()=>{
    try{
      const localWrite=backup(ctx), record=ctx.backup;
      try{await localWrite;}catch{ /* A successful server save can still protect the data. */ }
      status(ctx,'正在保存…');
      const result=await api('draft',{id:ctx.id,scope:ctx.scope,revision:ctx.revision,...JSON.parse(snapshot)});
      ctx.revision=result.revision;ctx.draft.revision=result.revision;ctx.baseline=snapshot;
      if(S.draftContext===ctx)markLearningStarted();
      try{await removeBackup(record);if(ctx.retireRecovered)await removeBackup(ctx.recovered);dismiss(ctx.recovered);ctx.recovered=null;}catch{ /* Server accepted this revision; stale local copies are checked on recovery. */ }
      if(serialize(ctx.draft)!==snapshot){await backup(ctx);status(ctx,'仍有新修改，等待保存…');}
      else status(ctx,'✓ 已保存');
    }catch(error){
      if(error.status===409){ctx.conflict=true;status(ctx,'版本冲突：本地内容已保留，请处理冲突');}
      else status(ctx,ctx.localError?'保存失败且本地备份不可用，请下载草稿，勿关闭页面':'保存失败，本地草稿保留；联网后点击保存重试');
      throw error;
    }finally{ctx.saving=null;}
  })();
  await ctx.saving;
  if(S.draftContext===ctx&&serialize(ctx.draft)!==ctx.baseline)return saveDraft();
}

export function downloadDraft(){
  const ctx=S.draftContext;if(!ctx)return;
  const blob=new Blob([JSON.stringify({id:ctx.id,scope:ctx.scope,revision:ctx.revision,...content(ctx.draft)},null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob), link=document.createElement('a');
  link.href=url;link.download='OpsForge-unsaved-draft.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),5000);
}

export async function showDraftConflict(){
  const ctx=S.draftContext;if(!ctx)return;
  if(ctx.saving)await ctx.saving.catch(()=>{});
  const {draft:remote}=await api('question?id='+encodeURIComponent(ctx.id));
  if(S.draftContext!==ctx)return;
  const panel=document.createElement('div');panel.className='modal-backdrop';
  panel.innerHTML=`<div class="modal"><h2>草稿版本冲突</h2><p>服务器内容不会被自动覆盖。请对照两份内容，在下方编辑合并结果。</p><h3>服务器版本</h3><textarea readonly id="draft-remote"></textarea><h3>本地内容 / 合并结果</h3><textarea id="draft-merged"></textarea><div class="row wrap"><button data-action="download-draft">下载本地副本</button><button id="draft-use-server">采用服务器版本</button><button id="draft-merge" ${remote.scope!==ctx.scope?'disabled':''}>保存合并结果</button><button data-action="close-modal">稍后处理</button></div><p>${remote.scope!==ctx.scope?'练习或考试已经切换，请先下载本地副本，再采用服务器版本。':''}</p></div>`;
  document.body.append(panel);
  panel.querySelector('#draft-remote').value=JSON.stringify(content(remote),null,2);
  panel.querySelector('#draft-merged').value=JSON.stringify(content(ctx.draft),null,2);
  panel.querySelector('#draft-use-server').onclick=()=>safe(async()=>{
    if(!confirm('采用服务器版本并放弃这份未同步草稿？需要保留时请先下载本地副本。'))return;
    await ctx.localWrite;
    await removeBackup(ctx.backup);if(ctx.retireRecovered)await removeBackup(ctx.recovered);
    dismiss(ctx.recovered);
    Object.assign(ctx.draft,remote);ctx.scope=remote.scope;ctx.revision=remote.revision;
    ctx.baseline=serialize(remote);ctx.conflict=false;status(ctx,'✓ 已加载服务器版本');
    panel.remove();location.reload();
  });
  panel.querySelector('#draft-merge').onclick=()=>safe(async()=>{
    if(S.draftContext!==ctx)throw Error('当前题目已变化，请重新处理冲突');
    const merged=JSON.parse(panel.querySelector('#draft-merged').value);
    if(!merged||typeof merged.text!=='string'||typeof merged.notes!=='string'||!merged.files||typeof merged.files!=='object'||Array.isArray(merged.files))throw Error('合并内容需要 text、notes 文本和 files 对象');
    Object.assign(ctx.draft,content(merged));ctx.revision=remote.revision;ctx.draft.revision=remote.revision;ctx.conflict=false;ctx.baseline=serialize(remote);
    await saveDraft();panel.remove();location.reload();
  });
}

window.addEventListener('online',()=>safe(saveDraft));
window.addEventListener('beforeunload',event=>{
  if(hasUnsavedDraft()||memoryBackups.size){event.preventDefault();event.returnValue='';}
});

export async function recoveryDialog(){
  let stored=[];
  try{stored=await transaction('readonly',store=>store.getAll());}catch{/* Memory copies remain available even without IndexedDB. */}
  const records=[...new Map([...stored,...memoryBackups.values()].map(record=>[record.key,record])).values()];
  const panel=document.createElement('div');panel.className='modal-backdrop';
  panel.innerHTML=`<div class="modal"><h2>未同步草稿</h2><p>考试结束后的本地答案仍可在此下载，下载不会修改服务器作答。</p>${recoveryNotice()}<div class="recovery-list"></div><button data-action="close-modal">关闭</button></div>`;
  const list=panel.querySelector('.recovery-list');
  for(const record of records){
    const button=document.createElement('button');button.textContent=`下载 ${record.id} · ${record.scope}`;
    button.onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='OpsForge-recovered-draft.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),5000);};
    list.append(button);
  }
  if(!records.length)list.textContent='没有未同步草稿';
  document.body.append(panel);
}

export function recoveryNotice(){
  return memoryBackups.size?'<p class="notice volatile-drafts">有未同步草稿仅保留在本页内存中，请从“未同步草稿”下载后再关闭或刷新页面。</p>':'';
}

export async function preserveDraft(ctx=S.draftContext){
  if(ctx&&(ctx.saving||ctx.conflict||serialize(ctx.draft)!==ctx.baseline)){
    try{await backup(ctx);}catch{return false;}
  }
  return true;
}
