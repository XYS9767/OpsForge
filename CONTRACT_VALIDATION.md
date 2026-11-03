现有ID与新规划题的可复现验收（续作检查点001）

本包已恢复scripts/validate_authored_contracts.py，直接调用当前hands_on.execution_bundle与平台assessment_runner；支持本机与显式既有WSL。原文档中的Docker模式和--docker参数本次未恢复，不能使用旧Docker示例；未构建或导出镜像。更完整恢复边界见docs/合同验收器恢复说明_20261028.txt。

在项目根目录执行（Windows Python Launcher）：

py -B scripts/validate_authored_contracts.py --source backend/data/hands-on-python-extra.json --wsl OpsForge-Validation-20261022 --wsl-user student --output work/new-python-four-route.json

py -B scripts/validate_contract_mutants.py --source backend/data/hands-on-python-extra.json --mutants tests/fixtures/python-continuation-mutants.json --wsl OpsForge-Validation-20261022 --wsl-user student --output work/new-python-boundaries.json

py -B scripts/audit_continuation_progress.py --output work/new-progress-audit.json

输出路径必须是尚不存在的新文件，旧证据不覆盖。--source可重复用于四路线；--id可重复限定既有ID。突变器单个--source，JSON映射为{question_id:{case_name:{artifact_path:content}}}，只能修改声明的学员产物。它自动加当前参考路线；fixture与四路negative及其他变体按合并后产物去重。

四路包括reference、starter、negative、runner_early_exit。参考必须完成所有可信检查；初始与错误路线必须因语义断言失败；退出0但检查未完成必须被平台拒绝。缺工具、导入/语法错误、超时和缺少判定不能算作正确拒绝。路线数不是题目数。

本轮使用显式既有WSL OpsForge-Validation-20261022、student UID1000，并未切换默认发行版或用户。发行版名只是本机环境标识，其他机器需显式填写自己的隔离环境并准备相应原生工具。临时目录是材料隔离，不能把本机/WSL模式作为不可信代码安全沙箱；仅运行已审校可信合同。

各题需要的原生工具分别预检；MySQL8.4与Redis7.2不能用模拟器或其他版本冒充。已有Istio原生实操依赖本机未提供的istioctl/Envoy时仍为未验收；新增离线算法不替代这些原生验收。完整模块复核、干净离线恢复与最终五轮PC仍未完成。

报告HTML检查用scripts/verify_project_report_browser.py --html <本地HTML> --output <全新目录>，只使用安装Playwright匹配revision的独立Headless Shell，缺失即失败；不回退系统Edge，不接触个人浏览器配置。报告页面检查不计最终PC五轮。
