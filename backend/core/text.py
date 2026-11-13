"""Text accepted by both SQLite and PostgreSQL, without altering user input."""
from .errors import ApiError


def validate_payload_text(payload):
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if '\0' in value:
                raise ApiError('输入含不支持的空字符 U+0000，请移除后重试；未保存内容请保留', 400)
            try:
                value.encode('utf-8')
            except UnicodeEncodeError as exc:
                raise ApiError('输入含无效 Unicode 字符，请检查后重试；未保存内容请保留', 400) from exc
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
