CREATE TABLE favorites(id TEXT PRIMARY KEY, created REAL NOT NULL);
INSERT INTO favorites(id,created) SELECT id,COALESCE(updated,0) FROM drafts WHERE favorite=1 ON CONFLICT(id) DO NOTHING;
