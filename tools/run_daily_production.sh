#!/bin/bash
# 唯一盘后生产入口：launchd 在交易日 15:05 调用。
set -u -o pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
python_bin="$project_dir/backend/.venv/bin/python"
target_date="$(TZ=Asia/Shanghai /bin/date +%F)"
log_dir="${TMPDIR:-/tmp}"
log_file="$log_dir/vibe-daily-production.log"

exec >>"$log_file" 2>&1
echo "[$(TZ=Asia/Shanghai /bin/date '+%F %T %Z')] start daily production: $target_date"

# 节假日不取数，也不产生无意义的 Git 提交。
set +e
"$python_bin" "$project_dir/market-monitor/is_trading_day.py" --date "$target_date"
trading_day_status=$?
set -e
if [ "$trading_day_status" = "10" ]; then
  echo "[$(TZ=Asia/Shanghai /bin/date '+%F %T')] non-trading day: skip"
  exit 0
fi
if [ "$trading_day_status" != "0" ]; then
  echo "trading-day check failed: $trading_day_status" >&2
  exit "$trading_day_status"
fi

run_with_retry() {
  local pipeline="$1"
  local attempt
  for attempt in 1 2 3; do
    echo "[$(TZ=Asia/Shanghai /bin/date '+%F %T')] $pipeline attempt $attempt/3"
    if /bin/bash "$project_dir/tools/run_local_production.sh" "$pipeline"; then
      echo "[$(TZ=Asia/Shanghai /bin/date '+%F %T')] $pipeline complete"
      return 0
    fi
    if [ "$attempt" != "3" ]; then
      sleep 300
    fi
  done
  echo "[$(TZ=Asia/Shanghai /bin/date '+%F %T')] $pipeline failed after 3 attempts" >&2
  return 1
}

# 两条生产链独立运行；市场链失败不阻断自选股更新，反之亦然。
market_status=0
stock_status=0
run_with_retry market || market_status=$?
run_with_retry stock || stock_status=$?

if [ "$market_status" != "0" ] || [ "$stock_status" != "0" ]; then
  echo "daily production incomplete: market=$market_status stock=$stock_status" >&2
  exit 1
fi
echo "[$(TZ=Asia/Shanghai /bin/date '+%F %T')] daily production complete"
