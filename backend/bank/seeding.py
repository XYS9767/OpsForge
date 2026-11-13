"""Upgrade managed builtins without overwriting locally modified questions."""
import hashlib
import json
import time
from .review import normalize


def fingerprint(question):
    payload = normalize(dict(question))
    payload.pop('version', None)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def retire_duplicates(questions, retirements):
    """Stop repeated builtins entering new practice without deleting history."""
    by_id = {q['id']: q for q in questions}
    changes = {}
    for item in retirements:
        qid, replacement = item['id'], item['replacement']
        if qid in changes or qid == replacement or qid not in by_id or replacement not in by_id:
            raise ValueError('Invalid duplicate question retirement')
        original, target = by_id[qid], by_id[replacement]
        if (fingerprint(original) != item['fingerprint'] or
                target.get('review_status') != 'reviewed' or
                target.get('assessment', {}).get('kind') != 'program'):
            raise ValueError('Duplicate retirement requires reviewed unchanged source and executable replacement')
        changes[qid] = {**original, 'review_status': 'retired',
                        'version': original.get('version', 1) + 1,
                        'superseded_by': replacement, 'review_note': item['reason']}
    if any(q['superseded_by'] in changes for q in changes.values()):
        raise ValueError('Replacement cannot itself be retired')
    return [changes.get(q['id'], q) for q in questions]


def synchronize(db, questions, legacy):
    conflicts, updated, seen = [], 0, set()
    for source in questions:
        q = normalize(dict(source))
        qid = q['id']
        if qid in seen:
            continue
        seen.add(qid)
        incoming = fingerprint(q)
        old = db.execute('SELECT payload FROM questions WHERE id=?', (qid,)).fetchone()
        tracked = db.execute('SELECT fingerprint FROM builtin_seeds WHERE qid=?', (qid,)).fetchone()
        if old:
            previous = json.loads(old[0])
            current = fingerprint(previous)
            if current != incoming:
                trusted = tracked[0] if tracked else legacy.get(qid)
                if current != trusted:
                    conflicts.append(qid)
                    continue
                q['version'] = max(previous.get('version', 1) + 1, q.get('version', 1))
                db.execute('INSERT INTO revisions(qid,payload,created) VALUES(?,?,?)', (qid, old[0], time.time()))
                db.execute('UPDATE questions SET payload=? WHERE id=?', (json.dumps(q, ensure_ascii=False), qid))
                updated += 1
        else:
            db.execute('INSERT INTO questions(id,payload) VALUES(?,?)', (qid, json.dumps(q, ensure_ascii=False)))
        db.execute('INSERT INTO builtin_seeds(qid,fingerprint) VALUES(?,?) ON CONFLICT(qid) DO UPDATE SET fingerprint=excluded.fingerprint', (qid, incoming))
    return {'updated': updated, 'conflicts': conflicts}
