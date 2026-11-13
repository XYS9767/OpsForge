ALTER TABLE exams ADD COLUMN created DOUBLE PRECISION;
ALTER TABLE exams ADD COLUMN duration_minutes INTEGER;
ALTER TABLE exams ADD COLUMN source_exam_id TEXT;
ALTER TABLE exams ADD COLUMN request_id TEXT;
CREATE UNIQUE INDEX exam_request ON exams(request_id);
