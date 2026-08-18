#!/usr/bin/env python3
"""每日数据同步：采集当日数据 → 更新后端 canonical → 提交推送 GitHub（多设备数据中枢）。

流程：
1. 核心股票池日更：python -m market_monitor.daily_refresh --date <today>
2. Canonical 采集：market-monitor/run_daily.py --target-date <today>
   （市场/指数/百亿成交/创新药/申万分析 → market-monitor/data/history/）
3. 同步 market-monitor/data → backend/data/market-monitor/data
   （canonical 单一真源，后端 /api/market-monitor 读的正是 backend/data/market-monitor/）
4. 删除后端 snapshot（backend/data/market-monitor/output/<date>/report_data.json）
   —— API 下次请求自动重建，保证数据即时生效
5. git add backend/data/market-monitor + commit + push backup（vibe_research）

用法：python backend/tools/daily_data_sync.py [--date YYYY-MM-DD] [--skip-push]
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

SYNC_DIRS = ["data", "sw_industry_history.csv", "sw_industry_latest.csv"]
# data/ 内含 history/ 与 cache/；同步时排除明显运行时产物（如 .bak）


def _run(cmd: list[str], label: str, cwd: Path | None = None) -> None:
    print(f"[1/5] {label} ...", flush=True)
    r = subprocess.run(cmd, cwd=cwd or PROJECT, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠ {label} 非零退出({r.returncode})：{r.stderr[-300:]}", file=sys.stderr)
        # 采集失败不中断后续（网络抖动常见），但记录
    else:
        tail = r.stdout.strip().splitlines()
        print(f"  ok: {tail[-1] if tail else ''}", flush=True)


def sync_market_data() -> None:
    """market-monitor/data → backend/data/market-monitor/data（含 history/cache）。"""
    print("[3/5] 同步 canonical 到后端数据 ...", flush=True)
    src, dst = MARKET_MONITOR / "data", BACKEND_DATA / "data"
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)
    for f in ("sw_industry_history.csv", "sw_industry_latest.csv"):
        shutil.copy2(MARKET_MONITOR / "data" / f, BACKEND_DATA / f)
    print("  ok: canonical 已同步到 backend/data/market-monitor/data", flush=True)


def clear_snapshot(target_date: str) -> None:
    """删后端 snapshot，让 API 下次请求自动重建（保证新数据即时生效）。"""
    snap = BACKEND_DATA / "output" / target_date / "report_data.json"
    if snap.exists():
        snap.unlink()
        print(f"[4/5] 已删除旧 snapshot {snap}（API 将重建）", flush=True)
    else:
        print("[4/5] 无旧 snapshot，跳过", flush=True)


def git_push() -> None:
    print("[5/5] git commit + push backup ...", flush=True)
    r = subprocess.run(["git", "add", "backend/data/market-monitor/"], cwd=PROJECT, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠ git add 失败: {r.stderr[-200:]}", file=sys.stderr)
        return
    r = subprocess.run(["git", "status", "--porcelain"], cwd=PROJECT, capture_output=True, text=True)
    changes = [ln for ln in r.stdout.splitlines() if "backend/data/market-monitor" in ln]
    if not changes:
        print("  无数据变更，跳过 commit/push", flush=True)
        return
    msg = f"data: 每日市场监控数据同步 {datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')}"
    subprocess.run(["git", "commit", "-m", msg], cwd=PROJECT, capture_output=True, text=True)
    # 背景：步骤1 daily_refresh 会先用 GitHub Contents API 提交"股票池快照"（data/stock-pool/），
    # 把远程 backup/main 推进一个 commit；本地 git push（backend/data/market-monitor/）因此可能
    # non-fast-forward。两边文件不重叠，自动 fetch+merge 后重试即可，无需人工介入。
    for attempt in range(3):
        r = subprocess.run(["git", "push", "backup", "main"], cwd=PROJECT, capture_output=True, text=True)
        if r.returncode == 0:
            print(f"  ok: 已推送 backup/main（{msg}）", flush=True)
            return
        if attempt >= 2:
            break
        print(f"  ~ push 被拒（第 {attempt + 1}/3 次），fetch+merge 远端 backup/main 后重试 ...", flush=True)
        subprocess.run(["git", "fetch", "backup"], cwd=PROJECT, capture_output=True, text=True)
        m = subprocess.run(
            ["git", "merge", "backup/main", "--no-edit", "-m", "merge: 同步远端 backup/main（push 重试）"],
            cwd=PROJECT,
            capture_output=True,
            text=True,
        )
        if m.returncode != 0:
            print(f"  ⚠ merge 冲突，已保留本地改动待人工处理: {m.stderr[-200:]}", file=sys.stderr)
            return
    print(f"  ⚠ push 失败(3 次重试后): {r.stderr[-300:]}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"))
    ap.add_argument("--skip-push", action="store_true", help="只更新本地数据，不 push")
    ap.add_argument("--skip-collect", action="store_true", help="跳过采集（只同步+提交）")
    args = ap.parse_args()

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

    sync_market_data()
    clear_snapshot(args.date)
    if not args.skip_push:
        git_push()
    else:
        print("[5/5] --skip-push：未推送（本地数据已更新）", flush=True)


if __name__ == "__main__":
    main()
