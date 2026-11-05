"""HWPX workflows integrated into the existing native desktop."""
import copy
import json
from pathlib import Path
import threading
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QPlainTextEdit, QLabel,
    QSpinBox, QComboBox, QLineEdit, QFileDialog, QMessageBox, QInputDialog,
    QScrollArea, QWidget, QTableWidget, QTableWidgetItem, QDoubleSpinBox)
from .hwpx import import_hwpx, source_result, walk_blocks, plain
from .equations import block as equation_block
from .store import now
from .validation import initial_stages, mark
from .publishing import export_pdf, export_hwpx, export_report_pdf, export_class_reports
from . import study


LABELS = {'missing': '미생성', 'generated': '생성됨', 'provided': '원본 제공',
          'unverified': '미검증', 'verifying': '검증 중', 'passed': '자동 검사 통과', 'held': '보류', 'failed': '실패', 'complete': '저장 완료'}


class HwpxUi:
    def background(self, work):
        self.idle_required()
        self._worker_error = ''
        self._activity = ''
        self._auto_run = False
        self.pipeline.cancel.clear()
        def run():
            try: work()
            except Exception as exc: self._worker_error = str(exc)[:500]
            finally: self.signals.done.emit()
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def add_hwpx(self):
        path, _ = QFileDialog.getOpenFileName(self, '문제 HWP/HWPX 가져오기 · 정답/해설 선택 사항', '', '한글 문서 (*.hwpx *.hwp)')
        if not path: return
        course, ok = QInputDialog.getText(self, '과목', '교재 과목/교육과정 (미지정 가능)')
        if not ok: return
        self.statusBar().showMessage('HWPX 구조 해석 및 문항 저장 중…')
        def work():
            from .hwp_import import import_hwp
            importer = import_hwp if Path(path).suffix.lower()=='.hwp' else import_hwpx
            result = importer(self.store, path, course, cancel=self.pipeline.cancel,
                progress=lambda done, total: setattr(self, '_activity', f'문항 DB 저장 {done}/{total}'))
            self.store.put_record('import_notice', {'message': f"문항 {result['saved']}개 저장 · 입력 정상 {result['ready_input']} · 보류 {result['held']} · 중복 {'아니오' if result['added'] else '예'}", 'created': now()}, 'last-import')
        self.background(work)

    def import_details(self):
        d = self.selected(self.documents_table, self.documents)
        info = source_result(self.store, d['id'])
        if not info: raise ValueError('이 자료는 HWPX 가져오기 기록이 없습니다.')
        r = info['import_result']
        details = [f"원본: {d['name']}", f"해시: {d['hash']}", f"저장 {r['saved']} / 정상 입력 {r['ready_input']} / 보류 {r['held']} / 실패 {r['failed']}",
                   '정답·해설은 별도 생성 작업에서 선택/일괄 처리합니다.']
        if info['metadata'].get('conversion'):
            conversion=info['metadata']['conversion']
            details[1]='관리 HWPX 해시: '+d['hash']
            details.extend(['원본 HWP 해시: '+conversion['source_sha256'],
                'HWP 변환: 수식 원문·텍스트 문단·그림·표·미주 개체 수 대조 통과. 한글 시각 검증은 별도입니다.'])
        for issue in r['issues']:
            loc = issue['location']
            details.append(f"{issue['number'] or '번호 없음'}번: {'; '.join(issue['reasons'])} ({loc['section']}, 문단 {loc['paragraph']})")
        QMessageBox.information(self, '가져오기 결과', '\n'.join(details))

    def add_quick_answers(self):
        d = self.selected(self.documents_table, self.documents)
        path, _ = QFileDialog.getOpenFileName(self, '빠른정답 CSV 연결', '', 'CSV (*.csv)')
        if not path: return
        from .workflows import import_quick_answers
        count = import_quick_answers(self.store, d['id'], path)
        self.refresh()
        QMessageBox.information(self, '정답 연결', f'{count}문항에 원본 빠른정답을 연결했습니다. 생성 화면에서 상세해설을 생성하고 검증하세요.')

    def quick_answer_template(self):
        d = self.selected(self.documents_table, self.documents)
        path, _ = QFileDialog.getSaveFileName(self, '답지 양식 저장', '빠른정답.csv', 'CSV (*.csv)')
        if not path: return
        import csv
        with self.store.connect() as db:
            numbers = [r[0] for r in db.execute('SELECT number FROM questions WHERE document_id=? ORDER BY rowid', (d['id'],))]
        with open(path, 'w', encoding='utf-8-sig', newline='') as out:
            writer = csv.writer(out); writer.writerow(['source_sha256', 'number', 'answer'])
            for n in numbers: writer.writerow([d['hash'], n, ''])

    def build_generation(self):
        layout = self.section('변형 생성 · 정답/해설 검증', '가져오기와 별도로 실행합니다. 원본 정답은 선택 사항이며 미지원 검사/충돌 문항만 보류합니다.')
        form = QFormLayout()
        layout.addLayout(form)
        self.generation_scope = QComboBox()
        self.generation_scope.addItems(['문항검색에서 선택한 문항', '자료실에서 선택한 자료 전체'])
        form.addRow('대상', self.generation_scope)
        self.generation_provider = QComboBox()
        self.generation_provider.addItems(['오프라인 계산기 (지원 방정식·다항식)', 'AI 연결 (설정에서 먼저 연결)'])
        form.addRow('생성 방식', self.generation_provider)
        self.numeric_count, self.thinking_count = QSpinBox(), QSpinBox()
        for w in (self.numeric_count, self.thinking_count): w.setRange(0, 20); w.setValue(1)
        form.addRow('숫자변형 개수', self.numeric_count)
        form.addRow('사고변형 개수', self.thinking_count)
        self.row(layout, [('정답 · 상세해설 생성/검증', self.generate_answers), ('숫자변형 · 사고변형 생성', self.generate_variants), ('선택 문항 검증 근거', self.verification_details)])
        self.generation_info = QLabel('AI 연결이 없으면 AI 생성은 성공 처리되지 않습니다. 오프라인 계산 결과는 AI 결과와 구분하여 저장합니다.\nAI 별도 재풀이가 일치해도 계산 검사 정책이 없는 유형은 보류합니다.')
        self.generation_info.setWordWrap(True)
        layout.addWidget(self.generation_info)
        layout.addStretch()

    def split_hwpx(self):
        from .editing import split_question
        q=self.selected(self.bank_table,self.questions)
        blocks=q['content'].get('blocks',[])
        if len(blocks)<2:raise ValueError('문단이 2개 이상인 HWPX 문항을 선택하세요.')
        labels=[f'{i+1}번째 문단부터: '+plain([b]).strip()[:70] for i,b in enumerate(blocks) if i]
        chosen,ok=QInputDialog.getItem(self,'문항 나누기','두 번째 문항이 시작되는 문단',labels,0,False)
        if ok:
            self.idle_required();split_question(self.store,q['id'],labels.index(chosen)+1);self.refresh()

    def merge_hwpx(self):
        from .editing import merge_questions
        ids=[self.questions[i.row()]['id'] for i in sorted(self.bank_table.selectionModel().selectedRows(),key=lambda x:x.row())]
        self.idle_required();merge_questions(self.store,ids);self.refresh()

    def generation_ids(self):
        if self.generation_scope.currentIndex() == 1:
            d = self.selected(self.documents_table, self.documents)
            with self.store.connect() as db:
                ids = [r[0] for r in db.execute("SELECT id FROM questions WHERE document_id=? AND id NOT IN (SELECT target FROM trash WHERE kind='question')", (d['id'],))]
        else:
            ids = [self.questions[i.row()]['id'] for i in self.bank_table.selectionModel().selectedRows()]
        if not ids: raise ValueError('자료실에서 자료를 선택하거나 문항검색에서 문항을 선택하세요.')
        return [i for i in ids if self.store.question(i)['content'].get('format') == 'structured-v2']

    def generate_answers(self):
        ids = self.generation_ids()
        if not ids: raise ValueError('HWPX 문항을 선택하세요.')
        kind = 'local_solve' if self.generation_provider.currentIndex() == 0 else 'ai_solve'
        for identifier in ids:
            q = self.store.question(identifier)
            self.store.enqueue(kind, identifier, q['version'])
        self._auto_run = True
        self.start_worker()

    def generate_variants(self):
        ids = self.generation_ids()
        prefix = 'variant_local_' if self.generation_provider.currentIndex() == 0 else 'variant_ai_'
        # Distinct jobs of the same kind need separate target-independent slots.
        with self.store.connect() as db:
            from .store import uid
            for identifier in ids:
                q = self.store.question(identifier)
                for kind, count in [('numeric', self.numeric_count.value()), ('thinking', self.thinking_count.value())]:
                    for _ in range(count):
                        existing = db.execute("SELECT count(*) FROM jobs WHERE kind=? AND target=? AND version=? AND status IN ('queued','running')", (prefix+kind, identifier, q['version'])).fetchone()[0]
                        if existing >= count: break
                        db.execute('INSERT INTO jobs(id,kind,target,version,status,updated) VALUES(?,?,?,?,?,?)',
                                   (uid(), prefix+kind, identifier, q['version'], 'queued', now()))
        self._auto_run = True
        self.start_worker()

    def verification_details(self):
        q = self.selected(self.bank_table, self.questions)
        c = q['content']
        with self.store.connect() as db:
            evidence = [dict(r) for r in db.execute('SELECT * FROM verification WHERE question_id=? ORDER BY created DESC', (q['id'],))]
        dialog = QDialog(self); dialog.setWindowTitle('출처 · 상태 · 검증 기록'); dialog.resize(780, 680)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(json.dumps({'문항ID': q['id'], '버전': q['version'], '문항저장': c.get('storage_status'), '입력품질': c.get('input_status'),
            '정답': c.get('answer_status'), '해설': c.get('solution_status'), '수학검증': c.get('verification_status'),
            '출처': c.get('origins'), '변형계보': c.get('source'), '검증': evidence}, ensure_ascii=False, indent=2)); view.setReadOnly(True)
        layout.addWidget(view); dialog.exec()

    def edit_hwpx(self, q):
        dialog = QDialog(self); dialog.setWindowTitle('HWPX 문항 편집 · 출처 보존'); dialog.resize(950, 800)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('원본 파일은 보존됩니다. 수정 후 정답·해설 검증은 다시 수행합니다.'))
        scroll = QScrollArea(); scroll.setWidgetResizable(True); body = QWidget(); form = QFormLayout(body); scroll.setWidget(body); layout.addWidget(scroll)
        c = copy.deepcopy(q['content']); editors = []
        for b in walk_blocks(c.get('blocks', [])):
            if b['type'] in ('text', 'equation'):
                editor = QPlainTextEdit(b['text'] if b['type'] == 'text' else b['source']); editor.setMaximumHeight(75)
                form.addRow('본문' if b['type'] == 'text' else '수식 (한글 수식 문법)', editor)
                editors.append((b, editor))
        if not c.get('blocks'):
            editor = QPlainTextEdit(c['text']); form.addRow('본문 ($수식$)', editor); editors.append((None, editor))
        choices = QPlainTextEdit('\n'.join(c.get('choices', []))); form.addRow('보기 (한 줄 하나)', choices)
        answer = QLineEdit(c.get('answer', '')); form.addRow('원본/수정 정답 (선택)', answer)
        unit = QLineEdit(c.get('unit', '미분류')); form.addRow('단원', unit)
        type_ = QLineEdit(c.get('type', '미분류')); form.addRow('유형', type_)
        difficulty = QSpinBox(); difficulty.setRange(1, 10); difficulty.setValue(c.get('difficulty', 5)); form.addRow('난이도 1~10', difficulty)
        def save():
            self.idle_required()
            for block, editor in editors:
                if block is None: c['text'] = editor.toPlainText()
                elif block['type'] == 'text': block['text'] = editor.toPlainText()
                else:
                    new = equation_block(editor.toPlainText()); block.update(new)
            if c.get('blocks'): c['text'] = plain(c['blocks']).strip()
            c.update(choices=choices.toPlainText().splitlines(), unit=unit.text(), type=type_.text(), difficulty=difficulty.value())
            if answer.text() != c.get('answer'):
                c['answer'] = answer.text(); c['origins']['answer'] = {'kind': 'user', 'created': now()}
            c['verification_status'] = 'unverified'; c.pop('verification', None)
            c['classification_origin'] = {'kind': 'user', 'confirmed': True}
            issues = [b.get('issue', '미지원 개체') for b in walk_blocks(c.get('blocks', [])) if b['type'] == 'unsupported' or b['type'] == 'equation' and not b.get('supported')]
            # Boundary issues are never cleared merely by editing a text field.
            if c.get('input_status') == 'complete' and issues: c['input_status'] = 'held'
            stages = initial_stages()
            for key in stages:
                mark(stages, key, 'passed' if key not in ('answer', 'solution') and c.get('input_status') == 'complete' else 'pending', q['version']+1)
            if not self.store.update_question(q['id'], q['version'], c, stages, '; '.join(issues) or '수정 후 검증 대기', manual=True):
                raise ValueError('동시 편집이 발생했습니다. 다시 열어주세요.')
            dialog.accept(); self.refresh()
        self.row(layout, [('수정 저장', save), ('검증 근거', self.verification_details)])
        dialog.exec()

    def publish(self, format_):
        exam = self.selected(self.exam_table, self.exams)
        kind, ok = QInputDialog.getItem(self, '출력 종류', '출력물', ['문제지', '빠른정답', '상세해설', '유형별 교재'], 0, False)
        if not ok: return
        kind = {'문제지': 'questions', '빠른정답': 'answers', '상세해설': 'solutions', '유형별 교재': 'textbook'}[kind]
        path, _ = QFileDialog.getSaveFileName(self, '출력 저장', 'MathBank.' + format_, '*.' + format_)
        if not path: return
        def work():
            (export_pdf if format_ == 'pdf' else export_hwpx)(self.store, exam, path, kind)
            self.store.put_record('import_notice', {'message': '출력 저장 완료: ' + Path(path).name}, 'last-import')
        self.background(work)

    def exam_settings(self):
        exam = self.selected(self.exam_table, self.exams)
        dialog = QDialog(self); dialog.setWindowTitle('새 시험 개정 · 출력 설정'); form = QFormLayout(dialog); fields = {}
        current = exam.get('output_settings', {})
        for key, title in [('academy','학원명'), ('subject','과목'), ('date','시행일 YYYY-MM-DD'), ('student','학생명'), ('class','반')]:
            w = QLineEdit(current.get(key, '')); fields[key] = w; form.addRow(title, w)
        numbers = {}
        for key, title, lo, hi, default in [('font_size','글자 크기',8,16,10), ('columns','단 수',1,2,2), ('per_page','페이지당 문항 수',1,10,4), ('space_mm','풀이 공간 mm',0,120,35), ('margin_mm','여백 mm',10,30,16), ('gap_mm','단 간격 mm',4,20,10)]:
            w = QSpinBox(); w.setRange(lo, hi); w.setValue(current.get(key, default)); numbers[key] = w; form.addRow(title, w)
        color = QComboBox(); color.addItems(['컬러','흑백']); form.addRow('인쇄', color)
        def save():
            from .store import uid
            revised = copy.deepcopy(exam); revised.pop('id', None)
            revised.update(output_settings={**{k:w.text() for k,w in fields.items()}, **{k:w.value() for k,w in numbers.items()}, 'color': color.currentIndex()==0},
                           revision_of=exam['id'], revision=exam.get('revision',1)+1, title=exam['title']+' · 개정')
            self.store.put_record('exam', revised); dialog.accept(); self.refresh()
        buttons = QWidget(); button_layout = QVBoxLayout(buttons)
        self.row(button_layout, [('새 개정 저장', save)]); form.addRow(buttons)
        dialog.exec()

    def build_attempts(self, layout):
        self.row(layout, [('검증 시험 응시 배정', self.assign_attempt), ('제출 답 자동채점', self.auto_grade), ('응시 성적표 PDF', self.report_pdf),
                          ('반 성적표 합본 PDF', self.class_pdf), ('오답 재출제/변형 과제', self.remediate)])
        self.row(layout, [('선택 학생별 시험지 · 답지 · 해설 묶음 출력', self.publish_packets)])
        self.attempt_table = self.table(layout, ['학생', '시험', '회차', '응시/채점 상태'])

    def refresh_attempts(self):
        with self.store.connect() as db: self.attempts = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY created DESC')]
        self.fill(self.attempt_table, [(self.store.record(a['student_id'])['name'], self.store.record(a['exam_id'])['title'], a['round'],
            {'assigned':'배정', 'absent':'미응시', 'grading':'채점 중','graded':'채점 완료'}.get(a['status'], a['status'])) for a in self.attempts])

    def assign_attempt(self):
        student = self.selected(self.student_table, self.students); exam = self.selected(self.exam_table, self.exams)
        study.assign(self.store, student['id'], exam['id']); self.refresh()

    def auto_grade(self):
        a = self.selected(self.attempt_table, self.attempts); exam = self.store.record(a['exam_id'])
        dialog = QDialog(self); dialog.setWindowTitle('제출 답 채점 · 복잡한 동치는 채점 대기'); dialog.resize(780, 650); layout = QVBoxLayout(dialog)
        table = QTableWidget(len(exam['questions']), 4); table.setHorizontalHeaderLabels(['번호', '제출 답', '수동 점수 (선택)', '만점']); layout.addWidget(table)
        for i, points in enumerate(exam['points']):
            for j, value in enumerate((str(i+1), '', '', str(points))): table.setItem(i,j,QTableWidgetItem(value))
        def save(absent=False):
            answers = [table.item(i,1).text() for i in range(table.rowCount())]
            manual = {i: float(table.item(i,2).text()) for i in range(table.rowCount()) if table.item(i,2).text().strip()}
            study.grade_attempt(self.store, a['id'], answers, manual, absent); dialog.accept(); self.refresh()
        self.row(layout, [('채점 저장', save), ('미응시로 기록', lambda: save(True))]); dialog.exec()

    def report_pdf(self):
        a = self.selected(self.attempt_table, self.attempts)
        if not a['report_id']: raise ValueError('채점 후 성적표를 출력하세요.')
        path,_=QFileDialog.getSaveFileName(self,'성적표 저장','성적표.pdf','PDF (*.pdf)')
        if path: self.background(lambda: export_report_pdf(self.store,self.store.record(a['report_id']),path))

    def class_pdf(self):
        student = self.selected(self.student_table,self.students); cls=student.get('class','')
        selected = self.attempt_table.selectionModel().selectedRows()
        exam_id = self.attempts[selected[0].row()]['exam_id'] if selected else self.selected(self.exam_table,self.exams)['id']
        reports=[]
        included=set()
        for a in self.attempts:
            if a['report_id'] and a['exam_id']==exam_id and a['student_id'] not in included and self.store.record(a['student_id']).get('class','')==cls:
                reports.append(self.store.record(a['report_id']));included.add(a['student_id'])
        if not reports: raise ValueError('선택 학생과 같은 반의 채점된 성적표가 없습니다.')
        path,_=QFileDialog.getSaveFileName(self,'반 합본 성적표 저장','반_성적표.pdf','PDF (*.pdf)')
        if path: self.background(lambda: export_class_reports(self.store,reports,path))

    def remediate(self):
        a=self.selected(self.attempt_table,self.attempts)
        mode,ok=QInputDialog.getItem(self,'오답 과제','종류',['원래 문항 재풀이','숫자변형 생성/검증','사고변형 생성/검증'],0,False)
        if not ok:return
        result=study.remediation(self.store,a['id'],{'원래 문항 재풀이':'repeat','숫자변형 생성/검증':'numeric','사고변형 생성/검증':'thinking'}[mode])
        self.refresh()
        if isinstance(result,list):self.start_worker()

    def live_ai_test(self):
        if not self.provider.enabled: raise ValueError('AI 연결 사용을 켠 뒤 실행하세요. 구독 서비스의 사용 제한이 적용될 수 있습니다. 유료 API로 전환하지 않습니다.')
        def work():
            result=self.provider.call('연결 시험입니다. {"answer":"4","solution":["1+3=4"],"uncertain":false}를 JSON으로 반환하세요.',[],self.pipeline.cancel)
            if result.get('answer')!='4': raise ValueError('실제 AI 응답 형식/값 검사 실패')
            self.store.put_record('import_notice',{'message':'실제 AI 연결 시험 통과 · 모델: '+(self.provider.observed_model or self.provider.model or 'CLI 기본값')},'last-import')
        self.background(work)

    def publish_packets(self):
        ids = [self.attempts[i.row()]['id'] for i in self.attempt_table.selectionModel().selectedRows()]
        if not ids: raise ValueError('학생별 응시 행을 선택하세요. Ctrl/Shift로 여러 학생을 선택할 수 있습니다.')
        directory = QFileDialog.getExistingDirectory(self, '학생별 출력 저장 폴더')
        if not directory: return
        def work():
            for i, identifier in enumerate(ids, 1):
                if self.pipeline.cancel.is_set(): raise ValueError('출력을 중단했습니다. 저장 완료 파일은 유지됩니다.')
                self._activity = f'학생별 출력 {i}/{len(ids)}'
                study.student_packet(self.store, identifier, directory)
        self.background(work)
