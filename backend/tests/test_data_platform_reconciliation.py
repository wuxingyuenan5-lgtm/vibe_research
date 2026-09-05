from __future__ import annotations

from data_platform.shadow_reconciliation import compare_payloads


def test_exact_shadow_data_passes():
    market = {"date": "2026-09-04", "advance": "1"}
    stocks = [{"instrument_id": "a", "code": "000001"}]
    result = compare_payloads(market, stocks, market.copy(), {"a": stocks[0].copy()}, "2026-09-04")
    assert result.status == "passed"
    assert result.stock_mismatches == 0


def test_missing_or_changed_shadow_data_is_warning():
    market = {"date": "2026-09-04", "advance": "1"}
    stocks = [{"instrument_id": "a", "code": "000001"}]
    result = compare_payloads(market, stocks, {"date": "2026-09-04", "advance": "2"}, {}, "2026-09-04")
    assert result.status == "warning"
    assert not result.market_match
    assert result.stock_mismatches == 1
