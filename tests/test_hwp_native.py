import copy
import random
import zipfile
from pathlib import Path
import pytest
from hwpx import HwpxDocument
from hwpx.hwp5.writer import write_hwp5
from mathbank.store import Store
from mathbank.hwp_import import import_hwp, convert_audited
from mathbank.hwpx import import_hwpx, walk_blocks
from mathbank.equations import block,render,parse,from_latex
from mathbank.pipeline import Pipeline
from mathbank.validation import printable
from mathbank.exam_algebra import solve_exam,polynomial_variant,polynomial_relation


def native_fixture(tmp_path):
    doc=HwpxDocument.new()
    doc.paragraphs[0].text=''
    doc.notes.add_endnote('2',paragraph=doc.paragraphs[0])
    p=doc.add_paragraph('두 다항식 ');p.add_equation('A,~B');p.add_run('에 대하여')
    p=doc.add_paragraph('');p.add_equation('A=x^2 ` + ` y,~B=2x^2 ` - ` y')
    p=doc.add_paragraph('일 때,');p.add_equation('A+B');p.add_run('를 계산하면? [3.5점]')
    for label,formula in zip('①②③④⑤',('x^2','3x^2','2xy','3y','-x^2')):
        p=doc.add_paragraph(label+' ');p.add_equation(formula)
    p=doc.add_paragraph('[서답형1]');doc.notes.add_endnote('0.24',paragraph=p)
    p=doc.add_paragraph('복소수 ');p.add_equation('z=3+4i');p.add_run('에 대하여 ')
    p.add_equation('{1} over {z}+{1} over {{overline{z}}}');p.add_run('의 값을 구하시오. (단, ')
    p.add_equation('i=sqrt{-1}');p.add_run(', ');p.add_equation('{overline{z}}');p.add_run('는 ');p.add_equation('z');p.add_run('의 켤레복소수) [4점]')
    doc.add_paragraph('정답 및 해설')
    hwpx=tmp_path/'generated-native.hwpx';doc.save_to_path(hwpx);doc.close()
    with zipfile.ZipFile(hwpx) as z:files={n:z.read(n) for n in z.namelist()}
    path=tmp_path/'generated-native.hwp';path.write_bytes(write_hwp5(files))
    return path


def test_native_hwp_endnotes_original_answers_and_restore(tmp_path):
    path=native_fixture(tmp_path);store=Store(tmp_path/'data')
    result=import_hwp(store,path,'공통수학1')
    assert result['saved']==2 and result['ready_input']==2
    audit=result['conversion']
    assert audit['equation_scripts_exact_match'] and audit['text_paragraph_multiset_match']
    assert audit['native_counts']['endnotes']==2
    ids=result['question_ids'];questions=[store.question(i) for i in ids]
    assert [q['content']['answer'] for q in questions]==['2','0.24']
    assert questions[1]['content']['text'].startswith('복소수')
    assert questions[1]['content']['source']['label']=='[서답형1]'
    assert questions[0]['content']['solution']==[]
    assert all(q['content']['origins']['answer']['control']=='endNote' for q in questions)
    assert import_hwp(store,path)['added'] is False
    for q in questions:store.enqueue('local_solve',q['id'],q['version'])
    Pipeline(store,None).run()
    assert all(printable(store.question(i),'solutions') for i in ids)
    store.backup(tmp_path/'backup.zip');restored=Store.restore(tmp_path/'backup.zip',tmp_path/'restore')
    with restored.connect() as db:original=db.execute("SELECT path FROM assets WHERE kind='application/x-hwp'").fetchone()[0]
    assert (restored.root/original).read_bytes()==path.read_bytes()


def test_ordinary_inline_endnotes_are_not_treated_as_answers(tmp_path):
    d=HwpxDocument.new();d.paragraphs[0].text='1. 정의를 이용하여 풀어보시오.';d.notes.add_endnote('2',paragraph=d.paragraphs[0])
    p=d.add_paragraph('2. 다음 문장을 논증하시오.');d.notes.add_endnote('3',paragraph=p)
    for label in '①②③④⑤':d.add_paragraph(label+' 보기')
    path=tmp_path/'ordinary.hwpx';d.save_to_path(path);d.close()
    store=Store(tmp_path/'data');r=import_hwpx(store,path)
    assert all(not store.question(i)['content']['answer'] for i in r['question_ids'])


def test_hwp_equation_spacing_cases_greek_and_conjugate():
    for source in ['A,~B','- ` 2xy+x^{2}','{cases{4x-y=a#x+y=-4}}','alpha^{3}+beta^{3}','{overline{z`}}','320 pi m {}^3']:
        b=block(source);assert b['supported'],b
    assert render(from_latex(r'x^{{2}}'),'typst')=='x^(2)'
    assert not block('int_0^1 x dx')['supported']


def test_polynomial_variants_recompute_and_change_reasoning():
    c={'text':'두 다항식 $A,B$에 대하여 $A=x^2+y, B=2x^2-y$일 때,$A+B$를 계산하면?',
       'choices':['$x^2$','$3x^2$','$2xy$','$3y$','$-x^2$']}
    assert solve_exam(c)['answer']=='2'
    for kind in ('numeric','thinking'):
        generated=polynomial_variant(c,kind,'fixed-test-seed')
        child={'text':generated['text'],'choices':generated['choices']}
        assert polynomial_relation(c,child,kind)
        assert solve_exam(child)['answer'].isdigit()
    numeric=polynomial_variant(c,'numeric','fixed-test-seed')
    assert not polynomial_relation(c,{'text':numeric['text'],'choices':numeric['choices']},'thinking')


@pytest.mark.parametrize('text,choices,answer',[
    ('이차방정식 $x^2+6x+a-2=0$이 실근을 갖도록 하는 실수 $a$의 최댓값은?', ['9','10','11','12','13'],'3'),
    ('등식 $(2+i)x-(1-2i)y=5$ 을 만족시키는 두 실수 $x,y$에 대하여 $x+y$의 값은? (단, $i=\\sqrt{-1}$)', ['0','1','2','3','4'],'2'),
    ('두 실수 $x,y$에 대하여 $x+y=3$이고 $x^3+y^3=9$일 때, $x^2+xy+y^2$의 값은?', ['5','6','7','8','9'],'3'),
])
def test_new_policies_derive_changed_constants(text,choices,answer):
    assert solve_exam({'text':text,'choices':choices})['answer']==answer


def test_bmp_asset_prints_without_changing_original(tmp_path):
    from PySide6.QtGui import QImage,QColor
    from mathbank.output import make_exam
    from mathbank.publishing import export_pdf,export_hwpx
    import pymupdf
    image=QImage(24,24,QImage.Format_RGB32);image.fill(QColor('white'))
    for n in range(24):image.setPixelColor(n,n,QColor('black'))
    bmp=tmp_path/'line.bmp';assert image.save(str(bmp),'BMP')
    doc=HwpxDocument.new();doc.paragraphs[0].text='1. 그림의 선을 설명하시오.'
    doc.add_picture(bmp.read_bytes(),'bmp',width_mm=40)
    doc.add_paragraph('2. 같은 선을 다시 설명하시오.')
    source=tmp_path/'figures.hwpx';doc.save_to_path(source);doc.close()
    store=Store(tmp_path/'data');r=import_hwpx(store,source)
    exam=store.record(make_exam(store,r['question_ids'],'그림',mode='draft'))
    with store.connect() as db:asset=Path(store.root/db.execute('SELECT path FROM assets').fetchone()[0])
    before=asset.read_bytes();export_pdf(store,exam,tmp_path/'figures.pdf')
    assert asset.read_bytes()==before
    with pymupdf.open(tmp_path/'figures.pdf') as pdf:assert any(p.get_images() for p in pdf)
    export_hwpx(store,exam,tmp_path/'figures-out.hwpx')
    with zipfile.ZipFile(tmp_path/'figures-out.hwpx') as z:assert any(z.read(n)==before for n in z.namelist() if n.lower().endswith('.bmp'))


def test_real_root_policy_refuses_nonreal_coefficients():
    c={'text':'이차방정식 $ix^2-i(a-3)=0$이 실근을 갖도록 하는 실수 $a$의 최댓값은?','choices':['1','2','3','4','5']}
    with pytest.raises(ValueError,match='실수 계수'):solve_exam(c)


def test_unreadable_choice_cannot_be_counted_as_incorrect():
    from mathbank.solver import verify_candidate
    root={'text':'방정식 $x+3=7$의 모든 실근을 구하시오.','choices':['4','미지원 표기'],'input_status':'complete'}
    assert verify_candidate(root,'1')['state']=='held'
    c={'text':'이차방정식 $x^2+6x+a-2=0$이 실근을 갖도록 하는 실수 $a$의 최댓값은?','choices':['11','미지원 표기']}
    with pytest.raises(ValueError,match='모든 보기'):solve_exam(c)
