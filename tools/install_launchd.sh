#!/bin/bash
# 在【普通终端】里运行本脚本，把前后端注册为登录自启服务（launchd 托管，开机/登录自动启动 + 崩溃自动重启）。
# 注意：WorkBuddy 会话环境注册不了 launchd；请打开 macOS 的「终端」App 运行本脚本。
# 若之前已用 ./serve.sh start 跑过守护进程，请先 ./serve.sh stop 再执行本脚本（避免端口冲突）。
set -u

LA="$HOME/Library/LaunchAgents"
PL1="$LA/com.viberesearch.frontend.plist"
PL2="$LA/com.viberesearch.backend.plist"

if [ ! -f "$PL1" ] || [ ! -f "$PL2" ]; then
  echo "错误：找不到 LaunchAgent 配置（$PL1 / $PL2），请先确认项目已完整部署。"
  exit 1
fi

echo ">>> 注册前端服务 ..."
launchctl unload "$PL1" 2>/dev/null
launchctl load -w "$PL1" && echo "    frontend 已注册（登录自启 + 崩溃自动重启）"

echo ">>> 注册后端服务 ..."
launchctl unload "$PL2" 2>/dev/null
launchctl load -w "$PL2" && echo "    backend 已注册（登录自启 + 崩溃自动重启）"

sleep 5
echo ">>> 验证 ..."
curl -s -o /dev/null -w "    frontend :5899 → %{http_code}\n" --max-time 6 http://localhost:5899/ || echo "    frontend 未就绪"
curl -s -o /dev/null -w "    backend :8900 → %{http_code}\n" --max-time 6 http://127.0.0.1:8900/docs || echo "    backend 未就绪"

echo ""
echo "完成。以后开机/登录自动运行；日志: /tmp/vibe-frontend.log /tmp/vibe-backend.log"
echo "如需卸载自启：launchctl unload -w $PL1 $PL2"
