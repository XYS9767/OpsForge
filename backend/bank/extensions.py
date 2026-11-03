"""Curated question-answer pairs; each row is stored as one versioned question object."""
BASIC = {
 "basics": "依次执行 pwd、whoami、hostname。分别记录工作目录、执行身份、当前主机名；命令改变目录前后，再执行 pwd 比较。",
 "linux": "mkdir -p /workspace/demo\nprintf 'hello\\n' > /workspace/demo/hello.txt\ncat /workspace/demo/hello.txt\nls -l /workspace/demo/hello.txt\n\n确认文件路径、内容、大小和权限；mkdir -p 可重复执行。",
 "permissions": "先用 id、ls -l 检查身份和所有者，再执行 chmod 600 /workspace/config.env；用 stat /workspace/config.env 验证权限为 600。不要将真实密钥写入题目。",
 "process": "ps -ef 查看 PID、PPID 和命令；ps -o pid,ppid,stat,cmd -p PID 检查指定进程。使用 kill -l 查看信号。真实容器工作区没有完整 systemd，主机服务管理需在专门主机环境练习。",
 "disk": "先 df -h 查看容量与挂载点；df -i 查看 inode；对同一挂载点执行 du -xhd1 路径，避免跨文件系统比较。差异大时检查权限、挂载遮挡和 lsof +L1 的已删除文件；不要直接删除未知数据。",
 "network": "ip addr 查看地址；ip route 查看默认路由；ss -lntp 查看监听（进程信息可能受权限限制）；curl -v --connect-timeout 3 --max-time 10 URL 查看连接、TLS 和 HTTP 阶段。每一步针对不同层。",
 "shell": "日志行计数可用 awk '/ERROR/ {n++} END {print n+0}' \"$file\"；执行前检查参数个数和 -r \"$file\"。路径必须加引号，坏输入返回非零退出码。完整实现见 Shell 编程题。",
 "python": "def count_status(lines):\n    counts = {}\n    for line in lines:\n        parts = line.split()\n        if not parts:\n            continue\n        code = parts[-1]\n        if len(code)==3 and code.isascii() and code.isdigit() and 100<=int(code)<=599:\n            counts[code] = counts.get(code, 0) + 1\n    return counts\n\n测试应包含重复状态码、空输入、坏行和越界状态码。",
 "go": "使用固定 worker 数，从任务 channel 读取目标；HTTP Client 配置 Timeout，请求使用 context；每次响应读取后关闭 Body。结果包含目标、状态码、耗时和 error，主协程等待全部 worker 结束。参考并发编程题练习 worker pool。",
 "git": "git switch -c feature/check\n修改文件后：git status；git diff；git add 指定文件；git diff --cached；git commit -m 'add check'。提交前核对暂存区中没有无关改动。",
 "docker": "docker run -d --name web -p 8080:80 nginx:alpine\n随后 docker ps、docker logs web、docker inspect web、curl localhost:8080。持久数据另用具名卷，检查容器重建后的数据是否保留。需要真实 Docker 工作区。",
 "dockerfile": "使用 golang 构建阶段编译 CGO_ENABLED=0 的程序，将二进制复制到精简运行阶段；创建并切换非 root 用户；用 ENTRYPOINT [\"/server\"] 启动。通过 docker inspect、HTTP 请求和停止测试验证。完整文件见 Dockerfile 编程题。",
 "kubernetes": "检查 Deployment 的 selector 与 Pod labels 一致；Service selector 匹配 Pod，targetPort 对应应用监听。使用 kubectl get pods --show-labels、kubectl describe service、kubectl get endpointslices、kubectl logs 收集证据。受限工作区部署需配置非 root、安全上下文和资源限制。",
 "nodeport": "Service spec.type: NodePort；ports 内分别设置 port:80、targetPort:8080、nodePort:30081。selector 匹配后端 Pod。检查端点与应用监听，再访问 http://节点IP:30081。NodePort 端口需在集群允许范围内，且入口网络策略与防火墙允许。",
 "helm": "Chart.yaml 定义名称与版本；values.yaml 放 image、replicas、port；Deployment 模板引用 .Values 并使用匹配标签，增加 readinessProbe。先 helm lint chart，再 helm template demo chart 检查渲染结果；安装后查实际 Pod。普通工作区使用 HELM_DRIVER=configmap。",
 "operator": "先定义 WebApp Spec 的 image、replicas、port 和 Status 的 readyReplicas、conditions。用 Kubebuilder 建立项目，Reconcile 读取 CR 后创建或更新 Deployment，设置所有权，再根据 Deployment 状态更新 CR Status。项目题给出详细评审清单；CRD 安装在独立 K8s 实验内进行。",
 "nginx": "server 监听入口端口，location / 配置 proxy_pass 指向可达上游；按应用要求设置 Host 与转发头。nginx -t 验证语法，重载后 curl -v 测试路径和 Host，同时观察 access/error 日志。proxy_pass 带不带 URI 会影响路径替换。",
 "envoy": "按 Listener → filter chain → HTTP connection manager → route → cluster 顺序读配置，确认监听端口、匹配路径与上游地址。检查 cluster endpoint 的健康状态和协议；运行配置校验，再发请求看访问日志。",
 "mysql": "先使用 SELECT 在测试表读取数据，再执行 EXPLAIN SELECT ...。查看访问类型、候选与实际索引、rows 估计和 Extra；结合实际耗时验证。rows 是估计扫描量，不是返回行数，不应只凭索引是否被使用判断性能。",
 "redis": "SET sample:value hello EX 300\nGET sample:value\nTTL sample:value\nEXISTS sample:value\n\nTTL 为 -1 表示没有过期时间，-2 表示键不存在。修改过期策略前确认该键是否允许作为缓存失效。",
 "kafka": "记录生产速率、消费处理速率和 lag 时间序列。kafka-consumer-groups.sh --bootstrap-server 地址 --describe --group 组名 查看各分区 offset 和 lag，结合重平衡、错误与下游耗时判断。工具路径和认证参数按环境设置。",
 "clickhouse": "列出 WHERE 的常用过滤条件及聚合维度，检查 MergeTree 的 ORDER BY 与查询是否匹配。用 EXPLAIN 和查询日志对比读取行数、字节数与耗时；排序键和分区键作用不同，不应把二者混同。",
 "tidb": "请求通常由 TiDB SQL 层规划执行，访问 TiKV 等存储组件；PD 提供集群元信息与调度。分别观察 SQL 延迟、存储请求、Region 分布、磁盘和网络。具体请求路径取决于使用的存储引擎与执行计划。",
 "ceph": "从 ceph -s 和 ceph health detail 获取概览，再查看 ceph osd tree、ceph df。确认故障域、PG 状态、容量与恢复进度；涉及数据风险的修复前先核实原因和副本状态，避免盲目移除 OSD。",
 "elk": "产生带唯一测试标识的日志，从采集器输入与 offset 状态开始，检查缓冲、解析输出、Elasticsearch 写入响应与索引时间字段，最后在 Kibana 按时间窗口检索。保留原始日志以便定位丢失环节。",
 "loki": "例如 {namespace=\"demo\", app=\"web\"} |= \"ERROR\"；先检查是否存在该日志流，再缩小时间范围与过滤内容。标签值必须与实际采集标签一致，高基数字段优先保留在日志内容或结构化元数据中。",
 "prometheus": "scrape_configs 中配置 job_name: node 和 static_configs targets: ['node:9100']。先 promtool check config，再加载配置；在 targets 中确认 UP，查询 up{job=\"node\"}。对累计请求数用 rate(counter_total[5m]) 观察速率。",
 "node_exporter": "按相同 instance、device、mountpoint 匹配 node_filesystem_avail_bytes 和 node_filesystem_size_bytes；可用百分比=avail/size*100。inode 另看 files_free/files。检查采集时的宿主机挂载配置，避免误把容器文件系统当作主机。",
 "alertmanager": "在 route 中设置 group_by、group_wait、group_interval、repeat_interval，按 severity 的 matcher 路由到接收器。amtool check-config 检查配置，再用测试告警验证。静默与抑制都可能使告警有状态但无通知。",
 "grafana": "添加 Prometheus 数据源并验证连接；在 Explore 先运行磁盘可用百分比查询；创建面板设置百分比单位、0–100 范围和 instance 变量，最后与原始指标值核对。不要同时重复乘 100 与按 0–1 格式解释。",
 "zabbix": "创建主机并正确配置 Agent 接口，关联合适模板；查看最新数据确认监控项有值，再检查触发器表达式、动作条件与媒介。逐层验证采集→触发→通知，Agent 主动/被动方式对应不同连接方向。",
 "ansible": "Inventory 指定目标与连接方式；copy/template 模块生成配置，notify 指向 handler；handler 在任务发生变更时重载服务。先限制到测试主机，重复执行确认幂等，再检查服务状态。",
 "terraform": "terraform init 初始化依赖，terraform validate 检查配置，terraform plan 检查变更。阅读 +、~、-/+ 的原因，特别核对会替换的资源。state 保存资源地址与远端对象的映射，需要受控存储与备份。",
 "cicd": "阶段建议：静态检查→单元测试→构建镜像→扫描与保存摘要→更新部署配置→发布→探针及业务验证。任何失败应停止后续发布；保存版本与日志，明确回滚和数据库兼容策略。",
 "aws": "在 AWS 模拟题中执行 cloud show；cloud instance start；cloud network allow 10.20.0.0/24；cloud storage private；cloud iam readonly；cloud verify。控制台按钮等价于这些平台模拟指令，不是 AWS CLI。",
 "azure": "在 Azure 模拟题中检查实例、网络来源、存储公开性与身份权限，依次启动实例、将来源设为 10.20.0.0/24、存储私有、身份只读，再验证。平台 cloud 指令不是 az CLI。",
 "gcp": "在 GCP 模拟题中完成实例启动、限制来源网段、关闭存储公共读取并授予只读身份，再验证。资源是平台内模拟；cloud 指令不是 gcloud CLI。",
}

BONUS = {
 "linux": [
  ("如何安全查看一个未知文本文件的前后内容？","先 ls -lh 确认大小；head -n 20 文件查看开头，tail -n 20 文件查看末尾。大文件可用 less 分页，避免直接将巨量内容输出到终端。",1),
  ("标准输出、标准错误与退出码分别表示什么？","stdout 输出正常结果，stderr 输出诊断信息；退出码用于向调用方报告成功或失败。可分别重定向，不能因为有输出就认定成功。",0)],
 "disk": [
  ("磁盘还有空间，为什么仍然报 No space left on device？","检查 inode、用户或项目配额、具体挂载点、文件系统保留空间以及实际写入位置。df -h 与 df -i 提供不同证据。",2),
  ("如何设计磁盘容量预警，避免只在 99% 时才告警？","组合剩余比例、剩余字节、增长趋势和业务写入速率，区分临时文件系统；考虑预计耗尽时间，并设置持续时间与告警分级。",3)],
 "nginx": [
  ("如何检查 Nginx 配置再重载？","先 nginx -t，确认校验通过后执行 nginx -s reload 或环境对应服务重载。重载后检查错误日志和实际 HTTP 响应。",1),
  ("proxy_pass 的尾部斜杠为什么会影响路径？","location 为前缀匹配时，proxy_pass 带 URI 会用其 URI 替换匹配部分；不带 URI 通常保留请求 URI。应用还可能受 rewrite、变量和规范化影响，需对目标路径测试。",3),
  ("Nginx 499 表示服务端返回了业务错误吗？","499 是 Nginx 记录客户端提前关闭连接的非标准状态。检查客户端超时、上游耗时、请求大小与链路；它不等价于应用主动返回业务错误。",2),
  ("如何判断反向代理中的请求耗时发生在哪一段？","记录 request_time、upstream_connect_time、upstream_header_time、upstream_response_time 并关联请求标识；结合上游监控比较连接、首包和总处理耗时。",3)],
 "redis": [
  ("TTL 返回 -1 与 -2 分别意味着什么？","-1 表示键存在但没有过期时间；-2 表示键不存在。先确认键名、数据库和连接实例正确。",1),
  ("为什么线上查找键通常使用 SCAN 而不是 KEYS *？","KEYS 会遍历全部匹配键并可能阻塞服务；SCAN 分批迭代以降低单次影响，但扫描期间变化的数据可能重复出现，不能当作一致性快照。",2),
  ("Redis 复制等同于备份吗？","不等同。误删除或错误写入可能传播到副本；应保留独立备份并验证恢复。复制主要用于冗余、可用性或读扩展。",1),
  ("缓存击穿如何治理？","针对热点键失效带来的并发回源，可使用互斥重建、逻辑过期、预热等策略；评估可接受的陈旧数据和锁失败行为，避免把所有请求堵塞。",3),
  ("出现延迟尖峰时为什么要检查大键？","大键的读取、删除、序列化和网络传输可能占用较多资源；用采样和诊断工具定位，结合 slowlog、客户端与持久化指标，避免用破坏性方式探测。",3)],
 "mysql": [
  ("WHERE 与 HAVING 的作用有什么区别？","WHERE 过滤输入行，HAVING 对分组或聚合后的结果施加条件。能在聚合前过滤的条件通常应尽早过滤，同时保持语义正确。",1),
  ("事务的原子性和隔离性分别是什么？","原子性要求事务整体提交或回滚；隔离性描述并发事务之间可见性和干扰程度，具体表现受隔离级别与数据库实现影响。",1),
  ("联合索引的列顺序为什么重要？","列顺序影响前缀匹配、范围扫描、排序与覆盖能力。应按查询条件、排序和数据分布设计，并使用执行计划与实际性能验证。",2),
  ("慢查询一定是缺索引吗？","不一定；还可能是锁等待、扫描量过大、错误计划、磁盘延迟、CPU 竞争或客户端读取慢。先定位耗时与等待原因。",2),
  ("如何排查主从复制延迟？","确认连接和复制线程状态，再检查事务大小、写入速率、锁等待、磁盘、网络及副本执行能力；同时确认监控延迟指标的含义。",3),
  ("恢复数据库前需要确定哪些目标？","确定恢复点、可接受数据损失、恢复时长、备份链与日志完整性；在隔离环境演练并核对业务数据，最后制定切换和回退步骤。",3)],
 "kafka": [
  ("同一个消费组内，两个消费者能同时拥有同一分区吗？","在正常稳定分配下，一个分区在组内由一个消费者负责；不同消费组各自独立消费。重平衡期间需考虑撤销和重新分配。",1),
  ("消费 lag 为零是否意味着业务已经处理成功？","不一定。需要核对 offset 提交时机；若在业务处理完成前提交，lag 可为零但业务仍失败。还需观察处理结果和下游。",2),
  ("增加分区为什么可能影响同一键的顺序？","默认分区选择通常依赖键哈希和分区数量；分区数改变后同一键可能映射到新分区。顺序保证通常局限于分区，需要设计迁移策略。",3),
  ("如何处理重复消费？","以业务唯一标识或幂等操作处理重复，协调业务提交与 offset 管理；重试、崩溃和重平衡都可能导致重复，不能只依赖消费者运行正常。",3)],
 "ceph": [
  ("OSD down 与 out 有什么区别？","down 描述守护进程不可达或未正常响应；out 表示不再参与预期数据放置。两者是不同状态，处理前检查故障原因和集群恢复能力。",2),
  ("Ceph degraded 和 undersized 可以混为一谈吗？","不能。degraded 表示对象存在需要恢复的副本问题；undersized 表示 PG 当前副本数量不足目标。应结合具体健康信息、PG 状态和 OSD 分布分析。",3),
  ("为什么恢复期间业务 I/O 可能变慢？","恢复和回填会竞争磁盘、网络与 CPU；需要监控资源瓶颈，在数据恢复速度与前台业务延迟之间配置合理策略。",3),
  ("RBD 和 CephFS 分别提供什么？","RBD 提供块设备接口；CephFS 提供文件系统接口。应根据应用是否需要块存储或共享文件语义选择，并确认 CSI 与访问模式。",1)],
 "helm": [
  ("helm template 与 helm install 的区别？","template 渲染清单用于检查；install 创建 release 并向集群提交资源。渲染成功不代表 API 接受或应用就绪。",1),
  ("为什么 values 中的字符串有时需要 quote？","YAML 可能把未加引号的值解析为数字或布尔等类型。quote 可明确输出字符串，但仍需满足目标 API 字段类型。",2),
  ("Helm 回滚是否自动回滚数据库数据？","一般不会。Helm 管理发布清单与相关操作，数据库迁移和业务数据需要独立的兼容与恢复策略。",2),
  ("如何排查 Chart 升级后出现字段不可变错误？","比较新旧清单，定位不可变字段，如某些 selector；评估保留字段、迁移或重建的影响，避免直接删除有状态资源。",3)],
 "operator": [
  ("CRD、CR 与 Controller 分别是什么？","CRD 定义自定义资源类型和模式；CR 是该类型的实例；Controller 观察资源变化并协调实际状态。仅安装 CRD 不会自动实现业务逻辑。",1),
  ("Reconcile 收到的请求是否就是完整变更事件？","通常只包含对象的键，协调时应重新读取当前状态。事件可能被合并和重复，不能依赖逐个事件重放实现正确性。",3),
  ("为什么应该谨慎更新 Status？","无意义更新可能触发额外协调或冲突；应基于观测状态计算有意义的差异，并处理资源版本冲突。",3),
  ("Finalizer 一直无法清除时应该查什么？","检查控制器是否运行、是否有权限、外部清理是否可重试以及删除时间戳分支。强行移除可能遗留外部资源，应先确认清理结果。",3),
  ("Operator 如何避免无限重建子资源？","设置稳定名称与所有权，读取当前对象后按差异更新；保留服务器默认字段，处理不可变字段，测试连续协调是否收敛。",4),
  ("设计 Operator 测试，应覆盖哪些生命周期？","首次创建、重复协调、Spec 更新、外部漂移、子资源缺失、权限或 API 错误、Status 反馈与删除清理；集成测试验证真实 API 语义。",4)],
 "prometheus": [
  ("up=1 能证明业务正确吗？","只能证明该目标最近一次抓取成功；还需要业务错误率、延迟、吞吐和依赖指标判断业务健康。",1),
  ("Counter 与 Gauge 有何区别？","Counter 表示累计量，通常单调增长但进程重启可重置；Gauge 表示可升可降的当前值，如温度或队列长度。",1),
  ("为什么对 counter 使用 rate 时要考虑窗口长度？","窗口应覆盖足够的采样点并匹配观察目标；过短可能缺数据或波动大，过长可能掩盖短期变化。",2),
  ("什么是高基数标签问题？","标签组合过多会产生大量时序，增加内存、存储和查询成本。不要随意把请求 ID、用户 ID 或原始 URL 放入标签。",2)],
 "alertmanager": [
  ("Prometheus 与 Alertmanager 的职责如何划分？","Prometheus 计算告警规则并发送告警；Alertmanager 负责分组、路由、静默、抑制和通知。通知失败不一定是规则问题。",1),
  ("如何排查触发了告警却没有收到邮件？","按规则 firing→Alertmanager 收到→route 匹配→silence/inhibition→receiver→邮件服务逐段验证，查看发送错误与重试。",3),
  ("告警风暴如何治理？","优化规则和持续时间，按实例或服务分组，使用合适抑制关系，避免重复通知；保留根因告警并验证重要告警不会被隐藏。",3)],
 "grafana": [
  ("No data 与指标值为零有什么区别？","No data 表示查询未返回可用数据；零是有效数值。先检查时间范围、标签、采集和数据源，不应直接把无数据替换为零。",1),
  ("如何避免仪表盘单位误导？","核对原始指标单位与查询转换，明确字节和 bit、秒和毫秒、0–1 与 0–100 的区别，并用已知样本验证。",2),
  ("仪表盘变量为什么可能让所有面板变空？","变量查询或标签值与面板过滤条件不匹配，多选与正则语法也可能不适用。先去掉变量过滤确认原始查询，再逐个恢复。",2)],
 "zabbix": [
  ("监控项、触发器和动作的关系是什么？","监控项获取数据；触发器根据表达式判断问题；动作在满足条件时执行通知或其他操作。依次验证各环节。",1),
  ("Agent 主动检查不回传数据要核对哪些配置？","检查 ServerActive、Hostname 与前端主机名匹配、网络方向、TLS 设置以及 Agent 日志；确认主动监控项存在且已下发。",2),
  ("模板继承有什么价值？","统一复用监控项、触发器和发现规则，减少逐主机配置；修改前评估受影响主机并处理主机级宏差异。",1),
  ("低级别发现 LLD 适合什么场景？","自动发现文件系统、接口等动态对象，并基于原型创建监控项与触发器；需要过滤无关对象和处理消失资源。",2),
  ("Zabbix 监控队列增长怎样排查？","查看延迟监控项类型、采集进程繁忙率、网络超时、代理与服务端负载、数据库性能，按瓶颈调整并验证。",3)],
 "node_exporter": [
  ("为什么根分区告警要过滤伪文件系统？","tmpfs、overlay 等可能不是希望监控的持久磁盘；按业务采集配置与 fstype、mountpoint 选择目标，避免重复或误报警。",2),
  ("主机内存 available 和 free 为什么不同？","free 是未使用内存；available 是对无需交换即可给新应用使用内存的估计，包含部分可回收缓存。需结合系统压力判断。",1)],
 "ansible": [
  ("changed 和 failed 分别表示什么？","changed 表示任务报告发生了状态变更；failed 表示执行失败。changed 不证明业务可用，还需要验证。",1),
  ("为什么 shell 任务容易每次都显示 changed？","任意命令通常无法自动推断是否改变状态；优先使用对应模块，必要时设置合理的 changed_when、creates 等条件。",2),
  ("handler 何时触发？","被发生变更的任务 notify 后，在相应处理阶段执行；同名 handler 通常合并通知。需要时可显式 flush_handlers。",2),
  ("如何结合 Ansible 处理磁盘告警？","先采集和报告挂载点、容量、inode与日志增长；用审批后的规则分批调整轮转或保留策略；执行后验证业务和告警，不能无差别删除日志。",3)],
 "loki": [
  ("日志标签与日志内容有什么区别？","标签用于标识日志流和筛选；内容是每条日志本身。选择稳定、低基数标签，动态请求字段保留在内容或适当结构化元数据中。",1),
  ("Loki 查询不到日志的排查顺序？","确认日志源产生数据、采集器有读取权限、标签正确、发送无错误、租户与时间窗口匹配，再检查存储和查询端。",2)],
 "envoy": [
  ("Envoy 的 Cluster 等同于 Kubernetes 集群吗？","不是。Envoy 中 Cluster 表示一组上游主机及其连接、负载均衡等配置；名称相同但概念不同。",1),
  ("端到端超时与重试超时如何协调？","为一次用户请求设总体预算，每次尝试占用预算的一部分，限制次数与退避；避免重试总时长超过上游调用方可接受时限。",3)],
 "clickhouse": [
  ("分区粒度过细会有什么问题？","可能导致大量分区与数据 part，增加元数据、合并和查询开销。按保留、管理与查询需求选择粒度，避免用高基数字段随意分区。",2),
  ("怎样评估查询优化是否有效？","对代表性查询比较延迟、读取行数、字节数、内存和并发负载，并控制缓存与数据规模等条件。只看单次最快时间不充分。",3)],
 "tidb": [
  ("如何区分 SQL 层慢与存储层慢？","结合慢查询、执行计划、SQL 层资源和存储请求延迟，观察热点 Region、TiKV 磁盘及网络。通过同一时间窗口关联证据。",3),
  ("分布式数据库扩容后吞吐一定立即提高吗？","不一定；数据调度需要时间，还可能受热点、SQL 模式、网络、存储或应用并发限制。检查资源和数据分布变化。",2)],
}


def questions(modules):
    result = []
    lookup = {m[0]: m[1] for m in modules}
    for slug, entries in BONUS.items():
        for i, (title, answer, level) in enumerate(entries, 1):
            result.append({"id": f"extra-{slug}-{i:02}", "title": title, "answer": answer, "level": level,
                           "module": slug, "category": lookup[slug], "type": "interview", "version": 1,
                           "body": "请用文字回答，可结合命令、指标或工作场景说明。回答后按参考要点自评。",
                           "hints": ["先说明概念与边界，再给出判断依据。"], "has_answer": True,
                           "source": "OpsForge 原创扩展问答", "rubric": ["原理准确", "判断有依据", "说明适用边界"]})
    projects = [
        ("observability","监控闭环：从磁盘告警到自动化修复","Prometheus、node_exporter、Grafana、Alertmanager、Zabbix、Ansible","设计容量与 inode 监控、告警路由和仪表盘；对告警主机生成排查报告，分批执行审核过的日志轮转配置并验证。","先统一指标语义与挂载点过滤；定义持续时间、分级、通知路由与静默。用 Ansible 采集事实和应用幂等变更，保留变更前后输出；以业务写入和告警恢复作为验证。"),
        ("delivery","发布失败：从提交到集群恢复","Git、CI/CD、Dockerfile、Helm、Kubernetes","发布后 Pod 不就绪，要求定位代码、构建、配置或运行环境中的问题，给出恢复和预防方案。","关联提交与不可变镜像摘要；检查构建产物、Helm 渲染差异、Pod 事件、探针和日志；基于证据选择修复或回滚，验证入口请求与关键业务。"),
        ("latency","网站慢：建立完整排查链路","网络、Nginx、Envoy、Kubernetes、MySQL、Redis","面对间歇性延迟升高，设计排查顺序，说明每一步的指标、日志与可排除的假设。","先确认影响范围和分位延迟，关联请求标识；分解 DNS、连接、代理和上游时间；检查 Pod 资源、数据库锁与慢查询、缓存命中及下游超时。一次变更一个因素并对照验证。"),
    ]
    for slug, title, tags, body, answer in projects:
        result.append({"id":"project-"+slug,"title":title,"tags":tags.split("、"),"category":"跨模块综合","type":"case","level":4,"version":1,
                       "body":body+"\n交付：排查过程、证据、根因假设、处理步骤、回退方案和恢复验证。此题为开放方案题，可结合真实工作区复现。",
                       "answer":answer,"has_answer":True,"hints":["先按请求或数据流画出关联组件。","分别列出各组件的输入、输出、正常基线和异常证据。"],
                       "rubric":["覆盖影响范围","建立证据链","处理可回退","恢复可验证"],"source":"OpsForge 原创综合方案题"})
    return result
