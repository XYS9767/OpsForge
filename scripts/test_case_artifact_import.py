"""Case artifact metadata imports without granting uploaded code execution."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'backend'))
from bank.assessment import capable
from bank.hands_on import program_contract
from bank.schema import prepare
from core.errors import ApiError


class CaseArtifactImportTests(unittest.TestCase):
    def source(self):
        return {'id': 'curated-known-case', 'title': 'Repair a bounded native script failure',
                'type': 'case', 'question_format': 'case', 'module': 'shell',
                'body': '操作任务：复现并修复。产物：repair.sh。验收方法：观察实际结果。',
                'files': {'repair.sh': 'exit 1\n'}, 'answer': 'Repair the actual error.',
                'exercise': {'environment': 'Isolated unprivileged Linux',
                             'deliverables': ['repair.sh'], 'verification': 'Run isolated boundary checks'},
                'review_status': 'reviewed',
                'assessment': {'kind': 'program', 'command': 'python3 checks/check.py',
                               'test_files': {'checks/check.py': 'raise SystemExit(0)\n'}},
                'solution_files': {'repair.sh': 'exit 0\n'},
                'negative_files': {'repair.sh': 'exit 99\n'}}

    def test_case_metadata_is_preserved_but_upload_gets_no_execution_rights(self):
        item = prepare([self.source()])[0]
        self.assertEqual(item['type'], 'case')
        self.assertEqual(item['question_format'], 'case')
        self.assertEqual(item['exercise']['deliverables'], ['repair.sh'])
        self.assertEqual(item['review_status'], 'pending')
        self.assertTrue(item['id'].startswith('custom-'))
        self.assertFalse({'assessment', 'solution_files', 'negative_files'} & item.keys())
        self.assertIsNone(program_contract(item))
        self.assertFalse(capable(item))

    def test_interview_still_cannot_declare_executable_artifact_metadata(self):
        item = self.source()
        item['type'] = 'interview'
        item['question_format'] = 'short_answer'
        with self.assertRaises(ApiError):
            prepare([item])

    def test_case_still_rejects_unsafe_paths_and_missing_contract_sections(self):
        for mutate in [lambda q: q['exercise'].update(deliverables=['../escape.sh']),
                       lambda q: q['exercise'].update(deliverables=[]),
                       lambda q: q.update(body='missing operation and verification labels')]:
            item = copy.deepcopy(self.source())
            mutate(item)
            with self.assertRaises((ApiError, ValueError)):
                prepare([item])


if __name__ == '__main__':
    unittest.main()
