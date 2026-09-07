from __future__ import annotations

from data_platform.market_read_model import comparable_payload


def test_comparison_ignores_only_generated_at():
    left = {"meta": {"report_date": "2026-09-07", "generated_at": "a"}, "rows": [1]}
    right = {"meta": {"report_date": "2026-09-07", "generated_at": "b"}, "rows": [1]}
    assert comparable_payload(left) == comparable_payload(right)
    right["rows"] = [2]
    assert comparable_payload(left) != comparable_payload(right)
