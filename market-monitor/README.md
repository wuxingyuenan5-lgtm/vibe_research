# market-monitor（A股每日市场监控生产链）

A股每日市场监控 HTML v1.1 生产链 —— Vibe-Research 项目的数据层子模块，从上游 `a_stock`（ops/html-monitor-v1 @ cb96ebb, PR #34）迁入并固定。

## 定位

- **项目内独立运行**：本目录自带完整生产链 + 历史种子数据，不依赖访问 `a_stock` 仓库即可产出每日看板；是 Vibe-Research 数据存储仓库（backup → vibe_research）的一部分。
- **四层分离**：`采集层 → Canonical 数据层 → report_data → 看板 UI`，Raw 数据不直接驱动前端。
- **固定版本**：生产流程锁定在源仓库 commit `cb96ebb`（HTML v1.1 + Canonical v2）。
- **CI 编排**：`.github/workflows/daily_market_monitor.yml`（项目根）默认在 `market-monitor/` 下执行全部生产步骤。

## 生产链

```text
run_history_preflight.py  (历史缺口预检/回填)
→ run_daily.py             (API 采集 → 按日期 upsert 唯一母表 → 验证)
→ validate_canonical_data.py (冗余复核)
→ build_report_data.py     (只读 Canonical → report_data.json)
→ render_market_monitor_html.py (HTML v1.1 单文件渲染)
→ validate_market_monitor_html.py (展示层校验 → html_validation.json)
```

网页端唯一数据入口：`data/published/latest_market_monitor.json`。GitHub Actions
在全部校验完成后一次性替换该文件；正式展示不拼接生产中的 CSV，也不现场生产。

## 模块说明

| 路径 | 职责 |
|---|---|
| `market_monitor/` | 母表存储/验证、采集器、HTML v1.1 渲染器、历史预检 |
| `run_daily.py` | 一键每日生产（采集 + 母表 upsert + 标准化 + 验证） |
| `build_report_data.py` | 生成展示层唯一业务数据合同 |
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
- 指数历史只能用历史 K 线补，不用当前报价倒填；
- Canonical Validator FAIL 时不允许生成 report_data.json 与 HTML。
- 母表永远只有 `data/` 下这一套滚动表；`output/YYYY-MM-DD/` 是日报审计产物，后端目录不保存母表镜像。

## 上游溯源

- 源仓库：https://github.com/wuxingyuenan5-lgtm/a_stock
- 分支：`ops/html-monitor-v1`（commit `cb96ebb`，PR #34）
- 本项目只迁入 HTML 生产链；Excel 渲染链、build_market_snapshot 等未迁入。
