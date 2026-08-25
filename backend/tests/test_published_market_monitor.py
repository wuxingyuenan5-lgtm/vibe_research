from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from market_monitor.published import load_bundled_fallback, validate_bundle


def valid_bundle(date: str = "2026-08-21") -> dict:
    report = {
        "meta": {"report_date": date, "latest_market_date": date, "status": "PASS"},
        "market_history": [{"date": date}],
    }
    return {
        "status": "published",
        "data_date": date,
        "published_at": f"{date}T15:23:00+08:00",
        "validation": {"canonical": "PASS", "html": "PASS", "report": "PASS"},
        "report_sha256": hashlib.sha256(
            json.dumps(report, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "report": report,
    }


class PublishedMarketMonitorTests(unittest.TestCase):
    def test_validate_rejects_mixed_dates(self):
        bundle = valid_bundle()
        bundle["report"]["market_history"][-1]["date"] = "2026-08-20"
        with self.assertRaises(RuntimeError):
            validate_bundle(bundle)

    def test_validate_rejects_modified_report(self):
        bundle = valid_bundle()
        bundle["report"]["meta"]["status"] = "WARN"
        with self.assertRaises(RuntimeError):
            validate_bundle(bundle)

    def test_loads_bundled_last_good_without_producing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "market-monitor/data/published/latest_market_monitor.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(valid_bundle()), encoding="utf-8")
            loaded = load_bundled_fallback(root)
            self.assertEqual(loaded["data_date"], "2026-08-21")

    def test_loads_newer_bundled_copy_when_backend_copy_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            newer = root / "market-monitor/data/published/latest_market_monitor.json"
            older = root / "backend/data/market-monitor/data/published/latest_market_monitor.json"
            newer.parent.mkdir(parents=True)
            older.parent.mkdir(parents=True)
            newer.write_text(json.dumps(valid_bundle("2026-08-25")), encoding="utf-8")
            older.write_text(json.dumps(valid_bundle("2026-08-21")), encoding="utf-8")
            loaded = load_bundled_fallback(root)
            self.assertEqual(loaded["data_date"], "2026-08-25")


if __name__ == "__main__":
    unittest.main()
