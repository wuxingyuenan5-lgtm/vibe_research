#!/bin/bash
# Vibe-Research 前后端服务开关（守护进程模式：开启后不随会话断，崩溃自动重启）
# 用法: ./serve.sh {start|stop|restart|status}
set -u

PY=/Users/zhangxu/.workbuddy/binaries/python/versions/3.13.12/bin/python3
DAEMON="$(cd "$(dirname "$0")" && pwd)/serve_daemon.py"

case "${1:-}" in
  start)
    "$PY" "$DAEMON" --start
    sleep 6
    "$PY" "$DAEMON" --status
    ;;
  stop)
    "$PY" "$DAEMON" --stop
    ;;
  restart)
    "$PY" "$DAEMON" --stop
    sleep 1
    "$PY" "$DAEMON" --start
    sleep 6
    "$PY" "$DAEMON" --status
    ;;
  status)
    "$PY" "$DAEMON" --status
    ;;
  *)
    echo "用法: ./serve.sh {start|stop|restart|status}"
    echo "  start    开启前后端（已开启则自动忽略，不会重复启动）"
    echo "  stop     关闭前后端"
    echo "  restart  重启前后端（改完后端代码后用它）"
    echo "  status   查看当前状态"
    exit 1
    ;;
esac
