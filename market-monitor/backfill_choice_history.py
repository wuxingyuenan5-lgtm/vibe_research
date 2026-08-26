#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from EmQuantAPI import c

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SW_INDUSTRY_PATH = DATA_DIR / "sw_industry_history.csv"
SW_ANALYSIS_PATH = DATA_DIR / "history" / "sw_analysis_daily_second.csv"
INDICES_PATH = DATA_DIR / "history" / "indices_history.csv"
MARKET_CORE_PATH = DATA_DIR / "history" / "market_core.csv"
SQRT_252 = math.sqrt(252.0)
VOL_WINDOW = 20

FOUR_SECTOR_NAMES = {
    "801102": "通信设备",
    "801101": "计算机设备",
    "801083": "元件",
    "801081": "半导体",
}
FOUR_SECTOR_SOURCE = "Choice申万二级指数历史修复（SWI）"
INDICES = {
    "上证50": ("1.000016", "000016.SH"),
    "中证2000": ("2.932000", "932000.CSI"),
    "中证全指": ("1.000985", "000985.CSI"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Use Choice to backfill market-monitor mother tables")
    parser.add_argument("--sw-industry-dates", default="", help="Comma-separated dates like 2026-08-12,2026-08-13")
    parser.add_argument("--indices-dates", default="", help="Comma-separated dates like 2026-08-10,2026-08-24")
    parser.add_argument(
        "--rewrite-sw-analysis-through",
        default="",
        help="Rewrite four-sector sw_analysis rows through this date (inclusive), e.g. 2026-08-24",
    )
    return parser.parse_args()


def parse_date_list(raw: str) -> list[str]:
    dates = {item.strip() for item in raw.split(",") if item.strip()}
    return sorted(dates)


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def normalize_date(value: str) -> str:
    return datetime.strptime(value.replace("-", "/"), "%Y/%m/%d").strftime("%Y-%m-%d")


def fmt_decimal(value: float | None, digits: int = 8) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def fmt_plain(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text if text else "0"


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def fetch_csd_rows(codes: list[str], indicators: list[str], start_date: str, end_date: str) -> list[dict[str, object]]:
    options = "Period=1,Order=1"
    rows: list[dict[str, object]] = []
    for batch in chunked(codes, 40):
        result = c.csd(",".join(batch), ",".join(indicators), start_date, end_date, options)
        if result.ErrorCode != 0:
            raise RuntimeError(f"Choice csd failed: {result.ErrorCode} {result.ErrorMsg}")
        for code in result.Codes:
            indicator_values = result.Data[code]
            for date_index, date_value in enumerate(result.Dates):
                row: dict[str, object] = {
                    "code": code,
                    "date": normalize_date(str(date_value)),
                }
                for indicator_index, indicator in enumerate(result.Indicators):
                    values = indicator_values[indicator_index]
                    row[indicator] = values[date_index] if date_index < len(values) else None
                rows.append(row)
    return rows


def number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_market_amount_by_date() -> dict[str, float]:
    _, rows = read_csv_rows(MARKET_CORE_PATH)
    output: dict[str, float] = {}
    for row in rows:
        total_amount = number(row.get("total_amount_100m"))
        if total_amount is not None:
            output[str(row.get("date") or "")[:10]] = total_amount
    return output


def recompute_sw_industry_history(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["指数代码"])].append(row)

    output: list[dict[str, str]] = []
    for code, group_rows in grouped.items():
        ordered = sorted(group_rows, key=lambda item: item["日期"])
        previous_close: float | None = None
        rolling_returns: list[float] = []
        for row in ordered:
            close = number(row.get("收盘价"))
            daily_return: float | None = None
            if close is not None and previous_close not in (None, 0):
                daily_return = close / previous_close - 1.0
            if close is not None:
                previous_close = close
            row["日收益率"] = fmt_decimal(daily_return)
            if daily_return is not None:
                rolling_returns.append(daily_return)
            if len(rolling_returns) >= VOL_WINDOW:
                window = rolling_returns[-VOL_WINDOW:]
                volatility = statistics.stdev(window) * SQRT_252
                row["20日年化波动率"] = fmt_decimal(volatility)
            else:
                row["20日年化波动率"] = ""
            output.append(row)
    return sorted(output, key=lambda item: (item["日期"], item["行业层级"], item["一级行业"], item["指数名称"]))


def backfill_sw_industry(target_dates: list[str]) -> dict[str, object]:
    fieldnames, existing_rows = read_csv_rows(SW_INDUSTRY_PATH)
    latest_date = max(str(row.get("日期") or "")[:10] for row in existing_rows if str(row.get("日期") or ""))
    metadata: dict[str, dict[str, str]] = {}
    for row in existing_rows:
        if str(row.get("日期") or "")[:10] != latest_date:
            continue
        code = str(row.get("指数代码") or "")
        if code and code not in metadata:
            metadata[code] = {
                "行业层级": str(row.get("行业层级") or ""),
                "一级行业代码": str(row.get("一级行业代码") or ""),
                "一级行业": str(row.get("一级行业") or ""),
                "指数代码": code,
                "指数名称": str(row.get("指数名称") or ""),
            }
    choice_codes = [f"{code}.SWI" for code in metadata]
    fetched = fetch_csd_rows(choice_codes, ["CLOSE", "AMOUNT", "PCTCHANGE"], min(target_dates), max(target_dates))
    expected_pairs = {(date, code) for date in target_dates for code in metadata}
    fetched_pairs = {(str(item["date"]), str(item["code"]).split(".")[0]) for item in fetched}
    missing_pairs = sorted(expected_pairs - fetched_pairs)
    if missing_pairs:
        raise RuntimeError(f"Choice sw_industry backfill incomplete: {missing_pairs[:10]}")

    replacement_rows: list[dict[str, str]] = []
    for item in fetched:
        date = str(item["date"])
        base_code = str(item["code"]).split(".")[0]
        if date not in target_dates:
            continue
        meta = metadata[base_code]
        replacement_rows.append({
            "日期": date,
            "行业层级": meta["行业层级"],
            "一级行业代码": meta["一级行业代码"],
            "一级行业": meta["一级行业"],
            "指数代码": base_code,
            "指数名称": meta["指数名称"],
            "收盘价": fmt_decimal(number(item.get("CLOSE"))),
            "成交额": fmt_decimal((number(item.get("AMOUNT")) or 0.0) / 1e8),
            "日收益率": "",
            "20日年化波动率": "",
        })

    kept_rows = [row for row in existing_rows if str(row.get("日期") or "")[:10] not in set(target_dates)]
    merged_rows = recompute_sw_industry_history(kept_rows + replacement_rows)
    write_csv_rows(SW_INDUSTRY_PATH, fieldnames, merged_rows)
    return {"target_dates": target_dates, "rows_written": len(replacement_rows)}


def backfill_indices(target_dates: list[str]) -> dict[str, object]:
    fieldnames, existing_rows = read_csv_rows(INDICES_PATH)
    choice_codes = [value[1] for value in INDICES.values()]
    fetched = fetch_csd_rows(choice_codes, ["CLOSE", "AMOUNT", "PCTCHANGE"], min(target_dates), max(target_dates))
    by_choice_code = {(str(item["date"]), str(item["code"])): item for item in fetched if str(item["date"]) in target_dates}

    replacement_rows: list[dict[str, str]] = []
    for name, (legacy_code, choice_code) in INDICES.items():
        for target_date in target_dates:
            item = by_choice_code.get((target_date, choice_code))
            if item is None:
                raise RuntimeError(f"Choice index backfill missing {choice_code} on {target_date}")
            replacement_rows.append({
                "date": target_date,
                "name": name,
                "code": legacy_code,
                "close": fmt_plain(number(item.get("CLOSE")), digits=4),
                "return": fmt_decimal((number(item.get("PCTCHANGE")) or 0.0) / 100.0),
                "amount_100m": fmt_decimal((number(item.get("AMOUNT")) or 0.0) / 1e8),
                "source": "Choice指数日行情历史修复",
                "status": "ok_choice_history_backfill",
            })

    target_keys = {(row["date"], row["name"]) for row in replacement_rows}
    kept_rows = [row for row in existing_rows if (str(row.get("date") or ""), str(row.get("name") or "")) not in target_keys]
    merged_rows = sorted(kept_rows + replacement_rows, key=lambda row: (row["date"], row["name"]))
    write_csv_rows(INDICES_PATH, fieldnames, merged_rows)
    return {"target_dates": target_dates, "rows_written": len(replacement_rows)}


def rewrite_sw_analysis_through(end_date: str) -> dict[str, object]:
    fieldnames, existing_rows = read_csv_rows(SW_ANALYSIS_PATH)
    market_amount_by_date = load_market_amount_by_date()
    existing_share_by_key = {
        (str(row.get("发布日期") or "")[:10], str(row.get("指数代码") or "").replace(".0", "")): row
        for row in existing_rows
    }
    start_date = min(str(row.get("date") or "")[:10] for row in read_csv_rows(MARKET_CORE_PATH)[1] if str(row.get("date") or ""))
    choice_codes = [f"{code}.SWI" for code in FOUR_SECTOR_NAMES]
    fetched = fetch_csd_rows(choice_codes, ["CLOSE", "VOLUME", "AMOUNT", "TURN", "PCTCHANGE"], start_date, end_date)

    replacement_rows: list[dict[str, str]] = []
    missing_dates: list[str] = []
    for item in fetched:
        date = str(item["date"])
        if date > end_date:
            continue
        base_code = str(item["code"]).split(".")[0]
        denominator = market_amount_by_date.get(date)
        amount_100m = (number(item.get("AMOUNT")) or 0.0) / 1e8
        share_value: float | None
        if denominator in (None, 0):
            fallback = existing_share_by_key.get((date, base_code))
            share_value = number(fallback.get("成交额占比")) if fallback else None
            if share_value is None:
                missing_dates.append(date)
                continue
        else:
            share_value = amount_100m / denominator * 100.0
        replacement_rows.append({
            "指数代码": base_code,
            "指数名称": FOUR_SECTOR_NAMES[base_code],
            "发布日期": date,
            "收盘指数": fmt_plain(number(item.get("CLOSE")), digits=4),
            "成交量": fmt_plain(number(item.get("VOLUME")), digits=6),
            "涨跌幅": fmt_plain(number(item.get("PCTCHANGE")), digits=6),
            "换手率": fmt_plain(number(item.get("TURN")), digits=6),
            "市盈率": "",
            "市净率": "",
            "均价": "",
            "成交额占比": fmt_decimal(share_value, digits=10),
            "流通市值": "",
            "平均流通市值": "",
            "股息率": "",
            "数据源": FOUR_SECTOR_SOURCE,
            "东方财富板块代码": "",
            "成交额": fmt_decimal(amount_100m, digits=8),
        })
    if missing_dates:
        raise RuntimeError(f"sw_analysis denominator missing for dates: {sorted(set(missing_dates))}")

    kept_rows = []
    for row in existing_rows:
        date = str(row.get("发布日期") or "")[:10]
        code = str(row.get("指数代码") or "").replace(".0", "")
        if code in FOUR_SECTOR_NAMES and date <= end_date:
            continue
        kept_rows.append(row)
    merged_rows = sorted(kept_rows + replacement_rows, key=lambda row: (row["发布日期"], row["指数代码"]))
    write_csv_rows(SW_ANALYSIS_PATH, fieldnames, merged_rows)
    return {"end_date": end_date, "rows_written": len(replacement_rows)}


def main() -> None:
    args = parse_args()
    sw_industry_dates = parse_date_list(args.sw_industry_dates)
    indices_dates = parse_date_list(args.indices_dates)
    results: dict[str, object] = {}
    login = c.start()
    if login.ErrorCode != 0:
        raise RuntimeError(f"Choice login failed: {login.ErrorCode} {login.ErrorMsg}")
    try:
        if sw_industry_dates:
            results["sw_industry"] = backfill_sw_industry(sw_industry_dates)
        if indices_dates:
            results["indices"] = backfill_indices(indices_dates)
        if args.rewrite_sw_analysis_through:
            results["sw_analysis"] = rewrite_sw_analysis_through(args.rewrite_sw_analysis_through)
    finally:
        c.stop()
    print(results)


if __name__ == "__main__":
    main()
