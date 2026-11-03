"""Validate knowledge-only continuation via the real bank seed and classifier."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from bank.service import BankService
from bank.formats import classify
from bank.schema import prepare
from core.database import Database
from core.question_identity import content_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'docs/istio-short-continuation-workitems.json').read_text(encoding='utf8'))
    ids = [row['question_id'] for row in manifest['workitems']]
    assert len(ids) == len(set(ids)) == 10
    assert len({row['task_id'] for row in manifest['workitems']}) == 10
    annotations = json.loads((ROOT / 'backend/data/knowledge-coverage-annotations.json').read_text(encoding='utf8'))['rows']
    annotation = {row['id']: row for row in annotations}
    results = []
    with tempfile.TemporaryDirectory(prefix='opsforge-istio-knowledge-') as temporary:
        database = Database(str(Path(temporary) / 'bank.sqlite'), 'bank')
        database.migrate()

        class Harness(BankService):
            def db(self, domain):
                assert domain == 'bank'
                return database.transaction()

        service = Harness()
        service.seed()
        for item in manifest['workitems']:
            question = service.getq(item['question_id'])
            assert classify(question) == 'short_answer'
            assert question['module'] == 'istio'
            assert question['review_status'] == 'reviewed'
            assert question['type'] == 'interview'
            assert question['answer'].strip() and len(question['rubric']) >= 4
            assert question['references'] == [item['reference']]
            assert 'assessment' not in question and 'grading' not in question
            assert content_key(question) == item['content_key'] == annotation[question['id']]['content_key']
            assert annotation[question['id']]['reviewed'] is True
            assert prepare([question])[0]['question_format'] == 'short_answer'
            results.append({'id': question['id'], 'task_id': item['task_id'],
                            'classification': classify(question), 'loaded': True,
                            'content_key': content_key(question), 'knowledge_mapping_current': True})
        service.seed()
        assert service.bank_meta['upgrade'] == {'updated': 0, 'conflicts': []}
        with database.transaction() as db:
            assert db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0] == 0
            assert sum(db.execute('SELECT COUNT(*) FROM questions WHERE id=?', (ident,)).fetchone()[0] for ident in ids) == 10
    report = {'status': 'passed', 'question_count': 10, 'new_question_ids': 10,
              'completed_workitems': 10, 'reseed_idempotent': True,
              'scope': 'Real BankService.seed/getq, SQLite migrations, import schema, classifier and content-key knowledge mappings. Manual self-assessment only. No browser or runtime mesh acceptance.',
              'sources': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                          ['backend/data/curated-questions.json', 'backend/data/knowledge-coverage-annotations.json',
                           'docs/istio-short-continuation-workitems.json', 'scripts/validate_istio_short_continuation.py']},
              'results': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'status': 'passed', 'completed_workitems': 10, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
