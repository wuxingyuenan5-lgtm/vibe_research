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

# 两条正式 CSV 生产链独立运行；市场链失败不阻断自选股更新，反之亦然。
market_status=0
stock_status=0
run_with_retry market || market_status=$?
run_with_retry stock || stock_status=$?

if [ "$market_status" != "0" ] || [ "$stock_status" != "0" ]; then
  echo "daily production incomplete: market=$market_status stock=$stock_status" >&2
  exit 1
fi

# 数据库仍是影子库：只有两条正式 CSV 链均成功才镜像和对账；失败不会影响正式更新。
if [ -n "${VR_DATABASE_URL:-}" ]; then
  echo "[$(TZ=Asia/Shanghai /bin/date '+%F %T')] shadow database import"
  if (cd "$project_dir/backend" && "$python_bin" -m data_platform.shadow_import --target-date "$target_date"); then
    echo "[$(TZ=Asia/Shanghai /bin/date '+%F %T')] shadow database import complete"
    if (cd "$project_dir/backend" && "$python_bin" -m data_platform.shadow_reconciliation --target-date "$target_date"); then
      echo "[$(TZ=Asia/Shanghai /bin/date '+%F %T')] shadow database reconciliation passed"
    else
      echo "[WARN] shadow database reconciliation failed; formal CSV production remains complete" >&2
    fi
  else
    echo "[WARN] shadow database import failed; formal CSV production remains complete" >&2
  fi
fi

echo "[$(TZ=Asia/Shanghai /bin/date '+%F %T')] daily production complete"
