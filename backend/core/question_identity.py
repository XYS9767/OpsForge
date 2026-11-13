"""Identify an assessed task independently of its catalog metadata."""
import hashlib
import json


def content_key(question):
    # Labels, review notes and version counters do not change what was solved.
    # A changed task, starter, solution or grader must not inherit old mastery.
    fields = ('type', 'title', 'body', 'intro', 'files', 'language', 'run',
              'exercise', 'assessment', 'solution_files', 'answer', 'grading',
              'rubric', 'state', 'template', 'seed', 'options', 'blanks')
    payload = {key: question[key] for key in fields if key in question}
    if isinstance(payload.get('assessment'), dict):
        assessment = dict(payload['assessment'])
        # Adding an environment preflight does not change the learner's task
        # or its executable assertions. Changed assertions still reset mastery.
        assessment.pop('requires', None)
        payload['assessment'] = assessment
    if isinstance(payload.get('exercise'), dict):
        exercise = dict(payload['exercise'])
        # Runtime availability/publication notes describe the platform, not a
        # different task or rubric.
        for key in ('environment_status', 'runtime_acceptance'):
            exercise.pop(key, None)
        operation = exercise.get('operation')
        # Some older tasks have their operation only in the body. Copying that
        # same paragraph into the structured field must not erase mastery.
        if isinstance(operation, str) and operation.strip() and operation.strip() in question.get('body', ''):
            exercise.pop('operation')
        payload['exercise'] = exercise
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()
