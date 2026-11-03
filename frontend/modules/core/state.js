export const types = {source:'原始问答',practice:'基础实操',scenario:'环境演练',interview:'面试文字题',case:'排障方案题',code:'编程 / 配置',generated:'随机变式'};
export const questionFormats = {single_choice:'单选',multiple_choice:'多选',true_false:'判断',fill_blank:'填空',short_answer:'简答',code:'编程',practice:'实操',case:'故障场景',project:'综合项目'};
export const questionTypeLabel = q => questionFormats[q.question_format] || types[q.type] || q.type;
export const levels = ['L0 · 入门','L1 · 简单','L2 · 进阶','L3 · 综合','L4 · 高级','L5 · 项目挑战'];
export const completions={not_started:'未开始',in_progress:'进行中',submitted:'已提交'};
export const masteries={unrated:'待评价',mastered:'已掌握',review:'待复习'};
export function learningLabel(q){return (completions[q?.learning?.completion]||'未开始')+' · '+(masteries[q?.learning?.mastery]||'待评价');}
export function markLearningStarted(){
  if(!S.q||S.q.learning?.completion==='submitted')return;
  S.q.learning={completion:'in_progress',mastery:'unrated'};
  document.querySelectorAll('[data-learning-status]').forEach(node=>node.textContent=learningLabel(S.q));
}
export const S = {boot:null, sessionEpoch:0, page:'work', pane:'list', tab:'terminal', filters:{}, list:[], total:0, listPage:1,
  q:null, draft:null, lab:null, log:[], checks:null, hintIndex:0, selectedFile:null, csrf:'', busy:false, submitting:false, exam:null, commandHistory:[], historyIndex:0};
export const timers = {};
