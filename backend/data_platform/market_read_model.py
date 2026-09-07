"""市场总览 PostgreSQL 只读快照。"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from data_platform.config import load_database_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOTHER_ROOT = PROJECT_ROOT / "market-monitor"


def build_formal_report(target_date: str) -> dict[str, Any]:
    from market_monitor.report_builder import build_report_data  # noqa: PLC0415

    return build_report_data(target_date, MOTHER_ROOT)


def upsert_market_report(cur: Any, target_date: str, payload: dict[str, Any]) -> None:
    cur.execute(
        "INSERT INTO market_report_snapshots "
        "(trade_date, definition_version, source_name, payload) "
        "VALUES (%s, 'report-v1', 'canonical-csv', %s) "
        "ON CONFLICT (trade_date, definition_version, source_name) DO UPDATE "
        "SET generated_at = now(), payload = EXCLUDED.payload",
        (target_date, json.dumps(payload, ensure_ascii=False)),
    )


def read_latest_market_report() -> tuple[str, dict[str, Any]]:
    settings = load_database_settings()
    if not settings.url:
        raise RuntimeError("市场总览已配置为数据库读取，但 VR_DATABASE_URL 未设置")
    import psycopg  # noqa: PLC0415

    with psycopg.connect(settings.url, connect_timeout=3) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trade_date, payload FROM market_report_snapshots "
                "ORDER BY trade_date DESC, generated_at DESC LIMIT 1"
            )
            row = cur.fetchone()
    if not row:
        raise RuntimeError("数据库尚无市场总览快照")
    return row[0].isoformat(), row[1]


def comparable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """移除每次构建都会变化、但不影响页面数据的生成时间。"""
    normalized = copy.deepcopy(payload)
    if isinstance(normalized.get("meta"), dict):
        normalized["meta"].pop("generated_at", None)
    return normalized

