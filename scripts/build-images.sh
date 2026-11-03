#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
registry="${1:?用法: bash scripts/build-images.sh 镜像仓库 新的发布清单.json}"
release="${2:?请指定新的发布清单路径，供部署及回滚使用}"
python3 scripts/release_images.py "$registry" "$release"
printf '下一步：bash scripts/deploy.sh %s %s\n' "$registry" "$release"
