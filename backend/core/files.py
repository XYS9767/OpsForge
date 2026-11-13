"""One UTF-8 file contract for imports, drafts and workspace uploads."""
import posixpath

MAX_FILES = 30
MAX_FILE_BYTES = 128000
MAX_TOTAL_BYTES = 500000


def validate_files(files):
    if not isinstance(files, dict) or len(files) > MAX_FILES:
        raise ValueError("文件数量最多 30")
    total, names = 0, set()
    for path, content in files.items():
        if (not isinstance(path, str) or not path or len(path) > 150
                or path.startswith('/') or '\\' in path or '\0' in path
                or '..' in path.split('/') or posixpath.normpath(path) == '.'):
            raise ValueError("文件必须使用工作区内的相对路径，最长 150 字符")
        name = posixpath.normpath(path)
        if name in names:
            raise ValueError("存在指向同一文件的重复路径")
        names.add(name)
        if isinstance(content, str) and '\0' in content:
            raise ValueError("文件不能包含 NUL 字符；二进制素材请使用 Base64 文本")
        if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_FILE_BYTES:
            raise ValueError("单文件最多 128000 字节（UTF-8）")
        total += len(path.encode('utf-8')) + len(content.encode('utf-8'))
    if total > MAX_TOTAL_BYTES:
        raise ValueError("文件内容与路径合计最多 500000 字节（UTF-8）")
    if any('/'.join(name.split('/')[:i]) in names for name in names for i in range(1, len(name.split('/')))):
        raise ValueError("文件路径不能同时作为其他文件的目录")
    if any(name == '.opsforge-sync.json' or name.startswith('.opsforge-sync.json/') for name in names):
        raise ValueError("此路径用于工作区同步记录，请使用其他文件名")
    return files
