# 上游来源 · A股每日市场监控（a股监控板）

本模块（`backend/market_monitor/` + 前端 `a股监控板` 页面）移植自独立上游仓库，用于追踪代码来源与版本。

| 项目 | 值 |
|---|---|
| upstream repo | [wuxingyuenan5-lgtm/a_stock](https://github.com/wuxingyuenan5-lgtm/a_stock) |
| upstream branch | `ops/html-monitor-v1` |
| integrated commit | `cb96ebbe1a0cb3d449231c8e40fba5b475d2c467` |
| source PR | [#34](https://github.com/wuxingyuenan5-lgtm/a_stock/pull/34) |
| 迁入日期 | 2026-08-15 |
| 上游实现版本 | 每日市场监控 HTML v1.1 + Canonical 数据母表 v2 |

## 迁移范围

### 迁入
- `build_report_data.py` → `backend/market_monitor/report_builder.py`（只读路径：Canonical CSV → report_data.json 合同）
- `market_monitor/history_preflight.py` → `backend/market_monitor/history_preflight.py`（只读：read_index_history / scan_history_gaps）
- 历史 Canonical 数据 → `backend/data/market-monitor/data/`
  - `history/market_core.csv`（含 verified backfill）
  - `history/indices_history.csv`
  - `history/hot_stocks.csv`
  - `history/sw_analysis_daily_second.csv`（四行业拥挤度）
  - `history/innovation_drug_eastmoney.csv`（创新药）
  - `sw_industry_latest.csv` / `sw_industry_history.csv`
- 报告产物 → `backend/data/market-monitor/output/2026-08-14/report_data.json`

### 未迁（有意排除）
- Excel 母表体系：`run_excel_renderer_v12/13/14/15.py`、excel_renderer_artifact.py、旧 Excel mother workbook 逻辑
- 网络采集/backfill：`market_monitor/collectors.py`、`pipeline.py`、`production.py`、`canonical_promotion.py` 的写入侧、`run_daily.py` 的实时采集（本次只迁移只读数据路径）
- 上游 run 脚本（`run_daily.py` / `run_history_preflight.py`）的 CLI 形态

## 后续若上游有修复
对照 `integrated commit` 做增量 diff，只把相关只读逻辑迁入，勿引入 Excel 旧链。

## 数据管道（本仓库内）
```
backend/data/market-monitor/data/history/*.csv（Canonical）
  → market_monitor/report_builder.build_report_data()
  → report_data.json（展示层唯一业务数据合同）
  → GET /api/market-monitor（FastAPI）
  → 前端「a股监控板」页面
```
Raw 数据不直接驱动前端；前端只消费 report_data.json。
