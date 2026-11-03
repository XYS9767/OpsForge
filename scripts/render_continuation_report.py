"""Render a self-contained local continuation report from a verified checkpoint."""
import argparse
import collections
import datetime
import html
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--progress', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = json.loads(args.progress.read_text(encoding='utf8'))
    if report.get('status') != 'passed':
        parser.error('Only a passed independent delta audit may be rendered')
    if args.output.exists():
        parser.error('Refusing to overwrite an existing report')
    esc = html.escape
    remaining = report['remaining']
    completed = report['completed']
    continuation_total = report['verified_delta'] + report['remaining_count']
    remaining_percent = round(report['remaining_count'] / continuation_total * 100, 1)
    created_at = datetime.datetime.fromisoformat(report['created_at']).astimezone(datetime.timezone(datetime.timedelta(hours=8)))
    display_time = created_at.strftime('%Y-%m-%d %H:%M:%S') + '（北京时间）'
    counts = collections.Counter(row['module'] for row in remaining)
    format_names = {'single_choice':'单选','multiple_choice':'多选','true_false':'判断','fill_blank':'填空',
                    'short_answer':'简答','code':'编程','practice':'实操','case':'故障场景','project':'综合项目','acceptance':'验收'}
    def pending_row(row):
        values = [row['module'], format_names[row['format']], row['task_id'], row['title'], row['reason']]
        return '<tr data-module="'+esc(row['module'],quote=True)+'">'+''.join('<td>'+esc(str(v))+'</td>' for v in values)+'</tr>'
    def done_row(row):
        label = '模块验收：'+row['module_review']['reviewed_module'] if row['format']=='acceptance' else row['question_id']
        basis = '不消耗题号' if row['format']=='acceptance' else ('新增题号' if row['new_question_id'] else '复用原题号')
        return '<tr>'+''.join('<td>'+esc(str(v))+'</td>' for v in [row['module'],format_names[row['format']],row['task_id'],label,basis])+'</tr>'
    options = '<option value="">全部模块</option>'+''.join('<option value="'+esc(module,quote=True)+'">'+esc(module)+' · '+str(count)+'</option>' for module,count in sorted(counts.items()))
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OpsForge 续作进度与剩余任务</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6fb;color:#173148;font:15px/1.65 "Microsoft YaHei",sans-serif}main{max-width:1560px;margin:auto;padding:32px 24px}h1{font-size:30px;margin:0 0 8px}h2{font-size:21px;margin:0 0 12px}p{margin:8px 0}section{background:white;border:1px solid #d8e3ed;border-radius:12px;padding:22px;margin:20px 0}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.stat{padding:20px;background:#eaf3fc;border-radius:10px}.stat b{display:block;font-size:32px;color:#145d89}.note{color:#526b7f}.status{display:inline-block;background:#dff5e9;color:#175d3e;padding:3px 10px;border-radius:20px}.table{overflow:auto;max-height:70vh;border:1px solid #d6e0e9}table{width:100%;border-collapse:collapse;font-size:13px;min-width:850px}td,th{padding:10px;border-bottom:1px solid #dce4ec;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#edf3fa;position:sticky;top:0}tr:nth-child(even){background:#fafcff}select,input{font:inherit;padding:10px;border:1px solid #a9bed0;border-radius:6px;max-width:100%}.filters{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:16px}.filters input{flex:1;min-width:200px}code{word-break:break-all}@media(max-width:700px){main{padding:20px 12px}.stats{grid-template-columns:1fr}section{padding:16px}h1{font-size:24px}}
</style></head><body><main>'''
    page += '<h1>OpsForge 续作进度与剩余任务</h1><p class="note">检查点生成时间：'+esc(display_time)+' · <span class="status">本轮逐项审计通过</span></p>'
    page += '<section><div class="stats"><div class="stat">本轮独立核验完成<b>'+str(report['verified_delta'])+'</b>个去重工作项</div><div class="stat">原清单剩余<b>'+str(report['remaining_count'])+'</b>个工作项</div><div class="stat">本轮待办剩余比例<b>'+str(remaining_percent)+'%</b>'+str(report['remaining_count'])+' / '+str(continuation_total)+'</div></div>'
    page += '<p><strong>统计边界：</strong>原包声明已完成4444项，但未包含checkpoint434审计原件，本轮未独立重现这4444项。可独立复核的是本轮新增完成的'+str(report['verified_delta'])+'项。仅沿用历史声明的条件总进度为'+str(report['conditional_total_completed'])+' / 5786（'+str(report['conditional_percent'])+'%），不作为本轮独立验收比例。</p>'
    page += '<p>其中新增题号'+str(report['new_question_ids'])+'个，复用原题号'+str(report['reused_question_ids'])+'个，独立验收项'+str(report.get('acceptance_items',0))+'个；验收项不消耗题号。重复执行、恢复验收工具和额外测试路线均不计新增工作项。</p></section>'
    module_note = 'Python模块已按当前235题完成独立复核，3个变体组排除后计232道唯一题；其他模块复核仍保留。' if report.get('acceptance_items',0) else '完整模块语义复核仍保留。'
    page += '<section><h2>验收范围与未完成事项</h2><p>已逐项核对原任务ID、目标模块和题型、实际题库加载、内容指纹、源码及验收器摘要、四路线及独立错误方案。开放简答为人工自评知识题；离线算法和原生本地机制按各题明确范围验收。</p><p>'+module_note+'全局语义重复证明、干净目标机离线恢复及最终五轮PC验收仍保留在剩余清单。未构建镜像、未推送、未部署、未更改默认身份。当前报告页面检查不计最终五轮PC验收。</p></section>'
    page += '<section><h2>本轮已完成 · '+str(len(completed))+'项</h2><div class="table"><table><thead><tr><th>模块</th><th>题型</th><th>原工作项</th><th>实际题号</th><th>题号口径</th></tr></thead><tbody>'+''.join(done_row(row) for row in completed)+'</tbody></table></div></section>'
    page += '<section><h2>全部剩余任务 · '+str(len(remaining))+'项</h2><div class="filters"><select id="module" aria-label="模块筛选">'+options+'</select><input id="query" aria-label="搜索任务" placeholder="搜索任务ID、标题、要求"><span id="count">'+str(len(remaining))+' / '+str(len(remaining))+'</span></div><div class="table"><table id="remaining"><thead><tr><th>模块</th><th>题型</th><th>唯一任务ID</th><th>待完成内容</th><th>原清单原因与要求</th></tr></thead><tbody>'+''.join(pending_row(row) for row in remaining)+'</tbody></table></div></section>'
    page += '''</main><script>const rows=[...document.querySelectorAll('#remaining tbody tr')];function filter(){const m=document.getElementById('module').value,q=document.getElementById('query').value.toLowerCase();let n=0;for(const r of rows){const show=(!m||r.dataset.module===m)&&r.textContent.toLowerCase().includes(q);r.hidden=!show;if(show)n++;}document.getElementById('count').textContent=n+' / '+rows.length;}document.getElementById('module').onchange=filter;document.getElementById('query').oninput=filter;</script></body></html>'''
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x',encoding='utf8') as handle:
        handle.write(page)
    print(str(args.output.resolve()))


if __name__ == '__main__':
    main()
