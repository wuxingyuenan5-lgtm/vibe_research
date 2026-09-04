from __future__ import annotations

import codecs
import csv
import io
from pathlib import Path

import pandas as pd

from .collectors import _fetch_em_klines
from .common import ensure_dir


SOURCE = "东方财富行业板块历史K线直连（整段统一口径）"
CURRENT_SOURCE = "东方财富行业板块轻量报价（每日15:05后母表直写）"
BOARD_DEFINITIONS = {
    "801102": ("通信设备", "BK0448"),
    "801101": ("计算机设备", "BK0735"),
    "801083": ("元件", "BK0459"),
    "801081": ("半导体", "BK1036"),
}
ANALYSIS_COLUMNS = [
    "指数代码", "指数名称", "东方财富板块代码", "发布日期", "收盘指数", "成交量", "成交额",
    "涨跌幅", "换手率", "市盈率", "市净率", "均价", "成交额占比", "流通市值",
    "平均流通市值", "股息率", "数据源",
]


def fetch_eastmoney_sector_history(start_date: str, target_date: str) -> pd.DataFrame:
    """Fetch the complete requested range for the four fixed Eastmoney boards."""
    records: list[dict[str, object]] = []
    beg = start_date.replace("-", "")
    end = target_date.replace("-", "")
    for logical_code, (name, board_code) in BOARD_DEFINITIONS.items():
        for values in _fetch_em_klines(f"90.{board_code}", beg, end, lmt=1000):
            records.append({
                "指数代码": logical_code,
                "指数名称": name,
                "东方财富板块代码": board_code,
                "发布日期": values[0],
                "收盘指数": float(values[2]),
                # Eastmoney f56 is volume in lots; 1e6 lots = 1e8 shares.
                "成交量": float(values[5]) / 1_000_000.0,
                "成交额": float(values[6]) / 100_000_000.0,
                "涨跌幅": float(values[8]),
                "换手率": float(values[10]),
            })
    frame = pd.DataFrame(records)
    if frame.empty:
        raise RuntimeError("Eastmoney four-sector history returned no rows")
    return frame.sort_values(["发布日期", "指数代码"]).reset_index(drop=True)


def _read_market_core(path: Path, target_date: str) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(f"market mother table does not exist: {path}")
    market = pd.read_csv(path, encoding="utf-8-sig")
    market["date"] = pd.to_datetime(market["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    market["total_amount_100m"] = pd.to_numeric(market["total_amount_100m"], errors="coerce")
    market = market[(market["date"] <= target_date) & (market["total_amount_100m"] > 0)].copy()
    market = market.drop_duplicates("date", keep="last").sort_values("date")
    if market.empty or market.iloc[-1]["date"] != target_date:
        latest = None if market.empty else market.iloc[-1]["date"]
        raise RuntimeError(f"market mother table is not ready for {target_date}: latest={latest}")
    return market[["date", "total_amount_100m"]]


def build_analysis(raw: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """Build the canonical chart rows and require identical full-date coverage."""
    required_raw = {
        "指数代码", "指数名称", "东方财富板块代码", "发布日期", "收盘指数", "成交量",
        "成交额", "涨跌幅", "换手率",
    }
    if not required_raw.issubset(raw.columns):
        raise RuntimeError(f"Eastmoney sector schema incomplete: {sorted(required_raw - set(raw.columns))}")
    market_dates = set(market["date"].astype(str))
    frame = raw[raw["发布日期"].astype(str).isin(market_dates)].copy()
    expected_codes = set(BOARD_DEFINITIONS)
    if set(frame["指数代码"].astype(str)) != expected_codes:
        raise RuntimeError("Eastmoney sector history is missing one or more fixed boards")
    for code in expected_codes:
        actual_dates = set(frame.loc[frame["指数代码"].astype(str) == code, "发布日期"].astype(str))
        if actual_dates != market_dates:
            missing = sorted(market_dates - actual_dates)
            extra = sorted(actual_dates - market_dates)
            raise RuntimeError(
                f"Eastmoney sector date coverage mismatch: code={code}, missing={missing[:10]}, extra={extra[:10]}"
            )
    frame = frame.merge(
        market.rename(columns={"date": "发布日期", "total_amount_100m": "全A成交额"}),
        on="发布日期",
        how="left",
        validate="many_to_one",
    )
    for column in ("成交额", "换手率", "收盘指数", "涨跌幅"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[["成交额", "换手率", "全A成交额"]].isna().any().any():
        raise RuntimeError("Eastmoney sector amount/turnover or all-A denominator is missing")
    frame["成交额占比"] = frame["成交额"] / frame["全A成交额"] * 100.0
    for column in ("市盈率", "市净率", "均价", "流通市值", "平均流通市值", "股息率"):
        frame[column] = pd.NA
    frame["数据源"] = SOURCE
    return frame[ANALYSIS_COLUMNS].sort_values(["发布日期", "指数代码"]).reset_index(drop=True)


def _atomic_write(frame: pd.DataFrame, path: Path) -> None:
    ensure_dir(path.parent)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig", float_format="%.10f")
    temporary.replace(path)


def upsert_eastmoney_sector_current(
    target_date: str,
    data_dir: Path,
    quotes: list[dict[str, object]],
    market_amount_100m: float,
) -> pd.DataFrame:
    """Append one validated close snapshot for the four fixed boards."""
    if market_amount_100m <= 0:
        raise RuntimeError("all-A amount denominator must be positive")
    by_code = {str(row.get("logical_code") or ""): row for row in quotes}
    if set(by_code) != set(BOARD_DEFINITIONS):
        raise RuntimeError(f"Eastmoney current sector coverage mismatch: {sorted(by_code)}")

    rows: list[dict[str, object]] = []
    for logical_code, (name, board_code) in BOARD_DEFINITIONS.items():
        quote = by_code[logical_code]
        if str(quote.get("date") or "") != target_date:
            raise RuntimeError(
                f"Eastmoney sector quote date mismatch: {logical_code}={quote.get('date')}"
            )
        required = ("close", "volume", "amount_100m", "return_pct", "turnover_pct")
        values = {field: pd.to_numeric(quote.get(field), errors="coerce") for field in required}
        if any(pd.isna(value) for value in values.values()):
            raise RuntimeError(f"Eastmoney sector quote fields incomplete: {logical_code}")
        rows.append({
            "指数代码": logical_code,
            "指数名称": name,
            "东方财富板块代码": board_code,
            "发布日期": target_date,
            "收盘指数": float(values["close"]),
            "成交量": float(values["volume"]),
            "成交额": float(values["amount_100m"]),
            "涨跌幅": float(values["return_pct"]),
            "换手率": float(values["turnover_pct"]),
            "市盈率": pd.NA,
            "市净率": pd.NA,
            "均价": pd.NA,
            "成交额占比": float(values["amount_100m"]) / market_amount_100m * 100.0,
            "流通市值": pd.NA,
            "平均流通市值": pd.NA,
            "股息率": pd.NA,
            "数据源": CURRENT_SOURCE,
        })

    history_path = Path(data_dir) / "history/sw_analysis_daily_second.csv"
    ensure_dir(history_path.parent)
    if history_path.exists():
        raw = history_path.read_bytes()
        newline = "\r\n" if b"\r\n" in raw else "\n"
        lines = raw.decode("utf-8-sig").splitlines()
        fieldnames = next(csv.reader([lines[0]])) if lines else list(ANALYSIS_COLUMNS)
        for column in ("东方财富板块代码", "成交额"):
            if column not in fieldnames:
                fieldnames.append(column)
        kept_lines: list[str] = []
        for line in lines[1:]:
            values = next(csv.reader([line]))
            record = dict(zip(fieldnames, values))
            code = str(record.get("指数代码") or "").removesuffix(".0")
            day = str(record.get("发布日期") or "")[:10]
            if day == target_date and code in BOARD_DEFINITIONS:
                continue
            kept_lines.append(line)
    else:
        newline = "\n"
        fieldnames = list(ANALYSIS_COLUMNS)
        kept_lines = []

    rendered_rows: list[str] = []
    for row in rows:
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore", lineterminator="")
        writer.writerow(row)
        rendered_rows.append(buffer.getvalue())
    output = newline.join([",".join(fieldnames), *kept_lines, *rendered_rows]) + newline
    temporary = history_path.with_suffix(history_path.suffix + ".tmp")
    temporary.write_bytes(codecs.BOM_UTF8 + output.encode("utf-8"))
    temporary.replace(history_path)
    return pd.read_csv(history_path, encoding="utf-8-sig")


def refresh_eastmoney_sector_mother_table(target_date: str, data_dir: Path) -> dict[str, object]:
    """Replace all four chart series across the full market calendar, atomically.

    Non-chart rows in the legacy analysis table are retained for compatibility, but every row for
    the four chart series is rebuilt from Eastmoney. No current snapshot or mixed-provider splice is
    allowed.
    """
    data_dir = Path(data_dir)
    history_path = data_dir / "history/sw_analysis_daily_second.csv"
    market = _read_market_core(data_dir / "history/market_core.csv", target_date)
    start_date = str(market.iloc[0]["date"])
    fresh = build_analysis(fetch_eastmoney_sector_history(start_date, target_date), market)

    existing = pd.read_csv(history_path, encoding="utf-8-sig") if history_path.exists() else pd.DataFrame()
    if not existing.empty and "指数代码" in existing.columns:
        codes = existing["指数代码"].astype(str).str.replace(r"\.0$", "", regex=True)
        existing = existing[~codes.isin(BOARD_DEFINITIONS)].copy()
    combined = pd.concat([existing, fresh], ignore_index=True, sort=False)
    combined["发布日期"] = pd.to_datetime(combined["发布日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    combined["指数代码"] = combined["指数代码"].astype(str).str.replace(r"\.0$", "", regex=True)
    combined = combined.drop_duplicates(["发布日期", "指数代码"], keep="last")
    combined = combined.sort_values(["发布日期", "指数代码"]).reset_index(drop=True)

    target_rows = fresh[fresh["发布日期"] == target_date]
    if len(target_rows) != len(BOARD_DEFINITIONS):
        raise RuntimeError(f"Eastmoney target-date sector rows incomplete: {len(target_rows)}/4")
    _atomic_write(combined, history_path)
    return {
        "provider": "eastmoney_fixed_industry_boards",
        "target_date": target_date,
        "history_start": start_date,
        "history_end": target_date,
        "rebuilt_rows": len(fresh),
        "board_codes": {name: board for _, (name, board) in BOARD_DEFINITIONS.items()},
    }
