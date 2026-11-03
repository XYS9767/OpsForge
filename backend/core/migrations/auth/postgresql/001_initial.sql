CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, csrf TEXT, expires DOUBLE PRECISION);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires);
