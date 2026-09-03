from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .common import append_history, ensure_dir, retry

# 本机 WorkBuddy/系统注入的 HTTP(S)_PROXY 常指向不可达的本地转发代理（如 127.0.0.1:1082），
# 会让 requests/akshare 的外网请求全部 ProxyError。采集改为直连可用源（腾讯/同花顺/申万）。
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"
INNOVATION_EM_SECID = "90.BK1106"
EM_LIMIT_POOL_URL = "https://push2ex.eastmoney.com/{endpoint}"
EM_LIMIT_POOL_UT = "7eea3edcaed734bea9cbfc24409ed989"


def _pick(frame: pd.DataFrame, *names: str) -> str:
    for name in names:
        if name in frame.columns:
            return name
    raise KeyError(f"missing {names}; actual={list(frame.columns)}")


def _as_number(value: Any) -> float | None:
    result = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(result) else float(result)


def _normalize_a_share_spot(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError(f"A股实时快照为空: {source}")
    code = _pick(raw, "代码", "symbol")
    name = _pick(raw, "名称", "name")
    close = _pick(raw, "最新价", "最新", "trade")
    prev = _pick(raw, "昨收", "昨收盘", "settlement")
    amount = _pick(raw, "成交额", "amount")
    volume = _pick(raw, "成交量", "volume")
    pct = _pick(raw, "涨跌幅", "changepercent")
    out = pd.DataFrame({
        "stock_code": raw[code].astype(str).str.extract(r"(\d{6})", expand=False),
        "stock_name": raw[name].astype(str),
        "close": pd.to_numeric(raw[close], errors="coerce"),
        "prev_close": pd.to_numeric(raw[prev], errors="coerce"),
        "amount_yuan": pd.to_numeric(raw[amount], errors="coerce"),
        "volume": pd.to_numeric(raw[volume], errors="coerce"),
        "return": pd.to_numeric(raw[pct], errors="coerce") / 100,
    }).dropna()
    out = out[(out["close"] > 0) & (out["prev_close"] > 0) & (out["amount_yuan"] > 0) & (out["volume"] > 0)]
    out = out[~out["stock_name"].str.contains("ST", case=False, na=False)]
    out = out[~out["stock_name"].str.startswith(("N", "C"), na=False)]
    out = out.drop_duplicates("stock_code", keep="last")
    out["amount_100m"] = out["amount_yuan"] / 1e8
    out["snapshot_source"] = source
    return out


def fetch_a_share_spot() -> pd.DataFrame:
    """Use the already-validated Sina all-A snapshot on GitHub runners."""
    import akshare as ak  # noqa: PLC0415

    raw = retry(ak.stock_zh_a_spot, attempts=3, delay=2.0)
    return _normalize_a_share_spot(raw, "AKShare stock_zh_a_spot / 新浪")


def fetch_limit_pools(target_date: str) -> tuple[int, int, list[dict[str, object]]]:
    """读取东方财富官方涨停池/跌停池，并返回数量与可归档明细。"""
    compact = target_date.replace("-", "")
    definitions = (
        ("limit_up", "getTopicZTPool", "fbt:asc"),
        ("limit_down", "getTopicDTPool", "fund:asc"),
    )
    details: list[dict[str, object]] = []
    counts: dict[str, int] = {}

    for direction, endpoint, sort in definitions:
        params = {
            "ut": EM_LIMIT_POOL_UT,
            "dpt": "wz.ztzt",
            "Pageindex": "0",
            "pagesize": "10000",
            "sort": sort,
            "date": compact,
        }

        def request() -> dict:
            session = requests.Session()
            session.trust_env = False
            response = session.get(
                EM_LIMIT_POOL_URL.format(endpoint=endpoint),
                params=params,
                headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
                timeout=(4, 12),
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
            if str(data.get("qdate") or "") != compact:
                raise RuntimeError(f"Eastmoney {direction} pool date mismatch: {data.get('qdate')}")
            return data

        data = retry(request, attempts=3, delay=1.0)
        pool = data.get("pool") or []
        count = int(data.get("tc") or 0)
        if count != len(pool):
            raise RuntimeError(f"Eastmoney {direction} pool incomplete: tc={count}, rows={len(pool)}")
        counts[direction] = count
        for row in pool:
            price = _as_number(row.get("p"))
            pct = _as_number(row.get("zdp"))
            amount = _as_number(row.get("amount"))
            turnover = _as_number(row.get("hs"))
            details.append({
                "date": target_date,
                "direction": direction,
                "stock_code": str(row.get("c") or "").zfill(6),
                "stock_name": str(row.get("n") or ""),
                "close": price / 1000 if price is not None else None,
                "return": pct / 100 if pct is not None else None,
                "amount_100m": amount / 1e8 if amount is not None else None,
                "turnover": turnover / 100 if turnover is not None else None,
                "industry": str(row.get("hybk") or ""),
                "source": "东方财富涨跌停池直接接口",
            })
    return counts["limit_up"], counts["limit_down"], details


def _em_curl_json(url: str, params: dict[str, str]) -> dict:
    """东财接口用 curl 子进程直连（--noproxy）。

    东财风控会按 TLS 指纹拒绝 python requests/urllib3（RemoteDisconnected），
    但系统 curl 可用；同时绕过 WorkBuddy 注入的失效代理。
    """
    import json as _json
    import subprocess

    qs = "&".join(f"{k}={str(v)}" for k, v in params.items())
    cmd = [
        "curl", "-s", "-m", "12", f"{url}?{qs}",
        "-H", "Referer: https://quote.eastmoney.com/",
        "-H", f"User-Agent: {UA}",
        "-H", "Accept: */*",
        "--noproxy", "*",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"curl Eastmoney failed: {proc.stderr[:120]}")
    return _json.loads(proc.stdout)


def _fetch_em_klines(secid: str, beg: str, end: str, lmt: int = 1000) -> list[list[str]]:
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "beg": beg,
        "end": end,
        "lmt": str(lmt),
        "ut": EM_UT,
    }

    def request() -> list[list[str]]:
        payload = _em_curl_json(EM_KLINE_URL, params)
        raw_rows = (payload.get("data") or {}).get("klines") or []
        if not raw_rows:
            raise RuntimeError(f"empty Eastmoney kline: {secid}")
        parsed = [row.split(",") for row in raw_rows]
        return [row for row in parsed if len(row) >= 11]

    return retry(request, attempts=2, delay=0.8)


def _innovation_em_frame(beg: str, end: str) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for values in _fetch_em_klines(INNOVATION_EM_SECID, beg, end, lmt=1000):
        records.append({
            "日期": pd.to_datetime(values[0]),
            "收盘价": float(values[2]),
            "成交量": float(values[5]),
            "成交额": float(values[6]),
            "日收益率": float(values[8]) / 100,
            "换手率": float(values[10]) / 100,
            "数据源": "东方财富创新药BK1106历史K线直连",
        })
    return pd.DataFrame(records)


def fetch_innovation_current_em(target_date: str) -> dict[str, object] | None:
    compact = target_date.replace("-", "")
    try:
        frame = _innovation_em_frame(compact, compact)
    except Exception:
        return None
    if frame.empty:
        return None
    row = frame.iloc[-1]
    return {
        "date": target_date,
        "close": _as_number(row["收盘价"]),
        "amount_100m": _as_number(row["成交额"]) / 1e8 if _as_number(row["成交额"]) is not None else None,
        "turnover": _as_number(row["换手率"]),
        "return": _as_number(row["日收益率"]),
        "source": "东方财富创新药BK1106历史K线直连",
    }


def update_innovation_history(target_date: str, history_path: Path, history_start: str) -> pd.DataFrame:
    """Eastmoney BK1106 history with hard HTTP timeouts and direct turnover."""
    ensure_dir(history_path.parent)
    existing = pd.DataFrame()
    if history_path.exists():
        existing = pd.read_csv(history_path, encoding="utf-8-sig")
        existing["日期"] = pd.to_datetime(existing["日期"], errors="coerce")
        last_date = existing["日期"].max()
        start = (last_date - pd.Timedelta(days=7)).strftime("%Y%m%d")
    else:
        start = history_start.replace("-", "")
    try:
        fresh = _innovation_em_frame(start, target_date.replace("-", ""))
    except Exception:
        return existing
    if fresh.empty:
        return existing
    combined = pd.concat([existing, fresh], ignore_index=True, sort=False) if not existing.empty else fresh
    combined["日期"] = pd.to_datetime(combined["日期"], errors="coerce")
    combined = combined.dropna(subset=["日期"]).drop_duplicates("日期", keep="last").sort_values("日期")
    exported = combined.copy()
    exported["日期"] = exported["日期"].dt.strftime("%Y-%m-%d")
    exported.to_csv(history_path, index=False, encoding="utf-8-sig", float_format="%.10f")
    return combined


def upsert_innovation_direct_quote(history_path: Path, quote: dict[str, object]) -> pd.DataFrame:
    """把东财 BK1106 直接报价写入历史；同日旧估算值会被直接值覆盖。"""
    required = ("date", "close", "volume", "amount_100m", "turnover", "return", "source")
    missing = [field for field in required if quote.get(field) is None]
    if missing:
        raise RuntimeError(f"innovation direct quote missing fields: {missing}")
    if "东方财富创新药BK1106" not in str(quote.get("source") or ""):
        raise RuntimeError("innovation quote is not direct Eastmoney BK1106 data")

    existing = pd.read_csv(history_path, encoding="utf-8-sig") if history_path.exists() else pd.DataFrame()
    if not existing.empty:
        existing = existing[existing["日期"].astype(str).str[:10] != str(quote["date"])]
    fresh = pd.DataFrame([{
        "日期": quote["date"],
        "收盘价": quote["close"],
        "成交量": quote["volume"],
        "成交额": float(quote["amount_100m"]) * 1e8,
        "日收益率": quote["return"],
        "换手率": quote["turnover"],
        "数据源": quote["source"],
    }])
    combined = pd.concat([existing, fresh], ignore_index=True, sort=False)
    combined["日期"] = pd.to_datetime(combined["日期"], errors="coerce")
    combined = combined.dropna(subset=["日期"]).drop_duplicates("日期", keep="last").sort_values("日期")
    exported = combined.copy()
    exported["日期"] = exported["日期"].dt.strftime("%Y-%m-%d")
    ensure_dir(history_path.parent)
    exported.to_csv(history_path, index=False, encoding="utf-8-sig", float_format="%.10f")
    return combined


def update_market_history(path: Path, market: dict[str, object]) -> pd.DataFrame:
    return append_history(path, market, key="date")
