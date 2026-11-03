#!/usr/bin/env bash
# A maintenance-window backup keeps all five business databases at one logical point.
set -euo pipefail
destination="${1:?用法: bash scripts/backup-postgres.sh 新备份目录}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config="${2:-$script_dir/../deploy/config.json}"
python3 "$script_dir/external_pg.py" preflight "$config"
if [ -e "$destination" ]; then
  echo "备份目录已存在，请使用新目录" >&2
  exit 2
fi
umask 077
mkdir -p "$destination"
declare -A replicas
services=()
printf 'incomplete\n' > "$destination/status.txt"
kubectl -n opsforge get configmap opsforge-config -o json > "$destination/configmap.json"
python3 "$script_dir/external_pg.py" verify "$config" "$destination/configmap.json"
cp -- "$config" "$destination/config.json"
for service in gateway auth bank learning exams labs backend; do
  name="opsforge-$service"
  # Only an authoritative NotFound may be skipped. Permission/network errors abort.
  count="$(kubectl -n opsforge get deployment "$name" --ignore-not-found -o jsonpath='{.spec.replicas}' --request-timeout=30s)"
  if [ -n "$count" ]; then
    [[ "$count" =~ ^[0-9]+$ ]] || { echo "无效副本数：$name" >&2; exit 2; }
    replicas[$name]="$count"
    services+=("$name")
    printf '%s\t%s\n' "$name" "$count" >> "$destination/replicas.tsv"
  fi
done
if [ "${#services[@]}" -eq 0 ]; then echo "未发现待备份的应用服务" >&2; exit 2; fi
backup_ready=false
finish() {
  result=$?
  trap - EXIT
  restore_failed=false
  for name in "${services[@]}"; do
    if ! kubectl -n opsforge scale deployment "$name" --replicas="${replicas[$name]}" --request-timeout=30s >> "$destination/restore.log" 2>&1; then
      restore_failed=true
      echo "恢复副本失败：$name；原副本数见 $destination/replicas.tsv" >&2
    fi
  done
  # Restore every dependency before waiting for the gateway's readiness probe.
  for name in "${services[@]}"; do
    if [ "${replicas[$name]}" -gt 0 ]; then
      if ! kubectl -n opsforge rollout status deployment/"$name" --timeout=180s >> "$destination/restore.log" 2>&1; then
        restore_failed=true
        echo "恢复就绪检查失败：$name；详见 $destination/restore.log" >&2
      fi
    fi
  done
  if $restore_failed; then result=1; fi
  if [ "$result" -eq 0 ] && $backup_ready; then
    printf 'complete\n' > "$destination/status.txt"
    printf '备份完成且应用副本已恢复。目录含敏感凭据，请加密保存：%s\n' "$destination"
  else
    printf 'incomplete\n' > "$destination/status.txt"
    echo "备份或应用恢复未完成；保留目录供检查：$destination" >&2
    if [ "$result" -eq 0 ]; then result=1; fi
  fi
  exit "$result"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
for name in "${services[@]}"; do
  kubectl -n opsforge scale deployment "$name" --replicas=0 --request-timeout=30s
  kubectl -n opsforge wait --for=delete pod -l "app=$name" --timeout=180s
done
for domain in bank learning labs exams auth; do
  python3 "$script_dir/external_pg.py" dump "$config" "$domain" "$destination/${domain}.dump.part"
  test -s "$destination/${domain}.dump.part"
  mv -- "$destination/${domain}.dump.part" "$destination/${domain}.dump"
done
(cd "$destination" && sha256sum -- *.dump config.json configmap.json replicas.tsv > SHA256SUMS)
backup_ready=true
