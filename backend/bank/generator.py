"""Deterministic parameterized exercises with exact grading, independent of source text."""
import ipaddress
import random
import re

TEMPLATES = [
    {"id": "chmod", "name": "文件权限换算", "category": "Linux", "difficulty": "入门"},
    {"id": "subnet", "name": "子网可用主机数", "category": "网络", "difficulty": "入门"},
    {"id": "network", "name": "子网网络地址", "category": "网络", "difficulty": "进阶"},
    {"id": "docker", "name": "容器端口映射", "category": "Docker / 容器", "difficulty": "入门"},
    {"id": "scale", "name": "Deployment 扩容", "category": "Kubernetes", "difficulty": "入门"},
    {"id": "rolling", "name": "滚动更新容量", "category": "Kubernetes", "difficulty": "进阶"},
    {"id": "slo", "name": "SLO 错误预算", "category": "SRE", "difficulty": "进阶"},
    {"id": "requests", "name": "Pod 资源预算", "category": "Kubernetes", "difficulty": "进阶"},
    {"id": "permission", "name": "最小权限选择", "category": "Linux", "difficulty": "入门"},
    {"id": "git", "name": "Git 暂存指定文件", "category": "Git", "difficulty": "入门"},
    {"id": "replicas", "name": "故障后副本缺口", "category": "Kubernetes", "difficulty": "入门"},
    {"id": "pipeline", "name": "流水线并行耗时", "category": "CI/CD", "difficulty": "进阶"},
]


def generate(template, seed):
    rng = random.Random(str(seed))
    meta = next((x for x in TEMPLATES if x["id"] == template), None)
    if meta is None:
        raise ValueError("未知题型")
    answer, options, kind = "", None, "exact"
    if template == "chmod":
        nums = [rng.randint(0, 7) for _ in range(3)]
        perms = ["".join(c if n & b else "-" for c, b in zip("rwx", [4, 2, 1])) for n in nums]
        title = f"文件权限为 {''.join(perms)}，对应的三位八进制权限数字是什么？只填数字。"
        answer = "".join(map(str, nums))
        explanation = "r=4，w=2，x=1。每组三位分别相加：" + "，".join(f"{p}={n}" for p, n in zip(perms, nums)) + "。"
    elif template == "permission":
        target, answer = rng.choice([("所有者可读写，组用户只读，其他人无权限", "640"),
                                    ("所有者可读写执行，组用户可读执行，其他人无权限", "750"),
                                    ("仅所有者可读写，组和其他用户无权限", "600")])
        title = f"为 /lab/config.env 设置权限：{target}。应使用哪个权限数字？"
        options = rng.sample(["600", "640", "644", "750"], 4)
        explanation = "按照所有者、所属组、其他人依次计算 r=4、w=2、x=1。正确权限：" + answer
        kind = "choice"
    elif template == "subnet":
        prefix = rng.randint(24, 29)
        title = f"常规 IPv4 /{prefix} 子网，扣除网络地址和广播地址后，有多少个可用主机地址？只填整数。"
        answer = str(2 ** (32 - prefix) - 2)
        explanation = f"主机位是 {32-prefix} 位，可用数量 2^{32-prefix} − 2 = {answer}。本题不涉及 /31、/32 特例。"
    elif template == "network":
        prefix = rng.choice([20, 22, 24, 25, 26, 27, 28])
        ip = f"10.{rng.randrange(1, 240)}.{rng.randrange(1, 240)}.{rng.randrange(1, 254)}"
        title = f"主机 {ip}/{prefix} 所在子网的网络地址是什么？填写点分十进制地址，不带前缀长度。"
        answer = str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False).network_address)
        explanation = f"将 IP 与 /{prefix} 掩码做按位与，主机位全部清零，得到 {answer}。"
    elif template == "docker":
        host, container = rng.randint(8001, 8999), rng.choice([80, 3000, 5000, 8080])
        title = f"应用在容器内监听 {container}，需从宿主机 {host} 端口访问。docker run 的 -p 参数值应填什么？只填端口对。"
        answer = f"{host}:{container}"
        explanation = f"-p 的顺序是宿主机端口:容器端口，即 -p {answer}。"
    elif template == "scale":
        name, count = rng.choice(["api", "worker", "web"]) + "-" + str(rng.randrange(10, 99)), rng.randrange(2, 10)
        title = f"在当前命名空间将 Deployment {name} 的期望副本数调整为 {count}。填写完整 kubectl scale 命令。"
        answer = f"kubectl scale deployment {name} --replicas={count}"
        kind = "scale"
        explanation = f"{answer}\n修改的是 Deployment 的期望副本数，控制器会据此协调 Pod 数量。"
    elif template == "rolling":
        n, surge = rng.randrange(3, 15), rng.randrange(1, 5)
        title = f"Deployment replicas={n}，maxSurge={surge}（整数），maxUnavailable=0。忽略正在终止的 Pod，滚动更新期间最多允许多少个非终止 Pod？"
        answer = str(n + surge)
        explanation = f"期望副本数 + maxSurge = {n} + {surge} = {answer}。正在终止的 Pod 不包含在本题计数中。"
    elif template == "slo":
        total, percent = rng.choice([10000, 20000, 50000, 100000]), rng.choice([99, 99.5, 99.9])
        budget = round(total * (100 - percent) / 100)
        title = f"按请求成功率计算 SLO：一个统计窗口共 {total:,} 次请求，目标 {percent}%。最多允许多少次失败，仍可达到该目标？"
        answer = str(budget)
        explanation = f"错误预算 = 总请求数 × (1 − SLO) = {total} × (1 − {percent}%) = {budget} 次。"
    elif template == "requests":
        count, cpu = rng.randrange(2, 9), rng.choice([100, 150, 250, 500])
        title = f"有 {count} 个 Pod，每个仅含一个容器，CPU request={cpu}m。忽略系统开销，合计请求多少 millicores？只填数字。"
        answer = str(count * cpu)
        explanation = f"{count} × {cpu}m = {answer}m。1000m = 1 CPU。"
    elif template == "git":
        filename = rng.choice(["deploy.yaml", "app.py", "Dockerfile", "config.yaml"])
        title = f"工作目录中有多个改动，只将 {filename} 加入 Git 暂存区。填写命令，不提交其他文件。"
        answer = f"git add {filename}"
        kind = "git"
        explanation = answer + "\n指定文件路径，避免 git add . 暂存其他改动。"
    elif template == "replicas":
        desired = rng.randrange(3, 15)
        ready = rng.randrange(0, desired)
        title = f"Deployment 期望 {desired} 个副本，目前只有 {ready} 个 Ready。距离期望数量还差多少个 Ready Pod？"
        answer = str(desired-ready)
        explanation = f"{desired} − {ready} = {answer}。Ready 数量与创建出来的总数量可能不同。"
    else:
        build, a, b, deploy = [rng.randrange(2, 15) for _ in range(4)]
        title = f"流水线：构建 {build} 分钟 → 并行执行测试 A（{a} 分钟）和测试 B（{b} 分钟）→ 部署 {deploy} 分钟。无排队和调度开销，最短总耗时多少分钟？"
        answer = str(build + max(a, b) + deploy)
        explanation = f"并行阶段取较长任务耗时：{build} + max({a}, {b}) + {deploy} = {answer} 分钟。"
    return {**meta, "id": f"gen:{template}:{seed}", "template": template, "seed": str(seed),
            "title": title, "answer": answer, "explanation": explanation, "type": "generated",
            "grading": kind, "options": options, "has_answer": True}


def grade(question, value):
    value = value.strip()
    answer = question["answer"]
    if question["grading"] == "scale":
        match = re.fullmatch(r"kubectl\s+scale\s+(?:deployment|deploy|deployments)(?:/|\s+)([\w-]+)\s+--replicas(?:=|\s+)(\d+)", value)
        expected = re.fullmatch(r"kubectl scale deployment ([\w-]+) --replicas=(\d+)", answer)
        return bool(match and match.groups() == expected.groups())
    if question["grading"] == "git":
        return re.sub(r"\s+", " ", value).replace("git add -- ", "git add ") == answer
    return value == answer
