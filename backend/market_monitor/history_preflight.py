from __future__ import annotations

import csv
from pathlib import Path


MARKET_CORE_FILE = "market_core.csv"


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
    """Read the single canonical market-core history."""
    return _read_csv(root / "data" / "history" / MARKET_CORE_FILE)


def _market_amount_dates(rows: list[dict[str, str]]) -> set[str]:
    return {
        str(row.get("date") or "")[:10]
        for row in rows
        if str(row.get("date") or "")[:10]
        and _float(row.get("total_amount_100m")) is not None
    }


def _innovation_amount_dates(path: Path, report_date: str) -> set[str]:
    out = set()
    for row in _read_csv(path):
        date = str(row.get("日期") or row.get("date") or "")[:10]
        raw_amount = row.get("成交额") if "成交额" in row else row.get("amount_100m")
        if date and date <= report_date and _float(raw_amount) is not None:
            out.add(date)
    return out


def scan_history_gaps(root: Path, report_date: str) -> dict[str, object]:
    """Report only real denominator gaps in the active mother tables."""
    history_dir = root / "data" / "history"
    market_rows = read_market_core_rows(root)
    denominator_gaps = sorted(
        _innovation_amount_dates(history_dir / "innovation_drug_eastmoney.csv", report_date)
        - _market_amount_dates(market_rows)
    )
    return {"report_date": report_date, "market_denominator_dates": denominator_gaps}
