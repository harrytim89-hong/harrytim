"""Executable integration acceptance, using explicitly GENERATED HWPX fixtures.

No real student data, real textbook, or real AI success is implied.
"""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import zlib
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hwpx import HwpxDocument
from mathbank.store import Store
from mathbank.hwpx import import_hwpx, walk_blocks
from mathbank.pipeline import Pipeline
from mathbank.validation import printable
from mathbank.output import make_exam
from mathbank.publishing import export_pdf, export_hwpx, export_report_pdf, export_class_reports
from mathbank import study


def triangle_png():
    width,height=240,140
    rows=[]
    for y in range(height):
        row=bytearray()
        for x in range(width):
            ink=(20<=x<=210 and abs(y-120)<=1) or (abs(x-20)<=1 and 20<=y<=120) or abs(y-(120-(x-20)*100/190))<=1 and 20<=x<=210
            row.extend((20,50,70) if ink else (255,255,255))
        rows.append(b'\0'+row)
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')


def fixture(path):
    doc=HwpxDocument.new()
    def problem(number, before, formula, after):
        p=doc.paragraphs[0] if number==1 else doc.add_paragraph('')
        p.text=f'{number}. '+before
        p.add_equation(formula);p.add_run(after)
    problem(1,'방정식 ','x+3=7','의 모든 실근을 구하시오.')
    problem(2,'방정식 ','x^2-5x+6=0','의 모든 실근을 구하시오.')
    problem(3,'다항식 ','x^2+2x+1','에서 ')
    p=doc.paragraphs[-1];p.add_equation('x=3');p.add_run('일 때의 값을 구하시오.')
    problem(4,'방정식 ','{x} over {2}=3','의 모든 실근을 구하시오.')
    problem(5,'방정식 ','2x+1=9','의 모든 실근을 구하시오.')
    p=doc.add_paragraph('')
    for label,value in zip('①②③④⑤',(2,4,6,8,10)):
        p.add_run(label+' ');p.add_equation(str(value));p.add_run('   ')
    doc.add_paragraph('6. 아래 표와 직각삼각형을 참고하여 입력값과 출력값의 관계를 설명하시오.')
    table=doc.add_table(3,2,width=35000)
    for r,values in enumerate([['입력','출력'],['2','4'],['3','9']]):
        for c,value in enumerate(values):table.cell(r,c).text=value
    doc.add_picture(triangle_png(),'png',width_mm=60)
    doc.add_paragraph('7. 다음 긴 조건을 읽고 논증의 타당성을 설명하시오. '+
        '조건을 하나씩 확인하고 사용한 가정이 결론에 어떻게 연결되는지 근거를 적으시오. '*35)
    problem(8,'다음 적분을 계산하시오. ','int _0 ^1 x dx','')
    doc.save_to_path(path);doc.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='work/acceptance');args=parser.parse_args()
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    if (out/'isolated-data').exists():raise ValueError('새 출력 폴더를 지정하세요. 이전 검사 데이터는 덮어쓰지 않습니다.')
    fixture(out/'generated-problems-only.hwpx')
    store=Store(out/'isolated-data')
    imported=import_hwpx(store,out/'generated-problems-only.hwpx','중등 수학',metadata={'book':'자체 생성 회귀 검증 자료','confirmed':True})
    assert imported['saved']==8 and imported['held']==1,imported
    initial=[store.question(i) for i in imported['question_ids']]
    assert all(not q['content']['answer'] and not q['content']['solution'] for q in initial)
    assert store.questions(search='방정식')[1]==4
    assert import_hwpx(store,out/'generated-problems-only.hwpx')['added'] is False
    for q in initial[:5]:store.enqueue('local_solve',q['id'],q['version'])
    Pipeline(store,None).run()
    ids=imported['question_ids'][:5]
    assert all(printable(store.question(i),'solutions') for i in ids),store.jobs()
    parent=store.question(ids[1])
    for k in ('numeric','thinking'):store.enqueue('variant_local_'+k,parent['id'],parent['version'])
    Pipeline(store,None).run()
    with store.connect() as db:children=[r[0] for r in db.execute('SELECT question_id FROM lineage')]
    assert len(children)==2 and all(printable(store.question(i),'solutions') for i in children),store.jobs()
    exam_id=study.assemble(store,ids+children,'HWPX 통합 검증 시험',settings={'academy':'MathBank 검증 자료','student':'검증 학생','date':'2026-11-05','columns':2,'space_mm':35})
    exam=store.record(exam_id)
    for kind in ('questions','answers','solutions'):
        export_pdf(store,exam,out/(kind+'.pdf'),kind)
        export_hwpx(store,exam,out/(kind+'.hwpx'),kind)
    # Table, image and long question are printable only as explicitly labeled drafts.
    draft=store.record(make_exam(store,imported['question_ids'][5:7],'표 · 그림 · 긴 문항 출력 검사',mode='draft'))
    export_pdf(store,draft,out/'objects-long-draft.pdf')
    export_hwpx(store,draft,out/'objects-long-draft.hwpx')
    student=store.put_record('student',{'name':'검증 학생','school':'중등','grade':'2','class':'검증반'})
    attempt=study.assign(store,student,exam_id)
    answers=[q['content']['answer'] for q in exam['questions']]
    answers[0]='8/2';answers[1]='0';answers[2]=''
    report_id=study.grade_attempt(store,attempt,answers,manual={3:2.5})
    report=store.record(report_id)
    assert [g['status'] for g in report['grades'][:4]]==['O','X','—','부분점수']
    export_report_pdf(store,report,out/'student-report.pdf')
    export_class_reports(store,[report],out/'class-report.pdf')
    repeat=store.record(study.remediation(store,attempt))
    export_pdf(store,repeat,out/'wrong-answer-homework.pdf')
    second=study.assign(store,student,exam_id);study.grade_attempt(store,second,[],absent=True)
    assert study.attempt(store,second)['round']==2 and study.attempt(store,second)['status']=='absent'
    before=store.record(exam_id);old=store.question(ids[0]);edited=copy.deepcopy(old['content']);edited['answer']='999'
    store.update_question(old['id'],old['version'],edited,old['stages'],manual=True)
    assert not printable(store.question(ids[0])) and store.record(exam_id)==before
    store.backup(out/'backup.zip');restored=Store.restore(out/'backup.zip',out/'restored-data')
    assert restored.record(report_id)==report
    for a in (store,restored):
        with a.connect() as db:assert not db.execute('PRAGMA foreign_key_check').fetchall()
    import pymupdf
    rendered={}
    for name in ('questions','answers','solutions','objects-long-draft','student-report','wrong-answer-homework'):
        with pymupdf.open(out/(name+'.pdf')) as pdf:
            assert all(page.get_text().strip() for page in pdf)
            png=out/(name+'-page1.png');pdf[0].get_pixmap(dpi=110).save(png)
            rendered[name]={'pages':len(pdf),'size':(out/(name+'.pdf')).stat().st_size,'a4':all(abs(p.rect.width-595.28)<1 and abs(p.rect.height-841.89)<1 for p in pdf)}
    summary={'fixture':'GENERATED / not a real textbook','windows_executed':os.name=='nt',
             'ai_live_success':False,'import':imported,'verified_initial':5,'variants':2,
             'earned':report['earned'],'possible':report['possible'],'pdf':rendered,
             'backup_restore':True,'old_exam_preserved':True,'unverified_blocked':True,
             'checks':['problem-only import','duplicate detection','search','native equations','table','referenced image','long text','unsupported equation hold',
                       'exact solver','numeric variant','thinking variant','blind numeric validation','student assignment','auto grading','equivalent answers','partial score','unanswered','absence','retake round','immutable snapshot','remediation','backup/restore']}
    (out/'acceptance-result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
