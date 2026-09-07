-- 市场总览的数据库只读模型。正式生产输入仍是 CSV 母表。
CREATE TABLE IF NOT EXISTS market_report_snapshots (
  trade_date DATE NOT NULL,
  definition_version TEXT NOT NULL,
  source_name TEXT NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL,
  PRIMARY KEY (trade_date, definition_version, source_name)
);

CREATE INDEX IF NOT EXISTS idx_market_report_latest
  ON market_report_snapshots(trade_date DESC, generated_at DESC);

