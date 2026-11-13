"""Publication gate shared by bank browsing, random generation and exams."""
from core.errors import ApiError


def normalize(question):
    question.setdefault("version", 1)
    # Keep cross-module scenarios discoverable from every related module.
    from .catalog import MODULES
    aliases = {m[1]: m[0] for m in MODULES}
    aliases.update({"Linux": "linux", "网络": "network", "权限": "permissions", "安全": "permissions",
                    "Docker": "docker", "Python": "python", "Go": "go", "CI/CD": "cicd",
                    "AWS": "aws", "Azure": "azure", "GCP": "gcp"})
    related = {aliases[tag] for tag in [question["category"], *question.get("tags", [])] if tag in aliases}
    if question.get("module"):
        related.add(question["module"])
    if question.get("state", {}).get("kind") == "disk":
        related.add("disk")
    question["related_modules"] = sorted(related)
    if "review_status" not in question:
        external = question["id"].startswith(("src-", "custom-"))
        question["review_status"] = "pending" if external else "reviewed"
        question["review_note"] = (
            "外部资料尚未审校，不参加练习或考试。"
            if external else "本版编写内容经检查；自动题另有规则测试，开放题需对照要点。"
        )
    return question


def require_published(question):
    if normalize(question)["review_status"] != "reviewed":
        raise ApiError("此题待审校，仅可在审校区查看；核实答案并发布后才能练习或组卷", 409)

