CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, text TEXT DEFAULT '', notes TEXT DEFAULT '', files TEXT DEFAULT '{}', favorite INTEGER DEFAULT 0, updated REAL);
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, qid TEXT, answer TEXT, result TEXT, snapshot TEXT, created REAL, event_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS views(qid TEXT, kind TEXT, created REAL);
CREATE INDEX IF NOT EXISTS attempts_question ON attempts(qid,id DESC);
