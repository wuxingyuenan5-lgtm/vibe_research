CREATE TABLE IF NOT EXISTS workspace_metadata (
  metadata_key TEXT PRIMARY KEY,
  payload JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE portfolio_closed_positions ADD COLUMN IF NOT EXISTS ordinal INTEGER;

CREATE INDEX IF NOT EXISTS idx_research_notes_created_at ON research_notes(created_at DESC);
