import { api } from '../core/api.js';

export async function transferFiles(progress){
  const header='{"format":"opsforge-transfer-v1","questions":[';
  const files=[];let parts=[header],bytes=header.length+2,fileCount=0;
  let after='',through=null,count=0;
  const flush=()=>{files.push({blob:new Blob([...parts,'] }'],{type:'application/json'}),count:fileCount});parts=[header];bytes=header.length+2;fileCount=0;};
  do{
    const params=new URLSearchParams({mode:'transfer',section:'questions',after:String(after)});
    if(through!==null)params.set('through',String(through));
    const page=await api('export?'+params);through=page.through;
    for(const item of page.items){
      const text=JSON.stringify(item),length=new TextEncoder().encode(text).length+1;
      if(fileCount&&(bytes+length>16000000||fileCount>=1000))flush();
      parts.push((fileCount?',':'')+text);bytes+=length;fileCount++;count++;
    }
    progress(count);after=page.next;
  }while(after!==null);
  if(fileCount||!files.length)flush();
  return files;
}

export function downloadTransfer(files){
  const save=(blob,name)=>{const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),5000);};
  if(files.length===1){save(files[0].blob,'OpsForge-question-transfer.json');return;}
  const panel=document.createElement('div');panel.className='modal-backdrop';
  panel.innerHTML='<section class="modal"><h2>下载题库迁移分片</h2><p>每份均可直接导入，按序导入全部文件；每份独立校验和保存。导出期间请暂停编辑。</p><div class="transfer-downloads"></div><button data-action="close-modal">关闭</button></section>';
  files.forEach((file,index)=>{
    const name=`OpsForge-question-transfer-${String(index+1).padStart(2,'0')}.json`;
    const button=document.createElement('button');button.dataset.transferPart=String(index+1);
    button.textContent=`下载第 ${index+1}/${files.length} 份 · ${file.count} 道题`;
    button.onclick=()=>{save(file.blob,name);button.textContent=`再次下载第 ${index+1}/${files.length} 份 · ${file.count} 道题`;};
    panel.querySelector('.transfer-downloads').append(button);
  });
  document.body.append(panel);
}

export async function archiveBlob(progress){
  const parts=['{"format":"opsforge-archive-v1","note":"分片资料归档用于查阅；导出期间请暂停编辑。事务一致恢复请使用数据库备份。"'];
  for(const section of ['questions','drafts','attempts','favorites']){
    parts.push(',"'+section+'":[');
    let after='',through=null,first=true,count=0;
    do{
      const params=new URLSearchParams({mode:'archive',section,after:String(after)});
      if(through!==null)params.set('through',String(through));
      const page=await api('export?'+params);
      through=page.through;
      for(const item of page.items){parts.push((first?'':',')+JSON.stringify(item));first=false;count++;}
      progress(section,count);after=page.next;
    }while(after!==null);
    parts.push(']');
  }
  parts.push('}');
  return new Blob(parts,{type:'application/json'});
}
