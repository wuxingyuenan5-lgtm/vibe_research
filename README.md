# Vibe-Research · 个人 AI 投研系统（A 股 / 美股 / 港股）

> 把 A 股 / 美股 / 港股 的行情、研报、估值、财务、公告、资金面、资讯集成到一块干净的看板，再留一个能接入我自己 AI 的接口。方向和结论，由我自己配置的模型决定。

[![License: TODO](https://img.shields.io/badge/License-TODO-lightgrey)](#license)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![English README](https://img.shields.io/badge/📖_English-README-1F6FEB?style=flat)](README_en.md)

<p align="center">
  <a href="#这是什么">这是什么</a> ·
  <a href="#核心特性">核心特性</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#项目结构">项目结构</a> ·
  <a href="#接入-ai">接入 AI</a> ·
  <a href="#license">License</a>
</p>

---

## 这是什么

Vibe-Research 是我自己在用的跨市场投研面板。**主推 A 股，兼看美股 / 港股**（A 股常要看隔夜外围脸色，所以数据配齐更顺手）。它不替我做决定——

- **数据层**：行情、研报、估值、财务、公告、资金面、资讯都集成进来，放进一个干净的看板；
- **接口层**：留一个能接入我自己 AI 的口子，方向和结论由我自己配置的模型产出；
- **不输出的东西**：买卖建议、目标价、择时信号——这些一律交给 AI / agent 决定，本系统只配齐数据 + 写好事实底稿的格式。

> 项目的实际定位、目标受众、技术取舍等大方向判断，详见 [VISION.md](VISION.md)；具体迭代节奏见 [ROADMAP.md](ROADMAP.md)。
>
> 涉及市场总览 / 市场监控 / 自选股的生产与显示规则，先看 [docs/production-rules.md](docs/production-rules.md)。
>
> 全栈数据平台的目标边界与非破坏迁移路径，见 [docs/target-platform-architecture.md](docs/target-platform-architecture.md)。

## 核心特性

| 模块 | 做什么 |
|---|---|
| 📊&nbsp;**每日复盘** | 大盘 / 短线情绪（连板股 · 成交额 TOP20） / 板块资金一屏看全，可一键交给 AI 复盘 |
| 📡&nbsp;**资讯雷达** | 跨赛道公开资讯聚合 + AI 要点提炼，**关注列表**自动挂钩 |
| 🔍&nbsp;**个股数据** | A 股 / 美股 / 港股 / 韩股 行情 + 估值矩阵 + 财务关键指标 + 资金面 + 研报公告 + 龙虎榜 + 限售解禁 |
| ⚔️&nbsp;**多空辩论** | 多 agent 辩论结构：事实底稿 → 多方 / 空方立论（可选交叉反驳）→ 中立主持归纳共识与分歧。**有意不产出买卖结论** |
| ⭐&nbsp;**自选股** | 批量粘贴代码即加，实时行情开关（交易时段 3 秒刷新，非交易时段自动暂停） |
| 🧩&nbsp;**板块中心** | 板块 + 产业链环节骨架 |
| 💼&nbsp;**我的持仓** | 录入即实时盈亏 + 已清仓记录（**仅本地、不上传**） |
| 📄&nbsp;**我的研报** | 私有研报归档（PDF / Word / txt / 表格 / 图片），**仅本地部署目录、不上传** |
| 📝&nbsp;**研究记录** | 复盘 / 今日要点 / 问 AI / 辩论结果本地沉淀 + 反思审计（让 AI 回头审这段推理） |
| 🔌&nbsp;**接入 AI** | 订阅 CLI（免 key） / API 多模型（自动填 baseURL） / MCP（挂进 Claude Code 等 agent） |

> **有意不提供**：买卖建议、目标价、择时信号、荐股——这些交给 AI / agent 决定。本系统只配齐数据、定义好事实底稿的格式。

## 数据源

本项目整合多套公开数据源（A 股 / 美股 / 港股 / 资讯 / 韩股），**直连调用 + 仓库内嵌离线副本**，`git clone` 下来开箱即用，无需另外下载、接线。

> ⚠️ 所有数据仅供个人研究使用，**不构成任何投资建议**。
>
> 数据源的具体技术细节、调用方式、合规分级，见各数据源子目录的 `SKILL.md`（A 股、美港股、资讯雷达）。**对外不展示具体上游仓库地址**——如有合规或归属问题，仓库 LICENSE / NOTICE 文件中保留追溯线索。

## 快速开始

### 环境要求

- Python 3.10+（推荐 3.13）
- Node.js 18+（推荐 22）
- pnpm

### 一键启动（推荐）

```bash
./start.command   # 同时启动后端 (8900) 和前端 (5899)
./stop.command    # 停掉两个服务
```

### 手动启动

```bash
# 后端（端口 8900）
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py

# 前端（端口 5899）
cd frontend
pnpm install
pnpm dev
```

打开 http://localhost:5899 即可使用。

> 启动脚本、守护进程、launchd 自启等运维细节见 [`tools/`](tools/) 目录。

## 项目结构

```
Vibe-Research/
├── backend/                 # FastAPI 后端
│   ├── app.py               # 主入口（行情 / K线 / 资讯 / 辩论 / 个股 等接口）
│   ├── astock.py            # A 股数据层（来自 a-stock-data 子模块）
│   ├── gstock.py            # 美港股数据层（来自 global-stock-data 子模块）
│   ├── newsradar.py         # 资讯雷达聚合
│   ├── market_monitor/      # 股票池 / 板块中心 / 每日复盘
│   ├── data/                # 运行时数据缓存（.gitignore）
│   └── README.md
├── frontend/                # React 19 + Vite + TypeScript
│   ├── src/pages/           # 主要页面（每日复盘 / 资讯雷达 / 个股 / 多空辩论 …）
│   ├── src/components/      # 共享组件（K 线 / PageHeader / Layout …）
│   ├── src/hooks/           # 自定义 hooks
│   └── README.md
├── a-stock-data/            # 内嵌 A 股数据源子模块（MIT License）
├── global-stock-data/       # 内嵌美港股数据源子模块（MIT License）
├── data/                    # 仓库内公开的快照数据（股票池 / 自选股历史 等）
├── docs/                    # 文档与截图
├── tools/                   # 本地运维脚本（启动守护 / launchd / 日志清理 …）
├── .workbuddy/              # WorkBuddy 项目记忆（个人助手数据，.gitignore）
├── start.command
└── stop.command
```

## 接入 AI

Vibe-Research 的核心定位是「数据 + 事实底稿」，**所有分析 / 决策都通过 AI 接口**。支持三种接入方式：

| 方式 | 适用场景 | 配置位置 |
|---|---|---|
| **订阅 CLI** | 本地已有 Claude Code / Codex / OpenCode 等 CLI 客户端时（免 API key） | 前端「接入 AI」→ 选「订阅接入」 |
| **API 多模型** | 任意 OpenAI-compatible 端点（DeepSeek / 通义千问 / 自部署模型） | 前端「接入 AI」→ 选「API」→ 填 baseURL + model |
| **MCP** | 让外部 agent（Claude Code 等）直接调用本项目的工具 / 数据 | `mcp_config.json` 注册本项目后端地址 |

> 接入 AI 之前建议先看 [`docs/upstreams/`](docs/upstreams/) 里的多空辩论 / 投研框架示例，**理解本系统怎么组织事实底稿**，效果会更好。

## License

<!-- TODO: 选择项目本身的许可证。可选：
     - MIT（最宽松，鼓励复用）
     - 仅自用声明（明确不授权第三方使用）
     - AGPL / Apache 2.0
     选定后同步更新 LICENSE 文件。 -->

**项目本身**：TODO（待定）

**内嵌子模块**保留各自原始 License（保持合规必要）：

- [`a-stock-data/`](a-stock-data/) — MIT License（详见其目录内 LICENSE）
- [`global-stock-data/`](global-stock-data/) — MIT License（详见其目录内 LICENSE）

## 致谢

<!-- TODO: 选填——如要致谢上游数据源 / 用到的库 / 工具，简短一段即可（不超过 10 行）。 -->
