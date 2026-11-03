"""Exercise real seed/evidence accounting against accidental over-crediting."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProgressAuditTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'work').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='progress-regression-', dir=ROOT / 'work')
        self.root = Path(self.temporary.name).resolve()
        assert self.root.is_relative_to((ROOT / 'work').resolve())
        self.addCleanup(self.temporary.cleanup)
        self.manifest = json.loads((ROOT / 'docs/continuation-claims.json').read_text(encoding='utf8'))

    def run_audit(self, claims, baseline=None):
        path = self.root / 'claims.json'
        path.write_text(json.dumps({'claims': claims}, ensure_ascii=False), encoding='utf8')
        command = [sys.executable, '-B', str(ROOT / 'scripts/audit_continuation_progress.py'),
                   '--claims', path.relative_to(ROOT).as_posix(), '--output', str(self.root / 'result.json')]
        if baseline is not None:
            bp = self.root / 'baseline.json'
            bp.write_text(json.dumps(baseline, ensure_ascii=False), encoding='utf8')
            command += ['--baseline', bp.relative_to(ROOT).as_posix()]
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf8', timeout=60)

    def test_real_knowledge_proof_counts_one_unique_delta(self):
        result = self.run_audit(self.manifest['claims'][:1])
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.root / 'result.json').read_text(encoding='utf8'))
        self.assertEqual((report['verified_delta'], report['remaining_count']), (1, 1341))
        self.assertFalse(report['inherited_baseline_independently_reproduced'])

    def test_same_question_cannot_consume_two_planning_slots(self):
        claims = copy.deepcopy(self.manifest['claims'][:2])
        claims[1]['question_id'] = claims[0]['question_id']
        result = self.run_audit(claims)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cannot consume multiple backlog slots', result.stderr)

    def test_other_module_cannot_fill_an_istio_slot(self):
        claim = copy.deepcopy(self.manifest['claims'][0])
        claim['question_id'] = 'interview-linux'
        result = self.run_audit([claim])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Target primary module not satisfied', result.stderr)

    def test_unchanged_existing_code_cannot_be_claimed_as_adapted(self):
        claim = {'task_id': 'question:curated-advanced-kubernetes-022', 'question_id': 'curated-advanced-kubernetes-022',
                 'evidence': [], 'change_reason': 'no actual change'}
        result = self.run_audit([claim])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Existing content did not change', result.stderr)

    def test_inherited_count_cannot_be_silently_increased(self):
        baseline = json.loads((ROOT / 'docs/continuation-baseline.json').read_text(encoding='utf8'))
        baseline['inherited_declared_completion']['completed'] += 1
        result = self.run_audit(self.manifest['claims'][:1], baseline)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Inherited declaration was changed', result.stderr)

    def test_changed_mutants_cannot_reuse_old_execution_proof(self):
        claim = copy.deepcopy(next(c for c in self.manifest['claims'] if c['question_id'] == 'curated-istio-continuation-code-003'))
        path = self.root / 'mutants.json'
        path.write_text('{}\n', encoding='utf8')
        claim['mutants'] = path.relative_to(ROOT).as_posix()
        result = self.run_audit([claim])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Mutant fixture SHA mismatch', result.stderr)

    def module_claim(self):
        return {'task_id':'module-review:python','question_id':None,
                'evidence':['evidence/module-review/python/checkpoint013/manifest-v4.json'],
                'change_reason':'Current235 manual facts/depth/semantic review; three variants excluded; native provenance bound.'}

    def test_module_acceptance_counts_one_gate_and_zero_question_ids(self):
        result=self.run_audit([self.module_claim()])
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads((self.root/'result.json').read_text(encoding='utf8'))
        self.assertEqual((report['verified_delta'],report['new_question_ids'],report['reused_question_ids'],report['acceptance_items']),(1,0,0,1))
        self.assertEqual(report['remaining_count'],1341)
        self.assertEqual(report['completed'][0]['module_review']['unique_questions'],232)

    def test_module_acceptance_cannot_also_consume_a_question_id(self):
        claim=self.module_claim();claim['question_id']='curated-advanced-python-017'
        result=self.run_audit([claim])
        self.assertNotEqual(result.returncode,0)
        self.assertIn('cannot consume a question ID',result.stderr)

    def test_python_evidence_cannot_complete_another_module_gate(self):
        claim=self.module_claim();claim['task_id']='module-review:redis'
        result=self.run_audit([claim])
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Unsupported acceptance claim',result.stderr)


if __name__ == '__main__':
    unittest.main()
