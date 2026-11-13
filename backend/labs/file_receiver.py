"""Standalone receiver sent to the workspace Python interpreter over exec."""
import json
import os
from pathlib import Path
import posixpath
import shutil
import sys
import tempfile


def synchronize(root, files):
    root = Path(root).resolve()
    manifest = '.opsforge-sync.json'
    def target(name):
        if not isinstance(name, str) or not name or name.startswith('/') or '\\' in name or '..' in name.split('/'):
            raise ValueError('Invalid workspace path')
        path = root / name
        if path == root or not path.resolve().is_relative_to(root):
            raise ValueError('File path escapes workspace')
        for part in [path, *path.parents]:
            if part == root:
                break
            if part.is_symlink():
                raise ValueError('Cannot synchronize through symbolic links')
        return path
    names = {posixpath.normpath(name): value for name, value in files.items()}
    if len(names) != len(files) or manifest in names:
        raise ValueError('Duplicate or reserved file name')
    if any('/'.join(name.split('/')[:i]) in names for name in names for i in range(1, len(name.split('/')))):
        raise ValueError('File/directory collision')
    metadata = target(manifest)
    previous = json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else []
    if not isinstance(previous, list) or any(not isinstance(n, str) or n == manifest for n in previous):
        raise ValueError('Invalid synchronization manifest')
    affected = sorted(set(names) | set(previous)) + [manifest]
    paths = {name: target(name) for name in affected}
    for path in paths.values():
        if path.exists() and not path.is_file():
            raise ValueError('Target is not a regular file')
        if any(p.exists() and not p.is_dir() for p in path.parents if p != root):
            raise ValueError('Parent is not a directory')
    # Stage everything before touching user files; rollback a failed replacement.
    stage = Path(tempfile.mkdtemp(prefix='.opsforge-stage-', dir=root))
    retain_backup = False
    try:
        replacements = {**names, manifest: json.dumps(sorted(names))}
        staged = {}
        for i, (name, value) in enumerate(replacements.items()):
            path = stage / ('new-' + str(i))
            path.write_text(value, encoding='utf-8', newline='')
            if paths[name].exists():
                path.chmod(paths[name].stat().st_mode & 0o777)
            staged[name] = path
        undo = []
        try:
            for i, name in enumerate(affected):
                path = paths[name]
                path.parent.mkdir(parents=True, exist_ok=True)
                original = stage / ('old-' + str(i)) if path.exists() else None
                if original:
                    os.replace(path, original)
                undo.append((path, original))
                if name in staged:
                    os.replace(staged[name], path)
        except Exception:
            failures = []
            for path, original in reversed(undo):
                try:
                    if path.exists():
                        path.unlink()
                    if original:
                        os.replace(original, path)
                except OSError as error:
                    failures.append(str(error))
            if failures:
                retain_backup = True
                raise RuntimeError('Rollback incomplete; preserved backups in ' + str(stage))
            raise
    finally:
        if not retain_backup:
            shutil.rmtree(stage)
    return len(names)


if __name__ == '__main__':
    data = json.loads(sys.stdin.read(int(sys.argv[1])))
    print('Uploaded', synchronize('/workspace', data), 'files')
