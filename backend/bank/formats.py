"""Nine teaching formats alongside unchanged legacy execution types."""
import re
import json
from functools import lru_cache
from pathlib import Path
from core.errors import ApiError

FORMATS = {'single_choice': '单选', 'multiple_choice': '多选', 'true_false': '判断',
           'fill_blank': '填空', 'short_answer': '简答', 'code': '编程',
           'practice': '实操', 'case': '故障场景', 'project': '综合项目'}
LEGACY = {'interview': 'short_answer', 'source': 'short_answer', 'code': 'code',
          'practice': 'practice', 'case': 'case', 'scenario': 'case'}
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,31}')

@lru_cache(maxsize=1)
def reviewed_annotations():
    path = Path(__file__).resolve().parents[1] / 'data/question-format-annotations.json'
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding='utf8'))
    result = {}
    for row in rows:
        if (not isinstance(row, dict) or row.get('reviewed') is not True
                or row.get('format') not in FORMATS or not row.get('reason')
                or not re.fullmatch(r'[0-9a-f]{64}', row.get('content_key', ''))
                or row.get('id') in result):
            raise ValueError('Invalid reviewed question-format annotation')
        result[row['id']] = row
    return result

def classify(question):
    explicit = question.get('question_format')
    if explicit:
        return explicit if isinstance(explicit, str) and explicit in FORMATS else None
    annotation = reviewed_annotations().get(question.get('id'))
    if annotation:
        from core.question_identity import content_key
        if annotation['content_key'] == content_key(question):
            return annotation['format']
    # Titles and difficulty do not turn a task into a project or objective item.
    return LEGACY.get(question.get('type'))

def prepare_metadata(item):
    kind = item.get('question_format')
    if kind is None:
        return {}
    if not isinstance(kind, str) or kind not in FORMATS:
        raise ApiError('question_format 需要是九类题型之一')
    result = {'question_format': kind}
    if kind in ('single_choice', 'multiple_choice', 'true_false'):
        options = item.get('options')
        if not isinstance(options, list) or not 2 <= len(options) <= 12:
            raise ApiError('选择/判断题需要2–12个选项')
        ids, cleaned = set(), []
        for option in options:
            if not isinstance(option, dict) or set(option) != {'id', 'text'}:
                raise ApiError('选项只包含id和text；正确答案放在私有判分规则中')
            ident, text = option['id'], option['text']
            if not isinstance(ident, str) or not IDENTIFIER.fullmatch(ident) or ident in ids:
                raise ApiError('选项id需要唯一且为1–32位字母开头的标识符')
            if not isinstance(text, str) or not text.strip() or len(text) > 5000:
                raise ApiError('选项文本需要1–5000字符')
            ids.add(ident); cleaned.append({'id': ident, 'text': text})
        if kind == 'true_false' and ids != {'true', 'false'}:
            raise ApiError('判断题必须使用true/false两个选项')
        result['options'] = cleaned
        if item.get('grading') is not None:
            from .assessment import validate
            rule = validate(item['grading'])
            if (rule['kind'] != 'choice' or set(rule['options']) != ids
                    or rule['multiple'] != (kind == 'multiple_choice')):
                raise ApiError('选择题选项、题型与私有判分规则不一致')
    elif kind == 'fill_blank':
        blanks = item.get('blanks')
        if not isinstance(blanks, list) or not 1 <= len(blanks) <= 12:
            raise ApiError('填空题需要1–12个空')
        ids, cleaned = set(), []
        for blank in blanks:
            if not isinstance(blank, dict) or set(blank) != {'id', 'label'}:
                raise ApiError('空位只包含id和label')
            ident, label = blank['id'], blank['label']
            if not isinstance(ident, str) or not IDENTIFIER.fullmatch(ident) or ident in ids:
                raise ApiError('空位id必须为唯一的简单标识符')
            if not isinstance(label, str) or not label.strip() or len(label) > 500:
                raise ApiError('空位label需要1–500字符')
            ids.add(ident); cleaned.append({'id': ident, 'label': label})
        result['blanks'] = cleaned
        if item.get('grading') is not None:
            from .assessment import validate
            rule = validate(item['grading'])
            if rule['kind'] != 'blanks' or {field['id'] for field in rule['fields']} != ids:
                raise ApiError('填空题空位与私有判分规则不一致')
    return result
