import json
import zipfile
from pathlib import Path
import pytest
from hwpx import HwpxDocument
from pypdf import PdfReader
from studio.runtime import prepare_rendering
from studio.fixtures import make_fixture
from studio.importers import import_document
from studio.storage import Store
from studio.exports import export_question,export_questions_archive
from studio.model import checksum


def test_windows_selects_software_before_qt_and_keeps_cpu_rasterizer_available():
    env={'QTWEBENGINE_CHROMIUM_FLAGS':'--disable-software-rasterizer --log-level=1','QT_OPENGL':'desktop'}
    assert prepare_rendering(env,'win32')
    assert env['QT_OPENGL']=='software' and env['QT_QUICK_BACKEND']=='software'
    assert '--disable-gpu' in env['QTWEBENGINE_CHROMIUM_FLAGS'] and '--disable-gpu-compositing' in env['QTWEBENGINE_CHROMIUM_FLAGS']
    assert '--disable-software-rasterizer' not in env['QTWEBENGINE_CHROMIUM_FLAGS']
    assert '--log-level=1' in env['QTWEBENGINE_CHROMIUM_FLAGS'] and '--no-sandbox' not in env['QTWEBENGINE_CHROMIUM_FLAGS']
    before=dict(env);prepare_rendering(env,'win32');assert env==before


def test_non_windows_environment_is_not_overwritten(monkeypatch):
    monkeypatch.setattr('sys.argv',['studio'])
    env={'QT_OPENGL':'desktop'};assert not prepare_rendering(env,'linux') and env=={'QT_OPENGL':'desktop'}


@pytest.mark.parametrize('fmt',['hwpx','pdf'])
def test_zip_has_one_question_per_file_without_creating_exams(tmp_path,fmt):
    s=Store(tmp_path/'db');original=make_fixture(tmp_path/'q.hwpx');before=original.read_bytes();import_document(s,original)
    qs=s.questions();path=export_questions_archive(s,[q['id'] for q in qs],fmt)
    with zipfile.ZipFile(path) as z:
        names=[n for n in z.namelist() if n.endswith('.'+fmt)];assert len(names)==2
        records=json.loads(z.read('questions.json'));assert len(records)==2
        for row in records:assert checksum(z.read(row['file']))==row['sha256']
        if fmt=='hwpx':
            for name in names:
                f=tmp_path/name;f.write_bytes(z.read(name));doc=HwpxDocument.open(f)
                text=' '.join(p.text for p in doc.paragraphs)
                assert ('다항식 A' in text)!=('이차방정식' in text),text
        else:
            import io
            texts=[''.join(p.extract_text() for p in PdfReader(io.BytesIO(z.read(name))).pages) for name in names]
            assert '다항식 A' in texts[0] and '이차방정식' not in texts[0]
            assert '이차방정식' in texts[1] and '다항식 A' not in texts[1]
    assert s.exams()==[] and len(s.questions())==2 and original.read_bytes()==before


def test_individual_export_rejects_unresolved_bundle_and_invalid_format(tmp_path):
    s=Store(tmp_path/'db');path=make_fixture(tmp_path/'q.hwpx');import_document(s,path);q=s.questions()[0]
    s.revise(q['id'],{'source':{**q['source'],'boundary_review':True}})
    with pytest.raises(ValueError,match='미분리'):export_question(s,q['id'])
    with pytest.raises(ValueError):export_questions_archive(s,[q['id']])
    with pytest.raises(ValueError):export_questions_archive(s,[q['id'],q['id']])
    with pytest.raises(ValueError):export_question(s,q['id'],'html')


@pytest.mark.parametrize('markers',[('1.','2.','1.','2.'),('1.','2.','1)','2)')])
def test_number_restart_after_short_answer_section_creates_individual_questions(tmp_path,markers):
    doc=HwpxDocument.new();doc.paragraphs[0].text='자체 작성 혼합 문항 검증 자료'
    for i,mark in enumerate(markers):
        if i==2:doc.add_paragraph('※ 단답형')
        doc.add_paragraph(mark+' 다음 식의 값을 구하시오.').add_equation(str(i+2)+'+1')
        if i<2:
            for j in range(5):doc.add_paragraph('①②③④⑤'[j]+' '+str(j))
    path=tmp_path/'mixed.hwpx';doc.save_to_path(path);s=Store(tmp_path/'db');r=import_document(s,path)
    assert r['total']==4 and r['complete']==4,r
    assert [q['source']['number'] for q in s.questions()]==[1,2,1,2]
    assert [q['body']['answer_format'] for q in s.questions()]==['mc','mc','short','short']
    assert not any(q['source']['boundary_review'] for q in s.questions())
