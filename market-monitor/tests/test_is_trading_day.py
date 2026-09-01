from __future__ import annotations

import io
import json
import unittest

from is_trading_day import is_trading_day


class TradingDayTests(unittest.TestCase):
    def test_returns_true_when_target_index_bar_exists(self):
        def opener(_request, timeout):
            self.assertEqual(timeout, 12)
            return _Response({"data": {"klines": ["2026-09-01,3200,3210"]}})

        self.assertTrue(is_trading_day("2026-09-01", opener=opener))

    def test_returns_false_when_target_index_bar_is_absent(self):
        def opener(_request, timeout):
            return _Response({"data": {"klines": []}})

        self.assertFalse(is_trading_day("2026-10-01", opener=opener))


class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


if __name__ == "__main__":
    unittest.main()
