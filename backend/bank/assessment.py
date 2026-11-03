"""Bounded, declarative answer checks. No expressions or learner code execute."""
import json
import re
from decimal import Decimal, DecimalException, InvalidOperation, localcontext
from core.errors import ApiError


def validate(spec):
    if not isinstance(spec, dict) or spec.get('kind') not in ('exact', 'number', 'json', 'choice', 'blanks'):
        raise ApiError('自动判题规则只支持 exact、number、json、choice 或 blanks')
    try:
        serialized = json.dumps(spec, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ApiError('自动判题规则必须是有限、无循环的 JSON 数据')
    if len(serialized) > 100000:
        raise ApiError('自动判题规则过大')
    kind = spec['kind']
    if kind == 'choice':
        options, accepted, multiple = spec.get('options'), spec.get('accepted'), spec.get('multiple', False)
        if (not isinstance(options, list) or not 2 <= len(options) <= 12
                or any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', x) for x in options)
                or len(options) != len(set(options)) or type(multiple) is not bool):
            raise ApiError('choice需要唯一选项id及明确的multiple布尔值')
        if (not isinstance(accepted, list) or not accepted or any(not isinstance(x, str) for x in accepted)
                or len(accepted) != len(set(accepted)) or not set(accepted) <= set(options)
                or (not multiple and len(accepted) != 1) or (multiple and len(accepted) < 2)):
            raise ApiError('choice正确答案需要是选项的唯一子集，并符合单选/多选数量')
        return {'kind': kind, 'options': options, 'accepted': accepted, 'multiple': multiple}
    if kind == 'blanks':
        fields, cleaned, ids = spec.get('fields'), [], set()
        if not isinstance(fields, list) or not 1 <= len(fields) <= 12:
            raise ApiError('blanks需要1–12个空位规则')
        for field in fields:
            if not isinstance(field, dict):
                raise ApiError('填空规则需要对象')
            ident, accepted = field.get('id'), field.get('accepted')
            if (not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', ident)
                    or ident in ids or not isinstance(accepted, list) or not 1 <= len(accepted) <= 30
                    or any(not isinstance(x, str) or not x.strip() or len(x) > 5000 for x in accepted)):
                raise ApiError('填空规则需要唯一id和非空标准答案')
            ids.add(ident); cleaned.append({'id': ident, 'accepted': accepted})
        return {'kind': kind, 'fields': cleaned}
    if kind == 'exact':
        accepted = spec.get('accepted')
        if not isinstance(accepted, list) or not 1 <= len(accepted) <= 30 or any(not isinstance(x, str) or not x.strip() for x in accepted):
            raise ApiError('exact 规则需要 1–30 个非空标准答案')
        return {'kind': kind, 'accepted': accepted}
    if 'expected' not in spec:
        raise ApiError('自动判题规则缺少 expected')
    if kind == 'number':
        try:
            expected, tolerance = Decimal(str(spec['expected'])), Decimal(str(spec.get('tolerance', '0')))
        except InvalidOperation:
            raise ApiError('数值判题参数无效')
        if not expected.is_finite() or not tolerance.is_finite() or tolerance < 0:
            raise ApiError('数值判题参数必须有限，容差不能为负')
        if not _bounded_number(expected) or not _bounded_number(tolerance):
            raise ApiError('数值判题参数的位数或指数超出 10000 的范围')
        return {'kind': kind, 'expected': str(expected), 'tolerance': str(tolerance)}
    raw = json.dumps(spec['expected'], allow_nan=False)
    if len(raw) > 100000:
        raise ApiError('JSON 标准产物过大')
    return {'kind': kind, 'expected': spec['expected']}


def declarative(question):
    rule = question.get('grading', {})
    if not isinstance(rule, dict) or rule.get('kind') not in ('exact', 'number', 'json', 'choice', 'blanks'):
        return None
    try:
        return validate(rule)
    except (ApiError, ValueError, TypeError):
        return None


def capable(question):
    if question['type'] in ('generated', 'scenario'):
        return True
    if declarative(question):
        return True
    if question.get('exercise'):
        from .hands_on import program_contract
        return bool(program_contract(question))
    return False


def _json_equal(left, right):
    # JSON numbers compare by value; booleans stay a separate type.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float, Decimal)) and isinstance(right, (int, float, Decimal)):
        a, b = Decimal(str(left)), Decimal(str(right))
        return a.is_finite() and b.is_finite() and a == b
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return left == right


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('ambiguous duplicate JSON key')
        value[key] = item
    return value


def _bounded_number(value):
    parts = value.as_tuple()
    return value.is_finite() and len(parts.digits) <= 10000 and abs(parts.exponent) <= 10000


def grade(question, answer):
    rule = declarative(question)
    if not rule:
        return None
    passed = False
    if not isinstance(answer, str) or len(answer) > 100000:
        return {'passed': False, 'method': '自动判分', 'stage': 'answer_checked',
                'message': '答案需要是不超过 100000 字符的文本。'}
    try:
        if rule['kind'] == 'exact':
            passed = answer.strip() in [x.strip() for x in rule['accepted']]
        elif rule['kind'] == 'choice':
            raw = answer.strip()
            value = json.loads(raw) if raw.startswith(('[', '"')) else raw
            selected = [value] if isinstance(value, str) else value
            if isinstance(selected, list) and all(isinstance(x, str) for x in selected):
                passed = (len(selected) == len(set(selected)) and set(selected) <= set(rule['options'])
                          and (rule['multiple'] or len(selected) == 1)
                          and set(selected) == set(rule['accepted']))
        elif rule['kind'] == 'blanks':
            value = json.loads(answer, object_pairs_hook=_unique_object)
            if isinstance(value, dict) and set(value) == {field['id'] for field in rule['fields']}:
                passed = all(isinstance(value[field['id']], str)
                             and value[field['id']].strip() in {x.strip() for x in field['accepted']}
                             for field in rule['fields'])
        elif rule['kind'] == 'number':
            value = Decimal(answer.strip())
            if _bounded_number(value):
                expected, tolerance = Decimal(rule['expected']), Decimal(rule['tolerance'])
                # Enough precision for exact subtraction, including long fractional
                # answers; the process-wide Decimal context must not round a fail
                # into a pass at a tolerance boundary. Exponents are bounded above.
                values = (value, expected, tolerance)
                precision = max(v.adjusted() for v in values) - min(v.as_tuple().exponent for v in values) + 3
                with localcontext() as context:
                    context.prec = max(28, precision)
                    passed = abs(value - expected) <= tolerance
        else:
            def reject(value):
                raise ValueError('non-finite JSON')
            value = json.loads(answer, parse_constant=reject, parse_float=Decimal, object_pairs_hook=_unique_object)
            passed = _json_equal(value, rule['expected'])
    except (ValueError, TypeError, DecimalException, RecursionError):
        pass
    return {'passed': bool(passed), 'method': '自动判分', 'stage': 'answer_checked',
            'message': '答案符合本题判题规则。' if passed else '答案不符合本题判题规则，请对照参考答案检查。'}
