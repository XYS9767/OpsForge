"""Read-only notebook over existing drafts and immutable submission snapshots."""
import json
from core.errors import ApiError


class NotesService:
    def notes_entries(self, kind='all'):
        if kind not in ('all', 'current', 'history'):
            raise ApiError('未知笔记类型')
        exam = self.active_exam()
        hidden = set(json.loads(exam['payload'])['ids']) if exam else set()
        entries = []
        with self.db('learning') as db:
            drafts = [dict(r) for r in db.execute("SELECT id,notes,updated FROM drafts WHERE TRIM(notes)<>''")] if kind != 'history' else []
            attempts = [dict(r) for r in db.execute('SELECT id,qid,submission,snapshot,created FROM attempts WHERE submission IS NOT NULL')] if kind != 'current' else []
        ids = [r['id'] for r in drafts if r['id'] not in hidden]
        labels = {}
        for start in range(0, len(ids), 200):
            labels.update(self.question_labels(ids[start:start+200]))
        for r in drafts:
            if r['id'] in hidden or not r['notes'].strip():
                continue
            label = labels.get(r['id'], {'title': r['id'], 'category': '原题已不存在'})
            entries.append({'id': r['id'], 'qid': r['id'], 'kind': 'current',
                            'notes': r['notes'], 'updated': r['updated'], **label})
        for r in attempts:
            if r['qid'] in hidden:
                continue
            notes = (json.loads(r['submission'] or '{}') or {}).get('notes', '')
            if not notes.strip():
                continue
            q = json.loads(r['snapshot'])
            entries.append({'id': str(r['id']), 'qid': r['qid'], 'kind': 'history',
                            'title': q['title'], 'category': q.get('category', ''),
                            'notes': notes, 'updated': r['created'], 'version': q.get('version', 1)})
        entries.sort(key=lambda r: (r['updated'], r['kind'], r['id']), reverse=True)
        return entries, bool(hidden)

    def route_notes(self, method, path, args):
        if method != 'GET' or path not in ('/api/notes', '/api/note'):
            return None
        kind = args.get('kind', 'all')
        entries, hidden = self.notes_entries(kind)
        if path == '/api/note':
            if kind not in ('current', 'history'):
                raise ApiError('请选择笔记类型')
            note = next((r for r in entries if r['id'] == args.get('id')), None)
            if note is None:
                raise ApiError('笔记不存在，或当前考试期间暂不可查看', 404)
            return {'note': note}, []
        search = args.get('search', '').strip().casefold()
        if len(search) > 200:
            raise ApiError('搜索内容最多 200 字符')
        entries = [r for r in entries if not search or search in
                   ' '.join((r['title'], r['category'], r['notes'], r['qid'])).casefold()]
        page, size = max(1, int(args.get('page', 1))), min(50, max(1, int(args.get('size', 20))))
        total = len(entries)
        page = min(page, max(1, (total + size - 1) // size))
        items = [{**{k: v for k, v in r.items() if k != 'notes'}, 'preview': r['notes'][:200]}
                 for r in entries[(page-1)*size:page*size]]
        return {'items': items, 'total': total, 'page': page, 'size': size, 'exam_hidden': hidden}, []
