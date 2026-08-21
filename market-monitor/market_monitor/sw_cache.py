from __future__ import annotations

from pathlib import Path

import akshare as ak
import pandas as pd

from .collectors import fetch_sw_analysis
from .common import ensure_dir
from .fast_market import fetch_a_share_spot_fast

CACHE_PATH = Path("data/cache/sw_analysis_daily_second.csv")
HISTORY_PATH = Path("data/history/sw_analysis_daily_second.csv")

# sw_crowding 表固定 14 列（akshare 申万日度分析，T+1/T+2 发布）
SW_ANALYSIS_COLUMNS = [
    "指数代码", "指数名称", "发布日期", "收盘指数", "成交量", "涨跌幅", "换手率",
    "市盈率", "市净率", "均价", "成交额占比", "流通市值", "平均流通市值", "股息率",
]


def load_sw_cache(target_date: str, path: Path = CACHE_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, encoding="utf-8-sig")
    date_col = next((c for c in ("发布日期", "日期", "date") if c in frame.columns), None)
    if date_col is not None:
        dates = pd.to_datetime(frame[date_col], errors="coerce")
        target = pd.Timestamp(target_date)
        frame = frame[(dates.isna()) | (dates <= target)].copy()
    return frame


def refresh_sw_cache(target_date: str, cache_path: Path = CACHE_PATH, history_path: Path = HISTORY_PATH) -> pd.DataFrame:
    # 拥挤度统一跟随生产流程母表（akshare 申万日度分析，T+1/T+2 发布）；
    # 不用实时源，避免与母表口径/更新流程不一致。
    frame = fetch_sw_analysis(target_date)
    if frame.empty:
        raise RuntimeError("申万日度分析接口未返回有效数据；保留旧缓存")
    ensure_dir(cache_path.parent)
    ensure_dir(history_path.parent)
    frame.to_csv(cache_path, index=False, encoding="utf-8-sig")

    if history_path.exists():
        old = pd.read_csv(history_path, encoding="utf-8-sig")
        combined = pd.concat([old, frame], ignore_index=True, sort=False)
        # 按主键 (代码, 日期) 去重而非整行去重：同一键新旧口径数值不同时
        # 整行比较不相等会被漏掉，导致 canonical 校验报 duplicate_key。
        # keep="last" 保证新抓取（frame）覆盖旧行。
        code_col = next((c for c in ("指数代码", "代码", "symbol") if c in combined.columns), None)
        date_col = next((c for c in ("发布日期", "日期", "date") if c in combined.columns), None)
        if code_col and date_col:
            # 用字符串拼接键去重：old 来自 CSV（str），frame 来自 akshare（datetime.date/int），
            # 混合类型主键比较判不等、去重会失效（duplicate_key:sw_crowding 根因）。
            # astype(str) 强制统一类型，保证同键一定判等；keep="last" 保留新抓取行。
            combined["__sw_key"] = (
                combined[code_col].astype(str) + "|" + combined[date_col].astype(str)
            )
            combined = combined.drop_duplicates(subset=["__sw_key"], keep="last").drop(columns="__sw_key")
            # 日期列统一为字符串写入，保持历史文件格式一致
            combined[date_col] = pd.to_datetime(combined[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
        else:
            combined = combined.drop_duplicates(keep="last")
    else:
        combined = frame.copy()
    date_col = next((c for c in ("发布日期", "日期", "date") if c in combined.columns), None)
    if date_col is not None:
        combined["__date"] = pd.to_datetime(combined[date_col], errors="coerce")
        combined = combined.sort_values("__date").drop(columns="__date")
    combined.to_csv(history_path, index=False, encoding="utf-8-sig")
    return frame


def _live_sw_snapshot() -> pd.DataFrame | None:
    """申万实时指数（一级+二级）→ 规整 DataFrame；失败返回 None。"""
    try:
        l1 = ak.index_realtime_sw(symbol="一级行业")
        l2 = ak.index_realtime_sw(symbol="二级行业")
    except Exception:
        return None
    live = pd.concat([l1, l2], ignore_index=True)
    if live is None or live.empty:
        return None
    live = live.rename(columns={
        "指数代码": "指数代码",
        "最新价": "close",
        "昨收盘": "prev_close",
        "成交额": "amount_million",   # 申万实时源成交额单位：百万元
        "成交量": "volume_million",   # 单位：百万股（手？）→ 与母表"亿"差 100 倍
    })
    live["指数代码"] = live["指数代码"].astype(str).str.extract(r"(\d{6})", expand=False)
    return live.dropna(subset=["指数代码"]).set_index("指数代码")


def backfill_sw_crowding_live(target_date: str, history_path: Path = HISTORY_PATH) -> pd.DataFrame | None:
    """用实时源把拥挤度表补齐到当日（T+1 母表源到之前先有当日估算值）。

    当日行 = 历史最新日骨架（估值/市值/股息率沿用昨日，保证 14 列全非空）
            + 实时自算（收盘指数/涨跌幅/成交量/均价/换手率/成交额占比）。
    口径：
      - 换手率 = 当日成交额 / 昨日流通市值（与母表一致：成交额=均价×成交量，已验证）
      - 成交额占比 = 当日成交额 / 全A总成交额 × 100（标准口径；母表该列 sum≠100，
        次日真实行覆盖时会产生 historical_value_changed WARN，可接受）
      - 成交量：实时源百万股 → 母表亿股（÷100）
    实时源拉取失败返回 None，调用方保持原样（T+1 源兜底，不阻断流程）。
    """
    if not history_path.exists():
        return None
    old = pd.read_csv(history_path, encoding="utf-8-sig")
    if old.empty:
        return None
    last_date = pd.to_datetime(old["发布日期"], errors="coerce").max().strftime("%Y-%m-%d")
    skeleton = old[old["发布日期"] == last_date].copy()
    if skeleton.empty:
        return None

    live = _live_sw_snapshot()
    if live is None:
        return None
    try:
        total_amount_yi = float(fetch_a_share_spot_fast()["amount_yuan"].sum()) / 1e8
    except Exception:
        total_amount_yi = None  # 全A总额拿不到 → 成交额占比沿用昨日，其余照常

    rows: list[dict] = []
    for _, base in skeleton.iterrows():
        row = base.to_dict()
        code = str(row.get("指数代码") or "").strip()
        lv = live.loc[code] if code in live.index else None
        if lv is not None:
            row["收盘指数"] = lv["close"]
            pct = None
            if lv["prev_close"]:
                pct = (float(lv["close"]) / float(lv["prev_close"]) - 1.0) * 100.0
            if pct is not None and abs(pct) < 50:  # 异常值保护（源偶尔返回错位昨收）
                row["涨跌幅"] = round(pct, 4)
            row["成交量"] = round(float(lv["volume_million"]) / 100.0, 4)  # 百万→亿
            avg_price = None
            if float(lv["volume_million"]) > 0:
                avg_price = float(lv["amount_million"]) / float(lv["volume_million"])
            if avg_price is not None:
                row["均价"] = round(avg_price, 4)
            mcap = _to_float(row.get("流通市值"))
            if mcap and mcap > 0:
                # 实时额(百万)→亿(÷100)；换手率 = 成交额(亿)/流通市值(亿) × 100%
                row["换手率"] = round(float(lv["amount_million"]) / 100.0 / mcap * 100.0, 4)
            if total_amount_yi and total_amount_yi > 0:
                row["成交额占比"] = round(float(lv["amount_million"]) / 100.0 / total_amount_yi * 100.0, 4)
        row["发布日期"] = target_date
        rows.append(row)

    frame = pd.DataFrame(rows, columns=SW_ANALYSIS_COLUMNS)
    combined = pd.concat([old, frame], ignore_index=True, sort=False)
    combined["__sw_key"] = (
        combined["指数代码"].astype(str) + "|" + combined["发布日期"].astype(str)
    )
    combined = combined.drop_duplicates(subset=["__sw_key"], keep="last").drop(columns="__sw_key")
    combined["发布日期"] = pd.to_datetime(combined["发布日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    combined.to_csv(history_path, index=False, encoding="utf-8-sig")
    return frame


def _to_float(value) -> float | None:
    try:
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None
