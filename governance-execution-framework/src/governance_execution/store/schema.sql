-- Portable schema: runs on py-pglite (PostgreSQL 17) and on SQLite (last-resort backend).
-- JSON columns are TEXT holding canonical JSON; timestamps are ISO-8601 TEXT.
-- Statements are separated by ";" at end of line; no Postgres-only functions.

CREATE TABLE IF NOT EXISTS catalog_item (
  id TEXT NOT NULL,
  kind TEXT NOT NULL,            -- control_rule|risk_rule|pattern|ra_template|app_model|decision_matrix|scoring_profile|gates
  version TEXT NOT NULL,
  status TEXT NOT NULL,
  source_ids TEXT NOT NULL,
  body TEXT NOT NULL,
  approved_by TEXT,
  approved_at TEXT,
  sha256 TEXT NOT NULL,
  PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS extraction_record (
  id TEXT PRIMARY KEY,
  item_id TEXT NOT NULL,
  prompt_version TEXT,
  model TEXT,
  input_hash TEXT,
  output TEXT,
  created TEXT
);

CREATE TABLE IF NOT EXISTS assessment (
  trace_id TEXT PRIMARY KEY,
  app_model_id TEXT,
  executor TEXT,
  mode TEXT,
  decision TEXT,
  assessment_status TEXT,
  validation_status TEXT,
  versions TEXT NOT NULL,
  started TEXT,
  finished TEXT
);

-- Immutable: rows are only inserted; same (trace_id, kind, id) must keep the same sha256.
CREATE TABLE IF NOT EXISTS artifact (
  id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  path TEXT NOT NULL,
  created TEXT NOT NULL,
  PRIMARY KEY (trace_id, kind, id),
  UNIQUE (sha256, kind, trace_id, id)
);

CREATE TABLE IF NOT EXISTS fact (
  id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  element_id TEXT,
  json_path TEXT,
  raw TEXT,
  normalized TEXT,
  taxonomy_version TEXT,
  mapping_status TEXT
);

CREATE TABLE IF NOT EXISTS decider_call (
  id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  input_hash TEXT,
  model TEXT,
  state TEXT,
  question TEXT,
  answer TEXT,
  confidence REAL,
  latency_ms REAL,
  outcome TEXT,
  cache_hit INTEGER,
  created TEXT
);

CREATE TABLE IF NOT EXISTS control_result (
  trace_id TEXT NOT NULL,
  control_id TEXT NOT NULL,
  status TEXT,
  gap_contribution REAL,
  rule_codes TEXT,
  remediation TEXT,
  PRIMARY KEY (trace_id, control_id)
);

CREATE TABLE IF NOT EXISTS risk_result (
  trace_id TEXT NOT NULL,
  risk_id TEXT NOT NULL,
  likelihood TEXT,
  impact TEXT,
  severity TEXT,
  triggered_by TEXT,
  PRIMARY KEY (trace_id, risk_id)
);

CREATE TABLE IF NOT EXISTS decision_record (
  trace_id TEXT PRIMARY KEY,
  gates_evaluated TEXT,
  matrix_cell TEXT,
  decision TEXT,
  conditions TEXT
);
