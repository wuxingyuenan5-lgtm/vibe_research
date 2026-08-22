from __future__ import annotations

from pathlib import Path

import pandas as pd

from .collectors import fetch_sw_analysis
from .common import ensure_dir

CACHE_PATH = Path("data/cache/sw_analysis_daily_second.csv")
HISTORY_PATH = Path("data/history/sw_analysis_daily_second.csv")

# sw_crowding 表固定字段，数据由申万官网日度分析接口直接返回。
SW_ANALYSIS_COLUMNS = [
    "指数代码", "指数名称", "发布日期", "收盘指数", "成交量", "涨跌幅", "换手率",
    "市盈率", "市净率", "均价", "成交额占比", "流通市值", "平均流通市值", "股息率", "数据源",
]
CRITICAL_CODES = {"801102", "801101", "801083", "801081"}


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
    # 拥挤度统一跟随申万官网日度分析母表，只接受目标交易日官方字段。
    frame = fetch_sw_analysis(target_date)
    if frame.empty:
        raise RuntimeError("申万日度分析接口未返回有效数据；保留旧缓存")
    frame = frame.copy()
    frame["发布日期"] = pd.to_datetime(frame["发布日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    target_rows = frame[frame["发布日期"] == target_date].copy()
    target_rows["指数代码"] = target_rows["指数代码"].astype(str).str.replace(r"\.0$", "", regex=True)
    target_codes = set(target_rows["指数代码"])
    missing_critical = sorted(CRITICAL_CODES - target_codes)
    if len(target_rows) < 120 or missing_critical:
        raise RuntimeError(
            f"申万日度分析当日数据不完整: rows={len(target_rows)}, missing_critical={missing_critical}"
        )
    for column in ("换手率", "成交额占比"):
        values = pd.to_numeric(
            target_rows[target_rows["指数代码"].isin(CRITICAL_CODES)][column], errors="coerce"
        )
        if len(values) != 4 or values.isna().any():
            raise RuntimeError(f"申万四行业官方字段缺失: {column}")
    frame["数据源"] = "申万宏源 index_analysis_daily_sw 官方日度分析"
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
            # 用字符串拼接键去重：old 来自 CSV，frame 来自官网接口（可能含混合类型），
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
