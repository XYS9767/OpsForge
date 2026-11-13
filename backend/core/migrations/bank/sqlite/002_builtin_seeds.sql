CREATE TABLE builtin_seeds(qid TEXT PRIMARY KEY REFERENCES questions(id), fingerprint TEXT NOT NULL);
