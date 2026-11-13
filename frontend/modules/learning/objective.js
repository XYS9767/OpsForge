import { esc } from '../core/ui.js';

export function objectiveAnswerView(question,text){
  const kind=question.question_format;
  if(['single_choice','multiple_choice','true_false'].includes(kind)&&Array.isArray(question.options)){
    let selected=[];
    try{const value=JSON.parse(text||'null');selected=Array.isArray(value)?value:typeof value==='string'?[value]:[];}catch{selected=text?[text]:[];}
    const multiple=kind==='multiple_choice';
    return `<fieldset class="answer-options"><legend>${multiple?'选择所有正确选项，漏选或多选均不通过。':'选择一个答案。'}</legend>${question.options.map(option=>`<label><input type="${multiple?'checkbox':'radio'}" name="format-choice" value="${esc(option.id)}" ${selected.includes(option.id)?'checked':''}> ${esc(option.id)}. ${esc(option.text)}</label>`).join('')}</fieldset>`;
  }
  if(kind==='fill_blank'&&Array.isArray(question.blanks)){
    let values={};try{const value=JSON.parse(text||'{}');if(value&&typeof value==='object'&&!Array.isArray(value))values=value;}catch{}
    return `<div class="answer-blanks">${question.blanks.map(blank=>`<label>${esc(blank.label)}<input type="text" data-blank-id="${esc(blank.id)}" value="${esc(typeof values[blank.id]==='string'?values[blank.id]:'')}" autocomplete="off"></label>`).join('')}</div>`;
  }
  return null;
}
