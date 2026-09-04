from __future__ import annotations

from data_platform.shadow_import import build_summary, load_formal_rows


def test_current_formal_market_and_stock_inputs_are_importable():
    market, stocks = load_formal_rows("2026-09-04")
    assert market["date"] == "2026-09-04"
    assert len(stocks) == 162
    assert all(row["data_status"] == "ok" for row in stocks)


def test_shadow_import_summary_has_current_counts():
    summary = build_summary("2026-09-04")
    assert summary.market_rows == 1
    assert summary.stock_rows == 162
    assert summary.stock_ok_rows == 162
