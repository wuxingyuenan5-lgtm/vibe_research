-- 个人工作区迁移基础。原文件仍保留，启用写入切换前只做显式导入。
CREATE TABLE IF NOT EXISTS portfolio_positions (
  position_key TEXT PRIMARY KEY,
  instrument_id TEXT NOT NULL,
  shares NUMERIC NOT NULL,
  cost NUMERIC NOT NULL,
  payload JSONB NOT NULL,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS portfolio_closed_positions (
  closed_key TEXT PRIMARY KEY,
  payload JSONB NOT NULL,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_reports (
  report_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  metadata JSONB NOT NULL,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_notes (
  note_id TEXT PRIMARY KEY,
  note_kind TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

