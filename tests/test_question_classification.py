import copy
import json
import pytest
from studio.classification import assess,edit,reclassify,METHOD
from studio.importers import import_document
from studio.model import body_fingerprint
from studio.storage import Store
from studio.reasoning import check_question
from studio.variants import generate
from studio.fixtures import make_fixture


def task(text,format='short'):
    return {'blocks':[{'kind':'paragraph','blocks':[{'kind':'text','value':text}]}],'choices':[],'answer_format':format}


def add(store,text):
    body=task(text);c,d=assess(body,'공통수학1')
    with store.transaction() as db:return store.insert_question(db,{'body':body,'classification':c,'difficulty':d,'input_state':'complete'})


def test_answer_format_is_not_a_difficulty_factor():
    a,d=assess(task('두 다항식을 계산하시오.','mc'),'공통수학1')
    b,e=assess(task('두 다항식을 계산하시오.','short'),'공통수학1')
    assert d==e==3
    assert a['difficulty_assessment']['basis']==b['difficulty_assessment']['basis']


@pytest.mark.parametrize('text,unit,subunit,score',[
    ('두 다항식을 계산하시오.','다항식','다항식의 연산',3),
    ('두 다항식의 관계식에서 B를 역으로 구하시오.','다항식','다항식의 연산',5),
    ('다항식을 나눈 나머지를 구하시오.','다항식','나머지정리',4),
    ('모든 자연수 n에 대하여 다항식을 나눈 나머지를 구하시오.','다항식','나머지정리',7),
    ('이차방정식의 해를 구하시오.','방정식과 부등식','이차방정식',3),
    ('이차방정식이 중근을 가질 조건을 구하시오.','방정식과 부등식','이차방정식',5),
    ('자연수에서 이차함수의 최댓값을 구하시오.','방정식과 부등식','이차함수',7),
    ('복소수의 켤레 관계를 이용하시오.','방정식과 부등식','복소수',5),
    ('순열의 수를 구하시오.','경우의 수','순열과 조합',4),
    ('행렬의 성분을 구하시오.','행렬','행렬의 연산',3),
    ('이차방정식이 실근을 갖도록 하는 계수의 최댓값은?','방정식과 부등식','이차방정식',5),
    ('이차함수의 그래프와 직선이 한 점에서 만나고 다른 그래프와 만나지 않을 조건은?','방정식과 부등식','이차함수',7),
    ('이차함수와 일차함수가 조건을 만족하고 그 합의 방정식이 중근을 갖는다.','방정식과 부등식','이차함수',7),
    ('다항식의 곱이 다른 식으로 나누어떨어지고 또 다른 다항식의 곱으로도 나누어떨어진다.','다항식','인수분해',8),
])
def test_each_task_gets_its_own_content_rubric(text,unit,subunit,score):
    c,d=assess(task(text),'공통수학1')
    assert (c['unit'],c['subunit'],d)==(unit,subunit,score)
    a=c['difficulty_assessment'];assert a['scope']=='question' and a['score']==score and a['basis'] and a['state']=='estimated'


def test_unknown_and_unsplit_bundles_are_not_assigned_a_visible_score():
    c,_=assess(task('문제에서 요구한 값을 구하시오.'))
    assert c['unit']=='미분류' and c['difficulty_assessment']['score'] is None
    c,_=assess(task('다항식 계산. 이차방정식의 해.'),boundary_review=True)
    assert c['difficulty_assessment']['state']=='pending_boundary' and c['difficulty_assessment']['score'] is None


def test_import_classifies_questions_separately_without_exam_or_filename_bias(tmp_path):
    path=tmp_path/'상급_시험_난이도10.hwpx';make_fixture(path);s=Store(tmp_path/'db');result=import_document(s,path)
    qs=s.questions();assert len(qs)==2
    assert {q['classification']['scope'] for q in qs}=={'question'}
    assert {q['difficulty'] for q in qs}=={3,5}
    assert len({q['classification']['subunit'] for q in qs})==2
    assert 'difficulty' not in s.documents()[0]['metadata']
    for q in qs:
        c,d=assess(q['body'],q['classification']['course']);assert d==q['difficulty'] and c==q['classification']


def test_metadata_edits_preserve_answer_and_old_exam_snapshot(tmp_path):
    s=Store(tmp_path/'db');p=tmp_path/'p.hwpx';make_fixture(p);import_document(s,p)
    q=s.questions()[0];s.save_answer(q['id'],q['revision'],q['fingerprint'],check_question(q));q=s.question(q['id']);assert q['available']
    exam=s.create_exam({'title':'분류 수정 전 시험','question_ids':[q['id']],'confirm':True})
    old=s.exam(exam)['items'][0]['snapshot']
    values={'course':'공통수학1','unit':'다항식','subunit':'연산 연습','type':'기본 연산','difficulty':2,'reason':'이 문항은 직접 대입과 항 정리 두 단계입니다.'}
    newrev=edit(s,q['id'],q['revision'],values);new=s.question(q['id'])
    assert newrev==q['revision']+1 and new['difficulty']==2 and new['available']
    assert new['answer']==q['answer'] and new['body']==q['body'] and new['fingerprint']==q['fingerprint']
    assert new['classification']['difficulty_assessment']['origin']=='user'
    assert s.exam(exam)['items'][0]['snapshot']==old
    reclassify(s,q['id']);assert s.question(q['id'])['difficulty']==2
    with pytest.raises(ValueError,match='변경'):edit(s,q['id'],q['revision'],values)


def test_upgrade_replaces_only_legacy_auto_scores_and_keeps_manual_values(tmp_path):
    root=tmp_path/'db';s=Store(root);p=tmp_path/'p.hwpx';make_fixture(p);import_document(s,p)
    first,second=s.questions();s.save_answer(first['id'],1,first['fingerprint'],check_question(first))
    for i,q in enumerate((first,second)):
        old={**q['classification'],'certainty':'user_confirmed' if i else 'suggested','basis':'본문 어휘에 의한 자동 제안'}
        s.db.execute('UPDATE versions SET classification=?,difficulty=7 WHERE question_id=?',(json.dumps(old,ensure_ascii=False),q['id']))
    s.db.close();reopened=Store(root);a=reopened.question(first['id']);b=reopened.question(second['id'])
    assert a['revision']==2 and a['difficulty']==3 and a['available']
    assert a['classification']['method']==METHOD
    assert b['revision']==1 and b['difficulty']==7 and b['classification']['certainty']=='user_confirmed'
    assert len(list((root/'backups').glob('before-question-classification-*.sqlite')))==1
    reopened.db.close();again=Store(root);assert again.question(first['id'])['revision']==2


def test_changed_question_is_reassessed_and_old_answer_is_not_reused(tmp_path):
    s=Store(tmp_path/'db');qid=add(s,'두 다항식을 계산하시오.');q=s.question(qid)
    assert q['difficulty']==3
    s.revise(qid,{'body':task('모든 자연수에 대해 다항식의 나머지를 구하시오.')})
    changed=s.question(qid);assert changed['difficulty']==7
    assert changed['classification']['difficulty_assessment']['body_fingerprint']==changed['fingerprint']
    assert not changed.get('answer')


def test_variants_are_assessed_from_their_content_not_parent_score(tmp_path):
    s=Store(tmp_path/'db');p=tmp_path/'p.hwpx';make_fixture(p);import_document(s,p)
    parent=s.questions()[0];s.revise(parent['id'],{'difficulty':10})
    numeric=s.question(generate(s,parent['id'],'numeric',{'provider':'local'},'n'))
    thinking=s.question(generate(s,parent['id'],'thinking',{'provider':'local'},'t'))
    assert numeric['difficulty']==3 and thinking['difficulty']==5
    assert numeric['classification']['difficulty_assessment']['body_fingerprint']==numeric['fingerprint']


def test_generic_manual_difficulty_edit_keeps_score_and_assessment_consistent(tmp_path):
    s=Store(tmp_path/'db');qid=add(s,'다항식을 계산하시오.');s.revise(qid,{'difficulty':9})
    q=s.question(qid);assert q['difficulty']==q['classification']['difficulty_assessment']['score']==9


def test_unknown_difficulty_is_not_counted_as_medium_or_printed_as_five(tmp_path):
    from studio.model import difficulty_counts,difficulty_label
    from studio.exports import PDF
    from studio.assessment import report
    from pypdf import PdfReader
    s=Store(tmp_path/'db');qid=add(s,'이 자료의 값을 구하시오.');q=s.question(qid)
    assert difficulty_label(q)=='난이도 미분류'
    assert difficulty_counts([q])=={'하':0,'중':0,'상':0,'미분류':1}
    eid=s.create_exam({'title':'미분류 출력 확인','question_ids':[qid]})
    # Drafts can be reviewed before mathematical certification.
    exam=s.exam(eid);pdf=PDF(s,tmp_path/'print').exam(exam,'questions')
    text=''.join(p.extract_text() for p in PdfReader(pdf).pages)
    assert '난이도 미분류' in text and '5/10' not in text
