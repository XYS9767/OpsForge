"""Regression guards against crediting infrastructure errors as rejected answers."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('validator', Path(__file__).with_name('validate_authored_contracts.py'))
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class RejectionTests(unittest.TestCase):
    def row(self, **changes):
        row = {'route': 'negative', 'outer_timeout': False, 'verdict_count': 1,
               'verdict': {'passed': False, 'completed': False, 'interrupted': False,
                           'exit_code': 1, 'output': 'AssertionError: wrong value\n'}}
        row['verdict'].update(changes)
        return row

    def test_infrastructure_failures_are_not_successful_rejections(self):
        for change in ({'error': 'FileNotFoundError'}, {'interrupted': True},
                       {'output': 'ModuleNotFoundError: absent\n'},
                       {'output': 'SyntaxError: malformed code\n'}, {'exit_code': -9}):
            with self.subTest(change=change):
                self.assertFalse(validator.assess(self.row(**change))[0])
        for field, value in [('outer_timeout', True), ('verdict_count', 0), ('verdict_count', 2)]:
            row = self.row(); row[field] = value
            self.assertFalse(validator.assess(row)[0])

    def test_zero_exit_without_completion_is_only_early_exit_success(self):
        row = self.row(exit_code=0, output='')
        self.assertFalse(validator.assess(row)[0])

        row['route'] = 'runner_early_exit'
        self.assertTrue(validator.assess(row)[0])
        row['verdict']['completed'] = True
        self.assertFalse(validator.assess(row)[0])

    def test_windows_bare_assertion_uses_crlf(self):
        self.assertTrue(validator.assess(self.row(output='Traceback...\r\nAssertionError\r\n'))[0])

    def test_real_runner_missing_tool_is_not_rejection_success(self):
        runner = (validator.ROOT / 'backend/labs/assessment_runner.py').read_text(encoding='utf8')
        files = {'checks/_opsforge_runner.py': runner,
                 'checks/_opsforge_spec.json': json.dumps({'command': 'python3 checks/check.py',
                     'timeout': 2, 'requires': {'commands': ['opsforge-tool-that-does-not-exist']}}),
                 'checks/check.py': 'raise AssertionError("must never execute")\n'}
        payload = {'routes': [{'name': 'negative', 'files': files}], 'timeout': 2}
        proc = subprocess.run([sys.executable, '-B', '-c', validator.WORKER],
                              input=json.dumps(payload), text=True, capture_output=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        row = json.loads(proc.stdout)['routes'][0]
        self.assertEqual(row['verdict']['error'], 'FileNotFoundError')
        self.assertFalse(validator.assess(row)[0])


if __name__ == '__main__':
    unittest.main()
