"""Stateful learning scenarios. Simulated commands are never executed on the host."""
import copy
import json
import random
import re
import shlex

CATALOG = [
    ("disk", "磁盘告急：从告警到恢复", ["Linux", "Kubernetes", "Loki", "Prometheus"], 3, "disk"),
    ("service", "Service 无法访问", ["Kubernetes", "网络", "NodePort"], 2, "service"),
    ("docker", "容器运行了，页面却打不开", ["Docker", "Nginx", "网络"], 2, "docker"),
    ("monitor", "Prometheus 目标 DOWN", ["Prometheus", "node_exporter", "Grafana"], 2, "monitor"),
    ("alert", "告警触发了却没有通知", ["Prometheus", "Alertmanager", "Ansible"], 3, "alert"),
    ("redis", "缓存内存持续上涨", ["Redis", "Linux", "Prometheus"], 3, "redis"),
    ("kafka", "订单消费积压", ["Kafka", "Kubernetes", "MySQL"], 3, "kafka"),
    ("permissions", "配置文件权限修复", ["Linux", "权限", "安全"], 1, "permissions"),
    ("aws", "AWS：实例与私有存储", ["AWS", "网络", "IAM"], 2, "cloud"),
    ("azure", "Azure：网络与存储权限", ["Azure", "网络", "身份"], 2, "cloud"),
    ("gcp", "GCP：最小访问范围", ["GCP", "网络", "IAM"], 2, "cloud"),
]


def create(kind, seed):
    entry = next((x for x in CATALOG if x[0] == kind), None)
    if not entry:
        raise ValueError("未知场景")
    rng = random.Random(str(seed))
    state = {"kind": kind, "seed": str(seed), "name": f"lab-{rng.randrange(100,999)}",
             "port": rng.choice([8080, 8081, 9000]), "inspected": [], "history": [],
             "fixed": False, "verified": False}
    if kind == "disk":
        state.update(cause=rng.choice(["logs", "deleted", "inodes"]), retention=False)
        body = "订单服务写入失败，节点出现磁盘告警。确认是空间还是 inode 问题，定位来源、修复、检查并试运行已有轮转策略，再验证恢复。实验数据可重置。"
        commands = ["df -h", "df -i", "du -sh /var/log/*", "lsof +L1", "kubectl get pods", "cat /etc/logrotate.d/app"]
        solution = "先执行 df -h 与 df -i。日志过大：truncate -s 0 /var/log/app.log；已删除文件仍被占用：systemctl restart app；inode 耗尽：find /var/tmp/cache -type f -delete。然后 logrotate --force /etc/logrotate.d/app；curl localhost:8080/health。这里日志为可丢弃的实验数据，生产处理需先核对保留要求。"
    elif kind == "service":
        body = f"Deployment {state['name']} 的 Pod 已就绪，但 Service 没有后端。查清标签与选择器差异，将 Service 选择器改为 app={state['name']} 并验证。"
        commands = ["kubectl get pods --show-labels", f"kubectl describe svc {state['name']}", f"kubectl get endpoints {state['name']}"]
        solution = f"核对 Pod 标签与 Service selector，执行 kubectl patch service {state['name']} -p '{{\"spec\":{{\"selector\":{{\"app\":\"{state['name']}\"}}}}}}'；再 curl http://{state['name']}。"
    elif kind == "docker":
        body = f"Nginx 容器 web 已运行，却无法通过宿主机 {state['port']} 访问。检查容器监听和映射，重建容器并将宿主机 {state['port']} 映射到容器 80。"
        commands = ["docker ps", "docker logs web", "docker inspect web"]
        solution = f"检查发现映射到错误的容器端口。docker rm -f web；docker run -d --name web -p {state['port']}:80 nginx:alpine；curl localhost:{state['port']}。"
    elif kind == "monitor":
        body = "node_exporter 正在 9100 监听，Prometheus 却显示目标 DOWN。检查抓取配置，修正目标端口并重新加载，再验证目标。本实验的服务单元已配置 reload。"
        commands = ["promtool check config /etc/prometheus/prometheus.yml", "cat /etc/prometheus/prometheus.yml", "ss -lntp", "curl localhost:9100/metrics"]
        solution = "将抓取端口从 9101 改为 9100：sed -i 's/9101/9100/g' /etc/prometheus/prometheus.yml；promtool check config /etc/prometheus/prometheus.yml；systemctl reload prometheus；curl localhost:9090/api/v1/targets。"
    elif kind == "alert":
        body = "DiskSpaceLow 已触发，但通知没有到达。存在一条过期维护用途的长期静默。先检查告警与静默，移除实验静默，再验证通知。"
        commands = ["amtool alert query", "amtool silence query", "cat /etc/alertmanager/alertmanager.yml"]
        solution = "amtool silence query 查到 maint-001 覆盖该告警；amtool silence expire maint-001；amtool alert query 检查告警。本模拟器额外显示通知结果；真实 amtool 告警列表不能证明通知送达，还要检查 Alertmanager 日志与接收端记录。真实环境需确认维护窗口后操作。"
    elif kind == "redis":
        body = "缓存服务内存上涨，实验键 cache:large 占用 80MB 且没有 TTL。检查内存和过期策略，为该缓存键设置 300 秒 TTL，再验证。"
        commands = ["redis-cli INFO memory", "redis-cli TTL cache:large", "redis-cli MEMORY USAGE cache:large"]
        solution = "先确认键是可过期缓存，再执行 redis-cli EXPIRE cache:large 300；redis-cli TTL cache:large 验证。生产环境应从写入逻辑修复过期策略。"
    elif kind == "kafka":
        body = "订单 Topic 有 4 个分区，消费者 Deployment 只有 1 个副本。模拟环境已确认单实例 CPU 满载且下游正常。扩至 4 副本，查看消费积压变化。"
        commands = ["kafka-consumer-groups --bootstrap-server kafka:9092 --describe --group orders", "kubectl get deploy consumer", "kubectl top pods", "kubectl logs deploy/consumer"]
        solution = "kubectl scale deployment consumer --replicas=4；kafka-consumer-groups --bootstrap-server kafka:9092 --describe --group orders。实际吞吐还受下游与分区分布限制。"
    elif kind == "permissions":
        body = "应用配置 /workspace/config.env 当前对所有人可写。将权限修改为仅所有者可读写（600），并检查结果。"
        commands = ["ls -l /workspace/config.env", "stat /workspace/config.env", "id"]
        solution = "chmod 600 /workspace/config.env；stat /workspace/config.env。"
    else:
        state.update(instance="stopped", cidr="0.0.0.0/0", public=True, role="admin")
        body = f"{kind.upper()} 模拟：启动实例，将管理端口来源限制为 10.20.0.0/24，存储设为私有，身份权限改为只读。此控制台不会连接真实云账号。"
        commands = ["cloud show", "cloud instance start", "cloud network allow 10.20.0.0/24", "cloud storage private", "cloud iam readonly", "cloud verify"]
        solution = "依次检查资源，再启动实例、限制 CIDR、关闭存储公开访问、将权限设为只读，最后验证。也可使用右侧资源控制台操作。"
    return {"id": f"scenario:{kind}:{seed}", "type": "scenario", "title": entry[1], "level": entry[3],
            "category": entry[2][0], "tags": entry[2], "body": body, "intro": "每次重置保留题目参数；随机变式可改变参数与故障。",
            "answer": solution, "has_answer": True, "hints": ["先查看状态，收集证据。", "根据证据选择处理操作，再执行验证命令。"],
            "commands": commands, "minutes": 30, "state": state, "source": "OpsForge 原创状态模拟", "version": 1}


def check(s):
    if s["kind"] in ["aws", "azure", "gcp"]:
        checks = [("实例已启动", s["instance"] == "running"), ("来源仅限指定网段", s["cidr"] == "10.20.0.0/24"),
                  ("存储私有", not s["public"]), ("身份只读", s["role"] == "readonly"), ("完成验证", s["verified"])]
    else:
        checks = [("收集状态证据", bool(s["inspected"])), ("修复根因", s["fixed"])]
        if s["kind"] == "disk":
            checks.append(("验证已有轮转策略", s["retention"]))
        checks.append(("验证恢复", s["verified"]))
    return {"checks": [{"label": k, "passed": bool(v)} for k, v in checks], "passed": all(v for _, v in checks)}


def execute(state, command):
    s = copy.deepcopy(state)
    c = command.strip()
    if len(c) > 4000:
        raise ValueError("命令过长")
    s["history"] = (s["history"] + [c])[-100:]
    k = s["kind"]
    out = "模拟器不支持该命令。输入 help 查看本场景可操作命令；完整命令请使用真实实验环境。"
    if c in ["help", "帮助"]:
        q = create(k, s["seed"])
        out = "观察命令：\n" + "\n".join(q["commands"]) + "\n\n支持常见修复命令；查看分级提示或参考答案可学习具体语法。模拟器不执行宿主机命令。"
    elif c in ["clear", "pwd", "whoami", "hostname", "id"]:
        out = {"clear": "", "pwd": "/workspace", "whoami": "student", "hostname": s["name"], "id": "uid=1000(student) gid=1000(student)"}[c]
    elif k == "disk":
        if c == "df -h":
            s["inspected"].append("space"); out = "Filesystem      Size Used Avail Use% Mounted on\n/dev/vda1        50G  " + ("18G  32G   36%" if s["fixed"] or s["cause"] == "inodes" else "49G  1G    98%") + " /"
        elif c == "df -i":
            s["inspected"].append("inode"); out = "Filesystem Inodes IUsed IFree IUse% Mounted on\n/dev/vda1 1000000 " + ("100000 900000 10%" if s["fixed"] or s["cause"] != "inodes" else "1000000 0 100%") + " /"
        elif c.startswith("du "):
            s["inspected"].append("du"); out = "31G /var/log/app.log\n1G /var/log/journal" if s["cause"] == "logs" and not s["fixed"] else "16M /var/log/app.log\n1G /var/log/journal"
        elif c == "lsof +L1":
            s["inspected"].append("lsof"); out = "COMMAND PID USER FD SIZE/OFF NAME\napp 271 app 3w 33285996544 /var/log/app.log (deleted)" if s["cause"] == "deleted" and not s["fixed"] else "无已删除但仍被进程持有的文件"
        elif c.startswith("find /var/tmp/cache") and "-delete" not in c:
            s["inspected"].append("cache"); out = "缓存目录包含 900000 个临时小文件" if s["cause"] == "inodes" else "缓存文件数量正常"
        elif c == "truncate -s 0 /var/log/app.log":
            s["fixed"] = s["cause"] == "logs" or s["fixed"]; out = "实验日志已截断"
        elif c == "systemctl restart app":
            s["fixed"] = s["cause"] == "deleted" or s["fixed"]; out = "app 已重启，打开的旧文件描述符已释放"
        elif c == "find /var/tmp/cache -type f -delete":
            s["fixed"] = s["cause"] == "inodes" or s["fixed"]; out = "实验临时缓存已清理"
        elif c.startswith("cat /etc/logrotate"):
            out = "/var/log/app.log {\n  daily\n  rotate 7\n  compress\n  copytruncate\n}"
        elif c == "logrotate --force /etc/logrotate.d/app":
            s["retention"] = True; out = "本次已执行轮转；已有配置的保留上限为 7 份，并启用压缩"
        elif c == "kubectl get pods":
            out = "NAME          READY STATUS\norders-0      " + ("1/1 Running" if s["fixed"] else "0/1 CrashLoopBackOff")
        elif c.startswith("curl ") and "/health" in c:
            s["verified"] = s["fixed"]; out = "200 OK — 写入检查通过" if s["fixed"] else "507 Insufficient Storage"
    elif k == "service":
        if c.startswith("kubectl get pods"):
            s["inspected"].append("labels"); out = f"NAME READY STATUS LABELS\n{s['name']}-abc 1/1 Running app={s['name']}"
        elif c.startswith("kubectl describe svc"):
            s["inspected"].append("selector"); out = "Selector: app=" + (s["name"] if s["fixed"] else "old-app") + "\nPort: 80  TargetPort: 8080"
        elif c.startswith("kubectl get endpoints"):
            s["inspected"].append("endpoints"); out = s["name"] + (" 10.42.0.8:8080" if s["fixed"] else " <none>")
        elif c.startswith("kubectl patch "):
            try:
                parts = shlex.split(c); payload = json.loads(parts[parts.index("-p") + 1])
                valid = parts[2] in ["svc", "service"] and parts[3] == s["name"] and payload["spec"]["selector"]["app"] == s["name"]
                s["fixed"] = valid
                out = "service patched" if valid else "名称或 selector 不符合目标"
            except (ValueError, KeyError, IndexError):
                out = "补丁格式错误，请使用 -p 后跟有效 JSON"
        elif c.startswith("curl ") and s["name"] in c:
            s["verified"] = s["fixed"]; out = "200 OK" if s["fixed"] else "503 no healthy upstream"
    elif k == "docker":
        if c in ["docker ps", "docker inspect web", "docker logs web"]:
            s["inspected"].append("docker"); out = f"web nginx:alpine running\n0.0.0.0:{s['port']}->" + ("80/tcp" if s["fixed"] else "8080/tcp") + "\nnginx listening on 80"
        elif c == "docker rm -f web":
            s["removed"] = True; s["fixed"] = False; out = "web"
        elif c.startswith("docker run "):
            parts = shlex.split(c)
            valid = s.get("removed") and "-p" in parts and parts[parts.index("-p")+1] == f"{s['port']}:80" and "--name" in parts and parts[parts.index("--name")+1] == "web" and parts[-1] in ["nginx", "nginx:alpine"]
            s["fixed"] = bool(valid); out = "container web started" if valid else "检查名称、镜像、端口；已有容器需先移除"
        elif c.startswith("curl ") and str(s["port"]) in c:
            s["verified"] = s["fixed"]; out = "200 Welcome to nginx" if s["fixed"] else "connection reset"
    elif k == "monitor":
        if c.startswith("cat /etc/prometheus"):
            s["inspected"].append("config"); out = "scrape_configs:\n  - job_name: node\n    static_configs:\n      - targets: ['node:" + ("9100" if s.get("edited") else "9101") + "']"
        elif c == "ss -lntp":
            s["inspected"].append("listen"); out = "LISTEN 0.0.0.0:9100 node_exporter"
        elif c.startswith("promtool check config "):
            s["inspected"].append("validate"); out = "SUCCESS: syntax valid（语法正确不代表目标可达）"
        elif c == "sed -i 's/9101/9100/g' /etc/prometheus/prometheus.yml":
            s["edited"] = True; out = "配置端口已修改"
        elif c == "systemctl reload prometheus":
            s["fixed"] = bool(s.get("edited")); out = "配置已重载"
        elif c.startswith("curl ") and "9100/metrics" in c:
            s["inspected"].append("metrics"); out = "node_filesystem_avail_bytes{mountpoint=\"/\"} 34359738368"
        elif c.startswith("curl ") and "/api/v1/targets" in c:
            s["verified"] = s["fixed"]; out = json.dumps({"health": "up" if s["fixed"] else "down", "target": "node:9100" if s["fixed"] else "node:9101"})
    elif k == "alert":
        if c == "amtool silence query":
            s["inspected"].append("silence"); out = "无活动静默" if s["fixed"] else "maint-001 alertname=DiskSpaceLow expires=2099-01-01"
        elif c == "amtool silence expire maint-001":
            s["fixed"] = True; out = "静默已到期"
        elif c == "amtool alert query":
            s["inspected"].append("alerts"); s["verified"] = s["fixed"]; out = "DiskSpaceLow firing; notification=" + ("delivered (模拟)" if s["fixed"] else "suppressed")
        elif c.startswith("cat /etc/alertmanager"):
            out = "route:\n  receiver: ops\nreceivers:\n  - name: ops"
    elif k == "redis":
        if c in ["redis-cli INFO memory", "redis-cli MEMORY USAGE cache:large"]:
            s["inspected"].append("memory"); out = "(integer) 83886080" if "MEMORY USAGE" in c else "used_memory:83886080\nmaxmemory:104857600"
        elif c == "redis-cli EXPIRE cache:large 300":
            s["fixed"] = True; out = "(integer) 1"
        elif c == "redis-cli TTL cache:large":
            s["inspected"].append("ttl"); s["verified"] = s["fixed"]; out = "(integer) " + ("300" if s["fixed"] else "-1")
    elif k == "kafka":
        if c.startswith("kafka-consumer-groups "):
            s["inspected"].append("lag"); s["verified"] = s["fixed"]; out = "GROUP TOPIC PARTITIONS CONSUMERS LAG\norders orders 4 " + ("4 120（正在下降）" if s["fixed"] else "1 12000（持续增长）")
        elif c == "kubectl scale deployment consumer --replicas=4":
            s["fixed"] = True; out = "deployment.apps/consumer scaled"
        elif c.startswith("kubectl get deploy"):
            s["inspected"].append("deploy"); out = "consumer " + ("4/4" if s["fixed"] else "1/1")
        elif c == "kubectl top pods":
            s["inspected"].append("cpu"); out = "consumer-0 990m 128Mi"
        elif c == "kubectl logs deploy/consumer":
            s["inspected"].append("logs"); out = "mysql latency=8ms; processing queue; errors=0"
    elif k == "permissions":
        if c in ["ls -l /workspace/config.env", "stat /workspace/config.env"]:
            import stat
            mode = s.get("mode", "600" if s["fixed"] else "666")
            s["inspected"].append("mode"); s["verified"] = s["fixed"]
            out = stat.filemode(stat.S_IFREG | int(mode, 8)) + " " + mode + " student /workspace/config.env"
        elif re.fullmatch(r"chmod [0-7]{3,4} /workspace/config\.env", c):
            s["mode"] = format(int(c.split()[1], 8), "03o")
            s["fixed"] = s["mode"] == "600"
            s["verified"] = False
            out = ""
    elif k in ["aws", "azure", "gcp"]:
        if c == "cloud show":
            s["inspected"].append("cloud"); out = json.dumps({x: s[x] for x in ["instance", "cidr", "public", "role"]}, ensure_ascii=False, indent=2)
        elif c == "cloud instance start": s["instance"] = "running"; out = "实例已启动"
        elif c == "cloud instance stop": s["instance"] = "stopped"; out = "实例已停止"
        elif c.startswith("cloud network allow "):
            import ipaddress
            s["cidr"] = str(ipaddress.ip_network(c.split()[-1], strict=False)); out = "网络规则已更新"
        elif c == "cloud storage private": s["public"] = False; out = "存储已设为私有"
        elif c == "cloud storage public": s["public"] = True; out = "模拟存储已设为公开"
        elif c == "cloud iam readonly": s["role"] = "readonly"; out = "身份权限已改为只读"
        elif c == "cloud iam admin": s["role"] = "admin"; out = "模拟身份权限已改为管理员"
        elif c == "cloud verify": s["verified"] = True; out = json.dumps(check(s), ensure_ascii=False)
    return s, out
