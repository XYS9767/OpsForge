"""Read-only preflight; databases and roles must already exist externally."""
import sys
from deployment_config import load, DOMAINS

def check(path):
    import psycopg
    _, values = load(path)
    for domain in DOMAINS:
        try:
            with psycopg.connect(values[domain.upper() + '_DATABASE_URL'], connect_timeout=10) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT has_schema_privilege(current_user,'public','USAGE'), has_schema_privilege(current_user,'public','CREATE'), pg_is_in_recovery(), current_setting('transaction_read_only')")
                    row = cursor.fetchone()
                    if not row[0] or not row[1] or row[2] or row[3] != 'off':
                        raise ValueError('Database must be writable and support schema migrations')
            print(domain + ': 外部数据库连接与建表权限检查通过')
        except Exception:
            raise RuntimeError(domain + ': 外部数据库检查失败；请核对网络、TLS、数据库、账号及建表权限') from None

if __name__ == '__main__':
    try:
        check(sys.argv[1])
    except Exception:
        print('数据库预检未全部通过，未修改数据库或集群。请检查外部数据库配置及权限。', file=sys.stderr)
        sys.exit(2)
