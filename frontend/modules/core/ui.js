import { S, types, questionTypeLabel, levels, timers } from './state.js';
import MarkdownIt from '../../vendor/markdown-it.js';

export const $ = s => document.querySelector(s);
export const esc = v => String(v ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
export function toast(message){$('#toast').textContent=message;$('#toast').style.display='block';clearTimeout(timers.toastTimer);timers.toastTimer=setTimeout(()=>$('#toast').style.display='none',4500);}

const markdown=new MarkdownIt({html:false,breaks:true,linkify:false,typographer:false});
markdown.renderer.rules.image=(tokens,index)=>{
  const token=tokens[index],src=token.attrGet('src')||'';
  return /^\/source-assets\/[a-zA-Z0-9_.%/-]+$/.test(src)&&!src.includes('..')
    ? `<img class="source-image" alt="${esc(token.content)}" src="${esc(src)}" loading="lazy">`
    : esc(token.content);
};
markdown.renderer.rules.link_open=(tokens,index,options,env,self)=>{
  tokens[index].attrSet('target','_blank');tokens[index].attrSet('rel','noopener noreferrer');
  return self.renderToken(tokens,index,options);
};
export function rich(text){return markdown.render(String(text??''));}
// Button titles support inline markup, but must not contain nested links/images.
const titleMarkdown=new MarkdownIt({html:false,linkify:false}).disable(['link','image','autolink']);
export function inlineRich(text){return titleMarkdown.renderInline(String(text??''));}

export function highlight(text){
  const pattern=/(#[^\n]*|\/\/[^\n]*|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`[^`]*`|\b(?:def|return|if|else|elif|for|while|in|import|from|class|try|except|raise|with|as|True|False|None|func|package|var|const|type|struct|interface|go|range|defer|select|case|switch|nil|make|chan|FROM|RUN|COPY|WORKDIR|USER|EXPOSE|ENTRYPOINT|CMD|AS|then|fi|do|done|exit|function)\b|\b\d+(?:\.\d+)?\b)/g;
  let result='',pos=0;
  for(const match of text.matchAll(pattern)){
    const t=match[0];result+=esc(text.slice(pos,match.index));
    const type=/^(#|\/\/|\/\*)/.test(t)?'comment':/^["'`]/.test(t)?'string':/^\d/.test(t)?'number':'keyword';
    result+=`<span class="tok-${type}">${esc(t)}</span>`;pos=match.index+t.length;
  }
  return result+esc(text.slice(pos))+'\n';
}

export function options(items,value,empty='全部'){return `<option value="">${empty}</option>`+items.map(([v,l])=>`<option value="${esc(v)}" ${String(value)===String(v)?'selected':''}>${esc(l)}</option>`).join('');}

export function tags(q){return `<span class="tag blue">${esc(levels[q.level??1])}</span><span class="tag">${esc(questionTypeLabel(q))}</span>`+(q.tags||[q.category]).slice(0,4).map(t=>`<span class="tag">${esc(t)}</span>`).join('');}

export async function safe(fn){try{return await fn();}catch(e){console.error(e);toast(e.message||String(e));}}
