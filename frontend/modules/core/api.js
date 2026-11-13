import { loginView } from './session.js';
import { S } from './state.js';

export async function api(path,body){
  const epoch=S.sessionEpoch;
  const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',
    headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':S.csrf},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await r.json();
  if(epoch!==S.sessionEpoch)throw new Error('会话已变化，已忽略旧请求结果');
  if(!r.ok){if(r.status===401){loginView();}const error=new Error(data.error||'请求失败');error.status=r.status;throw error;}return data;
}
