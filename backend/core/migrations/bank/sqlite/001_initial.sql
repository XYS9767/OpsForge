CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY, qid TEXT REFERENCES questions(id), payload TEXT, created REAL);
CREATE INDEX IF NOT EXISTS revisions_question ON revisions(qid,id DESC);
