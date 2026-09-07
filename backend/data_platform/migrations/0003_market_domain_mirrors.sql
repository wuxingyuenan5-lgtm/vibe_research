-- 市场监控其余正式母表的逐行影子镜像。
-- payload 保留 CSV 原始字段，避免迁移阶段改变业务口径。

CREATE TABLE IF NOT EXISTS hot_stock_daily (
  trade_date DATE NOT NULL,
  stock_code TEXT NOT NULL,
  definition_version TEXT NOT NULL,
  source_name TEXT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL,
  PRIMARY KEY (trade_date, stock_code, definition_version, source_name)
);

CREATE TABLE IF NOT EXISTS industry_crowding_daily (
  trade_date DATE NOT NULL,
  industry_code TEXT NOT NULL,
  definition_version TEXT NOT NULL,
  source_name TEXT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL,
  PRIMARY KEY (trade_date, industry_code, definition_version, source_name)
);

CREATE TABLE IF NOT EXISTS innovation_drug_daily (
  trade_date DATE NOT NULL,
  definition_version TEXT NOT NULL,
  source_name TEXT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL,
  PRIMARY KEY (trade_date, definition_version, source_name)
);

CREATE TABLE IF NOT EXISTS industry_daily_snapshots (
  trade_date DATE NOT NULL,
  industry_code TEXT NOT NULL,
  industry_level TEXT NOT NULL,
  definition_version TEXT NOT NULL,
  source_name TEXT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL,
  PRIMARY KEY (trade_date, industry_code, industry_level, definition_version, source_name)
);

