"""Consistent SQLite backup, runnable inside or outside the backend container."""
import argparse
from pathlib import Path
import sqlite3
from contextlib import closing
import os
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
if args.source.resolve() == args.destination.resolve():
    raise SystemExit("备份目标不能与源数据库相同")
if args.destination.exists() or args.destination.is_symlink():
    raise SystemExit("目标文件已存在，请换一个备份文件名")
args.destination.parent.mkdir(parents=True, exist_ok=True)
temporary = None
try:
    with closing(sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        fd, name = tempfile.mkstemp(prefix='.' + args.destination.name + '.', suffix='.part', dir=args.destination.parent)
        os.close(fd)
        temporary = Path(name)
        with closing(sqlite3.connect(temporary)) as dest:
            source.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError('备份数据库完整性检查失败，未生成正式备份')
        with temporary.open('r+b') as completed:
            os.fsync(completed.fileno())
        # Publish atomically without replacing a target created by another process.
        if os.name == 'nt':
            os.rename(temporary, args.destination)
        else:
            os.link(temporary, args.destination)
finally:
    if temporary is not None:
        temporary.unlink(missing_ok=True)
print("Backup complete")
