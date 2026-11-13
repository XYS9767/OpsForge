CREATE TABLE IF NOT EXISTS questions(
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    CHECK (payload->>'id' = id),
    CHECK (jsonb_typeof(payload) = 'object'),
    CHECK ((payload->>'version')::integer > 0)
);
CREATE TABLE IF NOT EXISTS revisions(
    id BIGSERIAL PRIMARY KEY, qid TEXT REFERENCES questions(id),
    payload JSONB NOT NULL, created DOUBLE PRECISION,
    CHECK(payload->>'id' = qid)
);
CREATE INDEX IF NOT EXISTS questions_module ON questions((payload->>'module'));
CREATE INDEX IF NOT EXISTS questions_review ON questions((payload->>'review_status'));
CREATE INDEX IF NOT EXISTS revisions_question ON revisions(qid, id DESC);
