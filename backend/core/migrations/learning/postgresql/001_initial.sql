CREATE TABLE IF NOT EXISTS drafts(
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
    files JSONB NOT NULL DEFAULT '{}', favorite INTEGER NOT NULL DEFAULT 0,
    updated DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS attempts(
    id BIGSERIAL PRIMARY KEY, qid TEXT NOT NULL,
    answer TEXT, result JSONB NOT NULL, snapshot JSONB NOT NULL, created DOUBLE PRECISION, event_key TEXT UNIQUE,
    CHECK(snapshot->>'id' = qid)
);
CREATE TABLE IF NOT EXISTS views(qid TEXT, kind TEXT, created DOUBLE PRECISION);
CREATE INDEX IF NOT EXISTS attempts_question ON attempts(qid, id DESC);
