"""Bounded, keyset-paginated material export; not a database backup."""
import json
from .errors import ApiError


def page(db, table, after='', through=None, decode_payload=False, custom_only=False):
    if table not in ('questions', 'drafts', 'attempts', 'favorites'):
        raise ApiError('未知归档部分')
    numeric = table == 'attempts'
    if custom_only and table != 'questions':
        raise ApiError('迁移分片只支持自定义题目')
    selection = " AND id LIKE 'custom-%'" if custom_only else ''
    try:
        after = int(after or 0) if numeric else str(after)
        if through is None:
            through = db.execute(f'SELECT MAX(id) FROM {table} WHERE 1=1' + selection).fetchone()[0]
        elif numeric:
            through = int(through)
    except (ValueError, TypeError):
        raise ApiError('归档游标无效')
    if through is None:
        return {'items': [], 'next': None, 'through': None}
    rows = db.execute(f'SELECT * FROM {table} WHERE id>? AND id<=?' + selection + ' ORDER BY id LIMIT 100', (after, through))
    items, size, cursor = [], 0, after
    for row in rows:
        item = json.loads(row['payload']) if decode_payload else row['id'] if table == 'favorites' else dict(row)
        length = len(json.dumps(item, ensure_ascii=False).encode('utf-8'))
        if items and size + length > 4_000_000:
            break
        if length > 8_000_000:
            raise ApiError('单条资料超过归档分片上限，请使用数据库备份', 413)
        items.append(item);size += length;cursor = row['id']
    more = bool(items) and db.execute(f'SELECT 1 FROM {table} WHERE id>? AND id<=?' + selection + ' LIMIT 1', (cursor, through)).fetchone() is not None
    return {'items': items, 'next': cursor if more else None, 'through': through}
