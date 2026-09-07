"""自选股日度行情读库；股票池定义始终由本地 pool.json 提供。"""
from __future__ import annotations

from typing import Any

from data_platform.config import load_database_settings


def read_latest_stock_cache() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    settings = load_database_settings()
    if not settings.url:
        raise RuntimeError("自选股已配置为数据库读取，但 VR_DATABASE_URL 未设置")
    import psycopg  # noqa: PLC0415

    with psycopg.connect(settings.url, connect_timeout=3) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT max(trade_date) FROM stock_pool_daily_cache")
            latest = cur.fetchone()[0]
            if not latest:
                raise RuntimeError("数据库尚无自选股日度缓存")
            cur.execute(
                "SELECT payload FROM stock_pool_daily_cache WHERE trade_date = %s ORDER BY instrument_id",
                (latest,),
            )
            stocks = [row[0] for row in cur.fetchall()]
            cur.execute(
                "SELECT payload FROM watchlist_index_daily_cache WHERE trade_date = %s ORDER BY index_code",
                (latest,),
            )
            indices = [row[0] for row in cur.fetchall()]
    if not indices:
        raise RuntimeError(f"数据库缺少 {latest.isoformat()} 自选行业指数缓存")
    return latest.isoformat(), stocks, indices

