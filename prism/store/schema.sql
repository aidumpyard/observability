-- Prism central store (SQLite). One file; the collector is the only writer.
-- WAL + busy_timeout are set on connect (db.py), not here.

CREATE TABLE IF NOT EXISTS apps (
    app_id      TEXT PRIMARY KEY,
    name        TEXT,
    owner       TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS prompts (
    prompt_id      TEXT PRIMARY KEY,
    app_id         TEXT,
    name           TEXT,
    version        INTEGER,
    template       TEXT,
    variables_json TEXT,
    tags           TEXT,
    created_by     TEXT,
    created_at     TEXT
);

CREATE TABLE IF NOT EXISTS traces (
    trace_id    TEXT PRIMARY KEY,
    app_id      TEXT,
    user_id     TEXT,
    session_id  TEXT,
    name        TEXT,
    status      TEXT,
    started_at  TEXT,   -- UTC; derived from min(span.started_at)
    ended_at    TEXT,   -- UTC; derived from max(span.ended_at)
    duration_ms REAL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS spans (
    span_id        TEXT PRIMARY KEY,
    trace_id       TEXT,
    parent_span_id TEXT,
    type           TEXT,
    name           TEXT,
    model          TEXT,
    prompt_id      TEXT,
    params_json    TEXT,
    system_prompt  TEXT,
    user_message   TEXT,
    response_text  TEXT,
    input_json     TEXT,
    output_json    TEXT,
    attributes_json TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    thoughts_tokens   INTEGER,
    tokens_source  TEXT,            -- 'model' | 'estimated'
    finish_reason  TEXT,
    full_gemini_response TEXT,
    cost_usd       REAL,
    duration_ms    REAL,            -- measured locally on the producing host
    status         TEXT,
    error          TEXT,
    data_classification TEXT,
    response_id    TEXT,
    project_id     TEXT,            -- tenant; stamped server-side from the ingest key
    app_id         TEXT,
    env            TEXT,
    app_type       TEXT,
    internal       TEXT,            -- 'eval' etc. — excluded from product metrics
    schema_version INTEGER,
    started_at     TEXT,            -- UTC, producer clock
    ended_at       TEXT,
    created_at     TEXT,            -- UTC, producer clock
    received_at    TEXT             -- UTC, collector clock (for skew correction)
);

CREATE TABLE IF NOT EXISTS scores (
    score_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    span_id     TEXT,
    trace_id    TEXT,
    name        TEXT,
    value       REAL,
    label       TEXT,
    source      TEXT,               -- 'heuristic' | 'llm_judge' | 'human'
    rationale   TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS costs (
    model          TEXT PRIMARY KEY,
    input_per_1k   REAL,
    output_per_1k  REAL,
    currency       TEXT DEFAULT 'USD'
);

-- Multi-tenant: one row per client/project. The ingest key maps a request to a
-- project; the collector stamps project_id on spans server-side.
CREATE TABLE IF NOT EXISTS projects (
    project_id  TEXT PRIMARY KEY,
    name        TEXT,
    ingest_key  TEXT UNIQUE,
    active      INTEGER DEFAULT 1,
    created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_spans_trace   ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_app     ON spans(app_id);
CREATE INDEX IF NOT EXISTS idx_spans_created ON spans(created_at);
CREATE INDEX IF NOT EXISTS idx_spans_model   ON spans(model);
CREATE INDEX IF NOT EXISTS idx_scores_span   ON scores(span_id);
CREATE INDEX IF NOT EXISTS idx_traces_app    ON traces(app_id);
CREATE INDEX IF NOT EXISTS idx_spans_project ON spans(project_id);
