"""将正式 CSV 单向镜像到 PostgreSQL 影子库，不参与页面读取。"""
from __future__ import annotations

import argparse
import csv
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from data_platform.config import load_database_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
MARKET_CORE = PROJECT_ROOT / "market-monitor" / "data" / "history" / "market_core.csv"
STOCK_CACHE = PROJECT_ROOT / "data" / "stock-pool" / "stocks.csv"


@dataclass(frozen=True)
class ShadowImportSummary:
    target_date: str
    market_rows: int
    stock_rows: int
    stock_ok_rows: int


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_formal_rows(target_date: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    """读取正式数据，不补值、不推断、不改写 CSV。"""
    market_rows = [row for row in _read_csv(MARKET_CORE) if row.get("date") == target_date]
    if len(market_rows) != 1:
        raise ValueError(f"market_core 对 {target_date} 应恰有一行，实际 {len(market_rows)} 行")
    stocks = _read_csv(STOCK_CACHE)
    if not stocks:
        raise ValueError("stocks.csv 为空")
    missing_ids = [row.get("instrument_id") or row.get("code") for row in stocks if not (row.get("instrument_id") or row.get("code"))]
    if missing_ids:
        raise ValueError("stocks.csv 存在缺失标识的行")
    return market_rows[0], stocks


def build_summary(target_date: str) -> ShadowImportSummary:
    _, stocks = load_formal_rows(target_date)
    return ShadowImportSummary(
        target_date=target_date,
        market_rows=1,
        stock_rows=len(stocks),
        stock_ok_rows=sum(row.get("data_status") == "ok" for row in stocks),
    )


def import_to_shadow_database(target_date: str) -> ShadowImportSummary:
    """以自然键 upsert 正式 CSV 的当前日镜像，并留下完整运行审计。"""
    market, stocks = load_formal_rows(target_date)
    summary = build_summary(target_date)
    settings = load_database_settings()
    if not settings.url:
        raise RuntimeError("未配置 VR_DATABASE_URL，不能写入影子库")

    import psycopg  # noqa: PLC0415

    run_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)
    with psycopg.connect(settings.url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_runs(run_id, pipeline, target_date, started_at, status, source_summary) "
                "VALUES (%s, %s, %s, %s, 'running', %s)",
                (run_id, "csv_shadow_import", target_date, started_at, json.dumps({"market_core": str(MARKET_CORE), "stocks": str(STOCK_CACHE)})),
            )
            cur.execute(
                "INSERT INTO market_daily_snapshots "
                "(trade_date, definition_version, source_name, quality_status, payload) "
                "VALUES (%s, 'csv-v1', %s, 'ready', %s) "
                "ON CONFLICT (trade_date, definition_version, source_name) DO UPDATE "
                "SET ingested_at = now(), quality_status = EXCLUDED.quality_status, payload = EXCLUDED.payload",
                (target_date, market.get("snapshot_source") or "eastmoney", json.dumps(market, ensure_ascii=False)),
            )
            for row in stocks:
                instrument_id = row.get("instrument_id") or row["code"]
                cur.execute(
                    "INSERT INTO stock_pool_daily_cache "
                    "(trade_date, instrument_id, source_name, quality_status, payload) "
                    "VALUES (%s, %s, 'eastmoney', %s, %s) "
                    "ON CONFLICT (trade_date, instrument_id, source_name) DO UPDATE "
                    "SET ingested_at = now(), quality_status = EXCLUDED.quality_status, payload = EXCLUDED.payload",
                    (target_date, instrument_id, row.get("data_status") or "unknown", json.dumps(row, ensure_ascii=False)),
                )
            cur.execute(
                "UPDATE ingestion_runs SET completed_at = now(), status = 'passed', source_summary = source_summary || %s "
                "WHERE run_id = %s",
                (json.dumps({"market_rows": summary.market_rows, "stock_rows": summary.stock_rows, "stock_ok_rows": summary.stock_ok_rows}), run_id),
            )
        conn.commit()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="CSV 正式数据到 PostgreSQL 影子库的单向导入")
    parser.add_argument("--target-date", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true", help="仅做输入完整性检查，不连接数据库")
    args = parser.parse_args()
    summary = build_summary(args.target_date) if args.dry_run else import_to_shadow_database(args.target_date)
    print(json.dumps(summary.__dict__, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
