"""Explicit user-confirmed curriculum scope; removed content cannot reappear through old DBs/imports."""
import json
from functools import lru_cache
from pathlib import Path
@lru_cache(maxsize=1)
def policy():
    return json.loads((Path(__file__).resolve().parents[1]/'data/course-scope.json').read_text(encoding='utf8'))
def removed(question):
    p=policy()
    if question.get('id') in p['user_removed_question_ids'] or question.get('module') in p['removed_module_ids']:return True
    if str(question.get('category','')).casefold() in {name.casefold() for name in p['removed_module_names']}:return True
    extra_sources=question.get('sources') or []
    if not isinstance(extra_sources,list):extra_sources=[extra_sources]
    sources=[question.get('source',''),*extra_sources]
    if any(str(source).replace('\\','/').startswith('topics/perl/') for source in sources):return True
    return False
def role(module):
    p=policy()
    return 'core' if module in p['core_module_ids'] else 'reference' if module in p['reference_module_ids'] else 'removed'
