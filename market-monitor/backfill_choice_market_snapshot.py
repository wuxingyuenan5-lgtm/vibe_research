#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from EmQuantAPI import c

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HOT_PATH = DATA_DIR / "history" / "hot_stocks.csv"
MARKET_CORE_PATH = DATA_DIR / "history" / "market_core.csv"
MAPPING_PATH = DATA_DIR / "cache" / "sw_stock_mapping.csv"
HOT_THRESHOLD_100M = 100.0
CHUNK_SIZE = 200
STOCK_INDICATORS = "CLOSE,DIFFERRANGE,AMOUNT,ISSURGEDLIMIT,ISDECLINELIMIT"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill market_core and hot_stocks using Choice all-A snapshots")
    parser.add_argument("--dates", required=True, help="Comma-separated dates like 2026-07-29,2026-08-07")
    return parser.parse_args()


def parse_date_list(raw: str) -> list[str]:
    return sorted({item.strip() for item in raw.split(",") if item.strip()})


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def fmt_decimal(value: float, digits: int = 10) -> str:
    return f"{value:.{digits}f}"


def fmt_price(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def to_float(value: object, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def load_mapping() -> dict[str, tuple[str, str]]:
    _, rows = read_csv_rows(MAPPING_PATH)
    mapping: dict[str, tuple[str, str]] = {}
    for row in rows:
        code = str(row.get("stock_code") or "").zfill(6)
        if code:
            mapping[code] = (
                str(row.get("sw_level1") or "未匹配"),
                str(row.get("sw_level2") or "未匹配"),
            )
    return mapping


def fetch_all_a_universe(trade_date: str) -> dict[str, str]:
    result = c.sector("001004", trade_date)
    if result.ErrorCode != 0:
        raise RuntimeError(f"Choice sector failed: {result.ErrorCode} {result.ErrorMsg}")
    names: dict[str, str] = {}
    data = result.Data or []
    indicators = len(result.Indicators)
    for index, code in enumerate(result.Codes):
        name_index = index * indicators + 1
        name = str(data[name_index]) if name_index < len(data) else ""
        names[code] = name
    return names


def fetch_stock_snapshot(trade_date: str, codes: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for batch in chunked(codes, CHUNK_SIZE):
        result = c.css(",".join(batch), STOCK_INDICATORS, f"TradeDate={trade_date.replace('-', '')}")
        if result.ErrorCode != 0:
            raise RuntimeError(f"Choice css failed on {trade_date}: {result.ErrorCode} {result.ErrorMsg}")
        for code in result.Codes:
            close, return_pct, amount, is_up, is_down = result.Data[code]
            rows.append({
                "code": code,
                "close": to_float(close),
                "return_pct": to_float(return_pct),
                "amount_100m": to_float(amount) / 1e8,
                "is_limit_up": str(is_up) == "是",
                "is_limit_down": str(is_down) == "是",
            })
    return rows


def build_snapshot(trade_date: str, mapping: dict[str, tuple[str, str]]) -> tuple[dict[str, str], list[dict[str, str]]]:
    universe = fetch_all_a_universe(trade_date)
    rows = fetch_stock_snapshot(trade_date, list(universe))
    advance = sum(1 for row in rows if row["return_pct"] > 0)
    decline = sum(1 for row in rows if row["return_pct"] < 0)
    flat = sum(1 for row in rows if row["return_pct"] == 0)
    total_amount = sum(row["amount_100m"] for row in rows)
    limit_up = sum(1 for row in rows if row["is_limit_up"])
    limit_down = sum(1 for row in rows if row["is_limit_down"])

    hot_candidates = [row for row in rows if row["amount_100m"] >= HOT_THRESHOLD_100M]
    hot_candidates.sort(key=lambda item: (-item["amount_100m"], item["code"]))
    hot_amount = sum(row["amount_100m"] for row in hot_candidates)

    hot_rows: list[dict[str, str]] = []
    for rank, row in enumerate(hot_candidates, start=1):
        stock_code = row["code"].split(".")[0]
        sw_level1, sw_level2 = mapping.get(stock_code, ("未匹配", "未匹配"))
        hot_rows.append({
            "date": trade_date,
            "rank": str(rank),
            "stock_code": stock_code,
            "stock_name": universe[row["code"]],
            "close": fmt_price(row["close"]),
            "return": fmt_decimal(row["return_pct"] / 100.0, digits=6),
            "amount_100m": fmt_decimal(row["amount_100m"], digits=4),
            "sw_level1": sw_level1,
            "sw_level2": sw_level2,
        })

    market_row = {
        "date": trade_date,
        "advance": str(advance),
        "decline": str(decline),
        "flat": str(flat),
        "limit_up": fmt_decimal(float(limit_up)),
        "limit_down": fmt_decimal(float(limit_down)),
        "effective_stocks": str(advance + decline + flat),
        "total_amount_100m": fmt_decimal(total_amount, digits=10),
        "hot_count": fmt_decimal(float(len(hot_candidates))),
        "hot_amount_100m": fmt_decimal(hot_amount, digits=10),
        "hot_concentration": fmt_decimal(hot_amount / total_amount if total_amount else 0.0, digits=10),
        "market_breadth": fmt_decimal((advance - decline) / (advance + decline) if (advance + decline) else 0.0, digits=10),
        "snapshot_source": "Choice全部A股日行情修复",
        "limit_source": "Choice全部A股日行情涨跌停标记修复",
    }
    return market_row, hot_rows


def merge_market_rows(target_rows: list[dict[str, str]]) -> None:
    fieldnames, existing_rows = read_csv_rows(MARKET_CORE_PATH)
    target_dates = {row["date"] for row in target_rows}
    kept_rows = [row for row in existing_rows if str(row.get("date") or "")[:10] not in target_dates]
    merged = sorted(kept_rows + target_rows, key=lambda row: row["date"])
    write_csv_rows(MARKET_CORE_PATH, fieldnames, merged)


def merge_hot_rows(target_rows: list[dict[str, str]]) -> None:
    fieldnames, existing_rows = read_csv_rows(HOT_PATH)
    target_dates = {row["date"] for row in target_rows}
    kept_rows = [row for row in existing_rows if str(row.get("date") or "")[:10] not in target_dates]
    merged = sorted(
        kept_rows + target_rows,
        key=lambda row: (row["date"], int(row["rank"]), row["stock_code"]),
    )
    write_csv_rows(HOT_PATH, fieldnames, merged)


def main() -> None:
    args = parse_args()
    target_dates = parse_date_list(args.dates)
    login = c.start()
    if login.ErrorCode != 0:
        raise RuntimeError(f"Choice login failed: {login.ErrorCode} {login.ErrorMsg}")
    try:
        mapping = load_mapping()
        market_rows: list[dict[str, str]] = []
        hot_rows: list[dict[str, str]] = []
        summary: dict[str, dict[str, object]] = {}
        for trade_date in target_dates:
            market_row, day_hot_rows = build_snapshot(trade_date, mapping)
            market_rows.append(market_row)
            hot_rows.extend(day_hot_rows)
            summary[trade_date] = {
                "hot_count": len(day_hot_rows),
                "hot_amount_100m": market_row["hot_amount_100m"],
                "total_amount_100m": market_row["total_amount_100m"],
            }
        merge_market_rows(market_rows)
        merge_hot_rows(hot_rows)
    finally:
        c.stop()
    print(summary)


if __name__ == "__main__":
    main()
