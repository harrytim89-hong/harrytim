import copy
import json
import time
import zipfile
from pathlib import Path
import pytest
from lxml import etree as E
from hwpx import HwpxDocument
from studio.storage import Store
from studio.importers import import_document
from studio.boundaries import prefix,visible_text
from studio.splitting import split_saved
from studio.model import plain_text,paragraphs
from studio.fixtures import make_fixture,native_fixture
from studio.exports import export_packet
from studio.service import Service

HP='http://www.hancom.co.kr/hwpml/2011/paragraph'
HH='http://www.hancom.co.kr/hwpml/2011/head'

def questions(path,markers=('1.','2.'),choices=True,table=False,notes=None):
    doc=HwpxDocument.new();doc.paragraphs[0].text='새 입력 검사 자료'
    if table:
        tbl=doc.add_table(1,len(markers),width=45000);cells=[tbl.cell(0,i) for i in range(len(markers))]
    for index,marker in enumerate(markers):
        add=cells[index].add_paragraph if table else doc.add_paragraph
        p=add(marker+'다음 식의 값을 구하시오.');p.add_equation(f'x+{index+2}')
        if notes:doc.notes.add_endnote(str(index+1),paragraph=p)
        if choices:
            for j in range(5):
                p=add('①②③④⑤'[j]+' ');p.add_equation(str(j+index))
    doc.save_to_path(path);return Path(path)

def rewrite(path,fn):
    with zipfile.ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
    fn(files)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)

@pytest.mark.parametrize('markers,numbers',[
    (('1.','2.'),[1,2]),(('01.','02.'),[1,2]),(('21.','22.'),[21,22]),
    (('1)','2)'),[1,2]),(('[1]','[2]'),[1,2]),(('(1)','(2)'),[1,2]),
    (('문제 1','문제 2'),[1,2]),(('[문제 01]','[문제 02]'),[1,2]),
    (('【1】','【2】'),[1,2]),(('1．','2．'),[1,2]),(('3.','8.'),[3,8]),
])
def test_number_formats_do_not_require_source_edits(tmp_path,markers,numbers):
    path=questions(tmp_path/'q.hwpx',markers);before=path.read_bytes();store=Store(tmp_path/'db')
    result=import_document(store,path)
    assert result['total']==2 and result['complete']==2,result
    qs=store.questions();assert [q['source']['number'] for q in qs]==numbers
    assert all(len(q['body']['choices'])==5 for q in qs)
    assert path.read_bytes()==before

def test_single_question_is_accepted(tmp_path):
    store=Store(tmp_path/'db');r=import_document(store,questions(tmp_path/'one.hwpx',('7.',)))
    assert r['total']==1 and r['complete']==1

def test_multiple_choice_then_short_answers_restart_numbering(tmp_path):
    source=questions(tmp_path/'mixed.hwpx',('1.','2.','[서답형1]','[서답형2]'))
    s=Store(tmp_path/'db');r=import_document(s,source)
    assert r['total']==4 and r['complete']==4,r
    assert [q['source']['number'] for q in s.questions()]==[1,2,1,2]

def test_real_line_breaks_preserve_equations(tmp_path):
    path=questions(tmp_path/'lines.hwpx')
    def combine(files):
        root=E.fromstring(files['Contents/section0.xml']);ps=list(root)[1:]
        for p in ps:root.remove(p)
        merged=E.SubElement(root,f'{{{HP}}}p')
        for index,p in enumerate(ps):
            if index:
                run=E.SubElement(merged,f'{{{HP}}}run');t=E.SubElement(run,f'{{{HP}}}t');E.SubElement(t,f'{{{HP}}}lineBreak')
            for child in p:
                if child.tag.rsplit('}',1)[-1]=='run':merged.append(child)
        files['Contents/section0.xml']=E.tostring(root)
    rewrite(path,combine);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['total']==2 and r['complete']==2,r
    assert sum(b['kind']=='math' for q in s.questions() for b in paragraphs(q['body']['blocks']))==2
    assert all(len(q['body']['choices'])==5 for q in s.questions())

def test_table_layout_is_read_in_actual_cell_order(tmp_path):
    store=Store(tmp_path/'db');r=import_document(store,questions(tmp_path/'table.hwpx',table=True))
    assert r['total']==2 and r['complete']==2,r
    assert all('/table/' in q['source']['locations'][0] for q in store.questions())
    assert all(len(q['body']['choices'])==5 for q in store.questions())

def test_unnumbered_table_can_be_reviewed_by_paragraph(tmp_path):
    path=questions(tmp_path/'table.hwpx',('', ''),table=True);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['boundary_review']==1 and r['held']==1
    q=s.questions()[0];starts=[i for i,b in enumerate(q['body']['blocks']) if '다음 식' in plain_text([b])]
    assert len(starts)==2
    result=split_saved(s,q['id'],q['revision'],starts);assert result['complete']==2

def test_unmarked_first_question_is_not_discarded_as_preamble(tmp_path):
    path=questions(tmp_path/'partial.hwpx',('', '2.'));s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['total']==2 and r['held']==1 and r['complete']==1,r
    assert 'x + 2' in s.questions()[0]['search_text']
    assert s.questions()[1]['source']['number']==2

def test_text_box_layout(tmp_path):
    path=questions(tmp_path/'boxes.hwpx')
    def box(files):
        root=E.fromstring(files['Contents/section0.xml']);ps=list(root)[1:]
        for p in ps:root.remove(p)
        outer=E.SubElement(root,f'{{{HP}}}p');run=E.SubElement(outer,f'{{{HP}}}run');rect=E.SubElement(run,f'{{{HP}}}rect');draw=E.SubElement(rect,f'{{{HP}}}drawText');sub=E.SubElement(draw,f'{{{HP}}}subList')
        for p in ps:sub.append(p)
        files['Contents/section0.xml']=E.tostring(root)
    rewrite(path,box);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['total']==2 and r['complete']==2,r
    assert '/textbox/' in s.questions()[0]['source']['locations'][0]

def test_paragraph_numbering_from_header(tmp_path):
    path=questions(tmp_path/'numbering.hwpx',('', ''))
    def numbered(files):
        header=E.fromstring(files['Contents/header.xml']);para=next(n for n in header.iter() if n.tag.rsplit('}',1)[-1]=='paraPr')
        copied=copy.deepcopy(para);copied.set('id','901')
        for n in list(copied):
            if n.tag.rsplit('}',1)[-1]=='heading':copied.remove(n)
        E.SubElement(copied,f'{{{HH}}}heading',type='NUMBER',idRef='901',level='0');para.getparent().append(copied)
        refs=next(n for n in header.iter() if n.tag.rsplit('}',1)[-1]=='refList');ns=E.SubElement(refs,f'{{{HH}}}numberings');n=E.SubElement(ns,f'{{{HH}}}numbering',id='901',start='41');E.SubElement(n,f'{{{HH}}}paraHead',level='1',start='41').text='^1.'
        root=E.fromstring(files['Contents/section0.xml'])
        for p in root:
            if '다음 식' in visible_text(p):p.set('paraPrIDRef','901')
        files['Contents/header.xml']=E.tostring(header);files['Contents/section0.xml']=E.tostring(root)
    rewrite(path,numbered);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['complete']==2 and [q['source']['number'] for q in s.questions()]==[41,42],r

def test_circled_choice_numbering_is_not_a_question_series(tmp_path):
    path=questions(tmp_path/'choices.hwpx')
    def format_choices(files):
        header=E.fromstring(files['Contents/header.xml']);para=next(n for n in header.iter() if n.tag.rsplit('}',1)[-1]=='paraPr')
        copied=copy.deepcopy(para);copied.set('id','902')
        for n in list(copied):
            if n.tag.rsplit('}',1)[-1]=='heading':copied.remove(n)
        E.SubElement(copied,f'{{{HH}}}heading',type='NUMBER',idRef='902',level='0');para.getparent().append(copied)
        refs=next(n for n in header.iter() if n.tag.rsplit('}',1)[-1]=='refList');ns=E.SubElement(refs,f'{{{HH}}}numberings');num=E.SubElement(ns,f'{{{HH}}}numbering',id='902',start='1');E.SubElement(num,f'{{{HH}}}paraHead',level='1',start='1',numFormat='CIRCLED_DIGIT').text='^1'
        root=E.fromstring(files['Contents/section0.xml'])
        for p in root:
            if visible_text(p).strip().startswith(tuple('①②③④⑤')):p.set('paraPrIDRef','902')
        files['Contents/header.xml']=E.tostring(header);files['Contents/section0.xml']=E.tostring(root)
    rewrite(path,format_choices);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['total']==2 and r['complete']==2
    assert all(len(q['body']['choices'])==5 for q in s.questions())

def test_question_labels_stored_as_equations(tmp_path):
    from hwpx import HwpxDocument
    doc=HwpxDocument.new();doc.paragraphs[0].text='수식 번호 자료'
    for i in range(1,3):
        p=doc.add_paragraph();p.add_equation(str(i)+'.');p.add_run('다음 식의 값을 구하시오.');p.add_equation('x+2')
    path=tmp_path/'math-label.hwpx';doc.save_to_path(path);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['complete']==2 and r['total']==2,r
    assert [q['source']['number'] for q in s.questions()]==[1,2]
    assert sum(b['kind']=='math' for q in s.questions() for b in paragraphs(q['body']['blocks']))==2

def test_decimal_and_caption_are_not_question_boundaries(tmp_path):
    path=questions(tmp_path/'q.hwpx')
    def insert(files):
        root=E.fromstring(files['Contents/section0.xml']);p=E.Element(f'{{{HP}}}p');run=E.SubElement(p,f'{{{HP}}}run');E.SubElement(run,f'{{{HP}}}t').text='0.8은 소수이다.'
        ctrl=E.SubElement(run,f'{{{HP}}}ctrl');E.SubElement(ctrl,f'{{{HP}}}autoNum',num='3',numType='PICTURE');root.insert(2,p);files['Contents/section0.xml']=E.tostring(root)
    rewrite(path,insert);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['total']==2 and '0.8' in s.questions()[0]['search_text']

def test_number_split_between_runs(tmp_path):
    path=questions(tmp_path/'q.hwpx')
    def split(files):
        root=E.fromstring(files['Contents/section0.xml'])
        for p in root:
            mark=prefix(p)
            if not mark:continue
            t=next(n for n in p.iter() if n.tag.rsplit('}',1)[-1]=='t');text=t.text;t.text=text[1:]
            run=E.Element(f'{{{HP}}}run');E.SubElement(run,f'{{{HP}}}t').text=text[0];p.insert(0,run)
        files['Contents/section0.xml']=E.tostring(root)
    rewrite(path,split);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['complete']==2
    assert all(not q['search_text'].lstrip().startswith('.') for q in s.questions())

def test_answer_notes_without_mc_choices(tmp_path):
    doc=HwpxDocument.new();doc.paragraphs[0].text='단답형 검사'
    for i in range(2):
        p=doc.add_paragraph();doc.notes.add_endnote(str(i+1),paragraph=p)
        p=doc.add_paragraph('다음 식을 계산하시오.');p.add_equation(f'{i}+1')
    path=tmp_path/'short.hwpx';doc.save_to_path(path);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['complete']==2 and [q['original_answer'] for q in s.questions()]==['1','2']

def test_only_bound_answer_notes_are_removed(tmp_path):
    path=make_fixture(tmp_path/'notes.hwpx',notes=True)
    def ordinary(files):
        root=E.fromstring(files['Contents/section0.xml']);p=list(root)[3];run=E.SubElement(p,f'{{{HP}}}run');ctrl=E.SubElement(run,f'{{{HP}}}ctrl');note=E.SubElement(ctrl,f'{{{HP}}}footNote',number='9');sub=E.SubElement(note,f'{{{HP}}}subList');para=E.SubElement(sub,f'{{{HP}}}p');r=E.SubElement(para,f'{{{HP}}}run');E.SubElement(r,f'{{{HP}}}t').text='출제 조건에 대한 참고 설명'
        files['Contents/section0.xml']=E.tostring(root)
    rewrite(path,ordinary);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['total']==2
    assert any(b['kind']=='note' for b in paragraphs(s.questions()[0]['body']['blocks']))
    assert '참고 설명' in s.questions()[0]['search_text']

def test_unknown_boundaries_are_saved_and_can_be_split(tmp_path):
    source=questions(tmp_path/'unnumbered.hwpx',('', ''));s=Store(tmp_path/'db');r=import_document(s,source)
    assert r['total']==1 and r['held']==1 and r['boundary_review']==1
    parent=s.questions()[0];assert not parent['available'] and parent['original_answer'] is None
    starts=[i for i,b in enumerate(parent['body']['blocks']) if '다음 식' in plain_text([b])]
    result=split_saved(s,parent['id'],parent['revision'],starts)
    assert result['total']==2 and result['complete']==2
    children=s.questions();assert len(children)==2 and all(len(q['body']['choices'])==5 for q in children)
    assert s.question(parent['id'])['trashed'] and len(s.questions(True))==3
    assert s.documents()[0]['report']['held']==0
    assert len(s.documents()[0]['report']['boundary_history'][0]['preamble_blocks'])==1
    assert import_document(s,source)['duplicate']
    with pytest.raises(ValueError):split_saved(s,parent['id'],parent['revision'],starts)
    eid=s.create_exam({'question_ids':[q['id'] for q in children],'confirm':False})
    assert Path(export_packet(s,eid,fmt='hwpx')).is_file()
    assert Path(export_packet(s,eid,fmt='pdf')).is_file()

def test_review_never_auto_distributes(tmp_path):
    s=Store(tmp_path/'db');import_document(s,questions(tmp_path/'q.hwpx',('', '')));q=s.questions()[0]
    with pytest.raises(ValueError):s.create_exam({'question_ids':[q['id']],'confirm':True})
    with pytest.raises(ValueError):split_saved(s,q['id'],q['revision'],[-1])
    with pytest.raises(ValueError):split_saved(s,q['id'],q['revision'],[1,1])
    with pytest.raises(ValueError):split_saved(s,q['id'],q['revision']+1,[1])

def test_native_non_one_start(tmp_path):
    path=questions(tmp_path/'q.hwpx',('51.', '52.'));native_fixture(path,tmp_path/'q.hwp');s=Store(tmp_path/'db');r=import_document(s,tmp_path/'q.hwp')
    assert r['total']==2 and r['complete']==2

def test_saved_review_is_not_reported_as_failed_file(tmp_path):
    source=questions(tmp_path/'q.hwpx',('', ''));s=Store(tmp_path/'db');service=Service(s);jid=service.jobs.start('import',[str(source)]);deadline=time.monotonic()+10
    while jid in service.jobs.stops and time.monotonic()<deadline:time.sleep(.02)
    job=s.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0]
    assert job['failed']==0 and '저장 보류 1문항' in job['detail'] and '원문 저장 완료' in job['detail']
    assert '작업 실패' not in job['detail'];service.jobs.close()
