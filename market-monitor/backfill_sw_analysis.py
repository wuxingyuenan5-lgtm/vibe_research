#!/usr/bin/env python3
"""一次性历史补数：申万二级行业日度分析 2026-01-05 ~ 起补全。

sw_analysis_daily_second.csv 原只有 08-04 起（8 个交易日），四行业资金拥挤度图太短。
本脚本用 akshare index_analysis_daily_sw 分段拉取更早历史并合并去重写回。
用法: python backfill_sw_analysis.py [--start 2026-01-05] [--end 2026-08-03]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "data/history/sw_analysis_daily_second.csv"
BATCH_DAYS = 10  # 每批 10 个自然日（约 7 个交易日），控制接口压力


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-05")
    ap.add_argument("--end", default="2026-08-03")
    args = ap.parse_args()

    import akshare as ak

    # 已存在的历史日期（避免重复拉取）
    existing: set[str] = set()
    if HISTORY.exists():
        old = pd.read_csv(HISTORY, encoding="utf-8-sig")
        dc = next((c for c in ("发布日期", "日期", "date") if c in old.columns), None)
        if dc:
            existing = set(pd.to_datetime(old[dc], errors="coerce").dropna().dt.strftime("%Y-%m-%d"))

    start, end = parse(args.start), parse(args.end)
    batches: list[pd.DataFrame] = []
    cur = start
    while cur <= end:
        batch_end = min(cur + timedelta(days=BATCH_DAYS - 1), end)
        beg, ed = cur.strftime("%Y%m%d"), batch_end.strftime("%Y%m%d")
        try:
            df = ak.index_analysis_daily_sw(symbol="二级行业", start_date=beg, end_date=ed)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] {beg}~{ed} 拉取失败: {type(e).__name__} {str(e)[:100]}", file=sys.stderr)
            cur = batch_end + timedelta(days=1)
            continue
        if df is not None and not df.empty:
            dc = next((c for c in ("发布日期", "日期", "date") if c in df.columns), None)
            if dc:
                df[dc] = pd.to_datetime(df[dc], errors="coerce").dt.strftime("%Y-%m-%d")
                new_rows = df[~df[dc].isin(existing)]
                if not new_rows.empty:
                    batches.append(new_rows)
                    existing.update(new_rows[dc])
                    print(f"[OK] {beg}~{ed}: +{len(new_rows)} 行 (累计 {len(existing)} 个交易日)")
        cur = batch_end + timedelta(days=1)

    if not batches:
        print("无新增数据")
        return
    merged = pd.concat(batches, ignore_index=True, sort=False).drop_duplicates(keep="last")
    if HISTORY.exists():
        old = pd.read_csv(HISTORY, encoding="utf-8-sig")
        merged = pd.concat([old, merged], ignore_index=True, sort=False).drop_duplicates(keep="last")
    dc = next((c for c in ("发布日期", "日期", "date") if c in merged.columns), None)
    if dc:
        merged[dc] = pd.to_datetime(merged[dc], errors="coerce").dt.strftime("%Y-%m-%d")
        # 注意：只能按「整行完全重复」去重（canonical gate 规则），绝不能按日期列 subset——
        # 同一天有 131 个二级行业，按日期去重会把每天只剩 1 行，摧毁数据。
        merged = merged.sort_values(dc).drop_duplicates(keep="last")
    merged.to_csv(HISTORY, index=False, encoding="utf-8-sig")
    print(f"完成: sw_analysis_daily_second.csv 现 {len(merged)} 行, 日期 {merged[dc].min()} ~ {merged[dc].max()}")


if __name__ == "__main__":
    main()
