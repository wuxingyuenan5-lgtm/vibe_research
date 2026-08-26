#!/usr/bin/env python3
"""本地市场数据诊断工具（正式生产只允许 GitHub Actions 执行）。

流程：
1. 核心股票池日更：python -m market_monitor.daily_refresh --date <today>
2. Canonical 采集：market-monitor/run_daily.py --target-date <today>
   （市场/指数/百亿成交/创新药/申万分析 → market-monitor/data/history/）
3. 从同一套 market-monitor/data 母表生成报告并校验（不复制后端镜像）
4. 不提交、不推送；检查结果仅保留在本地工作区供排障。

用法：python backend/tools/daily_data_sync.py --diagnostic-only [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parent.parent.parent   # Vibe-Research/
MARKET_MONITOR = PROJECT / "market-monitor"              # HTML 链（采集真源）
BACKEND_DATA = PROJECT / "backend/data/market-monitor"   # 后端数据（API 读它）

def _run(cmd: list[str], label: str, cwd: Path | None = None) -> None:
    print(f"[diagnostic] {label} ...", flush=True)
    r = subprocess.run(cmd, cwd=cwd or PROJECT, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠ {label} 非零退出({r.returncode})：{r.stderr[-300:]}", file=sys.stderr)
        # 采集失败不中断后续（网络抖动常见），但记录
    else:
        tail = r.stdout.strip().splitlines()
        print(f"  ok: {tail[-1] if tail else ''}", flush=True)


def sync_morning_brief() -> None:
    """晨报 payload（可选）：若根 market-monitor/morning-brief 存在则同步到后端。
    由统一晨报生产链（unified_morning）输出；未输出时跳过，不影响其他步骤。"""
    src = MARKET_MONITOR / "morning-brief"
    dst = BACKEND_DATA / "morning-brief"
    if not src.exists():
        print("  skip: 无 market-monitor/morning-brief（晨报生产链未输出 payload）", flush=True)
        return
    dst.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print("  ok: morning-brief 已同步到后端", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"))
    ap.add_argument("--diagnostic-only", action="store_true", help="确认这是本地诊断，不属于正式生产")
    ap.add_argument("--skip-push", action="store_true", help="兼容旧命令；本工具现在始终不 push")
    ap.add_argument("--skip-collect", action="store_true", help="跳过采集，仅检查已有唯一母表")
    args = ap.parse_args()

    if not args.diagnostic_only:
        ap.error("正式生产只允许 GitHub Actions；本地排障请显式添加 --diagnostic-only")

    if not args.skip_collect:
        _run(
            [sys.executable, "-m", "market_monitor.daily_refresh", "--date", args.date],
            "核心股票池日更",
            cwd=PROJECT / "backend",
        )
        _run(
            [sys.executable, str(MARKET_MONITOR / "run_daily.py"), "--target-date", args.date],
            "Canonical 采集（市场/指数/百亿/创新药/申万）",
            cwd=MARKET_MONITOR,
        )

    sync_morning_brief()
    print("本地诊断完成：唯一母表仍为 market-monitor/data；未复制、未 commit、未 push", flush=True)


if __name__ == "__main__":
    main()
