"""External PostgreSQL backup client. Credentials stay out of command arguments."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from deployment_config import load, DOMAINS

def verify(config_path, live_path):
    _, values = load(config_path)
    live = json.loads(Path(live_path).read_text(encoding='utf-8'))
    if live.get('data') != values:
        raise ValueError('本地明文配置与已部署 ConfigMap 不一致，停止备份')

def dump(config_path, domain, destination):
    config, _ = load(config_path)
    if domain not in DOMAINS:
        raise ValueError('Unknown domain')
    pg = config['postgres']; item = pg['databases'][domain]
    env = {k:v for k,v in os.environ.items() if not k.upper().startswith('PG')}
    env.update(PGHOST=pg['host'], PGPORT=str(pg['port']), PGUSER=item['user'], PGPASSWORD=item['password'],
               PGDATABASE=item['name'], PGSSLMODE=pg['sslmode'], PGCONNECT_TIMEOUT='10')
    result = subprocess.run(['pg_dump','--no-password','--format=custom','--no-owner','--no-acl','--file',str(destination)], env=env, capture_output=True)
    if result.returncode != 0 or not Path(destination).is_file() or Path(destination).stat().st_size == 0:
        raise RuntimeError(domain + ' 数据库导出失败，请核对配置、权限、网络和 pg_dump 版本')

if __name__ == '__main__':
    try:
        mode, config = sys.argv[1:3]
        load(config)
        if mode == 'preflight':
            if not shutil.which('pg_dump'):
                raise ValueError('请安装与外部 PostgreSQL 版本兼容的 pg_dump 客户端')
        elif mode == 'verify':
            verify(config,sys.argv[3])
        elif mode == 'dump':
            dump(config,sys.argv[3],sys.argv[4])
        else:
            raise ValueError('Unknown operation')
    except Exception:
        print('外部数据库备份检查或导出失败，请检查配置、连接权限及 pg_dump；未输出凭据。', file=sys.stderr)
        sys.exit(2)
