"""WSGI transport and module composition. Business rules live in domain packages."""
import hashlib
import hmac
import json
import os
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from core.errors import ApiError
from core.text import validate_payload_text
from core.database import Databases
from bank.service import BankService
from learning.service import LearningService
from labs.service import LabService
from labs.runtime import Runtime
from exams.service import ExamService
from auth.service import AuthService

ROOT = Path(__file__).resolve().parent


class App(BankService, LearningService, LabService, ExamService, AuthService):
    def __init__(self, data_dir=None, password=None):
        self.data_dir = Path(data_dir or os.getenv("DATA_DIR", ROOT / "storage"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.password = password or os.getenv("OPSFORGE_PASSWORD", "")
        if len(self.password) < 12:
            raise RuntimeError("OPSFORGE_PASSWORD 必须设置为至少 12 个字符")
        self.lock = threading.RLock()
        self.lab_operation = threading.Lock()
        self.limits = {}
        self.database = Databases(self.data_dir)
        self.database.migrate()
        self.synchronize_password()
        self.runtime = Runtime(self.load_runtime_state, self.save_runtime_state)
        self.seed()


    def db(self, domain):
        return self.database.transaction(domain)

    def route(self, method, path, args, body, env, user):
        if method == "GET" and path == "/api/live":
            return {"status": "ok", "version": "1.0.0"}, []
        if method == "GET" and path == "/api/health":
            try:
                for store in self.database.stores.values():
                    with store.transaction() as db:
                        db.execute("SELECT 1").fetchone()
            except Exception as exc:
                raise ApiError("数据库暂不可用", 503) from exc
            return {"status": "ok", "version": "1.0.0", "database": self.database.kind}, []
        if not user and path != "/api/login":
            raise ApiError("请先登录", 401)
        for handler in (self.route_auth, self.route_bank, self.route_learning, self.route_labs, self.route_exams):
            result = handler(method, path, args, body, env, user)
            if result is not None:
                return result
        raise ApiError("接口不存在", 404)

    def __call__(self, env, start_response):
        headers = [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"),
                   ("X-Content-Type-Options", "nosniff")]
        status = 200
        try:
            method, path = env["REQUEST_METHOD"], env.get("PATH_INFO", "")
            args = {k: v[-1] for k, v in parse_qs(env.get("QUERY_STRING", "")).items()}
            body = {}
            if method == "POST":
                origin = env.get("HTTP_ORIGIN")
                if origin and urlsplit(origin).netloc != env.get("HTTP_HOST"):
                    raise ApiError("跨站请求被拒绝", 403)
                if not env.get("CONTENT_TYPE", "").startswith("application/json"):
                    raise ApiError("请求需要 application/json", 415)
                length = int(env.get("CONTENT_LENGTH") or 0)
                if length > 20000000:
                    raise ApiError("请求超过 20MB", 413)
                body = json.loads(env["wsgi.input"].read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ApiError("请求内容必须是对象")
                validate_payload_text(body)
            user = None
            cookie = SimpleCookie()
            cookie.load(env.get("HTTP_COOKIE", ""))
            probe = method == "GET" and path in ("/api/live", "/api/health")
            if "opsforge" in cookie and not probe:
                user = self.authenticate(cookie["opsforge"].value)
            if method == "POST" and path != "/api/login":
                if not user:
                    raise ApiError("请先登录", 401)
                if not hmac.compare_digest(env.get("HTTP_X_CSRF_TOKEN", ""), user["csrf"]):
                    raise ApiError("请求校验失败，请刷新页面", 403)
            # Personal platform: serialize mutations to keep version changes,
            # exam transitions and simulation updates ordered across HTTP threads.
            if probe or path.startswith("/api/lab") or (path == "/api/submit" and not getattr(self, "serialize_submissions", False)):
                result, extra = self.route(method, path, args, body, env, user)
            else:
                with self.lock:
                    result, extra = self.route(method, path, args, body, env, user)
            headers.extend(extra)
        except ApiError as e:
            status, result = e.status, {"error": str(e)}
        except (ValueError, KeyError, TypeError, IndexError) as e:
            status, result = 400, {"error": "输入或操作不符合要求：" + str(e)[:300]}
        except Exception as e:
            import traceback
            traceback.print_exc()
            status, result = 500, {"error": "服务执行失败，请查看后端日志。实验启动问题请检查镜像、权限、配额和网络。"}
        payload = json.dumps(result, ensure_ascii=False).encode()
        headers.append(("Content-Length", str(len(payload))))
        from http import HTTPStatus
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [payload]



def main():
    application = App()
    host, port = os.getenv("HOST", "0.0.0.0"), int(os.getenv("PORT", "8081"))
    try:
        from waitress import serve
        serve(application, host=host, port=port, threads=12, max_request_body_size=20000000, channel_timeout=180)
    except ImportError:
        from socketserver import ThreadingMixIn
        from wsgiref.simple_server import WSGIServer, make_server
        class ThreadedServer(ThreadingMixIn, WSGIServer):
            daemon_threads = True
        print(f"Development API on http://{host}:{port}", flush=True)
        make_server(host, port, application, server_class=ThreadedServer).serve_forever()


if __name__ == "__main__":
    main()
