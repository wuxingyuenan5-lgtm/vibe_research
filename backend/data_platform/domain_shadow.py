"""市场监控四张正式母表的透明 PostgreSQL 镜像。"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DomainSpec:
    name: str
    path: Path
    table: str
    date_field: str
    key_fields: tuple[str, ...]
    source_field: str | None = None
    default_source: str = "eastmoney"


DOMAIN_SPECS = (
    DomainSpec("hot_stocks", PROJECT_ROOT / "market-monitor/data/history/hot_stocks.csv", "hot_stock_daily", "date", ("stock_code",)),
    DomainSpec("industry_crowding", PROJECT_ROOT / "market-monitor/data/history/sw_analysis_daily_second.csv", "industry_crowding_daily", "发布日期", ("指数代码",), "数据源"),
    DomainSpec("innovation_drug", PROJECT_ROOT / "market-monitor/data/history/innovation_drug_eastmoney.csv", "innovation_drug_daily", "日期", (), "数据源"),
    DomainSpec("industry_history", PROJECT_ROOT / "market-monitor/data/sw_industry_history.csv", "industry_daily_snapshots", "日期", ("指数代码", "行业层级")),
)


def load_domain_rows(target_date: str) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for spec in DOMAIN_SPECS:
        with spec.path.open(encoding="utf-8-sig", newline="") as handle:
            rows = [row for row in csv.DictReader(handle) if row.get(spec.date_field) == target_date]
        if not rows:
            raise ValueError(f"{spec.path.name} 缺少 {target_date} 正式记录")
        result[spec.name] = rows
    return result


def upsert_domain_rows(cur: Any, target_date: str, rows_by_domain: dict[str, list[dict[str, str]]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for spec in DOMAIN_SPECS:
        rows = rows_by_domain[spec.name]
        for row in rows:
            source = row.get(spec.source_field or "") or spec.default_source
            values = [target_date, *(row[field] for field in spec.key_fields), "csv-v1", source, json.dumps(row, ensure_ascii=False)]
            key_columns = ["trade_date"]
            if spec.name == "hot_stocks":
                key_columns += ["stock_code"]
            elif spec.name == "industry_crowding":
                key_columns += ["industry_code"]
            elif spec.name == "industry_history":
                key_columns += ["industry_code", "industry_level"]
            columns = key_columns + ["definition_version", "source_name", "payload"]
            placeholders = ", ".join(["%s"] * len(columns))
            conflict = ", ".join(columns[:-1])
            cur.execute(
                f"INSERT INTO {spec.table} ({', '.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict}) DO UPDATE SET ingested_at = now(), payload = EXCLUDED.payload",
                values,
            )
        counts[spec.name] = len(rows)
    return counts


def compare_domain_rows(cur: Any, target_date: str, formal: dict[str, list[dict[str, str]]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for spec in DOMAIN_SPECS:
        cur.execute(f"SELECT payload FROM {spec.table} WHERE trade_date = %s", (target_date,))
        actual = [row[0] for row in cur.fetchall()]
        expected = formal[spec.name]
        unmatched = len(expected) + len(actual) - 2 * sum(1 for row in expected if row in actual)
        result[spec.name] = {"expected": len(expected), "actual": len(actual), "mismatches": unmatched}
    return result
