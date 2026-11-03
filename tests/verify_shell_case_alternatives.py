"""Run known-correct Shell alternatives through the current trusted runner."""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
import validate_authored_contracts as validator
from bank import hands_on
from core.files import validate_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wsl', required=True)
    parser.add_argument('--wsl-user', default='student')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error('--output must be new')
    source = ROOT / 'backend/data/hands-on-shell-converted.json'
    fixture = ROOT / 'tests/fixtures/shell-continuation-valid-alternatives.json'
    alternatives = json.loads(fixture.read_text(encoding='utf-8'))
    report = {
        'schema': 1, 'scope': 'correct alternatives must pass the actual trusted contract',
        'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_sha256': validator.sha(source.read_bytes()),
        'fixture_sha256': validator.sha(fixture.read_bytes()),
        'runner_sha256': validator.sha((ROOT / 'backend/labs/assessment_runner.py').read_bytes()),
        'validator_sha256': validator.sha(Path(__file__).read_bytes()),
        'checks': [],
    }
    for qid, cases in alternatives.items():
        q = hands_on.catalog()[qid]
        bundle = hands_on.execution_bundle(q, hands_on.program_contract(q))
        for name, artifacts in cases.items():
            validate_files(artifacts)
            assert set(artifacts) <= set(q['exercise']['deliverables'])
            files = {**q['files'], **q['solution_files'], **artifacts, **bundle}
            validate_files(files)
            payload = json.dumps({'routes': [{'name': 'reference', 'files': files}],
                                  'timeout': q['assessment']['timeout']}).encode('utf-8')
            command = ['wsl', '-d', args.wsl, '--user', args.wsl_user,
                       '--', 'python3', '-B', '-c', validator.WORKER]
            process = subprocess.run(command, input=payload, capture_output=True, timeout=180)
            assert process.returncode == 0, process.stderr.decode('utf-8', errors='replace')
            result = json.loads(process.stdout)
            row = result['routes'][0]
            row['correct'], row['classification'] = validator.assess(row)
            report['checks'].append({'id': qid, 'alternative': name,
                                     'environment': result['environment'], 'result': row})
    report['check_count'] = len(report['checks'])
    report['passed_count'] = sum(item['result']['correct'] for item in report['checks'])
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(str(report['passed_count']) + '/' + str(report['check_count']) + ' correct alternatives passed')
    return 0 if report['passed_count'] == report['check_count'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
