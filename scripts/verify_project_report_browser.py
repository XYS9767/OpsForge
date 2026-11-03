"""Verify a local OpsForge report at PC viewports without editing the report."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from browser_runtime import report_browser


INSPECT = r'''() => {
  const visible = element => {
    const box = element.getBoundingClientRect(), style = getComputedStyle(element);
    return box.width > 0 && box.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const headings = [...document.querySelectorAll('h1,h2,h3')].filter(visible).map(e => e.innerText.trim());
  const progress = [...document.querySelectorAll('h1,h2,h3,.hero,[role="status"]')]
    .filter(visible).map(e => e.innerText.trim()).filter(text => /进度|总体|完成|剩余|progress/i.test(text));
  const tables = [...document.querySelectorAll('table')].map(table => {
    const rows = [...table.rows];
    const header = rows.find(row => row.querySelector('th'));
    const columns = header ? [...header.cells].reduce((n, cell) => n + cell.colSpan, 0) : 0;
    const data = rows.filter(row => row.querySelector('td'));
    const inconsistent = data.filter(row => [...row.cells].reduce((n, cell) => n + cell.colSpan, 0) !== columns).length;
    let scrollContainer = null;
    for (let parent = table.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      const style = getComputedStyle(parent);
      if (['auto','scroll'].includes(style.overflowX)) { scrollContainer = parent; break; }
    }
    const box = table.getBoundingClientRect();
    return {section_title: table.closest('section')?.querySelector('h2')?.innerText.trim() || '',
      headers: header ? [...header.cells].map(e => e.innerText.trim()) : [],
      columns, rows: data.length, inconsistent_rows: inconsistent,
      visible: visible(table), width: Math.round(box.width),
      horizontal_scroll_available: !!scrollContainer,
      horizontal_scroll_needed: !!scrollContainer && scrollContainer.scrollWidth > scrollContainer.clientWidth + 1,
      overflowing_without_scroll: box.right > innerWidth + 1 && !scrollContainer};
  });
  const inheritance = [...document.querySelectorAll('p')].filter(e => /未独立重现/.test(e.innerText)).map(e => {
    const box = e.getBoundingClientRect();
    return {text: e.innerText.trim(), visible: visible(e), within_initial_viewport: box.top >= 0 && box.bottom <= innerHeight};
  });
  return {title: document.title, headings, progress_titles: progress, inheritance_notes: inheritance,
    progress_excerpt: document.body.innerText.slice(0, 5000), tables,
    viewport_width: innerWidth, document_width: document.documentElement.scrollWidth,
    horizontal_page_overflow: document.documentElement.scrollWidth > innerWidth + 1,
    body_font_px: parseFloat(getComputedStyle(document.body).fontSize),
    replacement_characters: document.body.innerText.includes(String.fromCharCode(0xfffd)),
    broken_images: [...document.images].filter(image => !image.complete || image.naturalWidth === 0).length};
}'''


def verify(html, output, *, expected_completed=None, expected_remaining=None, expected_inherited=None):
    original = html.read_bytes()
    source_hash = hashlib.sha256(original).hexdigest()
    report = {'schema': 1, 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'scope': 'Local HTML report layout and controls only; not application or final five-round PC acceptance.',
              'html': str(html), 'html_sha256': source_hash,
              'browser': None, 'viewports': [], 'screenshots': [], 'console_errors': [],
              'page_errors': [], 'failed_requests': [], 'blocked_requests': [], 'issues': [],
              'controls': {'status': 'not_present'}}
    report['verifier_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['runtime_sha256'] = hashlib.sha256(Path(__file__).with_name('browser_runtime.py').read_bytes()).hexdigest()
    report['expected_workitems'] = {'completed': expected_completed, 'remaining': expected_remaining,
                                  'inherited_not_independently_reproduced': expected_inherited}
    target_uri = html.as_uri()
    try:
        with report_browser() as (context, metadata):
            report['browser'] = metadata
            page = context.new_page()
            page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
            page.on('console', lambda message: report['console_errors'].append(message.text) if message.type == 'error' else None)
            page.on('requestfailed', lambda request: report['failed_requests'].append({'url': request.url, 'failure': request.failure}))

            def local_only(route):
                url = route.request.url
                if url == target_uri or urlsplit(url).scheme in ('data', 'blob'):
                    route.continue_()
                else:
                    report['blocked_requests'].append(url)
                    route.abort()

            page.route('**/*', local_only)
            page.goto(target_uri, wait_until='load', timeout=30000)
            page.evaluate('document.fonts.ready')
            for width, height in [(1440, 1000), (1280, 900)]:
                page.set_viewport_size({'width': width, 'height': height})
                page.evaluate('window.scrollTo(0, 0)')
                snapshot = page.evaluate(INSPECT)
                snapshot['height'] = height
                report['viewports'].append(snapshot)
                filename = f'pc-{width}x{height}.png'
                page.screenshot(path=str(output / filename), full_page=True, animations='disabled')
                report['screenshots'].append(filename)
                prefix = str(width) + 'px: '
                if not snapshot['headings'] or not any('OpsForge' in text for text in snapshot['headings']):
                    report['issues'].append(prefix + 'missing visible OpsForge heading')
                if not snapshot['progress_titles']:
                    report['issues'].append(prefix + 'missing visible progress or remaining-work title')
                if not re.search(r'\d+(?:\.\d+)?\s*%|\d+\s*/\s*\d+|剩余\s*\d+', snapshot['progress_excerpt']):
                    report['issues'].append(prefix + 'missing numeric progress evidence')
                if not snapshot['tables'] or not any(table['rows'] for table in snapshot['tables']):
                    report['issues'].append(prefix + 'missing report data table')
                for index, table in enumerate(snapshot['tables'], 1):
                    if not table['visible'] or table['columns'] < 2 or table['inconsistent_rows']:
                        report['issues'].append(prefix + f'invalid table structure #{index}')
                    if table['overflowing_without_scroll']:
                        report['issues'].append(prefix + f'inaccessible table overflow #{index}')
                if snapshot['horizontal_page_overflow']:
                    report['issues'].append(prefix + 'page overflows the desktop viewport horizontally')
                if snapshot['body_font_px'] < 12:
                    report['issues'].append(prefix + 'body font is too small for the report PC baseline')
                if snapshot['replacement_characters'] or snapshot['broken_images']:
                    report['issues'].append(prefix + 'encoding replacement character or broken image')
                if expected_completed is not None and expected_remaining is not None:
                    counts = [table['rows'] for table in snapshot['tables']]
                    snapshot['observed_workitem_counts'] = counts
                    if counts != [expected_completed, expected_remaining] or sum(counts) != expected_completed + expected_remaining:
                        report['issues'].append(prefix + 'completed/remaining row counts differ from the expected checkpoint')
                if expected_inherited is not None:
                    notes = [note for note in snapshot['inheritance_notes'] if str(expected_inherited) in note['text']]
                    if not any(note['visible'] and note['within_initial_viewport'] for note in notes):
                        report['issues'].append(prefix + 'inherited historical claim limitation is not visible in the initial PC viewport')
            # Existing report controls are checked only when their documented IDs
            # and row data attributes are present. Other report layouts may omit them.
            if page.locator('#query').count() == 1 and page.locator('tbody tr[data-module]').count():
                query = page.locator('#query')
                before = page.locator('tbody tr[data-module]:visible').count()
                query.fill('__opsforge_no_such_task_7c3d9c__')
                empty = page.locator('tbody tr[data-module]:visible').count()
                query.fill('')
                restored = page.locator('tbody tr[data-module]:visible').count()
                controls = {'status': 'passed', 'initial_rows': before, 'search_empty_rows': empty, 'restored_rows': restored}
                if empty != 0 or restored != before:
                    controls['status'] = 'failed'
                    report['issues'].append('search filter did not hide and restore report rows')
                if page.locator('#module').count() == 1:
                    values = page.locator('#module option').evaluate_all('(options) => options.map(o => o.value).filter(Boolean)')
                    if values:
                        page.locator('#module').select_option(values[0])
                        modules = page.locator('tbody tr[data-module]:visible').evaluate_all('(rows) => rows.map(r => r.dataset.module)')
                        page.locator('#module').select_option('')
                        controls['module_value'] = values[0]
                        controls['module_rows'] = len(modules)
                        if not modules or any(module != values[0] for module in modules):
                            controls['status'] = 'failed'
                            report['issues'].append('module filter selected rows from the wrong module')
                report['controls'] = controls
    except Exception as error:
        report['issues'].append(type(error).__name__ + ': ' + str(error))
    report['source_unchanged'] = html.read_bytes() == original
    if not report['source_unchanged']:
        report['issues'].append('source HTML changed during verification')
    for field in ('console_errors', 'page_errors', 'failed_requests', 'blocked_requests'):
        if report[field]:
            report['issues'].append(field.replace('_', ' ') + ' were observed')
    report['status'] = 'passed' if not report['issues'] else 'failed'
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'status': report['status'], 'screenshots': report['screenshots'],
                      'issues': report['issues'], 'verification': str(output / 'verification.json')}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--expected-completed', type=int)
    parser.add_argument('--expected-remaining', type=int)
    parser.add_argument('--expected-inherited', type=int)
    args = parser.parse_args()
    html = args.html.resolve()
    output = args.output.absolute()
    if not html.is_file() or html.suffix.lower() not in ('.html', '.htm'):
        parser.error('--html must be an existing local HTML file')
    if output.exists() or output.is_symlink():
        parser.error('--output must be a new directory; existing outputs are never overwritten')
    if (args.expected_completed is None) != (args.expected_remaining is None):
        parser.error('--expected-completed and --expected-remaining must be provided together')
    if any(value is not None and value < 0 for value in (args.expected_completed, args.expected_remaining, args.expected_inherited)):
        parser.error('expected counts cannot be negative')
    output.mkdir(parents=True, exist_ok=False)
    return verify(html, output, expected_completed=args.expected_completed,
                  expected_remaining=args.expected_remaining, expected_inherited=args.expected_inherited)


if __name__ == '__main__':
    raise SystemExit(main())
