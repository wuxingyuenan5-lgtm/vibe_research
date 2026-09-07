# Data Platform Operations Contract

## Purpose

`GET /api/operations/data-platform` is an internal, read-only operations
contract. It makes the PostgreSQL import and read model observable while the
formal CSV production remains independently auditable.

## Response

- `mirror`: newest mirrored market and stock-pool dates plus row counts.
- `recent_events`: recent `ingestion_runs`; each is a completed one-way CSV
  database import, not a second source-data production job.
- `quality_checks`: recent CSV-to-database reconciliation results.

`status=ready` means the database is reachable. It does not replace the market
monitor's own data-quality verdict. A non-ready database leaves the previous
verified page snapshot in place and makes the daily production run fail clearly.

## Operating Rules

1. The CSV producer writes formal data first.
2. The database imports that completed result with natural-key upserts.
3. Reconciliation compares the database mirror with CSV exactly.
4. The operations endpoint is evidence only. It cannot refresh, repair, or
   override formal data.
5. Market-monitor and stock-pool daily reads use PostgreSQL; other domain cutovers remain separate decisions.

The database import covers all current market-monitor mother tables: market core,
hot stocks, Shenwan industry history, industry crowding, and innovation drug,
plus the independent stock-pool daily cache.

The market-monitor API now reads the materialized `market_report_snapshots`
payload. Set `VR_MARKET_READER=csv` only for an explicit manual rollback; the API
does not silently fall back when the database reader is unavailable.
