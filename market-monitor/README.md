# market-monitor（A股每日市场监控生产链）

A股每日市场监控 HTML v1.1 生产链 —— Vibe-Research 项目的数据层子模块，从上游 `a_stock`（ops/html-monitor-v1 @ cb96ebb, PR #34）迁入并固定。

## 定位

- **项目内独立运行**：本目录自带完整生产链 + 历史种子数据，不依赖访问 `a_stock` 仓库即可产出每日看板；是 Vibe-Research 数据存储仓库（backup → vibe_research）的一部分。
- **三层结构**：`定时采集 → 唯一母表 → 后端/前端`。
- **固定版本**：生产流程锁定在源仓库 commit `cb96ebb`（HTML v1.1 + Canonical v2）。
- **CI 编排**：`.github/workflows/daily_market_monitor.yml`（项目根）默认在 `market-monitor/` 下执行全部生产步骤。

## 生产链

```text
run_daily.py（15:20 抓取并按日期 upsert）
→ data/history/*.csv + data/sw_industry_*.csv（唯一母表）
→ GET /api/market-monitor（直接读取母表）
→ 前端展示
```

`report_data.json` 与离线 HTML 仅作为审计产物，不参与网页运行。

## 模块说明

| 路径 | 职责 |
|---|---|
| `market_monitor/` | 母表存储/验证、采集器、HTML v1.1 渲染器、历史预检 |
| `run_daily.py` | 一键每日生产（采集 + 母表 upsert + 标准化 + 验证） |
| `build_report_data.py` | 可选离线审计报告，不参与网页运行 |
| `render_market_monitor_html.py` | 渲染单文件离线 HTML（内嵌 CSS/JS，无 CDN） |
| `validate_market_monitor_html.py` | HTML 校验（无外部依赖、报告日一致等） |
| `data/history/` | Canonical 正式历史母表（CSV） |
| `docs/DAILY_PIPELINE.md` | 生产链路 v3.1 详细说明 |

## 本地运行

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 每日一键生产（中国时区当天）
python run_daily.py --target-date YYYY-MM-DD

# 历史缺口预检
python run_history_preflight.py --target-date YYYY-MM-DD

# 只整段重建四行业母表（适合修复历史日期，不读取/写入 cache）
python rebuild_eastmoney_sectors.py --target-date YYYY-MM-DD
```

## 测试

```bash
# 用现有种子数据 dry-run 展示层（不采集、不改历史）
python validate_canonical_data.py
python build_report_data.py --target-date <最新历史日>
python render_market_monitor_html.py --target-date <最新历史日>
python validate_market_monitor_html.py --target-date <最新历史日>
```

## 数据口径要点

- 创新药成交额占比 = 同日创新药成交额 / 同日全部 A 股成交额；
- 创新药换手率只接受供应商直接板块字段；「20日成交量活跃度代理」永久禁止进入 Canonical/report_data/HTML；
- 通信设备、计算机设备、元件、半导体四条序列固定使用东方财富板块
  `BK0448/BK0735/BK0459/BK1036`；成交额、换手率取历史 K 线直接字段，成交额占全 A 用同日 `market_core` 计算；
- 四行业日更在 15:20 后读取东方财富轻量板块报价，按日期向同一母表追加四行；
- `rebuild_eastmoney_sectors.py` 只用于显式历史补数或整段口径迁移，不参与普通日更；
- 指数历史只能用历史 K 线补，不用当前报价倒填；
- Canonical Validator FAIL 时不允许生成 report_data.json 与 HTML。
- 母表永远只有 `data/` 下这一套滚动表；`output/YYYY-MM-DD/` 是日报审计产物，后端目录不保存母表镜像。

## 上游溯源

- 源仓库：https://github.com/wuxingyuenan5-lgtm/a_stock
- 分支：`ops/html-monitor-v1`（commit `cb96ebb`，PR #34）
- 本项目只迁入 HTML 生产链；Excel 渲染链、build_market_snapshot 等未迁入。
