import copy
import json
from pathlib import Path
import zipfile
import pytest
import pymupdf
from mathbank.store import Store
from mathbank.validation import initial_stages, compare_readings, validate_content, printable
from mathbank.pipeline import Pipeline
from mathbank.output import make_exam, exam_html, export_docx, grade_report, report_html
from mathbank.exchange import identity, import_response


def content(text='$y=|x+1|-|x-2|$, $mx-y+3m-4=0$'):
    return dict(text=text, choices=['$1$', '$2$'], diagram=[], answer='$2$',
                solution=['조건을 해석합니다.', '$1+1=2$'], course='공통수학2', unit='함수',
                level=3, reason='조건 재구성', uncertain=False)


@pytest.fixture
def bank(tmp_path):
    store = Store(tmp_path / '한글 운영 데이터')
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((60, 80), '1. Calculate 1 + 1.\nA. 1  B. 2')
    path = tmp_path / '원본 자료.pdf'
    pdf.save(path)
    pdf.close()
    document, _ = store.add_document(path, '공통수학2')
    question = store.add_question(document, [{'page': 0, 'box': [40, 50, 400, 160]}], '0023')
    return store, document, question


def passed(store, identifier, c=None):
    q = store.question(identifier)
    stages = initial_stages()
    for value in stages.values():
        value.update(state='passed', version=q['version'])
    store.update_question(identifier, q['version'], c or content(), stages)
    return store.question(identifier)


def test_constant_corruption_regression():
    original = content()
    wrong = content('$y=|x+1|-|x-1|$, $mx-y+3m-2=0$')
    issues = compare_readings(original, wrong)
    assert any('숫자·부호' in issue for issue in issues)


def test_manual_edit_protects_against_late_result(bank):
    store, _, identifier = bank
    q = passed(store, identifier)
    edited = content('사용자가 수정한 $x=3$')
    assert store.update_question(identifier, 1, edited, initial_stages(), manual=True)
    assert not store.update_question(identifier, 1, content(), initial_stages())
    assert not store.update_question(identifier, 2, content(), initial_stages())
    assert store.question(identifier)['content']['text'] == edited['text']


def test_snapshot_is_immutable(bank):
    store, _, identifier = bank
    passed(store, identifier)
    exam_id = make_exam(store, [identifier], '중간고사')
    before = store.record(exam_id)
    store.update_question(identifier, 1, content('새 문제'), initial_stages(), manual=True)
    assert store.record(exam_id) == before


def test_unverified_output_blocked_and_draft_labeled(bank):
    store, _, identifier = bank
    with pytest.raises(ValueError):
        make_exam(store, [identifier], '정식')
    draft = store.record(make_exam(store, [identifier], '초안', mode='draft'))
    assert '처리 예외' in exam_html(draft)


def test_answer_failure_does_not_block_question(bank):
    store, _, identifier = bank
    q = passed(store, identifier)
    q['stages']['answer']['state'] = 'exception'
    assert printable(q)
    assert not printable(q, 'answers')


def test_backup_restore_hashes_and_records(bank, tmp_path):
    store, _, identifier = bank
    passed(store, identifier)
    store.put_record('student', {'name':'테스트 학생'})
    path = tmp_path / 'backup.zip'
    store.backup(path)
    restored = Store.restore(path, tmp_path / '복원 공간')
    assert restored.question(identifier) == store.question(identifier)
    assert restored.records('student') == store.records('student')
    assert restored.documents() == store.documents()
    with pytest.raises(ValueError):
        Store.restore(path, store.root)


def test_bad_backup_preserves_current(bank, tmp_path):
    store, _, identifier = bank
    path = tmp_path / 'bad.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('manifest.json', json.dumps({'version':1, 'files':{'../escape':'x'}}))
        archive.writestr('../escape', 'bad')
    with pytest.raises(ValueError):
        Store.restore(path, tmp_path / 'restore')
    assert store.question(identifier)
    assert not (tmp_path / 'escape').exists()


def test_docx_contains_native_math_and_no_answer_leak(bank, tmp_path):
    store, _, identifier = bank
    passed(store, identifier)
    exam = store.record(make_exam(store, [identifier], '수식 시험'))
    path = tmp_path / 'exam.docx'
    export_docx(exam, path)
    with zipfile.ZipFile(path) as archive:
        xml = archive.read('word/document.xml').decode()
    assert 'm:oMath' in xml
    assert '조건을 해석합니다' not in xml
    assert '조건을 해석합니다' not in exam_html(exam)


def test_ungraded_is_not_wrong(bank):
    store, _, identifier = bank
    passed(store, identifier)
    exam = store.record(make_exam(store, [identifier], '평가'))
    report = grade_report(exam, {'name':'테스트','school':'중등'}, [{'status':'미채점'}])
    assert report['graded'] == 0
    assert list(report['matrix'].values())[0]['pending'] == 1
    assert list(report['matrix'].values())[0]['possible'] == 0
    assert '최종 점수 미산출' in report_html(report)
    assert 'MIDDLE SCHOOL REPORT' in report_html(report)


def test_partial_score_range(bank):
    store, _, identifier = bank
    passed(store, identifier)
    exam = store.record(make_exam(store, [identifier], '평가'))
    with pytest.raises(ValueError):
        grade_report(exam, {}, [{'status':'부분점수','score':6}])


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call(self, prompt, images, cancel):
        self.calls.append((prompt, images))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)


REVIEW = dict(source_ok=True, diagram_ok=True, answer_ok=True, solution_ok=True, course_ok=True, reasons=[])


def test_full_queue_without_teacher_approval(bank):
    store, document, _ = bank
    provider = ScriptedProvider([dict(kind='questions', regions=[dict(number='1',box=[50,50,500,200])]), content(), content(), REVIEW])
    pipeline = Pipeline(store, provider)
    pipeline.enqueue_document(document)
    pipeline.run()
    questions, _ = store.questions()
    completed = [q for q in questions if printable(q)]
    assert len(completed) == 1
    assert len(provider.calls) == 4
    assert 'fresh independent' in provider.calls[2][0]
    assert store.record(make_exam(store, [completed[0]['id']], '자동 처리'))


def test_bounded_retries_and_next_question_continues(bank):
    store, document, identifier = bank
    bad = content()
    bad['uncertain'] = True
    second = store.add_question(document, [{'page':0,'box':[50,170,400,280]}], '2')
    provider = ScriptedProvider([bad,bad,bad,content(),content(),REVIEW])
    pipeline = Pipeline(store, provider)
    store.enqueue('question', identifier, 1)
    store.enqueue('question', second, 1)
    pipeline.run()
    assert not printable(store.question(identifier))
    assert printable(store.question(second))
    attempts = store.records('attempt')
    assert len(attempts) == 3
    assert len({a['method'] for a in attempts}) == 3


def test_solution_failure_preserves_source(bank):
    store, _, identifier = bank
    review = dict(REVIEW, solution_ok=False)
    pipeline = Pipeline(store, ScriptedProvider([content(),content(),review]))
    store.enqueue('question',identifier,1)
    pipeline.run()
    q = store.question(identifier)
    assert printable(q)
    assert not printable(q, 'solutions')


def test_stale_offline_response_rejected(bank, tmp_path):
    store, _, identifier = bank
    q = store.question(identifier)
    payload = {'identity':identity(store,q),'content':content()}
    payload['identity']['version'] = 99
    path = tmp_path / 'response.json'
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        import_response(store,path)


def test_import_does_not_grant_pass(bank, tmp_path):
    store, _, identifier = bank
    path = tmp_path / 'response.json'
    path.write_text(json.dumps({'identity':identity(store,store.question(identifier)), 'content':content()}))
    import_response(store,path)
    assert not printable(store.question(identifier))


@pytest.mark.parametrize('diagram', [[{'type':'script','label':'bad'}], [{'type':'text','x':1,'y':2,'label':3}], [{'type':'line','x1':float('nan'),'y1':1,'x2':2,'y2':3}]])
def test_untrusted_diagrams_rejected(diagram):
    c = content()
    c['diagram'] = diagram
    with pytest.raises(ValueError):
        validate_content(c)


def test_markup_escaped_in_output(bank):
    store, _, identifier = bank
    passed(store, identifier, content('<script>alert(1)</script>'))
    exam = store.record(make_exam(store, [identifier], '<img onerror=alert(1)>'))
    output = exam_html(exam)
    assert '<script>alert(1)</script>' not in output
    assert '&lt;script&gt;' in output


def test_duplicate_pdf_and_regions(bank):
    store, document, identifier = bank
    d = store.document(document)
    assert store.add_document(store.root / d['path']) == (document,False)
    q = store.question(identifier)
    assert store.add_question(document,q['regions']) == identifier


def test_pagination(bank):
    store, document, _ = bank
    for n in range(55):
        store.add_question(document,[{'page':0,'box':[0,n,100,n+1]}],str(n))
    first,total = store.questions(0)
    second,_ = store.questions(1)
    assert total == 56 and len(first) == 50 and len(second) == 6


def test_numeric_check_is_not_code_execution():
    from mathbank.arithmetic import numeric, audit
    assert numeric('1/2+1/2') == 1
    assert audit(['$2+3=6$'])['errors']
    assert audit(['$2+3=5$'])['checked_equalities'] == 1
    with pytest.raises(ValueError):
        numeric("__import__('os').system('id')")


def test_queue_not_starved_by_display_pagination(bank):
    store, _, identifier = bank
    first = store.enqueue('question', identifier, 1)
    for index in range(310):
        store.enqueue('page', f'test-{index}')
    assert store.next_job()['id'] == first


def test_original_hash_checked(bank, tmp_path):
    from mathbank.pipeline import crop
    store, document, identifier = bank
    (store.root / store.document(document)['path']).write_bytes(b'tampered')
    with pytest.raises(ValueError, match='해시'):
        crop(store,store.question(identifier),tmp_path)


def test_answer_edit_keeps_source_checks(bank):
    from mathbank.validation import invalidate_changes
    store, _, identifier = bank
    q = passed(store, identifier)
    changed = dict(q['content'], answer='$3$')
    stages = invalidate_changes(q['content'], changed, q['stages'], 2)
    assert stages['comparison'] == dict(state='passed', version=2, reason='')
    assert stages['answer']['state'] == 'pending'
    assert stages['solution']['state'] == 'pending'
