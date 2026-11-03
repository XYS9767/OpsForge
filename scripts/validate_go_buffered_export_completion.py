"""Exercise added TestMain files through the current real platform bundle.

The public mutant validator only replaces declared artifacts. This focused
integration check also adds a non-reserved learner _test.go, as Labs permits.
"""
import argparse
import base64
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import validate_authored_contracts as validator

ROOT = validator.ROOT
sys.path.insert(0, str(ROOT / 'backend'))
from bank import hands_on
from core.files import validate_files
from core.question_identity import content_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--wsl', required=True)
    parser.add_argument('--wsl-user', default='student')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('--output must be new')
    ident = 'curated-parallel-go-109'
    source = ROOT / 'backend/data/hands-on-development-existing-conversions.json'
    source_before = source.read_bytes()
    question = next(q for q in json.loads(source_before) if q['id'] == ident)
    assert hands_on.fingerprint(question) == hands_on.fingerprint(hands_on.catalog()[ident])
    assessment = hands_on.program_contract(question)
    bundle = hands_on.execution_bundle(question, assessment)
    base = {**question['files'], **question['solution_files'], **bundle}
    extra_path = 'submission_testmain_test.go'
    assert extra_path not in base
    reference = question['solution_files']['task.go']
    assert reference.count('import("bufio";"errors";"io")') == 1
    broken = reference.replace('import("bufio";"errors";"io")', 'import("bufio";"errors";"io";"os")')
    marker = 'func Export(dst io.WriteCloser, records []string)(err error){'
    assert broken.count(marker) == 1
    broken = broken.replace(marker, marker + '\n    if _,ok:=dst.(*os.File);!ok{_ = dst.Close();return nil}')
    required = ['TestExportExactBytes', 'TestExportErrorsRemainDiscoverable',
                'TestNativeFullFailsDuringActualFlushAndStillCloses', 'TestGoStringBytesRemainOpaqueAtFunctionBoundary']
    fake_lines = []
    for name in required:
        for action in ('run', 'pass'):
            # Valid JSON emitted by student Go code must stay Action:output in
            # the authoritative go test event stream.
            fake_lines.append('fmt.Println(`' + json.dumps({'Action':action,'Package':'practice','Test':name}) + '`)')
    legal = 'package practice\nimport("os";"testing")\nfunc TestMain(m *testing.M){os.Exit(m.Run())}\n'
    skip = 'package practice\nimport("os";"testing")\nfunc TestMain(m *testing.M){os.Exit(0)}\n'
    fake = 'package practice\nimport("fmt";"os";"testing")\nfunc TestMain(m *testing.M){\n' + '\n'.join(fake_lines) + '\nos.Exit(0)}\n'
    routes = [
        {'name':'reference','files':base},
        {'name':'legitimate_testmain_runs_all','files':{**base, extra_path:legal}},
        {'name':'bad_api_testmain_skips_all','files':{**base,'task.go':broken,extra_path:skip}},
        {'name':'bad_api_testmain_prints_fake_json','files':{**base,'task.go':broken,extra_path:fake}},
        {'name':'compilation_failure_not_semantic_credit','files':{**base,'task.go':'package practice\nfunc Export(\n'}},
    ]
    for row in routes:
        validate_files(row['files'])
        assert all(row['files'][path] == value for path, value in bundle.items()), 'trusted bundle overridden'
    payload = json.dumps({'routes':routes,'timeout':assessment['timeout']}).encode('utf8')
    worker = 'import base64;exec(base64.b64decode(' + repr(base64.b64encode(validator.WORKER.encode()).decode()) + '))'
    result = subprocess.run(['wsl.exe','--distribution',args.wsl,'--user',args.wsl_user,'--exec','python3','-B','-c',worker],
                            input=payload,capture_output=True,timeout=len(routes)*(assessment['timeout']+100))
    if result.returncode:
        raise RuntimeError('transport failed: ' + result.stderr.decode('utf8',errors='replace')[-2500:])
    report = json.loads(result.stdout)
    for row in report['routes']:
        verdict = row['verdict'] or {}
        if row['route'] in ('reference','legitimate_testmain_runs_all'):
            row['correct'] = (row['verdict_count'] == 1 and not row['outer_timeout'] and
                              verdict.get('passed') is True and verdict.get('completed') is True and
                              verdict.get('exit_code') == 0 and 'GO_TRUSTED_TESTS_COMPLETED:' in verdict.get('output',''))
            row['classification'] = 'all_trusted_tests_completed' if row['correct'] else 'reference_failed'
        elif row['route'] == 'compilation_failure_not_semantic_credit':
            semantic, _ = validator.assess(dict(row, route='negative'))
            row['correct'] = (not semantic and verdict.get('passed') is False and verdict.get('completed') is False and
                              'RuntimeError: Go compilation/environment failed:' in verdict.get('output',''))
            row['classification'] = 'compilation_failure_not_credited' if row['correct'] else 'incorrect_error_classification'
        else:
            semantic, classification = validator.assess(dict(row, route='negative'))
            row['correct'] = semantic and 'AssertionError: trusted Go tests did not complete:' in verdict.get('output','')
            row['classification'] = classification
    assert source.read_bytes() == source_before, 'validation modified question source'
    report.update({'status':'passed' if all(row['correct'] for row in report['routes']) else 'failed',
                   'id':ident,'content_key':content_key(question),'source_sha256':hashlib.sha256(source_before).hexdigest(),
                   'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'runner_sha256':hashlib.sha256((ROOT/'backend/labs/assessment_runner.py').read_bytes()).hexdigest(),
                   'execution':{'wsl':args.wsl,'user':args.wsl_user},'required_trusted_tests':required,
                   'scope':'real execution_bundle and WORKER; added non-reserved TestMain submission files; no new workitems',
                   'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':report['status'],'routes':[(r['route'],r['correct'],r['classification']) for r in report['routes']]},ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
