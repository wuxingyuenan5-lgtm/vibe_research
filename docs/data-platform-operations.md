# Data Platform Operations Contract

## Purpose

`GET /api/operations/data-platform` is an internal, read-only operations
contract. It makes the PostgreSQL shadow mirror observable without changing the
formal CSV production or the page-reading path.

## Response

- `mirror`: newest mirrored market and stock-pool dates plus row counts.
- `recent_events`: recent `ingestion_runs`; each is a completed one-way CSV
  shadow import, not a second production job.
- `quality_checks`: recent CSV-to-database reconciliation results.

`status=ready` means the database is reachable. It does not replace the market
monitor's own data-quality verdict. A non-ready shadow database never changes
whether the CSV producer or a page is considered successful.

## Operating Rules

1. The CSV producer writes formal data first.
2. The database imports that completed result with natural-key upserts.
3. Reconciliation compares the database mirror with CSV exactly.
4. The operations endpoint is evidence only. It cannot refresh, repair, or
   override formal data.
5. A public API/database reader cutover remains a separately approved decision.

The shadow import covers all current market-monitor mother tables: market core,
hot stocks, Shenwan industry history, industry crowding, and innovation drug,
plus the independent stock-pool daily cache.
