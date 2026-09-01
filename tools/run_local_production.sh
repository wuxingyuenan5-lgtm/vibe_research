#!/bin/bash
# 本地盘后任务：股票池行情由本地 API 刷新，市场母表同步由网页后端按需处理。
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
pipeline="${1:?usage: run_local_production.sh stock}"
python_bin="$project_dir/backend/.venv/bin/python"
target_date="$(TZ=Asia/Shanghai /bin/date +%F)"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

backup_files() {
  /usr/bin/git -C "$project_dir" add "$@"
  if /usr/bin/git -C "$project_dir" diff --cached --quiet; then
    echo "没有新的 $pipeline 数据需要备份。"
    return
  fi
  /usr/bin/git -C "$project_dir" commit -m "data: local $pipeline refresh $target_date"
  /usr/bin/git -C "$project_dir" push origin main
}

case "$pipeline" in
  stock)
    cd "$project_dir/backend"
    "$python_bin" -m market_monitor.daily_refresh --date "$target_date"
    backup_files \
      data/stock-pool/stocks.csv \
      data/stock-pool/indices.csv
    ;;
  *)
    echo "unknown pipeline: $pipeline" >&2
    exit 2
    ;;
esac
