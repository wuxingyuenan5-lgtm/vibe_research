CREATE TABLE IF NOT EXISTS watchlist_index_daily_cache (
  trade_date DATE NOT NULL,
  index_code TEXT NOT NULL,
  source_name TEXT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  quality_status TEXT NOT NULL,
  payload JSONB NOT NULL,
  PRIMARY KEY (trade_date, index_code, source_name)
);

