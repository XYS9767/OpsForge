"""Import contract. Text content is data, never server code."""
import hashlib
import json
import re
from core.errors import ApiError
from .catalog import modules
from core.files import validate_files
from core.text import validate_payload_text


def prepare(items):
    from .course_scope import removed
    if not isinstance(items, list) or not 1 <= len(items) <= 10000:
        raise ApiError("questions 需要包含 1–10000 道题")
    result, ids = [], set()
    module_names = {x["id"]: x["name"] for x in modules()}
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ApiError(f"第 {index} 道题必须为对象")
        validate_payload_text(item)
        title = item.get("title", "")
        if removed(item):
            raise ApiError("该模块已按用户要求移出课程", 400)
        if not isinstance(title, str) or not title.strip() or len(title) > 5000:
            raise ApiError(f"第 {index} 道题需要 1–5000 字符 title")
        for field in ["category", "body", "answer", "explanation", "module", "run", "intro", "pack"]:
            if field in item and (not isinstance(item[field], str) or len(item[field]) > 100000):
                raise ApiError(f"第 {index} 道题的 {field} 必须是长度不超过 100000 的文本")
        category = item.get("category", "自定义")
        level = item.get("level", 1)
        if isinstance(level, bool) or not isinstance(level, int) or level not in range(6):
            raise ApiError(f"第 {index} 道题 level 必须为 0–5 整数")
        kind = item.get("type", "interview")
        if kind not in ["source", "practice", "interview", "case", "code"]:
            raise ApiError(f"第 {index} 道题不支持 type={kind}；导入不接受可执行判题器")
        ident = str(item.get("id") or hashlib.sha256((category + "\0" + title).encode()).hexdigest()[:20])
        qid = ident if ident.startswith("custom-") else "custom-" + ident
        if not re.fullmatch(r"custom-[A-Za-z0-9_:.-]{1,150}", qid):
            raise ApiError(f"第 {index} 道题 id 仅使用英文字母、数字、下划线、冒号、点和横线")
        if qid in ids:
            raise ApiError(f"批次内有重复题号 {qid}，整批未写入")
        ids.add(qid)
        q = {
            "id": qid, "title": title.strip(), "body": item.get("body", ""), "category": category,
            "type": kind, "level": level, "answer": item.get("answer", "").strip(),
            "explanation": item.get("explanation", ""),
            "source": "用户导入", "version": 1, "review_status": "pending",
            "review_note": "导入或更新后需要审校；没有自动批准外部答案。",
            "pack": item.get("pack", "custom"),
        }
        if "version" in item:
            if not isinstance(item["version"], int) or isinstance(item["version"], bool) or item["version"] < 1:
                raise ApiError("version 必须为正整数")
            q["_expected_version"] = item["version"]
        q["has_answer"] = bool(q["answer"])
        from .formats import prepare_metadata
        q.update(prepare_metadata(item))
        for field in ["hints", "rubric", "tags", "references"]:
            value = item.get(field, [])
            if not isinstance(value, list) or len(value) > 30 or any(not isinstance(x, str) or len(x) > 3000 for x in value):
                raise ApiError(f"第 {index} 道题 {field} 必须是最多 30 项的文本数组")
            q[field] = value
        if any(not re.match(r"^https://[^\s<>\"']+$", x) for x in q["references"]):
            raise ApiError("references 仅支持 HTTPS 资料链接")
        module = item.get("module") or next((slug for slug, name in module_names.items() if name == category), "")
        if module and module not in module_names:
            raise ApiError(f"未知模块 {module}，请使用 modules 接口中的模块编号")
        if module:
            q["module"] = module
        files = item.get("files", {})
        validate_files(files)
        q["files"] = files
        language = item.get("language", "")
        if isinstance(language, str):
            language = language.strip().lower()
        if language not in ["", "python", "go", "shell", "bash", "dockerfile", "yaml", "json", "text", "configuration"]:
            raise ApiError("language 需要为支持的代码语言标记")
        q["language"] = language
        q["run"] = item.get("run", "")
        q["intro"] = item.get("intro", "")
        if 'grading' in item:
            from .assessment import validate
            q['grading'] = validate(item['grading'])
        topic = item.get("topic", "")
        if not isinstance(topic, str) or len(topic) > 120 or any(ord(c) < 32 for c in topic):
            raise ApiError(f"第 {index} 道题 topic 必须为不超过120字的单行知识专题")
        q["topic"] = topic.strip()
        if 'exercise' in item:
            exercise = item['exercise']
            if kind not in ('code', 'practice', 'case') or not isinstance(exercise, dict):
                raise ApiError('只有编程/配置、实操或故障场景题可声明产物合同')
            environment = exercise.get('environment')
            verification = exercise.get('verification')
            deliverables = exercise.get('deliverables')
            if not isinstance(environment, str) or not 1 <= len(environment) <= 3000:
                raise ApiError('产物合同需要明确操作环境')
            if (not isinstance(deliverables, list) or not 1 <= len(deliverables) <= 30
                    or any(not isinstance(name, str) for name in deliverables)
                    or len(set(deliverables)) != len(deliverables)):
                raise ApiError('产物合同需要1–30个唯一交付文件路径')
            validate_files({name: '' for name in deliverables})
            steps = [verification] if isinstance(verification, str) else verification
            if (not isinstance(steps, list) or not 1 <= len(steps) <= 30
                    or any(not isinstance(step, str) or not 1 <= len(step.strip()) <= 3000 for step in steps)):
                raise ApiError('产物合同需要明确的验收步骤')
            if not all(label in q['body'] for label in ('操作任务', '产物', '验收方法')):
                raise ApiError('动手题正文必须包含操作任务、产物和验收方法')
            q['exercise'] = {'environment': environment, 'deliverables': deliverables,
                             'verification': verification}
        result.append(q)
    return result

