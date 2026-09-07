from __future__ import annotations

from data_platform.domain_shadow import load_domain_rows


def test_all_market_domains_have_current_formal_rows():
    rows = load_domain_rows("2026-09-07")
    assert len(rows["hot_stocks"]) == 10
    assert len(rows["industry_crowding"]) > 0
    assert len(rows["innovation_drug"]) == 1
    assert len(rows["industry_history"]) > 0


def test_missing_date_is_rejected_instead_of_filled():
    try:
        load_domain_rows("2099-01-01")
    except ValueError as exc:
        assert "缺少 2099-01-01 正式记录" in str(exc)
    else:
        raise AssertionError("缺失日期不得被影子导入器静默补值")
