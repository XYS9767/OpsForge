"""The learning domain: owned state transitions and API handlers."""
import json
import time
import hashlib
import re
from bank import generator
from labs import scenarios
from core.errors import ApiError
from bank.review import require_published
from .notes import NotesService
from core.files import validate_files
from core.question_identity import content_key


class LearningService(NotesService):
    def learning_states(self, content_keys=None):
        with self.db('learning') as db:
            rounds = {r['qid']: dict(r) for r in db.execute('SELECT * FROM practice_rounds')}
            drafts = {r['id']: r['revision'] for r in db.execute('SELECT id,revision FROM drafts')}
            latest = db.execute('SELECT qid,MAX(id) AS id FROM attempts GROUP BY qid').fetchall()
            selected = [row['id'] for row in latest
                        if row['id'] > rounds.get(row['qid'], {}).get('attempt_after', 0)
                        and (content_keys is None or row['qid'] in content_keys)]
            def snapshots():
                # Do not materialize every historical task body for a one-item
                # page or hold the whole question bank's snapshots in memory.
                for offset in range(0, len(selected), 100):
                    ids = selected[offset:offset + 100]
                    yield from db.execute('SELECT id,qid,result,snapshot FROM attempts WHERE id IN (' + ','.join('?' for _ in ids) + ')', ids).fetchall()
            applicable = []
            for row in snapshots():
                qid = row['qid']
                after = rounds.get(qid, {}).get('attempt_after', 0)
                expected = content_keys.get(qid) if content_keys is not None else None
                if expected is None or content_key(json.loads(row['snapshot'])) == expected:
                    applicable.append({'qid':qid, 'result':row['result']})
                    continue
                # A frozen old exam can finish after a current-version attempt.
                # Search backwards in bounded pages without altering history.
                before = row['id']
                while True:
                    batch = db.execute('SELECT id,qid,result,snapshot FROM attempts WHERE qid=? AND id>? AND id<? ORDER BY id DESC LIMIT 100',
                                       (qid, after, before)).fetchall()
                    match = next((item for item in batch if content_key(json.loads(item['snapshot'])) == expected), None)
                    if match is not None:
                        applicable.append({'qid':qid, 'result':match['result']})
                        break
                    if len(batch) < 100:
                        break
                    before = batch[-1]['id']
        states = {qid: {'completion':'in_progress' if revision > rounds.get(qid, {}).get('start_revision', -1) else 'not_started', 'mastery':'unrated'} for qid, revision in drafts.items()}
        for qid in rounds:
            states.setdefault(qid, {'completion':'not_started','mastery':'unrated'})
        for row in applicable:
            passed = json.loads(row['result']).get('passed')
            states[row['qid']] = {'completion':'submitted','mastery':'mastered' if passed is True else 'review' if passed is False else 'unrated'}
        return states

    def grade(self, q, answer, self_rating=None, lab=None):
        from bank.assessment import grade
        checked = grade(q, answer)
        if checked is not None:
            return checked
        if q["type"] == "generated":
            passed = generator.grade(q, answer)
            return {"passed": passed, "method": "自动判分", "message": "回答正确" if passed else "尚未通过，请检查格式和推导"}
        if lab and lab["qid"] == q["id"] and lab["mode"] == "simulation":
            return {**scenarios.check(lab["payload"]), "method": "状态验收"}
        if self_rating in ["mastered", "review"]:
            return {"passed": self_rating == "mastered", "method": "对照要点自评", "message": "已记录自评；此结果不是自动语义评分"}
        return {"passed": None, "method": "待自评", "message": "回答已保存。展开参考答案和评分要点后，可标记掌握或待复习。"}


    def record(self, q, answer, result, event_key=None, submission=None):
        with self.db("learning") as db:
            db.execute("INSERT INTO attempts(qid,answer,result,snapshot,created,event_key,submission) VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_key) DO NOTHING",
                       (q["id"], answer, json.dumps(result, ensure_ascii=False), json.dumps(q, ensure_ascii=False), time.time(), event_key,
                        json.dumps(submission, ensure_ascii=False) if submission is not None else None))
            if event_key:
                return db.execute("SELECT id FROM attempts WHERE event_key=?", (event_key,)).fetchone()[0]


    def favorite_ids(self):
        with self.db("learning") as db:
            return {r[0] for r in db.execute("SELECT id FROM favorites")}

    def learning_summary(self):
        with self.db("learning") as db:
            total = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
            attempts = db.execute("SELECT a.qid,a.result FROM attempts a JOIN (SELECT qid,MAX(id) AS id FROM attempts GROUP BY qid) latest ON a.id=latest.id").fetchall()
            saved = db.execute("SELECT count(*) FROM favorites").fetchone()[0]
        return {"attempt_count": total, "favorites": saved,
                "latest": {r[0]: json.loads(r[1]) for r in attempts}}

    def exam_attempts(self, eid):
        with self.db("learning") as db:
            rows = db.execute("SELECT id,qid,result,snapshot FROM attempts WHERE event_key LIKE ?", ("exam:" + eid + ":%",)).fetchall()
        return [{"id": r["qid"], "title": json.loads(r["snapshot"])["title"],
                 "attempt_id": r["id"], **json.loads(r["result"])} for r in rows]

    def draft_details(self, question):
        exam_draft = self.exam_draft(question)
        if exam_draft is not None:
            exam_draft["favorite"] = int(question["id"] in self.favorite_ids())
            return exam_draft, {}
        with self.db("learning") as db:
            row = db.execute("SELECT * FROM drafts WHERE id=?", (question["id"],)).fetchone()
            current_round = db.execute('SELECT scope FROM practice_rounds WHERE qid=?', (question['id'],)).fetchone()
            viewed = db.execute("SELECT kind,count(*) FROM views WHERE qid=? GROUP BY kind", (question["id"],)).fetchall()
        draft = dict(row) if row else {"text": "", "notes": "", "files": json.dumps(question.get("files", {})), "favorite": 0}
        draft["files"] = json.loads(draft["files"])
        draft["favorite"] = int(question["id"] in self.favorite_ids())
        draft.setdefault("revision", 0)
        draft["scope"] = current_round['scope'] if current_round else 'practice'
        return draft, {r[0]: r[1] for r in viewed}

    def mark_view(self, qid, kind):
        with self.db("learning") as db:
            db.execute("INSERT INTO views VALUES(?,?,?)", (qid, kind, time.time()))

    def learning_export(self):
        with self.db("learning") as db:
            return ([dict(r) for r in db.execute("SELECT * FROM drafts")],
                    [dict(r) for r in db.execute("SELECT * FROM attempts")])

    def learning_export_page(self, section, after='', through=None):
        from core.archive import page
        if section not in ('drafts', 'attempts', 'favorites'):
            raise ApiError('未知学习归档部分')
        with self.db('learning') as db:
            return page(db, section, after, through)

    def route_learning(self, method, path, args, body, env, user):
        note_response = self.route_notes(method, path, args)
        if note_response is not None:
            return note_response
        if method == 'POST' and path == '/api/practice/restart':
            request_id = body.get('request_id')
            if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', request_id):
                raise ApiError('重新练习需要有效的请求标识')
            fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            with self.db('learning') as db:
                existing = db.execute('SELECT * FROM practice_restarts WHERE request_id=?', (request_id,)).fetchone()
            if existing:
                if existing['fingerprint'] != fingerprint:
                    raise ApiError('请求标识已用于其他重新练习操作', 409)
                return {'id':existing['qid'], 'scope':existing['scope'], 'restarted':True}, []
            q = self.getq(body['id']); require_published(q)
            current, _ = self.draft_details(q)
            if current['scope'].startswith('exam:'):
                raise ApiError('此题正在考试中，请先完成考试', 409)
            if type(body.get('revision')) is not int or body.get('revision') != current['revision'] or body.get('scope') != current['scope']:
                raise ApiError('本轮草稿已变化，请重新读取后再开始', 409)
            # Reset only this question's workspace. On cleanup failure, keep the draft.
            self.reset_question_labs([q['id']])
            scope = 'practice:' + request_id
            revision = current['revision'] + 1
            with self.db('learning') as db:
                after = db.execute('SELECT COALESCE(MAX(id),0) FROM attempts WHERE qid=?', (q['id'],)).fetchone()[0]
                db.execute("INSERT INTO drafts(id,text,notes,files,favorite,updated,revision) VALUES(?,'','',?,0,?,?) ON CONFLICT(id) DO UPDATE SET text='',notes='',files=excluded.files,updated=excluded.updated,revision=excluded.revision", (q['id'], json.dumps(q.get('files', {})), time.time(), revision))
                db.execute('INSERT INTO practice_rounds(qid,scope,attempt_after,start_revision) VALUES(?,?,?,?) ON CONFLICT(qid) DO UPDATE SET scope=excluded.scope,attempt_after=excluded.attempt_after,start_revision=excluded.start_revision', (q['id'],scope,after,revision))
                db.execute('INSERT INTO practice_restarts VALUES(?,?,?,?)', (request_id,q['id'],fingerprint,scope))
            return {'id':q['id'],'scope':scope,'restarted':True}, []
        if method == "POST" and path == "/api/attempt/rating":
            rating = body.get("rating")
            if rating not in ("mastered", "review"):
                raise ApiError("请选择已掌握或待复习")
            with self.db("learning") as db:
                row = db.execute("SELECT * FROM attempts WHERE id=?", (int(body["id"]),)).fetchone()
                if not row:
                    raise ApiError("答题记录不存在", 404)
                q = json.loads(row["snapshot"])
                self.ensure_answer_allowed(q["id"])
                from bank.assessment import capable
                if (capable(q) or q.get('exercise') or q["type"] not in ("source", "interview", "case", "practice", "code")
                        or (str(row['event_key'] or '').startswith('exam:') and q['type'] != 'interview')):
                    from bank.hands_on import manual_artifact_contract
                    if manual_artifact_contract(q):
                        raise ApiError("此产物需要独立人工审核，不能用自评替代审核。")
                    raise ApiError("此作答使用自动验收，不能覆盖自动结果")
                result = self.grade(q, row["answer"], rating)
                db.execute("UPDATE attempts SET result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), row["id"]))
            return {"id": row["id"], "result": result}, []
        if method == "POST" and path == "/api/favorite":
            q = self.getq(body["id"])
            enabled = body.get("enabled")
            if not isinstance(enabled, bool):
                raise ApiError("enabled 必须为 true 或 false")
            with self.db("learning") as db:
                if enabled:
                    db.execute("INSERT INTO favorites VALUES(?,?) ON CONFLICT(id) DO NOTHING", (q["id"], time.time()))
                else:
                    db.execute("DELETE FROM favorites WHERE id=?", (q["id"],))
            return {"id": q["id"], "favorite": enabled}, []
        if method == "POST" and path == "/api/draft":
            q = self.exam_question(body['id']) or self.getq(body["id"])
            exam = self.active_exam()
            if exam and time.time() > exam["deadline"] and q["id"] in json.loads(exam["payload"])["ids"]:
                raise ApiError("考试已到时，请交卷；截止时间后的作答不再计入", 409)
            text, notes, files = body.get("text", ""), body.get("notes", ""), body.get("files", {})
            if not isinstance(text, str) or not isinstance(notes, str) or len(text) > 100000 or len(notes) > 100000:
                raise ApiError("草稿内容过大或格式错误")
            validate_files(files)
            revision = body.get("revision")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise ApiError("保存需要当前草稿 revision，请刷新客户端", 409)
            current, _ = self.draft_details(q)
            if body.get("scope") != current["scope"]:
                raise ApiError("草稿所属练习或考试已变化，请重新打开；本地内容仍保留", 409)
            if revision != current["revision"]:
                raise ApiError("草稿已被其他页面更新，请处理版本冲突；本地内容仍保留", 409)
            if self.save_exam_draft(q, body):
                return {"saved": True, "scope": current["scope"], "revision": revision + 1}, []
            with self.db("learning") as db:
                saved = db.execute("INSERT INTO drafts(id,text,notes,files,favorite,updated,revision) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET text=excluded.text,notes=excluded.notes,files=excluded.files,updated=excluded.updated,revision=excluded.revision WHERE drafts.revision=?",
                                   (q["id"], text, notes, json.dumps(files), 0, time.time(), revision + 1, revision))
                if saved.rowcount != 1:
                    raise ApiError("草稿版本冲突；本地内容仍保留", 409)
            return {"saved": True, "scope": current['scope'], "revision": revision + 1}, []

        if method == "POST" and path == "/api/submit":
            request_id = body.get('request_id')
            event_key = None
            fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if request_id is not None:
                if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', request_id):
                    raise ApiError('无效的提交标识')
                event_key = 'practice:' + request_id
                with self.db('learning') as db:
                    previous = db.execute('SELECT result,submission FROM attempts WHERE event_key=?', (event_key,)).fetchone()
                if previous:
                    if json.loads(previous['submission'] or '{}').get('request_fingerprint') != fingerprint:
                        raise ApiError('提交标识已用于不同内容，请重新提交', 409)
                    return json.loads(previous['result']), []
            q = self.getq(body["id"])
            require_published(q)
            if int(body.get("version", q.get("version", 1))) != q.get("version", 1):
                raise ApiError("题目版本已变化，请重新打开题目后提交", 409)
            answer = str(body.get("answer", ""))[:100000]
            draft, _ = self.draft_details(q)
            if q['type'] == 'code' or 'draft_revision' in body or draft['scope'] != 'practice':
                revision = body.get('draft_revision')
                if (isinstance(revision, bool) or not isinstance(revision, int)
                        or revision != draft['revision'] or body.get('draft_scope') != draft['scope']):
                    raise ApiError('提交需要已保存的当前草稿版本，请保存或处理冲突后重试', 409)
            submission = {'files': draft['files'], 'notes': draft.get('notes', ''),
                          'draft_revision': draft['revision'], 'scope': draft['scope'],
                          'request_fingerprint': fingerprint}
            exam = self.active_exam()
            if exam and q["id"] in json.loads(exam["payload"])["ids"]:
                raise ApiError("考试题请通过交卷统一提交")
            lab = self.lab(body["lab"]) if body.get("lab") else None
            if q.get('exercise'):
                result = self.grade_artifact_submission(lab['id'] if lab else None, q, draft['files'])
            elif lab and lab["qid"] == q["id"] and lab["mode"] == "real" and q["type"] == "scenario":
                result = self.grade_real_lab(lab["id"], q)
            else:
                result = self.grade(q, answer, body.get("self_rating"), lab)
            with self.lock:
                if event_key:
                    with self.db('learning') as db:
                        previous = db.execute('SELECT result,submission FROM attempts WHERE event_key=?', (event_key,)).fetchone()
                    if previous:
                        if json.loads(previous['submission'] or '{}').get('request_fingerprint') != fingerprint:
                            raise ApiError('提交标识已用于不同内容，请重新提交', 409)
                        return json.loads(previous['result']), []
                current = self.getq(q["id"])
                if current.get("version", 1) != q.get("version", 1):
                    raise ApiError("验收期间题目已变化，请重新打开后提交", 409)
                exam = self.active_exam()
                if exam and q["id"] in json.loads(exam["payload"])["ids"]:
                    raise ApiError("考试题请通过交卷统一提交", 409)
                latest_draft, _ = self.draft_details(q)
                if latest_draft['revision'] != draft['revision'] or latest_draft['scope'] != draft['scope']:
                    raise ApiError('验收期间草稿已变化，请保存后重新提交', 409)
                self.record(q, answer, result, event_key=event_key, submission=submission)
            return result, []

        if method == "GET" and path == "/api/progress":
            size = min(100, max(1, int(args.get('size', 50))))
            before = int(args.get('before', 0))
            if before < 0:
                raise ApiError('无效的分页游标')
            with self.db("learning") as db:
                rows = db.execute("SELECT id,qid,snapshot,result,created,substr(answer,1,200) AS answer FROM attempts WHERE (?=0 OR id<?) ORDER BY id DESC LIMIT ?", (before, before, size + 1)).fetchall()
                total = db.execute('SELECT count(*) FROM attempts').fetchone()[0]
            more = len(rows) > size
            rows = rows[:size]
            return {"attempts": [{"id": r["id"], "qid": r["qid"], "title": json.loads(r["snapshot"])["title"],
                                  "version": json.loads(r["snapshot"]).get("version", 1),
                                  "answer": r["answer"], "result": json.loads(r["result"]), "created": r["created"]} for r in rows],
                    "total": total, "next": rows[-1]['id'] if more else None}, []

        if method == "GET" and path in ["/api/attempt", "/api/attempt/answer"]:
            with self.db("learning") as db:
                row = db.execute("SELECT * FROM attempts WHERE id=?", (int(args["id"]),)).fetchone()
            if not row:
                raise ApiError("答题记录不存在", 404)
            q = json.loads(row["snapshot"])
            if path.endswith("/answer"):
                self.ensure_answer_allowed(q["id"])
                return {"id": q["id"], "version": q.get("version", 1), "answer": q.get("answer", ""),
                        "explanation": q.get("explanation", ""), "references": q.get("references", [])}, []
            return {"id": row["id"], "question": self.public(q), "answer": row["answer"],
                    "exam_id": row['event_key'].split(':')[1] if str(row['event_key'] or '').startswith('exam:') else None,
                    "submission": json.loads(row['submission']) if row['submission'] else None,
                    "result": json.loads(row["result"]), "created": row["created"]}, []

        return None
