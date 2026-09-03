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

### 唯一正式母表
- 历史 Canonical 数据只维护在 `market-monitor/data/`：
  - `history/market_core.csv`
  - `history/hot_stocks.csv`
  - `history/sw_analysis_daily_second.csv`（四行业拥挤度）
  - `history/innovation_drug_eastmoney.csv`（创新药）
  - `sw_industry_latest.csv` / `sw_industry_history.csv`
- 日期永远是母表内字段，不产生按日期拆分的母表。所有日度序列按主键 upsert。
- 四行业固定使用东方财富 `BK0448/BK0735/BK0459/BK1036`：普通日更读取 15:20 后轻量收盘报价并追加当天四行；成交额和换手率取直接字段，占全 A 用同日 `market_core` 计算。历史 K 线仅用于显式补数或整段迁移，不阻塞每日生产。
- `sw_industry_history.csv` 继续服务独立的申万行业模块，不再为四行业图提供成交额。
- `market-monitor/output/YYYY-MM-DD/` 只保存该日报告的审计产物，不是母表。
- `backend/data/market-monitor/` 下的旧复制不再作为读取、生产或同步来源。

### 未迁（有意排除）
- Excel 母表体系：`run_excel_renderer_v12/13/14/15.py`、excel_renderer_artifact.py、旧 Excel mother workbook 逻辑
- 网络采集/backfill：`market_monitor/collectors.py`、`pipeline.py`、`production.py`、`run_daily.py` 的实时采集与母表按日期 upsert
- 上游 `run_daily.py` 的 CLI 形态

## 后续若上游有修复
对照 `integrated commit` 做增量 diff；采集、母表和发布逻辑只在 `market-monitor/` 维护一份。

## 数据管道（本仓库内）
```
market-monitor/data/history/*.csv + market-monitor/data/sw_industry_history.csv（唯一 Canonical）
  → GET /api/market-monitor（FastAPI 直接读取母表）
  → 前端「a股监控板」页面
```
后端不读取 `backend/data/market-monitor/` 副本，不选择本地包、远端包或内存回退包。
