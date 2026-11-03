"""Reconcile the explicit Python module review without inventing new question credit.

Older native runs are reusable only against their immutable original sources
and exactly equal current learner material/trusted bundles. Metadata validation
does not rerun learner programs and does not stand in for manual facts review.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'backend'))
from bank import assessment,formats,hands_on,taxonomy
from bank.seeding import fingerprint
from bank.service import BankService
from core.database import Database
from validate_authored_contracts import assess

TRUSTED_CODE = {
    'backend/bank/assessment.py','backend/learning/service.py','backend/bank/service.py',
    'backend/bank/formats.py','backend/bank/schema.py','backend/bank/review.py',
    'backend/bank/seeding.py','backend/bank/taxonomy.py','backend/core/question_identity.py',
    'backend/labs/assessment_runner.py','scripts/validate_authored_contracts.py',
    'scripts/validate_python_module_review.py'}

def require(value,message):
    if not value:raise ValueError(message)

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def bounded(name):
    require(isinstance(name,str)and bool(name),'Module evidence path missing')
    path=(ROOT/name.replace('\\','/')).resolve()
    require(path.is_relative_to(ROOT.resolve()),'Module evidence escapes package')
    require(path.is_file(),'Module evidence file missing: '+name)
    return path
def read(name):return json.loads(bounded(name).read_text(encoding='utf8'))

def relevant_policy(policy):
    return {key:policy[key]for key in ['minimum_unique_questions_per_module_format','knowledge_by_format_cartesian_product_required',
        'one_primary_module_and_one_primary_format_per_question','duplicate_or_reworded_question_credit','formal_module_count']}|{
        'formats':[row['id']for row in policy['formats']],
        'python_blueprint':policy['explicit_module_blueprints']['python']}

def registry_logic_sha():
    tree=ast.parse((ROOT/'backend/bank/hands_on.py').read_text(encoding='utf8'))
    for node in tree.body:
        if isinstance(node,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='SOURCES'for t in node.targets):
            node.value=ast.Tuple(elts=[],ctx=ast.Load())
    return hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest()

def checked_four(report,qid,question):
    require(report.get('runner_sha256')==sha(ROOT/'backend/labs/assessment_runner.py'),'Module runner changed')
    require(report.get('validator_sha256')==sha(ROOT/'scripts/validate_authored_contracts.py'),'Module native validator changed')
    items=report.get('questions',[])
    require(len(items)==len({item['id']for item in items}),'Duplicate native evidence question')
    found=[item for item in items if item['id']==qid]
    require(len(found)==1,'Module native question proof missing: '+qid)
    item=found[0]
    require(item.get('contract_fingerprint')==fingerprint(question),'Module native contract fingerprint mismatch: '+qid)
    require(item.get('environment',{}).get('uid')==1000,'Module native proof used wrong user')
    routes=item.get('routes',[])
    require(len(routes)==4 and{r.get('route')for r in routes}=={'reference','starter','negative','runner_early_exit'},'Module four routes incomplete')
    require(all(assess(row)[0]for row in routes),'Module native route did not pass strict verification: '+qid)

def verify_manifest(manifest_name,service):
    manifest=read(manifest_name)
    require(manifest.get('schema')==1 and type(manifest.get('schema'))is int,'Unsupported module evidence schema')
    require(manifest.get('kind')=='python_module_review_v1'and manifest.get('task_id')=='module-review:python','Unsupported module review task')
    files=manifest.get('files',{})
    require(isinstance(files,dict)and bool(files),'Module evidence file inventory missing')
    for name,expected in files.items():require(sha(bounded(name))==expected,'Module evidence SHA mismatch: '+name)
    proofs=manifest.get('proofs',{})
    def proof(key):
        name=proofs.get(key);require(name in files,'Module proof is not inventoried: '+key)
        return read(name)
    require(set(manifest.get('trusted_code',{}))==TRUSTED_CODE,'Module trusted code inventory incomplete')
    for name,expected in manifest['trusted_code'].items():require(sha(bounded(name))==expected,'Module assessment code changed: '+name)
    require(manifest.get('registry_logic_sha256')==registry_logic_sha(),'Module registry logic changed')
    policy=read('backend/data/curriculum-coverage-policy.json')
    require(manifest.get('policy')==relevant_policy(policy),'Module qualification policy changed')
    require(policy['minimum_unique_questions_per_module_format']==10 and policy['duplicate_or_reworded_question_credit']==0,'Unsupported module quota policy')
    frozen_export=proof('frozen_export');frozen={row['id']:row for row in frozen_export['questions']}
    current=[q for q in service.allq()if q.get('review_status')=='reviewed'and taxonomy.placement(q)['primary_module']=='python']
    current={q['id']:q for q in current}
    require(len(current)==235 and set(current)==set(frozen),'Current Python module roster changed')
    join=proof('join');require(join.get('status')=='step6_registered235_provenance_join_passed_not_module_acceptance','Module final provenance join did not pass')
    joined={row['id']:row for row in join['rows']}
    require(len(joined)==235 and set(joined)==set(current),'Module join roster mismatch')
    semantic=proof('semantic')
    require(semantic.get('questions_read')==235 and semantic.get('status')=='current235_obligation_semantic_read_review_complete_with_three_conservative_variant_groups','Module semantic reading incomplete')
    require(semantic.get('question_current_fingerprints')=={qid:row['fingerprint']for qid,row in frozen.items()},'Module semantic review is not bound to the full reviewed cohort')
    excluded=set();grouped=set()
    for group in semantic['duplicate_groups']:
        ids=[group['canonical'],*group['variants']]
        require(len(ids)>=2 and len(ids)==len(set(ids))and not grouped&set(ids),'Module duplicate groups overlap')
        require(set(ids)<=set(current)and len({formats.classify(current[qid])for qid in ids})==1,'Module duplicate group is not a single primary format')
        require(group.get('current_fingerprints')=={qid:frozen[qid]['fingerprint']for qid in ids},'Module semantic group members differ from reviewed fingerprint bindings')
        require(bool(group.get('reason','').strip()),'Module duplicate review rationale missing')
        grouped.update(ids);excluded.update(group['variants'])
    require(excluded==set(semantic['excluded_from_unique_credit'])and len(excluded)==3,'Module variant exclusion mismatch')
    counts=dict(Counter(formats.classify(q)for qid,q in current.items()if qid not in excluded))
    require(counts==semantic['unique_format_counts']and sum(counts.values())==232,'Module unique counts inflated')
    require(set(counts)==set(manifest['policy']['formats'])and min(counts.values())>=10,'Module unique format quota not met')
    oldproof=proof('old_four');newproof=proof('new017_four')
    # All old source bytes are archived. No changed current source hash is
    # substituted into a historical execution report.
    archive=manifest.get('old_source_archives',{})
    sources=oldproof.get('sources')
    require(isinstance(sources,list)and bool(sources),'Original module source provenance empty')
    require({item['path'].replace('\\','/')for item in sources}==set(archive),'Original module source archive roster mismatch')
    archived_questions={}
    for item in sources:
        original=item['path'].replace('\\','/')
        require(original in archive,'Original module source archive missing')
        require(archive[original]in files,'Original module source archive not inventoried')
        require(sha(bounded(archive[original]))==item['sha256'],'Original module execution source mismatch')
        for raw in read(archive[original]):archived_questions[raw['id']]=fingerprint(raw)
    for item in newproof['sources']:
        require(sha(bounded(item['path']))==item['sha256'],'Registered017 current source mismatch')
    programs=0;knowledge=[]
    for qid,q in current.items():
        row=joined[qid];old=frozen[qid];oldq=old['question']
        require(row['current_fingerprint']==fingerprint(q),'Current module fingerprint differs reviewed join: '+qid)
        require(formats.classify(q)==row['format']==old['format'],'Module reviewed format changed')
        contract=hands_on.program_contract(q)
        if contract is None:
            require(q==oldq,'Reviewed knowledge question changed: '+qid);knowledge.append(qid);continue
        programs+=1;bundle=hands_on.execution_bundle(q,contract)
        require(digest(bundle)==row['trusted_bundle_sha256'],'Module trusted bundle changed: '+qid)
        if qid=='curated-advanced-python-017':
            changed={k for k in set(q)|set(oldq)if q.get(k)!=oldq.get(k)}
            require(changed=={'solution_files','answer','assessment'},'017 repair exceeded reviewed scope')
            checked_four(newproof,qid,q)
        else:
            require(q==oldq and bundle==old['execution_bundle'],'Old module proof cannot cover changed contract: '+qid)
            require(archived_questions.get(qid)==fingerprint(oldq),'Original module source does not cover reviewed native contract: '+qid)
            checked_four(oldproof,qid,oldq)
    require(programs==177 and len(knowledge)==58,'Module teaching/knowledge split changed')
    objective=proof('objective40');short=proof('short18');grades=proof('objective_grades')
    require(objective.get('status')=='step1_complete_not_module_acceptance'and len(objective['rows'])==40,'Objective read review incomplete')
    require(short.get('status')=='step2_content_and_rubric_review_complete_not_module_acceptance'and len(short['rows'])==18,'Short-answer read review incomplete')
    require(not objective.get('confirmed_defects')and not short.get('references_with_confirmed_fact_errors'),'Known knowledge fact errors remain')
    reviewed=objective['rows']+short['rows']
    require(len({r['id']for r in reviewed})==58 and {r['id']for r in reviewed}==set(knowledge),'Knowledge review roster mismatch')
    for row in reviewed:require(row['fingerprint']==fingerprint(current[row['id']]),'Knowledge review fingerprint mismatch')
    require(grades.get('status')=='passed'and len(grades['rows'])==40,'Actual objective grading evidence missing')
    objective_ids={row['id']for row in objective['rows']}
    require(len(objective_ids)==40 and {row['id']for row in grades['rows']}==objective_ids,'Objective grading roster mismatch')
    require(all(formats.classify(current[qid])!='short_answer'for qid in objective_ids),'Objective roster includes short answers')
    calls=0;rating_checks=0
    for row in grades['rows']:
        q=current[row['id']];require(row['fingerprint']==fingerprint(q),'Objective grade question changed')
        checks=row['grade_checks'];require(len(checks)>=6,'Objective grading boundary matrix incomplete')
        for sample in checks:
            require(type(sample['expected'])is bool,'Objective expected verdict must be boolean')
            observed=assessment.grade(q,sample['answer'])
            require(observed is not None and observed['passed']is sample['expected'],'Current objective grade differs independently checked sample')
            calls+=1
        require(row.get('self_rating_cannot_override_wrong')is True,'Objective self-rating isolation evidence missing')
        rating_checks+=1
    require(calls+rating_checks==grades['grade_calls']and calls>=240 and rating_checks==40,'Objective grading evidence call count mismatch')
    for row in short['rows']:
        require(row.get('automatic_semantic_grading_claimed')is False,'Self-assessment cannot be claimed as semantic automatic grading')
        require(assessment.grade(current[row['id']],'arbitrary text')is None,'Short-answer grading semantics changed')
    breadth=proof('breadth');points=manifest['policy']['python_blueprint']
    require(len(breadth['topics'])==len(points)==15 and{r['blueprint_point']for r in breadth['topics']}==set(points),'Module blueprint coverage mismatch')
    for topic in breadth['topics']:
        supports=topic['explicit_knowledge_support']+topic['selected_executable_support']
        require(any(item['id']in current and item['id']not in excluded for item in supports),'Blueprint support only uses excluded variants')
        for item in supports:require(item['fingerprint']==fingerprint(current[item['id']]),'Blueprint reviewed support changed')
    depth=proof('depth');require(len(depth['questions'])==32,'High-format depth review incomplete')
    require(depth.get('status')=='step5_current32_bounded_depth_read_review_complete_not_module_acceptance','High-format depth review status incomplete')
    require(len({r['id']for r in depth['questions']})==32,'High-format depth roster duplicated')
    require(Counter(formats.classify(current[r['id']])for r in depth['questions'])=={'practice':12,'case':10,'project':10},'High-format depth roster mismatch')
    for row in depth['questions']:
        require(row['id']not in excluded and row['current_fingerprint']==fingerprint(current[row['id']]),'High-format reviewed question changed')
        require(row.get('actual_format')==formats.classify(current[row['id']]),'High-format reviewed teaching format missing')
        require(all(isinstance(row.get(key),str)and row[key].strip()for key in
            ['primary_operation_chain_manual','scope_and_depth_judgment','review_basis']),
            'High-format substantive manual review missing')
        require(row.get('depth_review')=='substantive_bounded_course_workflow_not_production_claim','High-format depth judgment missing')
    peer=proof('peer017');require(peer.get('all_expected')is True and peer['contract_fingerprint']==fingerprint(current['curated-advanced-python-017']),'017 independent review missing')
    return {'reviewed_module':'python','raw_questions':235,'unique_questions':232,'program_questions':177,
        'unique_program_questions':174,'knowledge_questions':58,'unique_format_counts':counts,
        'excluded_variants':sorted(excluded),'evidenced_native_routes':708,'fresh017_routes':4,
        'scope':'One module acceptance only. Three variants excluded; original176 native proofs reused only for identical full contracts/bundles. Not global semantic proof, offline restore or final PC acceptance.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',required=True)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    require(not args.output.exists(),'Refusing to replace module validation output')
    with tempfile.TemporaryDirectory(prefix='opsforge-python-module-')as temporary:
        database=Database(str(Path(temporary)/'bank.sqlite'),'bank');database.migrate()
        class Harness(BankService):
            def db(self,domain):require(domain=='bank','Wrong metadata database');return database.transaction()
        service=Harness();service.seed();result=verify_manifest(args.manifest,service)
        service.seed();require(service.bank_meta['upgrade']=={'updated':0,'conflicts':[]},'Module repeated seed not idempotent')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'status':'passed',**result,'manifest_sha256':sha(bounded(args.manifest)),
        'validator_sha256':sha(Path(__file__)),'new_task_credit':0},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':'passed','raw_questions':235,'unique_questions':232,'module_count':1}))

if __name__=='__main__':main()
