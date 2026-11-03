"""Presentation hierarchy with one primary placement per question."""
import hashlib
from collections import Counter
from .catalog import modules
from .formats import classify

LEVELS = ["入门", "简单", "进阶", "综合", "高级", "项目挑战"]
GROUPS = [
    ("systems", "系统与网络基础", ["basics", "linux", "permissions", "process", "disk", "network"]),
    ("development", "运维开发", ["shell", "python", "go", "git", "software_engineering"]),
    ("containers", "容器与 Kubernetes", ["docker", "kubernetes", "helm", "operator"]),
    ("traffic", "网关与流量管理", ["nginx", "envoy", "istio"]),
    ("data", "数据库、中间件与存储", ["mysql", "redis", "kafka", "clickhouse", "tidb", "ceph", "mongodb", "data_basics"]),
    ("observability", "监控、日志与告警", ["prometheus", "node_exporter", "alertmanager", "grafana", "zabbix", "elk", "loki", "observability_basics"]),
    ("delivery", "自动化与持续交付", ["ansible", "terraform", "cicd", "puppet"]),
    ("cloud", "云平台与云原生", ["aws", "azure", "gcp", "aliyun", "openstack", "cloud_basics"]),
]
SUBMODULE = {"dockerfile": "docker", "nodeport": "kubernetes"}
GROUP_FOR = {sub: group for group, _, subs in GROUPS for sub in subs}
SPECIAL = {"project-observability": "prometheus", "project-delivery": "cicd", "project-latency": "network"}
SCENARIO = {"disk": "disk", "service": "nodeport", "docker": "docker", "monitor": "prometheus", "alert": "alertmanager", "permissions": "permissions", "redis": "redis", "kafka": "kafka", "aws": "aws", "azure": "azure", "gcp": "gcp"}
DEFAULT_TOPICS = {
    "basics": "环境识别与访问链路", "linux": "文件与终端操作", "permissions": "访问控制与权限排查",
    "process": "进程生命周期与服务管理", "disk": "文件系统容量与恢复", "network": "网络分层与连接诊断",
    "shell": "脚本输入输出与错误处理", "python": "运维工具与日志处理", "go": "并发任务与资源管理",
    "git": "版本跟踪与协作", "docker": "容器运行与资源", "dockerfile": "Dockerfile 与镜像构建",
    "kubernetes": "工作负载与健康检查", "nodeport": "NodePort 与服务访问", "helm": "模板与发布管理",
    "operator": "控制器协调与生命周期", "nginx": "反向代理与请求诊断", "envoy": "上游连接与流量治理", "istio": "服务网格流量与安全治理",
    "mysql": "SQL、事务与恢复", "redis": "缓存访问与持久化", "kafka": "分区、消费与位点",
    "clickhouse": "写入组织与查询优化", "tidb": "分布式查询与存储调度", "ceph": "分布式存储与故障恢复",
    "elk": "日志采集与索引", "loki": "日志流与查询", "prometheus": "指标采集与查询",
    "node_exporter": "主机指标与采集范围", "alertmanager": "告警路由与通知", "grafana": "查询与可视化",
    "zabbix": "监控采集与告警链路", "ansible": "幂等配置与批量运维", "terraform": "基础设施状态管理",
    "cicd": "制品交付与发布验证", "aws": "身份、网络与云资源", "azure": "身份、网络与云资源",
    "gcp": "身份、网络与云资源", "aliyun": "云资源与托管集群",
    "mongodb": "文档模型与查询",
    "data_basics": "数据模型与治理", "openstack": "私有云组件与诊断",
    "cloud_basics": "服务模型与责任边界", "puppet": "声明式配置与数据分层",
    "software_engineering": "设计、测试与系统演进",
    "observability_basics": "信号、目标与可靠性",
}


def placement(q):
    known = {m["id"]: m["name"] for m in modules()}
    primary = q.get("module", "")
    if primary not in known:
        primary = SPECIAL.get(q["id"], "")
    if not primary and q["id"].startswith("scenario:"):
        primary = SCENARIO.get(q["id"].split(":")[1], "")
    if not primary:
        aliases = {name: ident for ident, name in known.items()}
        aliases.update({"Linux": "linux", "网络": "network", "权限": "permissions", "安全": "permissions", "Docker": "docker", "AWS": "aws", "Azure": "azure", "GCP": "gcp", "阿里云": "aliyun"})
        primary = aliases.get(q.get("category"), "")
    sub = SUBMODULE.get(primary, primary)
    topic_name = q.get("topic") or DEFAULT_TOPICS.get(primary, "待分类")
    topic = primary + ":" + hashlib.sha256(topic_name.encode()).hexdigest()[:12]
    return {"primary_module": primary, "group": GROUP_FOR.get(sub, ""), "submodule": sub, "topic_id": topic, "topic": topic_name}


def matches(q, filters):
    p = placement(q)
    return all(not filters.get(key) or filters[key] == p[key] for key in ("group", "submodule", "topic_id", "primary_module"))


def build(questions):
    names = {m["id"]: m["name"] for m in modules()}
    names.update(docker="Docker", kubernetes="Kubernetes", python="Python", go="Go", aws="AWS", azure="Azure", gcp="GCP")
    unique = {q["id"]: q for q in questions if q.get("review_status") == "reviewed"}
    buckets, unassigned = {}, []
    for q in unique.values():
        p = placement(q)
        if not p["group"]:
            unassigned.append(q["id"])
            continue
        key = (p["group"], p["submodule"], p["topic_id"])
        bucket = buckets.setdefault(key, {"id": p["topic_id"], "name": p["topic"], "primary_module": p["primary_module"], "levels": {}})
        bucket["levels"].setdefault(int(q.get("level", 1)), []).append({"id": q["id"], "title": q["title"], "type": q["type"], "question_format": classify(q), "learning": q.get('learning', {'completion':'not_started','mastery':'unrated'})})
    groups = []
    for gid, name, subs in GROUPS:
        children = []
        for sub in subs:
            topics = []
            for (group, sid, _), bucket in buckets.items():
                if (group, sid) != (gid, sub):
                    continue
                levels = [{"level": level, "name": LEVELS[level], "count": len(items), "items": sorted(items, key=lambda q: (q["title"], q["id"]))} for level, items in sorted(bucket["levels"].items())]
                topics.append({**bucket, "levels": levels, "count": sum(v["count"] for v in levels)})
            children.append({"id": sub, "name": names[sub], "topics": sorted(topics, key=lambda t: t["name"]), "count": sum(t["count"] for t in topics)})
        groups.append({"id": gid, "name": name, "children": children, "count": sum(c["count"] for c in children)})
    return {"groups": groups, "count": sum(g["count"] for g in groups), "unassigned_count": len(unassigned), "unassigned_ids": unassigned,
            "primary_counts": dict(Counter(placement(q)["primary_module"] for q in unique.values() if placement(q)["primary_module"]))}
