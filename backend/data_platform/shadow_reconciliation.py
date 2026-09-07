"""CSV 正式数据与 PostgreSQL 影子库的逐日对账。"""
from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass
from datetime import date

from data_platform.config import load_database_settings
from data_platform.domain_shadow import compare_domain_rows, load_domain_rows
from data_platform.shadow_import import load_formal_rows


@dataclass(frozen=True)
class ReconciliationResult:
    target_date: str
    status: str
    market_match: bool
    stock_expected: int
    stock_actual: int
    stock_mismatches: int
    domain_mismatches: int = 0


def compare_payloads(
    formal_market: dict[str, str],
    formal_stocks: list[dict[str, str]],
    shadow_market: dict | None,
    shadow_stocks: dict[str, dict],
    target_date: str,
) -> ReconciliationResult:
    """严格比较正式 CSV 与影子库 JSON，不尝试修补任意一侧。"""
    market_match = shadow_market == formal_market
    expected = {row.get("instrument_id") or row["code"]: row for row in formal_stocks}
    mismatches = sum(shadow_stocks.get(key) != row for key, row in expected.items())
    mismatches += len(set(shadow_stocks) - set(expected))
    status = "passed" if market_match and mismatches == 0 else "warning"
    return ReconciliationResult(
        target_date=target_date,
        status=status,
        market_match=market_match,
        stock_expected=len(expected),
        stock_actual=len(shadow_stocks),
        stock_mismatches=mismatches,
    )


def reconcile(target_date: str, record: bool = True) -> ReconciliationResult:
    formal_market, formal_stocks = load_formal_rows(target_date)
    formal_domains = load_domain_rows(target_date)
    settings = load_database_settings()
    if not settings.url:
        raise RuntimeError("未配置 VR_DATABASE_URL，不能执行影子库对账")

    import psycopg  # noqa: PLC0415

    with psycopg.connect(settings.url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM market_daily_snapshots WHERE trade_date = %s "
                "ORDER BY ingested_at DESC LIMIT 1",
                (target_date,),
            )
            market_row = cur.fetchone()
            cur.execute(
                "SELECT instrument_id, payload FROM stock_pool_daily_cache WHERE trade_date = %s",
                (target_date,),
            )
            stocks = dict(cur.fetchall())
            result = compare_payloads(formal_market, formal_stocks, market_row[0] if market_row else None, stocks, target_date)
            domain_detail = compare_domain_rows(cur, target_date, formal_domains)
            domain_mismatches = sum(item["mismatches"] for item in domain_detail.values())
            result = ReconciliationResult(**{**result.__dict__, "status": "passed" if result.status == "passed" and domain_mismatches == 0 else "warning", "domain_mismatches": domain_mismatches})
            if record:
                cur.execute(
                    "SELECT run_id FROM ingestion_runs WHERE target_date = %s AND status = 'passed' "
                    "ORDER BY completed_at DESC LIMIT 1",
                    (target_date,),
                )
                run = cur.fetchone()
                cur.execute(
                    "INSERT INTO data_quality_checks(check_id, run_id, domain, check_name, status, detail) "
                    "VALUES (%s, %s, 'shadow_database', 'csv_shadow_reconciliation', %s, %s)",
                    (
                        uuid.uuid4(),
                        run[0] if run else None,
                        result.status,
                        json.dumps({**result.__dict__, "domains": domain_detail}, ensure_ascii=False),
                    ),
                )
        conn.commit()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="CSV 正式数据与 PostgreSQL 影子库对账")
    parser.add_argument("--target-date", default=date.today().isoformat())
    parser.add_argument("--no-record", action="store_true", help="不写入 data_quality_checks")
    args = parser.parse_args()
    result = reconcile(args.target_date, record=not args.no_record)
    print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
