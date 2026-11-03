"""Validate continuation formats through the real bank seed and import boundaries."""
import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'backend'))

from bank import formats, hands_on, schema
from bank.assessment import capable
from bank.service import BankService
from core.database import Database
from core.errors import ApiError

PYTHON_IDS = ['curated-dev-python-' + n for n in
              ('073', '075', '076', '077', '083', '084', '085', '086', '087',
               '088', '089', '090', '091', '092')]
GO_IDS = ['curated-parallel-go-' + n for n in
          ('042', '043', '046', '050', '055', '056', '057', '061', '065', '083')]
SHELL_IDS = ['src-' + n for n in
             ('72fdd0fb36c61d4a', '85f4dfa373bdec37', '8b1fe28e7a1ba32d',
              '9a7211d37ecc2e2c', 'df2e2db8973dcd65', 'e388c334baa86bae',
              'e6ec668c4e4674ff', 'fefab13df2e2fea5')]
PROJECT_IDS = {'curated-dev-python-' + str(n).zfill(3) for n in range(83, 93)}
ISOLATION_IDS = ['curated-advanced-shell-014']


class LocalBank(BankService):
    def __init__(self, directory):
        self.store = Database(directory / 'bank.sqlite3', 'bank', dsn='')
        self.store.migrate()

    def db(self, domain):
        assert domain == 'bank'
        return self.store.transaction()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        parser.error('--output must be new')
    if os.environ.get('REQUIRE_POSTGRES') == 'true':
        parser.error('This isolated SQLite check requires REQUIRE_POSTGRES to be unset')
    output.parent.mkdir(parents=True, exist_ok=True)
    sources = {}
    for filename in ('hands-on-python-extra.json', 'hands-on-go-converted.json',
                     'hands-on-shell-converted.json',
                     'hands-on-continuation-shell-isolation-cases-native.json'):
        path = ROOT / 'backend/data' / filename
        sources[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {
        'schema': 1,
        'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'real BankService.seed/getq/public + formats.classify + schema.prepare; temporary SQLite only',
        'sources': sources,
        'checks': [],
    }
    with tempfile.TemporaryDirectory(prefix='bank-integration-', dir=output.parent) as directory:
        bank = LocalBank(Path(directory))
        bank.seed()
        assert not bank.bank_meta['upgrade']['conflicts']
        for qid in PYTHON_IDS + GO_IDS + SHELL_IDS + ISOLATION_IDS:
            expected = ('project' if qid in PROJECT_IDS else
                        'case' if qid in SHELL_IDS + ISOLATION_IDS else 'practice')
            source = hands_on.catalog()[qid]
            loaded = bank.getq(qid)
            assert formats.classify(source) == expected, (qid, 'source format')
            assert formats.classify(loaded) == expected, (qid, 'seed/getq format')
            if expected == 'project':
                assert loaded['type'] == 'code', qid
                assert loaded['exercise']['kind'] == 'code', qid
                assert loaded['question_format'] == 'project', qid
            elif expected == 'case':
                assert loaded['type'] == 'case', qid
                assert loaded['exercise']['kind'] == 'code', qid
                assert loaded['question_format'] == 'case', qid
            else:
                assert loaded['type'] == 'practice', qid
            assert hands_on.program_contract(loaded), (qid, 'trusted contract')
            assert capable(loaded), (qid, 'automatic grading')
            public = bank.public(loaded)
            assert public['question_format'] == expected, (qid, 'public format')
            assert public['automatic_grading'] is True, (qid, 'public grading')
            assert not set(hands_on.PRIVATE_FIELDS).intersection(public), (qid, 'private fields exposed')
            imported = schema.prepare([copy.deepcopy(loaded)])[0]
            assert formats.classify(imported) == expected, (qid, 'schema format')
            assert imported['type'] == loaded['type'], (qid, 'import legacy type')
            assert imported['exercise']['deliverables'] == loaded['exercise']['deliverables']
            report['checks'].append({
                'id': qid, 'legacy_type': loaded['type'], 'format': expected,
                'exercise_kind': loaded['exercise']['kind'],
                'seed_getq': True, 'public_format': True, 'schema_prepare': True,
                'trusted_program_contract': True, 'automatic_grading': True,
            })
        # Reproduce the original metadata defect and verify both boundaries
        # distinguish it from the supported legacy code + project format.
        broken = copy.deepcopy(bank.getq('curated-dev-python-083'))
        broken['type'] = 'project'
        broken.pop('question_format', None)
        assert formats.classify(broken) is None
        try:
            schema.prepare([broken])
        except ApiError:
            report['legacy_project_type_rejected'] = True
        else:
            raise AssertionError('schema accepted unsupported legacy project type')
        bank.seed()
        assert not bank.bank_meta['upgrade']['conflicts']
        assert bank.bank_meta['upgrade']['updated'] == 0, 'repeat seed was not idempotent'
        report['repeat_seed_idempotent'] = True
    report['question_count'] = len(report['checks'])
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Verified 33 continuation questions through seed/getq/public/classify/schema; repeat seed idempotent')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
