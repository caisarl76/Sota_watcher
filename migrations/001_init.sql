CREATE TABLE targets (
  id            INTEGER PRIMARY KEY,
  title         TEXT NOT NULL,
  origin_url    TEXT NOT NULL UNIQUE,       -- 사용자가 등록한 URL
  summary       TEXT,                       -- 논문 한 줄 요약 (LLM 컨텍스트용)
  wants         TEXT NOT NULL DEFAULT '["model_release","inference_code","training_code","dataset","demo_space"]',  -- JSON 배열
  state         TEXT NOT NULL DEFAULT 'new', -- new|watching|partial|released|paused
  created_at    TEXT NOT NULL,
  last_checked  TEXT,
  last_change   TEXT
);

CREATE TABLE sources (
  id            INTEGER PRIMARY KEY,
  target_id     INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
  type          TEXT NOT NULL,              -- github|project_page|arxiv|huggingface
  url           TEXT NOT NULL,
  meta          TEXT,                       -- JSON: owner/repo, default_branch, etag, hf_repo_type ...
  error_count   INTEGER NOT NULL DEFAULT 0,
  UNIQUE(target_id, url)
);

CREATE TABLE snapshots (
  id            INTEGER PRIMARY KEY,
  source_id     INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  taken_at      TEXT NOT NULL,
  kind          TEXT NOT NULL,              -- tree|readme|page_text|hf_files|commits_head
  content_hash  TEXT NOT NULL,
  content_gz    BLOB NOT NULL
);
CREATE INDEX idx_snapshots_source ON snapshots(source_id, kind, taken_at DESC);

CREATE TABLE events (
  id            INTEGER PRIMARY KEY,
  source_id     INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  observed_at   TEXT NOT NULL,
  kind          TEXT NOT NULL,
  summary       TEXT NOT NULL,
  detail        TEXT,
  url           TEXT,
  rule_label    TEXT NOT NULL,              -- skip|candidate|strong
  run_id        TEXT NOT NULL
);

CREATE TABLE classifications (
  id            INTEGER PRIMARY KEY,
  target_id     INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
  run_id        TEXT NOT NULL,
  model         TEXT NOT NULL,
  result_json   TEXT NOT NULL,              -- LLM 출력 원문
  decided_state TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE TABLE notifications (
  id            INTEGER PRIMARY KEY,
  target_id     INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
  category      TEXT NOT NULL,
  channel       TEXT NOT NULL,              -- slack|email
  status        TEXT NOT NULL,              -- queued|sent|failed
  attempts      INTEGER NOT NULL DEFAULT 0,
  sent_at       TEXT,
  UNIQUE(target_id, category, channel)
);
