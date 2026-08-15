#!/bin/bash
# Vibe-Research 一键停止脚本
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/.logs"

echo "==> 停止 Vibe-Research..."

# 优先用记录的 pid
for name in backend frontend; do
  pidfile="$LOG_DIR/$name.pid"
  if [ -f "$pidfile" ]; then
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && echo "    已停止 $name (pid $pid)"
    fi
    rm -f "$pidfile"
  fi
done

# 兜底：按端口杀
for port in 8900 5899; do
  pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null && echo "    端口 $port 进程已清理"
  fi
done

echo "✅ 已停止"
