"""取数适配层测试 —— 全部离线。

这一层踩过的坑有个共同形状：**不报错，给一个看着正常的结果**。
所以每条测试针对的都是「静默错」，而不是「会不会抛异常」。

本 fork 已把上游的 baostock/yahoo/subprocess 取数层重写为**新浪财经直连**
（`_fetch_sina` + `_frame_from_sina`），故上游针对 baostock/yahoo 解析器、
subprocess 取数信封、`_assert_same_instrument`、`_yahoo_range` 的用例已随机制一并删除；
下面保留的是仍适用的通用逻辑（代码规整 / 市场判定 / 分辨率 / 闸口一致性 / 成功失败清除）。
"""
from __future__ import annotations

import os
import sys
import pathlib

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from backtest.loader import (  # noqa: E402
    LoaderError, VibeLoader, SymbolProvenance, _to_ns_index,
    assert_a_share_stock, canonical_code, market_of,
)


@pytest.mark.parametrize("raw,want", [
    ("600519", "600519.SH"), ("601127", "601127.SH"), ("688981", "688981.SH"),
    ("000001", "000001.SZ"), ("002050", "002050.SZ"), ("300308", "300308.SZ"),
    ("430139", "430139.BJ"), ("870204", "870204.BJ"),
    ("sz.300308", "300308.SZ"), ("sh.600519", "600519.SH"),
    ("aapl", "AAPL"), ("00700.hk", "00700.HK"),
])
def test_canonical_code(raw, want):
    assert canonical_code(raw) == want


def test_bare_code_without_a_known_range_is_refused():
    """认不出就报错，不猜 —— 猜错的后果是整只票用错市场规则，而结果看着正常。"""
    with pytest.raises(LoaderError):
        canonical_code("999999")


@pytest.mark.parametrize("code,mkt", [
    ("600519.SH", "a_share"), ("300308.SZ", "a_share"),
    ("AAPL", "us_equity"), ("NVDA", "us_equity"), ("00700.HK", "hk_equity"),
])
def test_market_of(code, mkt):
    assert market_of(code) == mkt


@pytest.mark.parametrize("bad", [
    "^HSI", "BTC/USDT", "RB2410.SHFE", "RELIANCE.NS", "EURUSD=X",
    # 👇 这四个是测试自己抓出来的：形状守卫原本写得太宽（美股放到 10 位字母），
    #    它们通过了形状检查，然后被上游的兜底判成 a_share 拿去查 baostock，
    #    而闸口**放行**。「我以为堵上了」的地方恰恰没堵。
    "EURUSD", "BTCUSDT", "RELIANCE", "BRK.B",
])
def test_market_of_refuses_instead_of_defaulting_to_a_share(bad):
    """🔴 上游 `_detect_market` 认不出时一律回落 a_share。
    在只支持三个市场的这一版里，那个回落会把「不支持」变成「用错规则跑完」。"""
    with pytest.raises(LoaderError):
        market_of(bad)


@pytest.mark.parametrize("code", ["510300.SH", "159915.SZ", "113050.SH", "128036.SZ"])
def test_non_stock_a_share_codes_refused(code):
    """ETF / 指数 / 可转债：新浪个股日线对它们返回**空序列而不报错**。"""
    with pytest.raises(LoaderError, match="不是个股"):
        assert_a_share_stock(code)


@pytest.mark.parametrize("code", ["600519.SH", "300308.SZ", "000001.SZ", "430139.BJ"])
def test_stock_codes_pass(code):
    assert_a_share_stock(code) is None


def test_pre_bse_history_refused_before_fetch(tmp_path, monkeypatch):
    import backtest.loader as loader
    monkeypatch.setattr(loader, "_fetch_sina", lambda *a, **kw: pytest.fail("unsupported history must not fetch"))
    ld = VibeLoader(out_dir=tmp_path)
    with pytest.raises(LoaderError, match="2021-11-15"):
        ld._fetch_one("430047.BJ", "2020-01-01", "2024-01-01")


# ── 时间分辨率：最重要的一条 ──

@pytest.mark.parametrize("unit", ["s", "us", "ms", "ns"])
def test_index_is_normalised_to_nanoseconds(unit):
    """🔴 pandas 3 保留原始分辨率，秒被当纳秒 → 所有 bar 掉到 1970 年 →
    与信号完全对不上 → **一笔都不成交**，且**不抛异常**：产出一份「总收益 0.00%」报告。"""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"]).astype(f"datetime64[{unit}]")
    df = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
    out = _to_ns_index(df)
    assert out.index.dtype == "datetime64[ns]"
    assert out.index[0].year == 2024, "归一后日期必须还是 2024，不能掉到 1970"


def test_to_ns_index_rejects_a_non_time_index():
    with pytest.raises(LoaderError):
        _to_ns_index(pd.DataFrame({"close": [1.0]}, index=[0]))


# ── 粒度 ──

@pytest.mark.parametrize("interval", ["1m", "5m", "15m", "1H", "4H"])
def test_non_daily_interval_refused(interval, tmp_path):
    """拿日线顶替分钟线，回测结果看着完全正常，但它测的不是日内。"""
    with pytest.raises(LoaderError, match="日线"):
        VibeLoader(out_dir=tmp_path).fetch(["600519.SH"], "2024-01-01", "2024-02-01", interval=interval)


def test_gate_refuses_everything_market_of_refuses():
    """闸口与取数层必须口径一致 —— 取数层拒绝的，闸口不能放行（反过来也一样）。"""
    from backtest.gate import Refusal, plan_backtest
    for code in ["EURUSD", "BTCUSDT", "BRK.B", "^HSI", "RELIANCE", "999999"]:
        with pytest.raises(LoaderError):
            market_of(code)
        got = plan_backtest(codes=[code], start="2021-01-01", end="2025-12-31", style="long")
        assert isinstance(got, Refusal), f"{code} 取数层拒绝了，闸口却放行"
    for code in ["510300.SH", "159915.SZ", "113050.SH", "128036.SZ"]:
        with pytest.raises(LoaderError):
            assert_a_share_stock(code)
        got = plan_backtest(codes=[code], start="2021-01-01", end="2025-12-31", style="long")
        assert isinstance(got, Refusal), f"{code} 取数层拒绝了，闸口却放行"
        assert "不是个股" in got.reason, f"{code} 的拒绝理由要说到点子上"


def test_ambiguous_ticker_shapes_are_refused():
    """`BRK.B` 这类带类别后缀的写法：本层不认，直接拒 —— 不猜成美股也不兜底成 A股。"""
    for code in ["BRK.B", "BF.A", "RDS.A"]:
        with pytest.raises(LoaderError):
            market_of(code)


def test_cross_check_branch_rejects_a_disagreement(monkeypatch):
    """交叉核对分支本身的测试。

    ⚠️ **诚实地说清楚**：在当前的形状（美股 1-5 位纯字母）下，这个分支
    **不可达** —— 上游对 1-5 位纯字母同样判 us_equity，两边永远一致。
    它是第二层：只有将来形状被放宽（比如放到 10 位、把 EURUSD 收进来）时才承重。
    """
    import backtest.loader as L
    monkeypatch.setattr(L, "_detect_market", lambda c: "kr_equity")
    with pytest.raises(LoaderError, match="歧义"):
        L.market_of("AAPL")


def test_both_layers_independently_refuse_a_forex_pair(monkeypatch):
    """两层各自都拦得住 EURUSD —— 冗余是真的，不是一层掩着另一层。"""
    import backtest.loader as L
    # 只留形状这一层（把交叉核对变成永远一致）
    monkeypatch.setattr(L, "_detect_market", lambda c: "us_equity")
    with pytest.raises(LoaderError, match="认不出"):
        L.market_of("EURUSD")


# ── 以下针对 Codex 审计指出的问题（每条都做过变异验证）──

def test_ns_guard_survives_python_dash_O():
    """分辨率守卫不能用 assert —— `python -O` 会把 assert 整条删掉，
    而这正是最不能被关掉的一道（它防的是那个不抛异常的静默错）。"""
    src = (pathlib.Path(__file__).resolve().parents[1] / "loader.py").read_text()
    body = src[src.index("def _fetch_one"):]
    assert "assert df.index.dtype" not in body, "关键守卫不能写成 assert"
    assert "datetime64[ns]" in body and "raise LoaderError" in body


def test_success_clears_a_previous_failure_for_the_same_code(tmp_path, monkeypatch):
    """同一只票不能既在 failures 又在 provenance —— 报告层会同时看到「成功」和「失败」。"""
    ld = VibeLoader(out_dir=tmp_path)
    ld.failures["600519.SH"] = "上一次超时"
    df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
                      index=pd.to_datetime(["2024-01-02"]).astype("datetime64[ns]"))
    prov = SymbolProvenance(code="600519.SH", market="a_share", endpoint="x", rows=1)
    monkeypatch.setattr(ld, "_fetch_one", lambda c, s, e: (df, prov))
    ld.fetch(["600519.SH"], "2024-01-01", "2024-02-01")
    assert "600519.SH" not in ld.failures
    assert "600519.SH" in ld.provenance


def test_failure_clears_a_previous_success_for_the_same_code(tmp_path, monkeypatch):
    ld = VibeLoader(out_dir=tmp_path)
    ld.provenance["600519.SH"] = SymbolProvenance(code="600519.SH", market="a_share", endpoint="x", rows=9)
    def boom(c, s, e): raise LoaderError("这次挂了")
    monkeypatch.setattr(ld, "_fetch_one", boom)
    ld.fetch(["600519.SH"], "2024-01-01", "2024-02-01")
    assert "600519.SH" in ld.failures and "600519.SH" not in ld.provenance


def test_unexpected_parse_error_lands_in_failures(tmp_path, monkeypatch):
    """解析层的意外不该炸穿整次回测 —— 那样看不出是哪只票、哪个端点出的问题。"""
    ld = VibeLoader(out_dir=tmp_path)
    def boom(c, s, e): raise ValueError("数组长度不齐")
    monkeypatch.setattr(ld, "_fetch_one", boom)
    out = ld.fetch(["600519.SH", "AAPL"], "2024-01-01", "2024-02-01")
    assert out == {} and set(ld.failures) == {"600519.SH", "AAPL"}
    assert "数组长度不齐" in ld.failures["600519.SH"]
