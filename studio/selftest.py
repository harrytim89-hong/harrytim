"""Packaged application acceptance: real imports, outputs, grading and web bridge."""
from __future__ import annotations
import json
import os
import sys
import tempfile
import time
from pathlib import Path

def exercise(root):
    from .fixtures import make_fixture,native_fixture
    from .storage import Store
    from .importers import import_document
    from .reasoning import check_question
    from .variants import generate
    from .exports import export_packet,PDF
    from .assessment import grade,report,remediation
    from pypdf import PdfReader
    source=make_fixture(root/'source.hwpx',notes=True)
    native_fixture(source,root/'source.hwp')
    store=Store(root/'workspace');result=import_document(store,source)
    assert result['total']==2 and result['complete']==2 and result['answer_count']==2,{'report':result,'issues':[q['issues'] for q in store.questions()]}
    assert import_document(store,source)['duplicate']
    native=Store(root/'native-workspace');nr=import_document(native,root/'source.hwp')
    assert nr['total']==2 and nr['audit']['formula_preserved'],nr
    assert len(native.questions())==2
    original=store.questions()
    for q in original:
        answer=check_question(q);assert answer['verification']=='passed',answer
        store.save_answer(q['id'],q['revision'],q['fingerprint'],answer)
    child_ids=[generate(store,original[0]['id'],kind,{'provider':'local'},'selftest-'+kind) for kind in ('numeric','thinking')]
    assert all(store.question(i)['available'] for i in child_ids)
    eid=store.create_exam({'title':'개념을 연결하는 수학 · 공개 검증용','question_ids':[q['id'] for q in original]+child_ids,'points':[25]*4,'date':'2026-11-05','confirm':True,'settings':{'academy':'MATHBANK STUDIO'}})
    for kind in ('questions','answers','solutions','workbook'):
        for fmt in ('pdf','hwpx'):
            path=export_packet(store,eid,kind,fmt=fmt)
            if fmt=='pdf':assert len(PdfReader(path).pages)>=1
    sid=store.add_student({'name':'가상 학생','school':'검증용 학교','grade':'1학년','class_name':'공개 검증반'})
    aid=store.assign(eid,[sid])[0];exam=store.exam(eid)
    submitted={item['id']:item['snapshot']['answer']['final_answer'] for item in exam['items']}
    submitted[exam['items'][1]['id']]='';submitted[exam['items'][2]['id']]='0'
    r=grade(store,aid,submitted,{exam['items'][2]['id']:12.5})
    assert r['score']==62.5 and r['correct']==2,r
    path=PDF(store,store.root/'outputs/report').report(r);assert PdfReader(path).pages
    remedial=remediation(store,aid);assert len(store.exam(remedial)['items'])==2
    retry=store.assign(eid,[sid])[0];assert report(store,retry)['attempt']['round']==2
    grade(store,retry,{},absent=True);assert report(store,retry)['score'] is None
    before=store.exam(eid)['items'][0]['snapshot']['fingerprint']
    store.revise(original[0]['id'],{'difficulty':8})
    assert not store.question(original[0]['id'])['available']
    assert store.exam(eid)['items'][0]['snapshot']['fingerprint']==before
    assert report(store,aid)['score']==62.5
    archive=root/'backup.zip';store.backup(archive);restored=Store.restore(archive,root/'restored');check=Store(restored)
    assert len(check.questions())==4 and report(check,aid)['score']==62.5
    native.db.close();check.db.close()
    return store,{'questions':4,'variants':2,'pdf_and_hwpx_kinds':4,'score':62.5,'backup_restored':True,'native_import':True}

def gui_check(store,output=None):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QEventLoop,QTimer
    from .desktop import Window
    app=QApplication.instance() or QApplication(['MathBankStudio-selftest'])
    window=Window(store);window.show();state={'ready':False,'error':None};loop=QEventLoop();start=time.monotonic()
    def result(value):
        if isinstance(value,str):
            try:value=json.loads(value)
            except ValueError:value={}
        if value and value.get('ready'):
            try:
                assert value['cards']==1 and value['count']==4 and value['nav']==7,value
                assert value['math']>0,value
                state['ready']=True
                if output:window.grab().save(str(output))
            except Exception as exc:state['error']=str(exc)
            loop.quit()
        elif time.monotonic()-start>40:state['error']='QWebChannel 화면 초기화 시간 초과';loop.quit()
    def check():
        window.page.runJavaScript('JSON.stringify((()=>{if(!bridge || data.questions.length!==4)return {ready:false};navigate("library");let cards=document.querySelectorAll(".doc-row").length;document.querySelector("[data-nav=questions]").click();return {ready:true,count:data.questions.length,nav:document.querySelectorAll("nav button").length,cards:cards,math:document.querySelectorAll("math").length}})())',result)
    timer=QTimer();timer.timeout.connect(check);timer.start(300);QTimer.singleShot(45000,loop.quit);loop.exec();timer.stop();window.close();app.processEvents()
    if not state['ready']:raise AssertionError(state['error'] or '화면 검증 실패')
    return True

def run():
    try:
        with tempfile.TemporaryDirectory(prefix='mathbank-studio-check-',ignore_cleanup_errors=True) as temp:
            store,result=exercise(Path(temp));result['desktop_webchannel']=gui_check(store);store.db.close()
        Path('studio-selftest.json').write_text(json.dumps({'ok':True,**result},ensure_ascii=False,indent=2),encoding='utf-8')
        return 0
    except BaseException as exc:
        import traceback
        Path('studio-selftest.json').write_text(json.dumps({'ok':False,'error':str(exc),'trace':traceback.format_exc()},ensure_ascii=False,indent=2),encoding='utf-8')
        return 1
