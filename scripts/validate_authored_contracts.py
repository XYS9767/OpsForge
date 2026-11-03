"""Reproduce packaged contracts through the platform runner in disposable directories.

Local/WSL execution is for trusted authored contracts, not an untrusted-code sandbox.
It never changes the default WSL distribution/user, credentials, or source files.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'backend'))

# This transport only materializes the already trusted platform bundle. Judging
# remains inside the exact packaged assessment_runner, including feature probes.
WORKER = r'''
import json,os,pathlib,platform,secrets,subprocess,sys,tempfile,time
payload=json.load(sys.stdin)
rows=[]
for route in payload['routes']:
 with tempfile.TemporaryDirectory(prefix='opsforge-contract-') as tmp:
  root=pathlib.Path(tmp)
  for name,content in route['files'].items():
   path=root/name
   if not path.resolve().is_relative_to(root.resolve()):raise ValueError('unsafe artifact path')
   path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf8')
  token=secrets.token_hex(24);marker='__OPSF_VERDICT_'+token+'__'
  started=time.monotonic()
  env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
  # The nested platform runner bounds and kills the checker process group.
  proc=subprocess.Popen([sys.executable,'-B','checks/_opsforge_runner.py',token],cwd=root,
   stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,
   start_new_session=os.name=='posix')
  outer_timeout=False
  try:raw=proc.communicate(timeout=payload['timeout']+90)[0]
  except subprocess.TimeoutExpired:
   outer_timeout=True
   if os.name=='posix':
    import signal
    os.killpg(proc.pid,signal.SIGKILL)
   else:proc.kill()
   raw=proc.communicate(timeout=10)[0]
  output=raw.decode('utf8',errors='replace')
  verdicts=[line[len(marker):] for line in output.splitlines() if line.startswith(marker)]
  verdict=None
  if len(verdicts)==1:
   try:verdict=json.loads(verdicts[0])
   except ValueError:pass
  rows.append({'route':route['name'],'outer_exit_code':proc.returncode,
   'outer_timeout':outer_timeout,'verdict_count':len(verdicts),'verdict':verdict,
   'seconds':round(time.monotonic()-started,3),'transport_output':output[-8000:]})
print(json.dumps({'environment':{'platform':platform.platform(),'python':sys.version,
 'uid':os.getuid() if hasattr(os,'getuid') else None},'routes':rows},ensure_ascii=True))
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def routes_for(question, bundle):
    from core.files import validate_files
    starter = dict(question.get('files', {}))
    solutions = question.get('solution_files')
    negatives = question.get('negative_files')
    if not solutions or not negatives:
        raise ValueError('Four-route verification requires solution_files and negative_files')
    for files in (starter, solutions, negatives):
        validate_files(files)
        if set(files) & set(bundle):
            raise ValueError('Learner artifacts overlap trusted bundle')
    reference = {**starter, **solutions, **bundle}
    early = dict(reference)
    if question['assessment']['command'] == 'python3 checks/check.py':
        early['checks/check.py'] = 'import sys\nsys.exit(0)\n'
    else:
        tests = [(n, c) for n, c in bundle.items() if n.endswith('_test.go')]
        if not tests or any(re.search(r'^func\s+TestMain\s*\(', c, re.M) for _, c in tests):
            raise ValueError('Go early-exit injection needs tests without existing TestMain')
        name, content = tests[0]
        package = re.search(r'^package\s+(\w+)', content, re.M)
        if not package:
            raise ValueError('Cannot identify Go test package')
        directory = name.rpartition('/')[0]
        path = (directory + '/' if directory else '') + 'opsforge_early_exit_test.go'
        if path in early:
            raise ValueError('Early-exit fixture filename collision')
        early[path] = 'package ' + package[1] + '\nimport("os";"testing")\nfunc TestMain(m *testing.M){os.Exit(0)}\n'
    return [
        {'name': 'reference', 'files': reference},
        {'name': 'starter', 'files': {**starter, **bundle}},
        {'name': 'negative', 'files': {**starter, **negatives, **bundle}},
        {'name': 'runner_early_exit', 'files': early},
    ]


def assess(row):
    verdict = row.get('verdict')
    if (row.get('outer_timeout') or row.get('verdict_count') != 1
            or not isinstance(verdict, dict) or verdict.get('error')
            or verdict.get('interrupted') is not False):
        return False, 'environment_or_runner_error'
    if row['route'] == 'reference':
        ok = verdict.get('passed') is True and verdict.get('completed') is True and verdict.get('exit_code') == 0
        return ok, 'reference_passed' if ok else 'reference_failed'
    if row['route'] == 'runner_early_exit':
        ok = verdict.get('passed') is False and verdict.get('completed') is False and verdict.get('exit_code') == 0
        return ok, 'early_exit_rejected' if ok else 'early_exit_not_rejected'
    output = verdict.get('output', '').replace('\r\n', '\n')
    # Do not credit imports, missing tools, syntax errors, signals, or timeouts as
    # semantic rejection. A later reference failure also disqualifies the question.
    failure = bool(re.search(r'(?m)^(?:AssertionError|NotImplementedError)(?::|$)', output))
    if not failure and 'go_tests' in row:
        failure = '"Action":"fail"' in output and '--- FAIL:' in output
    ok = (verdict.get('passed') is False and verdict.get('completed') is False
          and isinstance(verdict.get('exit_code'), int) and verdict['exit_code'] > 0 and failure)
    return ok, 'semantic_rejection' if ok else 'unverified_rejection'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', required=True)
    parser.add_argument('--id', action='append', default=[])
    parser.add_argument('--output', required=True)
    parser.add_argument('--wsl', help='Explicit existing distribution; does not change defaults')
    parser.add_argument('--wsl-user', default='student')
    args = parser.parse_args()
    from bank import hands_on
    from bank.seeding import fingerprint
    trusted = hands_on.catalog()
    selected, sources = {}, []
    for name in args.source:
        path = Path(name).resolve()
        if path.parent != (ROOT / 'backend/data').resolve() or path.name not in hands_on.SOURCES:
            parser.error('--source must be a registered packaged backend/data source')
        data = path.read_bytes()
        sources.append({'path': str(path.relative_to(ROOT)), 'sha256': sha(data)})
        for question in json.loads(data.decode('utf8')):
            if args.id and question['id'] not in args.id:
                continue
            if question['id'] not in trusted or fingerprint(question) != fingerprint(trusted[question['id']]):
                parser.error('Selected question is not the current trusted contract: ' + question['id'])
            selected[question['id']] = question
    if not selected or set(args.id) - set(selected):
        parser.error('No matching questions, or requested IDs absent from selected sources')
    report = {'schema': 1, 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'scope': 'authored_contract_four_routes; not PC acceptance, deployment, or semantic deduplication',
              'sources': sources, 'runner_sha256': sha((ROOT / 'backend/labs/assessment_runner.py').read_bytes()),
              'validator_sha256': sha(Path(__file__).read_bytes()),
              'execution': {'mode': 'wsl' if args.wsl else 'local', 'distribution': args.wsl,
                            'user': args.wsl_user if args.wsl else None}, 'questions': []}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        parser.error('--output must be new; existing evidence is never overwritten')
    for qid, question in selected.items():
        item = {'id': qid, 'contract_fingerprint': fingerprint(question)}
        try:
            assessment = hands_on.program_contract(question)
            bundle = hands_on.execution_bundle(question, assessment)
            routes = routes_for(question, bundle)
            payload = json.dumps({'routes': routes, 'timeout': assessment.get('timeout', 30)})
            command = (['wsl.exe', '--distribution', args.wsl, '--user', args.wsl_user, '--exec', 'python3', '-B', '-c', WORKER]
                       if args.wsl else [sys.executable, '-B', '-c', WORKER])
            started = time.monotonic()
            proc = subprocess.run(command, input=payload.encode('utf8'), capture_output=True,
                                  timeout=4 * (assessment.get('timeout', 30) + 100) + 30)
            if proc.returncode:
                raise RuntimeError('Transport failed: ' + proc.stderr.decode('utf8', errors='replace')[-2000:])
            result = json.loads(proc.stdout.decode('utf8'))
            item.update(result)
            item['seconds'] = round(time.monotonic()-started, 3)
            for row in item['routes']:
                if assessment['command'].startswith('go test'):
                    row['go_tests'] = True
                row['correct'], row['classification'] = assess(row)
            item['verified'] = len(item['routes']) == 4 and all(r['correct'] for r in item['routes'])
        except Exception as error:
            item.update(verified=False, error=type(error).__name__ + ': ' + str(error))
        report['questions'].append(item)
        report['question_count'] = len(selected)
        report['verified_question_count'] = sum(q['verified'] for q in report['questions'])
        report['run_count'] = sum(len(q.get('routes', [])) for q in report['questions'])
        report['correct_count'] = sum(r['correct'] for q in report['questions'] for r in q.get('routes', []))
        report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(qid + ': ' + ('verified' if item['verified'] else 'NOT VERIFIED'), flush=True)
    return 0 if report['verified_question_count'] == len(selected) else 1


if __name__ == '__main__':
    raise SystemExit(main())
