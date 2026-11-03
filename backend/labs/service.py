"""The labs domain: owned state transitions and API handlers."""
import json
import secrets
import time
from contextlib import contextmanager
from . import scenarios
from core.errors import ApiError
from bank.review import require_published


class LabService:
    def lab_question(self, qid):
        # Retakes use the frozen paper, including its initial files and scenario.
        return self.exam_question(qid) or self.getq(qid)

    def _exam_lab(self, qid, created):
        with self.db('labs') as db:
            rows = db.execute('SELECT id FROM labs WHERE qid=? AND created>=? ORDER BY created DESC',
                              (qid, created)).fetchall()
        return self.lab(rows[0]['id']) if rows else None

    def exam_lab_revision(self, qid, created):
        lab = self._exam_lab(qid, created)
        with self.db('labs') as db:
            stopped = db.execute('SELECT * FROM stopped_lab_revisions WHERE qid=? AND created>=?',
                                 (qid, created)).fetchone()
        if stopped and (not lab or stopped['created'] >= lab['created']):
            return stopped['lab_id'] + ':' + str(stopped['revision'])
        return (lab['id'] + ':' + str(lab['payload'].get('command_revision', 0))) if lab else None

    def grade_exam_lab(self, question, created, files):
        lab = self._exam_lab(question['id'], created)
        revision = (lab['id'] + ':' + str(lab['payload'].get('command_revision', 0))) if lab else self.exam_lab_revision(question['id'], created)
        if self.exam_lab_revision(question['id'], created) != revision:
            raise ApiError('验收开始前实验发生变化，请重新验收', 409)
        if question.get('exercise'):
            result = self.grade_artifact_submission(lab['id'] if lab else None, question, files)
        elif not lab:
            result = {'passed': False, 'method': '状态验收', 'message': '本次考试未创建并完成此题实验。'}
        elif lab['mode'] == 'simulation':
            result = {**scenarios.check(lab['payload']), 'method': '状态验收'}
        else:
            result = self.grade_real_lab(lab['id'], question)
        if self.exam_lab_revision(question['id'], created) != revision:
            raise ApiError('验收期间实验发生变化，请重新验收', 409)
        return {**result, 'workspace_revision': revision}

    def grade_artifact_submission(self, sid, question, files):
        from bank.hands_on import inspect_artifacts, program_contract, execution_bundle, distributed_contract, cluster_contract, manual_artifact_contract
        from core.files import validate_files
        current = question
        result = inspect_artifacts(current, files)
        if result['passed'] is False:
            return result
        assessment = program_contract(current)
        if not assessment:
            if manual_artifact_contract(current):
                return {**result, 'passed': None, 'method': '人工审核',
                        'stage': 'awaiting_manual_review',
                        'message': '产物已保存，待人工审核；保存或自评不代表独立审核通过。'}
            return {**result, 'message': '产物已保存，当前题尚无已审校的执行验收器；请按题目步骤验收并提交证据。'}
        if not sid:
            return {**result, 'message': '产物检查通过，请在网页创建真实隔离工作区后提交执行验收。'}
        with self.exclusive_lab_operation():
            lab = self.lab(sid)
            if lab['qid'] != current['id'] or lab['mode'] != 'real':
                raise ApiError('产物验收需要本题的真实隔离工作区', 409)
            if current.get('exercise', {}).get('workspace') == 'docker' and lab['payload'].get('environment') != 'docker':
                raise ApiError('本题需要专用 Docker 工作区，请重新选择真实 Docker 环境', 409)
            if cluster_contract(current) and (lab['payload'].get('environment') != 'cluster'
                                             or lab['payload'].get('resource_profile') == 'distributed'):
                raise ApiError('本题需要独立 Kubernetes 集群工作区，请重新创建', 409)
            if distributed_contract(current) and lab['payload'].get('resource_profile') != 'distributed':
                raise ApiError('本题需要高内存分布式服务工作区，请重新创建', 409)
            tests = execution_bundle(current, assessment)
            if any(name in files for name in tests):
                raise ApiError('验收文件由平台提供，不能作为提交产物覆盖')
            upload = {**files, **tests}
            validate_files(upload)
            pod = lab['payload']['pod']
            written = self.runtime.write_files(pod, upload)
            if written['exit_code'] != 0:
                raise ApiError('同步验收产物失败；未进行执行评分', 503)
            token = secrets.token_hex(24)
            outcome = self.runtime.command(pod, 'python3 checks/_opsforge_runner.py ' + token,
                                           '/workspace', min(120, assessment.get('timeout', 30) + 10))
            prefix = '__OPSF_VERDICT_' + token + '__'
            verdict = None
            for line in outcome.get('output', '').splitlines():
                if line.startswith(prefix):
                    try:
                        verdict = json.loads(line[len(prefix):])
                    except ValueError:
                        pass
            if isinstance(verdict, dict) and verdict.get('error'):
                raise ApiError('实验验收器无法运行，请检查工作区工具和验收配置；本次未判错', 503)
            if verdict is None and outcome.get('exit_code') in (124, 126, 127):
                raise ApiError('实验验收连接超时或运行工具不可用；本次未判错', 503)
            passed = (outcome['exit_code'] == 0 and isinstance(verdict, dict)
                      and verdict.get('passed') is True and verdict.get('completed') is True)
            return {**result, 'passed': passed, 'method': '实验执行验收',
                    'stage': 'execution_passed' if passed else 'execution_failed',
                    'checks': result['checks'] + [{'label': '通过本题已审校的执行测试', 'passed': passed}],
                    'message': '本次提交通过题内执行测试。' if passed else '执行测试未通过或未完整执行，请检查产物和运行输出。',
                    'output': (verdict.get('output', '') if isinstance(verdict, dict) else outcome.get('output', ''))[:6000]}

    def lab_progress(self):
        with self.db('labs') as db:
            rows = db.execute('SELECT qid,mode,payload FROM labs').fetchall()
        return list({r['qid'] for r in rows if r['mode'] == 'real' or json.loads(r['payload']).get('history')})

    def reset_question_labs(self, qids, skip_empty=False):
        if skip_empty:
            with self.db('labs') as db:
                present = any(row['qid'] in qids for row in db.execute('SELECT qid FROM labs'))
            if not present:
                return {'reset': True}
        with self.exclusive_lab_operation():
            with self.db('labs') as db:
                rows = [dict(r) for r in db.execute('SELECT * FROM labs') if r['qid'] in qids]
            for row in rows:
                if row['mode'] == 'real' and not self.runtime.stop(json.loads(row['payload'])['pod']):
                    raise ApiError('旧工作区仍在清理，请稍后重试；作答尚未清空', 409)
            with self.db('labs') as db:
                for row in rows:
                    db.execute('DELETE FROM labs WHERE id=?', (row['id'],))
        return {'reset':True}

    def runtime_status(self):
        return self.runtime.status()

    def grade_real_lab(self, sid, q):
        lab = self.lab(sid)
        if lab["qid"] != q["id"] or lab["mode"] != "real" or q["type"] != "scenario":
            raise ApiError("实验与题目不匹配", 409)
        with self.exclusive_lab_operation():
            return self.runtime.check_scenario(lab["payload"]["pod"], q)

    def load_runtime_state(self):
        with self.db("labs") as db:
            row = db.execute("SELECT payload FROM runtime_state WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}

    def save_runtime_state(self, state):
        with self.db("labs") as db:
            db.execute("INSERT INTO runtime_state(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (json.dumps(state),))

    @contextmanager
    def exclusive_lab_operation(self):
        if not self.lab_operation.acquire(blocking=False):
            raise ApiError("工作区正在执行操作，请等待完成或销毁工作区以取消", 409)
        try:
            yield
        finally:
            self.lab_operation.release()

    def lab(self, sid):
        with self.db("labs") as db:
            row = db.execute("SELECT * FROM labs WHERE id=?", (sid,)).fetchone()
        if not row:
            raise ApiError("实验不存在，请重新创建", 404)
        row = dict(row)
        row["payload"] = json.loads(row["payload"])
        return row


    def save_lab(self, lab):
        with self.db("labs") as db:
            db.execute("UPDATE labs SET payload=? WHERE id=?", (json.dumps(lab["payload"]), lab["id"]))


    def route_labs(self, method, path, args, body, env, user):
        if method != "GET" and path.startswith("/api/lab") and path != "/api/lab/stop":
            with self.exclusive_lab_operation():
                return self._route_labs(method, path, args, body, env, user)
        return self._route_labs(method, path, args, body, env, user)

    def _route_labs(self, method, path, args, body, env, user):
        if method == "POST" and path == "/api/lab/start":
            q = self.lab_question(body["id"])
            require_published(q)
            requires_docker = q.get('exercise', {}).get('workspace') == 'docker'
            from bank.hands_on import distributed_contract, cluster_contract
            requires_distributed = distributed_contract(q)
            requires_cluster = cluster_contract(q)
            if body.get('resume') is True:
                existing, _ = self._route_labs('GET','/api/lab/current',{'qid':q['id']},{},env,user)
                if existing['lab']:
                    if requires_docker and existing['lab'].get('environment') != 'docker':
                        raise ApiError('旧工作区不满足本题的专用 Docker 环境要求，请明确选择重建', 409)
                    if requires_cluster and (existing['lab'].get('mode') != 'real'
                                             or existing['lab'].get('environment') != 'cluster'
                                             or existing['lab'].get('state', {}).get('resource_profile') == 'distributed'):
                        raise ApiError('旧工作区不满足本题的独立 Kubernetes 环境要求，请明确选择重建', 409)
                    if requires_distributed and existing['lab'].get('state', {}).get('resource_profile') != 'distributed':
                        raise ApiError('旧工作区资源不足，请明确选择重建分布式服务工作区', 409)
                    return existing['lab'], []
            mode = body.get("mode", "simulation")
            docker, cluster = body.get('docker', False), body.get('cluster', False)
            if not isinstance(docker, bool) or not isinstance(cluster, bool) or (docker and cluster):
                raise ApiError('请选择一种工作区类型，docker/cluster 必须为布尔值')
            if requires_docker and (mode != 'real' or not docker or cluster):
                raise ApiError('本题需要专用 Docker 工作区；请选择真实 Docker 环境', 409)
            if requires_cluster and (mode != 'real' or not cluster or docker or requires_distributed):
                raise ApiError('本题需要真实独立 Kubernetes 集群，不能使用模拟、普通或其他工作区', 409)
            if requires_distributed and (mode != 'real' or docker or cluster):
                raise ApiError('本题需要真实分布式服务工作区，不能使用模拟或其他工作区', 409)
            old = None
            if body.get('replace_id'):
                try:
                    old = self.lab(body['replace_id'])
                except ApiError as exc:
                    if exc.status != 404:
                        raise
                if old and old['qid'] != q['id']:
                    raise ApiError('不能替换其他题目的工作区', 409)
            environment = 'simulation' if mode == 'simulation' else 'cluster' if cluster else 'docker' if docker else 'real'
            sid = secrets.token_hex(12)
            def insert(payload):
                payload['environment'] = environment
                with self.db('labs') as db:
                    if mode == 'simulation':
                        db.execute("DELETE FROM labs WHERE mode='simulation' AND qid=?", (q['id'],))
                    db.execute('INSERT INTO labs VALUES(?,?,?,?,?)', (sid,q['id'],mode,json.dumps(payload),time.time()))
            if mode == 'simulation':
                if docker or cluster or q['type'] != 'scenario':
                    raise ApiError('此题没有状态模拟器，或所选环境参数不一致')
                payload = q['state'].copy()
                insert(payload)
            elif mode == 'real':
                status = self.runtime.status()
                if requires_distributed and not status.get('distributed_enabled'):
                    raise ApiError('高内存分布式服务实验未启用；原工作区保持不变', 409)
                if not status['enabled'] or (docker and not status['docker_enabled']) or (cluster and not status['cluster_enabled']):
                    raise ApiError('所选真实实验未启用；原工作区保持不变', 409)
                if q['type'] == 'scenario':
                    kind = q['state']['kind']
                    if kind not in ('permissions','service','docker'):
                        raise ApiError('此题支持网页场景模拟，尚无对应的真实故障初始化器')
                    if kind == 'docker' and not docker:
                        raise ApiError('此题需要真实 Docker 工作区')
                    if kind == 'service' and (docker or cluster):
                        raise ApiError('此题需要受限的 Linux / kubectl / Helm 工作区')
                try:
                    with self.runtime.prepared_start(docker, cluster, q, old['payload']['pod'] if old and old['mode']=='real' else None) as payload:
                        insert(payload)
                except Exception:
                    with self.db('labs') as db:
                        db.execute('DELETE FROM labs WHERE id=?',(sid,))
                    raise
            else:
                raise ApiError('未知实验模式')
            cleanup_pending = False
            if old and old['id'] != sid:
                if old['mode']=='real' and mode=='simulation':
                    try:
                        cleanup_pending = not self.runtime.stop(old['payload']['pod'])
                    except Exception:
                        cleanup_pending = True
                with self.db('labs') as db:
                    if not cleanup_pending:
                        db.execute('DELETE FROM labs WHERE id=?',(old['id'],))
            return {'id':sid,'mode':mode,'environment':environment,'state':payload,'ready':True,
                    'cleanup_pending':cleanup_pending,'checks':scenarios.check(payload) if mode=='simulation' else None}, []

        if method == 'GET' and path == '/api/lab/current':
            with self.db('labs') as db:
                row = db.execute('SELECT id FROM labs WHERE qid=? ORDER BY created DESC LIMIT 1',(args['qid'],)).fetchone()
            if row is None:
                return {'lab':None}, []
            try:
                result, _ = self._route_labs('GET','/api/lab',{'id':row['id']},{},env,user)
                return {'lab':result}, []
            except ApiError as exc:
                if exc.status != 404:
                    raise
                return {'lab':None}, []

        if method == "GET" and path == "/api/lab/status":
            lab = self.lab(args["id"])
            result = self.runtime.poll(lab["payload"]["pod"]) if lab["mode"] == "real" else {"phase": "Ready", "ready": True, "checks": scenarios.check(lab["payload"])}
            if lab["mode"] == "real" and result["ready"] and not lab["payload"].get("initialized", True):
                # Status reads stay available during exec; initialization still mutates
                # the workspace and must share the command/start operation lock.
                if not self.lab_operation.acquire(blocking=False):
                    result.update(ready=False, reason="工作区正在执行操作，稍后重试场景初始化")
                else:
                    try:
                        lab = self.lab(args["id"])
                        if not lab["payload"].get("initialized", True):
                            setup = self.runtime.setup_scenario(lab["payload"]["pod"], self.lab_question(lab["qid"]))
                            if setup["exit_code"]:
                                result.update(ready=False, reason="场景初始化尚未完成：" + setup["output"][-1000:])
                            else:
                                lab["payload"]["initialized"] = True
                                self.save_lab(lab)
                    finally:
                        self.lab_operation.release()
            return result, []

        if method == "GET" and path == "/api/lab":
            lab = self.lab(args["id"])
            ready = True
            if lab["mode"] == "real":
                ready = self.runtime.poll(lab["payload"]["pod"]).get('ready',False) and lab['payload'].get('initialized',True)
            return {"id": lab["id"], "qid": lab["qid"], "mode": lab["mode"], "state": lab["payload"],
                    "ready":ready,
                    "environment": lab['payload'].get('environment', 'simulation' if lab['mode'] == 'simulation' else 'unknown' if lab['payload'].get('namespace') == self.runtime.docker_namespace else 'real'),
                    "checks": scenarios.check(lab["payload"]) if lab["mode"] == "simulation" else None}, []

        if method == "POST" and path == "/api/lab/command":
            lab = self.lab(body["id"])
            command = str(body.get("command", ""))
            if lab["mode"] == "simulation":
                with self.lock:
                    lab = self.lab(body["id"])
                    state, output = scenarios.execute(lab["payload"], command)
                    state['command_revision'] = lab['payload'].get('command_revision', 0) + 1
                    lab["payload"] = state
                    self.save_lab(lab)
                return {"output": output, "state": state, "checks": scenarios.check(state)}, []
            timeout = min(120, max(1, int(body.get("timeout", 20))))
            lab['payload']['command_revision'] = lab['payload'].get('command_revision', 0) + 1
            self.save_lab(lab)
            result = self.runtime.command(lab["payload"]["pod"], command, lab["payload"].get("cwd", "/workspace"), timeout)
            lab["payload"]["cwd"] = result["cwd"]
            self.save_lab(lab)
            return result, []

        if method == "POST" and path == "/api/lab/files":
            lab = self.lab(body["id"])
            if lab["mode"] != "real":
                raise ApiError("代码运行需要真实隔离工作区；模拟终端不执行代码")
            from bank.hands_on import program_contract
            from core.files import validate_files
            files = body['files']
            validate_files(files)
            assessment = program_contract(self.lab_question(lab['qid']))
            if assessment:
                if set(files).intersection(assessment['test_files']):
                    raise ApiError('验收文件由平台提供，不能作为提交产物覆盖')
                files = {**files, **assessment['test_files']}
            lab['payload']['command_revision'] = lab['payload'].get('command_revision', 0) + 1
            self.save_lab(lab)
            result = self.runtime.write_files(lab["payload"]["pod"], files)
            return result, []

        if method == "POST" and path == "/api/lab/stop":
            lab = self.lab(body["id"])
            if lab["mode"] == "real":
                if not self.runtime.stop(lab["payload"]["pod"]):
                    return {"stopped": False, "pending": True}, []
            with self.db("labs") as db:
                db.execute('INSERT INTO stopped_lab_revisions(qid,lab_id,revision,created) VALUES(?,?,?,?) '
                           'ON CONFLICT(qid) DO UPDATE SET lab_id=excluded.lab_id,revision=excluded.revision,created=excluded.created '
                           'WHERE excluded.created>=stopped_lab_revisions.created',
                           (lab['qid'], lab['id'], lab['payload'].get('command_revision', 0), lab['created']))
                db.execute("DELETE FROM labs WHERE id=?", (lab["id"],))
            return {"stopped": True}, []

        return None
