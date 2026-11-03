// Markdown rendering is scoped to the oral memorization page.
// Raw HTML is escaped. Only HTTPS links are allowed.
import { esc } from '../core/ui.js';

function inline(value){
  return esc(value)
    .replace(/`([^`\n]+)`/g,'<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')
    .replace(/\[([^\]\n]+)\]\((https:\/\/[^\s<>"']+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}
export function oralMarkdown(markdown){
  const lines=String(markdown||'').replace(/\r/g,'').split('\n');
  let out='',paragraph=[],list=null,code=null,language='';
  const flush=()=>{if(paragraph.length){out+='<p>'+inline(paragraph.join('\n')).replace(/\n/g,'<br>')+'</p>';paragraph=[];}};
  const closeList=()=>{if(list){out+='</'+list+'>';list=null;}};
  for(const line of lines){
    if(line.startsWith('```')){
      flush();closeList();
      if(code!==null){out+=`<pre><span class="code-language">${esc(language)}</span><code>${esc(code.join('\n'))}</code></pre>`;code=null;}
      else{code=[];language=line.slice(3).trim();}
      continue;
    }
    if(code!==null){code.push(line);continue;}
    const heading=line.match(/^(#{1,6})\s+(.+)$/);
    const item=line.match(/^\s*(?:([-*+])\s+|\d+\.\s+)(.+)$/);
    if(heading){flush();closeList();const level=heading[1].length;out+=`<h${level}>${inline(heading[2])}</h${level}>`;}
    else if(item){flush();const kind=item[1]?'ul':'ol';if(list!==kind){closeList();out+='<'+kind+'>';list=kind;}out+='<li>'+inline(item[2])+'</li>';}
    else if(/^>\s?/.test(line)){flush();closeList();out+='<blockquote>'+inline(line.replace(/^>\s?/,''))+'</blockquote>';}
    else if(/^---+$/.test(line)){flush();closeList();out+='<hr>';}
    else if(!line.trim()){flush();closeList();}
    else{closeList();paragraph.push(line);}
  }
  flush();closeList();
  if(code!==null)out+='<pre><code>'+esc(code.join('\n'))+'</code></pre>';
  return out;
}
