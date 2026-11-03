"""Deterministic hundred-point paper scoring with explicit pending points."""


def report(eid, payload, results):
    snapshots = payload.get('snapshots', [])
    count = len(snapshots)
    if not count:
        return {'id': eid, 'results': [], 'late': payload.get('late', False),
                'score': None, 'earned_points': 0, 'max_points': 100,
                'pending_points': 100, 'pending_count': 0, 'score_status': 'incomplete'}
    base, extra = divmod(10000, count)
    indexed = {r['id']: r for r in results}
    enriched, earned, pending, pending_count, automatic, manual = [], 0, 0, 0, 0, 0
    for index, q in enumerate(snapshots):
        points = base + (index < extra)
        result = dict(indexed.get(q['id'], {'id': q['id'], 'title': q['title'],
                          'passed': None, 'method': '待判分', 'message': '本题判分尚未完成。'}))
        auto = result.get('method') in ('自动判分', '状态验收', '实验执行验收', '产物检查')
        self_rated = q['type'] == 'interview' and result.get('method') == '对照要点自评'
        known = isinstance(result.get('passed'), bool) and (auto or self_rated)
        value = points if known and result['passed'] else 0
        if not known:
            pending += points
            pending_count += 1
        elif auto:
            automatic += value
        else:
            manual += value
        earned += value
        result.update(number=index+1, max_points=points/100,
                      points=value/100 if known else None,
                      grading_mode='automatic' if auto else 'self_review' if q['type']=='interview' else 'pending')
        enriched.append(result)
    level = 'pending' if pending_count else 'excellent' if earned >= 9000 else 'passed' if earned >= 6000 else 'failed'
    return {'id': eid, 'results': enriched, 'late': payload.get('late', False),
            'grade_band': level,
            'grade_label': {'pending':'待评','excellent':'优秀','passed':'及格','failed':'未及格'}[level],
            'submission_status': 'timeout' if payload.get('late', False) else 'submitted',
            'submission_label': '作答超时' if payload.get('late', False) else '正常交卷',
            'score': earned/100 if not pending_count else None, 'max_points': 100,
            'earned_points': earned/100, 'pending_points': pending/100,
            'automatic_points': automatic/100, 'self_review_points': manual/100,
            'pending_count': pending_count, 'score_status': 'pending' if pending_count else 'final',
            'scoring_rule': '全卷100分，题目等权；不足0.01分的尾差按题序分配。未答自动题0分；待评不记作最终分。文字面试题自评单列。'}
