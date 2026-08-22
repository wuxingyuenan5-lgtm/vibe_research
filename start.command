#!/bin/bash
# Vibe-Research 一键启动（统一走 serve_daemon 守护：崩溃自动重启、环境固定直连）
# 后端 :8900  前端 :5899
cd "$(dirname "$0")"
bash tools/serve.sh start
open "http://localhost:5899/" 2>/dev/null || true
