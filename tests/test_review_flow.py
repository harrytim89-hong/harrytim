import copy
import json
import zipfile
from pathlib import Path
import pytest
from lxml import etree as E
from studio.storage import Store
from studio.fixtures import make_fixture
from studio.importers import import_document
from studio.model import plain_text
from studio.reasoning import check_question
from studio.proofreading import inspect,run,apply,dismiss,latest
from studio.review import summary,source,undo_reparse
from studio.splitting import split_saved
from studio.boundaries import suggest_blocks

@pytest.fixture
def case(tmp_path):
    store=Store(tmp_path/'db');path=make_fixture(tmp_path/'q.hwpx');r=import_document(store,path)
    yield store,path,r
    store.db.close()

def mutate_zip(path,change):
    with zipfile.ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
    change(files)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for n,data in files.items():z.writestr(n,data)

def unnumber(path):
    def change(files):
        root=E.fromstring(files['Contents/section0.xml'])
        for n in root.iter():
            if n.tag.rsplit('}',1)[-1]=='t' and n.text in ('1. ','2. '):n.text=''
        files['Contents/section0.xml']=E.tostring(root)
    mutate_zip(path,change)

def test_guidance_advances_from_import_through_confirmed_exam(case):
    s,_,r=case;did=r['document_id'];first=summary(s,did)
    assert first['next_action']=='explain' and first['counts']['mc']==2
    for q in s.questions():s.save_answer(q['id'],q['revision'],q['fingerprint'],check_question(q))
    after=summary(s,did);assert after['next_action']=='compose' and after['counts']['ready']==2
    eid=s.create_exam({'question_ids':after['ready_ids'],'confirm':True,'settings':{'source_document_id':did}})
    assert summary(s,did)['next_action']=='exam' and summary(s,did)['last_exam_id']==eid

def test_typo_findings_are_real_and_not_silent_corrections(case):
    s,path,r=case;q=s.questions()[1];body=copy.deepcopy(q['body'])
    text=next(b for p in body['blocks'] for b in p.get('blocks',[]) if b['kind']=='text' and '최댓값은' in b['value'])
    text['value']=text['value'].replace('최댓값은','최댓값은은')
    s.revise(q['id'],{'body':body});q=s.question(q['id']);before=copy.deepcopy(q['body']);original_bytes=path.read_bytes()
    report=run(s,q['id']);assert report['count']==1 and report['findings'][0]['rule']=='repeated_particle'
    assert s.question(q['id'])['body']==before and path.read_bytes()==original_bytes
    assert summary(s,r['document_id'])['next_action']=='proofreading'
    found=report['findings'][0];fixed=apply(s,q['id'],q['revision'],found['id'])
    current=s.question(q['id']);assert current['revision']==q['revision']+1 and '값은은' not in current['search_text']
    assert current['answer'] is None and not current['available']
    assert fixed['review']['count']==0 and path.read_bytes()==original_bytes

def test_broken_character_blocks_usage(case):
    s,_,_=case;q=s.questions()[0];a=check_question(q);s.save_answer(q['id'],q['revision'],q['fingerprint'],a)
    assert s.question(q['id'])['available']
    report={'findings':[]}
    body=copy.deepcopy(q['body']);body['blocks'][0]['blocks'].append({'kind':'text','value':'\ufffd'})
    s.revise(q['id'],{'body':body});q=s.question(q['id']);assert q['text_review']['blocking']==1
    s.save_answer(q['id'],q['revision'],q['fingerprint'],{'final_answer':'2','steps':[{'title':'test','blocks':[]}],'verification':'passed','proof':{}})
    assert not s.question(q['id'])['available']
    with pytest.raises(ValueError):dismiss(s,q['id'],q['revision'],q['text_review']['findings'][0]['id'])

def test_dismiss_false_positive_is_saved_for_current_revision(case):
    s,_,_=case;q=s.questions()[0];body=copy.deepcopy(q['body']);body['blocks'][0]['blocks'].append({'kind':'text','value':' 다음 다음'})
    s.revise(q['id'],{'body':body});q=s.question(q['id']);reviewed=run(s,q['id']);assert reviewed['count']==1
    result=dismiss(s,q['id'],q['revision'],reviewed['findings'][0]['id']);assert result['count']==0
    assert latest(s,q['id'],q['revision'])['findings'][0]['dismissed']
    assert '다음 다음' in s.question(q['id'])['search_text']

def test_stale_typo_correction_is_rejected(case):
    s,_,_=case;q=s.questions()[0];s.revise(q['id'],{'difficulty':7})
    with pytest.raises(ValueError):apply(s,q['id'],q['revision'],'unknown','수정')

def test_source_view_comes_from_immutable_managed_file(case):
    s,path,_=case;q=s.questions()[0];original=source(s,q);assert original['kind']=='extracted_source'
    assert '3x' in plain_text(original['blocks']).replace(' ','')
    body=copy.deepcopy(q['body']);body['blocks'].append({'kind':'paragraph','blocks':[{'kind':'text','value':'선생님 수정 내용'}]})
    s.revise(q['id'],{'body':body});path.unlink();raw=source(s,s.question(q['id']))
    assert '선생님 수정 내용' not in plain_text(raw['blocks']) and raw['locations']

def test_reparse_is_reversible_and_preserves_exam_snapshots(case):
    s,path,r=case;did=r['document_id'];ids=[q['id'] for q in s.questions()]
    eid=s.create_exam({'question_ids':ids,'confirm':False});before=copy.deepcopy(s.exam(eid))
    q=s.question(ids[0]);body=copy.deepcopy(q['body']);body['blocks'].append({'kind':'paragraph','blocks':[{'kind':'text','value':'직접 수정'}]});s.revise(q['id'],{'body':body})
    import_document(s,s.path(s.documents()[0]['path']),replace_document=did)
    assert s.question(ids[0])['trashed'] and not s.question(ids[1])['trashed']
    assert s.exam(eid)==before and summary(s,did)['has_repair_history']
    undo_reparse(s,did);assert not s.question(ids[0])['trashed'] and '직접 수정' in s.question(ids[0])['search_text']
    assert s.exam(eid)==before

def test_existing_bad_choice_splits_offer_automatic_repair(case):
    from studio.formula import equation
    from studio.model import encode
    s,path,r=case;did=r['document_id']
    for q in s.questions():s.trash('question',q['id'])
    with s.transaction() as db:
        for i in range(1,6):
            s.insert_question(db,{'body':{'blocks':[{'kind':'paragraph','blocks':[{'kind':'text','value':'① '},equation(str(i))]}],'choices':[],'answer_format':'short'},'source':{'number':i,'boundary_evidence':'paragraph-numbering'},'input_state':'complete'},did)
        doc=s.documents()[0];report={**doc['report'],'parser_version':2,'profile':'paragraph-numbering'};db.execute('UPDATE documents SET report=? WHERE id=?',(encode(report),did))
    assert summary(s,did)['next_action']=='reparse'
    import_document(s,s.path(s.documents()[0]['path']),replace_document=did)
    assert len(s.questions())==2 and summary(s,did)['next_action']=='explain'

def test_automatic_boundary_proposals_replace_hundreds_of_empty_checkboxes(tmp_path):
    path=make_fixture(tmp_path/'no-label.hwpx');unnumber(path);s=Store(tmp_path/'db');r=import_document(s,path)
    q=s.questions()[0];proposal=suggest_blocks(q['body']['blocks'])
    assert len(proposal['starts'])==2 and proposal['choice_cycles']==2
    result=split_saved(s,q['id'],q['revision'],proposal['starts']);assert result['complete']==2
    assert all(check_question(q)['verification']=='passed' for q in s.questions())

def test_question_numbering_does_not_require_a_quick_answer_in_notes(tmp_path):
    path=make_fixture(tmp_path/'empty-notes.hwpx',notes=True)
    def remove_answers(files):
        root=E.fromstring(files['Contents/section0.xml'])
        for n in root.iter():
            if n.tag.rsplit('}',1)[-1]=='endNote':
                for t in n.iter():
                    if t.tag.rsplit('}',1)[-1]=='t':t.text=''
        files['Contents/section0.xml']=E.tostring(root)
    mutate_zip(path,remove_answers);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['total']==2 and r['complete']==2 and r['answer_count']==0

def test_detailed_notes_do_not_block_question_storage(tmp_path):
    path=make_fixture(tmp_path/'notes.hwpx',notes=True)
    def detail(files):
        root=E.fromstring(files['Contents/section0.xml'])
        for n in root.iter():
            if n.tag.rsplit('}',1)[-1]=='endNote':
                for t in n.iter():
                    if t.tag.rsplit('}',1)[-1]=='t':t.text='해설 설명과 정답이 섞인 원본 주석'
        files['Contents/section0.xml']=E.tostring(root)
    mutate_zip(path,detail);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['total']==2 and r['complete']==2
    assert all(q['source']['answer_ambiguity'] and q['source']['original_note'] for q in s.questions())
    assert all(check_question(q)['verification']=='held' for q in s.questions())

def test_ai_proofreading_validates_the_exact_quote(case,monkeypatch):
    from studio import ai
    s,_,_=case;q=s.questions()[0]
    monkeypatch.setattr(ai,'request',lambda *a,**k:{'findings':[{'text_key':'0','start':0,'end':2,'original':'틀린 인용','suggestion':'수정','reason':'검사'}]})
    with pytest.raises(ValueError):ai.proofread(q,{'provider':'codex'})
    report=run(s,q['id'],{'provider':'codex'});assert report['ai_state']=='failed' and report['findings']==[]

def test_ai_connection_failure_does_not_claim_a_successful_review(case,monkeypatch):
    from studio import ai
    s,_,_=case;q=s.questions()[0]
    def fail(*a,**k):raise ValueError('연결할 수 없음')
    monkeypatch.setattr(ai,'proofread',fail)
    result=run(s,q['id'],{'provider':'codex'});assert result['ai_state']=='failed' and '연결할 수 없음' in result['ai_error']

def test_upgrade_preserves_old_data_and_takes_database_snapshot(tmp_path):
    import sqlite3
    s=Store(tmp_path/'db');s.add_student({'name':'보존 학생'})
    s.db.execute('DROP TABLE text_reviews');s.db.execute('DROP TABLE job_documents');s.db.execute('PRAGMA user_version=1');s.db.close()
    upgraded=Store(tmp_path/'db');assert upgraded.students()[0]['name']=='보존 학생'
    assert upgraded.db.execute('PRAGMA user_version').fetchone()[0]==2
    backups=list((tmp_path/'db/backups').glob('*.sqlite'));assert len(backups)==1
    old=sqlite3.connect(backups[0]);assert old.execute('PRAGMA user_version').fetchone()[0]==1
    assert old.execute('SELECT name FROM students').fetchone()[0]=='보존 학생';old.close();upgraded.db.close()

@pytest.mark.parametrize('text,rule',[('같은 같은 값','repeated_word'),('최댓값은은?','repeated_particle'),('값은??','repeated_punctuation'),('다음   문항','excess_spacing'),('잘못된 \ufffd 문자','broken_character')])
def test_rule_scope_is_explicit(text,rule):
    report=inspect({'blocks':[{'kind':'paragraph','blocks':[{'kind':'text','value':text}]}],'choices':[]})
    assert any(f['rule']==rule for f in report['findings'])
