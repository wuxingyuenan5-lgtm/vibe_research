from __future__ import annotations

from pathlib import Path

import akshare as ak
import pandas as pd

from .collectors import _as_number
from .common import ensure_dir, retry


# 与 sw_cache.HISTORY_PATH 对齐：同日同目录下保存 canonical，便于 run_daily 同阶段刷新。
INNOVATION_HISTORY_PATH = Path("data/history/innovation_drug_eastmoney.csv")

# 与 sw_cache.SW_ANALYSIS_COLUMNS 等价的常量：本主题历史列名由 EM 决定，与 SW 母表无共享列。
INNOVATION_HISTORY_COLUMNS = [
    "日期",
    "收盘价",
    "成交量",
    "成交额",
    "日收益率",
    "换手率",
    "数据源",
    "20日成交量活跃度代理",
]


def _ths_concept_history(start_date: str, end_date: str) -> pd.DataFrame:
    """同花顺创新药概念历史（带日期，T+1 发布）。失败返回空表。"""
    try:
        frame = retry(
            lambda: ak.stock_board_concept_index_ths(
                symbol="创新药",
                start_date=start_date,
                end_date=end_date,
            ),
            attempts=2,
            delay=1.0,
        ).copy()
    except Exception:
        return pd.DataFrame()
    if frame is None or frame.empty or not {"日期", "收盘价", "成交额"}.issubset(frame.columns):
        return pd.DataFrame()
    frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
    for column in ("收盘价", "成交量", "成交额"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["日期", "收盘价", "成交额"]).sort_values("日期")


def backfill_innovation_live(
    target_date: str,
    history_path: Path = INNOVATION_HISTORY_PATH,
) -> pd.DataFrame | None:
    """T+1 Eastmoney BK1106 K 线缺失的交易日补齐（同 sw_crowding 的 backfill 模式）。

    数据源：`ak.stock_board_concept_index_ths("创新药")` 历史接口（带真实日期、T+1 发布，
    当前环境稳定可用；东财 push2his 被网络断时由它兜底）。实时接口（stock_board_concept_info_ths）
    无日期字段、周末/节假日会把上一交易日误标成当天，故**不使用**。

    写策略（受 `html_production_runtime.json.innovation_turnover_rule = supplier_direct_only` 约束）：
      - 日期：同花顺历史返回的真实交易日（只补 canonical 中缺失的日）
      - 成交额 / 收盘价：同花顺历史直接字段
      - 日收益率：同花顺历史"收盘价" pct_change 自算（该源口径，T+1 东财真值到达后覆盖）
      - 换手率 / 成交量 / 活跃度代理：留空（不伪填；成交量单位与东财 K 线不同，混入会污染
        20 日活跃度代理的 rolling 窗口）
      - 数据源标注"同花顺概念历史补齐"，下日 EM K 线拿到后由 update_innovation_history 覆盖

    与 backfill_sw_crowding_live 的区别：sw_crowding 用实时源自算 turnover；创新药主题在
    同花顺没有板块换手率字段，因此 turnover 保留缺口 → validator WARN 暴露，真值到达自动覆盖。

    写格式：与 innovation_drug_eastmoney.csv 完全一致（8 列），已存在的日期不会被改写。

    返回：新增行 DataFrame（None = 接口失败/历史为空/无缺失日）。
    """
    if not history_path.exists():
        return None
    raw = pd.read_csv(history_path, encoding="utf-8-sig")
    if raw.empty:
        return None

    raw["日期"] = pd.to_datetime(raw["日期"], errors="coerce")
    target_dt = pd.Timestamp(target_date)
    last_date = raw["日期"].max()
    existing_dates = set(raw["日期"].dt.strftime("%Y-%m-%d"))

    # 请求窗口：从已有历史最新日前推 7 天开始，覆盖到 target_date（周六/周日天然不含交易日）。
    start_dt = last_date - pd.Timedelta(days=7) if pd.notna(last_date) else target_dt - pd.Timedelta(days=30)
    hist = _ths_concept_history(
        start_dt.strftime("%Y%m%d"),
        target_date.replace("-", ""),
    )
    if hist.empty:
        return None

    hist = hist[hist["日期"] <= target_dt].copy()
    # 日收益率：先在完整 hist 上算（该源收盘价连续 pct_change），再过滤已有日期。
    # 顺序很关键：若先过滤 existing 再 pct_change，缺口首日会拿 canonical 前日（东财口径）收盘价
    # 做分母，而东财/同花顺板块收盘价口径不同，会算出失真收益率（如 -7.8% 假暴跌）。
    hist = hist.sort_values("日期")
    hist["日收益率"] = hist["收盘价"].pct_change(fill_method=None)
    hist = hist[~hist["日期"].dt.strftime("%Y-%m-%d").isin(existing_dates)]
    if hist.empty:
        return None

    new_rows = pd.DataFrame(
        {
            "日期": hist["日期"].dt.strftime("%Y-%m-%d"),
            "收盘价": hist["收盘价"],
            "成交量": None,
            "成交额": hist["成交额"],
            "日收益率": hist["日收益率"],
            "换手率": None,  # supplier_direct_only，下一 T+1 EM 真值覆盖
            "数据源": "同花顺概念历史补齐（东财BK1106 K线不可达，T+1真值覆盖）",
            "20日成交量活跃度代理": None,
        },
        columns=INNOVATION_HISTORY_COLUMNS,
    )

    combined = pd.concat([raw, new_rows], ignore_index=True, sort=False)
    combined["日期"] = pd.to_datetime(combined["日期"], errors="coerce")
    combined = (
        combined.dropna(subset=["日期"])
        .drop_duplicates("日期", keep="last")
        .sort_values("日期")
    )
    # 活跃度代理仅在有成交量的行计算（同 update_innovation_history 的口径）
    if combined["成交量"].notna().any():
        combined["20日成交量活跃度代理"] = combined["成交量"] / combined[
            "成交量"
        ].rolling(20, min_periods=1).mean()

    ensure_dir(history_path.parent)
    exported = combined.copy()
    exported["日期"] = exported["日期"].dt.strftime("%Y-%m-%d")
    exported.to_csv(
        history_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.10f",
    )
    return new_rows
