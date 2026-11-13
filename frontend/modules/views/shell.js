import { updateExamTime, examBannerView } from '../exams/controller.js';
import { workView } from './workbench.js';
import { pageView } from './pages.js';
import { bindInputs, bindSplitter } from '../core/bindings.js';
import { $ } from '../core/ui.js';
import { S } from '../core/state.js';
import { recoveryNotice } from '../learning/drafts.js';
import { bindNotes } from '../learning/notes.js';

export function render(){
  if(!S.boot)return;
  const nav=[['work','练习工作台'],['modules','模块题库'],['study','口述背题'],['exam','模拟考试'],['progress','练习记录'],['notes','我的笔记'],['manage','题库管理']];
  $('#app').innerHTML=`<header class="header"><div class="brand"><div class="brand-mark">of</div><div><strong>OpsForge</strong><small>云栈实训</small></div></div><nav class="nav">${nav.map(([id,t])=>`<button data-action="nav" data-page="${id}" class="${S.page===id?'active':''}">${t}</button>`).join('')}</nav><div class="spacer"></div><div class="header-status"><span class="dot"></span> 个人实训空间</div><button class="flat" data-action="recover-drafts">未同步草稿</button><button class="flat logout" data-action="logout">退出</button></header>
  ${examBannerView()}
  ${recoveryNotice()}${S.page==='work'?workView():pageView()}`;
  bindInputs();bindNotes();if(S.page==='work')bindSplitter();updateExamTime();
}
