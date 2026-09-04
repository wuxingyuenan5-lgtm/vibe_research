#!/usr/bin/env python3
"""A 股交易日检查：以上证综指在目标日是否存在日线为准。"""
from __future__ import annotations

import argparse
from datetime import datetime, date
from zoneinfo import ZoneInfo

import requests


SHANGHAI_COMPOSITE_SECID = "1.000001"
QUOTE_URL = "https://push2delay.eastmoney.com/api/qt/stock/get"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


def is_trading_day(target_date: str, requester=requests.get) -> bool:
    if len(target_date) != 10:
        raise ValueError(f"invalid date: {target_date}")
    try:
        response = requester(
            QUOTE_URL,
            params={"secid": SHANGHAI_COMPOSITE_SECID, "fields": "f86", "ut": "bd1d9ddb04089700cf9c27f6f7426281"},
            headers=HEADERS,
            timeout=(3, 6),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"交易日历查询失败: {exc}") from exc

    timestamp = (payload.get("data") or {}).get("f86")
    if not timestamp:
        raise RuntimeError("交易日历查询失败: 上证综指报价时间为空")
    quote_date = datetime.fromtimestamp(float(timestamp), ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    return quote_date == target_date


def main() -> int:
    parser = argparse.ArgumentParser(description="检查目标日是否为 A 股交易日")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    try:
        if is_trading_day(args.date):
            print(f"TRADE_DAY {args.date}")
            return 0
        print(f"NON_TRADING_DAY {args.date}")
        return 10
    except RuntimeError as exc:
        # 日历源临时超时不应成为工作日生产的单点故障；后续每条链会校验实际数据日期。
        weekday = date.fromisoformat(args.date).weekday()
        if weekday < 5:
            print(f"CALENDAR_UNAVAILABLE_CONTINUE {args.date}: {exc}")
            return 0
        print(f"NON_TRADING_DAY {args.date} (calendar unavailable, weekend)")
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
