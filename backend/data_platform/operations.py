"""数据库运行审计与只读运维查询。"""
from __future__ import annotations

from datetime import date
from typing import Any

from data_platform.config import load_database_settings
from data_platform.domain_shadow import DOMAIN_SPECS


def platform_operations_summary(limit: int = 20) -> dict[str, Any]:
    """返回数据库镜像和最近运行证据，供内部运维页面读取。"""
    settings = load_database_settings()
    if not settings.url:
        return {"status": "disabled", "recent_events": [], "quality_checks": []}

    import psycopg  # noqa: PLC0415

    with psycopg.connect(settings.url, connect_timeout=3) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT max(trade_date), count(*) FROM market_daily_snapshots")
            market_date, market_rows = cur.fetchone()
            cur.execute("SELECT max(trade_date), count(*) FROM stock_pool_daily_cache")
            stock_date, stock_rows = cur.fetchone()
            cur.execute("SELECT max(trade_date), count(*) FROM watchlist_index_daily_cache")
            index_date, index_rows = cur.fetchone()
            cur.execute(
                "SELECT (SELECT count(*) FROM portfolio_positions), "
                "(SELECT count(*) FROM portfolio_closed_positions), "
                "(SELECT count(*) FROM research_reports), "
                "(SELECT count(*) FROM research_notes)"
            )
            positions, closed_positions, reports, notes = cur.fetchone()
            domain_mirrors: dict[str, dict[str, Any]] = {}
            for spec in DOMAIN_SPECS:
                cur.execute(f"SELECT max(trade_date), count(*) FROM {spec.table}")
                latest_date, row_count = cur.fetchone()
                domain_mirrors[spec.name] = {
                    "latest_date": latest_date.isoformat() if latest_date else None,
                    "rows": row_count,
                }
            cur.execute(
                "SELECT pipeline, target_date, 'shadow_import', status, "
                "COALESCE(completed_at, started_at), source_summary "
                "FROM ingestion_runs ORDER BY started_at DESC LIMIT %s",
                (limit,),
            )
            events = [_event_row(row) for row in cur.fetchall()]
            cur.execute(
                "SELECT domain, check_name, status, observed_at, detail "
                "FROM data_quality_checks ORDER BY observed_at DESC LIMIT %s",
                (limit,),
            )
            checks = [_check_row(row) for row in cur.fetchall()]
    return {
        "status": "ready",
        "mirror": {
            "market_latest_date": market_date.isoformat() if market_date else None,
            "market_rows": market_rows,
            "stock_latest_date": stock_date.isoformat() if stock_date else None,
            "stock_rows": stock_rows,
            "index_latest_date": index_date.isoformat() if index_date else None,
            "index_rows": index_rows,
            "domains": domain_mirrors,
        },
        "recent_events": events,
        "quality_checks": checks,
        "workspace": {
            "positions": positions,
            "closed_positions": closed_positions,
            "reports": reports,
            "notes": notes,
        },
    }


def _event_row(row: tuple[Any, ...]) -> dict[str, Any]:
    pipeline, target_date, stage, status, occurred_at, detail = row
    return {
        "pipeline": pipeline,
        "target_date": target_date.isoformat() if isinstance(target_date, date) else str(target_date),
        "stage": stage,
        "status": status,
        "occurred_at": occurred_at.isoformat(),
        "detail": detail,
    }


def _check_row(row: tuple[Any, ...]) -> dict[str, Any]:
    domain, check_name, status, observed_at, detail = row
    return {
        "domain": domain,
        "check_name": check_name,
        "status": status,
        "observed_at": observed_at.isoformat(),
        "detail": detail,
    }
