CREATE TABLE practice_rounds(qid TEXT PRIMARY KEY, scope TEXT NOT NULL, attempt_after INTEGER NOT NULL, start_revision INTEGER NOT NULL);
CREATE TABLE practice_restarts(request_id TEXT PRIMARY KEY, qid TEXT NOT NULL, fingerprint TEXT NOT NULL, scope TEXT NOT NULL);
