"""Verify new process continuations through actual bank and import boundaries."""
import argparse
import copy
import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'backend'))
from bank import formats,hands_on,schema
from bank.service import BankService
from bank.assessment import capable
from core.database import Database


class LocalBank(BankService):
    def __init__(self,directory):
        self.store=Database(directory/'bank.sqlite3','bank',dsn='')
        self.store.migrate()
    def db(self,domain):
        assert domain=='bank'
        return self.store.transaction()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);args=parser.parse_args();output=Path(args.output).resolve()
    if output.exists():parser.error('--output must be new')
    output.parent.mkdir(parents=True,exist_ok=True)
    expected={'curated-feishu-60-064':'case','src-b50128eb7459ce12':'practice'}
    report={'schema':1,'scope':'real seed/getq/public/classify/schema/automatic grading and idempotent reseed',
            'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'sources':{},'checks':[]}
    for filename in ['hands-on-continuation-process-terminal-native.json','hands-on-continuation-process-syscalls-native.json']:
        path=ROOT/'backend/data'/filename;report['sources'][filename]=hashlib.sha256(path.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='process-metadata-',dir=output.parent)as directory:
        bank=LocalBank(Path(directory));bank.seed();assert not bank.bank_meta['upgrade']['conflicts']
        for qid,kind in expected.items():
            source=hands_on.catalog()[qid];loaded=bank.getq(qid)
            assert formats.classify(source)==formats.classify(loaded)==kind
            assert loaded['type']==kind and loaded['question_format']==kind and loaded['exercise']['kind']=='code'
            assert hands_on.program_contract(loaded) and capable(loaded)
            public=bank.public(loaded);assert public['question_format']==kind and public['automatic_grading']is True
            assert not set(hands_on.PRIVATE_FIELDS).intersection(public)
            imported=schema.prepare([copy.deepcopy(loaded)])[0]
            assert imported['type']==kind and formats.classify(imported)==kind
            assert imported['exercise']['deliverables']==loaded['exercise']['deliverables']
            report['checks'].append({'id':qid,'type':kind,'format':kind,'seed_getq':True,'public':True,
                                     'schema_prepare':True,'trusted_program_contract':True,'automatic_grading':True})
        bank.seed();assert not bank.bank_meta['upgrade']['conflicts']and bank.bank_meta['upgrade']['updated']==0
        report['repeat_seed_idempotent']=True
    report['question_count']=len(report['checks'])
    report['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('2/2 process continuation metadata integrations passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
