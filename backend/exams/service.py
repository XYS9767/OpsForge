"""The exams domain: owned state transitions and API handlers."""
import json
import re
import secrets
import time
from core.errors import ApiError
from .scoring import report


class ExamService:
    def grade_exam_answer(self, question, draft, created):
        if question.get('exercise') or question['type'] == 'scenario':
            return self.grade_exam_lab(question, created, draft.get('files', {}))
        answer = draft.get('text', '')
        if question['type'] != 'interview' and not answer.strip():
            return {'passed': False, 'method': '自动判分', 'message': '本题未作答，计0分。'}
        result = self.grade(question, answer)
        if question['type'] != 'interview' and result.get('passed') is None:
            return {'passed': None, 'method': '待判分', 'stage': 'missing_grader',
                    'message': '此旧版题缺少自动验收规则，不能用关键词或自评代替程序判题。'}
        return result

    def exam_states(self):
        exam = self._active_exam()
        if not exam:
            return {}
        payload = json.loads(exam['payload'])
        return {qid: {'completion':'in_progress' if payload.get('drafts', {}).get(qid, {}).get('revision', 0) else 'not_started', 'mastery':'unrated'} for qid in payload['ids']}

    def exam_draft(self, question):
        exam = self._active_exam()
        if not exam:
            return None
        payload = json.loads(exam["payload"])
        if question["id"] not in payload["ids"]:
            return None
        draft = payload.get("drafts", {}).get(question["id"], {
            "text": "", "notes": "", "files": question.get("files", {}), "favorite": 0
        })
        return {**draft, "revision": draft.get("revision", 0), "scope": "exam:" + exam["id"]}

    def save_exam_draft(self, question, draft):
        exam = self._active_exam()
        if not exam:
            return False
        payload = json.loads(exam["payload"])
        if question["id"] not in payload["ids"]:
            return False
        if time.time() > exam["deadline"] or "deliveries" in payload or 'submission_started_at' in payload:
            raise ApiError("考试已到时或正在交卷，不能再修改本次作答", 409)
        payload.setdefault("drafts", {})[question["id"]] = {
            "text": draft.get("text", ""), "notes": draft.get("notes", ""),
            "files": draft.get("files", {}), "favorite": int(bool(draft.get("favorite"))),
            "revision": draft["revision"] + 1
        }
        with self.db("exams") as db:
            db.execute("UPDATE exams SET payload=? WHERE id=?", (json.dumps(payload), exam["id"]))
        return True

    def _active_exam(self):
        with self.db("exams") as db:
            row = db.execute("SELECT * FROM exams WHERE finished=0 ORDER BY deadline DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def active_exam(self):
        # Cross-service callers need only membership and timing, never all drafts.
        exam = self._active_exam()
        if exam:
            exam['payload'] = json.dumps({'ids': json.loads(exam['payload'])['ids']})
        return exam

    def exam_question(self, qid):
        exam = self._active_exam()
        if not exam:
            return None
        return next((q for q in json.loads(exam['payload']).get('snapshots', []) if q['id'] == qid), None)


    def ensure_answer_allowed(self, qid):
        exam = self.active_exam()
        if exam and qid in json.loads(exam["payload"])["ids"]:
            raise ApiError("考试进行中，交卷后可查看提示和参考答案")


    def route_exams(self, method, path, args, body, env, user):
        if method == 'POST' and path == '/api/exam/check':
            exam = self._active_exam()
            if not exam or body.get('id') != exam['id']:
                raise ApiError('当前试卷已结束或发生变化', 409)
            payload = json.loads(exam['payload'])
            if time.time() > exam['deadline'] or 'deliveries' in payload or 'submission_started_at' in payload:
                raise ApiError('考试已到时或正在交卷', 409)
            q = next((q for q in payload['snapshots'] if q['id'] == body.get('qid')), None)
            if not q:
                raise ApiError('题目不属于当前试卷', 400)
            draft = payload.get('drafts', {}).get(q['id'], {'revision': 0, 'files': q.get('files', {})})
            if type(body.get('revision')) is not int or body['revision'] != draft.get('revision', 0):
                raise ApiError('请先保存本题最新产物后再验收', 409)
            result = self.grade_exam_answer(q, draft, exam['created'] or 0)
            fresh = self._active_exam()
            if not fresh or fresh['id'] != exam['id']:
                raise ApiError('验收期间试卷已结束', 409)
            payload = json.loads(fresh['payload'])
            if ('deliveries' in payload or 'submission_started_at' in payload or time.time() > exam['deadline']
                    or payload.get('drafts', {}).get(q['id'], {}).get('revision', 0) != body['revision']):
                raise ApiError('验收期间草稿或考试状态变化，请重试', 409)
            payload.setdefault('checks', {})[q['id']] = {'revision': body['revision'], 'result': result}
            with self.db('exams') as db:
                db.execute('UPDATE exams SET payload=? WHERE id=? AND finished=0', (json.dumps(payload), exam['id']))
            return {'saved': True, 'message': '已记录本题验收快照，判分结果在交卷后展示。'}, []
        if method == 'GET' and path == '/api/exam/history':
            page = max(1, int(args.get('page', 1)))
            with self.db('exams') as db:
                total = db.execute('SELECT COUNT(*) FROM exams WHERE finished=1').fetchone()[0]
                rows = db.execute('SELECT id,deadline,created,duration_minutes,source_exam_id FROM exams WHERE finished=1 ORDER BY COALESCE(created,deadline) DESC,id DESC LIMIT 20 OFFSET ?', ((page-1)*20,)).fetchall()
            return {'items':[dict(r) for r in rows], 'total':total, 'page':page}, []
        if method == 'POST' and path == '/api/exam/retake':
            request_id, source = body.get('request_id'), body.get('id')
            if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', request_id):
                raise ApiError('重考需要有效的请求编号')
            with self.db('exams') as db:
                existing = db.execute('SELECT * FROM exams WHERE request_id=?', (request_id,)).fetchone()
                original = db.execute('SELECT * FROM exams WHERE id=?', (source,)).fetchone()
            if not original:
                raise ApiError('原试卷不存在', 404)
            if not original['finished']:
                raise ApiError('请先交完原试卷再重考', 409)
            minutes = original['duration_minutes'] or body.get('minutes', 30)
            if type(minutes) is not int or not 1 <= minutes <= 180:
                raise ApiError('旧试卷未记录时长，请设置 1–180 分钟')
            if existing:
                if existing['source_exam_id'] != source or existing['duration_minutes'] != minutes:
                    raise ApiError('重考请求编号已用于其他试卷或时长', 409)
                return {'id':existing['id'], 'ids':json.loads(existing['payload'])['ids'], 'deadline':existing['deadline'], 'server_time':time.time(), 'finished':bool(existing['finished'])}, []
            if self.active_exam():
                raise ApiError('请先完成当前考试再重考', 409)
            original_payload = json.loads(original['payload'])
            snapshots = original_payload.get('snapshots', [])
            if [q['id'] for q in snapshots] != original_payload['ids']:
                raise ApiError('原试卷题目快照不完整，不能保证原卷重考', 409)
            self.reset_question_labs(original_payload['ids'])
            eid, created = secrets.token_hex(10), time.time()
            deadline = created + minutes * 60
            payload = {'ids':original_payload['ids'], 'snapshots':snapshots, 'drafts':{}}
            with self.db('exams') as db:
                db.execute('INSERT INTO exams(id,payload,deadline,finished,created,duration_minutes,source_exam_id,request_id) VALUES(?,?,?,0,?,?,?,?)', (eid,json.dumps(payload),deadline,created,minutes,source,request_id))
            return {'id':eid, 'ids':payload['ids'], 'deadline':deadline, 'server_time':time.time()}, []
        if method == 'GET' and path == '/api/exam/result':
            with self.db('exams') as db:
                row = db.execute('SELECT finished FROM exams WHERE id=?', (args.get('id', ''),)).fetchone()
            if not row:
                raise ApiError('试卷不存在', 404)
            if not row['finished']:
                raise ApiError('试卷尚未完成', 409)
            return self.route_exams('POST', '/api/exam/finish', {}, {'id':args['id']}, env, user)
        if method == "POST" and path == "/api/exam/start":
            if self.active_exam():
                raise ApiError("请先完成当前考试")
            size = body.get("count", 10)
            minutes = body.get("minutes", 30)
            if type(size) is not int or not 1 <= size <= 50 or type(minutes) is not int or not 1 <= minutes <= 180:
                raise ApiError("题数须为 1–50 整数，时长须为 1–180 整数")
            filters = body.get("filters", {})
            if not isinstance(filters, dict):
                raise ApiError("filters 必须为对象")
            if filters.get("type") == "generated":
                from bank import generator
                from bank.review import normalize
                module = filters.get("module")
                templates = [t for t in generator.TEMPLATES
                             if (not module or module in normalize(generator.generate(t['id'], 'template'))['related_modules'])
                             and (not filters.get('level') or int(filters['level']) == (3 if t['difficulty'] == '进阶' else 1))]
                if not templates:
                    raise ApiError("该模块和强度没有随机题模板")
                for _ in range(size):
                    q = generator.generate(secrets.choice(templates)['id'], secrets.token_hex(8))
                    q.update(level=3 if q['difficulty'] == '进阶' else 1, body="参数化变式题：填写答案后提交。")
                    self.putq(normalize(q))
            pool = self.exam_candidate_ids(filters)
            if not pool:
                raise ApiError("没有符合条件的可考试题目；非文字面试题必须先配置并审校自动判题器")
            import random
            selected = [self.getq(qid) for qid in random.SystemRandom().sample(pool, min(size, len(pool)))]
            # A new paper must not inherit a completed practice workspace.
            self.reset_question_labs([q['id'] for q in selected], skip_empty=True)
            eid = secrets.token_hex(10)
            payload = {"ids": [q["id"] for q in selected], "snapshots": selected, "drafts": {}}
            deadline = time.time() + minutes * 60
            with self.db("exams") as db:
                db.execute("INSERT INTO exams(id,payload,deadline,finished,created,duration_minutes) VALUES(?,?,?,0,?,?)", (eid, json.dumps(payload), deadline, time.time(), minutes))
            return {"id": eid, "ids": payload["ids"], "deadline": deadline, "server_time": time.time()}, []

        if method == "POST" and path == "/api/exam/finish":
            eid = body.get("id")
            if not isinstance(eid, str) or not eid:
                raise ApiError("交卷必须指定试卷 ID，请刷新客户端", 409)
            with self.db("exams") as db:
                row = db.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
            if not row:
                raise ApiError("试卷不存在", 404)
            exam = dict(row)
            if body.get("automatic") and not exam['finished'] and time.time() < exam['deadline']:
                raise ApiError("服务端尚未到交卷时间，请同步倒计时", 409)
            # Freeze answers and results before crossing the database boundary.
            # If a later write fails, a retry reuses this snapshot and event keys.
            payload = json.loads(exam["payload"])
            if exam['finished']:
                attempts = {a['id']: a for a in self.exam_attempts(eid)}
                results = [attempts[q['id']] for q in payload['snapshots'] if q['id'] in attempts]
                return report(eid, payload, results), []
            if "deliveries" not in payload:
                if 'submission_started_at' not in payload:
                    payload['submission_started_at'] = time.time()
                    payload['late'] = payload['submission_started_at'] > exam['deadline']
                    with self.db('exams') as db:
                        db.execute('UPDATE exams SET payload=? WHERE id=?', (json.dumps(payload), eid))
                deliveries = []
                for q in payload["snapshots"]:
                    draft = payload.get('drafts', {}).get(q['id'], {'text':'', 'files':q.get('files', {}), 'revision':0})
                    answer = draft.get('text', '')
                    cached = payload.get('checks', {}).get(q['id'], {})
                    reusable = cached and cached['revision'] == draft.get('revision', 0)
                    if reusable and (q.get('exercise') or q['type'] == 'scenario'):
                        workspace = self.exam_lab_revision(q['id'], exam['created'] or 0)
                        # A destroyed lab may retain its completed snapshot. A later
                        # command, file upload or reset must invalidate the old result.
                        reusable = workspace is None or workspace == cached['result'].get('workspace_revision')
                    if reusable:
                        result = cached['result']
                    else:
                        try:
                            result = self.grade_exam_answer(q, draft, exam['created'] or 0)
                        except ApiError as error:
                            result = {'passed': None, 'method': '待判分', 'stage': 'execution_unavailable',
                                      'message': '验收未完成，未按错题扣分：' + str(error)}
                    deliveries.append({"question": q, "answer": answer, "result": result,
                                       "submission": {"files": draft.get('files', {}), "notes": draft.get('notes', ''),
                                                      "draft_revision": draft.get('revision', 0), "scope": 'exam:' + eid}})
                payload["deliveries"] = deliveries
                with self.db("exams") as db:
                    db.execute("UPDATE exams SET payload=? WHERE id=?", (json.dumps(payload), exam["id"]))
            results = []
            for item in payload["deliveries"]:
                q, answer, result = item["question"], item["answer"], item["result"]
                attempt_id = self.record(q, answer, result, event_key="exam:" + exam["id"] + ":" + q["id"], submission=item.get('submission'))
                results.append({"id": q["id"], "title": q["title"], "attempt_id": attempt_id, **result})
            payload.setdefault('late', payload.get('submission_started_at', time.time()) > exam['deadline'])
            with self.db("exams") as db:
                db.execute("UPDATE exams SET finished=1,payload=? WHERE id=?", (json.dumps(payload), exam["id"]))
            return report(eid, payload, results), []
        return None
