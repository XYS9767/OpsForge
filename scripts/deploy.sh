#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
registry="${1:?用法: bash scripts/deploy.sh 镜像仓库 发布清单.json [明文配置.json]}"
release="${2:?请提供构建时生成的发布清单.json}"
config="${3:-deploy/config.json}"
if [[ ! "$registry" =~ ^[a-zA-Z0-9._:/-]+$ ]]; then echo "镜像仓库地址格式不正确" >&2; exit 2; fi
python3 scripts/deployment_config.py "$config"
python3 scripts/check-databases.py "$config"
python3 scripts/check-labs.py "$config"
umask 077
render_dir="$(mktemp -d)"
trap 'rm -f "$render_dir/api.json" "$render_dir/deployment.yaml"; rmdir "$render_dir"' EXIT
kubectl -n default get endpoints/kubernetes service/kubernetes -o json > "$render_dir/api.json"
python3 scripts/render_deploy.py "$release" "$render_dir/api.json" "$registry" "$config" > "$render_dir/deployment.yaml"
# Existing data stays intact; an old installation requires explicit migration.
old_pg="$(kubectl -n opsforge get statefulset opsforge-postgres --ignore-not-found -o name)"
if [ -n "$old_pg" ]; then
  echo "发现旧内置数据库：请先备份、迁移到外部 PostgreSQL，再由管理员移除旧 StatefulSet；本脚本不删除旧数据或 PVC。" >&2
  exit 2
fi
old_replicas="$(kubectl -n opsforge get deployment opsforge-backend --ignore-not-found -o jsonpath='{.spec.replicas}')"
if [ -n "$old_replicas" ] && [ "$old_replicas" != 0 ]; then
  echo "请先备份并停止旧单体后端，禁止新旧服务同时写入。" >&2; exit 2
fi
kubectl create namespace opsforge --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$render_dir/deployment.yaml"
for service in auth bank learning exams labs gateway frontend; do
  kubectl -n opsforge rollout status "deployment/opsforge-$service" --timeout=600s
done
printf '\n部署完成：外部 PostgreSQL，明文 ConfigMap，无内置数据库、PVC 或 Secret。\n'
kubectl -n opsforge get pods,svc
