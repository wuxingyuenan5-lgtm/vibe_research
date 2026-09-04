# Vibe-Research Target Platform Architecture

**Status:** Design baseline. This document does not change the current CSV production contract.

## 1. Goal

Vibe-Research will evolve from a file-backed personal research application into a
professional, locally operated research-data platform. The target must remain
compatible with the useful architectural boundaries in `Platform_Experiment`:

- one modular-monolith business API;
- frontend reads only public API contracts;
- external providers are isolated behind adapters;
- every response states data source, observed time and quality status;
- each database table has one domain owner and one authority class;
- migrations are ordered, additive and repeatable;
- any future trade execution runtime remains a separate deployable boundary.

The old platform's execution, accounting and live-trading modules are not part of
this migration. They are future integration boundaries, not dependencies for the
current research platform.

## 2. Current Production Contract

The current file-backed system remains the only formal producer and reader until
it passes three consecutive trading-day acceptance checks.

| Domain | Current authority | Current producer | Current reader |
| --- | --- | --- | --- |
| Market monitor | `market-monitor/data/` CSV mother tables | `market-monitor/run_daily.py` | `GET /api/market-monitor` |
| Stock-pool definition | `data/stock-pool/pool.json` | local user edits | `GET /api/stock-pool` |
| Stock-pool daily cache | `data/stock-pool/stocks.csv`, `indices.csv` | `backend/market_monitor/daily_refresh.py` | `GET /api/stock-pool` |
| Realtime market modules | external provider adapters | request-time fetch plus bounded cache | market API routes |
| Personal portfolio, reports and notes | local application files | page/API mutations | dedicated API routes |

The only scheduled production trigger is the local `launchd` task at 15:05 on
weekdays. It checks the trading calendar, runs market and stock-pool production
independently, and stores successful outputs before GitHub backup.

## 3. Target Topology

```text
React frontend
  -> versioned FastAPI contracts
  -> Vibe-Research modular-monolith API
       -> research services and deterministic policies
       -> provider adapters and bounded cache
       -> repository layer
       -> PostgreSQL
  -> one local scheduled production runner
       -> provider adapters
       -> PostgreSQL ingestion and quality checks

Future only, if live execution is introduced:
  modular-monolith API -> versioned execution contract -> isolated execution runtime
```

No frontend module accesses a provider, CSV, database or broker directly. No
provider adapter contains display logic or business classification policy.

## 4. Data Authority And Initial Tables

The database will first be a **shadow mirror** of current formal files. It must
not become a second producer or change displayed data during this phase.

| Domain | Initial tables | Authority | Notes |
| --- | --- | --- | --- |
| Reference | `instruments`, `trading_calendar`, `provider_catalog` | reference/master | Normalized codes, exchanges, names and provider metadata |
| Research lists | `research_watchlists`, `research_watchlist_members`, `research_focus_members`, `research_baskets` | user-managed reference | `pool.json` remains the edit authority during migration; changes are mirrored with revision metadata |
| Market daily facts | `market_daily_snapshots`, `industry_daily_snapshots`, `industry_crowding_daily`, `innovation_drug_daily`, `hot_stock_daily` | immutable research observations | Natural key includes observation date, instrument or industry, definition version and source |
| Realtime/cache | `provider_cache_entries` | bounded cache | Has provider timestamp, fetch timestamp, expiry and explicit status; not a historical fact table |
| Operations | `ingestion_runs`, `ingestion_run_steps`, `data_quality_checks`, `data_quality_findings` | operational evidence | Each scheduled run is observable and reproducible |
| Personal workspace | `portfolio_positions`, `portfolio_transactions`, `research_reports`, `research_notes` | private user data | Migrate only after market-data mirror is verified |

All observation tables record: source name, upstream timestamp when available,
platform fetch timestamp, quality status, error summary, and definition version.
An unavailable or stale provider result cannot overwrite a valid observation.

## 5. Domain Boundaries

| Module | Owns | Must not own |
| --- | --- | --- |
| `research_market` | daily market facts, industry facts, data definitions | frontend rendering, provider HTTP details |
| `research_watchlist` | pool membership, focus and research baskets | daily prices or market production |
| `provider_adapters` | source requests, field normalization, raw provider metadata | business formulas, SQL, page behavior |
| `data_quality` | completeness, freshness, source and reconciliation checks | silently repairing source data |
| `production_operations` | scheduled run lifecycle, logs and retry evidence | research display calculations |
| `personal_workspace` | portfolios, reports, notes and user-scoped data | shared market-data authority |

The current FastAPI application can remain a modular monolith. A separate service
is justified only for a real isolation boundary, such as future broker execution.

## 5A. Current File-To-Table Mapping

This is the initial import map. It defines migration targets, not a second
production path.

| Current file | Target table | Natural key | Important fields |
| --- | --- | --- | --- |
| `market_core.csv` | `market_daily_snapshots` | `trade_date`, `definition_version` | advance/decline, limits, effective stocks, total turnover, market breadth, source |
| `hot_stocks.csv` | `hot_stock_daily` | `trade_date`, `stock_code`, `definition_version` | rank, close, return, amount, Shenwan L1/L2 |
| `innovation_drug_eastmoney.csv` | `innovation_drug_daily` | `trade_date`, `definition_version`, `source` | close, volume, amount, return, turnover |
| `sw_analysis_daily_second.csv` | `industry_crowding_daily` | `trade_date`, `industry_code`, `definition_version` | close, volume, return, turnover, amount, Eastmoney board code |
| `sw_industry_history.csv` | `industry_daily_snapshots` | `trade_date`, `industry_code`, `industry_level`, `definition_version` | L1 ownership, close, amount, return, 20-day volatility |
| `sw_stock_mapping.csv` | `instrument_industry_memberships` | `instrument_id`, `classification_version` | Shenwan L1/L2 codes and names |
| `pool.json` | `research_watchlists`, `research_watchlist_members`, `research_focus_members`, `research_baskets` | list/basket key plus instrument | local pool definition, Focus and research-basket membership |
| `stocks.csv` | `stock_pool_daily_cache` | `trade_date`, `instrument_id`, `source` | price, return windows, amount, valuation, turnover and quality status |
| `indices.csv` | `watchlist_index_daily_cache` | `trade_date`, `index_code`, `source` | price, return windows, amount, valuation and quality status |

Importers must preserve the raw source label and add `ingested_at`,
`source_observed_at` when available, and `quality_status`. Values are not
silently converted from `stale` to `ready` during import.

## 6. Migration Phases

### Phase 0: Stabilize And Observe

1. Verify three consecutive trading days of current automatic production.
2. Record each run's start, finish, provider result, written dates and page checks.
3. Do not modify formal CSV readers or page contracts.

### Phase 1: Database Foundation

1. Add PostgreSQL configuration, migrations and repository conventions.
2. Create the reference, market-observation, quality and ingestion-run tables.
3. Add a one-way CSV-to-database importer with idempotent natural keys.
4. Compare daily row counts, dates, source metadata and key aggregates against CSV.

### Phase 2: Shadow Read Validation

1. Keep production writing CSV first.
2. Mirror the validated result to PostgreSQL.
3. Build internal comparison endpoints and an operations view.
4. Require a sustained zero-difference window before changing a public reader.

### Phase 3: Read Cutover By Domain

1. Move market-monitor historical/API reads to PostgreSQL.
2. Move stock-pool daily cache reads to PostgreSQL while retaining `pool.json` as
   the local editing authority until its user workflow is migrated.
3. Move personal workspace data separately with user-scoped access controls.
4. Retire a CSV only after its replacement has a verified backup/export path.

## 7. Non-Negotiable Rules

1. No big-bang rewrite.
2. One business rule has one owner.
3. CSV and database must never both be treated as independent formal producers.
4. A source fallback is explicit, labeled and later repairable; it is never silent.
5. Data quality is an operational fact, not a cosmetic page badge.
6. Schema migrations are additive, versioned, tested on clean and existing data,
   and never altered after being applied.
7. No execution or accounting concepts enter the research data model without a
   separate approved contract.

## 8. Immediate Next Work

1. Confirm today's 15:05 scheduled run and start the three-day acceptance window.
2. Inventory CSV/JSON fields and map them to the Phase 1 schema.
3. Choose PostgreSQL deployment details and create migrations only after the
   acceptance window starts successfully.
