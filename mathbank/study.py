"""Frozen exams, explicit attempt rounds, exact short-answer grading, remediation."""
import copy
import json
import math
from .store import uid, now
from .solver import equivalent
from .validation import printable
from .output import grade_report


def save_student(store, body, identifier=None):
    if not body.get('name', '').strip(): raise ValueError('학생 이름을 입력하세요.')
    identifier = identifier or uid()
    with store.connect() as db:
        db.execute('INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,updated=excluded.updated',
            (identifier, 'student', json.dumps(body, ensure_ascii=False), now()))
        db.execute('DELETE FROM memberships WHERE student_id=?', (identifier,))
        if body.get('class', '').strip():
            name = body['class'].strip()
            row = db.execute('SELECT id FROM classes WHERE name=?', (name,)).fetchone()
            class_id = row[0] if row else uid()
            if not row: db.execute('INSERT INTO classes VALUES(?,?)', (class_id, name))
            db.execute('INSERT INTO memberships VALUES(?,?)', (class_id, identifier))
    return identifier


def assemble(store, ids, title, points=5, settings=None, revision_of=None):
    from .output import make_exam
    identifier = make_exam(store, ids, title, points=points, layout='two')
    exam = store.record(identifier)
    exam.update(status='confirmed', revision_of=revision_of, output_settings=settings or {},
                date=(settings or {}).get('date', ''), revision=1)
    if revision_of:
        previous = store.record(revision_of)
        exam['revision'] = previous.get('revision', 1) + 1
    store.put_record('exam', {k: v for k, v in exam.items() if k != 'id'}, identifier)
    return identifier


def select_questions(store, unit='', type_name='', minimum=1, maximum=10, count=10):
    if not 1 <= minimum <= maximum <= 10 or type(count) is not int or count < 1:
        raise ValueError('난이도/문항 수 조건 오류')
    with store.connect() as db:
        questions = [store.decode(r) for r in db.execute("SELECT * FROM questions WHERE id NOT IN (SELECT target FROM trash WHERE kind='question') AND document_id NOT IN (SELECT target FROM trash WHERE kind='document') ORDER BY rowid")]
    candidates = [q for q in questions if printable(q) and minimum <= q['content'].get('difficulty', q['content'].get('level', 3)*2) <= maximum
        and (not unit or q['content'].get('unit') == unit) and (not type_name or q['content'].get('type') == type_name)]
    if len(candidates) < count: raise ValueError(f'조건에 맞는 사용 가능 문항은 {len(candidates)}개입니다. 요청 {count}개를 채우기 위해 복제하지 않습니다.')
    return [q['id'] for q in candidates[:count]]


def assign(store, student_id, exam_id, status='assigned'):
    exam = store.record(exam_id)
    if exam.get('draft') or any(not printable(q, 'solutions') for q in exam['questions']):
        raise ValueError('정답·해설까지 검증한 확정 시험만 배정할 수 있습니다.')
    store.record(student_id)
    with store.connect() as db:
        round_ = db.execute('SELECT COALESCE(MAX(round),0)+1 FROM attempts WHERE student_id=? AND exam_id=?', (student_id, exam_id)).fetchone()[0]
        identifier = uid()
        db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?)', (identifier, student_id, exam_id, round_, status, None, now()))
    return identifier


def attempt(store, identifier):
    with store.connect() as db:
        row = db.execute('SELECT * FROM attempts WHERE id=?', (identifier,)).fetchone()
    if not row: raise ValueError('응시 기록이 없습니다.')
    return dict(row)


def grade_answer(q, submitted, maximum):
    value = submitted.strip()
    if not value: return {'answer': submitted, 'status': '—', 'score': 0}
    content = q['content']
    if not printable(q, 'answers'): return {'answer': submitted, 'status': '미채점', 'score': None}
    if content.get('choices'):
        answer = content['answer'].strip()
        result = value == answer if value.isdigit() and answer.isdigit() else None
    else:
        result = equivalent(value, content.get('answer', ''))
    if result is None: return {'answer': submitted, 'status': '미채점', 'score': None}
    return {'answer': submitted, 'status': 'O' if result else 'X', 'score': maximum if result else 0}


def grade_attempt(store, attempt_id, submitted, manual=None, absent=False):
    a = attempt(store, attempt_id)
    exam, student = store.record(a['exam_id']), store.record(a['student_id'])
    if absent:
        with store.connect() as db:
            db.execute("UPDATE attempts SET status='absent',report_id=NULL WHERE id=?", (attempt_id,))
            db.execute('DELETE FROM results WHERE attempt_id=?', (attempt_id,))
        return None
    if len(submitted) != len(exam['questions']): raise ValueError('제출 답의 수가 시험 문항 수와 다릅니다.')
    grades = [grade_answer(q, str(answer), maximum) for q, answer, maximum in zip(exam['questions'], submitted, exam['points'])]
    for index, score in (manual or {}).items():
        if type(index) is not int or not 0 <= index < len(grades) or type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= exam['points'][index]:
            raise ValueError('수동 점수/문항 번호 범위 오류')
        grades[index].update(status='O' if score == exam['points'][index] else 'X' if score == 0 else '부분점수', score=score, manual=True)
    report = grade_report(exam, student, grades)
    report.update(attempt_id=attempt_id, round=a['round'])
    weaknesses = sorted({q['content'].get('unit', '미분류') for q, g in zip(exam['questions'], grades) if g['status'] in ('X', '—', '부분점수')})
    report['notes'] = {'weakness': ', '.join(weaknesses) + ' 단원의 오답·무응답·부분정답을 다시 풀이하세요.' if weaknesses else '현재 채점 기록에서 보완 단원이 확인되지 않았습니다.',
                       'strength': f"완전 정답 {sum(g['status']=='O' for g in grades)}문항 / 전체 {len(grades)}문항",
                       'summary': '다음 과제: 오답 문항 재풀이 후 검증된 숫자변형·사고변형으로 확인합니다.' if weaknesses else '미채점 문항이 있으면 채점을 완료하세요.'}
    report_id = uid()
    with store.connect() as db:
        db.execute('INSERT INTO records VALUES(?,?,?,?)', (report_id, 'report', json.dumps(report, ensure_ascii=False), now()))
        db.execute('DELETE FROM results WHERE attempt_id=?', (attempt_id,))
        db.executemany('INSERT INTO results VALUES(?,?,?,?,?)', [(attempt_id, i+1, g['answer'], g['score'], g['status']) for i, g in enumerate(grades)])
        db.execute('UPDATE attempts SET status=?,report_id=? WHERE id=?', ('graded' if report['graded'] == len(grades) else 'grading', report_id, attempt_id))
    return report_id


def wrong_ids(store, attempt_id):
    a = attempt(store, attempt_id)
    if not a['report_id']: raise ValueError('채점 기록이 없습니다.')
    report = store.record(a['report_id'])
    return [q['id'] for q, g in zip(report['exam']['questions'], report['grades']) if g['status'] in ('X', '—', '부분점수')]


def remediation(store, attempt_id, mode='repeat'):
    a = attempt(store, attempt_id)
    if not a['report_id']: raise ValueError('채점 기록이 없습니다.')
    report = store.record(a['report_id'])
    wrong = [copy.deepcopy(q) for q, g in zip(report['exam']['questions'], report['grades']) if g['status'] in ('X', '—', '부분점수')]
    if not wrong: raise ValueError('오답·무응답·부분정답 문항이 없습니다.')
    if mode == 'repeat':
        # Use the old exam snapshot even when the live bank has changed/deleted.
        exam = copy.deepcopy(report['exam'])
        exam.pop('id', None)
        exam.update(title=exam['title'] + ' · 오답 재풀이', questions=wrong,
                    points=[5] * len(wrong), remediation_of=attempt_id)
        return store.put_record('exam', exam)
    if mode not in ('numeric', 'thinking'): raise ValueError('오답 과제 종류 오류')
    jobs = []
    for q in wrong:
        current = store.question(q['id'])
        if current['version'] != q['version']:
            raise ValueError('원본 문항이 변경되어 변형 기준을 확인해야 합니다. 과거 문항 재풀이는 가능합니다.')
        jobs.append(store.enqueue('variant_local_' + mode, q['id'], q['version']))
    return jobs


def student_packet(store, attempt_id, destination):
    from pathlib import Path
    from .publishing import export_pdf, export_hwpx
    a = attempt(store, attempt_id)
    student = store.record(a['student_id'])
    exam = copy.deepcopy(store.record(a['exam_id']))
    exam.setdefault('output_settings', {}).update(student=student['name'], **{'class': student.get('class', '')})
    directory = Path(destination) / a['id'][:12]
    directory.mkdir(parents=True, exist_ok=True)
    for kind in ('questions', 'answers', 'solutions'):
        export_pdf(store, exam, directory/(kind+'.pdf'), kind, attempt_id=attempt_id)
        export_hwpx(store, exam, directory/(kind+'.hwpx'), kind, attempt_id=attempt_id)
    return directory
