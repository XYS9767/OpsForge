"""Explicit internal JSON contracts; no arbitrary method or SQL forwarding."""
import hmac
import http.client
import json
import os
from urllib.parse import urlsplit
from .errors import ApiError

MAX_BYTES = 20000000
METHODS = {
    "auth": {"authenticate"},
    "bank": {"getq", "putq", "filtered", "exam_candidate_ids", "question_labels"},
    "learning": {"draft_details", "favorite_ids", "learning_summary", "learning_states", "learning_export", "learning_export_page", "mark_view", "grade", "record", "exam_attempts"},
    "exams": {"active_exam", "exam_question", "exam_states", "ensure_answer_allowed", "exam_draft", "save_exam_draft"},
    "labs": {"lab", "runtime_status", "grade_real_lab", "grade_artifact_submission", "grade_exam_lab", "exam_lab_revision", "lab_progress", "reset_question_labs"},
}
OWNER = {method: domain for domain, methods in METHODS.items() for method in methods}


def secret():
    value = os.getenv("SERVICE_SECRET", "")
    if len(value) < 32:
        raise RuntimeError("SERVICE_SECRET 必须至少32个字符；服务密钥不能使用登录密码")
    return value


def serializable(value):
    if isinstance(value, (set, tuple)):
        return list(value)
    raise TypeError("Unsupported internal response type")


class Peers:
    def __init__(self, key=None, addresses=None):
        self.key = key or secret()
        self.addresses = addresses or {name: os.getenv(name.upper() + "_SERVICE_URL", f"http://opsforge-{name}:8081") for name in METHODS}

    def call(self, domain, operation, *args, **kwargs):
        if operation not in METHODS.get(domain, set()) | {"dispatch", "health"}:
            raise ApiError("未定义的服务调用", 500)
        url = urlsplit(self.addresses[domain])
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.path not in ("", "/") or url.query or url.fragment:
            raise RuntimeError("服务地址必须为HTTP(S)源地址")
        transport = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        exam_execution = (domain == 'exams' and operation == 'dispatch' and len(args) > 1
                          and args[0] == 'POST' and args[1] in ('/api/exam/check', '/api/exam/finish'))
        timeout = 150 if domain == "labs" or exam_execution else 30
        conn = transport(url.hostname, url.port, timeout=timeout)
        try:
            payload = json.dumps({"operation": operation, "args": args, "kwargs": kwargs}, ensure_ascii=False, default=serializable).encode()
            if len(payload) > MAX_BYTES:
                raise ApiError("内部请求超过20MB", 413)
            conn.request("POST", "/internal", payload, {"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
            response = conn.getresponse()
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ApiError("服务响应超过上限，请缩小查询范围", 502)
            result = json.loads(raw)
            if response.status != 200:
                raise ApiError(result.get("error", "服务请求失败"), response.status)
            return result["result"]
        except (OSError, http.client.HTTPException, json.JSONDecodeError, KeyError) as exc:
            # Mutations are deliberately not retried: callers reconcile explicit IDs.
            raise ApiError(f"{domain} 服务暂不可用，请稍后重试", 503) from exc
        finally:
            conn.close()


def authenticated(env, key):
    return hmac.compare_digest(env.get("HTTP_AUTHORIZATION", ""), "Bearer " + key)
