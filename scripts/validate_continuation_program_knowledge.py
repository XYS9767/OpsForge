"""Read-only validation of the finite continuation knowledge mapping increment.

Uses an isolated SQLite bank, never edits question sources or shared annotations.
This is metadata validation; native runtime evidence remains separate.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from bank import hands_on
from bank.service import BankService
from core.database import Database
from core.question_identity import content_key

EXTRA = {
    'src-df2e2db8973dcd65', 'src-fefab13df2e2fea5',
    'src-72fdd0fb36c61d4a', 'src-9a7211d37ecc2e2c',
    'src-8b1fe28e7a1ba32d', 'src-85f4dfa373bdec37',
    'src-e6ec668c4e4674ff', 'src-e388c334baa86bae',
    'curated-advanced-shell-014', 'curated-parallel-nginx-086',
    'extra-nginx-02', 'curated-istio-continuation-project-001',
    'curated-istio-continuation-project-002', 'curated-parallel-go-109',
}
GAPS = {'curated-parallel-go-050', 'curated-parallel-go-055'}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('--output must name a new report')
    increment_path = ROOT / 'docs/continuation-program-knowledge-increment.json'
    increment = read_json(increment_path)
    # This increment describes one frozen cohort; later continuation claims
    # must not silently expand it or make the original 48-row proof unusable.
    claims = [row for row in read_json(ROOT / 'evidence/continuation/checkpoint-001/progress.json')['completed']
              if row['format'] in ('code', 'practice', 'case', 'project')]
    assert len(claims) == 34
    expected = {row['question_id'] for row in claims} | EXTRA
    assert len(expected) == 48
    rows = increment['rows']
    assert len(rows) == 48 and len({row['id'] for row in rows}) == 48
    assert {row['id'] for row in rows} == expected
    assert increment['full_coverage_review_complete'] is False
    assert increment['net_new_workitems'] == 0
    policy = read_json(ROOT / 'backend/data/curriculum-coverage-policy.json')
    curated = read_json(ROOT / 'backend/data/curated-questions.json')
    nginx_topics = {row['topic'] for row in curated if row.get('module') == 'nginx'}
    # Catalog is inspected as text: do not execute an alternative taxonomy.
    catalog = (ROOT / 'backend/bank/catalog.py').read_text(encoding='utf8')
    catalog_line = next(line for line in catalog.splitlines() if '("nginx","Nginx"' in line)
    catalog_knowledge = set(re.findall(r'"([^"]*)"', catalog_line)[3].split('；'))
    sources = {ROOT / row['source'] for row in rows}
    shared = ROOT / 'backend/data/knowledge-coverage-annotations.json'
    protected = sources | {shared}
    before = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in protected}
    per_question = []
    with tempfile.TemporaryDirectory(prefix='opsforge-program-knowledge-') as temporary:
        database = Database(str(Path(temporary) / 'bank.sqlite'), 'bank')
        database.migrate()

        class Harness(BankService):
            def db(self, domain):
                assert domain == 'bank'
                return database.transaction()

        service = Harness()
        service.seed()
        first_keys = {}
        for row in rows:
            ident = row['id']
            raw = next(q for q in read_json(ROOT / row['source']) if q['id'] == ident)
            claim = next((claim for claim in claims if claim['question_id'] == ident), None)
            task_id = claim['task_id'] if claim else raw.get('workitem_id', 'question:' + ident)
            assert row['original_task_id'] == task_id
            assert row['semantic_review_performed'] is True
            assert row['eligible_for_coverage_merge'] is row['reviewed']
            question = service.getq(ident)
            key = content_key(question)
            first_keys[ident] = key
            assert key == row['content_key'], ('stale content_key', ident)
            assert question['module'] == row['module']
            assert hands_on.program_contract(question) is not None, ident
            assert row['full_coverage_review_complete'] is False
            assert len(row['reason']) >= 35 and len(row['scope']) >= 20
            assert len(row['knowledge_points']) == len(set(row['knowledge_points']))
            if ident in GAPS:
                assert row['reviewed'] is False and row['knowledge_points'] == []
                assert row['mapping_gap'] and row['existing_taxonomy_reference'] == [question['topic']]
                assert row['taxonomy_source']['kind'] == 'reference_only_not_blueprint_coverage'
            else:
                assert row['reviewed'] is True and 1 <= len(row['knowledge_points']) <= 3
                if row['module'] == 'nginx':
                    assert row['taxonomy_source']['kind'] == 'existing_taxonomy_fallback'
                    assert set(row['knowledge_points']) <= nginx_topics | catalog_knowledge
                    assert row['taxonomy_source']['policy'] == 'other_module_blueprints'
                else:
                    assert set(row['knowledge_points']) <= set(policy['explicit_module_blueprints'][row['module']])
            artifacts = row['reviewed_artifacts']
            tests = question['assessment']['test_files']
            assert artifacts['deliverables'] == question['exercise']['deliverables']
            assert artifacts['assertion_files'] == list(tests) and tests
            assert artifacts['assertion_files_sha256'] == {p: digest(c.encode()) for p, c in tests.items()}
            assert artifacts['body_sha256'] == digest(question['body'].encode())
            per_question.append({'id': ident, 'content_key': key, 'module': row['module'],
                                 'reviewed_coverage': row['reviewed'], 'knowledge_points': row['knowledge_points'],
                                 'mapping_gap': row.get('mapping_gap'), 'program_contract': True})
        partial = next(row for row in rows if row['id'] == 'curated-dev-python-091')
        assert partial['mapping_gap']
        service.seed()
        assert service.bank_meta['upgrade'] == {'updated': 0, 'conflicts': []}
        assert {ident: content_key(service.getq(ident)) for ident in expected} == first_keys
    after = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in protected}
    assert after == before, 'question source or shared annotation modified during validation'
    report = {
        'status': 'passed', 'scope': 'metadata mapping only; native tests are separate evidence',
        'questions_reviewed': 48, 'mergeable_reviewed_rows': 46, 'unmapped_rows': sorted(GAPS),
        'partially_mapped_rows_with_main_mechanism_gap': ['curated-dev-python-091'],
        'module_counts': dict(Counter(row['module'] for row in rows)),
        'actual_bank_seed_getq_content_keys': True, 'program_contracts': True,
        'reseed_idempotent': True, 'source_and_shared_annotations_unchanged': True,
        'full_coverage_review_complete': False, 'net_new_workitems': 0,
        'increment_sha256': digest(increment_path.read_bytes()), 'protected_sha256': before,
        'taxonomy_verified': {'explicit_policy_sha256': digest((ROOT / 'backend/data/curriculum-coverage-policy.json').read_bytes()),
                              'nginx_fallback': 'existing curated topics or catalog knowledge; no invented points'},
        'rows': per_question,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('rows', 'protected_sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
