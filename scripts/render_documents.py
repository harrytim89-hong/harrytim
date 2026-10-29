"""Rendered exam/report fixtures and DOCX inspection; synthetic data only."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from mathbank.desktop import Preview
from mathbank.output import exam_html, report_html, grade_report, export_docx
from mathbank.validation import initial_stages

root = Path(__file__).resolve().parents[1] / 'artifacts'
root.mkdir(exist_ok=True)
stages = initial_stages()
for item in stages.values(): item['state'] = 'passed'
questions = [dict(id=str(i),version=1,stages=stages,error='',content={
    'text': f'다음 식의 값을 구하시오. $x={i+1}$일 때 $x^2+1$의 값은?',
    'choices':['$1$','$2$','$5$','$10$','$17$'], 'diagram':[],
    'answer':str((i+1)**2+1), 'solution':[f'$({i+1})^2+1={(i+1)**2+1}$'],
    'unit':'문자와 식','level':2}) for i in range(4)]
exam = dict(title='수식 출력 검증 · 생성 테스트 자료',questions=questions,points=[5]*4,layout='two',draft=False)
export_docx(exam,root/'exam-synthetic.docx')
notes = {'weakness':'[문제 진단] 02번은 오답, 03번은 미응답으로 기록되어 있습니다. 오답 원인은 답안만으로 단정하지 않습니다.\n[연습] 문자에 값을 대입하는 새 문항을 풀며 각 계산 단계를 기록합니다.',
         'strength':'01번에서 주어진 값을 대입한 문항을 맞혔습니다. 풀이 과정은 별도 제출되지 않아 추가 사고 과정은 추정하지 않습니다.',
         'summary':'이번 평가는 문자와 식의 정형적 적용 4문항으로 구성했습니다. 04번이 미채점이므로 최종 총점은 아직 산출하지 않았습니다.'}
fixtures=[('exam-synthetic.pdf',exam_html(exam))]
for school,label in [('중등','middle'),('고등','high')]:
    report=grade_report(exam,{'name':'출력 검증용 학생','school':school},[{'status':'O'},{'status':'X'},{'status':'—'},{'status':'미채점'}],notes)
    fixtures.append((f'report-{label}-synthetic.pdf',report_html(report)))
app=QApplication([])
index=0
previews=[]
failed=[]
def launch():
    global index
    if index==len(fixtures):
        app.quit();return
    name,html=fixtures[index]
    preview=Preview(html)
    previews.append(preview)
    preview.show()
    timer=QTimer(preview)
    timer.setInterval(100)
    def poll():
        if preview.ready:
            timer.stop();preview.write_pdf(root/name)
    timer.timeout.connect(poll)
    def done(path,ok):
        global index
        if not ok: failed.append(name)
        print(name,ok)
        index+=1
        QTimer.singleShot(200,launch)
    preview.view.page().pdfPrintingFinished.connect(done)
    timer.start()
launch()
QTimer.singleShot(60000,app.quit)
app.exec()
sys.exit(0 if index==len(fixtures) and not failed else 1)
