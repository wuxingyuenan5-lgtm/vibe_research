from __future__ import annotations

import json
from pathlib import Path

from .report_builder import build_report_data

ROOT = Path(__file__).resolve().parent.parent / "data" / "market-monitor"
TARGET_DATE = "2026-08-14"  # 迁移验收样本（用户指定 8-14 fixture）


def _check(name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


def run() -> int:
    print(f"== 迁移验收：report_data 合同（fixture {TARGET_DATE}）==")
    report = build_report_data(TARGET_DATE, ROOT)
    checks: list[bool] = []

    # 1. meta 与质量
    ok = report["meta"]["report_date"] == TARGET_DATE
    checks.append(ok)
    _check("meta.report_date == 2026-08-14", ok)

    # 2. 只从 Canonical 构建：report_data 里必须存在各历史模块（不依赖 raw daily_payload）
    required = ("market_history", "indices_history", "sw_industry_latest",
                "hot_stock_matrix", "hot_stocks_latest", "sw_crowding_history",
                "innovation_history", "quality")
    ok = all(key in report for key in required)
    checks.append(ok)
    _check("report_data 包含全部合同模块", ok, ", ".join(k for k in required if k not in report))

    # 3. 百亿历史完整保留（hot_stocks_history 数量 >= 最新报告日数量）
    hot_all = report["hot_stocks_history"]
    hot_latest = report["hot_stocks_latest"]
    ok = len(hot_all) >= len(hot_latest) and len(hot_latest) > 0
    checks.append(ok)
    _check("百亿历史完整保留", ok, f"history={len(hot_all)} latest={len(hot_latest)}")

    # 4. 10 日窗口只属于展示层（matrix 是显示窗口；history 是完整记录）
    matrix_dates = report["hot_stock_matrix"]["dates"]
    ok = len(matrix_dates) <= 10 and len({r["date"] for r in hot_all}) >= len(matrix_dates)
    checks.append(ok)
    _check("10日窗口仅展示层", ok, f"matrix={len(matrix_dates)}d history_dates={len({r['date'] for r in hot_all})}d")

    # 5. 矩阵最新日期在左
    ok = matrix_dates and matrix_dates[0] >= matrix_dates[-1]
    checks.append(ok)
    _check("百亿矩阵最新日期在左", ok, f"{matrix_dates[0]} .. {matrix_dates[-1]}")

    # 6. 市场家数恒等式（advance+decline+flat ≈ effective_stocks）
    latest = report["market_history"][-1]
    a, d, f = latest.get("advance"), latest.get("decline"), latest.get("flat")
    eff = latest.get("effective_stocks")
    if None not in (a, d, f, eff):
        ok = abs((a + d + f) - eff) <= max(1, eff * 0.01)
    else:
        ok = False
    checks.append(ok)
    _check("市场家数恒等式", ok, f"{a}+{d}+{f} vs {eff}")

    # 7. 市场宽度公式（(advance-decline)/(advance+decline)；以源数据定义复核）
    breadth = latest.get("market_breadth")
    if breadth is not None and a is not None and d is not None and (a + d) != 0:
        expected = (a - d) / (a + d)
        ok = abs(expected - breadth) < 0.005
    else:
        ok = False
    checks.append(ok)
    _check("市场宽度公式", ok, f"({a}-{d})/({a}+{d})={expected:.4f} vs {breadth}" if (a is not None and d is not None and (a + d) != 0) else "无值")

    # 8. 创新药换手率来自供应商直接字段（存在 turnover 且非空日占比高）
    innov = report["innovation_history"]
    with_turnover = sum(1 for r in innov if r.get("turnover") is not None)
    ok = len(innov) > 0 and with_turnover >= len(innov) * 0.9
    checks.append(ok)
    _check("创新药换手率供应商直供", ok, f"{with_turnover}/{len(innov)} 天有值")

    # 9. 四行业拥挤度含全部目标，且不含「合计」展示依赖（前端禁用 combined，这里断言数据存在 targets）
    crowd = report["sw_crowding_history"]
    targets_ok = all(set(r["targets"].keys()) == {"通信设备", "计算机设备", "元件", "半导体"} for r in crowd if r.get("targets"))
    ok = len(crowd) > 0 and targets_ok
    checks.append(ok)
    _check("四行业拥挤度 targets 完整", ok, f"{len(crowd)} 天")

    # 10. 指数历史覆盖最近交易日
    idx_dates = sorted({r["date"] for r in report["indices_history"]})
    ok = bool(idx_dates) and idx_dates[-1] >= "2026-08-14"
    checks.append(ok)
    _check("指数历史覆盖 8-14", ok, f"latest={idx_dates[-1] if idx_dates else None}")

    total = sum(checks)
    print(f"\n结果：{total}/{len(checks)} 通过；report 质量状态 = {report['meta']['status']}")
    if report["quality"]["unresolved"]:
        print("WARN 项：")
        for u in report["quality"]["unresolved"]:
            print(f"  [{u['level']}] {u['module']}: {str(u['detail'])[:120]}")
    return 0 if total == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(run())
