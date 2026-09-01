#!/usr/bin/env python3
"""A 股交易日检查：以上证综指在目标日是否存在日线为准。"""
from __future__ import annotations

import argparse
import json
import urllib.request


SHANGHAI_COMPOSITE_SECID = "1.000001"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


def is_trading_day(target_date: str, opener=urllib.request.urlopen) -> bool:
    compact = target_date.replace("-", "")
    if len(compact) != 8 or not compact.isdigit():
        raise ValueError(f"invalid date: {target_date}")
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={SHANGHAI_COMPOSITE_SECID}&klt=101&fqt=0&beg={compact}&end={compact}"
        "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56"
    )
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with opener(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"交易日历查询失败: {exc}") from exc

    rows = (payload.get("data") or {}).get("klines") or []
    return any(str(row).startswith(target_date + ",") for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="检查目标日是否为 A 股交易日")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    if is_trading_day(args.date):
        print(f"TRADE_DAY {args.date}")
        return 0
    print(f"NON_TRADING_DAY {args.date}")
    return 10


if __name__ == "__main__":
    raise SystemExit(main())
