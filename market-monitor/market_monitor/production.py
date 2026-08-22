from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from . import pipeline
from .collectors import fetch_indices as fetch_indices_legacy
from .common import retry
from .fast_market import fetch_a_share_spot_fast
from .sw_cache import load_sw_cache


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
# 东财行情节点选型（2026-08-22 实测，本机网络下）：
#   push2 / 91.push2 / 82.push2 / push2his（即时行情节点）→ HTTP 000 被风控拒绝；
#   push2delay（延迟行情节点，daily_refresh 股票池快照同款）→ HTTP 200 稳定可用。
# 延迟节点是 15 分钟延迟行情，生产在收盘后 15:20 跑 → 当日数据已定型，无延迟问题。
# 指数与板块实时一律走 push2delay；历史 K 线（push2his）被拒时由同花顺历史 backfill 兜底。
EM_INDEX_QUOTE_URL = "https://push2delay.eastmoney.com/api/qt/stock/get"
EM_CONCEPT_QUOTE_URL = "https://push2delay.eastmoney.com/api/qt/stock/get"
EM_UT = "bd1d9ddb04089700cf9c27f6f7426281"
INNOVATION_SECID = "90.BK1106"


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


def _index_current_quote(target_date: str, definition: dict[str, str]) -> dict[str, object]:
    payload = _request_json(
        EM_INDEX_QUOTE_URL,
        {
            "secid": definition["secid"],
            "fields": "f43,f48,f57,f58,f86,f170",
            "fltt": "2",
            "invt": "2",
            "ut": EM_UT,
        },
    )
    data = payload["data"]
    close = _number(data.get("f43"))
    amount = _number(data.get("f48"))
    pct = _number(data.get("f170"))
    if close is None or amount is None or pct is None:
        raise RuntimeError(f"current quote missing fields: {definition['name']}")
    return {
        "date": target_date,
        "name": definition["name"],
        "code": definition["secid"],
        "close": close,
        "return": pct / 100,
        "amount_100m": amount / 1e8,
        "source": "东方财富轻量指数报价 / api/qt/stock/get",
        "status": "ok_current_quote_hard_timeout",
    }


def fetch_indices_resilient(target_date: str, definitions: list[dict[str, str]]):
    primary: dict[str, dict[str, object]] = {}
    failed: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(definitions))) as executor:
        future_map = {
            executor.submit(_index_current_quote, target_date, definition): definition
            for definition in definitions
        }
        for future in as_completed(future_map):
            definition = future_map[future]
            try:
                primary[definition["name"]] = future.result()
            except Exception:
                failed.append(definition)

    fallback_map: dict[str, dict[str, object]] = {}
    if failed:
        fallback = fetch_indices_legacy(target_date, failed)
        fallback_map = {str(item.get("name")): item for item in fallback}

    out = []
    for definition in definitions:
        name = definition["name"]
        record = primary.get(name) or fallback_map.get(name)
        if record is None:
            record = {
                "date": target_date,
                "name": name,
                "code": definition["secid"],
                "close": None,
                "return": None,
                "amount_100m": None,
                "source": "bounded index quote chain",
                "status": "error: current quote and bounded K-line fallback unavailable",
            }
        out.append(record)
    return out


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
    quote_time = datetime.fromtimestamp(quote_timestamp, ZoneInfo("Asia/Shanghai"))
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


def run(
    target_date: str,
    config_path: Path = Path("config/market_monitor.json"),
    root: Path = Path("."),
    refresh_mapping: bool = False,
):
    """Production entrypoint with all mutable data scoped to the supplied root."""
    root = Path(root).resolve()
    pipeline.fetch_a_share_spot = fetch_a_share_spot_fast
    pipeline.fetch_sw_analysis = lambda date: load_sw_cache(
        date,
        root / "data/cache/sw_analysis_daily_second.csv",
    )
    pipeline.fetch_indices = fetch_indices_resilient
    pipeline.fetch_innovation_current_em = fetch_innovation_current_reliable
    return pipeline.run(
        target_date=target_date,
        config_path=config_path,
        root=root,
        refresh_mapping=refresh_mapping,
    )
