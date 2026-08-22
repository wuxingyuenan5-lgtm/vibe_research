#!/usr/bin/env python3
"""Fast daily Shenwan level-1/level-2 snapshot refresh.

Two bulk SWS realtime calls replace ~150 per-index history calls on the normal
daily path. Existing history remains the authoritative rolling cache; this
script only appends/upserts the target day and recomputes 20d volatility.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd
import requests

from market_monitor.common import retry

DATA_DIR = Path("data")
# 保留窗口需 >= 全量刷新(history_rows=260)+增量冗余，否则 tail() 会截断 live 已有历史
# （曾因 260 < live 每指数 ~270 行，截掉最老交易日导致 canonical 校验 historical_key_deleted 拦截）
KEEP_HISTORY_ROWS = 1000
VOL_WINDOW = 20
ANNUALIZATION_DAYS = 252
MIN_COVERAGE = 0.90
SWS_CURRENT_URL = "https://www.swsresearch.com/institute-sw/api/index_publish/current/"
SWS_CURRENT_REFERER = "https://www.swsresearch.com/institute_sw/allIndex/releasedIndex"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/114 Safari/537.36"

EXPORT_COLUMNS = {
    "date": "日期",
    "level": "行业层级",
    "level1_code": "一级行业代码",
    "level1_name": "一级行业",
    "index_code": "指数代码",
    "index_name": "指数名称",
    "close": "收盘价",
    "amount": "成交额",
    "daily_return": "日收益率",
    "volatility_20d": "20日年化波动率",
}
REVERSE_COLUMNS = {value: key for key, value in EXPORT_COLUMNS.items()}


def strip_suffix(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.split(".")[0]


def load_existing(history_file: Path) -> pd.DataFrame:
    if not history_file.exists():
        raise RuntimeError(f"missing {history_file}; run full bootstrap first")
    frame = pd.read_csv(history_file, encoding="utf-8-sig").rename(columns=REVERSE_COLUMNS)
    required = {
        "date", "level", "level1_code", "level1_name", "index_code",
        "index_name", "close", "amount",
    }
    if not required.issubset(frame.columns):
        raise RuntimeError(f"invalid Shenwan history columns: {list(frame.columns)}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["index_code"] = frame["index_code"].map(strip_suffix)
    frame["level1_code"] = frame["level1_code"].map(strip_suffix)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    return frame.dropna(subset=["date", "index_code", "close"])


def fetch_bulk(symbol: str) -> pd.DataFrame:
    session = requests.Session()
    session.trust_env = False
    headers = {"User-Agent": UA, "Referer": SWS_CURRENT_REFERER}

    def page(page_number: int) -> tuple[int, list[dict]]:
        response = session.get(
            SWS_CURRENT_URL,
            params={"page": page_number, "page_size": 50, "indextype": symbol},
            headers=headers,
            timeout=(4, 15),
            verify=False,
        )
        response.raise_for_status()
        data = response.json().get("data") or {}
        return int(data.get("count") or 0), list(data.get("results") or [])

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    total, rows = retry(lambda: page(1), attempts=3, delay=1.0)
    for page_number in range(2, math.ceil(total / 50) + 1):
        _, page_rows = retry(lambda page_number=page_number: page(page_number), attempts=3, delay=1.0)
        rows.extend(page_rows)
    if len(rows) != total:
        raise RuntimeError(f"SWS realtime pagination incomplete ({symbol}): {len(rows)}/{total}")
    raw = pd.DataFrame(rows).rename(columns={
        "swindexcode": "指数代码",
        "swindexname": "指数名称",
        "l3": "昨收盘",
        "l4": "今开盘",
        "l5": "成交额",
        "l6": "最高价",
        "l7": "最低价",
        "l8": "最新价",
        "l11": "成交量",
    })
    required = {"指数代码", "指数名称", "昨收盘", "最新价", "成交额"}
    if raw is None or raw.empty or not required.issubset(raw.columns):
        raise RuntimeError(f"index_realtime_sw({symbol}) invalid: {list(raw.columns)}")
    out = raw.copy()
    out["index_code"] = out["指数代码"].map(strip_suffix)
    out["close"] = pd.to_numeric(out["最新价"], errors="coerce")
    out["prev_close"] = pd.to_numeric(out["昨收盘"], errors="coerce")
    out["amount"] = pd.to_numeric(out["成交额"], errors="coerce") / 100.0
    return out[["index_code", "close", "prev_close", "amount"]].dropna(
        subset=["index_code", "close"]
    )


def calculate_metrics(data: pd.DataFrame) -> pd.DataFrame:
    data = (
        data.sort_values(["index_code", "date"])
        .drop_duplicates(["index_code", "date"], keep="last")
        .copy()
    )
    data["daily_return"] = data.groupby("index_code")["close"].pct_change(fill_method=None)
    data["volatility_20d"] = data.groupby("index_code")["daily_return"].transform(
        lambda series: series.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std(ddof=1)
        * math.sqrt(ANNUALIZATION_DAYS)
    )
    return data.groupby("index_code", group_keys=False).tail(KEEP_HISTORY_ROWS)


def write_outputs(
    data: pd.DataFrame,
    target_date: str,
    history_file: Path,
    latest_file: Path,
) -> None:
    history_file.parent.mkdir(parents=True, exist_ok=True)
    latest_file.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "date", "level", "level1_code", "level1_name", "index_code",
        "index_name", "close", "amount", "daily_return", "volatility_20d",
    ]
    exported = data[columns].sort_values(
        ["date", "level", "level1_name", "index_name"]
    ).rename(columns=EXPORT_COLUMNS)
    exported["日期"] = pd.to_datetime(exported["日期"]).dt.strftime("%Y-%m-%d")
    exported.to_csv(history_file, index=False, encoding="utf-8-sig", float_format="%.8f")

    # latest 只能包含目标交易日真实返回的活跃指数；不再拿历史旧行补齐数量。
    latest = data[
        pd.to_datetime(data["date"], errors="coerce").dt.strftime("%Y-%m-%d") == target_date
    ][columns].sort_values(["level", "level1_name", "index_name"]).rename(columns=EXPORT_COLUMNS)
    if len(latest) < 150:
        raise RuntimeError(f"Shenwan latest active universe too small: {len(latest)}")
    latest["日期"] = pd.to_datetime(latest["日期"]).dt.strftime("%Y-%m-%d")
    latest.to_csv(latest_file, index=False, encoding="utf-8-sig", float_format="%.8f")


def update(target_date: str, data_dir: Path = DATA_DIR) -> dict[str, object]:
    data_dir = Path(data_dir)
    history_file = data_dir / "sw_industry_history.csv"
    latest_file = data_dir / "sw_industry_latest.csv"
    existing = load_existing(history_file)
    metadata = (
        existing.sort_values("date")
        .groupby("index_code", as_index=False, group_keys=False)
        .tail(1)[["level", "level1_code", "level1_name", "index_code", "index_name"]]
        .drop_duplicates("index_code")
    )
    if metadata.empty:
        raise RuntimeError("Shenwan metadata cache is empty")

    live = pd.concat(
        [fetch_bulk("一级行业"), fetch_bulk("二级行业")],
        ignore_index=True,
    ).drop_duplicates("index_code", keep="last")

    fresh = metadata.merge(live, on="index_code", how="inner")
    coverage = len(fresh) / len(metadata)
    if coverage < MIN_COVERAGE:
        raise RuntimeError(
            f"Shenwan bulk realtime coverage too low: {len(fresh)}/{len(metadata)}={coverage:.1%}"
        )

    fresh["date"] = pd.Timestamp(target_date)
    fresh = fresh[[
        "date", "level", "level1_code", "level1_name", "index_code",
        "index_name", "close", "amount",
    ]]
    base = existing[[
        "date", "level", "level1_code", "level1_name", "index_code",
        "index_name", "close", "amount",
    ]]
    data = calculate_metrics(pd.concat([base, fresh], ignore_index=True))
    write_outputs(data, target_date, history_file, latest_file)

    target_rows = int((pd.to_datetime(data["date"]).dt.strftime("%Y-%m-%d") == target_date).sum())
    result = {
        "mode": "bulk_realtime_incremental",
        "target_date": target_date,
        "cached_indices": int(len(metadata)),
        "updated_indices": int(len(fresh)),
        "coverage": round(coverage, 6),
        "target_date_rows": target_rows,
        "data_dir": str(data_dir),
    }
    print(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Fast daily Shenwan industry refresh")
    parser.add_argument("--target-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    update(args.target_date, Path(args.data_dir))


if __name__ == "__main__":
    main()
