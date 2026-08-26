#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Callable
from zoneinfo import ZoneInfo

from market_monitor.production import run
from market_monitor.history_preflight import append_index_history
from market_monitor.canonical_store import CANONICAL_TABLES, normalize_candidate, read_csv_rows
from market_monitor.canonical_validation import validate_candidate
from market_monitor.sw_cache import refresh_sw_cache
from market_monitor.collectors import update_limit_pool_history
from build_report_data import append_hot_stock_history
from update_sw_industry_fast import update as update_sw_industry_fast
from update_sw_industry import update as update_sw_industry_full


def default_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A股每日监控一键数据生产")
    parser.add_argument("--target-date", default=default_date(), help="YYYY-MM-DD；正式日更只允许中国时区当天")
    parser.add_argument("--config", default="config/market_monitor.json")
    parser.add_argument("--refresh-mapping", action="store_true")
    parser.add_argument("--full-refresh-sw-industry", action="store_true")
    parser.add_argument("--force-hot-snapshot", action="store_true", help="非周五也归档百亿成交明细")
    return parser.parse_args()


def refresh_sources(
    root: Path,
    target_date: str,
    full_refresh_sw_industry: bool = False,
    crowding_refresh_fn: Callable = refresh_sw_cache,
    fast_industry_refresh_fn: Callable = update_sw_industry_fast,
    full_industry_refresh_fn: Callable = update_sw_industry_full,
) -> dict[str, object]:
    """Refresh mutable sources in the one canonical data directory."""
    root = Path(root).resolve()
    data_dir = root / "data"
    result: dict[str, object] = {"warnings": []}

    try:
        crowding_refresh_fn(
            target_date,
            cache_path=data_dir / "cache/sw_analysis_daily_second.csv",
            history_path=data_dir / "history/sw_analysis_daily_second.csv",
        )
        result["sw_crowding"] = "ok"
    except Exception as exc:
        result["sw_crowding"] = "fallback_previous_canonical"
        result["warnings"].append(f"sw_crowding_refresh_failed:{exc}")

    try:
        if full_refresh_sw_industry:
            full_industry_refresh_fn(
                history_rows=260,
                sleep_seconds=0.15,
                workers=4,
                data_dir=data_dir,
            )
            result["sw_industry"] = "ok_full"
        else:
            fast_industry_refresh_fn(target_date, data_dir=data_dir)
            result["sw_industry"] = "ok_fast"
    except Exception as exc:
        result["sw_industry"] = "fallback_previous_canonical"
        result["warnings"].append(f"sw_industry_refresh_failed:{exc}")

    return result


def _archive_raw_outputs(output_dir: Path) -> None:
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.iterdir():
        if not path.is_file():
            continue
        shutil.copy2(path, raw_dir / path.name)


def _baseline_rows(root: Path) -> dict[str, list[dict[str, str]]]:
    return {
        name: read_csv_rows(root / spec.path)
        for name, spec in CANONICAL_TABLES.items()
    }


def main() -> None:
    args = parse_args()
    today = default_date()
    if args.target_date != today:
        raise SystemExit(
            f"daily pipeline uses a current-day stock snapshot, so target_date must be {today}; "
            "use the historical backfill workflow for older dates"
        )

    repo_root = Path(".").resolve()
    config_path = (repo_root / args.config).resolve()
    baseline_rows = _baseline_rows(repo_root)
    source_refresh = refresh_sources(
        root=repo_root,
        target_date=args.target_date,
        full_refresh_sw_industry=args.full_refresh_sw_industry,
    )

    result = run(
        target_date=args.target_date,
        config_path=config_path,
        root=repo_root,
        refresh_mapping=args.refresh_mapping,
    )
    payload = result["payload"]
    append_index_history(
        repo_root / "data/history/indices_history.csv",
        list((payload.get("indices") or {}).values()),
    )
    # 百亿成交股是每日母表，不是周五快照。每天按 date+stock_code upsert。
    append_hot_stock_history(
        repo_root / "data/history/hot_stocks.csv",
        args.target_date,
        payload.get("hot_stocks") or [],
    )
    update_limit_pool_history(
        repo_root / "data/history/limit_pool.csv",
        args.target_date,
        payload.get("limit_pool") or [],
    )

    output_dir = repo_root / "output" / args.target_date
    output_dir.mkdir(parents=True, exist_ok=True)
    _archive_raw_outputs(output_dir)

    normalization = normalize_candidate(repo_root)
    canonical_validation = validate_candidate(
        repo_root,
        repo_root,
        args.target_date,
        baseline_rows=baseline_rows,
    )
    canonical_validation["normalization"] = normalization
    canonical_validation["source_refresh"] = source_refresh
    canonical_validation["warnings"] = list(dict.fromkeys(
        list(canonical_validation.get("warnings") or []) + list(source_refresh.get("warnings") or [])
    ))
    if canonical_validation["status"] != "FAIL" and canonical_validation["warnings"]:
        canonical_validation["status"] = "WARN"

    validation_path = output_dir / "canonical_validation.json"
    validation_path.write_text(
        json.dumps(canonical_validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if canonical_validation["status"] == "FAIL":
        failures = "; ".join(canonical_validation.get("failures") or [])
        raise RuntimeError(f"canonical validation failed; GitHub mother tables will not be committed: {failures}")

    payload_validation = result["validation"]
    removed = sum(int(item.get("removed_identical_rows") or 0) for item in normalization.values())
    print(
        f"completed date={args.target_date} payload_status={payload_validation['status']} "
        f"canonical_status={canonical_validation['status']} identical_duplicates_removed={removed} "
        f"sw_crowding={source_refresh['sw_crowding']} sw_industry={source_refresh['sw_industry']} "
        "innovation=direct_eastmoney_only "
        f"output={output_dir}"
    )


if __name__ == "__main__":
    main()
