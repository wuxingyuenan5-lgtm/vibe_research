#!/bin/bash
# 注册本地自选股盘后任务。市场母表由 GitHub 生产、网页后端按需同步。
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
agent_dir="$HOME/Library/LaunchAgents"
for name in stock-production; do
  source="$project_dir/tools/launchd/com.viberesearch.${name}.plist"
  target="$agent_dir/com.viberesearch.${name}.plist"
  /bin/mkdir -p "$agent_dir"
  /bin/chmod 755 "$project_dir/tools/run_local_production.sh"
  /bin/cp "$source" "$target"
  /bin/chmod 644 "$target"
  /bin/launchctl bootout "gui/$(id -u)" "$target" 2>/dev/null || true
  /bin/launchctl bootstrap "gui/$(id -u)" "$target"
  echo "已注册 com.viberesearch.${name}"
done
