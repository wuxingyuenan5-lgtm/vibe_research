#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_monitor.sector_eastmoney import refresh_eastmoney_sector_mother_table


def main() -> None:
    parser = argparse.ArgumentParser(description="整段重建东方财富四行业母表")
    parser.add_argument("--target-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    result = refresh_eastmoney_sector_mother_table(args.target_date, Path(args.data_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
