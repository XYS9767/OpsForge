"""Transactional storage. PostgreSQL in Kubernetes; SQLite for a local preview."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3


class Row(dict):
    """Named columns and positional reads without driver-specific service code."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def pg_row_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, values))


class Connection:
    def __init__(self, raw, kind):
        self.raw, self.kind = raw, kind

    def execute(self, sql, params=()):
        # Domain SQL is static, parameterized, and never contains literal '?'.
        if self.kind == "postgresql":
            sql = sql.replace("?", "%s")
        return self.raw.execute(sql, params)


DOMAINS = ("bank", "learning", "labs", "exams", "auth")


class Database:
    def __init__(self, sqlite_path, domain, dsn=""):
        self.path = sqlite_path
        self.domain = domain
        self.dsn = dsn
        self.kind = "postgresql" if self.dsn else "sqlite"
        if self.dsn and not self.dsn.startswith(("postgresql://", "postgres://")):
            raise RuntimeError(f"{domain.upper()}_DATABASE_URL 需要使用 PostgreSQL 连接地址")
        if os.getenv("REQUIRE_POSTGRES") == "true" and not self.dsn:
            raise RuntimeError(f"正式部署必须提供 {domain.upper()}_DATABASE_URL；拒绝回退到临时数据库")

    @contextmanager
    def transaction(self):
        if self.kind == "postgresql":
            import psycopg
            from psycopg.types.json import set_json_loads
            raw = psycopg.connect(self.dsn, row_factory=pg_row_factory, connect_timeout=10)
            # Services consume JSON text identically across the two drivers.
            set_json_loads(lambda b: b.decode("utf-8") if isinstance(b, bytes) else str(b), raw)
        else:
            raw = sqlite3.connect(self.path, timeout=30)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA foreign_keys=ON")
        try:
            with raw:
                yield Connection(raw, self.kind)
        finally:
            raw.close()

    def migrate(self):
        if self.kind == "sqlite":
            conn = sqlite3.connect(self.path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            finally:
                conn.close()
        with self.transaction() as db:
            if self.kind == "postgresql":
                db.execute("SELECT pg_advisory_xact_lock(719104001)")
            db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY)")
            applied = {r[0] for r in db.execute("SELECT version FROM schema_migrations")}
            folder = Path(__file__).with_name("migrations") / self.domain / self.kind
            for file in sorted(folder.glob("*.sql")):
                version = int(file.stem.split("_")[0])
                if version in applied:
                    continue
                for statement in file.read_text(encoding="utf-8").split(";"):
                    if statement.strip():
                        db.execute(statement.strip())
                db.execute("INSERT INTO schema_migrations VALUES(?)", (version,))


class Databases:
    """A connection boundary per business domain, with independent migrations."""
    def __init__(self, folder, domains=DOMAINS):
        if not domains or any(name not in DOMAINS for name in domains):
            raise ValueError("Unknown database domain")
        self.stores = {
            name: Database(folder / f"{name}.sqlite3", name, os.getenv(f"{name.upper()}_DATABASE_URL", "").strip())
            for name in domains
        }
        kinds = {store.kind for store in self.stores.values()}
        if len(kinds) != 1:
            raise RuntimeError("请完整设置五个独立数据库连接；不支持部分 PostgreSQL、部分临时数据库")
        self.kind = next(iter(kinds))
        if self.kind == "postgresql":
            from urllib.parse import urlsplit
            identities = [(urlsplit(s.dsn).hostname, urlsplit(s.dsn).port or 5432,
                           urlsplit(s.dsn).path) for s in self.stores.values()]
            if len(set(identities)) != len(domains):
                raise RuntimeError("五个业务模块必须使用不同数据库，不能指向同一库")

    def migrate(self):
        for store in self.stores.values():
            store.migrate()

    def transaction(self, domain):
        return self.stores[domain].transaction()

