"""Verify extra authored artifact mutants with the current trusted platform bundle."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import sys

import validate_authored_contracts as validator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--mutants', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--wsl')
    parser.add_argument('--wsl-user')
    args = parser.parse_args()
    if args.wsl_user and not args.wsl:
        parser.error('--wsl-user requires --wsl')
    output = Path(args.output)
    if output.exists():
        parser.error('--output must be new; existing evidence is never overwritten')
    from bank import hands_on
    from core.files import validate_files
    source = Path(args.source)
    mutants_path = Path(args.mutants)
    if source.resolve().parent != (validator.ROOT / 'backend/data').resolve() or source.name not in hands_on.SOURCES:
        parser.error('--source must be a current registered packaged backend/data source')
    if args.wsl and args.wsl_user is None:
        args.wsl_user = 'student'
    questions = {q['id']: q for q in json.loads(source.read_text(encoding='utf-8'))}
    mutants = json.loads(mutants_path.read_text(encoding='utf-8'))
    if not isinstance(mutants, dict) or not mutants:
        parser.error('mutants must map question IDs to nonempty named artifact maps')
    report = {
        'schema': 1,
        'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'extra artifact boundary mutants; not additional questions',
        'source_sha256': validator.sha(source.read_bytes()),
        'mutants_sha256': validator.sha(mutants_path.read_bytes()),
        'runner_sha256': validator.sha((validator.ROOT / 'backend/labs/assessment_runner.py').read_bytes()),
        'validator_sha256': validator.sha(Path(__file__).read_bytes()),
        'execution': {'wsl': args.wsl, 'user': args.wsl_user},
        'questions': [],
    }
    for question_id, cases in mutants.items():
        q = questions[question_id]
        current = hands_on.catalog().get(question_id)
        if current is None or hands_on.fingerprint(q) != hands_on.fingerprint(current):
            raise ValueError('Source is not the registered current trusted contract: ' + question_id)
        assessment = hands_on.program_contract(q)
        bundle = hands_on.execution_bundle(q, assessment)
        routes = [validator.routes_for(q, bundle)[0]]
        if not isinstance(cases, dict) or not cases:
            raise ValueError('Every question needs named artifact mutants')
        for name, artifacts in cases.items():
            if name in ('reference', 'runner_early_exit'):
                raise ValueError('Reserved route name')
            validate_files(artifacts)
            allowed = set(q['exercise']['deliverables']) | set(q.get('files', {}))
            if not artifacts or set(artifacts) - allowed:
                raise ValueError('Mutants may only replace declared learner artifacts')
            if set(artifacts) & set(bundle):
                raise ValueError('Mutants cannot replace trusted tests or platform runner')
            route_files = {**q['files'], **q['solution_files'], **artifacts, **bundle}
            validate_files(route_files)
            routes.append({'name': name, 'files': route_files})
        payload = json.dumps({'routes': routes, 'timeout': assessment.get('timeout', 30)}).encode('utf-8')
        command = ['wsl', '-d', args.wsl] if args.wsl else []
        if args.wsl_user:
            command += ['--user', args.wsl_user]
        command += ['--', 'python3', '-B', '-c', validator.WORKER] if args.wsl else [sys.executable, '-B', '-c', validator.WORKER]
        process = subprocess.run(command, input=payload, capture_output=True,
                                 timeout=(assessment.get('timeout', 30) + 100) * len(routes))
        if process.returncode:
            raise RuntimeError('Transport failed: ' + process.stderr.decode('utf-8', errors='replace'))
        item = json.loads(process.stdout)
        item['id'] = question_id
        item['contract_fingerprint'] = hands_on.fingerprint(q)
        for row in item['routes']:
            if assessment['command'].startswith('go test'):
                row['go_tests'] = True
            row['correct'], row['classification'] = validator.assess(row)
        item['verified'] = all(row['correct'] for row in item['routes'])
        report['questions'].append(item)
        print(question_id + ': ' + ('verified' if item['verified'] else 'NOT VERIFIED'))
    report['mutant_count'] = sum(len(q['routes']) - 1 for q in report['questions'])
    report['rejected_mutant_count'] = sum(r['correct'] for q in report['questions'] for r in q['routes'] if r['route'] != 'reference')
    report['verified_question_count'] = sum(q['verified'] for q in report['questions'])
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if all(q['verified'] for q in report['questions']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
