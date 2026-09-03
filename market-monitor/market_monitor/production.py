from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from . import pipeline
from .common import retry
from .fast_market import fetch_a_share_spot_fast
from .sector_eastmoney import BOARD_DEFINITIONS


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
# 东财行情节点选型（2026-08-22 实测，本机网络下）：
#   push2 / 91.push2 / 82.push2 / push2his（即时行情节点）→ HTTP 000 被风控拒绝；
#   push2delay（延迟行情节点，daily_refresh 股票池快照同款）→ HTTP 200 稳定可用。
# 延迟节点是 15 分钟延迟行情，生产在收盘后 15:20 跑 → 当日数据已定型，无延迟问题。
# 板块实时一律走 push2delay；生产在收盘后执行，当日数据已定型。
EM_CONCEPT_QUOTE_URL = "https://push2delay.eastmoney.com/api/qt/stock/get"
EM_MARKET_ACTIVITY_URL = "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
EM_UT = "bd1d9ddb04089700cf9c27f6f7426281"
INNOVATION_SECID = "90.BK1106"
CLOSE_READY_TIME = time(15, 20)


def _require_close_ready(target_date: str, timestamp: object, label: str) -> datetime:
    value = _number(timestamp)
    if value is None:
        raise RuntimeError(f"{label} quote timestamp missing")
    quote_time = datetime.fromtimestamp(value, ZoneInfo("Asia/Shanghai"))
    if quote_time.strftime("%Y-%m-%d") != target_date or quote_time.time() < CLOSE_READY_TIME:
        raise RuntimeError(
            f"{label} close quote not ready: {quote_time.isoformat(timespec='seconds')}"
        )
    return quote_time


def fetch_market_activity_summary(target_date: str) -> dict[str, int] | None:
    """乐咕活跃度只作补充；不可用时回退全A快照自算，不阻断正式母表。"""
    try:
        import akshare as ak  # noqa: PLC0415
    except Exception:
        return None

    try:
        frame = retry(ak.stock_market_activity_legu, attempts=3, delay=0.8)
        if frame is None or frame.empty or not {"item", "value"}.issubset(frame.columns):
            return None
        values = {str(row["item"]): row["value"] for _, row in frame.iterrows()}
        source_date = str(values.get("统计日期") or "")[:10]
        if source_date != target_date:
            return None
        result = {
            "advance": int(float(values.get("上涨") or 0)),
            "decline": int(float(values.get("下跌") or 0)),
            "flat": int(float(values.get("平盘") or 0)),
            "limit_up": int(float(values.get("涨停") or 0)),
            "limit_down": int(float(values.get("跌停") or 0)),
        }
        if result["advance"] + result["decline"] + result["flat"] < 4500:
            return None
        return result
    except Exception:
        return None


def _number(value):
    result = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(result) else float(result)


def _request_json(url: str, params: dict) -> dict:
    def call():
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=(3, 6),
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("data"):
            raise RuntimeError("empty Eastmoney quote payload")
        return payload

    return retry(call, attempts=3, delay=0.8)


def fetch_innovation_current_reliable(target_date: str):
    payload = _request_json(
        EM_CONCEPT_QUOTE_URL,
        {
            "secid": INNOVATION_SECID,
            "fields": "f43,f47,f48,f86,f168,f170",
            "mpi": "1000",
            "invt": "2",
            "fltt": "2",
        },
    )
    data = payload["data"]
    amount = _number(data.get("f48"))
    close = _number(data.get("f43"))
    volume = _number(data.get("f47"))
    quote_timestamp = _number(data.get("f86"))
    turnover_raw = _number(data.get("f168"))
    return_raw = _number(data.get("f170"))
    if None in (amount, close, volume, quote_timestamp, turnover_raw, return_raw):
        raise RuntimeError("innovation quote missing close/volume/amount/time/turnover/return")
    quote_time = _require_close_ready(target_date, quote_timestamp, "innovation")
    quote_date = quote_time.strftime("%Y-%m-%d")
    if quote_date != target_date:
        raise RuntimeError(f"innovation quote date mismatch: {quote_date} != {target_date}")
    return {
        "date": quote_date,
        "quote_time": quote_time.isoformat(timespec="seconds"),
        "close": close,
        "volume": volume,
        "amount_100m": amount / 1e8,
        "turnover": turnover_raw / 100,
        "return": return_raw / 100,
        "source": "东方财富创新药BK1106轻量板块报价（供应商直接字段）",
    }


def fetch_four_sector_current_reliable(target_date: str) -> list[dict[str, object]]:
    """Read the four board close snapshots from Eastmoney's delayed endpoint."""
    def fetch_one(item: tuple[str, tuple[str, str]]) -> dict[str, object]:
        logical_code, (name, board_code) = item
        payload = _request_json(
            EM_CONCEPT_QUOTE_URL,
            {
                "secid": f"90.{board_code}",
                "fields": "f43,f47,f48,f86,f168,f170",
                "mpi": "1000",
                "invt": "2",
                "fltt": "2",
            },
        )
        data = payload["data"]
        amount = _number(data.get("f48"))
        close = _number(data.get("f43"))
        volume = _number(data.get("f47"))
        timestamp = _number(data.get("f86"))
        turnover = _number(data.get("f168"))
        return_pct = _number(data.get("f170"))
        if None in (amount, close, volume, timestamp, turnover, return_pct):
            raise RuntimeError(f"sector quote fields incomplete: {name}/{board_code}")
        quote_time = _require_close_ready(target_date, timestamp, f"sector {name}")
        return {
            "logical_code": logical_code,
            "board_code": board_code,
            "date": quote_time.strftime("%Y-%m-%d"),
            "quote_time": quote_time.isoformat(timespec="seconds"),
            "close": close,
            "volume": volume / 1_000_000.0,
            "amount_100m": amount / 1e8,
            "turnover_pct": turnover,
            "return_pct": return_pct,
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(fetch_one, BOARD_DEFINITIONS.items()))


def run(
    target_date: str,
    config_path: Path = Path("config/market_monitor.json"),
    root: Path = Path("."),
    refresh_mapping: bool = False,
):
    """Production entrypoint with all mutable data scoped to the supplied root."""
    root = Path(root).resolve()
    pipeline.fetch_a_share_spot = fetch_a_share_spot_fast
    pipeline.fetch_market_activity_summary = fetch_market_activity_summary
    pipeline.fetch_four_sector_current = fetch_four_sector_current_reliable
    # 当日创新药是正式母表的一部分；抓取失败必须让生产失败，不能静默沿用旧日。
    pipeline.fetch_innovation_current_em = fetch_innovation_current_reliable
    return pipeline.run(
        target_date=target_date,
        config_path=config_path,
        root=root,
        refresh_mapping=refresh_mapping,
    )
