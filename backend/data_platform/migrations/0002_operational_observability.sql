-- 平台运行可观测性与后续领域迁移的预留结构。
-- 不参与当前 CSV 正式生产或页面读取。

CREATE TABLE IF NOT EXISTS production_run_events (
  event_id UUID PRIMARY KEY,
  pipeline TEXT NOT NULL,
  target_date DATE NOT NULL,
  stage TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('started', 'passed', 'failed', 'skipped', 'warning')),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  detail JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS data_quality_findings (
  finding_id UUID PRIMARY KEY,
  domain TEXT NOT NULL,
  target_date DATE,
  severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
  finding_code TEXT NOT NULL,
  summary TEXT NOT NULL,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS provider_catalog (
  provider_key TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  authority_scope TEXT NOT NULL,
  fallback_only BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_cache_entries (
  cache_key TEXT PRIMARY KEY,
  provider_key TEXT NOT NULL REFERENCES provider_catalog(provider_key),
  observed_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ready', 'stale', 'failed')),
  payload JSONB,
  error_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_production_run_events_date ON production_run_events(target_date, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_data_quality_findings_open ON data_quality_findings(domain, target_date) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_provider_cache_expiry ON provider_cache_entries(expires_at);
