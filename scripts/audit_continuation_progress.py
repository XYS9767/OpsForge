"""Reconcile uniquely claimed backlog items with current bank and execution proof.

The original 4444 completed items are an inherited declaration: the source ZIP
did not contain checkpoint434. This audit only independently proves the delta.
It never grants completion credit for restoring tools or rerunning old checks.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'backend'))
from bank import hands_on
from bank.formats import classify
from bank.taxonomy import placement
from bank.seeding import fingerprint
from bank.service import BankService
from bank.schema import prepare
from core.database import Database
from core.question_identity import content_key
from validate_authored_contracts import assess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounded(name):
    path = (ROOT / name.replace('\\', '/')).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError('Evidence must be packaged beneath the project root')
    return path


def read(name):
    return json.loads(bounded(name).read_text(encoding='utf8'))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def source_proof(report):
    sources = report.get('sources')
    require(bool(sources), 'Empty source provenance')
    if isinstance(sources, list):
        for source in sources:
            require(sha(bounded(source['path'])) == source['sha256'], 'Execution source SHA mismatch: ' + source['path'])
    elif isinstance(sources, dict):
        for name, digest in sources.items():
            require(sha(bounded(name)) == digest, 'Knowledge source SHA mismatch: ' + name)
    else:
        raise ValueError('Missing source provenance')


def execution_proof(report, question, source, mutants=False, fixture=None):
    if mutants:
        require(fixture is not None and report.get('mutants_sha256') == sha(bounded(fixture)), 'Mutant fixture SHA mismatch')
        require(report.get('source_sha256') == sha(bounded(source)), 'Mutant source SHA mismatch')
        require(report.get('validator_sha256') == sha(ROOT / 'scripts/validate_contract_mutants.py'), 'Mutant validator SHA mismatch')
    else:
        source_proof(report)
        require(any(item['path'].replace('\\', '/') == source for item in report['sources']), 'Question source absent from four-route proof: ' + question['id'])
        require(report.get('validator_sha256') == sha(ROOT / 'scripts/validate_authored_contracts.py'), 'Four-route validator SHA mismatch')
    require(report.get('runner_sha256') == sha(ROOT / 'backend/labs/assessment_runner.py'), 'Runner SHA mismatch')
    rows = [q for q in report.get('questions', []) if q.get('id') == question['id']]
    require(len(rows) == 1, 'Execution question missing or duplicated')
    item = rows[0]
    require(item.get('contract_fingerprint') == fingerprint(question), 'Contract fingerprint mismatch')
    require(item.get('verified') is True, 'Unverified execution question')
    routes = item.get('routes', [])
    names = [row['route'] for row in routes]
    require(len(names) == len(set(names)), 'Duplicate execution route')
    if mutants:
        require('reference' in names and len(names) >= 3, 'Need reference plus independent boundary faults')
        cases = read(fixture).get(question['id'], {})
        require(set(names) == {'reference', *cases}, 'Execution routes differ from packaged fault cases')
        artifacts = {**question.get('files', {}), **question['solution_files']}
        original = json.dumps(artifacts, sort_keys=True, ensure_ascii=False)
        typical_negative = json.dumps({**question.get('files', {}), **question['negative_files']}, sort_keys=True, ensure_ascii=False)
        variants = [json.dumps({**artifacts, **files}, sort_keys=True, ensure_ascii=False) for files in cases.values()]
        require(len(set(variants)) == len(variants) and original not in variants and typical_negative not in variants,
                'Boundary cases must differ from each other, reference and four-route negative: ' + question['id'])
    else:
        require(set(names) == {'reference', 'starter', 'negative', 'runner_early_exit'}, 'Incomplete four-route proof')
    require(all(assess(row)[0] for row in routes), 'Route verdict does not meet semantic/completion criteria')
    require(item.get('environment', {}).get('uid') == 1000, 'Native checks must run as the explicit isolated student user')
    return len(routes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='docs/continuation-baseline.json')
    parser.add_argument('--claims', default='docs/continuation-claims.json')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    require(not output.exists(), 'Refusing to replace an existing checkpoint')
    baseline, manifest = read(args.baseline), read(args.claims)
    inherited = baseline['inherited_declared_completion']
    require((inherited['completed'], inherited['total'], inherited['remaining']) == (4444, 5786, 1342), 'Inherited declaration was changed')
    pending = {item['task_id']: item for item in baseline['workitems']}
    require(len(pending) == len(baseline['workitems']) == 1342, 'Original backlog uniqueness/count mismatch')
    claims = manifest['claims']
    require(len({item['task_id'] for item in claims}) == len(claims), 'A backlog item can only be claimed once')
    question_claims = [item for item in claims if item.get('question_id') is not None]
    require(len({item['question_id'] for item in question_claims}) == len(question_claims), 'A question cannot consume multiple backlog slots')
    original_ids = set(baseline['original_packaged_question_ids'])
    result = []
    source_by_id = {}
    for name in hands_on.SOURCES:
        for question in json.loads((ROOT / 'backend/data' / name).read_text(encoding='utf8')):
            source_by_id[question['id']] = 'backend/data/' + name
    with tempfile.TemporaryDirectory(prefix='opsforge-progress-audit-') as temporary:
        database = Database(str(Path(temporary) / 'bank.sqlite'), 'bank')
        database.migrate()

        class Harness(BankService):
            def db(self, domain):
                require(domain == 'bank', 'Unexpected database domain')
                return database.transaction()

        service = Harness()
        service.seed()
        for claim in claims:
            task = pending.get(claim['task_id'])
            require(task is not None, 'Claim not present in original backlog: ' + claim['task_id'])
            if task['format'] == 'acceptance':
                require(task['task_id'] == 'module-review:python' and task['module'] == 'global', 'Unsupported acceptance claim')
                require(claim.get('question_id') is None, 'Module acceptance cannot consume a question ID')
                require(bool(claim.get('change_reason', '').strip()), 'Module acceptance review reason missing')
                paths = claim.get('evidence', [])
                require(isinstance(paths, list) and len(paths) == 1, 'Module acceptance needs one complete evidence manifest')
                from validate_python_module_review import verify_manifest
                reviewed = verify_manifest(paths[0], service)
                result.append({'task_id': task['task_id'], 'question_id': None, 'module': task['module'],
                               'format': 'acceptance', 'new_question_id': None, 'checked_routes': 0,
                               'module_review': reviewed, 'evidence': {paths[0]: sha(bounded(paths[0]))}})
                continue
            qid = claim['question_id']
            if task['task_id'].startswith('question:'):
                require(task['task_id'] == 'question:' + qid, 'Existing backlog item must retain its ID')
            question = service.getq(qid)
            require(placement(question)['primary_module'] == task['module'], 'Target primary module not satisfied: ' + qid)
            require(classify(question) == task['format'], 'Target teaching format not satisfied: ' + qid)
            imported = prepare([question])[0]
            require(classify(imported) == task['format'], 'Import boundary loses the target format: ' + qid)
            public = service.public(question)
            require(public.get('question_format') == task['format'], 'Public API loses the target format: ' + qid)
            require(not {'answer', 'assessment', 'solution_files', 'negative_files', 'grading'} & public.keys(),
                    'Public API leaks private assessment material: ' + qid)
            require(question.get('review_status') == 'reviewed' and bool(question.get('answer', '').strip()), 'Question not published/reviewed')
            require(bool(claim.get('change_reason', '').strip()), 'Claim must explain the reviewed substantive change')
            old = baseline['original_seed_snapshot'].get(qid)
            if old is not None:
                # A changed hash is a necessary consistency check, never a
                # substitute for the separately recorded semantic review.
                require(content_key(question) != old['content_key'], 'Existing content did not change for an adaptation claim')
                if task['task_id'].startswith('planned-new:'):
                    require(old['format'] != task['format'], 'An already-qualified old format cannot consume a planning slot')
            checked_routes = 0
            paths = claim['evidence']
            require(isinstance(paths, list) and len(paths) >= 1, 'Claim lacks proof')
            reports = [read(path) for path in paths]
            if task['format'] in ('code', 'practice', 'case', 'project'):
                require(public.get('automatic_grading') is True, 'Public API cannot execute the claimed program contract: ' + qid)
                if task['task_id'].startswith('planned-new:'):
                    require(question.get('workitem_id') == task['task_id'], 'Program planning slot lacks explicit question binding')
                require(len(reports) == 2, 'Need both four-route and boundary-fault proof')
                current = hands_on.catalog().get(qid)
                require(current is not None and fingerprint(question) == fingerprint(current), 'Seeded task differs from executable contract')
                checked_routes += execution_proof(reports[0], current, source_by_id[qid])
                checked_routes += execution_proof(reports[1], current, source_by_id[qid], mutants=True, fixture=claim.get('mutants'))
            else:
                require(len(reports) == 1, 'Knowledge proof must be a unique integration report')
                report = reports[0]
                source_proof(report)
                require(report.get('status') == 'passed' and report.get('reseed_idempotent') is True, 'Knowledge integration did not pass')
                matches = [item for item in report.get('results', []) if item.get('id') == qid and item.get('task_id') == task['task_id']]
                require(len(matches) == 1 and matches[0]['content_key'] == content_key(question), 'Knowledge task/content-key mismatch')
                samples = matches[0].get('graded_samples', [])
                if task['format'] != 'short_answer':
                    from bank.assessment import grade
                    require(len(samples) >= 6 and any(s['expected_passed'] for s in samples) and any(not s['expected_passed'] for s in samples), 'Objective item lacks positive/negative samples')
                    require(all(grade(question, sample['answer'])['passed'] == sample['expected_passed'] for sample in samples), 'Objective sample grade mismatch')
            result.append({'task_id': task['task_id'], 'question_id': qid, 'module': task['module'],
                           'format': task['format'], 'content_key': content_key(question),
                           'new_question_id': qid not in original_ids, 'checked_routes': checked_routes,
                           'evidence': {name: sha(bounded(name)) for name in paths}})
        service.seed()
        require(service.bank_meta['upgrade'] == {'updated': 0, 'conflicts': []}, 'Final repeated seed is not idempotent')
    complete = {item['task_id'] for item in result}
    inherited = baseline['inherited_declared_completion']
    remaining = [item for item in baseline['workitems'] if item['task_id'] not in complete]
    projected = inherited['completed'] + len(result)
    report = {'status': 'passed', 'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'auditor_sha256': sha(Path(__file__).resolve()),
              'import_schema_sha256': sha(ROOT / 'backend/bank/schema.py'),
              'bank_service_sha256': sha(ROOT / 'backend/bank/service.py'),
              'baseline_sha256': sha(bounded(args.baseline)), 'claims_sha256': sha(bounded(args.claims)),
              'inherited_completed_count': inherited['completed'], 'inherited_baseline_independently_reproduced': False,
              'verified_delta': len(result), 'new_question_ids': sum(item['new_question_id'] is True for item in result),
              'reused_question_ids': sum(item['new_question_id'] is False for item in result),
              'acceptance_items': sum(item['format'] == 'acceptance' for item in result),
              'remaining_count': len(remaining), 'conditional_total_completed': projected,
              'conditional_percent': round(projected/inherited['total']*100, 1),
              'scope': 'Independent delta only. Original checkpoint434 was absent. Tools, repeated routes, module reviews, deployment and PC acceptance receive no implicit credit.',
              'completed': result, 'remaining': remaining}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({key: report[key] for key in ('status', 'verified_delta', 'new_question_ids', 'remaining_count', 'conditional_percent')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
