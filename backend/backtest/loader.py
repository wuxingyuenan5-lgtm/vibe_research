"""把本产品的取数层接到回测引擎上 —— 移植时唯一需要改写的代码。

引擎与数据之间只有一条缝：``loader.fetch()`` 返回 ``{代码: OHLCV DataFrame}``。
上游走 baostock / yahoo（经注册表端点 + raw 落盘）；本 fork 的数据层是
akshare + 东财/同花顺 + 腾讯，且**本机直连东财 push2his 不通**（Clash 掐连接），
故这里改用**新浪财经前复权日线**（akshare 三接口，本机实测可达）：

    A股    600519.SH / 300308.SZ / 300308   → stock_zh_a_daily（新浪，qfq）
    美股    AAPL / NVDA                      → stock_us_daily（新浪，qfq，全量）
    港股    00700.HK / 0700.HK               → stock_hk_daily（新浪，qfq，全量）

🔴 **只做日线**。要 5 分钟线就明说取不到，绝不悄悄拿日线顶替 ——
   那会让一个"日内策略"的回测结果看着完全正常，而它测的根本不是日内。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

import astock  # 触发 requests trust_env=False patch + 复用 akshare 惰性封装/重试

from backtest.engines._market_hooks import _detect_market

SUPPORTED_MARKETS = ("a_share", "us_equity", "hk_equity")
#: 引擎按 bar 撮合，这一版只喂日线。上游支持的分钟级要等做 T 那一期。
SUPPORTED_INTERVALS = ("1D", "1d", "D", "day", "daily")


class LoaderError(RuntimeError):
    """取数在**能不能开始回测**这一层就失败了 —— 不该被当成"这只票没数据"往下走。"""


def price_basis(market: str) -> str:
    """Source-specific price/accounting limits, shared by preview and runtime disclosure."""
    source = (
        "A 股取新浪财经前复权日线（adjust=qfq），不是当日未复权成交价；复权影响不等于分红现金到账。"
        if market == "a_share" else
        "港美股取新浪财经前复权日线（adjust=qfq），不使用 adjclose；不可把它当作含分红的总回报序列。"
    )
    return source + "引擎不单独记现金分红、再投资或公司行动现金流。历史序列按本次取数版本重建，可能随公司行动或上游修订重述，并非当时可见快照；不同日期重跑可变，收益偏差方向不作保证。"


@dataclass
class SymbolProvenance:
    """一只票的数据来自哪儿 —— 回测结论要能顺着这条链查回去。"""

    code: str
    market: str
    endpoint: str
    raw_refs: List[str] = field(default_factory=list)
    rows: int = 0
    first_bar: Optional[str] = None
    last_bar: Optional[str] = None
    halted_bars: int = 0
    note: str = ""
    price_basis: str = ""


def canonical_code(code: str) -> str:
    """把代码规整成**市场判得出来**的写法。

    ``_detect_market`` 对认不出的格式一律回落 ``a_share`` —— 也就是说打错的美股代码
    会被静默当成 A 股去跑（T+1、涨跌停、整手全套上身），而结果看着完全正常。
    ⇒ 六位纯数字在这里就补上交易所后缀，让归属是**判出来的**而不是**兜底兜出来的**。
    """
    c = str(code).strip().upper()
    if not c:
        raise LoaderError("代码是空的")
    # baostock 风格 sz.300308 / sh.600519 → 300308.SZ
    m = re.fullmatch(r"(SZ|SH|BJ)\.(\d{6})", c)
    if m:
        return f"{m.group(2)}.{m.group(1)}"
    if re.fullmatch(r"\d{6}", c):
        return f"{c}.{_a_share_exchange(c)}"
    return c


def _a_share_exchange(six: str) -> str:
    """六位代码 → 交易所后缀。

    按号段前缀查表，**认不出就报错**，不猜一个 —— 猜错的后果是整只票用错市场规则
    （涨跌停带、T+1、费率全套），而回测结果看着完全正常。
    """
    return _a_lookup(six)[0]


#: 号段 → (交易所, 是不是个股)。长前缀在前，匹配到第一个即用。
#: 🔴 `is_stock=False` 的（ETF / 指数 / 可转债）在这一版取不到 —— 新浪的
#:    前复权日 K 是**个股**接口，对它们返回 0 行而**不报错**。不在这儿拦住，
#:    就会变成「回测跑完了、结果是空的」，而空的原因没人看得出来。
_A_PREFIX: tuple[tuple[str, str, bool], ...] = (
    # 上交所
    ("688", "SH", True), ("689", "SH", True),          # 科创板
    ("110", "SH", False), ("111", "SH", False), ("113", "SH", False),  # 沪市可转债
    ("6", "SH", True),                                  # 主板股票
    ("50", "SH", False), ("51", "SH", False), ("52", "SH", False),
    ("53", "SH", False), ("56", "SH", False), ("58", "SH", False),     # 沪市基金 / ETF
    # 深交所
    ("300", "SZ", True), ("301", "SZ", True), ("302", "SZ", True),     # 创业板
    ("000", "SZ", True), ("001", "SZ", True),
    ("002", "SZ", True), ("003", "SZ", True),           # 主板
    ("12", "SZ", False),                                # 深市可转债
    ("15", "SZ", False), ("16", "SZ", False), ("18", "SZ", False),     # 深市基金 / ETF
    # 北交所
    ("43", "BJ", True), ("83", "BJ", True), ("87", "BJ", True),
    ("88", "BJ", True), ("92", "BJ", True),
)


def _a_lookup(six: str) -> tuple[str, bool]:
    for prefix, ex, is_stock in _A_PREFIX:
        if six.startswith(prefix):
            return ex, is_stock
    raise LoaderError(f"认不出六位代码 {six} 属于哪个交易所，请写全后缀，如 {six}.SH / {six}.SZ")


def assert_a_share_stock(code: str) -> None:
    """A 股这一版只回测**个股**。ETF / 指数 / 可转债 明确拒掉，不让它静默跑出空结果。"""
    six = bare(code)
    try:
        _, is_stock = _a_lookup(six)
    except LoaderError:
        return          # 认不出的交给取数时报错，别在这儿抢着下结论
    if not is_stock:
        raise LoaderError(
            f"{code} 不是个股（ETF / 指数 / 可转债 号段）—— 这一版的日线取数只覆盖个股，"
            f"对它返回的是空序列而不是报错，所以在这里就拦下来"
        )


def bare(code: str) -> str:
    """去掉交易所后缀，取端点要的裸代码。"""
    return code.split(".")[0]


#: 三种支持的写法 → 市场。**由我们自己判**，不依赖上游的兜底。
_SHAPES: tuple[tuple[Any, str], ...] = (
    (re.compile(r"^\d{6}\.(SZ|SH|BJ)$", re.I), "a_share"),
    (re.compile(r"^\d{3,5}\.HK$", re.I), "hk_equity"),
    # 美股代码 1-5 位字母（NYSE / Nasdaq 的实际上限）。
    # ⚠️ 放宽到 10 位就会把 EURUSD / BTCUSDT 收进来 —— 它们随后会被上游的兜底
    #    判成 a_share 拿去查 baostock。**第一版这里就是写宽了，被测试抓出来的。**
    (re.compile(r"^[A-Z]{1,5}$"), "us_equity"),
)


def market_of(code: str) -> str:
    """判市场。**认不出就报错，不兜底；与上游判定不一致也报错。**

    🔴 上游 `_detect_market` 对认不出的格式一律回落 `a_share`。在只支持三个市场的
       这一版里，那个回落把「不支持」变成了「用错市场规则跑完，结果看着正常」。
    🔴 所以这里**自己判**，再拿上游的结论交叉核对：两边不一致说明这个写法处在
       某种灰色地带（如 BRK.B），宁可拒掉也不选一边 —— 选错那边就是上面那种静默错。
    """
    c = canonical_code(code)
    mine = next((m for pat, m in _SHAPES if pat.fullmatch(c)), None)
    if mine is None:
        raise LoaderError(
            f"认不出 {code!r} 是哪个市场的代码。这一版认这三种写法："
            "A股 600519.SH / 美股 AAPL / 港股 00700.HK"
        )
    theirs = _detect_market(c)
    if theirs != mine:
        raise LoaderError(
            f"{code!r} 的市场归属有歧义（本层判 {mine}，引擎侧判 {theirs}）—— "
            f"已拒绝。归属判错意味着整只票套错市场规则，而回测结果看不出异常"
        )
    return mine


def _to_ns_index(df: pd.DataFrame) -> pd.DataFrame:
    """把索引统一成 ``datetime64[ns]``。

    🔴 pandas 3 会**保留**原始时间分辨率：不同源解析出来可能是 ``[us]`` / ``[s]``；
       而上游 ``_align`` 里 ``pd.DatetimeIndex(index.asi8)`` 把整数一律当**纳秒**解释
       （pandas 2 一律压成纳秒，所以上游没这问题）。
       秒被当纳秒 → 所有 bar 掉到 1970 年 → 与信号完全对不上 → **一笔都不成交**。

    ⚠️ 这个 bug **不抛异常**：它产出的是一份"总收益 0.00%、最大回撤 0.00%"的
       完整报告，排版整齐、指标齐全。⇒ 在数据边界钉死分辨率，并在下面断言。
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise LoaderError(f"索引不是时间索引：{type(df.index).__name__}")
    if df.index.dtype != "datetime64[ns]":
        df = df.copy()
        df.index = df.index.astype("datetime64[ns]")
    return df


# ── 取数（新浪财经，本 fork 适配） ──

#: 新浪三个接口的列名 → 标准列名。三市场公共列：date/open/high/low/close/volume。
_SINA_COLMAP = {
    "date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
    "turnover": "turn",
    "outstanding_share": "outstanding_share",
}


def _sina_symbol(code: str, market: str) -> str:
    """把带后缀的写法转成新浪要的 symbol。"""
    six = bare(code)
    if market == "a_share":
        # 新浪 A 股要 sh600519 / sz000001 / bj 前缀
        ex = code.split(".")[-1].lower()
        return f"{ex}{six}"
    if market == "hk_equity":
        return six.zfill(5)
    return six  # 美股裸 ticker


def _frame_from_sina(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """新浪日线 DataFrame → 标准 OHLCV DataFrame（datetime64[ns] 索引）。

    新浪列名是英文（date/open/high/low/close/volume/[amount/turnover]），
    直接 rename 到标准名。pre_close 没有原值，用 close.shift(1) 近似（除权日会偏，
    但除权一年仅 1-2 次，对回测收益影响可忽略）。
    """
    if df is None or df.empty:
        return pd.DataFrame(), 0
    out = pd.DataFrame()
    for src, dst in _SINA_COLMAP.items():
        if src in df.columns:
            out[dst] = df[src]
    if "date" not in out.columns:
        raise LoaderError("新浪日线返回里没有 date 列，无法解析")
    out["date"] = pd.to_datetime(out["date"])
    out = out.set_index("date").sort_index()
    # 前收：用上一根收盘近似（引擎判涨跌停时找 pre_close）
    out["pre_close"] = out["close"].shift(1)
    out.loc[out.index[0], "pre_close"] = out["open"].iloc[0]
    # 剔除 OHLC 缺值/非正的行（新浪美股偶有缺值行）
    before = len(out)
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out[out[["open", "high", "low", "close"]].map(lambda v: pd.notna(v) and float(v) > 0).all(axis=1)]
    return out, before - len(out)


def _fetch_sina(code: str, start_date: str, end_date: str, market: str) -> pd.DataFrame:
    """经 akshare 的新浪日线接口取数；A股支持区间，美股/港股全量后自行切片。"""
    ak = astock._akshare()
    sym = _sina_symbol(code, market)
    try:
        if market == "a_share":
            df = astock._ak_call(
                ak.stock_zh_a_daily, symbol=sym,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""), adjust="qfq")
        elif market == "us_equity":
            df = astock._ak_call(ak.stock_us_daily, symbol=sym, adjust="qfq")
        else:  # hk_equity
            df = astock._ak_call(ak.stock_hk_daily, symbol=sym, adjust="qfq")
    except Exception as exc:  # noqa: BLE001
        raise LoaderError(f"新浪取 {sym} 失败：{type(exc).__name__}: {exc}") from exc
    # 美股/港股接口返回全量，不在这里切片（date 列类型不统一，str/date 混用会炸），
    # 交给 _fetch_one 里 _frame_from_sina 转成 datetime 索引后统一 .loc[start:end]。
    return df if df is not None and not df.empty else pd.DataFrame()


class VibeLoader:
    """回测引擎眼里的"数据源"。

    引擎只调 ``fetch()``；``name`` 是 benchmark 那边用 ``getattr`` 读的。
    """

    name = "sina"

    def __init__(self, out_dir: Path = None, python: Optional[str] = None, timeout: int = 120) -> None:
        self.out_dir = Path(out_dir) if out_dir else None
        self.python = python
        self.timeout = timeout
        #: 每只票的来源，回测报告要用
        self.provenance: Dict[str, SymbolProvenance] = {}
        #: 一根 bar 都没取到的票 —— **不是空着算了**，交给上层决定是拒跑还是缩小范围
        self.failures: Dict[str, str] = {}

    # ── 引擎调的就是这一个 ──
    def fetch(self, codes: Iterable[str], start_date: str, end_date: str,
              fields: Optional[Any] = None, interval: str = "1D") -> Dict[str, pd.DataFrame]:
        if interval not in SUPPORTED_INTERVALS:
            raise LoaderError(
                f"这一版只做日线，取不到 {interval!r} 的数据。"
                "别把它当日线跑 —— 那样出来的结果测的不是你想测的东西。"
            )
        out: Dict[str, pd.DataFrame] = {}
        for raw_code in codes:
            code = canonical_code(raw_code)
            try:
                df, prov = self._fetch_one(code, start_date, end_date)
            except LoaderError as exc:
                self.failures[code] = str(exc)
                self.provenance.pop(code, None)     # 同一只票不能既成功又失败
                continue
            except Exception as exc:                # noqa: BLE001
                self.failures[code] = f"{type(exc).__name__}: {exc}"
                self.provenance.pop(code, None)
                continue
            if df.empty:
                self.failures[code] = "区间内一根 bar 都没有"
                self.provenance.pop(code, None)
                continue
            out[code] = df
            self.provenance[code] = prov
            self.failures.pop(code, None)           # 这次成功了，清掉上一次的失败记录
        return out

    def _fetch_one(self, code: str, start_date: str, end_date: str):
        mkt = market_of(code)
        if mkt not in SUPPORTED_MARKETS:
            raise LoaderError(f"这一版只支持 A股 / 美股 / 港股，{code} 判为 {mkt}")

        if mkt == "a_share":
            assert_a_share_stock(code)
            if code.endswith(".BJ") and date.fromisoformat(start_date) < date(2021, 11, 15):
                raise LoaderError("北交所仅支持 2021-11-15 起的区间；此前精选层/新三板规则未建模")
            endpoint = "sina_a_daily"
        elif mkt == "us_equity":
            endpoint = "sina_us_daily"
        else:
            endpoint = "sina_hk_daily"

        raw_df = _fetch_sina(code, start_date, end_date, mkt)
        df, dropped = _frame_from_sina(raw_df)

        if not df.empty:
            df = _to_ns_index(df).loc[str(start_date):str(end_date)]
            # 分辨率一旦漂回去，表现是「回测跑完但零成交」，不是报错，所以必须在这里挡住。
            # ⚠️ 不用 assert：`python -O` 会把 assert 整条删掉，而这正是最不能被关掉的一道。
            if df.index.dtype != "datetime64[ns]":
                raise LoaderError(f"索引分辨率没钉住：{df.index.dtype}（应为 datetime64[ns]）")

        prov = SymbolProvenance(
            code=code, market=mkt, endpoint=endpoint, raw_refs=[],
            rows=len(df),
            first_bar=str(df.index[0].date()) if len(df) else None,
            last_bar=str(df.index[-1].date()) if len(df) else None,
            halted_bars=dropped,
            note=("停牌 / 无成交 %d 根已剔除" % dropped) if dropped else "",
            price_basis=price_basis(mkt),
        )
        return df, prov
