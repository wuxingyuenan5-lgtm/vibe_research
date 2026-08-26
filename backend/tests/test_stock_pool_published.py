from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from market_monitor import stock_pool
from market_monitor.daily_refresh import require_current_close_window
from datetime import datetime
from zoneinfo import ZoneInfo


def valid_bundle() -> dict:
    payload = {
        "meta": {"report_date": "2026-08-25"},
        "summary": {"tracked_count": 1, "pending_refresh": 0},
        "stocks": [{"instrument_id": "600519"}],
    }
    return {
        "status": "published",
        "data_date": "2026-08-25",
        "published_at": "2026-08-25T15:35:00+08:00",
        "payload": payload,
    }


class StockPoolPublishedTests(unittest.TestCase):
    def test_current_snapshot_cannot_be_backdated_or_run_preclose(self):
        partial = datetime(2026, 8, 25, 15, 19, tzinfo=ZoneInfo("Asia/Shanghai"))
        with self.assertRaises(RuntimeError):
            require_current_close_window("2026-08-25", partial)
        with self.assertRaises(RuntimeError):
            require_current_close_window("2026-08-24", datetime(2026, 8, 25, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai")))

    def test_valid_bundle(self):
        self.assertEqual(stock_pool.validate_published_bundle(valid_bundle())["data_date"], "2026-08-25")

    def test_rejects_date_mismatch(self):
        bundle = valid_bundle()
        bundle["payload"]["meta"]["report_date"] = "2026-08-24"
        with self.assertRaises(RuntimeError):
            stock_pool.validate_published_bundle(bundle)

    def test_rejects_pending_rows(self):
        bundle = valid_bundle()
        bundle["payload"]["summary"]["pending_refresh"] = 1
        with self.assertRaises(RuntimeError):
            stock_pool.validate_published_bundle(bundle)

    def test_loads_bundled_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(json.dumps(valid_bundle()), encoding="utf-8")
            with patch.object(stock_pool, "LATEST_BUNDLE_PATH", path):
                self.assertEqual(stock_pool.load_bundled_latest()["data_date"], "2026-08-25")


if __name__ == "__main__":
    unittest.main()
