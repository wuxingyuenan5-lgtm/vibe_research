from __future__ import annotations

from pathlib import Path

import pandas as pd

from .collectors import fetch_sw_analysis
from .common import ensure_dir

CACHE_PATH = Path("data/cache/sw_analysis_daily_second.csv")
HISTORY_PATH = Path("data/history/sw_analysis_daily_second.csv")


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
