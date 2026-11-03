"""Local preview: frontend, gateway and five domain services in separate processes."""
import http.client
import http.server
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import urllib.request
import time

ROOT = Path(__file__).resolve().parent
PORT = int(os.getenv("PREVIEW_PORT", "8080"))
API_PORT = int(os.getenv("PORT", "8081"))


class Proxy(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "frontend"), **kwargs)

    def proxy(self):
        conn = http.client.HTTPConnection("127.0.0.1", API_PORT, timeout=180)
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 <= length <= 20000000:
                self.send_error(413)
                return
            data = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in ["connection", "accept-encoding"]}
            conn.request(self.command, self.path, body=data, headers=headers)
            response = conn.getresponse()
            body = response.read()
            try:
                self.send_response(response.status)
                for k, v in response.getheaders():
                    if k.lower() not in ["server", "date", "connection", "transfer-encoding"]:
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Browser navigation may close a request after the API has replied.
                pass
        finally:
            conn.close()

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.proxy()
        super().do_GET()

    def do_POST(self):
        self.proxy()


if __name__ == "__main__":
    env = os.environ.copy()
    generated = "OPSFORGE_PASSWORD" not in env
    env.setdefault("OPSFORGE_PASSWORD", secrets.token_urlsafe(15))
    env.setdefault("SERVICE_SECRET", secrets.token_urlsafe(40))
    env.update(HOST="127.0.0.1", PORT=str(API_PORT), PYTHONUTF8="1")
    env.setdefault("DATA_DIR", str(ROOT / "backend/storage"))
    domains = ["auth", "bank", "learning", "exams", "labs"]
    for index, domain in enumerate(domains, 1):
        env[domain.upper() + "_SERVICE_URL"] = f"http://127.0.0.1:{API_PORT + index}"
    if generated:
        print("本次访问密码：" + env["OPSFORGE_PASSWORD"], flush=True)
    processes = []
    try:
        import socket
        # Fail before starting children if any requested port is already occupied.
        for port in [PORT, *range(API_PORT, API_PORT + 6)]:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
        if PORT in range(API_PORT, API_PORT + 6):
            raise RuntimeError("PREVIEW_PORT must not overlap the API service ports")
        for index, domain in enumerate(["gateway", *domains]):
            child_env = {**env, "OPSFORGE_SERVICE": domain, "PORT": str(API_PORT + index)}
            if domain != "auth":
                child_env.pop("OPSFORGE_PASSWORD", None)
            for name in domains:
                if name != domain:
                    child_env.pop(name.upper() + "_DATABASE_URL", None)
            processes.append(subprocess.Popen([sys.executable, "-u", str(ROOT / "backend/microservices.py")], env=child_env))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(300):
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("有后端服务启动失败")
            try:
                with opener.open(f"http://127.0.0.1:{API_PORT}/api/health", timeout=1) as response:
                    response.read()
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("后端服务健康检查超时")
        print(f"OpsForge: http://127.0.0.1:{PORT}", flush=True)
        http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Proxy).serve_forever()
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
