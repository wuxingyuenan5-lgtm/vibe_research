from __future__ import annotations

import unittest

from is_trading_day import is_trading_day


class TradingDayTests(unittest.TestCase):
    def test_matches_target_quote_date(self) -> None:
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"data": {"f86": 1788249600}}

        self.assertTrue(is_trading_day("2026-09-01", requester=lambda *args, **kwargs: Response()))

    def test_other_quote_date_is_not_trading_day(self) -> None:
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"data": {"f86": 1790812800}}

        self.assertFalse(is_trading_day("2026-09-01", requester=lambda *args, **kwargs: Response()))
