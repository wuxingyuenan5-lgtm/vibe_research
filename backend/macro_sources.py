"""宏观 / 产业数据源 —— 从上游 simonlin1212/Vibe-Research 移植的取数核心。

与上游的差异：去掉了 `sources._http` 的 raw 落盘 / 证据信封框架，只保留**取数 + 分类 + 过滤**，
HTTP 直连（海外源经本地 Clash 代理，国内源直连）。护栏文字作为 note 一并返回，供前端展示。

数据源：
- CFTC COT 持仓（黄金/白银等，`market_contains` 筛）→ publicreporting.cftc.gov（Socrata）
- 宏观概率（Kalshi + Polymarket，6 核心模块）→ 预测市场零鉴权 API
- 大宗期货（沪铜/锡/铝/镍/工业硅）→ 新浪连续合约（akshare）
- DRAM/NAND 现货 → GitHub 社区仓转录的 DRAMeXchange

⚠️ 护栏（必须与数字同段呈现）：
- 预测市场概率是**市场当前的定价预期**，不是事实也不是预测，只在 as_of 那一刻成立；
  低成交量合约噪音极大。
- 期货价是全市场定价，不是公司采购价；单日波动是噪音，看 30 日方向。
- DRAM 序列来自社区转录，不是官方一手，可能有转录误差与停更。
"""

from __future__ import annotations

import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

# 海外源经本地 Clash 代理（本机直连不通）；国内源直连。VR_PROXY 可覆盖。
_PROXY = os.environ.get("VR_PROXY", "http://127.0.0.1:7890")
_PROXIES = {"http": _PROXY, "https": _PROXY}
UA = "Mozilla/5.0 (vibe-research)"


def _get_overseas(url: str, params: dict | None = None, timeout: int = 20):
    return requests.get(url, params=params, timeout=timeout, proxies=_PROXIES,
                        headers={"User-Agent": UA, "Accept": "application/json"})


def _f(v):
    try:
        x = float(v)
        return x if x == x and x not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────
# 1. CFTC COT 持仓
# ──────────────────────────────────────────────────────────────

def cftc_cot(limit: int = 20, market_contains: str | None = None) -> list[dict]:
    """CFTC COT 持仓报告（Socrata 6dca-aqww，按报告日倒序）。

    market_contains 对合约市场名做子串匹配（如 "GOLD" / "SILVER" / "COPPER"）。
    返回原始行：contract_market_name / report_date / open_interest_all /
    noncomm_positions_long_all / noncomm_positions_short_all / comm_positions_* 等。
    """
    q: dict = {"$limit": limit, "$order": "report_date_as_yyyy_mm_dd DESC"}
    if market_contains:
        q["$where"] = f"upper(contract_market_name) like upper('%{market_contains}%')"
    r = _get_overseas("https://publicreporting.cftc.gov/resource/6dca-aqww.json", params=q)
    r.raise_for_status()
    return r.json()


# ──────────────────────────────────────────────────────────────
# 2. 宏观概率（Kalshi + Polymarket）
# ──────────────────────────────────────────────────────────────

CORE_MODULES = ("货币政策", "宏观经济", "地缘政治", "政治选举", "股指大宗", "AI科技")

# 分类器关键词（移植自 GlobalPercent market_taxonomy.py，判定顺序保持一致）
_GEO = ["china", "taiwan", "tariff", "trade war", "xi jinping", "hormuz", "iran", "venezuela",
        "russia", "ukraine", "blockade", "north korea", "israel", "gaza", "hezbollah", "lebanon",
        "syria", "middle east", " nato", "nuclear", "missile", "ceasefire", "invade", "war ",
        "military", "peace deal", "strike on"]
_MONETARY = ["fed ", "fed decision", "fed funds", "federal reserve", "interest rate", "rate cut",
             "rate hike", "fomc", "powell", "basis point", "rate after"]
_MACRO = ["recession", " gdp", "inflation", " cpi", "unemployment", "jobs report", "jobs numbers",
          "payroll", "nonfarm", "jobless", " ppi", " pce", "gas price"]
_AI = ["nvidia", "openai", " agi", "semiconductor", "tsmc", " chip", "anthropic", "gpt", "chatgpt",
       "llm", "grok", "gemini", "claude", "deepmind", "artificial intelligence", "best ai",
       "humanoid robot", "deepseek"]
_INDEX = ["s&p", "nasdaq", "dow ", " stock", "earnings", " ipo", "market cap", "crude oil",
          "wti", "brent", "oil price", "gold price", "gold hit", "gold above", " xau",
          "commodit", " spy ", "valuation"]
_ELECTION = ["election", "president", " senate", "congress", "nominee", "potus", "white house",
             "governor", " mayor", "parliament", "prime minister", "referendum", "trump", "newsom",
             " vance", "midterm", "impeach", "attorney general", "reconciliation", "election winner"]
_CRYPTO = ["bitcoin", " btc", "ethereum", "crypto", "microstrategy", " mstr", "solana", "dogecoin",
           "coinbase", "stablecoin", "ripple", " xrp"]
_SPORTS = ["nba", "nfl", " mlb", "world series", "super bowl", "stanley cup", "tennis", " atp", " wta",
           "wimbledon", "us open", "french open", "australian open", "ufc", "boxing", "premier league",
           "la liga", "champions league", "grand prix", " pga ", "esports", " lol ", "cs2", "valorant",
           "dota", " vs.", " vs ", "world cup", "fifa", "golf", "tournament", "playoff", "champion"]
_ENT = ["movie", "oscar", "grammy", "box office", "taylor swift", "tweet", "person of the year",
        "rotten tomatoes", "billboard", "spotify", "netflix", "love island", "celebrity", "album",
        " song ", "emmy", "what will"]
_KALSHI_CAT = {"Economics": "宏观经济", "Financials": "股指大宗", "Commodities": "股指大宗",
               "Companies": "股指大宗", "Elections": "政治选举", "Politics": "政治选举",
               "World": "地缘政治", "Crypto": "加密", "Sports": "体育", "Entertainment": "娱乐"}


def _classify(question: str | None, kalshi_category: str | None = None) -> str:
    t = " " + (question or "").lower() + " "
    if "world cup" in t or "fifa" in t:
        return "体育"
    for kws, mod in ((_GEO, "地缘政治"), (_MONETARY, "货币政策"), (_MACRO, "宏观经济"), (_AI, "AI科技"),
                     (_CRYPTO, "加密"), (_INDEX, "股指大宗"), (_ELECTION, "政治选举"),
                     (_SPORTS, "体育"), (_ENT, "娱乐")):
        if any(k in t for k in kws):
            return mod
    return _KALSHI_CAT.get(kalshi_category or "", "其他")


def _days_out(close_day: str | None, today: str) -> int | None:
    if not close_day or len(close_day) != 10:
        return None
    try:
        return (datetime.strptime(close_day, "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days
    except ValueError:
        return None


def _kalshi_macro() -> list[dict]:
    """Kalshi 定向取宏观合约：/series?category=Economics|Financials → /events?series_ticker=。

    ⚠️ category 参数在 /series 有效、在 /events 被服务端忽略（实测）。成交量字段是
    volume_24h_fp / open_interest_fp（带 _fp 后缀，且可能返回字符串）。
    并发：2 个 category 的 series 并行，各 series 的 events 并行（最多 24 个请求）。
    """
    cats = ("Economics", "Financials")

    def _fetch_series(cat: str):
        try:
            s = _get_overseas("https://api.elections.kalshi.com/trade-api/v2/series",
                              params={"category": cat, "limit": 100})
            return cat, s.json().get("series") or []
        except Exception:
            return cat, []

    series_by_cat: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        for cat, series in ex.map(_fetch_series, cats):
            series_by_cat[cat] = series

    jobs = []
    for cat in cats:
        for ser in series_by_cat.get(cat, [])[:12]:
            ticker = ser.get("ticker")
            if ticker:
                jobs.append((cat, ticker))

    def _fetch_events(cat_ticker):
        cat, ticker = cat_ticker
        res = []
        try:
            e = _get_overseas("https://api.elections.kalshi.com/trade-api/v2/events",
                              params={"series_ticker": ticker, "status": "open", "with_nested_markets": "true"})
            events = e.json().get("events") or []
        except Exception:
            return res
        for ev in events:
            title = ev.get("title") or ""
            close = ev.get("close_time") or ""
            if close:
                close = close[:10]
            # 多腿事件取最接近 50% 的那条腿
            markets = ev.get("markets") or []
            best, bestd = None, 9.9
            for m in markets:
                p = _f(m.get("yes_ask")) or (_f(m.get("last_price")) / 100 if _f(m.get("last_price")) is not None else None)
                if p is None or not 0 < p < 1:
                    continue
                d = abs(p - 0.5)
                if d < bestd:
                    best, bestd = p, d
            if best is None:
                continue
            res.append({
                "source": "kalshi", "title": title, "prob": round(best, 4),
                "close_date": close or None,
                "volume_24h": _f(ev.get("volume_24h")) or _f(ev.get("volume_24h_fp")) or 0.0,
                "open_interest": _f(ev.get("open_interest")) or _f(ev.get("open_interest_fp")) or 0.0,
                "category": cat,
            })
        return res

    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for chunk in ex.map(_fetch_events, jobs):
            out.extend(chunk)
    return out


def _polymarket_macro() -> list[dict]:
    """Polymarket 定向取宏观合约：翻页拿 markets，本地按标题分类。

    ⚠️ 排序参数是 volume24hr（无下划线），官方文档写 volume_24hr 是错的（实测 422）。
    并发：4 页并行取，各页独立解析。
    """
    def _fetch_page(page: int):
        res = []
        try:
            r = _get_overseas("https://gamma-api.polymarket.com/markets",
                              params={"limit": 100, "offset": page * 100, "active": "true",
                                      "closed": "false", "order": "volume24hr", "ascending": "false"})
            rows = r.json()
        except Exception:
            return res
        if not isinstance(rows, list) or not rows:
            return res
        for row in rows:
            title = row.get("question") or row.get("slug") or ""
            close = row.get("endDate") or ""
            close = close[:10] if close else None
            # 结构化体育标记优先，避免球队名（如 Borussia 含 russia）误判地缘
            events = row.get("events") or []
            is_sport = bool(row.get("sportsMarketType")) or any(isinstance(e, dict) and e.get("gameId") for e in events)
            mod = "体育" if is_sport else _classify(title)
            if mod not in CORE_MODULES:
                continue
            p = _f(row.get("lastTradePrice")) or _f(row.get("outcomePrices"))
            if p is None or not 0 < p < 1:
                continue
            res.append({
                "source": "polymarket", "title": title, "prob": round(p, 4),
                "close_date": close,
                "volume_24h": _f(row.get("volume24hr")) or 0.0,
                "open_interest": _f(row.get("liquidity")) or 0.0,
                "category": None,
            })
        return res

    out = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for chunk in ex.map(_fetch_page, range(4)):
            out.extend(chunk)
    return out


def macro_probability(per_module: int = 3) -> dict:
    """宏观概率：Kalshi + Polymarket，6 核心模块，每模块按 max(24h量, 持仓) 取 top N。

    返回 {as_of, guard, modules: {模块: [合约...]}}。参考类（加密/体育/娱乐/其他）丢弃。
    两个源并行取数，总耗时 = max(两源) 而非两源之和。
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_k = ex.submit(_kalshi_macro)
        f_p = ex.submit(_polymarket_macro)
        contracts = f_k.result() + f_p.result()

    buckets: dict[str, list] = {m: [] for m in CORE_MODULES}
    for c in contracts:
        mod = _classify(c["title"], c.get("category"))
        if mod not in CORE_MODULES:
            continue
        d = _days_out(c.get("close_date"), today)
        # 过滤：过期 / 远期无成交的僵尸盘
        if d is not None and d < 0:
            continue
        if d is not None and d > 800:
            continue
        if c["volume_24h"] <= 0 and c["open_interest"] <= 0:
            continue
        if d is not None and d > 180 and c["volume_24h"] <= 0:
            continue
        buckets[mod].append(c)

    result = {}
    for mod in CORE_MODULES:
        items = sorted(buckets[mod], key=lambda x: max(x["volume_24h"], x["open_interest"]), reverse=True)
        result[mod] = items[:per_module]

    return {
        "as_of": today,
        "guard": ("预测市场概率是市场当前的定价预期，不是事实也不是预测，只在 as_of 那一刻成立；"
                  "低成交量合约噪音极大，量小的不要当信号。"),
        "modules": result,
    }


# ──────────────────────────────────────────────────────────────
# 3. 大宗期货 + DRAM 现货
# ──────────────────────────────────────────────────────────────

_FUTURES = {
    "CU0": ("沪铜", "元/吨", "PCB 铜箔 / 铜缆 / 液冷管路 / 电力电缆"),
    "SN0": ("沪锡", "元/吨", "焊料凸点与 BGA 焊球"),
    "AL0": ("沪铝", "元/吨", "液冷散热器 / 机箱 / 结构件"),
    "NI0": ("沪镍", "元/吨", "MLCC 电极浆料 / 合金"),
    "SI0": ("工业硅", "元/吨", "硅基半导体源头；需求由光伏主导，对半导体是弱信号"),
}

_DRAM_SOURCES = [
    {"key": "DDR5", "url": "https://raw.githubusercontent.com/nlee756525/dram-prices/main/history.json",
     "path": "ddr5", "avg": "session_avg"},
    {"key": "NAND_TLC", "url": "https://raw.githubusercontent.com/nlee756525/dram-prices/main/history.json",
     "path": "tlc", "avg": "session_avg"},
    {"key": "DDR4", "url": "https://raw.githubusercontent.com/titled-agent-001/ddr4-pricing-log/main/ddr4-pricing.json",
     "path": "logs", "avg": "session_average"},
]


def commodity_futures() -> dict:
    """大宗期货：新浪连续合约（akshare futures_zh_daily_sina），最新收盘 + 1日/1周/1月涨跌。

    并发：5 个品种并行取数。
    """
    import astock
    ak = astock._akshare()

    def _one(item):
        code, (name, unit, use) = item
        try:
            df = astock._ak_call(ak.futures_zh_daily_sina, symbol=code)
            if df is None or df.empty:
                return None
            df = df.tail(30).reset_index(drop=True)
            last = df.iloc[-1]
            close = float(last["close"])
            n = len(df)
            def pct(back: int):
                idx = n - 1 - back  # back=1 是上一交易日，back=5 约一周，back=21 约一月
                if idx < 0:
                    return None
                base = float(df.iloc[idx]["close"])
                return round((close - base) / base * 100, 2) if base else None
            return {
                "code": code, "name": name, "unit": unit, "use": use,
                "close": close,
                "date": str(last["date"]),
                "chg_1d": pct(1), "chg_1w": pct(5), "chg_1m": pct(21),
            }
        except Exception:
            return None

    result = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        for r in ex.map(_one, _FUTURES.items()):
            if r:
                result.append(r)

    return {
        "guard": "期货价是全市场定价不是公司采购价；传导到毛利有季度级滞后并被长约与套保平滑；"
                 "单日波动是噪音，看 30 日方向；工业硅需求由光伏主导，对半导体是弱信号。",
        "futures": result,
    }


def dram_spot() -> dict:
    """DRAM / NAND 现货均价（GitHub 社区仓转录的 DRAMeXchange，非官方一手）。

    并发：3 个源并行取数。
    """
    def _one(src):
        try:
            r = requests.get(src["url"], timeout=20, proxies=_PROXIES, headers={"User-Agent": UA})
            payload = r.json()
        except Exception:
            return None
        seq = payload.get(src["path"]) if isinstance(payload, dict) else None
        if not isinstance(seq, list) or not seq:
            return None
        latest = seq[-1]
        return {
            "key": src["key"],
            "latest_avg": _f(latest.get(src["avg"])),
            "date": latest.get("date") or latest.get("timestamp") or latest.get("day"),
        }

    result = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        for r in ex.map(_one, _DRAM_SOURCES):
            if r:
                result.append(r)

    return {
        "guard": "序列来自社区转录的 DRAMeXchange 存档，不是官方一手（可能有转录误差与停更）；"
                 "DRAM 现货是 HBM 的影子指标，不是 HBM 价格。",
        "dram": result,
    }
