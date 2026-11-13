"""Independently deployed domain processes plus a database-free public gateway."""
import json
import os
import threading
import traceback
from http import HTTPStatus
from pathlib import Path
from app import App
from auth.service import AuthService
from bank.service import BankService
from learning.service import LearningService
from exams.service import ExamService
from labs.service import LabService
from labs.runtime import Runtime
from core.database import Databases
from core.errors import ApiError
from core.text import validate_payload_text
from core.rpc import METHODS, OWNER, MAX_BYTES, Peers, authenticated, secret, serializable


def route_owner(path):
    if path in ("/api/login", "/api/logout"):
        return "auth"
    if path.startswith("/api/exam/"):
        return "exams"
    if path == "/api/lab" or path.startswith("/api/lab/"):
        return "labs"
    if path in ("/api/notes", "/api/note", "/api/practice/restart", "/api/draft", "/api/favorite", "/api/submit", "/api/progress", "/api/attempt", "/api/attempt/answer", "/api/attempt/rating"):
        return "learning"
    if path in ("/api/bootstrap", "/api/curriculum", "/api/study", "/api/study/export", "/api/question", "/api/question/edit", "/api/questions", "/api/random", "/api/answer", "/api/hint", "/api/export", "/api/import", "/api/import/preview", "/api/review", "/api/revisions"):
        return "bank"
    raise ApiError("接口不存在", 404)


class Domain:
    domain = ""

    def __init__(self, data_dir=None, password=None, peers=None):
        self.peers = peers or Peers()
        self.key = self.peers.key
        self.lock = threading.RLock()
        self.lab_operation = threading.Lock()
        self.data_dir = Path(data_dir or os.getenv("DATA_DIR", "/data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database = Databases(self.data_dir, (self.domain,))
        self.database.migrate()
        if self.domain == "auth":
            self.password = password or os.getenv("OPSFORGE_PASSWORD", "")
            if len(self.password) < 12:
                raise RuntimeError("OPSFORGE_PASSWORD 必须至少12个字符")
            self.limits = {}
            self.synchronize_password()
        if self.domain == "bank":
            self.seed()
        if self.domain == "labs":
            self.runtime = Runtime(self.load_runtime_state, self.save_runtime_state)

    def db(self, domain):
        if domain != self.domain:
            raise RuntimeError("跨服务数据库访问被拒绝")
        return self.database.transaction(domain)

    def __getattr__(self, method):
        owner = OWNER.get(method)
        if owner and owner != self.domain:
            return lambda *args, **kwargs: self.peers.call(owner, method, *args, **kwargs)
        raise AttributeError(method)

    @staticmethod
    def public(question):
        return BankService.public(question)

    def health(self):
        try:
            with self.db(self.domain) as db:
                db.execute("SELECT 1").fetchone()
        except Exception as exc:
            raise ApiError("数据库暂不可用", 503) from exc
        return {"status": "ok", "service": self.domain, "database": self.database.kind}

    def dispatch(self, method, path, args, body, env, user):
        if route_owner(path) != self.domain:
            raise ApiError("此接口不属于当前服务", 404)
        if not user and path != "/api/login":
            raise ApiError("请先登录", 401)
        result = getattr(self, "route_" + self.domain)(method, path, args, body, env, user)
        if result is None:
            raise ApiError("接口不存在", 404)
        return result

    def __call__(self, env, start_response):
        status = 200
        try:
            path = env.get("PATH_INFO", "")
            if env["REQUEST_METHOD"] == "GET" and path == "/api/live":
                result = {"status": "ok", "service": self.domain}
            elif env["REQUEST_METHOD"] == "GET" and path == "/api/health":
                result = self.health()
            else:
                if not authenticated(env, self.key):
                    raise ApiError("内部服务认证失败", 403)
                if env["REQUEST_METHOD"] != "POST" or path != "/internal":
                    raise ApiError("接口不存在", 404)
                if not env.get("CONTENT_TYPE", "").startswith("application/json"):
                    raise ApiError("需要JSON请求", 415)
                length = int(env.get("CONTENT_LENGTH") or 0)
                if not 0 < length <= MAX_BYTES:
                    raise ApiError("请求大小不符合要求", 413)
                request = json.loads(env["wsgi.input"].read(length))
                validate_payload_text(request)
                operation = request["operation"]
                if operation not in METHODS[self.domain] | {"dispatch", "health"}:
                    raise ApiError("未开放的内部操作", 403)
                args, kwargs = request.get("args", []), request.get("kwargs", {})
                if not isinstance(args, list) or not isinstance(kwargs, dict):
                    raise ApiError("参数格式错误")
                # The single gateway orders public state transitions. Internal reads
                # must remain reentrant (exam -> learning -> exam) without lock cycles.
                result = {"result": getattr(self, operation)(*args, **kwargs)}
        except ApiError as exc:
            status, result = exc.status, {"error": str(exc)}
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            status, result = 400, {"error": "内部请求格式错误"}
        except Exception:
            traceback.print_exc()
            status, result = 500, {"error": "服务执行失败，请检查对应服务日志"}
        payload = json.dumps(result, ensure_ascii=False, default=serializable).encode()
        start_response(f"{status} {HTTPStatus(status).phrase}", [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"), ("Content-Length", str(len(payload)))])
        return [payload]


class AuthDomain(AuthService, Domain):
    domain = "auth"


class BankDomain(BankService, Domain):
    domain = "bank"


class LearningDomain(LearningService, Domain):
    domain = "learning"


class ExamDomain(ExamService, Domain):
    domain = "exams"


class LabDomain(LabService, Domain):
    domain = "labs"


class Gateway(App):
    def __init__(self, peers=None):
        # No database, domain initializers, password, or Kubernetes client here.
        self.peers = peers or Peers()
        self.lock = threading.RLock()
        self.serialize_submissions = True

    def authenticate(self, token):
        return self.peers.call("auth", "authenticate", token)

    def route(self, method, path, args, body, env, user):
        if method == "GET" and path == "/api/live":
            return {"status": "ok", "service": "gateway"}, []
        if method == "GET" and path == "/api/health":
            for domain in METHODS:
                self.peers.call(domain, "health")
            return {"status": "ok", "service": "gateway", "domains": list(METHODS)}, []
        if not user and path != "/api/login":
            raise ApiError("请先登录", 401)
        clean_env = {k: env.get(k, "") for k in ("REMOTE_ADDR", "HTTP_HOST", "HTTP_X_REAL_IP")}
        return self.peers.call(route_owner(path), "dispatch", method, path, args, body, clean_env, user)


SERVICES = {"auth": AuthDomain, "bank": BankDomain, "learning": LearningDomain, "exams": ExamDomain, "labs": LabDomain, "gateway": Gateway}


def main():
    domain = os.getenv("OPSFORGE_SERVICE", "gateway")
    if domain not in SERVICES:
        raise RuntimeError("Unknown OPSFORGE_SERVICE")
    application = SERVICES[domain]()
    from waitress import serve
    serve(application, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8081")), threads=16, max_request_body_size=MAX_BYTES, channel_timeout=180)


if __name__ == "__main__":
    main()
