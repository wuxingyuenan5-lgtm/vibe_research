from __future__ import annotations

import csv
from pathlib import Path

INDEX_NAMES = ("上证50", "中证2000", "中证全指")
INDEX_REQUIRED_FIELDS = ("return", "amount_100m")
INDEX_HISTORY_WINDOW = 5
MARKET_CORE_FILE = "market_core.csv"
MARKET_VERIFIED_BACKFILL_FILE = "market_core_verified_backfill.csv"


def _float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_market_core_rows(root: Path) -> list[dict[str, str]]:
    """Canonical market-core history，verified backfill 覆盖层叠加。"""
    history_dir = root / "data" / "history"
    merged: dict[str, dict[str, str]] = {}
    for filename in (MARKET_CORE_FILE, MARKET_VERIFIED_BACKFILL_FILE):
        for row in _read_csv(history_dir / filename):
            d = str(row.get("date") or "")[:10]
            if d:
                merged[d] = dict(row)
    return [merged[d] for d in sorted(merged)]


def read_index_history(path: Path) -> list[dict[str, object]]:
    out = []
    for row in _read_csv(path):
        out.append({
            "date": str(row.get("date") or ""),
            "name": str(row.get("name") or ""),
            "code": str(row.get("code") or ""),
            "close": _float(row.get("close")),
            "return": _float(row.get("return")),
            "amount_100m": _float(row.get("amount_100m")),
            "source": str(row.get("source") or ""),
            "status": str(row.get("status") or ""),
        })
    out.sort(key=lambda r: (str(r["date"]), str(r["name"])))
    return out


def _market_amount_dates(rows: list[dict[str, str]]) -> set[str]:
    out = set()
    for row in rows:
        d = str(row.get("date") or "")[:10]
        if d and _float(row.get("total_amount_100m")) is not None:
            out.add(d)
    return out


def _innovation_amount_dates(path: Path, report_date: str) -> set[str]:
    out = set()
    for row in _read_csv(path):
        d = str(row.get("日期") or row.get("date") or "")[:10]
        raw = row.get("成交额") if "成交额" in row else row.get("amount_100m")
        if d and d <= report_date and _float(raw) is not None:
            out.add(d)
    return out


def scan_history_gaps(root: Path, report_date: str, required_index_dates: list[str] | None = None) -> dict[str, object]:
    """扫描展示相关历史缺口（只读，无网络调用）。"""
    history_dir = root / "data" / "history"
    market_rows = read_market_core_rows(root)
    market_dates = [str(r.get("date") or "")[:10] for r in market_rows if r.get("date") and str(r.get("date"))[:10] <= report_date]
    dates_to_scan = required_index_dates if required_index_dates is not None else market_dates[-INDEX_HISTORY_WINDOW:]
    index_rows = read_index_history(history_dir / "indices_history.csv")
    by_key = {(str(r["date"]), str(r["name"])): r for r in index_rows}
    index_gaps = []
    for d in dates_to_scan:
        for name in INDEX_NAMES:
            row = by_key.get((d, name))
            missing = [field for field in INDEX_REQUIRED_FIELDS if not row or row.get(field) is None]
            if missing:
                index_gaps.append({"date": d, "name": name, "fields": missing})
    denominator_gaps = sorted(
        _innovation_amount_dates(history_dir / "innovation_drug_eastmoney.csv", report_date)
        - _market_amount_dates(market_rows)
    )
    return {"report_date": report_date, "indices": index_gaps, "market_denominator_dates": denominator_gaps}
