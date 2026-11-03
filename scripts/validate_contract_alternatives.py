"""Run declared valid learner alternatives against the unchanged trusted runner."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import sys
import validate_authored_contracts as validator


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True);parser.add_argument('--valid',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--wsl');parser.add_argument('--wsl-user');args=parser.parse_args()
    if args.wsl_user and not args.wsl:parser.error('--wsl-user requires --wsl')
    output=Path(args.output)
    if output.exists():parser.error('--output must be new')
    from bank import hands_on
    from core.files import validate_files
    source=Path(args.source);fixture=Path(args.valid)
    if source.resolve().parent!=(validator.ROOT/'backend/data').resolve() or source.name not in hands_on.SOURCES:parser.error('source must be registered packaged data')
    authored={q['id']:q for q in json.loads(source.read_text(encoding='utf8'))};alternatives=json.loads(fixture.read_text(encoding='utf8'))
    if not isinstance(alternatives,dict) or not alternatives:parser.error('valid must map IDs to named artifact maps')
    report={'schema':1,'scope':'Valid learner alternatives, not extra completed questions','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'source_sha256':validator.sha(source.read_bytes()),'valid_sha256':validator.sha(fixture.read_bytes()),
            'runner_sha256':validator.sha((validator.ROOT/'backend/labs/assessment_runner.py').read_bytes()),
            'validator_sha256':validator.sha(Path(__file__).read_bytes()),'execution':{'wsl':args.wsl,'user':args.wsl_user or ('student' if args.wsl else None)},'questions':[]}
    for ident,cases in alternatives.items():
        q=authored[ident];current=hands_on.catalog().get(ident)
        if current is None or hands_on.fingerprint(q)!=hands_on.fingerprint(current):raise ValueError('not current trusted source')
        if not isinstance(cases,dict) or not cases:raise ValueError('nonempty named valid alternatives required')
        assessment=hands_on.program_contract(q);bundle=hands_on.execution_bundle(q,assessment);routes=[]
        for name,artifacts in cases.items():
            validate_files(artifacts)
            if not artifacts or set(artifacts)-set(q['exercise']['deliverables']) or set(artifacts)&set(bundle):raise ValueError('only declared learner files may change')
            files={**q['files'],**q['solution_files'],**artifacts,**bundle};validate_files(files)
            routes.append({'name':'reference','files':files})
        command=['wsl','-d',args.wsl,'--user',args.wsl_user or 'student','--exec','python3','-B','-c',validator.WORKER] if args.wsl else [sys.executable,'-B','-c',validator.WORKER]
        payload=json.dumps({'routes':routes,'timeout':assessment.get('timeout',30)}).encode('utf8')
        process=subprocess.run(command,input=payload,capture_output=True,timeout=(assessment.get('timeout',30)+100)*len(routes))
        if process.returncode:raise RuntimeError('transport failure: '+process.stderr.decode(errors='replace'))
        item=json.loads(process.stdout);item['id']=ident;item['contract_fingerprint']=hands_on.fingerprint(q)
        if len(item['routes'])!=len(cases):raise ValueError('alternative route count mismatch')
        for name,row in zip(cases,item['routes']):
            row['alternative']=name;row['correct'],row['classification']=validator.assess(row)
        item['verified']=all(row['correct'] for row in item['routes']);report['questions'].append(item)
        print(ident+': '+('verified' if item['verified'] else 'NOT VERIFIED'))
    report['alternative_count']=sum(len(q['routes']) for q in report['questions']);report['accepted_alternative_count']=sum(row['correct'] for q in report['questions'] for row in q['routes'])
    report['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return 0 if report['accepted_alternative_count']==report['alternative_count'] else 1


if __name__=='__main__':raise SystemExit(main())
