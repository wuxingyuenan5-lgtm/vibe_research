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
    def test_current_snapshot_rejects_future_or_same_day_preclose(self):
        partial = datetime(2026, 8, 25, 15, 19, tzinfo=ZoneInfo("Asia/Shanghai"))
        with self.assertRaises(RuntimeError):
            require_current_close_window("2026-08-25", partial)
        with self.assertRaises(RuntimeError):
            require_current_close_window("2026-08-26", datetime(2026, 8, 25, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
        current = require_current_close_window("2026-08-24", datetime(2026, 8, 25, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertEqual(current.strftime("%Y-%m-%d"), "2026-08-25")

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

    def test_save_focus_persists_into_pool_json(self):
        with tempfile.TemporaryDirectory() as directory:
            pool_path = Path(directory) / "pool.json"
            pool_path.write_text(json.dumps({
                "pool_name": "核心股票池",
                "version": "2026-08-31",
                "stocks": [
                    {"instrument_id": "600519", "code": "600519", "name": "贵州茅台", "industry": "白酒"},
                    {"instrument_id": "000858", "code": "000858", "name": "五粮液", "industry": "白酒"},
                ],
            }, ensure_ascii=False), encoding="utf-8")
            with patch.object(stock_pool, "POOL_PATH", pool_path):
                result = stock_pool.save_focus(["600519", "000858", "600519"], push=False)
                saved = json.loads(pool_path.read_text(encoding="utf-8"))
        self.assertTrue(result["ok"])
        self.assertEqual(saved["focus"]["codes"], ["600519", "000858"])
        self.assertIn("updated_at", saved["focus"])

    def test_load_pool_migrates_legacy_focus_and_strips_runtime_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            pool_path = Path(directory) / "pool.json"
            legacy_focus_path = Path(directory) / "focus.json"
            pool_path.write_text(json.dumps({
                "pool_name": "核心股票池",
                "version": "2026-08-31",
                "stocks": [
                    {
                        "instrument_id": "600519",
                        "code": "600519",
                        "exchange": "SSE",
                        "name": "贵州茅台",
                        "industry": "白酒",
                        "price": 1234.56,
                        "change": 0.01,
                        "data_status": "live",
                    }
                ],
            }, ensure_ascii=False), encoding="utf-8")
            legacy_focus_path.write_text(json.dumps({"codes": ["600519"]}, ensure_ascii=False), encoding="utf-8")
            with patch.object(stock_pool, "POOL_PATH", pool_path), patch.object(stock_pool, "LEGACY_FOCUS_PATH", legacy_focus_path):
                pool = stock_pool.load_pool()
                stock_pool.save_pool(pool)
                saved = json.loads(pool_path.read_text(encoding="utf-8"))
        self.assertEqual(pool["focus"]["codes"], ["600519"])
        self.assertEqual(saved["focus"]["codes"], ["600519"])
        self.assertEqual(saved["stocks"][0]["code"], "600519")
        self.assertNotIn("price", saved["stocks"][0])
        self.assertNotIn("change", saved["stocks"][0])
        self.assertNotIn("data_status", saved["stocks"][0])


if __name__ == "__main__":
    unittest.main()
