from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

STOCK_FIELDS = (
    "instrument_id", "code", "exchange", "name", "industry", "price", "change",
    "change_5d", "change_20d", "ytd", "amount_yi", "mcap_yi", "turnover",
    "pe_ttm", "pb", "data_status",
)
INDEX_FIELDS = (
    "code", "name", "price", "change", "change_5d", "change_20d", "change_60d",
    "ytd", "amount_yi", "turnover", "pe_ttm", "pb", "mcap_yi", "data_status", "source",
)
LEADER_COUNT = 8


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def build_stock_pool_payload(root: Path = Path(".")) -> dict[str, Any]:
    data_dir = root / "stock-pool"
    stocks_raw = _read_csv(data_dir / "stocks.csv")
    indices_raw = _read_csv(data_dir / "indices.csv")

    stocks: list[dict[str, Any]] = []
    for raw in stocks_raw:
        row: dict[str, Any] = {
            "instrument_id": _str(raw.get("instrument_id")) or f"legacy:{raw.get('name')}",
            "code": _str(raw.get("code")),
            "exchange": _str(raw.get("exchange")),
            "name": _str(raw.get("name")) or "",
            "industry": _str(raw.get("industry")) or "",
        }
        for field in ("price", "change", "change_5d", "change_20d", "ytd", "amount_yi",
                      "mcap_yi", "turnover", "pe_ttm", "pb"):
            row[field] = _num(raw.get(field))
        row["data_status"] = _str(raw.get("data_status")) or ""
        stocks.append(row)

    indices: list[dict[str, Any]] = []
    for raw in indices_raw:
        row: dict[str, Any] = {"code": _str(raw.get("code")) or "", "name": _str(raw.get("name")) or ""}
        for field in ("price", "change", "change_5d", "change_20d", "change_60d", "ytd",
                      "amount_yi", "turnover", "pe_ttm", "pb", "mcap_yi"):
            row[field] = _num(raw.get(field))
        row["data_status"] = _str(raw.get("data_status")) or ""
        row["source"] = _str(raw.get("source")) or ""
        indices.append(row)

    # summary / breadth
    changes = [s["change"] for s in stocks if s["change"] is not None]
    up = sum(1 for c in changes if c > 0)
    down = sum(1 for c in changes if c < 0)
    flat = sum(1 for c in changes if c == 0)
    sorted_changes = sorted(changes)
    n = len(sorted_changes)
    median = sorted_changes[n // 2] if n else None
    avg_change = sum(changes) / n if n else None
    total_amount = sum(s["amount_yi"] for s in stocks if s["amount_yi"] is not None)

    summary = {
        "tracked_count": len(stocks),
        "breadth": {"count": n, "up": up, "down": down, "flat": flat, "median": median},
        "avg_change": avg_change,
        "total_amount_yi": round(total_amount, 2),
        "pending_refresh": 0,
        "legacy_missing_code": sum(1 for s in stocks if not s.get("code")),
    }

    # heatmap（weight = 市值）
    heatmap = [
        {"instrument_id": s["instrument_id"], "name": s["name"], "industry": s["industry"],
         "change": s["change"], "weight": s["mcap_yi"] or 1}
        for s in stocks if s["change"] is not None
    ]

    # leaders：今日最强 / 最弱
    ranked = sorted([s for s in stocks if s["change"] is not None], key=lambda s: s["change"], reverse=True)
    leaders = {"up": ranked[:LEADER_COUNT], "down": ranked[-LEADER_COUNT:][::-1]}

    # industry_ranking（备用，JS 实际用 indices）
    industry_ranking = indices

    return {
        "meta": {
            "report_date": datetime.now().astimezone().strftime("%Y-%m-%d"),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "version": "0.1.0",
            "percent_contract": "decimal_ratio",
        },
        "summary": summary,
        "stocks": stocks,
        "indices": indices,
        "heatmap": heatmap,
        "industry_ranking": industry_ranking,
        "leaders": leaders,
        "default_index_selfselect": [i["code"] for i in indices if i["code"]],
    }


def build_stock_pool_payload_file(root: Path = Path("."), out: Path | None = None) -> Path:
    payload = build_stock_pool_payload(root)
    if out is None:
        out = root / "output" / "stock-pool" / "payload.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
