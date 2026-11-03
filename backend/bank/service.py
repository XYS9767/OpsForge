"""The bank domain: owned state transitions and API handlers."""
import hashlib
import json
import secrets
import time
from collections import Counter
from pathlib import Path
from . import catalog as curriculum, extensions as bank_extensions, code_tasks, generator
from labs import scenarios
from . import schema, verified, study, oral, taxonomy, formats
from .review import normalize, require_published
from .course_scope import removed as removed_from_course
ROOT = Path(__file__).resolve().parents[1]
from core.errors import ApiError
from core.text import validate_payload_text
from core.question_identity import content_key


class BankService:
    def question_labels(self, ids):
        if not isinstance(ids, list) or len(ids) > 200 or any(not isinstance(i, str) for i in ids):
            raise ApiError('题目标签查询格式错误')
        if not ids:
            return {}
        with self.db('bank') as db:
            rows = db.execute('SELECT id,payload FROM questions WHERE id IN (' + ','.join('?' for _ in ids) + ')', ids).fetchall()
        return {r['id']: {k: json.loads(r['payload']).get(k, '') for k in ('title', 'category')} for r in rows if not removed_from_course(json.loads(r['payload']))}

    def question_states(self, questions=None):
        questions = self.allq() if questions is None else questions
        states = self.learning_states(content_keys={q['id']: content_key(q) for q in questions})
        for qid in self.lab_progress():
            item = states.setdefault(qid, {'completion':'not_started', 'mastery':'unrated'})
            if item['completion'] == 'not_started':
                item['completion'] = 'in_progress'
        states.update(self.exam_states())
        return states

    def with_states(self, questions, states=None):
        states = self.question_states(questions) if states is None else states
        return [{**q, 'learning':states.get(q['id'], {'completion':'not_started', 'mastery':'unrated'})} for q in questions]

    def seed(self):
        bank = json.loads((ROOT / "data/bank.json").read_text(encoding="utf-8"))
        self.bank_meta = bank["meta"]
        candidates = []
        for q in bank["questions"]:
            q.setdefault("level", 3 if q["difficulty"] == "进阶" else 1)
            q.setdefault("body", "先尝试用自己的话回答，再展开原始资料中的参考答案。原始答案未逐题审校。")
            q.setdefault("version", 1)
            candidates.append(q)
        candidates.extend(oral.apply(curriculum.questions() + code_tasks.questions() + bank_extensions.questions(curriculum.MODULES) + verified.questions()))
        candidates.extend(scenarios.create(entry[0], "beginner") for entry in scenarios.CATALOG)
        curated_path = ROOT / "data/curated-questions.json"
        if curated_path.exists():
            curated = json.loads(curated_path.read_text(encoding="utf-8"))
            schema.prepare(curated)
            for q in curated:
                if not q["id"].startswith("curated-") or q.get("review_status") != "reviewed" or not q.get("answer", "").strip():
                    raise ValueError("随包审校题必须具有独立编号、参考答案和审校状态")
            candidates.extend(curated)
        from .seeding import synchronize, retire_duplicates
        from .hands_on import catalog
        # A reviewed practical rewrite retains the original ID and history.
        # Override the builtin before synchronization, not after a duplicate ID
        # has already been skipped. Locally edited questions remain protected
        # by synchronize's fingerprint conflict check.
        practical = catalog()
        candidates = [practical.get(q['id'], q) for q in candidates]
        candidate_ids = {q['id'] for q in candidates}
        candidates.extend(q for qid, q in practical.items() if qid not in candidate_ids)
        retirements = ROOT / 'data/retired-duplicates.json'
        if retirements.exists():
            candidates = retire_duplicates(candidates, json.loads(retirements.read_text(encoding='utf-8')))
        candidates = [q for q in candidates if not removed_from_course(q)]
        validate_payload_text(candidates)
        legacy = json.loads((ROOT / "data/builtin-baseline.json").read_text(encoding="utf-8"))
        with self.db("bank") as db:
            self.bank_meta['upgrade'] = synchronize(db, candidates, legacy)


    def getq(self, qid):
        with self.db("bank") as db:
            row = db.execute("SELECT payload FROM questions WHERE id=?", (qid,)).fetchone()
        if not row or removed_from_course(json.loads(row[0])):
            raise ApiError("题目不存在", 404)
        return normalize(json.loads(row[0]))


    def putq(self, q):
        if removed_from_course(q):
            raise ApiError("该模块已按用户要求移出课程", 400)
        with self.db("bank") as db:
            db.execute("INSERT INTO questions(id,payload) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (q["id"], json.dumps(normalize(q), ensure_ascii=False)))
        return q


    @staticmethod
    def public(q):
        if removed_from_course(q):
            raise ApiError("题目已移出课程", 404)
        from .hands_on import PRIVATE_FIELDS, manual_artifact_contract
        from .assessment import capable
        kind = formats.classify(q)
        private = {"answer", "explanation", "grading", "state", "hints"} | PRIVATE_FIELDS
        if kind in ('single_choice', 'multiple_choice', 'true_false', 'fill_blank'):
            private.add('rubric')
        return {**{k: v for k, v in q.items() if k not in private},
                'automatic_grading': capable(q), 'question_format': kind,
                'manual_artifact_review': manual_artifact_contract(q)}


    def allq(self):
        with self.db("bank") as db:
            return [q for r in db.execute("SELECT payload FROM questions") if not removed_from_course(q := normalize(json.loads(r[0])))]


    def filtered(self, query):
        qs = [q for q in self.allq() if q["review_status"] == query.get("review", "reviewed")]
        if any(query.get(key) for key in ("group", "submodule", "topic_id", "primary_module")):
            qs = [q for q in qs if taxonomy.matches(q, query)]
        if query.get("module"):
            module = query["module"]
            name = next((x["name"] for x in curriculum.modules() if x["id"] == module), module)
            qs = [q for q in qs if module in q.get("related_modules", []) or q["category"] == name]
        if query.get("category"):
            qs = [q for q in qs if q["category"] == query["category"]]
        if query.get("type"):
            qs = [q for q in qs if q["type"] == query["type"]]
        if query.get('format'):
            if query['format'] not in formats.FORMATS:
                raise ApiError('未知题型')
            qs = [q for q in qs if formats.classify(q) == query['format']]
        if query.get("level"):
            qs = [q for q in qs if int(q.get("level", 1)) == int(query["level"])]
        if query.get("search"):
            term = query["search"].casefold()
            qs = [q for q in qs if term in (q["title"] + " " + q["category"] + " " + taxonomy.placement(q)["topic"] + " " + " ".join(q.get("tags", []))).casefold()]
        if query.get("favorite") == "1":
            ids = self.favorite_ids()
            qs = [q for q in qs if q["id"] in ids]
        if query.get("wrong") == "1":
            query = {**query, 'mastery':'review'}
        if query.get('completion') or query.get('mastery'):
            states = self.question_states(qs)
            for field, allowed, default in [('completion', ('not_started','in_progress','submitted'), 'not_started'), ('mastery', ('unrated','mastered','review'), 'unrated')]:
                value = query.get(field)
                if value:
                    if value not in allowed:
                        raise ApiError('无效的学习状态筛选')
                    qs = [q for q in qs if states.get(q['id'], {}).get(field, default) == value]
        priority = {"scenario": 0, "practice": 1, "code": 2, "interview": 3, "case": 4, "generated": 5, "source": 6}
        qs.sort(key=lambda q: (priority.get(q["type"], 5), q["category"], q["title"]))
        return qs


    def exam_candidate_ids(self, query):
        from .assessment import capable
        return [q['id'] for q in self.filtered({**query, 'review': 'reviewed'})
                if q['type'] == 'interview' or capable(q)]

    def route_bank(self, method, path, args, body, env, user):
        if method == "GET" and path == "/api/curriculum":
            return taxonomy.build(self.with_states(self.filtered({**args, "review": "reviewed"}))), []
        if method == "GET" and path in ["/api/study", "/api/study/export"]:
            questions = self.filtered({**args, "review": "reviewed", "type": "interview"})
            total, offset, cursor = len(questions), 0, None
            if args.get('paged') == '1':
                questions.sort(key=lambda q: q['id'])
                after = args.get('after', '')
                offset = sum(q['id'] <= after for q in questions)
                batch, size = [], 0
                for q in questions[offset:]:
                    length = len(json.dumps(q, ensure_ascii=False).encode('utf-8'))
                    if batch and (len(batch) >= 1000 or size + length > 4_000_000):
                        break
                    batch.append(q); size += length
                cursor = batch[-1]['id'] if batch and offset + len(batch) < total else None
                questions = batch
            if path.endswith("/export"):
                if self.active_exam():
                    raise ApiError("考试进行中，交卷后才能导出包含答案的背题文档", 409)
                result = {"filename": "OpsForge_口述题背题册.md", "count": total,
                          "content": study.markdown(questions, total=total, start=offset, header=offset == 0), 'next': cursor}
                if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 16_000_000:
                    raise ApiError('背题资料较大，请刷新客户端后使用分段导出', 413)
                return result, []
            favorites = self.favorite_ids()
            result = {"count": total, "items": [{**self.public(q), "favorite": q["id"] in favorites} for q in self.with_states(questions)], 'next': cursor}
            if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 16_000_000:
                raise ApiError('背题列表较大，请刷新客户端后分段读取', 413)
            return result, []
        if method == "GET" and path == "/api/bootstrap":
            all_questions = self.allq()
            qs = [q for q in all_questions if q["review_status"] == "reviewed"]
            summary = self.learning_summary()
            states = self.question_states(qs)
            qs = self.with_states(qs, states)
            attempts, saved, latest = summary["attempt_count"], summary["favorites"], summary["latest"]
            mods = curriculum.modules()
            for m in mods:
                subset = [q for q in qs if m["id"] in q.get("related_modules", []) or q["category"] == m["name"]]
                m.update(count=len(subset), levels=sorted({q.get("level", 1) for q in subset}),
                         types=dict(Counter(q["type"] for q in subset)),
                         mastered=sum(q['learning']['mastery'] == 'mastered' for q in subset))
            exam = self.active_exam()
            if exam:
                exam["payload"] = json.dumps({"ids": json.loads(exam["payload"])["ids"]})
            return {"csrf": user["csrf"], "count": len(qs), "total_count": len(all_questions),
                    "pending_count": sum(q['review_status'] == 'pending' for q in all_questions),
                    "retired_count": sum(q['review_status'] == 'retired' for q in all_questions),
                    "database": self.database.kind, "modules": mods, "curriculum": taxonomy.build(qs),
                    "categories": dict(Counter(q["category"] for q in qs)), "source_meta": self.bank_meta,
                    "templates": generator.TEMPLATES, "scenarios": [{"id": x[0], "name": x[1], "tags": x[2]} for x in scenarios.CATALOG],
                    "runtime": self.runtime_status(), "stats": {"attempts": attempts, "mastered": sum(q['learning']['mastery'] == 'mastered' for q in qs), "favorites": saved},
                    "exam": exam, "server_time": time.time()}, []

        if method == "GET" and path == "/api/question/edit":
            q = self.getq(args["id"])
            self.ensure_answer_allowed(q["id"])
            return {"question": q}, []

        if method == "GET" and path == "/api/questions":
            qs = self.filtered(args)
            page, size = max(1, int(args.get("page", 1))), min(100, max(1, int(args.get("size", 30))))
            return {"total": len(qs), "items": [self.public(q) for q in self.with_states(qs[(page-1)*size:page*size])], "page": page}, []

        if method == "GET" and path == "/api/question":
            q = self.exam_question(args['id']) or self.getq(args['id'])
            draft, viewed = self.draft_details(q)
            return {"question": self.public(self.with_states([q])[0]), "draft": draft, "views": viewed, "hint_count": len(q.get("hints", []))}, []
        if method == "POST" and path == "/api/random":
            mode = body.get("mode", "bank")
            seed = secrets.token_hex(5)
            if mode == "generated":
                template = body.get("template") or secrets.choice(generator.TEMPLATES)["id"]
                q = generator.generate(template, seed)
                q["level"] = 3 if q["difficulty"] == "进阶" else 1
                q["body"] = "参数化变式题：填写答案后提交，参考答案默认隐藏。"
            elif mode == "scenario":
                q = scenarios.create(body.get("scenario") or secrets.choice(scenarios.CATALOG)[0], seed)
            else:
                pool = self.filtered({**body.get("filters", {}), "review": "reviewed"})
                if not pool:
                    raise ApiError("当前筛选条件下没有题目")
                q = secrets.choice(pool)
            self.putq(normalize(q))
            return self.public(q), []

        if method == "POST" and path in ["/api/answer", "/api/hint"]:
            q = self.getq(body["id"])
            if int(body.get("version", q.get("version", 1))) != q.get("version", 1):
                raise ApiError("题目已更新，请重新打开题目后查看对应答案", 409)
            self.ensure_answer_allowed(q["id"])
            kind = "answer" if path.endswith("answer") else "hint"
            self.mark_view(q["id"], kind)
            if kind == "answer":
                return {"id": q["id"], "version": q.get("version", 1), "answer": q.get("answer") or "原始资料未提供答案，请补充审校后再使用。",
                        "explanation": q.get("explanation", ""), "rubric": q.get("rubric", []),
                        "notice": "待审校的资料答案，可能错误；此内容不参与练习或考试。" if q["review_status"] != "reviewed" else "",
                        "references": q.get("references", []), "review_status": q["review_status"]}, []
            index = max(0, int(body.get("index", 0)))
            hints = (q.get("hints") or ["先确认概念与目标，列出已知条件，尝试独立作答。"])
            return {"hint": hints[min(index, len(hints)-1)], "total": len(hints)}, []

        if method == "GET" and path == "/api/export":
            if self.active_exam():
                raise ApiError("考试进行中，交卷后可导出包含参考答案的题库", 409)
            if args.get('mode') == 'transfer' and args.get('section'):
                if args['section'] != 'questions':
                    raise ApiError('迁移导出只包含自定义题目')
                from core.archive import page
                with self.db('bank') as db:
                    return page(db, 'questions', args.get('after', ''), args.get('through'), decode_payload=True, custom_only=True), []
            if args.get('mode') == 'archive' and args.get('section'):
                section, after, through = args['section'], args.get('after', ''), args.get('through')
                if section == 'questions':
                    from core.archive import page
                    with self.db('bank') as db:
                        return page(db, section, after, through, decode_payload=True), []
                return self.learning_export_page(section, after, through), []
            questions = self.allq()
            if args.get("mode") != "archive":
                transferable = [q for q in questions if q["id"].startswith("custom-")]
                if len(json.dumps(transferable, ensure_ascii=False).encode('utf-8')) > 16_000_000:
                    raise ApiError('资料较大，请使用新版页面的分片题库迁移导出', 413)
                return {"format": "opsforge-transfer-v1", "questions": transferable,
                        "excluded_count": len(questions) - len(transferable),
                        "note": "迁移自定义题目；导入后进入待审区。内置题随安装提供，随机变式及学习记录请另存完整资料归档或备份数据库。"}, []
            archive = {"format": "opsforge-archive-v1", "questions": questions,
                       "note": "资料归档仅供查阅；完整恢复请使用数据库备份。"}
            size = len(json.dumps(archive, ensure_ascii=False).encode('utf-8'))
            for section in ('drafts', 'attempts', 'favorites'):
                archive[section] = []
                after, through = '', None
                while True:
                    part = self.learning_export_page(section, after, through)
                    size += len(json.dumps(part['items'], ensure_ascii=False).encode('utf-8'))
                    if size > 16_000_000:
                        raise ApiError('资料较大，请使用新版页面的分片完整资料归档', 413)
                    archive[section].extend(part['items'])
                    after, through = part['next'], part['through']
                    if after is None:
                        break
            return archive, []

        if method == "POST" and path in ["/api/import", "/api/import/preview"]:
            if body.get("format", "opsforge-bank-v1") not in ["opsforge-bank-v1", "opsforge-transfer-v1"]:
                raise ApiError("题库格式版本不受支持")
            items = body.get("questions", [])
            prepared = [] if body.get("format") == "opsforge-transfer-v1" and items == [] else schema.prepare(items)
            active = self.active_exam()
            exam_ids = set(json.loads(active["payload"])["ids"]) if active else set()
            if any(q["id"] in exam_ids for q in prepared):
                raise ApiError("本批次有题目正在考试中，交卷后才能更新", 409)
            created, updated = 0, 0
            with self.db("bank") as db:
                for q in prepared:
                    old = db.execute("SELECT payload FROM questions WHERE id=?", (q["id"],)).fetchone()
                    expected = q.pop("_expected_version", None)
                    if old:
                        if expected != json.loads(old[0]).get("version", 1):
                            raise ApiError("更新已有题目必须提供当前 version，防止旧文件覆盖新答案：" + q["id"], 409)
                        updated += 1
                        q["version"] = json.loads(old[0]).get("version", 1) + 1
                    else:
                        created += 1
                    if path.endswith("/preview"):
                        continue
                    if old:
                        db.execute("INSERT INTO revisions(qid,payload,created) VALUES(?,?,?)", (q["id"], old[0], time.time()))
                    db.execute("INSERT INTO questions(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (q["id"], json.dumps(q, ensure_ascii=False)))
            return {"imported": 0 if path.endswith("/preview") else len(prepared),
                    "created": created, "updated": updated, "pending": len(prepared),
                    "ids": [q["id"] for q in prepared], "note": "整批通过结构校验；内容需审校后发布。"}, []
        if method == "POST" and path == "/api/review":
            q = self.getq(body["id"])
            self.ensure_answer_allowed(q["id"])
            if body.get("version") != q.get("version", 1):
                raise ApiError("题目已变化，请重新核对当前版本", 409)
            if not q["id"].startswith("custom-"):
                raise ApiError("原始资料和内置题保留不变；请先编辑副本，再审校副本")
            if not q.get("answer", "").strip():
                raise ApiError("没有参考答案，不能发布")
            note = str(body.get("note", "")).strip()
            if len(note) < 12:
                raise ApiError("请填写至少 12 字的核对依据，例如版本、验证方法或官方资料")
            old_payload = json.dumps(q, ensure_ascii=False)
            q.update(review_status="reviewed", review_note=note[:3000],
                     reviewed_at=time.time(), version=q.get("version", 1)+1)
            with self.db("bank") as db:
                db.execute("INSERT INTO revisions(qid,payload,created) VALUES(?,?,?)", (q["id"], old_payload, time.time()))
                db.execute("UPDATE questions SET payload=? WHERE id=?", (json.dumps(q, ensure_ascii=False), q["id"]))
            return {"id": q["id"], "version": q["version"], "review_status": "reviewed"}, []
        if method == "GET" and path == "/api/revisions":
            q = self.getq(args["id"])
            self.ensure_answer_allowed(q["id"])
            with self.db("bank") as db:
                rows = db.execute("SELECT payload,created FROM revisions WHERE qid=? ORDER BY id DESC", (q["id"],)).fetchall()
            return {"id": q["id"], "versions": [{"question": json.loads(r[0]), "created": r[1]} for r in rows]}, []
        return None
