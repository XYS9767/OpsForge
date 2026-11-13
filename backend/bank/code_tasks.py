"""Runnable starter projects and explicit review rubrics."""
TASKS = [
    {
        "id": "code-python-log", "category": "Python", "module": "python", "level": 2,
        "title": "Python：编写 HTTP 日志统计器", "language": "python",
        "body": "实现 count_status(lines)，从每行的最后一个字段读取三位 HTTP 状态码（100–599），忽略空行和无效行，返回 {状态码字符串: 次数}。不得因为坏数据中断。先运行测试观察失败，再补充实现。",
        "files": {"main.py": "def count_status(lines):\n    # TODO: validate each line and count status codes\n    return {}\n",
                  "test_main.py": "import unittest\nfrom main import count_status\nclass Tests(unittest.TestCase):\n    def test_counts(self):\n        self.assertEqual(count_status(['GET / 200', 'POST /api 500', 'GET / 200']), {'200':2,'500':1})\n    def test_bad_data(self):\n        self.assertEqual(count_status(['', 'bad', 'GET / 999', 'GET / 201']), {'201':1})\n    def test_empty(self):\n        self.assertEqual(count_status([]), {})\nif __name__ == '__main__': unittest.main()\n"},
        "run": "python3 -m unittest -v",
        "answer": "def count_status(lines):\n    result = {}\n    for line in lines:\n        parts = line.split()\n        if not parts:\n            continue\n        code = parts[-1]\n        if len(code) == 3 and code.isascii() and code.isdigit() and 100 <= int(code) <= 599:\n            result[code] = result.get(code, 0) + 1\n    return result",
        "hints": ["先 split，再检查列表是否为空。", "验证状态码长度、数字与范围，使用字典累加。"],
        "rubric": ["正确统计", "忽略无效数据", "空输入正常", "函数无外部副作用"],
    },
    {
        "id": "code-go-worker", "category": "Go", "module": "go", "level": 3,
        "title": "Go：实现可测试的并发平方任务",
        "body": "实现 Squares(nums []int, workers int) []int。限制工作协程数量，保持输出顺序；workers<=0 时按 1 处理，空输入返回空切片。思考如何迁移到主机巡检，并增加 context 取消。",
        "language": "go", "run": "go test -v ./...",
        "files": {"go.mod": "module opsforge/worker\n\ngo 1.23\n",
                  "worker.go": "package worker\n\nfunc Squares(nums []int, workers int) []int {\n    // TODO: bounded worker pool, preserve ordering\n    return nil\n}\n",
                  "worker_test.go": "package worker\nimport(\"reflect\"; \"testing\")\nfunc TestSquares(t *testing.T){if got:=Squares([]int{2,-3,4},2); !reflect.DeepEqual(got,[]int{4,9,16}){t.Fatalf(\"unexpected: %v\",got)}}\nfunc TestZeroWorkers(t *testing.T){if got:=Squares([]int{5},0); !reflect.DeepEqual(got,[]int{25}){t.Fatal(got)}}\nfunc TestEmpty(t *testing.T){if len(Squares(nil,3))!=0{t.Fatal(\"empty input\")}}\n"},
        "answer": "package worker\nimport \"sync\"\nfunc Squares(nums []int, workers int) []int {\n out := make([]int,len(nums))\n if workers<1 { workers=1 }; if workers>len(nums) { workers=len(nums) }\n jobs:=make(chan int); var wg sync.WaitGroup\n for w:=0; w<workers; w++ { wg.Add(1); go func(){ defer wg.Done(); for i:=range jobs {out[i]=nums[i]*nums[i]} }() }\n for i:=range nums { jobs<-i }; close(jobs); wg.Wait(); return out\n}",
        "hints": ["使用任务索引保存输出顺序。", "固定数量 worker 从 channel 读取索引，WaitGroup 等待结束。"],
        "rubric": ["结果正确", "并发数量受控", "无任务泄漏", "空输入和异常参数可处理"],
    },
    {
        "id": "code-shell-check", "category": "Shell", "module": "shell", "level": 2,
        "title": "Shell：稳健统计 ERROR 日志",
        "body": "编写 check.sh，接收一个日志路径，输出含 ERROR 的行数；没有匹配时输出 0 并成功退出；参数缺失或文件不存在时错误退出。文件名可能包含空格。",
        "language": "shell", "run": "bash test.sh",
        "files": {"check.sh": "#!/usr/bin/env bash\n# TODO: validate path, count matching lines\nexit 1\n",
                  "test.sh": "#!/usr/bin/env bash\nset -eu\ntmp=$(mktemp -d); trap 'rm -rf \"$tmp\"' EXIT\nprintf 'INFO ok\\nERROR one\\nERROR two\\n' > \"$tmp/a b.log\"\n[ \"$(bash check.sh \"$tmp/a b.log\")\" = 2 ]\nprintf 'INFO ok\\n' > \"$tmp/ok.log\"\n[ \"$(bash check.sh \"$tmp/ok.log\")\" = 0 ]\nif bash check.sh \"$tmp/missing\"; then exit 1; fi\nif bash check.sh; then exit 1; fi\nprintf 'All checks passed\\n'\n"},
        "answer": "#!/usr/bin/env bash\nif [ \"$#\" -ne 1 ] || [ ! -r \"$1\" ]; then\n  printf 'Usage: check.sh readable-log\\n' >&2\n  exit 2\nfi\nawk '/ERROR/ {n++} END {print n+0}' \"$1\"",
        "hints": ["先检查参数个数，再引用路径。", "grep 无匹配时的退出码需要处理；也可用 awk 统计。"],
        "rubric": ["路径正确引用", "空匹配输出零", "异常输入错误退出"],
    },
    {
        "id": "code-dockerfile", "category": "Dockerfile", "module": "dockerfile", "level": 2,
        "title": "Dockerfile：为 Go Web 服务制作镜像", "language": "dockerfile",
        "body": "使用多阶段构建编译 Go 服务，最终镜像使用非 root 用户，服务监听 8080，以 exec 形式启动程序。构建和运行需要启用真实 Docker 实验。验收包含镜像运行身份、HTTP 响应和停止行为。",
        "run": "docker build -t opsforge-web .",
        "files": {"main.go": "package main\nimport(\"fmt\"; \"net/http\")\nfunc main(){http.HandleFunc(\"/health\",func(w http.ResponseWriter,r *http.Request){fmt.Fprintln(w,\"ok\")}); panic(http.ListenAndServe(\":8080\",nil))}\n",
                  "go.mod": "module opsforge/web\n\ngo 1.23\n", "Dockerfile": "# TODO: build and runtime stages\n"},
        "answer": "FROM golang:1.27.3-alpine AS build\nWORKDIR /src\nCOPY go.mod main.go ./\nRUN CGO_ENABLED=0 go build -o /out/server .\nFROM alpine:3.21\nRUN adduser -D -u 10001 app\nCOPY --from=build /out/server /server\nUSER 10001\nEXPOSE 8080\nENTRYPOINT [\"/server\"]\n\n启动后检查 /health，检查容器用户；停止容器并验证退出行为。生产依赖应按维护策略更新并固定摘要。",
        "hints": ["构建阶段需要编译器，运行阶段只需要产物。", "USER 设置运行身份，ENTRYPOINT 使用 JSON 数组。"],
        "rubric": ["多阶段构建", "非 root", "服务可访问", "可正常停止"],
    },
    {
        "id": "code-helm", "category": "Helm", "module": "helm", "level": 3,
        "title": "Helm：参数化 Deployment", "language": "yaml", "run": "helm lint chart && helm template demo chart",
        "body": "补全 Chart 模板，让 values 中的 image、replicas 和 port 控制 Deployment；标签与 selector 必须一致，容器设置 readinessProbe。渲染后再部署到练习命名空间验收。",
        "files": {"chart/Chart.yaml": "apiVersion: v2\nname: opsforge-web\nversion: 0.1.0\n",
                  "chart/values.yaml": "replicas: 2\nimage: nginxinc/nginx-unprivileged:1.28-alpine\nport: 8080\n",
                  "chart/templates/deployment.yaml": "# TODO: Deployment with matching labels, values and readinessProbe\n"},
        "answer": "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: {{ .Release.Name }}\nspec:\n  replicas: {{ .Values.replicas }}\n  selector:\n    matchLabels: {app: {{ .Release.Name }}}\n  template:\n    metadata:\n      labels: {app: {{ .Release.Name }}}\n    spec:\n      securityContext:\n        runAsNonRoot: true\n        runAsUser: 101\n        seccompProfile: {type: RuntimeDefault}\n      containers:\n        - name: web\n          image: {{ .Values.image | quote }}\n          ports:\n            - containerPort: {{ .Values.port }}\n          securityContext:\n            allowPrivilegeEscalation: false\n            capabilities: {drop: [ALL]}\n          resources:\n            requests: {cpu: 50m, memory: 32Mi}\n            limits: {cpu: 200m, memory: 128Mi}\n          readinessProbe:\n            httpGet:\n              path: /\n              port: {{ .Values.port }}",
        "hints": ["先明确 selector 与 Pod labels 的关系。", "先 helm lint，再 helm template，最后验证运行状态。"],
        "rubric": ["可渲染", "参数生效", "标签匹配", "就绪探针有效"],
    },
    {
        "id": "code-ansible", "category": "Ansible", "module": "ansible", "level": 2,
        "title": "Ansible：幂等生成监控配置", "language": "yaml", "run": "ansible-playbook -i inventory playbook.yml",
        "body": "在 localhost 的 /workspace/prometheus.yml 生成 node_exporter 抓取配置，目标 node:9100。重复执行第二次应无变更。所有路径都限制在实验工作目录。",
        "files": {"inventory": "localhost ansible_connection=local\n", "playbook.yml": "---\n- hosts: all\n  gather_facts: false\n  tasks:\n    # TODO: copy content with explicit mode\n"},
        "answer": "- hosts: all\n  gather_facts: false\n  tasks:\n    - name: Write scrape configuration\n      ansible.builtin.copy:\n        dest: /workspace/prometheus.yml\n        mode: '0644'\n        content: |\n          global:\n            scrape_interval: 15s\n          scrape_configs:\n            - job_name: node\n              static_configs:\n                - targets: ['node:9100']",
        "hints": ["使用 copy 模块 content 参数。", "重复运行，观察 changed 数量。"],
        "rubric": ["文件内容正确", "权限明确", "第二次执行无变更"],
    },
    {
        "id": "code-operator", "category": "Go Operator", "module": "operator", "level": 5,
        "title": "Operator 项目：设计可重复协调的 WebApp", "language": "go", "run": "go test ./...",
        "body": "项目任务：用 Kubebuilder 建立 WebApp API，Spec 含 image、replicas、port，Status 含 readyReplicas 与 conditions。Reconcile 管理 Deployment 和 Service，处理更新、OwnerReference、冲突重试。编写测试验证重复协调不重复创建资源。本任务需要联网安装项目依赖，平台提供设计骨架和人工评审清单；它不是已完成的 Operator。",
        "files": {"DESIGN.md": "# WebApp Operator\n\n## API\n\n## Reconcile\n\n## Ownership and deletion\n\n## Tests\n",
                  "reconcile_plan.go": "// Design sketch: replace with a generated Kubebuilder project before building.\npackage design\n\n// Reconcile: load CR -> ensure child resources -> update status -> return.\n"},
        "answer": "1. 用 Kubebuilder 初始化项目并生成 WebApp API。\n2. 定义 Spec、Status、validation 与 deepcopy。\n3. Reconcile 读取 CR，忽略 NotFound；根据期望创建或更新 Deployment/Service，设置 ControllerReference。\n4. 保留服务器分配字段，避免无限更新。\n5. 从子资源状态构造 conditions，仅在变化时更新 Status。\n6. RBAC 按资源最小化配置；Finalizer 只在需要外部清理时加入。\n7. 用 fake client 或 envtest 覆盖首次创建、重复协调、更新、删除和冲突。\n8. 构建镜像，在练习集群部署，并验证故障恢复。",
        "hints": ["先设计 API 和生命周期，再写控制逻辑。", "区分期望状态与观测状态，写清重复调用的行为。"],
        "rubric": ["API 设计", "幂等协调", "所有权与生命周期", "状态反馈", "测试与权限"],
    },
]


def questions():
    return [{**q, "answer": render_answer(q), "type": "code", "has_answer": True, "source": "OpsForge 原创编程任务", "version": 1,
             "minutes": 60 if q["level"] < 4 else 180, "intro": "先保存文件，再在真实隔离环境运行；未启用真实环境时可编辑、保存与对照解析。"}
            for q in TASKS]


def render_answer(question):
    if question["id"] == "code-operator":
        return question["answer"]
    code, separator, tail = question["answer"].partition("\n\n启动后")
    return "```" + question["language"] + "\n" + code + "\n```" + ("\n\n启动后" + tail if separator else "")
