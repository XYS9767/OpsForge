"""The auth domain: owned state transitions and API handlers."""
import hashlib
import hmac
import os
import secrets
import time
import ipaddress
import socket
from core.errors import ApiError


class AuthService:
    def authenticate(self, token):
        if not token:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.db("auth") as db:
            row = db.execute("SELECT * FROM sessions WHERE token=? AND expires>?", (digest, time.time())).fetchone()
        return dict(row) if row else None

    def synchronize_password(self):
        # Password rotation, including the first upgrade, revokes old sessions.
        with self.db('auth') as db:
            row = db.execute("SELECT value FROM auth_settings WHERE key='password_salt'").fetchone()
            salt = row[0] if row else secrets.token_hex(32)
            fingerprint = hashlib.scrypt(self.password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
            old = db.execute("SELECT value FROM auth_settings WHERE key='password_fingerprint'").fetchone()
            if not old or not hmac.compare_digest(old[0], fingerprint):
                db.execute('DELETE FROM sessions')
                for key, value in [('password_salt', salt), ('password_fingerprint', fingerprint)]:
                    db.execute('INSERT INTO auth_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

    def login_address(self, env):
        """Trust only configured proxy peers, never a caller-supplied forwarding chain."""
        peer = env.get("REMOTE_ADDR", "")
        try:
            address = ipaddress.ip_address(peer)
        except ValueError:
            return peer
        trusted = any(address in ipaddress.ip_network(cidr.strip())
                      for cidr in os.getenv("TRUSTED_PROXY_CIDRS", "").split(',') if cidr.strip())
        # A headless Service resolves to the actual frontend Pod IPs, not all private IPs.
        hosts = tuple(h.strip() for h in os.getenv("TRUSTED_PROXY_HOSTS", "").split(',') if h.strip())
        if hosts:
            cached = getattr(self, '_proxy_addresses', None)
            if not cached or cached[0] != hosts or time.monotonic() >= cached[1]:
                peers = set()
                for host in hosts:
                    try:
                        peers.update(ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, None))
                    except OSError:
                        # Fail closed; an unresolved proxy must not make all peers trusted.
                        continue
                cached = self._proxy_addresses = (hosts, time.monotonic() + 30, peers)
            trusted = trusted or address in cached[2]
        if trusted:
            try:
                return str(ipaddress.ip_address(env.get("HTTP_X_REAL_IP", "")))
            except ValueError:
                pass
        return str(address)

    def route_auth(self, method, path, args, body, env, user):
        if method == "POST" and path == "/api/login":
            address = self.login_address(env)
            now = time.time()
            with self.lock:
                recent = [t for t in self.limits.get(address, []) if now - t < 300]
                if len(recent) >= 10:
                    raise ApiError("尝试过于频繁，请 5 分钟后重试", 429)
                if not hmac.compare_digest(str(body.get("password", "")).encode(), self.password.encode()):
                    self.limits[address] = recent + [now]
                    raise ApiError("密码不正确", 401)
                self.limits.pop(address, None)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            with self.db("auth") as db:
                db.execute("DELETE FROM sessions WHERE expires<?", (now,))
                db.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), csrf, now + 28800))
            secure = "; Secure" if os.getenv("COOKIE_SECURE") == "true" else ""
            return {"ok": True, "csrf": csrf}, [("Set-Cookie", f"opsforge={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800{secure}")]

        if method == "POST" and path == "/api/logout":
            with self.db("auth") as db:
                db.execute("DELETE FROM sessions WHERE token=?", (user["token"],))
            return {"ok": True}, [("Set-Cookie", "opsforge=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")]

        return None
