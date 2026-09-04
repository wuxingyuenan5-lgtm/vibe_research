-- Vibe-Research PostgreSQL 影子库基础结构。
-- 本迁移只建立数据契约与运行审计，不改变当前 CSV 的生产和读取路径。

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  checksum TEXT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
  run_id UUID PRIMARY KEY,
  pipeline TEXT NOT NULL,
  target_date DATE NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('running', 'passed', 'failed', 'partial')),
  source_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_summary TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_run_steps (
  run_id UUID NOT NULL REFERENCES ingestion_runs(run_id),
  step_name TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('running', 'passed', 'failed', 'skipped')),
  row_count INTEGER,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (run_id, step_name)
);

CREATE TABLE IF NOT EXISTS data_quality_checks (
  check_id UUID PRIMARY KEY,
  run_id UUID REFERENCES ingestion_runs(run_id),
  domain TEXT NOT NULL,
  check_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('passed', 'warning', 'failed')),
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  detail JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS market_daily_snapshots (
  trade_date DATE NOT NULL,
  definition_version TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_observed_at TIMESTAMPTZ,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  quality_status TEXT NOT NULL,
  payload JSONB NOT NULL,
  PRIMARY KEY (trade_date, definition_version, source_name)
);

CREATE TABLE IF NOT EXISTS stock_pool_daily_cache (
  trade_date DATE NOT NULL,
  instrument_id TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_observed_at TIMESTAMPTZ,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  quality_status TEXT NOT NULL,
  payload JSONB NOT NULL,
  PRIMARY KEY (trade_date, instrument_id, source_name)
);

CREATE TABLE IF NOT EXISTS research_watchlists (
  watchlist_key TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  revision INTEGER NOT NULL,
  authority TEXT NOT NULL CHECK (authority IN ('local_user', 'database')),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_watchlist_members (
  watchlist_key TEXT NOT NULL REFERENCES research_watchlists(watchlist_key),
  instrument_id TEXT NOT NULL,
  member_payload JSONB NOT NULL,
  revision INTEGER NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (watchlist_key, instrument_id)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_target_date ON ingestion_runs(target_date, pipeline);
CREATE INDEX IF NOT EXISTS idx_quality_checks_domain ON data_quality_checks(domain, observed_at DESC);
