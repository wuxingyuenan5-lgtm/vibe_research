#!/bin/bash
# Vibe-Research 一键停止（统一走 serve_daemon）
cd "$(dirname "$0")"
bash tools/serve.sh stop
