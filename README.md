# OpsForge 源码交接包

2026-11-13 从 OpsForge 线上运行容器只读提取。

- backend/ 包含 Python 服务代码和依赖声明。题库服务的实际挂载覆盖已包含，labs/runtime.py 取自实操服务的运行容器。
- frontend/ 包含线上入口、静态资源和第三方许可。实际入口为 index.html 与 preview.js。
- DEPLOYMENT-SOURCES.json 记录各部署的镜像摘要和 ConfigMap 名称。
- 试卷相关入口可先看 backend/exams/service.py、backend/exams/scoring.py 和 frontend/preview.js。

此包用于源码交接和排查。生产题库、实操数据集、数据库、凭据、TLS 私钥及完整部署配置未打包。独立复现需要另行准备运行数据和环境配置。本次未构建镜像或部署，也未验证随机组卷功能。
