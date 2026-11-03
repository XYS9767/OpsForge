import { S, types, questionFormats, questionTypeLabel, levels, completions, masteries, learningLabel } from '../core/state.js';
import { inlineRich, esc, options, safe } from '../core/ui.js';
import { api } from '../core/api.js';
import { readStorage, writeStorage } from '../core/storage.js';
import { render } from '../views/shell.js';
import { loadList, selectQuestion } from './controller.js';
import { saveDraft } from '../learning/controller.js';

let sequence = 0;
let opened = {};
try {
  const raw = readStorage('localStorage', 'opsforge-curriculum-open') || '{}';
  const saved = raw.length <= 2_000_000 ? JSON.parse(raw) : {};
  if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
    opened = Object.fromEntries(Object.entries(saved).filter(([key, value]) => key.length < 200 && typeof value === 'boolean'));
  }
} catch { /* A corrupt preference must not prevent the bank from opening. */ }
S.catalogFilters = {search:'', level:'', format:'',completion:'',mastery:''};

function persist() {
  writeStorage('localStorage', 'opsforge-curriculum-open', JSON.stringify(opened));
}
function activeFilter() { return Object.values(S.catalogFilters).some(Boolean); }
function details(key, css, summary, content) {
  const open = Object.hasOwn(opened,key) ? opened[key] : activeFilter();
  return `<details class="catalog-node ${css}" data-catalog-key="${esc(key)}" ${open?'open':''}><summary>${summary}<span class="catalog-chevron" aria-hidden="true">⌄</span></summary>${content}</details>`;
}
function heading(name, count, kind) {
  return `<span class="catalog-label"><small>${kind}</small><strong>${esc(name)}</strong></span><span class="catalog-count">${count} 题</span>`;
}
function levelView(topic, level) {
  const filters = {...S.catalogFilters, topic_id:topic.id, level:String(level.level)};
  const items = level.items.slice(0,20).map(q => `<button class="catalog-question" data-action="select" data-id="${esc(q.id)}"><span>${inlineRich(q.title)}</span><small>${esc(questionTypeLabel(q))} · ${learningLabel(q)}</small><span aria-hidden="true">→</span></button>`).join('');
  const more = level.count > 20 ? `<button class="small" data-action="catalog-list" data-filters="${esc(JSON.stringify(filters))}">查看此难度全部 ${level.count} 题 →</button>` : '';
  return details(`${topic.id}:L${level.level}`, 'catalog-level', heading(level.name,level.count,`L${level.level} · 难度`), `<div class="catalog-questions">${items}${more}</div>`);
}
export function curriculumView() {
  const tree = S.catalogBoot === S.boot && S.catalog ? S.catalog : S.boot.curriculum;
  if (!tree) return '<main class="page"><p>正在读取题库目录…</p></main>';
  const groups = tree.groups.filter(g => !activeFilter() || g.count).map((g,i) => {
    const children = g.children.filter(s => !activeFilter() || s.count).map(s => {
      const topics = s.topics.map(t => details(t.id,'catalog-topic',heading(t.name,t.count,'知识专题'),`<div class="catalog-children">${t.levels.map(l=>levelView(t,l)).join('')}</div>`)).join('');
      const browse = `<button class="small" data-action="catalog-list" data-submodule="${esc(s.id)}" data-filters="${esc(JSON.stringify({...S.catalogFilters,submodule:s.id}))}">查看本模块全部 ${s.count} 题 →</button>`;
      return details(`sub:${s.id}`,'catalog-submodule',heading(s.name,s.count,'子模块'),topics?`<div class="catalog-children">${browse}${topics}</div>`:'<p class="catalog-empty">暂无已审校题目。</p>');
    }).join('');
    return details(`group:${g.id}`,'catalog-group',heading(g.name,g.count,`${String(i+1).padStart(2,'0')} / 总模块`),`<div class="catalog-children">${children}</div>`);
  }).join('');
  return `<main class="page catalog-page"><div class="page-heading"><div><div class="eyebrow">QUESTION LIBRARY</div><h1>从一个方向，练到解决问题。</h1><p>总模块 → 子模块 → 知识专题 → 难度。展开标题，选择适合自己的练习。</p></div><button class="primary" data-action="catalog-random">随机抽题 →</button></div>
    <div class="catalog-toolbar"><label class="catalog-search">搜索题目或专题<input id="catalog-search" value="${esc(S.catalogFilters.search)}" placeholder="例如：Shell、日志、权限…"></label><label>难度<select id="catalog-level">${options(levels.map((v,i)=>[i,v]),S.catalogFilters.level,'全部难度')}</select></label><label>题型<select id="catalog-type">${options(Object.entries(questionFormats),S.catalogFilters.format,'全部题型')}</select></label><label>完成状态<select id="catalog-completion">${options(Object.entries(completions),S.catalogFilters.completion,'全部完成状态')}</select></label><label>掌握状态<select id="catalog-mastery">${options(Object.entries(masteries),S.catalogFilters.mastery,'全部掌握状态')}</select></label><button data-action="catalog-search">筛选</button><button data-action="catalog-clear">重置</button></div>
    <div class="row between catalog-meta"><span role="status">${S.catalogLoading?'正在更新…':`当前目录 ${tree.count} 道题 · 每题只在一个位置计数`}</span><div class="row"><button class="flat" data-action="catalog-expand">全部展开</button><button class="flat" data-action="catalog-collapse">全部收起</button></div></div>
    ${tree.unassigned_count?`<p class="notice">另有 ${tree.unassigned_count} 道已发布题目尚待归类，可在练习工作台检索。</p>`:''}
    <section class="catalog-tree" aria-label="分层题库目录">${groups||'<p class="catalog-empty">没有符合条件的题目，请调整搜索词或筛选条件。</p>'}</section></main>`;
}

export async function loadCurriculum() {
  const ticket = ++sequence, filters = {...S.catalogFilters}, epoch = S.sessionEpoch;
  S.catalogLoading = true;
  try {
    const tree = await api('curriculum?' + new URLSearchParams(filters));
    if(ticket !== sequence || S.sessionEpoch !== epoch) return;
    S.catalog = tree; S.catalogBoot = S.boot;
  } finally {
    if(ticket === sequence) {
      S.catalogLoading = false;
      if(S.page === 'modules' && S.sessionEpoch === epoch) render();
    }
  }
}

export function bindCurriculum() {
  document.querySelectorAll('[data-catalog-key]').forEach(node => node.addEventListener('toggle', () => {
    if(!node.isConnected) return;
    // Rendering an already remembered open node also emits toggle. Avoid
    // thousands of identical storage writes after expanding the whole bank.
    if(opened[node.dataset.catalogKey] === node.open) return;
    opened[node.dataset.catalogKey] = node.open; persist();
  }));
  const search = document.querySelector('#catalog-search');
  if(search) search.onkeydown = e => { if(e.key === 'Enter') safe(()=>curriculumAction('catalog-search')); };
  for(const id of ['catalog-level','catalog-type','catalog-completion','catalog-mastery']) {
    const node = document.getElementById(id);
    if(node) node.onchange = () => safe(()=>curriculumAction('catalog-search'));
  }
}

export async function curriculumAction(action, button) {
  if(action === 'catalog-expand' || action === 'catalog-collapse') {
    document.querySelectorAll('[data-catalog-key]').forEach(node => { opened[node.dataset.catalogKey] = action === 'catalog-expand'; });
    persist(); render(); return;
  }
  if(action === 'catalog-list') {
    await saveDraft(); S.filters=JSON.parse(button.dataset.filters); S.listPage=1;
    await loadList(); S.page='work'; S.pane='list'; render(); return;
  }
  if(action === 'catalog-random') {
    const q = await api('random',{filters:S.catalogFilters}); await selectQuestion(q.id); return;
  }
  S.catalogFilters = action === 'catalog-clear' ? {search:'',level:'',format:'',completion:'',mastery:''} : {
    search:document.getElementById('catalog-search').value.trim(),
    level:document.getElementById('catalog-level').value,
    format:document.getElementById('catalog-type').value,
    completion:document.getElementById('catalog-completion').value,
    mastery:document.getElementById('catalog-mastery').value
  };
  await loadCurriculum();
}
