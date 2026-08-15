#!/bin/bash
# Vibe-Research 一键启动脚本（双击或终端运行均可）
# 后端 :8900  前端 :5899
# 进程用 nohup 拉起，关闭终端也不会掉；停止用 stop.command 或 kill 掉对应端口

set -e
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
LOG_DIR="$PROJECT_DIR/.logs"
mkdir -p "$LOG_DIR"

# --- 选 npm：优先 PATH 上的，没有就用 managed 版本 ---
NPM_BIN="$(command -v npm 2>/dev/null || true)"
if [ -z "$NPM_BIN" ]; then
  NPM_BIN="/Users/zhangxu/.workbuddy/binaries/node/versions/22.22.2/bin/npm"
fi

# --- 端口占用检测，已在跑就跳过 ---
port_alive() { curl -s -o /dev/null -m 2 "http://127.0.0.1:$1/" >/dev/null 2>&1 || curl -s -o /dev/null -m 2 "http://127.0.0.1:$1/docs" >/dev/null 2>&1; }

echo "==> Vibe-Research 启动中..."

if port_alive 8900; then
  echo "    后端 :8900 已在运行，跳过"
else
  echo "    启动后端 :8900"
  cd "$BACKEND_DIR"
  nohup .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8900 > "$LOG_DIR/backend.log" 2>&1 &
  echo $! > "$LOG_DIR/backend.pid"
  disown
fi

if port_alive 5899; then
  echo "    前端 :5899 已在运行，跳过"
else
  echo "    启动前端 :5899"
  cd "$FRONTEND_DIR"
  nohup "$NPM_BIN" run dev -- --port 5899 > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$LOG_DIR/frontend.pid"
  disown
fi

# --- 等待就绪 ---
echo "    等待服务就绪..."
for i in $(seq 1 30); do
  port_alive 8900 && port_alive 5899 && break
  sleep 1
done

if port_alive 8900 && port_alive 5899; then
  echo ""
  echo "✅ 启动成功"
  echo "   前端：    http://localhost:5899"
  echo "   后端 API：http://127.0.0.1:8900/docs"
  echo "   日志：    $LOG_DIR/{backend,frontend}.log"
  # 自动打开浏览器
  open "http://localhost:5899/" 2>/dev/null || true
else
  echo ""
  echo "⚠️  启动可能未完成，请查看日志：$LOG_DIR/"
  echo "   后端状态: $(port_alive 8900 && echo OK || echo 未就绪)"
  echo "   前端状态: $(port_alive 5899 && echo OK || echo 未就绪)"
fi
