from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from math import ceil

import akshare as ak
import pandas as pd
import requests

from .common import retry

EM_ALL_A_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
EM_PAGE_SIZE = 100
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def _normalize(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError(f"empty all-A snapshot: {source}")
    aliases = {
        "code": next((c for c in ("代码", "symbol") if c in raw.columns), None),
        "name": next((c for c in ("名称", "name") if c in raw.columns), None),
        "close": next((c for c in ("最新价", "最新", "trade") if c in raw.columns), None),
        "prev": next((c for c in ("昨收", "昨收盘", "settlement") if c in raw.columns), None),
        "amount": next((c for c in ("成交额", "amount") if c in raw.columns), None),
        "volume": next((c for c in ("成交量", "volume") if c in raw.columns), None),
        "pct": next((c for c in ("涨跌幅", "changepercent") if c in raw.columns), None),
    }
    if any(value is None for value in aliases.values()):
        raise RuntimeError(f"unexpected all-A columns: {list(raw.columns)}")
    out = pd.DataFrame({
        "stock_code": raw[aliases["code"]].astype(str).str.extract(r"(\d{6})", expand=False),
        "stock_name": raw[aliases["name"]].astype(str),
        "close": pd.to_numeric(raw[aliases["close"]], errors="coerce"),
        "prev_close": pd.to_numeric(raw[aliases["prev"]], errors="coerce"),
        "amount_yuan": pd.to_numeric(raw[aliases["amount"]], errors="coerce"),
        "volume": pd.to_numeric(raw[aliases["volume"]], errors="coerce"),
        "return": pd.to_numeric(raw[aliases["pct"]], errors="coerce") / 100,
    }).dropna()
    out = out[(out["close"] > 0) & (out["prev_close"] > 0) & (out["amount_yuan"] > 0) & (out["volume"] > 0)]
    out = out[~out["stock_name"].str.contains("ST", case=False, na=False)]
    out = out[~out["stock_name"].str.startswith(("N", "C"), na=False)]
    out = out.drop_duplicates("stock_code", keep="last")
    out["amount_100m"] = out["amount_yuan"] / 1e8
    out["snapshot_source"] = source
    return out


def _fetch_eastmoney_all_a() -> pd.DataFrame:
    base_params = {
        "pz": str(EM_PAGE_SIZE),
        "po": "1",
        "np": "2",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f6",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": "f2,f3,f5,f6,f12,f14,f18,f124",
    }

    def request_page(page: int) -> tuple[int, list[dict]]:
        session = requests.Session()
        session.trust_env = False
        response = session.get(
            EM_ALL_A_URL,
            params={**base_params, "pn": str(page)},
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/center/gridlist.html#hs_a_board"},
            timeout=(4, 8),
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        if not (data.get("diff") or []):
            raise RuntimeError("empty Eastmoney all-A snapshot")
        diff = data.get("diff") or []
        rows = list(diff.values()) if isinstance(diff, dict) else list(diff)
        return int(data.get("total") or len(rows)), rows

    total, first_page = retry(lambda: request_page(1), attempts=3, delay=0.8)
    page_count = max(1, ceil(total / EM_PAGE_SIZE))
    rows = list(first_page)
    if page_count > 1:
        with ThreadPoolExecutor(max_workers=8) as executor:
            def request_page_with_retry(page: int) -> tuple[int, list[dict]]:
                return retry(lambda: request_page(page), attempts=3, delay=0.8)

            for _, page_rows in executor.map(request_page_with_retry, range(2, page_count + 1)):
                rows.extend(page_rows)
    if len(rows) != total:
        raise RuntimeError(f"Eastmoney all-A pagination incomplete: {len(rows)}/{total}")

    raw = pd.DataFrame(rows)
    required = {"f2", "f3", "f5", "f6", "f12", "f14", "f18", "f124"}
    if not required.issubset(raw.columns):
        raise RuntimeError(f"Eastmoney all-A fields changed: {list(raw.columns)}")
    normalized = pd.DataFrame({
        "代码": raw["f12"],
        "名称": raw["f14"],
        "最新价": raw["f2"],
        "昨收": raw["f18"],
        "成交额": raw["f6"],
        "成交量": raw["f5"],
        "涨跌幅": raw["f3"],
        "snapshot_timestamp": raw["f124"],
    })
    result = _normalize(normalized, "东方财富沪深京A股延迟行情直连")
    timestamps = pd.to_datetime(
        pd.to_numeric(normalized.loc[result.index, "snapshot_timestamp"], errors="coerce"),
        unit="s",
        errors="coerce",
        utc=True,
    ).dt.tz_convert("Asia/Shanghai")
    result["snapshot_date"] = timestamps.dt.strftime("%Y-%m-%d")
    if len(result) < 4500:
        raise RuntimeError(f"Eastmoney all-A snapshot too small: {len(result)}")
    if result["snapshot_date"].isna().any():
        raise RuntimeError("Eastmoney all-A snapshot contains missing timestamps")
    return result


def _fetch_sina_all_a() -> pd.DataFrame:
    raw = retry(ak.stock_zh_a_spot, attempts=3, delay=2.0)
    return _normalize(raw, "AKShare stock_zh_a_spot / 新浪")


def fetch_a_share_spot_fast() -> pd.DataFrame:
    # 正式生产只使用带源时间戳、可完整分页的东财快照；不再静默切换口径。
    return _fetch_eastmoney_all_a()
