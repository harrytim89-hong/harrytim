import copy
import json
import time
import zipfile
from pathlib import Path
import pytest
from studio.storage import Store
from studio.fixtures import make_fixture,native_fixture
from studio.importers import import_document,read_package
from studio.reasoning import check_question
from studio.model import body_fingerprint,plain_text,available
from studio.formula import equation
from studio.algebra import parse,same,scalar_answer,Unsupported
from studio.variants import generate
from studio.assessment import auto_grade,grade,report,remediation
from studio.jobs import Jobs

@pytest.fixture
def workspace(tmp_path):
    store=Store(tmp_path/'db');source=make_fixture(tmp_path/'source.hwpx',notes=True);import_document(store,source)
    yield store
    store.db.close()

def solve_all(store):
    for q in store.questions():store.save_answer(q['id'],q['revision'],q['fingerprint'],check_question(q))

def test_real_pipeline_without_original_answers(tmp_path):
    source=make_fixture(tmp_path/'problems-only.hwpx');s=Store(tmp_path/'db');r=import_document(s,source)
    assert r['answer_count']==0 and r['complete']==2
    assert all(q['answer'] is None for q in s.questions())
    solve_all(s);assert all(q['available'] for q in s.questions())

def test_endnotes_bind_to_document_not_number(workspace,tmp_path):
    q=workspace.questions()[0];assert q['original_answer']=='2'
    assert '2'!=plain_text(q['body']['blocks']).strip()
    assert not any(b['kind']=='note' for p in q['body']['blocks'] for b in p.get('blocks',[]))

def test_duplicate_and_trash_recovery(workspace,tmp_path):
    doc=workspace.documents()[0];r=import_document(workspace,tmp_path/'source.hwpx');assert r['duplicate']
    workspace.trash('document',doc['id']);assert not workspace.questions()
    workspace.trash('document',doc['id'],False);assert len(workspace.questions())==2

def test_provided_answer_conflict_preserved(workspace):
    q=workspace.questions()[0];q['original_answer']='1';a=check_question(q)
    assert a['verification']=='failed' and a['provided_answer']=='1' and a['final_answer']=='2'

def test_missing_answer_is_not_input_failure(workspace):
    q=workspace.questions()[0];q['original_answer']=None
    a=check_question(q);assert a['verification']=='passed'

def test_every_choice_must_be_parsed(workspace):
    q=workspace.questions()[0];q['body']['choices'][4]=[{'kind':'text','value':'이 보기를 해석할 수 없음'}]
    q['fingerprint']=body_fingerprint(q['body']);a=check_question(q)
    assert a['verification']=='held'

def test_multiple_equivalent_choices_hold(workspace):
    q=workspace.questions()[0];q['body']['choices'][0]=copy.deepcopy(q['body']['choices'][1]);q['fingerprint']=body_fingerprint(q['body'])
    assert check_question(q)['verification']=='held'

def test_input_quality_gate(workspace):
    q=workspace.questions()[0];q['input_state']='held';a=check_question(q)
    assert a['verification']=='held'

def test_unknown_semantics_hold(workspace):
    q=workspace.questions()[0];q['body']={'blocks':[{'kind':'paragraph','blocks':[{'kind':'text','value':'새 유형: 모든 실수의 성질을 증명하시오.'}]}],'choices':[],'answer_format':'short'}
    q['fingerprint']=body_fingerprint(q['body']);assert check_question(q)['verification']=='held'

def test_unrecognized_extra_condition_cannot_be_ignored(workspace):
    q=workspace.questions()[0]
    q['body']['blocks'].append({'kind':'paragraph','blocks':[{'kind':'text','value':'추가로 x는 양수이며 y는 음수이다.'}]})
    q['fingerprint']=body_fingerprint(q['body'])
    assert check_question(q)['verification']=='held'

@pytest.mark.parametrize('formula,expected',[('(x-3)^2','x^2-6x+9'),('{1} over {(x_{1})^2}','x_1^(-2)'),('sqrt{-3}sqrt{-12}','-6'),('2x^2-x y+3y^2','2x^2-xy+3y^2')])
def test_formula_semantics(formula,expected):
    if 'x_1' in expected:assert str(parse(formula))=='x_1**(-2)'
    else:assert same(parse(formula),parse(expected))

@pytest.mark.parametrize('payload',['__import__("os").system("whoami")','open("secret")','2^1000000'])
def test_math_never_evaluates_python(payload):
    with pytest.raises((ValueError,TypeError,Unsupported)):scalar_answer(payload)

def test_variants_are_new_and_idempotent(workspace):
    solve_all(workspace);parent=workspace.questions()[0];children=[]
    for kind in ('numeric','thinking'):
        child=generate(workspace,parent['id'],kind,{'provider':'local'},kind);children.append(child)
        assert generate(workspace,parent['id'],kind,{'provider':'local'},kind)==child
        q=workspace.question(child);assert q['available'];assert q['lineage']['parent_revision']==1
    assert len(set(children))==2 and len(workspace.questions())==4
    assert workspace.question(parent['id'])['fingerprint']==parent['fingerprint']

def test_exam_freezes_versions_and_retests(workspace):
    solve_all(workspace);questions=workspace.questions();eid=workspace.create_exam({'question_ids':[q['id'] for q in questions],'points':[40,60],'confirm':True})
    sid=workspace.add_student({'name':'가상 학생'});aid=workspace.assign(eid,[sid])[0];exam=workspace.exam(eid)
    submitted={i['id']:i['snapshot']['answer']['final_answer'] for i in exam['items']};grade(workspace,aid,submitted)
    workspace.revise(questions[0]['id'],{'original_answer':'1'})
    assert not workspace.question(questions[0]['id'])['available']
    assert report(workspace,aid)['score']==100
    assert workspace.exam(eid)['items'][0]['snapshot']['original_answer']=='2'
    new=workspace.assign(eid,[sid])[0];assert report(workspace,new)['attempt']['round']==2

def test_stale_job_cannot_apply_to_new_revision(workspace):
    q=workspace.questions()[0];a=check_question(q);workspace.revise(q['id'],{'difficulty':8})
    with pytest.raises(ValueError):workspace.save_answer(q['id'],q['revision'],q['fingerprint'],a)

def test_distribution_rejects_unverified(workspace):
    with pytest.raises(ValueError):workspace.create_exam({'question_ids':[workspace.questions()[0]['id']],'confirm':True})
    eid=workspace.create_exam({'question_ids':[workspace.questions()[0]['id']],'confirm':False})
    sid=workspace.add_student({'name':'가상'})
    with pytest.raises(ValueError):workspace.assign(eid,[sid])

def test_partial_blank_absent_and_limits(workspace):
    solve_all(workspace);eid=workspace.create_exam({'question_ids':[q['id'] for q in workspace.questions()],'points':[30,70],'confirm':True})
    sid=workspace.add_student({'name':'가상'});aid=workspace.assign(eid,[sid])[0];items=workspace.exam(eid)['items']
    r=grade(workspace,aid,{items[0]['id']:'1'},{items[0]['id']:15});assert r['score']==15
    assert [i['status'] for i in r['items']]==['partial','blank'] and r['correct_rate']==0
    with pytest.raises(ValueError):grade(workspace,aid,{}, {items[1]['id']:71})
    grade(workspace,aid,{},absent=True);assert report(workspace,aid)['score_rate'] is None

def test_equivalent_short_answer_and_undecidable(workspace):
    q=workspace.questions()[0];q['body']['answer_format']='short';q['answer']={'final_answer':'4/5'}
    assert auto_grade('0.8',q)==('correct',1)
    assert auto_grade('',q)==('blank',0)
    assert auto_grade('설명형 답',q)[0]=='pending'

def test_snapshot_backup_integrity(workspace,tmp_path):
    solve_all(workspace);archive=tmp_path/'backup.zip';workspace.backup(archive);dest=Store.restore(archive,tmp_path/'restored');restored=Store(dest)
    assert [q['fingerprint'] for q in restored.questions()]==[q['fingerprint'] for q in workspace.questions()]
    with pytest.raises(ValueError):Store.restore(archive,tmp_path/'restored')
    with zipfile.ZipFile(archive) as z:files={name:z.read(name) for name in z.namelist()}
    files['studio.sqlite']+=b'corruption'
    with zipfile.ZipFile(tmp_path/'bad.zip','w') as z:
        for name,value in files.items():z.writestr(name,value)
    with pytest.raises(ValueError):Store.restore(tmp_path/'bad.zip',tmp_path/'bad-restore')

def test_zip_traversal_rejected(tmp_path):
    with zipfile.ZipFile(tmp_path/'bad.hwpx','w') as z:z.writestr('../evil','x')
    with pytest.raises(ValueError):read_package(tmp_path/'bad.hwpx')

def test_native_hwp_conversion_audited(tmp_path):
    source=make_fixture(tmp_path/'a.hwpx',notes=True);native_fixture(source,tmp_path/'a.hwp');s=Store(tmp_path/'db');r=import_document(s,tmp_path/'a.hwp')
    assert r['audit']['formula_preserved'] and r['audit']['text_preserved'] and r['total']==2

def test_backup_cannot_escape_root(tmp_path):
    with zipfile.ZipFile(tmp_path/'bad.zip','w') as z:z.writestr('manifest.json',json.dumps({'files':{'../evil':'hash'}}))
    with pytest.raises(ValueError):Store.restore(tmp_path/'bad.zip',tmp_path/'restore')

def test_jobs_resume_and_cancel_without_duplicate(tmp_path):
    s=Store(tmp_path/'db');make_fixture(tmp_path/'a.hwpx');jobs=Jobs(s);jid=jobs.start('import',[str(tmp_path/'a.hwpx')]);deadline=time.monotonic()+10
    while jid in jobs.stops and time.monotonic()<deadline:time.sleep(.03)
    assert len(s.questions())==2
    assert s.rows('SELECT state FROM jobs WHERE id=?',(jid,))[0]['state']=='completed'
    jobs.close()

def test_ai_failure_is_real(monkeypatch):
    from studio import ai
    monkeypatch.setattr(ai.shutil,'which',lambda _:None)
    assert not ai.connect({'provider':'codex'})['ok']
    with pytest.raises(ValueError):ai.request({'provider':'codex'},'문제')

def test_ai_blind_conflict_blocks_release(workspace):
    q=workspace.questions()[0];a=check_question(q,{'final_answer':'2','steps':[],'blind_answer':'3'})
    assert a['verification']=='failed'
