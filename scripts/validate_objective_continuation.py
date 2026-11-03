"""Integration checks for seven reused objective questions, with no external state."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from bank import assessment, formats, schema
from bank.service import BankService
from core.database import Database
from core.question_identity import content_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'docs/objective-continuation-workitems.json').read_text(encoding='utf8'))
    rows = manifest['workitems']
    assert len(rows) == len({row['task_id'] for row in rows}) == len({row['question_id'] for row in rows}) == 7
    annotations = json.loads((ROOT / 'backend/data/knowledge-coverage-annotations.json').read_text(encoding='utf8'))['rows']
    mappings = {(row['id'], row['module']): row for row in annotations}
    results = []
    with tempfile.TemporaryDirectory(prefix='opsforge-objective-continuation-') as temporary:
        database = Database(str(Path(temporary) / 'bank.sqlite'), 'bank')
        database.migrate()

        class Harness(BankService):
            def db(self, domain):
                assert domain == 'bank'
                return database.transaction()

        service = Harness()
        service.seed()
        for row in rows:
            q = service.getq(row['question_id'])
            assert formats.classify(q) == row['format']
            assert q['review_status'] == 'reviewed' and q['type'] == 'interview'
            assert q['references'] == [row['reference']]
            assert q.get('exercise') is None and q.get('assessment') is None
            assert 'run' not in q and 'files' not in q and 'solution_files' not in q
            assert q['grading']['kind'] in ('choice', 'blanks')
            assert schema.prepare([q])[0]['question_format'] == row['format']
            assert content_key(q) == row['content_key'] == mappings[(q['id'], q['module'])]['content_key']
            if row['format'] == 'true_false':
                correct = q['grading']['accepted'][0]
                answers = [(correct, True), ('true', False), ('', False), ('["false","false"]', False), ('["false","true"]', False), ('false because', False)]
            else:
                value = {field['id']: field['accepted'][0] for field in q['grading']['fields']}
                wrong = {key: 'wrong' for key in value}
                partial = dict(value)
                partial.pop(next(iter(value)))
                extra = {**value, 'unexpected': 'value'}
                answers = [(json.dumps(value), True), (json.dumps({key: ' '+v+' ' for key, v in value.items()}), True),
                           (json.dumps(wrong), False), (json.dumps(partial), False), (json.dumps(extra), False), ('{}', False)]
            outcomes = []
            for answer, expected in answers:
                result = assessment.grade(q, answer)
                assert result is not None and result['passed'] is expected, (q['id'], answer, result)
                outcomes.append({'answer': answer, 'expected_passed': expected, 'actual_passed': result['passed']})
            results.append({'id': q['id'], 'task_id': row['task_id'], 'format': row['format'],
                            'content_key': content_key(q), 'graded_samples': outcomes})
        service.seed()
        assert service.bank_meta['upgrade'] == {'updated': 0, 'conflicts': []}
        with database.transaction() as db:
            assert db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0] == 0
            for row in rows:
                ident = row['question_id']
                original = json.loads(db.execute('SELECT payload FROM questions WHERE id=?', (ident,)).fetchone()[0])
                local = {**original, 'answer': 'LOCAL_EDITOR_CHANGE_MUST_SURVIVE:' + ident}
                db.execute('UPDATE questions SET payload=? WHERE id=?', (json.dumps(local), ident))
        service.seed()
        assert service.bank_meta['upgrade']['updated'] == 0
        assert set(service.bank_meta['upgrade']['conflicts']) == {row['question_id'] for row in rows}
        for row in rows:
            assert service.getq(row['question_id'])['answer'] == 'LOCAL_EDITOR_CHANGE_MUST_SURVIVE:' + row['question_id']
        with database.transaction() as db:
            assert db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0] == 0
    report = {'status': 'passed', 'completed_workitems': 7, 'reused_question_ids': 7,
              'new_question_ids': 0, 'graded_sample_count': sum(len(result['graded_samples']) for result in results),
              'reseed_idempotent': True, 'local_edit_preserved_with_conflict': True,
              'local_edit_protected_ids': [row['question_id'] for row in rows],
              'scope': 'Actual BankService seed/getq, SQLite migration, classifier, schema, declarative grading and local-edit protection. No practical runtime, incident or PC acceptance.',
              'sources': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                          ['backend/data/bank.json', 'backend/data/curated-questions.json',
                           'backend/data/knowledge-coverage-annotations.json', 'backend/bank/service.py',
                           'docs/objective-continuation-workitems.json', 'scripts/validate_objective_continuation.py']},
              'results': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({key: report[key] for key in ['status', 'completed_workitems', 'new_question_ids', 'graded_sample_count']}))


if __name__ == '__main__':
    main()
