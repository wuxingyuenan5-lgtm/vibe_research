#!/usr/bin/env python3
"""Field-level audit for the repository's market and stock-pool mother tables."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


TARGET_SW = {"801102", "801101", "801083", "801081"}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty table: {path}")
    fields = list(rows[0])
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def number(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def dates(rows: Iterable[dict[str, str]], field: str) -> list[str]:
    return sorted({str(row.get(field) or "")[:10] for row in rows if row.get(field)})


def finding(severity: str, table: str, code: str, evidence: object) -> dict[str, object]:
    return {"severity": severity, "table": table, "code": code, "evidence": evidence}


def audit(root: Path, target_date: str, repair_safe: bool = False) -> dict[str, object]:
    paths = {
        "market_core": root / "market-monitor/data/history/market_core.csv",
        "hot_stocks": root / "market-monitor/data/history/hot_stocks.csv",
        "indices": root / "market-monitor/data/history/indices_history.csv",
        "limit_pool": root / "market-monitor/data/history/limit_pool.csv",
        "innovation": root / "market-monitor/data/history/innovation_drug_eastmoney.csv",
        "sw_analysis": root / "market-monitor/data/history/sw_analysis_daily_second.csv",
        "sw_industry": root / "market-monitor/data/sw_industry_history.csv",
    }
    rows = {name: read_rows(path) for name, path in paths.items()}
    calendar = [d for d in dates(rows["innovation"], "日期") if d <= target_date]
    calendar_set = set(calendar)
    findings: list[dict[str, object]] = []
    repairs: list[dict[str, object]] = []

    specs = {
        "market_core": ("date", ("date",), ("advance", "decline", "flat", "effective_stocks", "total_amount_100m", "market_breadth")),
        "hot_stocks": ("date", ("date", "stock_code"), ("rank", "stock_name", "close", "return", "amount_100m")),
        "indices": ("date", ("date", "name"), ("close", "return", "amount_100m")),
        "limit_pool": ("date", ("date", "direction", "stock_code"), ("stock_name", "close", "return", "amount_100m", "turnover")),
        "innovation": ("日期", ("日期",), ("收盘价", "成交量", "成交额", "日收益率", "换手率", "数据源")),
        "sw_analysis": ("发布日期", ("发布日期", "指数代码"), ("收盘指数", "涨跌幅", "成交额占比")),
        "sw_industry": ("日期", ("日期", "指数代码"), ("收盘价", "成交额")),
    }
    profiles: dict[str, object] = {}
    for name, (date_field, key_fields, required) in specs.items():
        table = rows[name]
        keys = [tuple(str(r.get(k) or "").strip() for k in key_fields) for r in table]
        duplicates = [key for key, count in Counter(keys).items() if count > 1]
        nulls = {field: sum(1 for r in table if str(r.get(field) or "").strip() == "") for field in required}
        table_dates = dates(table, date_field)
        profiles[name] = {
            "rows": len(table),
            "date_min": table_dates[0] if table_dates else None,
            "date_max": table_dates[-1] if table_dates else None,
            "date_count": len(table_dates),
            "duplicate_key_count": len(duplicates),
            "required_nulls": nulls,
        }
        if not table:
            findings.append(finding("CRITICAL", name, "missing_or_empty_table", str(paths[name])))
            continue
        if duplicates:
            findings.append(finding("CRITICAL", name, "duplicate_keys", duplicates[:20]))
        if table_dates and table_dates[-1] != target_date:
            findings.append(finding("HIGH", name, "stale_latest_date", {"expected": target_date, "actual": table_dates[-1]}))
        nonzero_nulls = {field: count for field, count in nulls.items() if count}
        if nonzero_nulls:
            findings.append(finding("HIGH", name, "required_nulls", nonzero_nulls))

    market_by_date = {r["date"]: r for r in rows["market_core"]}
    missing_market = [d for d in calendar if d not in market_by_date]
    if missing_market:
        findings.append(finding("HIGH", "market_core", "missing_trading_dates", missing_market))
    for day, row in market_by_date.items():
        advance, decline, flat, effective = (number(row.get(k)) for k in ("advance", "decline", "flat", "effective_stocks"))
        if None not in (advance, decline, flat, effective) and int(advance + decline + flat) != int(effective):
            findings.append(finding("CRITICAL", "market_core", "effective_stock_mismatch", day))
        breadth = number(row.get("market_breadth"))
        if None not in (advance, decline, breadth) and advance + decline:
            expected = (advance - decline) / (advance + decline)
            if abs(expected - breadth) > 1e-8:
                findings.append(finding("CRITICAL", "market_core", "breadth_mismatch", day))

    hot_by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows["hot_stocks"]:
        hot_by_date[row["date"]].append(row)
    for day, market in market_by_date.items():
        expected_count = number(market.get("hot_count"))
        if expected_count is None:
            continue
        actual = hot_by_date.get(day, [])
        if int(expected_count) != len(actual):
            findings.append(finding("HIGH", "hot_stocks", "count_mismatch", {"date": day, "expected": int(expected_count), "actual": len(actual)}))
        expected_amount = number(market.get("hot_amount_100m"))
        if expected_amount is not None:
            actual_amount = sum(number(r.get("amount_100m")) or 0 for r in actual)
            if abs(expected_amount - actual_amount) > 0.05:
                findings.append(finding("HIGH", "hot_stocks", "amount_mismatch", {"date": day, "expected": expected_amount, "actual": actual_amount}))

    innovation_bad = []
    for row in rows["innovation"]:
        values = {field: number(row.get(field)) for field in ("收盘价", "成交量", "成交额", "日收益率", "换手率")}
        if any(values[field] is None or values[field] <= 0 for field in ("收盘价", "成交量", "成交额")) or values["换手率"] is None or not 0 <= values["换手率"] <= 1 or values["日收益率"] is None or abs(values["日收益率"]) > 0.3 or "东方财富创新药BK1106" not in str(row.get("数据源") or ""):
            innovation_bad.append(row.get("日期"))
    if innovation_bad:
        findings.append(finding("CRITICAL", "innovation", "invalid_domain_or_source", innovation_bad))

    for name, date_field, code_field, expected_count in (
        ("sw_analysis", "发布日期", "指数代码", 4),
        ("sw_industry", "日期", "指数代码", 4),
    ):
        coverage = Counter()
        for row in rows[name]:
            code = str(row.get(code_field) or "").replace(".0", "")
            if code in TARGET_SW:
                coverage[str(row.get(date_field) or "")[:10]] += 1
        missing = [d for d in calendar if coverage[d] != expected_count]
        if missing:
            findings.append(finding("HIGH", name, "four_industry_date_gaps", missing))

    bad_sector_rows = []
    for row in rows["sw_analysis"]:
        code = str(row.get("指数代码") or "").replace(".0", "")
        day = str(row.get("发布日期") or "")[:10]
        if code not in TARGET_SW or day not in calendar_set:
            continue
        source = str(row.get("数据源") or "")
        source_ok = "东方财富行业板块" in source or "Choice申万二级指数历史修复" in source
        if (
            number(row.get("成交额")) is None
            or number(row.get("换手率")) is None
            or number(row.get("成交额占比")) is None
            or not source_ok
        ):
            bad_sector_rows.append({"date": day, "code": code})
    if bad_sector_rows:
        findings.append(finding("CRITICAL", "sw_analysis", "four_sector_not_uniform_eastmoney", bad_sector_rows[:40]))

    severity_order = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
    counts = Counter(item["severity"] for item in findings)
    status = "FAIL" if any(severity_order[item["severity"]] >= 2 for item in findings) else "PASS"
    return {
        "target_date": target_date,
        "status": status,
        "calendar_source": "innovation_drug_eastmoney direct-date mother table",
        "calendar_dates": len(calendar),
        "profiles": profiles,
        "findings": findings,
        "finding_counts": dict(counts),
        "repairs": repairs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-date", required=True)
    # The GitHub workflow runs with ``market-monitor`` as its working directory,
    # while ``audit`` resolves paths from the repository root.  Anchor the
    # default to this file instead of the caller's current directory so local
    # and CI executions inspect the same canonical tables.
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default="")
    parser.add_argument("--repair-safe", action="store_true")
    args = parser.parse_args()
    report = audit(Path(args.root).resolve(), args.target_date, args.repair_safe)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
