from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from market_monitor.collectors import update_limit_pool_history, upsert_innovation_direct_quote
from market_monitor.pipeline import _normalize_sw_targets, _upsert_current_sw_amounts
from market_monitor.production import _require_close_ready


class DataPipelineContractTests(unittest.TestCase):
    def test_close_quote_gate_rejects_partial_1520_value(self):
        partial = datetime(2026, 8, 25, 15, 20, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        ready = datetime(2026, 8, 25, 15, 35, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        with self.assertRaises(RuntimeError):
            _require_close_ready("2026-08-25", partial, "innovation")
        self.assertEqual(_require_close_ready("2026-08-25", ready, "innovation").minute, 35)

    def test_current_sw_amount_fallback_does_not_fake_turnover(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            industry = root / "sw_industry_history.csv"
            crowding = root / "sw_analysis_daily_second.csv"
            pd.DataFrame([{
                "日期": "2026-08-25", "指数代码": code, "指数名称": name,
                "收盘价": 100, "成交额": amount, "日收益率": 0.01,
            } for name, code, amount in (
                ("通信设备", "801102", 1000), ("计算机设备", "801101", 200),
                ("元件", "801083", 800), ("半导体", "801081", 2000),
            )]).to_csv(industry, index=False, encoding="utf-8-sig")
            result = _upsert_current_sw_amounts(
                industry, crowding,
                {"通信设备": "801102", "计算机设备": "801101", "元件": "801083", "半导体": "801081"},
                "2026-08-25", 20_000,
            )
            current = result[result["发布日期"] == "2026-08-25"]
            self.assertEqual(len(current), 4)
            self.assertTrue(current["换手率"].isna().all())
            self.assertAlmostEqual(float(current["成交额占比"].sum()), 20.0)

    def test_sw_targets_use_official_percent_fields(self):
        frame = pd.DataFrame([{
            "指数代码": "801102",
            "指数名称": "通信设备",
            "发布日期": "2026-08-21",
            "换手率": 7.14,
            "成交额占比": 10.40,
        }])
        result = _normalize_sw_targets(
            frame, {"通信设备": "801102"}, "2026-08-21", 18_724.983679
        )["通信设备"]
        self.assertAlmostEqual(result["turnover"], 0.0714)
        self.assertAlmostEqual(result["amount_share_of_a"], 0.104)
        self.assertAlmostEqual(result["amount_100m"], 1_947.398302616)

    def test_limit_pool_history_replaces_same_day(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "limit_pool.csv"
            first = [{
                "date": "2026-08-21", "direction": "limit_up", "stock_code": "000001",
                "stock_name": "旧值", "close": 10, "return": 0.1, "amount_100m": 1,
                "turnover": 0.02, "industry": "银行", "source": "东方财富涨跌停池直接接口",
            }]
            second = [{**first[0], "stock_name": "新值", "amount_100m": 2}]
            update_limit_pool_history(path, "2026-08-21", first)
            result = update_limit_pool_history(path, "2026-08-21", second)
            self.assertEqual(len(result), 1)
            self.assertEqual(result.iloc[0]["stock_name"], "新值")
            self.assertEqual(float(result.iloc[0]["amount_100m"]), 2)

    def test_direct_innovation_quote_overwrites_estimate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "innovation.csv"
            pd.DataFrame([{
                "日期": "2026-08-21", "收盘价": 1, "成交量": None, "成交额": 1,
                "日收益率": 0, "换手率": 0.99, "数据源": "旧估算", "20日成交量活跃度代理": None,
            }]).to_csv(path, index=False, encoding="utf-8-sig")
            result = upsert_innovation_direct_quote(path, {
                "date": "2026-08-21", "close": 1490.28, "volume": 67_278_094,
                "amount_100m": 1145.0513175, "turnover": 0.0435, "return": -0.0396,
                "source": "东方财富创新药BK1106轻量板块报价（供应商直接字段）",
            })
            self.assertEqual(len(result), 1)
            self.assertAlmostEqual(float(result.iloc[0]["换手率"]), 0.0435)
            self.assertNotIn("估算", str(result.iloc[0]["数据源"]))


if __name__ == "__main__":
    unittest.main()
