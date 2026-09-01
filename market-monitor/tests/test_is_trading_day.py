from __future__ import annotations

import unittest

from is_trading_day import is_trading_day


class TradingDayTests(unittest.TestCase):
    def test_returns_true_when_target_index_bar_exists(self):
        def requester(_url, **kwargs):
            self.assertEqual(kwargs["timeout"], (3, 6))
            return _Response({"data": {"f86": 1788248700}})

        self.assertTrue(is_trading_day("2026-09-01", requester=requester))

    def test_returns_false_when_target_index_bar_is_absent(self):
        def requester(_url, **_kwargs):
            return _Response({"data": {"f86": 1788248700}})

        self.assertFalse(is_trading_day("2026-10-01", requester=requester))


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


if __name__ == "__main__":
    unittest.main()
