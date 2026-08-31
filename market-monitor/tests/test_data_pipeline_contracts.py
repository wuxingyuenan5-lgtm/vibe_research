from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from market_monitor.collectors import update_limit_pool_history, upsert_innovation_direct_quote
from market_monitor.pipeline import _normalize_sw_targets
from market_monitor.production import _require_close_ready
from market_monitor.sector_eastmoney import (
    BOARD_DEFINITIONS,
    CURRENT_SOURCE,
    SOURCE,
    build_analysis,
    refresh_eastmoney_sector_mother_table,
    upsert_eastmoney_sector_current,
)
from update_sw_industry_fast import calculate_metrics, require_current_close_window
from build_report_data import _sw_crowding
from run_daily import _restore_mother_tables, _snapshot_mother_tables, refresh_sources


class DataPipelineContractTests(unittest.TestCase):
    @staticmethod
    def _eastmoney_rows():
        rows = []
        for date in ("2026-08-24", "2026-08-25"):
            for code, (name, board) in BOARD_DEFINITIONS.items():
                rows.append({
                    "指数代码": code, "指数名称": name, "东方财富板块代码": board,
                    "发布日期": date, "收盘指数": 1000.0, "成交量": 10.0,
                    "成交额": 1000.0, "涨跌幅": 1.0, "换手率": 5.0,
                })
        return pd.DataFrame(rows)

    def test_eastmoney_rebuild_replaces_full_four_sector_history(self):
        raw = self._eastmoney_rows()

        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "history").mkdir(parents=True)
            pd.DataFrame([
                {"date": "2026-08-24", "total_amount_100m": 20_000.0},
                {"date": "2026-08-25", "total_amount_100m": 25_000.0},
            ]).to_csv(data_dir / "history/market_core.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame([{
                "指数代码": code, "指数名称": name, "发布日期": "2026-08-24",
                "换手率": 99.0, "成交额占比": 99.0, "数据源": "旧申万口径",
            } for code, (name, _) in BOARD_DEFINITIONS.items()]).to_csv(
                data_dir / "history/sw_analysis_daily_second.csv", index=False, encoding="utf-8-sig"
            )
            with patch(
                "market_monitor.sector_eastmoney.fetch_eastmoney_sector_history",
                return_value=raw,
            ):
                refresh_eastmoney_sector_mother_table("2026-08-25", data_dir)

            analysis = pd.read_csv(
                data_dir / "history/sw_analysis_daily_second.csv", encoding="utf-8-sig"
            )
            self.assertEqual(len(analysis[analysis["发布日期"] == "2026-08-24"]), 4)
            self.assertEqual(len(analysis[analysis["发布日期"] == "2026-08-25"]), 4)
            self.assertEqual(set(analysis["数据源"]), {SOURCE})
            self.assertAlmostEqual(float(analysis.iloc[0]["换手率"]), 5.0)

    def test_eastmoney_build_uses_direct_amount_turnover_and_market_denominator(self):
        result = build_analysis(
            self._eastmoney_rows(),
            pd.DataFrame([
                {"date": "2026-08-24", "total_amount_100m": 20_000.0},
                {"date": "2026-08-25", "total_amount_100m": 25_000.0},
            ]),
        )

        communication = result[result["指数代码"] == "801102"].iloc[0]
        self.assertAlmostEqual(float(communication["成交额"]), 1000.0)
        self.assertAlmostEqual(float(communication["成交额占比"]), 5.0)
        self.assertAlmostEqual(float(communication["换手率"]), 5.0)
        self.assertEqual(communication["数据源"], SOURCE)

    def test_eastmoney_daily_upsert_replaces_only_target_date(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "history").mkdir(parents=True)
            pd.DataFrame([{
                "指数代码": code,
                "指数名称": name,
                "发布日期": "2026-08-24",
                "成交额": 1.0,
                "换手率": 1.0,
                "成交额占比": 1.0,
                "数据源": "历史保留行",
            } for code, (name, _) in BOARD_DEFINITIONS.items()]).to_csv(
                data_dir / "history/sw_analysis_daily_second.csv",
                index=False,
                encoding="utf-8-sig",
            )
            preserved_line = (data_dir / "history/sw_analysis_daily_second.csv").read_text(
                encoding="utf-8-sig"
            ).splitlines()[1]
            quotes = [{
                "logical_code": code,
                "date": "2026-08-25",
                "close": 1000.0,
                "volume": 10.0,
                "amount_100m": 500.0,
                "return_pct": 2.0,
                "turnover_pct": 4.0,
            } for code in BOARD_DEFINITIONS]
            result = upsert_eastmoney_sector_current(
                "2026-08-25", data_dir, quotes, market_amount_100m=20_000.0
            )

            previous = result[result["发布日期"] == "2026-08-24"]
            current = result[result["发布日期"] == "2026-08-25"]
            self.assertEqual(len(previous), 4)
            self.assertEqual(len(current), 4)
            self.assertEqual(set(current["数据源"]), {CURRENT_SOURCE})
            self.assertTrue((current["成交额占比"].astype(float) == 2.5).all())
            self.assertTrue((current["换手率"].astype(float) == 4.0).all())
            self.assertIn(
                preserved_line,
                (data_dir / "history/sw_analysis_daily_second.csv").read_text(encoding="utf-8-sig").splitlines(),
            )

    def test_failed_run_snapshot_restores_mother_table_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data/history/market_core.csv"
            path.parent.mkdir(parents=True)
            original = b"date,value\n2026-08-25,1\n"
            path.write_bytes(original)
            snapshot = _snapshot_mother_tables(root)
            path.write_bytes(b"partial-write")
            _restore_mother_tables(snapshot)
            self.assertEqual(path.read_bytes(), original)

    def test_refresh_sources_warns_instead_of_aborting_on_sw_refresh_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result = refresh_sources(
                root=Path(directory),
                target_date="2026-08-28",
                fast_industry_refresh_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("sw timeout")),
            )
        self.assertEqual(result["sw_industry"], "warn_stale_previous_snapshot")
        self.assertIn(
            "sw_industry_refresh_failed:2026-08-28:sw timeout",
            result["warnings"],
        )

    def test_sw_current_return_uses_api_previous_close_across_history_gap(self):
        frame = pd.DataFrame([
            {
                "date": pd.Timestamp("2026-08-21"),
                "index_code": "801102",
                "close": 9921.45,
                "daily_return": 0.0298,
            },
            {
                "date": pd.Timestamp("2026-08-25"),
                "index_code": "801102",
                "close": 9366.85,
                "daily_return": 9366.85 / 9404.81 - 1,
            },
        ])

        result = calculate_metrics(frame)

        actual = result.loc[
            result["date"] == pd.Timestamp("2026-08-25"), "daily_return"
        ].iloc[0]
        self.assertAlmostEqual(actual, 9366.85 / 9404.81 - 1)

    def test_shenwan_current_snapshot_cannot_run_before_1520(self):
        partial = datetime(2026, 8, 25, 15, 19, tzinfo=ZoneInfo("Asia/Shanghai"))
        ready = datetime(2026, 8, 25, 15, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
        with self.assertRaises(RuntimeError):
            require_current_close_window("2026-08-25", partial)
        self.assertEqual(require_current_close_window("2026-08-25", ready).minute, 20)

    def test_four_sector_report_uses_amount_from_same_mother_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = root / "analysis.csv"
            industry = root / "industry.csv"
            pd.DataFrame([{
                "指数代码": code, "指数名称": name, "发布日期": "2026-08-07",
                "换手率": turnover, "成交额占比": share, "成交额": amount,
            } for name, code, turnover, share, amount in (
                ("通信设备", "801102", 9.44, 9.94, 2218.03927039),
                ("计算机设备", "801101", 5.31, 1.67, 372.32508411),
                ("元件", "801083", 13.61, 7.36, 1642.51484070),
                ("半导体", "801081", 8.21, 17.71, 3952.40804900),
            )]).to_csv(analysis, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=["日期", "指数代码", "成交额"]).to_csv(
                industry, index=False, encoding="utf-8-sig"
            )
            result = _sw_crowding(analysis, industry, [], "2026-08-25")
            self.assertAlmostEqual(result[0]["combined"]["amount_100m"], 8185.2872442)
            self.assertAlmostEqual(result[0]["combined"]["amount_share_of_a"], 0.3668)

    def test_close_quote_gate_rejects_partial_1520_value(self):
        partial = datetime(2026, 8, 25, 15, 19, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        ready = datetime(2026, 8, 25, 15, 20, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        with self.assertRaises(RuntimeError):
            _require_close_ready("2026-08-25", partial, "innovation")
        self.assertEqual(_require_close_ready("2026-08-25", ready, "innovation").minute, 20)

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
