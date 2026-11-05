import copy
import csv
import json
from pathlib import Path
import threading
import zipfile
import pytest
from hwpx import HwpxDocument
from mathbank.store import Store
from mathbank.hwpx import import_hwpx, Package, walk_blocks
from mathbank.equations import parse, render, from_latex, UnsupportedEquation
from mathbank.solver import safe_expr, equivalent, solve_exact, verify_candidate
from mathbank.pipeline import Pipeline
from mathbank.provider import ProviderError
from mathbank.validation import printable
from mathbank.output import make_exam
from mathbank.publishing import export_pdf, export_hwpx, export_report_pdf
from mathbank.workflows import import_quick_answers
from mathbank import study


def source_hwpx(path):
    doc = HwpxDocument.new()
    doc.paragraphs[0].text = '1. 방정식 '
    doc.paragraphs[0].add_equation('x+3=7')
    doc.paragraphs[0].add_run('의 모든 실근을 구하시오.')
    p = doc.add_paragraph('2. 방정식 ')
    p.add_equation('x^2-5x+6=0'); p.add_run('의 모든 실근을 구하시오.')
    p = doc.add_paragraph('3. 다항식 ')
    p.add_equation('x^2+2x+1'); p.add_run('에서 '); p.add_equation('x=3'); p.add_run('일 때의 값을 구하시오.')
    p = doc.add_paragraph('4. 방정식 ')
    p.add_equation('{x} over {2}=3'); p.add_run('의 모든 실근을 구하시오.')
    doc.add_paragraph('5. 다음 표의 값을 이용하여 물음에 답하시오.')
    table = doc.add_table(2, 2, width=30000)
    table.cell(0,0).text = '입력'; table.cell(0,1).text = '출력'
    table.cell(1,0).text = '2'; table.cell(1,1).text = '4'
    p = doc.add_paragraph('6. 다음 적분을 계산하시오. ')
    p.add_equation('int _0 ^1 x dx')
    doc.save_to_path(path); doc.close()
    return path


@pytest.fixture
def hwpx_bank(tmp_path):
    store = Store(tmp_path/'bank')
    result = import_hwpx(store, source_hwpx(tmp_path/'questions.hwpx'), '중등 수학')
    return store, result


def run_local(store, ids):
    for identifier in ids:
        q = store.question(identifier)
        store.enqueue('local_solve', identifier, q['version'])
    Pipeline(store, None).run()


def test_problem_only_import_and_classification_without_ai(hwpx_bank):
    store, result = hwpx_bank
    assert result['saved'] == 6
    assert result['ready_input'] == 5
    assert result['held'] == 1
    first = store.question(result['question_ids'][0])
    assert first['content']['answer'] == '' and first['content']['solution'] == []
    assert first['content']['storage_status'] == 'saved'
    assert first['content']['answer_status'] == 'missing'
    assert first['content']['unit'] == '방정식'
    assert first['content']['origins']['answer']['kind'] == 'missing'
    assert store.questions(search='방정식')[1] == 3
    assert not printable(first)
    assert any(b['type']=='equation' and b['ast'] for b in walk_blocks(first['content']['blocks']))
    original = store.root/store.document(result['document_id'])['path']
    assert import_hwpx(store, original)['added'] is False
    assert store.questions()[1] == 6


def test_exact_re_solve_variants_exam_grading_report_restore(hwpx_bank, tmp_path):
    store, result = hwpx_bank
    ids = result['question_ids'][:4]
    run_local(store, ids)
    assert [store.question(i)['content']['answer'] for i in ids] == ['4','2, 3','16','6']
    assert all(printable(store.question(i), 'solutions') for i in ids)
    parent = store.question(ids[1])
    for kind in ('numeric','thinking'): store.enqueue('variant_local_'+kind, parent['id'], parent['version'])
    Pipeline(store,None).run()
    with store.connect() as db:
        children = [r[0] for r in db.execute('SELECT question_id FROM lineage')]
    assert len(children) == 2
    assert all(printable(store.question(i), 'solutions') for i in children)
    exam_id = study.assemble(store, ids+children, '통합 검증 시험', settings={'student':'검증 학생','date':'2026-11-05'})
    exam = store.record(exam_id)
    export_pdf(store,exam,tmp_path/'questions.pdf')
    export_pdf(store,exam,tmp_path/'answers.pdf','answers')
    export_pdf(store,exam,tmp_path/'solutions.pdf','solutions')
    export_hwpx(store,exam,tmp_path/'editable.hwpx')
    with zipfile.ZipFile(tmp_path/'editable.hwpx') as z:
        body=z.read('Contents/section0.xml').decode()
        assert 'equation' in body and 'script' in body and '정답:' not in body
    student = store.put_record('student',{'name':'검증 학생','school':'중등','grade':'2','class':'A'})
    attempt = study.assign(store, student, exam_id)
    answers = [q['content']['answer'] for q in exam['questions']]
    answers[0]='8/2'; answers[1]='0'; answers[2]=''
    report_id = study.grade_attempt(store,attempt,answers,manual={3:2.5})
    report=store.record(report_id)
    assert [g['status'] for g in report['grades'][:4]]==['O','X','—','부분점수']
    export_report_pdf(store,report,tmp_path/'report.pdf')
    wrong = store.record(study.remediation(store,attempt))
    assert len(wrong['questions']) == 3
    before=store.record(exam_id)
    q=store.question(ids[0]); edited=copy.deepcopy(q['content']); edited['answer']='99'
    store.update_question(q['id'],q['version'],edited,q['stages'],manual=True)
    assert not printable(store.question(ids[0]))
    assert store.record(exam_id)==before
    assert store.record(report_id)==report
    attempt2=study.assign(store,student,exam_id)
    assert study.attempt(store,attempt2)['round']==2
    study.grade_attempt(store,attempt2,[],absent=True)
    assert study.attempt(store,attempt2)['status']=='absent'
    backup=tmp_path/'backup.zip'; store.backup(backup)
    restored=Store.restore(backup,tmp_path/'restored')
    assert restored.record(report_id)==report
    assert restored.question(children[0])==store.question(children[0])


def test_supplied_answer_conflict_keeps_source_and_blocks_release(hwpx_bank,tmp_path):
    store,result=hwpx_bank
    doc=store.document(result['document_id'])
    path=tmp_path/'answers.csv'
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['source_sha256','number','answer']);w.writerow([doc['hash'],'1','5'])
    assert import_quick_answers(store,doc['id'],path)==1
    first=store.question(result['question_ids'][0])
    run_local(store,[first['id']])
    q=store.question(first['id'])
    assert q['content']['answer']=='5'
    assert q['content']['origins']['answer']['kind']=='source_quick_answer'
    assert q['content']['verification_status']=='failed'
    assert not printable(q)
    with pytest.raises(ValueError): make_exam(store,[q['id']],'차단')
    path.write_text(path.read_text().replace(doc['hash'],'0'*64))
    with pytest.raises(ValueError,match='해시'): import_quick_answers(store,doc['id'],path)
    backup=tmp_path/'backup.zip';store.backup(backup);restored=Store.restore(backup,tmp_path/'restored')
    assert (restored.root/q['content']['origins']['answer']['path']).is_file()


def test_no_policy_is_held_and_ai_failure_not_faked(hwpx_bank):
    store,result=hwpx_bank
    run_local(store,[result['question_ids'][4]])
    q=store.question(result['question_ids'][4])
    assert q['content']['verification_status']=='held' and not printable(q)
    class Unavailable:
        def call(self,*args): raise ProviderError('연결 없음')
    first=store.question(result['question_ids'][0])
    store.enqueue('ai_solve',first['id'],first['version'])
    Pipeline(store,Unavailable()).run()
    assert store.jobs()[0]['status']=='paused'
    assert store.question(first['id'])['content']['answer']==''


def test_ai_resolve_does_not_receive_proposal_or_reference(hwpx_bank):
    store,result=hwpx_bank
    class Provider:
        model='test-only'
        def __init__(self):self.prompts=[]
        def call(self,prompt,images,cancel):
            self.prompts.append(prompt)
            return {'answer':'4','solution':['제안 해설 UNIQUE_SECRET_PROPOSAL'],'uncertain':False}
    provider=Provider()
    qid=result['question_ids'][0];store.enqueue('ai_solve',qid,1);Pipeline(store,provider).run()
    q=store.question(qid)
    assert len(provider.prompts)==2
    assert 'UNIQUE_SECRET_PROPOSAL' not in provider.prompts[1]
    assert printable(q,'solutions')
    assert q['content']['proposal_origin']['kind']=='ai_generated'
    assert q['content']['origins']['solution']['kind']=='exact_calculation'
    assert 'UNIQUE_SECRET_PROPOSAL' not in ''.join(q['content']['solution'])


def test_safe_expression_and_math_equivalence():
    assert equivalent('1/2','2/4') is True
    assert equivalent('sqrt(8)/2','sqrt(2)') is True
    assert equivalent('2,3','3,2') is True
    assert equivalent('복잡한 논증','다른 논증') is None
    for s in ["__import__('os').system('id')",'1/0','2**1000000','1/x']:
        with pytest.raises(ValueError):safe_expr(s)
    tree=parse('{x^2+1} over {sqrt {2}}')
    assert '\\frac' in render(tree,'latex') and 'frac(' in render(tree,'typst')
    assert render(from_latex(r'\frac{x+1}{2}'),'hwp')
    with pytest.raises(UnsupportedEquation):parse('int _0 ^1 x dx')


def test_spine_order_instead_of_section_filename(tmp_path):
    path=source_hwpx(tmp_path/'source.hwpx')
    with zipfile.ZipFile(path) as z: files={n:z.read(n) for n in z.namelist()}
    xml=files['Contents/section0.xml']
    files['Contents/section0.xml']=xml.replace(b'1. ',b'2. ',1)
    files['Contents/section9.xml']=xml.replace(b'1. ',b'1. ',1)
    hpf=files['Contents/content.hpf'].decode()
    # Only package-order behavior is tested; reused text is not claimed as real input.
    import re
    section_item=re.search(r'<[^>]*item\b[^>]*id="section0"[^>]*/>',hpf).group()
    item=section_item.replace('section0','section9')
    hpf=hpf.replace(section_item,section_item+item)
    itemref=re.search(r'<[^>]*itemref\b[^>]*idref="section0"[^>]*/>',hpf).group()
    hpf=hpf.replace(itemref,itemref.replace('section0','section9')+itemref)
    files['Contents/content.hpf']=hpf.encode()
    altered=tmp_path/'ordered.hwpx'
    with zipfile.ZipFile(altered,'w') as z:
        for name,data in files.items():z.writestr(name,data)
    p=Package(altered)
    assert p.sections==['Contents/section9.xml','Contents/section0.xml'];p.close()


def test_cancel_import_is_atomic(tmp_path):
    store=Store(tmp_path/'bank');event=threading.Event();event.set()
    with pytest.raises(ValueError,match='취소'):import_hwpx(store,source_hwpx(tmp_path/'q.hwpx'),cancel=event)
    assert store.documents()==[] and store.questions()[1]==0


def test_zip_path_and_entity_rejected(tmp_path):
    path=tmp_path/'bad.hwpx'
    with zipfile.ZipFile(path,'w') as z:z.writestr('../outside','bad')
    with pytest.raises(ValueError):Package(path)
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('mimetype','application/hwp+zip')
        z.writestr('Contents/content.hpf','<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><x>&a;</x>')
    with pytest.raises(Exception):Package(path)


def test_retry_variant_is_idempotent(hwpx_bank):
    store,result=hwpx_bank
    qid=result['question_ids'][0]
    jobid=store.enqueue('variant_local_numeric',qid,1)
    Pipeline(store,None).run()
    store.job_status(jobid,'queued');Pipeline(store,None).run()
    with store.connect() as db:assert db.execute('SELECT count(*) FROM lineage').fetchone()[0]==1


def test_boundary_correction_preserves_old_snapshot(hwpx_bank):
    from mathbank.editing import merge_questions, split_question
    store,result=hwpx_bank
    ids=result['question_ids'][:2]
    run_local(store,ids)
    exam_id=make_exam(store,ids,'이전 시험');snapshot=store.record(exam_id)
    merged=merge_questions(store,ids)[0]
    assert all(store.is_trashed(store.question(i)) for i in ids)
    assert store.record(exam_id)==snapshot
    assert store.question(merged)['content']['answer']==''
    split=split_question(store,merged,1)
    assert len(split)==2 and store.questions()[1]==6
    assert all(not printable(store.question(i)) for i in split)


def test_only_real_thinking_changes_receive_relation_pass():
    from mathbank.solver import variant_relation
    parent={'text':'방정식 $x^2-5x+6=0$의 모든 실근을 구하시오.'}
    numeric={'text':'방정식 $x^2-4x+3=0$의 모든 실근을 구하시오.'}
    inverse={'text':'방정식 $x^2-5x+a=0$의 한 실근이 $x=2$일 때, 상수 $a$의 값을 구하시오.'}
    assert variant_relation(parent,numeric,'numeric')['state']=='passed'
    assert variant_relation(parent,numeric,'thinking')['state']=='held'
    assert variant_relation(parent,inverse,'thinking')['state']=='passed'


def test_editable_unsupported_equation_preserved_only_in_draft(hwpx_bank,tmp_path):
    store,result=hwpx_bank
    qid=result['question_ids'][-1]
    with pytest.raises(ValueError):make_exam(store,[qid],'차단')
    draft=store.record(make_exam(store,[qid],'원문 수식 유지',mode='draft'))
    export_hwpx(store,draft,tmp_path/'raw-equation.hwpx')
    with zipfile.ZipFile(tmp_path/'raw-equation.hwpx') as z:assert 'int _0 ^1 x dx' in z.read('Contents/section0.xml').decode()
    with pytest.raises(ValueError,match='미지원 수식'):export_pdf(store,draft,tmp_path/'no-loss.pdf')
    assert not (tmp_path/'no-loss.pdf').exists()


def test_new_students_have_class_membership_and_packets(hwpx_bank,tmp_path):
    store,result=hwpx_bank;ids=result['question_ids'][:1];run_local(store,ids)
    student=study.save_student(store,{'name':'학생','class':'A','school':'중등','grade':'2'})
    with store.connect() as db:assert db.execute('SELECT count(*) FROM memberships WHERE student_id=?',(student,)).fetchone()[0]==1
    exam=study.assemble(store,ids,'개별 출력')
    a=study.assign(store,student,exam)
    packet=study.student_packet(store,a,tmp_path/'packets')
    assert len(list(packet.glob('*.pdf')))==3 and len(list(packet.glob('*.hwpx')))==3
    with store.connect() as db:assert db.execute('SELECT count(*) FROM distributions WHERE attempt_id=?',(a,)).fetchone()[0]==6
    with pytest.raises(ValueError):study.grade_attempt(store,a,['4'],manual={0:float('nan')})


def test_input_conflicts_and_duplicate_mc_choices_do_not_pass():
    c={'text':'방정식 $x+3=7$의 모든 실근을 구하시오.','input_status':'complete','choices':['4','4','5']}
    assert verify_candidate(c,'1')['state']=='failed'
    c['choices']=[]
    assert verify_candidate(c,'4','5')['state']=='held'
    c['input_status']='held'
    assert verify_candidate(c,'4')['state']=='held'


def test_exact_root_count_and_empty_real_roots():
    for formula,answer in [('x^2+1=0','없음'),('x^2-2x+1=0','1'),('x^2-2=0','-sqrt(2),sqrt(2)')]:
        c={'text':f'방정식 ${formula}$의 모든 실근을 구하시오.','input_status':'complete','choices':[]}
        result=verify_candidate(c,answer)
        assert result['state']=='passed',result
    c={'text':'방정식 $1/(x-1)=0$의 모든 실근을 구하시오.','input_status':'complete'}
    assert verify_candidate(c,'없음')['state']=='held'


def test_uncertain_ai_variant_never_becomes_automatically_usable(hwpx_bank):
    store,result=hwpx_bank
    class Provider:
        model='test-only'
        def call(self,*args):
            return {'text':'방정식 $x+4=9$의 모든 실근을 구하시오.','choices':[],
                'answer':'5','solution':['x=5'],'uncertain':True,'changes':'상수 변경',
                'objective':'일차방정식 연습','unit':'방정식','difficulty':3}
    store.enqueue('variant_ai_numeric',result['question_ids'][0],1)
    Pipeline(store,Provider()).run()
    with store.connect() as db:child=db.execute('SELECT question_id FROM lineage').fetchone()[0]
    q=store.question(child)
    assert q['content']['input_status']=='held' and not printable(q)
