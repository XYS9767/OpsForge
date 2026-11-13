"""Import the user's archive as data. Never execute archive contents."""
import argparse
import hashlib
import html
import json
import re
import zipfile
import posixpath
from urllib.parse import quote
from pathlib import Path
if __package__:
    from .course_scope import removed
else:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from bank.course_scope import removed

TOPICS = {
    "linux": "Linux", "containers": "Docker / 容器", "kubernetes": "Kubernetes",
    "git": "Git", "shell": "Shell", "ansible": "Ansible", "terraform": "Terraform",
    "cicd": "CI/CD", "aws": "AWS", "azure": "Azure", "gcp": "GCP",
    "devops": "DevOps", "dns": "DNS", "security": "安全", "databases": "数据库",
    "observability": "可观测性", "grafana": "Grafana", "sre": "SRE",
    "cloud": "云计算", "software_development": "软件开发", "soft_skills": "软技能",
    "argo": "Argo", "openshift": "OpenShift", "kafka": "Kafka",
    "chaos_engineering": "混沌工程", "circleci": "CI/CD", "zuul": "CI/CD",
    "datadog": "可观测性",
}


def clean(text):
    text = text.replace("\r", "")
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?:b|p|details|summary|strong|em|ul|ol|li|div|span|a|img|pre|h[1-6])\b[^>]*>",
                  "", text, flags=re.I)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def blocks(text):
    """Balance nested details so inner answers cannot be paired with outer questions."""
    stack = []
    for m in re.finditer(r"</?details\b[^>]*>", text, re.I):
        if m.group().lower().startswith("</"):
            if stack:
                start = stack.pop()
                yield start, text[start:m.start()]
        else:
            stack.append(m.end())


def own_content(block):
    """Exclude nested question blocks from a parent's own question/answer pair."""
    depth, cursor, pieces = 0, 0, []
    for match in re.finditer(r"</?details\b[^>]*>", block, re.I):
        closing = match.group().lower().startswith("</")
        if not closing:
            if depth == 0:
                pieces.append(block[cursor:match.start()])
            depth += 1
        else:
            depth = max(0, depth - 1)
            if depth == 0:
                cursor = match.end()
    if depth == 0:
        pieces.append(block[cursor:])
    return "".join(pieces)


def rewrite_images(text, source):
    def target(path):
        path = html.unescape(path.strip())
        if path.startswith(("https://", "http://")):
            return path
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
        if resolved.startswith("images/"):
            return "/source-assets/" + quote(resolved, safe="/")
        return path
    text = re.sub(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>',
                  lambda m: "![原题配图](" + target(m[1]) + ")", text, flags=re.I)
    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", lambda m: "![" + m[1] + "](" + (m[2] if m[2].startswith("/source-assets/") else target(m[2])) + ")", text)


def build(archive, dest):
    dest = Path(dest)
    (dest / "data").mkdir(parents=True, exist_ok=True)
    source_dir = dest / "sources"
    questions, seen, raw_count = [], {}, 0
    with zipfile.ZipFile(archive) as z:
        roots = [x.split("/")[0] for x in z.namelist() if x.endswith("/README-zh_CN.md")]
        if not roots:
            raise ValueError("没有找到 README-zh_CN.md")
        root = roots[0] + "/"
        names = [root + "README-zh_CN.md", root + "README.md"]
        names += sorted(n for n in z.namelist() if n.startswith(root + "topics/") and
                        (n.endswith("/README.md") or n.endswith("/CKA.md")))
        names += sorted(n for n in z.namelist() if n.startswith(root + "certificates/") and n.endswith(".md"))
        asset_root = dest.parent / "frontend" / "source-assets"
        for name in z.namelist():
            if name.startswith(root + "images/") and not name.endswith("/"):
                asset = asset_root / name[len(root):]
                if asset.resolve().is_relative_to(asset_root.resolve()):
                    asset.parent.mkdir(parents=True, exist_ok=True)
                    asset.write_bytes(z.read(name))
        for name in names:
            rel = name[len(root):]
            if rel.startswith("topics/perl/"):
                continue
            path = source_dir / rel
            if not path.resolve().is_relative_to(source_dir.resolve()):
                continue
            text = z.read(name).decode("utf-8-sig").replace("\r", "")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            for start, block in sorted(blocks(text)):
                block = own_content(block)
                m = re.search(r"<summary[^>]*>(.*?)</summary>", block, re.S | re.I)
                if not m:
                    continue
                raw_count += 1
                title, answer = clean(rewrite_images(m[1], rel)), clean(rewrite_images(block[m.end():], rel))
                if not title:
                    continue
                headings = re.findall(r"^##\s+(.+)$", text[:start], re.M)
                category = clean(headings[-1]) if headings else "综合"
                if rel.startswith("topics/"):
                    slug = rel.split("/")[1]
                    category = TOPICS.get(slug, slug)
                elif rel.startswith("certificates/"):
                    category = "认证 · " + rel.split("/")[-1].replace(".md", "")
                category = {"Docker": "Docker / 容器", "Shell 脚本": "Shell", "云": "云计算",
                            "安全": "安全", "网络": "网络"}.get(category, category)
                subsections = re.findall(r"^#{3,6}\s+(.+)$", text[:start], re.M)
                sub = clean(subsections[-1]) if subsections else ""
                difficulty = "进阶" if any(x in sub.lower() for x in ["高级", "advanced", "内部", "场景", "故障"]) else "入门"
                fingerprint = category.casefold() + "|" + re.sub(r"[\s`？?。，,.：:]", "", title).casefold()
                if fingerprint in seen:
                    existing = questions[seen[fingerprint]]
                    existing["sources"].append(rel)
                    if not existing["answer"] and answer:
                        existing.update(answer=answer, source=rel, has_answer=True)
                    continue
                item = {
                    "id": "src-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:16],
                    "title": title, "answer": answer, "category": category,
                    "difficulty": difficulty, "section": sub, "type": "source",
                    "has_answer": bool(answer), "source": rel, "sources": [rel],
                }
                if removed(item):
                    continue
                seen[fingerprint] = len(questions)
                questions.append(item)
        (dest / "data" / "SOURCE-LICENSE.txt").write_bytes(z.read(root + "LICENSE"))
    data = {"questions": questions, "meta": {
        "archive": Path(archive).name, "raw_count": raw_count, "count": len(questions),
        "with_answers": sum(q["has_answer"] for q in questions),
        "categories": len({q["category"] for q in questions}),
        "notice": "用户提供的原始资料，未逐题审校。难度按目录推断；开放题采用对照参考答案自评。",
        "license": "CC BY-NC-ND 3.0", "upstream": "https://github.com/bregman-arie/devops-exercises",
    }}
    (dest / "data" / "bank.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(data["meta"], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--dest", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    build(args.archive, args.dest)
