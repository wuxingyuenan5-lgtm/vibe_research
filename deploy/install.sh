#!/usr/bin/env bash
# 安装/重新安装 Vibe-Research 的 4 个 LaunchAgent。
#
# 用途：deploy/*.plist 是模板，其中的 __PROJECT_DIR__ 占位符在安装时被替换为
#       本仓库的实际绝对路径。因此项目目录被移动后，只需在新目录重新运行本脚本，
#       不需要手工修改任何绝对路径。__HOME__ 占位符替换为当前用户家目录。
#
# 用法： bash deploy/install.sh
#       bash deploy/install.sh --uninstall   # 只卸载不安装
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_DIR="$HOME/Library/LaunchAgents"
LABELS=(frontend backend postgres daily-production)

uninstall() {
  for label in "${LABELS[@]}"; do
    local dest="$AGENT_DIR/com.viberesearch.$label.plist"
    launchctl unload "$dest" 2>/dev/null || true
    rm -f "$dest"
  done
}

if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall
  echo "uninstalled 4 agents"
  exit 0
fi

# 前置步骤：停掉手工启动的本项目进程（仅匹配 cwd 在本项目内的进程，避免误杀）
stop_manual() {
  local port pid cwd
  for port in 54329 8900 5899; do
    pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
    [[ -z "$pid" ]] && continue
    cwd="$(lsof -p "$pid" -a -d cwd -Fn 2>/dev/null | tail -1 | sed 's/^n//')"
    if [[ "$cwd" == "$PROJECT_DIR"* ]]; then
      kill "$pid" 2>/dev/null || true
      echo "stopped manual process on :$port (pid $pid)"
    else
      echo "WARN: port $port held by unrelated process (pid $pid, cwd=$cwd) — 未处理" >&2
    fi
  done
  sleep 3
}
stop_manual

# 加载顺序：postgres -> backend -> frontend -> daily-production
for label in "${LABELS[@]}"; do
  src="$SCRIPT_DIR/com.viberesearch.$label.plist"
  dest="$AGENT_DIR/com.viberesearch.$label.plist"
  [[ -f "$src" ]] || { echo "missing template: $src" >&2; exit 1; }

  launchctl unload "$dest" 2>/dev/null || true
  # 复用本机已配置的数据库连接串（不写入仓库模板）。首次安装时可能为空。
  db_url="$(plutil -extract EnvironmentVariables.VR_DATABASE_URL raw "$dest" 2>/dev/null || true)"
  # 只替换占位符，其余内容（端口、环境变量、调度时间）原样保留
  sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$src" > "$dest"
  if grep -q "__VR_DATABASE_URL__" "$dest" 2>/dev/null; then
    if [[ -n "$db_url" ]]; then
      DB_URL="$db_url" perl -0777 -pi -e 's/__VR_DATABASE_URL__/$ENV{DB_URL}/g' "$dest"
    else
      echo "WARN: $label 模板含 __VR_DATABASE_URL__ 但本机无既有连接串，请在 $dest 手工补全" >&2
    fi
  fi
  launchctl load "$dest"
  echo "installed com.viberesearch.$label -> $PROJECT_DIR"
done

echo
echo "project dir : $PROJECT_DIR"
echo "postgres    : 127.0.0.1:54329 (data: $PROJECT_DIR/.local/postgres)"
echo "backend     : http://127.0.0.1:8900"
echo "frontend    : http://127.0.0.1:5899"
