from __future__ import annotations

from market_monitor.stock_pool import build_stock_pool_payload


def test_external_daily_rows_keep_local_definition(monkeypatch):
    monkeypatch.setattr("market_monitor.stock_pool.load_pool", lambda: {
        "pool_name": "核心股票池",
        "stocks": [{"instrument_id": "600519", "code": "600519", "name": "贵州茅台", "industry": "白酒", "exchange": "SSE"}],
        "focus": {"codes": ["600519"]},
        "research_baskets": [{"key": "consumer", "name": "消费", "codes": ["600519"]}],
    })
    daily = [{"instrument_id": "600519", "code": "600519", "price": "100", "change": "0.01", "data_status": "ok"}]
    payload = build_stock_pool_payload(daily, [{"code": "801120", "name": "食品饮料"}], "2026-09-07")
    assert payload["meta"]["report_date"] == "2026-09-07"
    assert payload["stocks"][0]["name"] == "贵州茅台"
    assert payload["stocks"][0]["research_baskets"] == ["消费"]
    assert payload["definitions"]["focus_codes"] == ["600519"]
