#!/usr/bin/env python3
"""本地市场数据诊断工具（正式生产只允许 GitHub Actions 执行）。

流程：
1. 核心股票池日更：python -m market_monitor.daily_refresh --date <today>
2. Canonical 采集：market-monitor/run_daily.py --target-date <today>
   （市场/指数/百亿成交/创新药/申万分析 → market-monitor/data/history/）
3. 同步 market-monitor/data → backend/data/market-monitor/data
   （canonical 单一真源，后端 /api/market-monitor 读的正是 backend/data/market-monitor/）
4. 删除后端 snapshot（backend/data/market-monitor/output/<date>/report_data.json）
   —— API 下次请求自动重建，保证数据即时生效
5. 不提交、不推送；检查结果仅保留在本地工作区供排障。

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


def clear_snapshot(target_date: str) -> None:
    """清空后端 output 目录所有旧 snapshot，让 API 下次请求自动重建最新（保证新数据即时生效）。

    只删 target_date 日期的快照删不干净——旧快照可能早于当天（历史遗留，如 8/18），
    日期不匹配就永远留着，API 会一直读旧快照。故全清，API 从最新 history 现场重建。
    """
    out_root = BACKEND_DATA / "output"
    removed = 0
    if out_root.exists():
        for snap in out_root.glob("*/report_data.json"):
            snap.unlink()
            removed += 1
        # 顺手清理空快照目录（保留 stock-pool）
        for d in out_root.iterdir():
            if d.is_dir() and d.name != "stock-pool" and not any(d.iterdir()):
                d.rmdir()
    print(f"[4/5] 已清理 {removed} 个旧 snapshot（API 将自动重建最新）", flush=True)


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
    ap.add_argument("--diagnostic-only", action="store_true", help="确认这是本地诊断，不属于正式生产")
    ap.add_argument("--skip-push", action="store_true", help="兼容旧命令；本工具现在始终不 push")
    ap.add_argument("--skip-collect", action="store_true", help="跳过采集（只同步+提交）")
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

    sync_market_data()
    sync_morning_brief()
    clear_snapshot(args.date)
    print("[5/5] 本地诊断完成：未 commit、未 push；正式数据等待 GitHub Actions 发布", flush=True)


if __name__ == "__main__":
    main()
