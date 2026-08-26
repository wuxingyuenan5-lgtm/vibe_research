# Vibe-Research · Personal AI Research Workspace (A-share / US / HK)

> A clean dashboard that aggregates A-share, US, and HK data — quotes, research reports, valuation, fundamentals, filings, fund flows, news — and exposes an interface for *my* AI to consume. Direction and conclusions are decided by the model *I* configure.

[![License: TODO](https://img.shields.io/badge/License-TODO-lightgrey)](#license)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![简体中文 README](https://img.shields.io/badge/📖_简体中文-README-1F6FEB?style=flat)](README.md)

<p align="center">
  <a href="#what-it-is">What it is</a> ·
  <a href="#core-features">Core features</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#project-structure">Project structure</a> ·
  <a href="#pluggable-ai">Pluggable AI</a> ·
  <a href="#license">License</a>
</p>

---

## What it is

Vibe-Research is the cross-market research workspace I use day-to-day. **Primary focus: A-share; US / HK included for overnight context** (A-share often moves on the previous night's overseas tape, so having all three is convenient). It doesn't make decisions for me —

- **Data layer**: quotes, research reports, valuation, fundamentals, filings, fund flows, news — all wired into one clean dashboard;
- **Interface layer**: a pluggable surface so *my* AI can read the structured data and produce direction;
- **What it deliberately does *not* do**: buy/sell calls, target prices, timing signals — those are the AI's job. This system only assembles data and structures the factual brief.

> Strategic direction, target audience, and technical trade-offs are documented in [VISION.md](VISION.md); iteration rhythm in [ROADMAP.md](ROADMAP.md).

## Core features

| Module | What it does |
|---|---|
| 📊&nbsp;**Daily review** | Index / sentiment (limit-up boards, top-20 by turnover) / sector flows on one screen; one-click AI review |
| 📡&nbsp;**News radar** | Public news aggregation across verticals + AI key-point extraction; tied to watchlist |
| 🔍&nbsp;**Single-stock data** | A / US / HK / KR — quotes, valuation matrix, key fundamentals, fund flows, reports, filings, top-list, unlock schedule |
| ⚔️&nbsp;**Bull / Bear debate** | Multi-agent debate: factual brief → bull case / bear case (optional cross-rebuttal) → neutral moderator (consensus + real disagreements). **Deliberately outputs no buy/sell** |
| ⭐&nbsp;**Watchlist** | Paste a list of codes to add; live quote toggle (3s refresh during trading hours, auto-pause otherwise) |
| 🧩&nbsp;**Sector hub** | Sectors + industry-chain nodes |
| 💼&nbsp;**My positions** | Live P&L + closed-position history (**local-only, never uploaded**) |
| 📄&nbsp;**My research notes** | Private research archive (PDF / Word / txt / sheets / images), **local-only** |
| 📝&nbsp;**Research journal** | Daily reviews / AI Q&A / debate results stored locally + retrospective audit (let AI critique this reasoning) |
| 🔌&nbsp;**Pluggable AI** | Subscription CLI (no key) / API multi-model (auto baseURL) / MCP (plug into Claude Code et al.) |

> **Deliberately not provided**: buy/sell calls, target prices, timing signals — delegated to AI / agent. This system only assembles data and structures the factual brief.

## Data sources

Multiple public data sources are integrated (A-share / US / HK / news / KR), **direct-fetch + embedded offline snapshots** — `git clone` is enough, no extra download or wiring needed.

> ⚠️ Data is for personal research only, **not investment advice**.
>
> Technical details, call patterns, and compliance levels are in each sub-module's `SKILL.md`. **Upstream repository addresses are intentionally not exposed in this README** — LICENSE / NOTICE files inside the repo preserve traceability.

## Quick start

### Requirements

- Python 3.10+ (3.13 recommended)
- Node.js 18+ (22 recommended)
- pnpm

### One-command start (recommended)

```bash
./start.command   # starts backend (8900) + frontend (5899)
./stop.command    # stops both
```

### Manual start

```bash
# Backend (port 8900)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py

# Frontend (port 5899)
cd frontend
pnpm install
pnpm dev
```

Open http://localhost:5899.

> Daemon / launchd / log rotation scripts are in [`tools/`](tools/).

## Project structure

```
Vibe-Research/
├── backend/                 # FastAPI backend
│   ├── app.py
│   ├── astock.py            # A-share data layer (from a-stock-data submodule)
│   ├── gstock.py            # US/HK data layer (from global-stock-data submodule)
│   ├── newsradar.py
│   ├── market_monitor/      # Stock pool / sector hub / daily review
│   └── data/                # Runtime cache (.gitignore)
├── frontend/                # React 19 + Vite + TypeScript
│   └── src/{pages,components,hooks}/
├── a-stock-data/            # Embedded A-share data submodule (MIT)
├── global-stock-data/       # Embedded US/HK data submodule (MIT)
├── data/                    # Public snapshots tracked in git (stock pool etc.)
├── docs/
├── tools/                   # Local ops scripts
├── .workbuddy/              # WorkBuddy project memory (.gitignore)
├── start.command
└── stop.command
```

## Pluggable AI

Core positioning: **data + factual brief**. All analysis / decisions flow through the AI interface. Three modes:

| Mode | When | Where |
|---|---|---|
| **Subscription CLI** | Local CLI client (Claude Code / Codex / OpenCode …) — no API key | Frontend → "AI" → "Subscription" |
| **API multi-model** | Any OpenAI-compatible endpoint (DeepSeek / Qwen / self-hosted) | Frontend → "AI" → "API" → baseURL + model |
| **MCP** | External agents (Claude Code etc.) call this project's tools directly | Register backend in `mcp_config.json` |

> Before wiring AI, skim [`docs/upstreams/`](docs/upstreams/) — the debate / research-framework examples show how this system structures factual briefs.

## License

<!-- TODO: pick one — MIT / personal-use-only / AGPL / Apache 2.0. Update LICENSE file accordingly. -->

**Project itself**: TODO

**Embedded sub-modules** retain their original licenses (compliance requirement):

- [`a-stock-data/`](a-stock-data/) — MIT (see its LICENSE)
- [`global-stock-data/`](global-stock-data/) — MIT (see its LICENSE)

## Acknowledgements

<!-- TODO: optional — short paragraph (<10 lines) crediting upstream data sources / libraries / tools. -->
