from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .history_preflight import INDEX_NAMES, read_index_history, read_market_core_rows, scan_history_gaps

TARGET_SW = {"通信设备": "801102", "计算机设备": "801101", "元件": "801083", "半导体": "801081"}
CN_TZ = ZoneInfo("Asia/Shanghai")
QUALITY_MODULE_LABELS = {
    "market": "市场核心母表",
    "indices": "监控页三项指数",
    "sw_industry": "申万行业母表",
    "sw_crowding": "四行业拥挤度母表",
    "innovation": "创新药母表",
    "hot_stocks": "百亿成交母表",
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value):
    number = _num(value)
    return None if number is None else int(round(number))


def _prev_weekday(value: str) -> str:
    current = datetime.strptime(value, "%Y-%m-%d").date()
    while True:
        current = current.fromordinal(current.toordinal() - 1)
        if current.weekday() < 5:
            return current.isoformat()


def _latest_date(rows: list[dict[str, object]], key: str = "date") -> str | None:
    dates = [str(row.get(key) or "")[:10] for row in rows if str(row.get(key) or "")[:10]]
    return max(dates, default=None)


def _filter_rows(rows: list[dict[str, object]], cutoff_date: str | None, key: str = "date") -> list[dict[str, object]]:
    if not cutoff_date:
        return []
    return [row for row in rows if str(row.get(key) or "")[:10] <= cutoff_date]


def _has_row_for_date(rows: list[dict[str, object]], target_date: str, key: str = "date") -> bool:
    return any(str(row.get(key) or "")[:10] == target_date for row in rows)


def _recent_gap_entries(gaps: list[object], cutoff_date: str) -> list[object]:
    recent: list[object] = []
    for item in gaps:
        if isinstance(item, dict):
            item_date = str(item.get("date") or "")[:10]
            if item_date and item_date >= cutoff_date:
                recent.append(item)
        else:
            item_date = str(item)[:10]
            if item_date and item_date >= cutoff_date:
                recent.append(item)
    return recent


def _check_status(ok: bool, warn: bool = False) -> str:
    if ok:
        return "PASS"
    return "WARN" if warn else "FAIL"


def _module_health_rows(module_latest_dates: dict[str, str | None], benchmark_date: str | None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    order = ("market", "indices", "sw_industry", "sw_crowding", "innovation", "hot_stocks")
    for key in order:
        latest = module_latest_dates.get(key)
        if not latest:
            status = "FAIL"
            detail = "母表缺少有效数据"
        elif benchmark_date and latest < benchmark_date:
            status = "WARN"
            detail = f"晚于页面基准日 {benchmark_date} 的数据尚未补齐"
        else:
            status = "PASS"
            detail = "母表已就绪"
        rows.append({
            "key": key,
            "label": QUALITY_MODULE_LABELS.get(key, key),
            "latest": latest,
            "status": status,
            "detail": detail,
        })
    return rows


def _unresolved_message(module: str, detail: object, benchmark_date: str | None = None) -> str:
    if module == "indices_history":
        dates = sorted({
            str(item.get("date") or "")[:10]
            for item in (detail or [])
            if isinstance(item, dict) and str(item.get("date") or "")[:10]
        })
        return f"监控页指数历史仍有缺口，涉及日期：{', '.join(dates) if dates else '待核对'}。"
    if module == "market_denominator":
        dates = [str(item)[:10] for item in (detail or []) if str(item)[:10]]
        return f"全A成交额分母仍缺日期：{', '.join(dates) if dates else '待核对'}，会影响占全A类指标。"
    if module == "hot_stocks_latest" and isinstance(detail, dict):
        expected = detail.get("expected")
        actual = detail.get("actual")
        return f"百亿成交母表当日明细数量不一致：应为 {expected} 只，当前 {actual} 只。"
    if module == "canonical_validation":
        return "离线审计还没有完全通过，当前页面可以继续直读母表，但底层体检结果还不完整。"
    if module == "publication_gate":
        return "当前还有发布门禁未通过，建议先补齐母表后再把这版当成稳定产物。"
    if module.endswith("_latest") and isinstance(detail, dict):
        latest = detail.get("latest")
        report_date = detail.get("report_date") or benchmark_date
        return f"{QUALITY_MODULE_LABELS.get(module.replace('_latest', ''), module)} 最新只到 {latest}，落后于页面基准日 {report_date}。"
    return f"{QUALITY_MODULE_LABELS.get(module, module)} 仍需继续核对。"


def _build_quality_summary(
    report_date: str,
    module_latest_dates: dict[str, str | None],
    latest_hot: list[dict[str, object]],
    expected_hot: int,
    hot_latest_date: str | None,
    indices_history: list[dict[str, object]],
    sw_industry: list[dict[str, object]],
    sw_crowding: list[dict[str, object]],
    innovation: list[dict[str, object]],
    gaps: dict[str, object],
    canonical_validation: dict[str, object],
) -> dict[str, object]:
    mother_tables = _module_health_rows(module_latest_dates, report_date)

    latest_indices = [row for row in indices_history if str(row.get("date") or "") == report_date]
    indices_ok = len([row for row in latest_indices if row.get("name") in INDEX_NAMES and row.get("return") is not None and row.get("amount_100m") is not None]) == len(INDEX_NAMES)
    crowding_row = next((row for row in sw_crowding if str(row.get("date") or "") == report_date), None)
    crowding_targets = (crowding_row or {}).get("targets") or {}
    crowding_ok = len(crowding_targets) == len(TARGET_SW) and all(
        crowding_targets.get(name, {}).get("amount_100m") is not None
        and crowding_targets.get(name, {}).get("amount_share_of_a") is not None
        and crowding_targets.get(name, {}).get("turnover") is not None
        for name in TARGET_SW
    )
    innovation_row = next((row for row in innovation if str(row.get("date") or "") == report_date), None)
    innovation_ok = bool(
        innovation_row
        and innovation_row.get("amount_100m") is not None
        and innovation_row.get("amount_share_of_a") is not None
        and innovation_row.get("turnover") is not None
    )
    frontend_checks = [
        {
            "key": "market",
            "label": "市场总览正常显示",
            "status": _check_status(bool(report_date and module_latest_dates.get("market") == report_date)),
            "detail": "依赖 market_core 最新交易日",
        },
        {
            "key": "indices",
            "label": "监控页三项指数正常显示",
            "status": _check_status(indices_ok, warn=bool(latest_indices)),
            "detail": "监控页指数区块在页面基准日需同时具备涨跌幅和成交额",
        },
        {
            "key": "sw_industry",
            "label": "申万行业表正常显示",
            "status": _check_status(bool(sw_industry and module_latest_dates.get("sw_industry") == report_date), warn=bool(sw_industry)),
            "detail": "要求页面基准日存在行业快照",
        },
        {
            "key": "sw_crowding",
            "label": "四行业拥挤度图正常显示",
            "status": _check_status(crowding_ok, warn=bool(crowding_row)),
            "detail": "要求四条行业线在页面基准日同时具备成交额、占全A和换手率",
        },
        {
            "key": "innovation",
            "label": "创新药模块正常显示",
            "status": _check_status(innovation_ok, warn=bool(innovation_row)),
            "detail": "要求页面基准日存在成交额、占全A和换手率",
        },
        {
            "key": "hot_stocks",
            "label": "百亿成交榜正常显示",
            "status": _check_status(hot_latest_date == report_date and len(latest_hot) == expected_hot, warn=bool(latest_hot)),
            "detail": f"要求页面基准日百亿成交股数量与 market_core 记录一致（当前应为 {expected_hot} 只）",
        },
    ]

    index_gap_items = list(gaps.get("indices") or [])
    index_gap_dates = sorted({str(item.get("date") or "")[:10] for item in index_gap_items if isinstance(item, dict) and str(item.get("date") or "")[:10]})
    denominator_gap_dates = [str(item)[:10] for item in (gaps.get("market_denominator_dates") or []) if str(item)[:10]]
    canonical_status = str(canonical_validation.get("status") or "UNKNOWN")
    history_notes: list[str] = []
    if index_gap_items:
        history_notes.append(f"监控页三项指数最近窗口仍有 {len(index_gap_items)} 个字段缺口，涉及 {', '.join(index_gap_dates)}")
    if denominator_gap_dates:
        history_notes.append(f"创新药 / 四行业占全A分母仍缺 {', '.join(denominator_gap_dates)}")
    if canonical_status == "FAIL":
        history_notes.append("离线审计未通过，说明底层母表还有问题，当前版本不建议当成最终稳定版。")
    elif canonical_status == "WARN":
        history_notes.append("离线审计仍有提醒项，但当前页面依赖的母表和展示检查已通过。")
    elif canonical_status in {"UNKNOWN", "SKIPPED"}:
        history_notes.append("离线审计这次没有跑出结果；当前页面仍直接读取母表，但这里暂时不能给出完整底层体检。")
    history_status = "PASS" if not history_notes else ("FAIL" if canonical_status == "FAIL" else "WARN")
    if not history_notes:
        history_notes.append("未发现历史缺口")

    return {
        "report_date": report_date,
        "mother_tables": mother_tables,
        "frontend_checks": frontend_checks,
        "history_integrity": {
            "status": history_status,
            "index_gap_count": len(index_gap_items),
            "index_gap_dates": index_gap_dates,
            "market_denominator_gap_count": len(denominator_gap_dates),
            "market_denominator_gap_dates": denominator_gap_dates,
            "notes": history_notes,
        },
    }


def _resolve_publication(
    target_date: str,
    market_history: list[dict[str, object]],
    indices_history: list[dict[str, object]],
    sw_crowding: list[dict[str, object]],
    innovation: list[dict[str, object]],
    hot_latest_date: str | None,
    canonical_validation: dict[str, object],
    gaps: dict[str, object],
) -> dict[str, object]:
    today = datetime.now(CN_TZ).date().isoformat()
    latest_market = _latest_date(market_history)
    cutoff_date = target_date
    blocked_target_date = False
    reasons: list[dict[str, object]] = []
    market_dates = sorted(str(row.get("date") or "")[:10] for row in market_history if str(row.get("date") or "")[:10])

    def _market_publishable(candidate: str) -> bool:
        if not candidate:
            return False
        if not _has_row_for_date(market_history, candidate):
            return False
        if candidate in {str(item)[:10] for item in (gaps.get("market_denominator_dates") or [])}:
            return False
        if hot_latest_date and hot_latest_date < candidate:
            return False
        return True

    if target_date >= today:
        cutoff_date = _prev_weekday(target_date)
        warning_strings = [str(item) for item in (canonical_validation.get("warnings") or [])]

        if latest_market == target_date:
            blocked_target_date = True
            reasons.append({
                "module": "target_date_market_snapshot",
                "detail": f"target_date {target_date} still points at same-day market data",
            })
        if not _has_row_for_date(market_history, cutoff_date):
            blocked_target_date = True
            reasons.append({
                "module": "market_history",
                "detail": f"missing latest complete trading day {cutoff_date}",
            })
        recent_denominator_gaps = _recent_gap_entries(gaps.get("market_denominator_dates") or [], cutoff_date)
        if recent_denominator_gaps:
            blocked_target_date = True
            reasons.append({
                "module": "market_denominator",
                "detail": recent_denominator_gaps,
            })
        if hot_latest_date and hot_latest_date < cutoff_date:
            blocked_target_date = True
            reasons.append({
                "module": "hot_stocks_latest",
                "detail": {"latest": hot_latest_date, "expected_at_least": cutoff_date},
            })
        if any(item.startswith("sw_crowding_refresh_failed:") for item in warning_strings):
            reasons.append({
                "module": "sw_crowding_refresh",
                "detail": [item for item in warning_strings if item.startswith("sw_crowding_refresh_failed:")],
            })
        if any(item.startswith(f"sw_crowding_critical_rows_missing:{target_date}:") for item in warning_strings):
            reasons.append({
                "module": "sw_crowding_target_date",
                "detail": [item for item in warning_strings if item.startswith(f"sw_crowding_critical_rows_missing:{target_date}:")],
            })

    publishable_report_date = None
    for candidate in reversed(market_dates):
        if candidate > cutoff_date:
            continue
        if _market_publishable(candidate):
            publishable_report_date = candidate
            break
    if publishable_report_date is None:
        publishable_report_date = _latest_date([row for row in market_history if str(row.get("date") or "") <= cutoff_date])
    if publishable_report_date and target_date > publishable_report_date:
        blocked_target_date = True
    if publishable_report_date and publishable_report_date < cutoff_date:
        reasons.append({
            "module": "publishable_report_date",
            "detail": {"publishable": publishable_report_date, "expected": cutoff_date},
        })

    return {
        "target_date": target_date,
        "display_cutoff_date": cutoff_date,
        "blocked_target_date": blocked_target_date,
        "blocking_reasons": reasons,
        "publishable_report_date": publishable_report_date,
        "can_publish_target_date": publishable_report_date == target_date and not blocked_target_date,
    }


def _market_history(root: Path, target_date: str) -> list[dict[str, object]]:
    integer_fields = ("advance", "decline", "flat", "limit_up", "limit_down", "effective_stocks", "hot_count")
    numeric_fields = ("total_amount_100m", "hot_amount_100m", "hot_concentration", "market_breadth")
    rows = []
    for raw in read_market_core_rows(root):
        row_date = str(raw.get("date") or "")[:10]
        if not row_date or row_date > target_date:
            continue
        row = {"date": row_date}
        for field in integer_fields:
            row[field] = _int(raw.get(field))
        for field in numeric_fields:
            row[field] = _num(raw.get(field))
        rows.append(row)
    return sorted(rows, key=lambda row: row["date"])


def _indices_history(path: Path, target_date: str) -> list[dict[str, object]]:
    return [row for row in read_index_history(path) if str(row["date"]) <= target_date]


def _sw_industry(path: Path, target_date: str) -> list[dict[str, object]]:
    numeric = {"收盘价", "成交额", "日收益率", "20日年化波动率"}
    raw_rows = _read_csv(path)
    available_dates = sorted({
        str(raw.get("日期") or "")[:10]
        for raw in raw_rows
        if str(raw.get("日期") or "")[:10] and str(raw.get("日期") or "")[:10] <= target_date
    })
    if not available_dates:
        return []
    snapshot_date = available_dates[-1]
    rows = []
    for raw in raw_rows:
        if str(raw.get("日期") or "")[:10] != snapshot_date:
            continue
        row = {}
        for key, value in raw.items():
            row[key] = _num(value) if key in numeric else value
        rows.append(row)
    return rows


def _hot_rows(path: Path, target_date: str) -> list[dict[str, object]]:
    rows = []
    for raw in _read_csv(path):
        row_date = str(raw.get("date") or "")[:10]
        if not row_date or row_date > target_date:
            continue
        rows.append({
            "date": row_date,
            "rank": _int(raw.get("rank")),
            "stock_code": str(raw.get("stock_code") or "").zfill(6),
            "stock_name": str(raw.get("stock_name") or ""),
            "close": _num(raw.get("close")),
            "return": _num(raw.get("return")),
            "amount_100m": _num(raw.get("amount_100m")),
            "sw_level1": str(raw.get("sw_level1") or "未匹配"),
            "sw_level2": str(raw.get("sw_level2") or "未匹配"),
        })
    return sorted(
        rows,
        key=lambda row: (row["date"], row["rank"] if row["rank"] is not None else 9999),
    )


def build_hot_stock_matrix(
    rows: list[dict[str, object]],
    recent_dates: int = 10,
    named_max: int = 13,
    newest_first: bool = True,
) -> dict[str, object]:
    dates = sorted({str(row["date"]) for row in rows})[-recent_dates:]
    if newest_first:
        dates = list(reversed(dates))
    cumulative: dict[str, int] = {}
    counts = {row_date: {} for row_date in dates}
    for row in rows:
        industry = str(row.get("sw_level2") or "待申万映射")
        if industry in ("", "未匹配"):
            industry = "待申万映射"
        cumulative[industry] = cumulative.get(industry, 0) + 1
        row_date = str(row.get("date") or "")
        if row_date in counts:
            counts[row_date][industry] = counts[row_date].get(industry, 0) + 1
    named = sorted(cumulative, key=lambda value: (-cumulative[value], value))[:named_max]
    overflow = set(cumulative) - set(named)
    matrix_rows = []
    for industry in named:
        matrix_rows.append({
            "industry": industry,
            "counts": [counts[row_date].get(industry, 0) for row_date in dates],
            "history_total": cumulative[industry],
        })
    if overflow:
        matrix_rows.append({
            "industry": "其他行业汇总",
            "counts": [sum(counts[row_date].get(industry, 0) for industry in overflow) for row_date in dates],
            "history_total": sum(cumulative[industry] for industry in overflow),
        })
    return {"dates": dates, "rows": matrix_rows}


def _sw_crowding(
    path: Path,
    industry_history_path: Path,
    market_history: list[dict[str, object]],
    target_date: str,
) -> list[dict[str, object]]:
    denominator = {row["date"]: row.get("total_amount_100m") for row in market_history}
    direct_amounts: dict[tuple[str, str], float] = {}
    for raw in _read_csv(industry_history_path):
        row_date = str(raw.get("日期") or "")[:10]
        code = str(raw.get("指数代码") or "").replace(".0", "")
        amount = _num(raw.get("成交额"))
        if row_date and row_date <= target_date and code in TARGET_SW.values() and amount is not None:
            direct_amounts[(row_date, code)] = amount
    rows_by_date: dict[str, dict[str, object]] = {}
    for raw in _read_csv(path):
        row_date = str(raw.get("发布日期") or raw.get("日期") or "")[:10]
        code = str(raw.get("指数代码") or "").replace(".0", "")
        if not row_date or row_date > target_date or code not in TARGET_SW.values():
            continue
        label = next(name for name, target_code in TARGET_SW.items() if target_code == code)
        share_raw = _num(raw.get("成交额占比"))
        turnover_raw = _num(raw.get("换手率"))
        share = share_raw / 100 if share_raw is not None else None
        turnover = turnover_raw / 100 if turnover_raw is not None else None
        row = rows_by_date.setdefault(row_date, {"date": row_date, "targets": {}})
        # 新母表把东方财富板块成交额直接保存在同一行；旧申万行业表只作历史兼容。
        amount = _num(raw.get("成交额"))
        if amount is None:
            amount = direct_amounts.get((row_date, code))
        if amount is None and denominator.get(row_date) is not None and share is not None:
            amount = denominator[row_date] * share
        if share is None and amount is not None and denominator.get(row_date) not in (None, 0):
            share = amount / denominator[row_date]
        row["targets"][label] = {
            "code": code,
            "amount_100m": amount,
            "amount_share_of_a": share,
            "turnover": turnover,
        }
    out = []
    for row_date, row in sorted(rows_by_date.items()):
        targets = row["targets"]
        shares = [targets[name].get("amount_share_of_a") for name in TARGET_SW if name in targets]
        amounts = [targets[name].get("amount_100m") for name in TARGET_SW if name in targets]
        row["combined"] = {
            "amount_100m": sum(value for value in amounts if value is not None)
            if len(amounts) == 4 and all(value is not None for value in amounts)
            else None,
            "amount_share_of_a": sum(value for value in shares if value is not None)
            if len(shares) == 4 and all(value is not None for value in shares)
            else None,
        }
        out.append(row)
    return out


def _innovation(path: Path, market_history: list[dict[str, object]], target_date: str) -> list[dict[str, object]]:
    denominator = {row["date"]: row.get("total_amount_100m") for row in market_history}
    rows = []
    for raw in _read_csv(path):
        row_date = str(raw.get("日期") or raw.get("date") or "")[:10]
        if not row_date or row_date > target_date:
            continue
        raw_amount = _num(raw.get("成交额"))
        amount = raw_amount / 1e8 if raw_amount is not None else _num(raw.get("amount_100m"))
        denominator_value = denominator.get(row_date)
        share = amount / denominator_value if amount is not None and denominator_value not in (None, 0) else None
        rows.append({
            "date": row_date,
            "amount_100m": amount,
            "amount_share_of_a": share,
            "turnover": _num(raw.get("换手率")) if "换手率" in raw else _num(raw.get("turnover")),
            "return": _num(raw.get("日收益率")) if "日收益率" in raw else _num(raw.get("return")),
            "volume": _num(raw.get("成交量")) if "成交量" in raw else _num(raw.get("volume")),
            "source": str(raw.get("数据源") or raw.get("source") or ""),
        })
    return sorted(rows, key=lambda row: row["date"])


def build_report_data(target_date: str, root: Path = Path(".")) -> dict[str, object]:
    output_dir = root / "output" / target_date
    canonical_validation_path = output_dir / "canonical_validation.json"
    canonical_validation = (
        _read_json(canonical_validation_path)
        if canonical_validation_path.exists()
        else {"status": "SKIPPED", "failures": [], "warnings": [], "tables": {}}
    )

    raw_market_history = _market_history(root, target_date)
    raw_indices_history = _indices_history(root / "data/history/indices_history.csv", target_date)
    raw_hot_all = _hot_rows(root / "data/history/hot_stocks.csv", target_date)
    raw_hot_latest_date = max((row["date"] for row in raw_hot_all), default=None)
    raw_sw_industry = _sw_industry(root / "data/sw_industry_history.csv", target_date)
    raw_sw_crowding = _sw_crowding(
        root / "data/history/sw_analysis_daily_second.csv",
        root / "data/sw_industry_history.csv",
        raw_market_history,
        target_date,
    )
    raw_innovation = _innovation(root / "data/history/innovation_drug_eastmoney.csv", raw_market_history, target_date)
    raw_gaps = scan_history_gaps(root, target_date)
    # 展示层直接读取唯一母表，不再选择候选日期、发布包或回退包。
    # target_date 只是母表读取截止日。
    report_date = target_date
    market_history = raw_market_history
    indices_history = raw_indices_history
    sw_industry = raw_sw_industry
    hot_all = raw_hot_all
    hot_latest_date = max((row["date"] for row in hot_all), default=None)
    latest_hot = [row for row in hot_all if row["date"] == hot_latest_date]
    matrix = build_hot_stock_matrix(hot_all)
    sw_crowding = raw_sw_crowding
    innovation = raw_innovation
    gaps = raw_gaps

    latest_market = market_history[-1]["date"] if market_history else None
    sw_latest = max((str(row.get("日期") or "")[:10] for row in sw_industry if row.get("日期")), default=None)
    crowd_latest = _latest_date(sw_crowding)
    innovation_latest = _latest_date(innovation)
    module_latest_dates = {
        "market": latest_market,
        "indices": _latest_date(indices_history),
        "sw_industry": sw_latest,
        "sw_crowding": crowd_latest,
        "innovation": innovation_latest,
        "hot_stocks": hot_latest_date,
    }
    publication = {
        "target_date": target_date,
        "source": "canonical_mother_tables",
        "can_publish_target_date": latest_market == target_date,
        "blocking_reasons": [],
        "module_cutoff_dates": module_latest_dates,
    }

    unresolved: list[dict[str, object]] = []
    if gaps["indices"]:
        unresolved.append({"module": "indices_history", "level": "WARN", "detail": gaps["indices"], "message": _unresolved_message("indices_history", gaps["indices"], latest_market)})
    if gaps["market_denominator_dates"]:
        unresolved.append({"module": "market_denominator", "level": "WARN", "detail": gaps["market_denominator_dates"], "message": _unresolved_message("market_denominator", gaps["market_denominator_dates"], latest_market)})
    hot_market_row = next((row for row in market_history if row["date"] == hot_latest_date), {})
    expected_hot = int(hot_market_row.get("hot_count") or 0)
    if len(latest_hot) != expected_hot:
        unresolved.append({
            "module": "hot_stocks_latest",
            "level": "FAIL",
            "detail": {"expected": expected_hot, "actual": len(latest_hot)},
            "message": _unresolved_message("hot_stocks_latest", {"expected": expected_hot, "actual": len(latest_hot)}, latest_market),
        })
    if canonical_validation.get("status") == "FAIL":
        unresolved.append({
            "module": "canonical_validation",
            "level": "FAIL",
            "detail": canonical_validation.get("failures") or [],
            "message": _unresolved_message("canonical_validation", canonical_validation.get("failures") or [], latest_market),
        })
    elif canonical_validation.get("status") == "WARN":
        unresolved.append({
            "module": "canonical_validation",
            "level": "WARN",
            "detail": canonical_validation.get("warnings") or ["canonical validation status unknown"],
            "message": _unresolved_message("canonical_validation", canonical_validation.get("warnings") or [], latest_market),
        })
    if publication["blocking_reasons"]:
        unresolved.append({
            "module": "publication_gate",
            "level": "WARN",
            "detail": publication["blocking_reasons"],
            "message": _unresolved_message("publication_gate", publication["blocking_reasons"], latest_market),
        })

    for module_name, latest in module_latest_dates.items():
        if latest_market and latest and latest < latest_market:
            unresolved.append({
                "module": f"{module_name}_latest",
                "level": "WARN",
                "detail": {"latest": latest, "report_date": latest_market},
                "message": _unresolved_message(f"{module_name}_latest", {"latest": latest, "report_date": latest_market}, latest_market),
            })

    status = "FAIL" if any(item["level"] == "FAIL" for item in unresolved) else ("WARN" if unresolved else "PASS")
    quality_summary = _build_quality_summary(
        latest_market or report_date,
        module_latest_dates,
        latest_hot,
        expected_hot,
        hot_latest_date,
        indices_history,
        sw_industry,
        sw_crowding,
        innovation,
        gaps,
        canonical_validation,
    )

    return {
        "meta": {
            "report_name": "A股每日市场监控",
            "report_date": latest_market or report_date,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "latest_market_date": latest_market,
            "status": status,
            "canonical_validation_status": canonical_validation.get("status"),
        },
        "market_history": market_history,
        "indices_history": indices_history,
        "sw_industry_latest": sw_industry,
        "hot_stock_matrix": matrix,
        "hot_stocks_history": hot_all,
        "hot_stocks_latest": latest_hot,
        "sw_crowding_history": sw_crowding,
        "innovation_history": innovation,
        "quality": {
            "status": status,
            "summary": quality_summary,
            "unresolved": unresolved,
            "module_latest_dates": module_latest_dates,
            "history_gaps": gaps,
            "publication": publication,
            "canonical_validation": {
                "status": canonical_validation.get("status"),
                "failures": canonical_validation.get("failures") or [],
                "warnings": canonical_validation.get("warnings") or [],
                "tables": canonical_validation.get("tables") or {},
            },
        },
    }


def latest_market_date(root: Path) -> str | None:
    rows = read_market_core_rows(Path(root))
    return max((str(row.get("date") or "")[:10] for row in rows if row.get("date")), default=None)
