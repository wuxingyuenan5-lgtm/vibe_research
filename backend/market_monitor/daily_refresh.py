"""核心股票池日度数据刷新（东财接口，无重依赖）。

流程：
1. 读 data/stock-pool/pool.json（162 只，含代码）
2. 东财 ulist 批量拉快照：现价/涨跌幅/换手/PE/PB/总市值/成交额/5日涨跌幅
3. 东财 kline 逐只拉日 K（300 根）算 20日涨跌幅 / YTD
4. 更新 stocks.csv（当日快照，覆盖）+ pool.json version（报告日）
5. 重建 output/stock-pool/payload.json

用法：python -m market_monitor.daily_refresh [--date 2026-08-15]
说明：数据为东财真实公开行情；拉不到的字段写空，前端显示 "—"（不造数）。
indices.csv（行业/指数强弱）本轮不刷新，仅刷新股票池。
"""
import argparse
import csv
import json
import re
import time
import urllib.request
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE.parent
POOL_PATH = PROJECT_ROOT / "data" / "stock-pool" / "pool.json"
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "stock-pool"
OUT_DIR = SNAPSHOT_DIR
STOCKS_CSV = SNAPSHOT_DIR / "stocks.csv"
INDICES_CSV = SNAPSHOT_DIR / "indices.csv"
LATEST_BUNDLE = SNAPSHOT_DIR / "latest_stock_pool.json"
LEGACY_SNAPSHOT_DIR = BASE / "data" / "market-monitor" / "stock-pool"
CLOSE_READY_TIME = dt_time(15, 20)

INDICES_FIELDS = [
    "code", "name", "price", "change", "change_5d", "change_20d", "change_60d", "ytd",
    "amount_yi", "turnover", "pe_ttm", "pb", "mcap_yi", "data_status", "source",
]

# 通达信/旧版申万二级代码 → 申万官网（swsresearch）二级代码 801xxx
SW_L2_MAP = {
    "802046": "801081",  # 半导体
    "802024": "801053",  # 贵金属
    "803080": "801054",  # 小金属
    "802023": "801055",  # 基本金属 → 工业金属
    "803079": "801056",  # 稀土 → 能源金属
    "802095": "801078",  # 机器人 → 自动化设备
}

CSV_FIELDS = [
    "instrument_id", "code", "exchange", "name", "industry",
    "price", "change", "change_5d", "change_20d", "ytd",
    "amount_yi", "mcap_yi", "turnover", "pe_ttm", "pb", "data_status",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}
ULIST_URL = "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
ULIST_FIELDS = "f12,f14,f2,f3,f6,f8,f9,f20,f23,f109,f124"
KLINE_FIELDS = "f51,f53"


# 国内财经站直连 opener（绕过系统代理：代理会把东财/腾讯的 CONNECT 掐掉，与估值 Connection refused 同款问题）
_no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with _no_proxy_opener.open(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


def require_current_close_window(target_date: str, now: datetime | None = None) -> datetime:
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    else:
        current = current.astimezone(ZoneInfo("Asia/Shanghai"))
    if current.strftime("%Y-%m-%d") != target_date:
        raise RuntimeError(
            f"股票池当前快照不能写成 {target_date}; 当前日期为 {current:%Y-%m-%d}"
        )
    if current.time() < CLOSE_READY_TIME:
        raise RuntimeError(f"股票池收盘快照尚未就绪: {current.isoformat(timespec='seconds')}")
    return current


def seed_single_source_files() -> None:
    """One-time migration from the retired backend mirror into the root mother-table directory."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("stocks.csv", "indices.csv"):
        target = SNAPSHOT_DIR / name
        legacy = LEGACY_SNAPSHOT_DIR / name
        if not target.exists() and legacy.exists():
            target.write_bytes(legacy.read_bytes())


def secid_of(code: str) -> str:
    """代码 → 东财 secid（A 股沪 1./深 0.；港股 116.）。"""
    code = (code or "").strip()
    if not code:
        return ""
    if len(code) == 5:  # 港股
        return f"116.{code}"
    return f"1.{code}" if code.startswith(("6", "9")) else f"0.{code}"


def fetch_snapshot(secids: list[str]) -> dict[str, dict]:
    """ulist 批量拉快照 → {code: 原始字段}（值放大 100 的整数）。"""
    out: dict[str, dict] = {}
    for i in range(0, len(secids), 50):
        batch = secids[i:i + 50]
        url = f"{ULIST_URL}?secids={','.join(batch)}&fields={ULIST_FIELDS}"
        try:
            d = _get(url)
            for v in d.get("data", {}).get("diff", []) or []:
                code = str(v.get("f12") or "").strip()
                if code:
                    out[code] = v
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] ulist 批次 {i // 50 + 1} 失败: {e}")
        time.sleep(0.2)
    return out


def fetch_kline(symbol: str) -> list[tuple[str, float]]:
    """日 K（腾讯前复权，最多 300 根，symbol 形如 sh600519/hk00700/sz399808）→ [(date, close)]。带重试。"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,300,qfq"
    for attempt in range(3):
        try:
            d = _get(url)
            data = d.get("data", {}).get(symbol, {})
            rows_raw = data.get("qfqday") or data.get("day") or []
            rows = [(r[0], float(r[2])) for r in rows_raw if len(r) >= 3]
            if rows:
                return rows
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] kline {symbol} 重试 {attempt + 1}: {e}")
        time.sleep(0.8 * (attempt + 1))
    return []


def fetch_eastmoney_kline(code: str) -> list[tuple[str, float]]:
    """日 K（东方财富复权日线）→ [(date, close)]。用于股票池日更缓存的 20日/YTD 计算。"""
    secid = secid_of(code)
    if not secid:
        return []
    url = (
        f"{KLINE_URL}?secid={secid}"
        "&klt=101&fqt=1&lmt=300&end=20500000"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    )
    for attempt in range(3):
        try:
            d = _get(url)
            rows_raw = (d.get("data") or {}).get("klines") or []
            rows = []
            for item in rows_raw:
                parts = str(item).split(",")
                if len(parts) >= 3:
                    rows.append((parts[0], float(parts[2])))
            if rows:
                return rows
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] eastmoney kline {code} 重试 {attempt + 1}: {e}")
        time.sleep(0.8 * (attempt + 1))
    return []


def compute_trends(klines: list[tuple[str, float]]) -> tuple[float | None, float | None]:
    """从日 K 算 (20日涨跌幅, YTD)，均为小数比例。"""
    if len(klines) < 2:
        return None, None
    closes = [c for _, c in klines]
    last = closes[-1]
    chg20 = (last - closes[-21]) / closes[-21] if len(closes) >= 21 else None
    # YTD：优先取上一年最后一个交易日；否则取当年第一根之前一根。
    ytd = None
    dates = [d for d, _ in klines]
    current_year = dates[-1][:4]
    prev_year_close = f"{int(current_year) - 1}-12-31"
    current_year_start = f"{current_year}-01-01"
    try:
        idx = dates.index(prev_year_close)
        base = closes[idx]
    except ValueError:
        year_start_idx = next((i for i, d in enumerate(dates) if d >= current_year_start), None)
        if year_start_idx is None or year_start_idx == 0:
            base = None
        else:
            base = closes[year_start_idx - 1]
    if base:
        ytd = (last - base) / base
    return chg20, ytd


def fmt_num(v: float | None, scale: float = 1.0) -> str:
    if v is None:
        return ""
    return f"{v / scale:.4f}" if scale == 1 else f"{v / scale:.6f}"


def tx_symbol_of(code: str) -> str:
    """代码 → 腾讯行情 symbol（sh/sz/hk/bj）。拉不到的（申万 801、通达信自定义等）返回空。"""
    code = (code or "").strip()
    if code == "HSI":
        return "hkHSI"
    if code == "HSTECH":
        return "hkHSTECH"
    if code.isdigit() and len(code) == 5:  # 港股
        return "hk" + code
    if code.startswith(("60", "68", "51", "56", "58", "9")):  # 沪 A 股/ETF
        return "sh" + code
    if code.startswith(("00", "30", "39")):  # 深 A 股/ETF/深证指数
        return "sz" + code
    if code.startswith(("000", "880", "930", "931")):  # 中证指数
        return "sh" + code
    if code.startswith("899"):  # 北证
        return "bj" + code
    return ""


def refresh_indices() -> tuple[int, int]:
    """刷新 indices.csv：
    - 申万指数（801/802/803）→ akshare index_realtime_sw + index_hist_sw
    - 标准指数/ETF（sh/sz/hk/bj）→ 腾讯 kline
    - 通达信自定义等拉不到 → 保留旧值标 stale
    """
    rows = list(csv.DictReader(open(INDICES_CSV, encoding="utf-8")))
    refreshed, stale = 0, 0

    # akshare 申万：实时（一次全量）+ 逐只历史（二级经 SW_L2_MAP 映射到官网代码）
    sw_realtime: dict[str, dict] = {}
    sw_hist: dict[str, list[tuple[str, float]]] = {}
    sw_codes = [r["code"] for r in rows if str(r.get("code", "")).startswith(("801", "802", "803"))]
    if sw_codes:
        try:
            import akshare as ak  # noqa: PLC0415

            rt = ak.index_realtime_sw()
            sw_realtime = {str(v["指数代码"]): v for _, v in rt.iterrows()}
            official = dict.fromkeys(SW_L2_MAP.get(c, c) for c in sw_codes)  # 去重
            for oc in official:
                for attempt in range(3):
                    try:
                        h = ak.index_hist_sw(symbol=oc, period="day")
                        sw_hist[oc] = [(str(v["日期"]), float(v["收盘"])) for _, v in h.iterrows()]
                        break
                    except Exception as e:  # noqa: BLE001
                        if attempt == 2:
                            print(f"  [WARN] 申万历史 {oc} 失败: {e}")
                        time.sleep(1.0)
                time.sleep(0.3)
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] akshare 申万实时拉取失败: {e}")

    for r in rows:
        code = str(r.get("code", "")).strip()
        # 1) 申万类（akshare：用户代码 → 官网代码拉 hist 全字段）
        if code.startswith(("801", "802", "803")):
            oc = SW_L2_MAP.get(code, code)
            kl = sw_hist.get(oc)
            if kl and len(kl) >= 2:
                closes = [c for _, c in kl]
                last = closes[-1]
                r["price"] = f"{last:.2f}"
                r["change"] = f"{(last - closes[-2]) / closes[-2]:.6f}"
                r["change_5d"] = f"{(last - closes[-6]) / closes[-6]:.6f}" if len(closes) >= 6 else ""
                r["change_20d"] = f"{(last - closes[-21]) / closes[-21]:.6f}" if len(closes) >= 21 else ""
                r["change_60d"] = f"{(last - closes[-61]) / closes[-61]:.6f}" if len(closes) >= 61 else ""
                dates = [d for d, _ in kl]
                try:
                    base = closes[dates.index("2025-12-31")]
                except ValueError:
                    i26 = next((i for i, d in enumerate(dates) if d >= "2026-01-01"), None)
                    base = closes[i26 - 1] if i26 and i26 > 0 else None
                r["ytd"] = f"{(last - base) / base:.6f}" if base else ""
                r["data_status"] = "ok"
                refreshed += 1
                continue
            rt = sw_realtime.get(oc)  # hist 无数据时 realtime 兜底（仅当日）
            if rt is not None:
                price = float(rt.get("最新价") or 0)
                prev = float(rt.get("昨收盘") or 0)
                r["price"] = f"{price:.2f}"
                r["change"] = f"{(price - prev) / prev:.6f}" if prev else ""
                r["data_status"] = "ok"
                refreshed += 1
                continue
            r["data_status"] = "stale"
            stale += 1
            continue
        # 2) 标准指数/ETF（腾讯 kline）
        symbol = tx_symbol_of(code)
        if not symbol:
            r["data_status"] = "stale"
            stale += 1
            continue
        kl = fetch_kline(symbol)
        if len(kl) < 2:
            r["data_status"] = "stale"
            stale += 1
            continue
        closes = [c for _, c in kl]
        last = closes[-1]
        r["price"] = f"{last:.2f}"
        r["change"] = f"{(last - closes[-2]) / closes[-2]:.6f}"
        r["change_5d"] = f"{(last - closes[-6]) / closes[-6]:.6f}" if len(closes) >= 6 else ""
        r["change_20d"] = f"{(last - closes[-21]) / closes[-21]:.6f}" if len(closes) >= 21 else ""
        r["change_60d"] = f"{(last - closes[-61]) / closes[-61]:.6f}" if len(closes) >= 61 else ""
        dates = [d for d, _ in kl]
        try:
            base = closes[dates.index("2025-12-31")]
        except ValueError:
            i26 = next((i for i, d in enumerate(dates) if d >= "2026-01-01"), None)
            base = closes[i26 - 1] if i26 and i26 > 0 else None
        r["ytd"] = f"{(last - base) / base:.6f}" if base else ""
        r["data_status"] = "ok"
        refreshed += 1
        time.sleep(0.08)

    out = [INDICES_FIELDS] + [[r.get(f, "") or "" for f in INDICES_FIELDS] for r in rows]
    INDICES_CSV.write_text("\n".join(",".join(row) for row in out), encoding="utf-8")
    return refreshed, stale


# ---------------------------------------------------------------------------
# 兜底：池子里有 code 但 stocks.csv 没匹配的股票，主动用腾讯实时行情补全
# ---------------------------------------------------------------------------

def _refill_pool_from_quote(stocks: list[dict]) -> int:
    """对池子里所有有 6 位 A 股代码且缺数据的股票，主动 astock.tencent_quote 补实时行情。
    返回补全的股票数。"""
    need_codes: list[str] = []
    for s in stocks:
        code = (s.get("code") or "").strip()
        if len(code) != 6 or not code.isdigit():
            continue
        if s.get("price") in (None, "", 0):
            need_codes.append(code)
    if not need_codes:
        return 0
    try:
        import astock
        quotes = astock.tencent_quote(need_codes)
    except Exception as e:  # noqa: BLE001
        print(f"  [WARN] astock.tencent_quote 失败: {e}")
        return 0
    filled = 0
    for s in stocks:
        code = (s.get("code") or "").strip()
        if len(code) != 6:
            continue
        q = quotes.get(code)
        if not q:
            continue
        if s.get("price") in (None, "", 0):
            try:
                s["price"] = round(float(q["price"]), 2)
                s["change"] = round(float(q["change_pct"]) / 100, 6)
                if q.get("turnover_pct") is not None:
                    s["turnover"] = round(float(q["turnover_pct"]) / 100, 6)
                if q.get("pe_ttm") is not None:
                    s["pe_ttm"] = round(float(q["pe_ttm"]), 2)
                if q.get("pb") is not None:
                    s["pb"] = round(float(q["pb"]), 2)
                s["data_status"] = "live"
                filled += 1
            except (KeyError, TypeError, ValueError):
                continue
    return filled


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="报告日（默认今天）")
    args = ap.parse_args()
    close_time = require_current_close_window(args.date)
    seed_single_source_files()

    pool = json.loads(POOL_PATH.read_text("utf-8"))
    stocks = pool.get("stocks", [])
    coded = [s for s in stocks if s.get("code")]
    print(f"池子 {len(stocks)} 只，有代码 {len(coded)} 只")

    # 1) ulist 快照
    secids = [secid_of(s["code"]) for s in coded]
    snap = fetch_snapshot(secids)
    print(f"快照拉到 {len(snap)} 只")
    missing_codes = sorted({str(s["code"]) for s in coded} - set(snap))
    quote_dates = {
        datetime.fromtimestamp(float(v["f124"]), ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        for v in snap.values() if v.get("f124")
    }
    if missing_codes:
        raise RuntimeError(f"股票池快照覆盖不完整: missing={missing_codes}")
    if quote_dates != {args.date}:
        raise RuntimeError(f"股票池行情日期不匹配: expected={args.date}, actual={sorted(quote_dates)}")

    # 2) kline 算 20日/YTD
    trends: dict[str, tuple[float | None, float | None]] = {}
    for s in coded:
        code = s["code"]
        kl = fetch_eastmoney_kline(code)
        trends[code] = compute_trends(kl)
        time.sleep(0.1)
    ok_trends = sum(1 for s in coded if trends.get(s["code"], (None, None))[0] is not None)
    print(f"20日/YTD 计算完成（有 20日: {ok_trends}/{len(coded)}）")

    # 3) 组装 stocks.csv 行
    rows: list[list[str]] = [CSV_FIELDS]
    missing = []
    for s in stocks:
        code = (s.get("code") or "").strip()
        v = snap.get(code) or {}
        chg20, ytd = trends.get(code, (None, None)) if code else (None, None)
        price = v.get("f2")
        if price is None:
            missing.append(s.get("name", code))
        row = {
            "instrument_id": s.get("instrument_id") or "",
            "code": code,
            "exchange": s.get("exchange") or "",
            "name": s.get("name") or "",
            "industry": s.get("industry") or "",
            "price": f"{price / (1000 if len(code) == 5 else 100):.2f}" if price is not None else "",
            "change": f"{v.get('f3', 0) / 10000:.6f}" if v.get("f3") is not None else "",
            "change_5d": f"{v.get('f109', 0) / 10000:.6f}" if v.get("f109") is not None else "",
            "change_20d": f"{chg20:.6f}" if chg20 is not None else "",
            "ytd": f"{ytd:.6f}" if ytd is not None else "",
            "amount_yi": f"{v.get('f6', 0) / 1e8:.2f}" if v.get("f6") is not None else "",
            "mcap_yi": f"{v.get('f20', 0) / 1e8:.2f}" if v.get("f20") is not None else "",
            "turnover": f"{v.get('f8', 0) / 10000:.6f}" if v.get("f8") is not None else "",
            "pe_ttm": f"{v.get('f9', 0) / 100:.2f}" if v.get("f9") is not None else "",
            "pb": f"{v.get('f23', 0) / 100:.2f}" if v.get("f23") is not None else "",
            "data_status": "ok" if v else "missing",
        }
        rows.append([row[f] for f in CSV_FIELDS])

    if missing:
        raise RuntimeError(f"股票池存在空行情，拒绝写入母表: {missing[:10]}")
    STOCKS_CSV.write_text("\n".join(",".join(r) for r in rows), encoding="utf-8")
    print(f"stocks.csv 已更新（{len(rows) - 1} 行），拉取失败 0 只")

    # 3.1) 自选股不维护逐日全量历史。stocks.csv 是覆盖式轻量缓存；
    # 页面通过 /api/quote 批量覆盖今日字段并在浏览器内重新汇总。

    # 3.5) indices.csv 刷新（标准指数/ETF 刷新，申万/自定义保留旧值标 stale）
    n_ok, n_stale = refresh_indices()
    print(f"indices.csv 已更新：刷新 {n_ok} 个 / 保留旧值 {n_stale} 个（申万/自定义等公开接口无数据）")

    # 3.6) 兜底：池子里有 code 但 stocks.csv 没匹配的股票，主动用腾讯实时行情补全 pool.json
    # 修复"pool 里加了一只但 daily_refresh 没拉到数据"导致全"—"的问题
    filled = _refill_pool_from_quote(stocks)
    if filled:
        print(f"用腾讯实时行情兜底填充 {filled} 只（pool.json 里但 stocks.csv 无对应快照）")

    # 4) pool version = 报告日
    pool["version"] = args.date
    POOL_PATH.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"pool.json version → {args.date}")

    # 5) 重建 payload
    from market_monitor.stock_pool import build_stock_pool_payload  # noqa: PLC0415
    payload = build_stock_pool_payload()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_BUNDLE.write_text(json.dumps({
        "status": "published",
        "data_date": args.date,
        "published_at": close_time.isoformat(timespec="seconds"),
        "payload": payload,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"latest_stock_pool.json 已重建 | report_date={payload['meta']['report_date']} | pending={payload['summary']['pending_refresh']}")
    print("完成 ✅")


if __name__ == "__main__":
    main()
