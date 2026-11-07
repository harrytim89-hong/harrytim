import copy
import pytest
from studio.storage import Store
from studio.service import Service
from studio.classification import assess, edit
from studio.curriculum import scope
from studio.formula import equation
from studio.similarity import SimilarityIndex
from studio.fixtures import make_fixture
from studio.importers import import_document
from studio.reasoning import check_question
from studio.assessment import report, grade, save_comment
from studio.exports import PDF
from pypdf import PdfReader


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path/'workspace')
    yield s
    s.db.close()


def insert(s, number=3, choice='7', picture=None, boundary=False):
    body = {'blocks': [{'kind': 'paragraph', 'blocks': [
        {'kind': 'text', 'value': '다음 일차방정식의 해를 구하시오.'},
        equation(f'2x+{number}=9')]}],
        'choices': [[{'kind': 'text', 'value': choice}]], 'answer_format': 'mc'}
    if picture:body['blocks'].append({'kind': 'image', 'path': picture})
    c,d=assess(body)
    with s.transaction() as db:
        return s.insert_question(db, {'body':body, 'classification':c, 'difficulty':d,
                                     'source':{'boundary_review':boundary}})


def test_identical_numeric_and_choice_changes(store):
    source=insert(store);exact=insert(store);numeric=insert(store,5);choice=insert(store,choice='8')
    result=SimilarityIndex(store).search(source)
    by_id={m['id']:m for m in result['matches']}
    assert result['matches'][0]['id']==exact and result['exact_count']==1
    assert by_id[exact]['kind']=='exact'
    assert by_id[numeric]['kind']=='template' and by_id[choice]['kind']!='exact'
    assert source not in by_id


def test_image_content_required_for_exact(store):
    a=store.blob(b'picture-a','assets','.png');b=store.blob(b'picture-b','assets','.png')
    source=insert(store,picture=a);same=insert(store,picture=a);different=insert(store,picture=b)
    matches={m['id']:m for m in SimilarityIndex(store).search(source)['matches']}
    assert matches[same]['kind']=='exact' and matches[different]['kind']!='exact'


def test_index_revisions_trash_and_unresolved(store):
    source=insert(store);other=insert(store);insert(store,boundary=True)
    index=SimilarityIndex(store)
    assert index.search(source)['exact_count']==1
    body=copy.deepcopy(store.question(other)['body']);body['blocks'][0]['blocks'][1]=equation('2x+5=9')
    store.revise(other,{'body':body})
    assert index.search(source)['exact_count']==0
    assert index.search(source)['matches'][0]['revision']==2
    store.trash('question',other)
    assert index.search(source)['matches']==[]
    store.trash('question',source)
    with pytest.raises(ValueError):index.search(source)


def test_unrelated_not_returned_from_same_classification(store):
    source=insert(store)
    q=copy.deepcopy(store.question(source));q['body']={'blocks':[{'kind':'text','value':'동전을 세 번 던질 때 앞면이 나올 확률은?'}], 'choices':[], 'answer_format':'short'}
    with store.transaction() as db:store.insert_question(db,q)
    assert SimilarityIndex(store).search(source)['matches']==[]
    with pytest.raises(ValueError):SimilarityIndex(store).search(source,0)


def test_known_variants_remain_retrievable_after_teacher_reclassification(store,tmp_path):
    from studio.variants import generate
    import_document(store,make_fixture(tmp_path/'variants.hwpx',notes=True))
    q=store.questions()[0]
    store.save_answer(q['id'],q['revision'],q['fingerprint'],check_question(q))
    child=generate(store,q['id'],'numeric',{'provider':'local'},'similarity-fixture')
    store.revise(q['id'],{'classification':{**q['classification'],'unit':'개인 수업','type':'복습'}})
    found={m['id']:m for m in SimilarityIndex(store).search(q['id'])['matches']}
    assert child in found and '같은 원본에서 연결된 변형 문항' in found[child]['reasons']


@pytest.mark.parametrize('text,level,unit',[
    ('소인수분해로 최대공약수를 구하시오.','중등','수와 연산'),
    ('피타고라스 정리를 이용해 삼각형의 길이를 구하시오.','중등','기하'),
    ('도함수를 이용하여 미분하시오.','고등','미적분'),
    ('이차방정식을 풀어라.','중·고 공통','방정식과 부등식'),
    ('이 문장은 분류하기 어렵습니다.','미분류','미분류'),
])
def test_school_scope(text,level,unit):
    body={'blocks':[{'kind':'text','value':text}],'choices':[],'answer_format':'short'}
    c,_=assess(body)
    assert c['unit']==unit and scope(body,c)==level


def test_teacher_scope_is_persisted_without_rewriting_question(store):
    qid=insert(store);q=store.question(qid)
    edit(store,qid,q['revision'],{'course':'수학','unit':'방정식','subunit':'일차방정식','type':'기본 계산',
                                'difficulty':2,'reason':'중학교 수업용','school_level':'중등'})
    new=store.question(qid)
    assert new['body']==q['body'] and scope(new['body'],new['classification'])=='중등'
    assert Service(store).command('similar_questions',{'id':qid})['matches']==[]


def test_report_comments_weakness_and_pdf_survive_reopen(store,tmp_path):
    import_document(store,make_fixture(tmp_path/'example.hwpx',notes=True))
    for q in store.questions():store.save_answer(q['id'],q['revision'],q['fingerprint'],check_question(q))
    eid=store.create_exam({'question_ids':[q['id'] for q in store.questions()],'confirm':True})
    sid=store.add_student({'name':'테스트 학생'});aid=store.assign(eid,[sid])[0]
    assert report(store,aid)['weak_types']=={}
    grade(store,aid,{})
    assert report(store,aid)['weak_types']
    comment='계산 과정을 차분히 확인하세요.\n다음 시간에는 오답을 다시 풉니다.'
    r=save_comment(store,aid,comment)
    path=PDF(store,store.root/'outputs/teacher-report').report(r)
    text=''.join(p.extract_text() for p in PdfReader(path).pages)
    assert '교사 코멘트' in text and '계산 과정을' in text
    another=Store(store.root)
    try:assert report(another,aid)['comment']==comment
    finally:another.db.close()
    with pytest.raises(ValueError):save_comment(store,aid,'x'*4001)
    assert report(store,aid)['comment']==comment
    grade(store,aid,{},absent=True)
    assert report(store,aid)['weak_types']=={} and report(store,aid)['score'] is None
