"""Reject incomplete or inflated module claims against one actual seeded bank."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from validate_python_module_review import ROOT, BankService, Database, sha, verify_manifest

MANIFEST='evidence/module-review/python/checkpoint013/manifest-v4.json'


class ModuleReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_dir=tempfile.TemporaryDirectory(prefix='module-review-bank-')
        cls.database=Database(str(Path(cls.database_dir.name)/'bank.sqlite'),'bank')
        cls.database.migrate()
        class Harness(BankService):
            def db(self,domain):
                if domain!='bank':raise ValueError('Unexpected domain')
                return ModuleReviewTests.database.transaction()
        cls.service=Harness();cls.service.seed()

    @classmethod
    def tearDownClass(cls):cls.database_dir.cleanup()

    def setUp(self):
        (ROOT/'work').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='module-negative-',dir=ROOT/'work')
        self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.manifest=json.loads((ROOT/MANIFEST).read_text(encoding='utf8'))

    def mutate_proof(self,key,change):
        original=self.manifest['proofs'][key]
        document=json.loads((ROOT/original).read_text(encoding='utf8'))
        change(document)
        path=self.directory/(key+'.json')
        path.write_text(json.dumps(document,ensure_ascii=False),encoding='utf8')
        relative=path.relative_to(ROOT).as_posix()
        self.manifest['proofs'][key]=relative
        self.manifest['files'][relative]=sha(path)

    def verify(self):
        path=self.directory/'manifest.json'
        path.write_text(json.dumps(self.manifest,ensure_ascii=False),encoding='utf8')
        return verify_manifest(path.relative_to(ROOT).as_posix(),self.service)

    def test_actual_module_keeps_three_variants_out_of_unique_counts(self):
        result=self.verify()
        self.assertEqual((result['raw_questions'],result['unique_questions']), (235,232))
        self.assertEqual(len(result['excluded_variants']),3)

    def test_status_only_report_cannot_replace_manual_evidence(self):
        self.manifest={'schema':1,'kind':'python_module_review_v1','task_id':'module-review:python','status':'passed'}
        with self.assertRaisesRegex(ValueError,'inventory missing'):self.verify()

    def test_missing_trusted_code_inventory_is_rejected(self):
        self.manifest['trusted_code']={}
        with self.assertRaisesRegex(ValueError,'trusted code inventory incomplete'):self.verify()

    def test_current_fingerprint_cannot_be_replaced_by_status_passed(self):
        self.mutate_proof('join',lambda doc:doc['rows'][0].update(current_fingerprint='0'*64))
        with self.assertRaisesRegex(ValueError,'fingerprint differs'):self.verify()

    def test_variant_credit_inflation_is_rejected_even_with_new_evidence_sha(self):
        self.mutate_proof('semantic',lambda doc:doc['unique_format_counts'].update(code=145))
        with self.assertRaisesRegex(ValueError,'unique counts inflated'):self.verify()

    def test_missing_native_route_is_rejected_even_with_new_evidence_sha(self):
        self.mutate_proof('new017_four',lambda doc:doc['questions'][0]['routes'].pop())
        with self.assertRaisesRegex(ValueError,'four routes incomplete'):self.verify()

    def test_self_assessment_cannot_be_upgraded_to_semantic_automatic_grading(self):
        self.mutate_proof('short18',lambda doc:doc['rows'][0].update(automatic_semantic_grading_claimed=True))
        with self.assertRaisesRegex(ValueError,'Self-assessment'):self.verify()

    def test_repeated_depth_row_cannot_replace_an_unreviewed_question(self):
        def repeat(doc):doc['questions'][1]=copy.deepcopy(doc['questions'][0])
        self.mutate_proof('depth',repeat)
        with self.assertRaisesRegex(ValueError,'depth roster duplicated'):self.verify()

    def test_empty_original_source_provenance_is_rejected(self):
        self.mutate_proof('old_four',lambda doc:doc.update(sources=[]))
        with self.assertRaisesRegex(ValueError,'source provenance empty'):self.verify()

    def test_duplicate_group_members_must_match_the_manually_reviewed_pair(self):
        self.mutate_proof('semantic',lambda doc:doc['duplicate_groups'][0].update(variants=['code-python-log']))
        with self.assertRaisesRegex(ValueError,'group members differ'):self.verify()

    def test_depth_id_index_cannot_replace_substantive_manual_review(self):
        def strip(doc):doc['questions']=[{k:r[k]for k in ['id','current_fingerprint']}for r in doc['questions']]
        self.mutate_proof('depth',strip)
        with self.assertRaisesRegex(ValueError,'High-format reviewed teaching format missing'):self.verify()


if __name__=='__main__':unittest.main()
