"""Native Qt desktop UI. All user data stays outside the application directory."""
from .pdf_lock import PDF_LOCK
import copy
import json
from pathlib import Path
import shutil
import tempfile
import threading

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QObject, QRectF
from PySide6.QtGui import QPixmap, QPageSize, QPageLayout, QPainter, QPen, QColor
from PySide6.QtCore import QMarginsF
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QPushButton, QLabel, QFileDialog, QMessageBox, QLineEdit, QComboBox,
    QPlainTextEdit, QDialog, QFormLayout, QSpinBox, QDoubleSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QCheckBox, QGraphicsView,
    QGraphicsScene, QDialogButtonBox, QInputDialog, QTabWidget)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEnginePage, QWebEngineProfile
from PySide6.QtPrintSupport import QPrinter, QPrintDialog

from .store import Store
from .provider import CodexProvider
from .pipeline import Pipeline, crop
from .validation import initial_stages, validate_content, printable, invalidate_changes
from .output import ASSETS, exam_html, export_docx, make_exam, grade_report, report_html, page_html, text_html, svg


class LocalOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        url = info.requestUrl()
        allowed = url.scheme() in ("data", "about", "qrc")
        if url.isLocalFile():
            allowed = Path(url.toLocalFile()).resolve().is_relative_to(ASSETS.resolve())
        info.block(not allowed)


class SafePage(QWebEnginePage):
    def acceptNavigationRequest(self, url, kind, main):
        return url.scheme() in ("data", "about") or (url.isLocalFile() and Path(url.toLocalFile()).resolve().is_relative_to(ASSETS.resolve()))


class Preview(QDialog):
    def __init__(self, html, parent=None):
        super().__init__(parent)
        self.setWindowTitle("A4 미리보기 · PDF 저장 · 프린터 출력")
        self.resize(940, 820)
        layout = QVBoxLayout(self)
        self.message = QLabel("수식·글꼴을 렌더링하고 있습니다…")
        layout.addWidget(self.message)
        self.view = QWebEngineView()
        self.profile = QWebEngineProfile()
        self.interceptor = LocalOnly(self)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.webpage = SafePage(self.profile, self)
        self.profile.setParent(self.webpage)
        self.view.setPage(self.webpage)
        layout.addWidget(self.view)
        buttons = QHBoxLayout()
        self.pdf_button = QPushButton("PDF 저장")
        self.print_button = QPushButton("프린터로 인쇄")
        self.pdf_button.setEnabled(False)
        self.print_button.setEnabled(False)
        buttons.addWidget(self.pdf_button)
        buttons.addWidget(self.print_button)
        layout.addLayout(buttons)
        self.pdf_button.clicked.connect(self.save_pdf)
        self.print_button.clicked.connect(self.print_document)
        self.view.page().pdfPrintingFinished.connect(self.pdf_done)
        self.view.printFinished.connect(self.print_done)
        self.view.loadFinished.connect(self.loaded)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.check_ready)
        self.polls = 0
        self.view.setHtml(html, QUrl.fromLocalFile(str(ASSETS) + "/"))
        self.printer = None
        self.ready = False

    def loaded(self, ok):
        if not ok:
            self.message.setText("미리보기 로드 실패")
        else:
            self.timer.start()

    def check_ready(self):
        self.polls += 1
        self.view.page().runJavaScript('JSON.stringify({ready:window.renderReady,error:window.renderError})', self.render_status)
        if self.polls > 200:
            self.timer.stop()
            self.message.setText("수식·글꼴 렌더링 시간 초과. 출력하지 않았습니다.")

    def render_status(self, raw):
        result = json.loads(raw or '{}')
        if result.get("error"):
            self.timer.stop()
            self.message.setText("수식 렌더링 오류: " + result["error"])
        elif result.get("ready"):
            self.timer.stop()
            self.ready = True
            self.message.setText("렌더링 완료 · A4 210 × 297 mm")
            self.pdf_button.setEnabled(True)
            self.print_button.setEnabled(True)

    def save_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "PDF 저장", "MathBank.pdf", "PDF (*.pdf)")
        if path:
            self.write_pdf(path)

    def write_pdf(self, path):
        if not self.ready:
            raise ValueError("수식·글꼴 렌더링이 완료되지 않았습니다.")
        self.pdf_button.setEnabled(False)
        self.message.setText("PDF를 저장하고 있습니다…")
        self.view.page().printToPdf(str(path), QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(16, 17, 16, 17)))

    def pdf_done(self, path, ok):
        import pymupdf
        try:
            if not ok or not Path(path).exists() or Path(path).stat().st_size < 100:
                raise ValueError("빈 파일 또는 PDF 생성 실패")
            with PDF_LOCK, pymupdf.open(path) as pdf:
                if pdf.page_count < 1:
                    raise ValueError("페이지가 없습니다.")
                self.message.setText(f"PDF 저장 완료 · {pdf.page_count}페이지 · {path}")
        except Exception as exc:
            self.message.setText(f"PDF 저장 실패: {exc}")
        finally:
            self.pdf_button.setEnabled(True)

    def print_document(self):
        self.printer = QPrinter(QPrinter.HighResolution)
        self.printer.setPageSize(QPageSize(QPageSize.A4))
        if QPrintDialog(self.printer, self).exec() == QDialog.Accepted:
            self.print_button.setEnabled(False)
            self.message.setText("프린터로 전송하고 있습니다…")
            self.view.print(self.printer)

    def print_done(self, ok):
        self.message.setText("프린터 작업 전송 완료" if ok else "프린터 출력 실패")
        self.print_button.setEnabled(True)


class RegionView(QGraphicsView):
    def __init__(self, image):
        super().__init__()
        self.canvas = QGraphicsScene(self)
        self.setScene(self.canvas)
        pixmap = QPixmap(str(image))
        self.canvas.addPixmap(pixmap)
        self.image_width, self.image_height = pixmap.width(), pixmap.height()
        self.selection = None
        self.origin = None
        self.box = None
        self.setMinimumSize(460, 560)

    def showEvent(self, event):
        super().showEvent(event)
        self.fitInView(self.canvas.sceneRect(), Qt.KeepAspectRatio)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.origin = self.mapToScene(event.position().toPoint())
            if self.selection:
                self.canvas.removeItem(self.selection)
            self.selection = self.canvas.addRect(QRectF(self.origin, self.origin), QPen(QColor('#008b8b'), 3))

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            rect = QRectF(self.origin, self.mapToScene(event.position().toPoint())).normalized()
            self.box = rect.intersected(QRectF(0, 0, self.image_width, self.image_height))
            self.selection.setRect(self.box)

    def mouseReleaseEvent(self, event):
        self.origin = None


class WorkerSignals(QObject):
    done = Signal()


class MainWindow(QMainWindow):
    def __init__(self, store=None):
        super().__init__()
        self.store = store or Store()
        settings = self.store.records("ai_settings")
        settings = settings[0] if settings else {}
        self.provider = CodexProvider(model=settings.get("model", ""), effort=settings.get("effort", ""), store=self.store)
        observed = self.store.records("ai_observed")
        if observed:
            self.provider.observed_model = observed[0].get("model", "")
        self.pipeline = Pipeline(self.store, self.provider, workers=settings.get("workers", 2))
        self.thread = None
        self._auto_run = True
        self._worker_error = ""
        self.signals = WorkerSignals()
        self.signals.done.connect(self.worker_finished)
        self.page = 0
        self.setWindowTitle("MathBank Desktop")
        self.resize(1280, 840)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        self.nav = QListWidget()
        self.nav.setFixedWidth(210)
        self.nav.addItems(["01  PDF 자료실", "02  문제 보관함", "03  시험지 · 과제", "04  학생 · 성적표", "05  작업 큐", "06  AI · 백업 설정"])
        outer.addWidget(self.nav)
        right = QVBoxLayout()
        outer.addLayout(right)
        brand = QLabel("MATHBANK  /  DESKTOP  0.2.3")
        brand.setStyleSheet("font-size:24px;font-weight:700;color:#087e82;padding:16px")
        right.addWidget(brand)
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        right.addWidget(self.tabs)
        self.nav.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.setStyleSheet('''QMainWindow{background:#f3f6f8} QWidget{font-size:13px;color:#183345}
            QListWidget,QTableWidget,QPlainTextEdit,QLineEdit{background:white;border:1px solid #dce4ea;border-radius:5px;padding:6px}
            QPushButton{background:#087e82;color:white;border:0;border-radius:5px;padding:9px 13px}
            QPushButton:disabled{background:#aebbc3} QListWidget::item{padding:16px 5px}
            QListWidget::item:selected{background:#d8eeee;color:#07676a} QHeaderView::section{padding:7px;background:#e7eef2;border:0}''')
        self.build_library()
        self.build_bank()
        self.build_exams()
        self.build_students()
        self.build_jobs()
        self.build_settings()
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET status='paused',error='앱 중단 후 재개 대기' WHERE status='running'")
        self.refresh()
        self.statusBar().showMessage(f"운영 데이터: {self.store.root}")
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.poll_work)
        self.poll.start(1500)

    def section(self, title, subtitle):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:22px;font-weight:600;padding-top:8px")
        layout.addWidget(heading)
        description = QLabel(subtitle)
        description.setWordWrap(True)
        layout.addWidget(description)
        self.tabs.addTab(widget, title)
        return layout

    def row(self, layout, buttons):
        row = QHBoxLayout()
        layout.addLayout(row)
        for title, callback in buttons:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, cb=callback: self.guard(cb))
            row.addWidget(button)
        row.addStretch()
        return row

    def guard(self, callback):
        try:
            callback()
        except Exception as exc:
            QMessageBox.warning(self, "작업을 완료하지 못했습니다", str(exc))

    def table(self, layout, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(table)
        return table

    def fill(self, table, rows):
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                table.setItem(i, j, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()

    def selected(self, table, data):
        index = table.currentRow()
        if index < 0 or index >= len(data):
            raise ValueError("먼저 항목을 선택하세요.")
        return data[index]

    def build_library(self):
        layout = self.section("PDF 자료실", "PDF를 등록한 뒤 자동 처리 시작을 누르세요. 완료 문항은 승인 없이 보관함에 저장됩니다.")
        self.row(layout, [("PDF 등록", self.add_pdf), ("자동 처리 시작", self.process_pdf), ("영역 직접 추가", self.add_region), ("자료 삭제", lambda: self.trash_selected("document", self.documents_table, self.documents))])
        self.documents_table = self.table(layout, ["자료명", "과정", "페이지", "등록일"])

    def add_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "PDF 등록", "", "PDF (*.pdf)")
        if not path:
            return
        course, ok = QInputDialog.getText(self, "과정", "교재 과정 (예: 공통수학2, 미지정 가능)")
        if not ok:
            return
        _, added = self.store.add_document(path, course)
        self.refresh()
        if not added:
            QMessageBox.information(self, "중복 자료", "동일한 PDF가 이미 등록되어 있습니다.")

    def process_pdf(self):
        document = self.selected(self.documents_table, self.documents)
        self._auto_run = True
        self.pipeline.enqueue_document(document["id"])
        self.start_worker()

    def start_worker(self):
        if self.thread and self.thread.is_alive():
            return
        if not self.provider.enabled:
            raise ValueError("작업은 큐에 저장되었습니다. AI · 백업 설정에서 구독 연결을 켜고 작업 큐에서 재개하세요.")
        self._worker_error = ""
        def work():
            try:
                self.pipeline.run()
            except Exception as exc:
                self._worker_error = f"{type(exc).__name__}: {str(exc)[:300]}"
                self.pipeline.cancel.set()
            finally:
                self.signals.done.emit()
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        self.refresh_jobs()

    def add_region(self):
        import pymupdf
        document = self.selected(self.documents_table, self.documents)
        number, ok = QInputDialog.getInt(self, "페이지 선택", "페이지", 1, 1, document["pages"])
        if not ok:
            return
        with tempfile.TemporaryDirectory() as temp:
            with PDF_LOCK, pymupdf.open(self.store.root / document["path"]) as pdf:
                page = pdf[number-1]
                width, height = page.rect.width, page.rect.height
                image = Path(temp) / "page.png"
                page.get_pixmap(dpi=120).save(image)
            dialog = QDialog(self)
            dialog.setWindowTitle("문항 영역 · 마우스로 드래그하세요")
            layout = QVBoxLayout(dialog)
            view = RegionView(image)
            layout.addWidget(view)
            button = QPushButton("선택 영역을 문항으로 저장")
            button.clicked.connect(dialog.accept)
            layout.addWidget(button)
            if dialog.exec() == QDialog.Accepted:
                if not view.box or view.box.width() < 5 or view.box.height() < 5:
                    raise ValueError("유효한 문항 영역을 드래그하세요.")
                box = view.box
                identifier = self.store.add_question(document["id"], [{"page": number-1, "box":
                    [box.left()/view.image_width*width, box.top()/view.image_height*height,
                     box.right()/view.image_width*width, box.bottom()/view.image_height*height]}])
                self.store.enqueue("question", identifier, self.store.question(identifier)["version"])
                self.refresh()

    def build_bank(self):
        layout = self.section("문제 보관함", "한 페이지에 50문항을 표시합니다. 원문 검사와 정답·풀이 검사는 별도로 관리됩니다.")
        row = self.row(layout, [("새로고침", self.refresh_bank), ("검색", self.search_bank), ("원본 · 편집", self.edit_question), ("재처리", self.retry_question), ("이전", self.previous_page), ("다음", self.next_page), ("문항 삭제", lambda: self.trash_selected("question", self.bank_table, self.questions))])
        self.search = QLineEdit()
        self.search.setPlaceholderText("본문 · 단원 · 문항번호 검색")
        self.search.returnPressed.connect(self.search_bank)
        row.addWidget(self.search)
        self.only_exceptions = QCheckBox("처리 예외만")
        self.only_exceptions.stateChanged.connect(self.search_bank)
        row.addWidget(self.only_exceptions)
        self.bank_auto = QCheckBox("자동 새로고침 (작업 중)")
        self.bank_auto.setChecked(True)
        layout.addWidget(self.bank_auto)
        self.bank_count = QLabel()
        layout.addWidget(self.bank_count)
        self.bank_table = self.table(layout, ["원본 번호", "본문", "단원", "난이도", "원문", "정답", "풀이"])
        self.bank_table.doubleClicked.connect(lambda _: self.guard(self.edit_question))

    def search_bank(self):
        self.page = 0
        self.refresh_bank()

    def previous_page(self):
        self.page = max(0, self.page-1)
        self.refresh_bank()

    def next_page(self):
        if (self.page+1)*50 < self.bank_total:
            self.page += 1
            self.refresh_bank()

    def retry_question(self):
        q = self.selected(self.bank_table, self.questions)
        self.store.enqueue("question", q["id"], q["version"])
        self.start_worker()

    def edit_question(self):
        q = self.store.question(self.selected(self.bank_table, self.questions)["id"])
        dialog = QDialog(self)
        dialog.setWindowTitle("원본 대조 · 선택적 편집")
        dialog.resize(1150, 800)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(q["error"] or "원본과 본문을 비교할 수 있습니다. 저장 후 자동 재검사를 예약합니다."))
        splitter = QSplitter()
        layout.addWidget(splitter)
        source = QLabel()
        source.setAlignment(Qt.AlignTop)
        temp = tempfile.TemporaryDirectory()
        images = crop(self.store, q, temp.name)
        source.setPixmap(QPixmap(str(images[0])).scaledToWidth(460, Qt.SmoothTransformation))
        splitter.addWidget(source)
        fields = QWidget()
        form = QFormLayout(fields)
        c = q["content"]
        editors = {}
        for key, title, value in (("text", "본문 ($LaTeX$)", c.get("text", "")),
            ("choices", "보기 (한 줄에 하나)", '\n'.join(c.get("choices", []))),
            ("answer", "빠른답", c.get("answer", "")), ("solution", "풀이 (한 줄에 한 단계)", '\n'.join(c.get("solution", []))),
            ("diagram", "구조화 도형 JSON", json.dumps(c.get("diagram", []), ensure_ascii=False, indent=2))):
            editor = QPlainTextEdit(value)
            editor.setMaximumHeight(130)
            editors[key] = editor
            form.addRow(title, editor)
        unit = QLineEdit(c.get("unit", "수학 종합"))
        form.addRow("단원", unit)
        level = QSpinBox()
        level.setRange(1, 5)
        level.setValue(c.get("level", 3))
        form.addRow("난이도", level)
        splitter.addWidget(fields)
        def content():
            return dict(text=editors["text"].toPlainText(), choices=editors["choices"].toPlainText().splitlines(),
                        answer=editors["answer"].toPlainText(), solution=editors["solution"].toPlainText().splitlines(),
                        diagram=json.loads(editors["diagram"].toPlainText()), unit=unit.text(), level=level.value(),
                        course=c.get("course", ""), reason="사용자 편집", uncertain=False)
        def preview():
            result = validate_content(content())
            Preview(page_html('<h2>문항 미리보기</h2><p>'+text_html(result["text"])+'</p>'+svg(result["diagram"])+'<p>'+'<br>'.join(text_html(s) for s in result["choices"])+'</p>'), dialog).exec()
        def save():
            result = validate_content(content())
            stages = invalidate_changes(q["content"], result, q["stages"], q["version"] + 1)
            if not self.store.update_question(q["id"], q["version"], result, stages, "수동 편집 후 자동 검사 대기", manual=True):
                raise ValueError("다른 작업에서 변경되었습니다. 다시 열어주세요.")
            self.store.enqueue("question", q["id"], q["version"]+1)
            dialog.accept()
            self.refresh()
            if self.provider.enabled:
                self.start_worker()
        self.row(layout, [("수식 · 도형 미리보기", preview), ("저장", save)])
        dialog.exec()
        temp.cleanup()

    def build_exams(self):
        layout = self.section("시험지 · 과제 제작", "선택 문항의 내용·정답·분류를 스냅샷으로 저장합니다. 원문 검사 예외는 초안에 명시합니다.")
        self.row(layout, [("보관함 선택 문항으로 만들기", self.create_exam), ("문제지", lambda: self.preview_exam("questions")),
                          ("빠른답", lambda: self.preview_exam("answers")), ("상세 해설", lambda: self.preview_exam("solutions")), ("DOCX 저장", self.save_docx), ("시험지 삭제", lambda: self.trash_selected("exam", self.exam_table, self.exams))])
        self.exam_table = self.table(layout, ["제목", "문항 수", "출력 상태"])

    def create_exam(self):
        ids = [self.questions[i.row()]["id"] for i in self.bank_table.selectionModel().selectedRows()]
        if not ids:
            raise ValueError("문제 보관함에서 문항을 선택하세요. Ctrl/Shift로 여러 문항을 선택할 수 있습니다.")
        title, ok = QInputDialog.getText(self, "시험지", "제목")
        if not ok or not title.strip():
            return
        layout, ok = QInputDialog.getItem(self, "조판", "레이아웃", ["one", "two", "grid"], 0, False)
        if not ok:
            return
        points, ok = QInputDialog.getDouble(self, "배점", "문항당 배점", 5, .1, 100, 1)
        if not ok:
            return
        blocked = [self.store.question(i) for i in ids if not printable(self.store.question(i))]
        mode = "complete"
        if blocked:
            choice, ok = QInputDialog.getItem(self, "처리 예외", '\n'.join(f'{q["number"] or q["id"][:8]}: {q["error"] or "자동 검사 미완료"}' for q in blocked),
                                             ["완료 문항만 사용", "예외 표시 초안", "재처리 후 만들기"], 0, False)
            if not ok:
                return
            if choice == "완료 문항만 사용":
                ids = [i for i in ids if i not in {q["id"] for q in blocked}]
            elif choice == "예외 표시 초안":
                mode = "draft"
            else:
                for q in blocked:
                    self.store.enqueue("question", q["id"], q["version"])
                self.start_worker()
                return
        make_exam(self.store, ids, title.strip(), mode, points, layout)
        self.refresh()

    def preview_exam(self, kind):
        exam = self.selected(self.exam_table, self.exams)
        Preview(exam_html(exam, kind), self).exec()

    def save_docx(self):
        exam = self.selected(self.exam_table, self.exams)
        path, _ = QFileDialog.getSaveFileName(self, "DOCX 저장", "MathBank.docx", "Word (*.docx)")
        if path:
            export_docx(exam, path)
            QMessageBox.information(self, "저장 완료", "Word 수식 객체로 저장했습니다. 한글 호환성은 별도 검증이 필요합니다.")

    def build_students(self):
        layout = self.section("학생 · 채점 · 성적표", "미채점과 오답을 구분합니다. 성적표는 저장 당시 시험지와 채점 결과를 보존합니다.")
        self.row(layout, [("학생 등록", self.add_student), ("선택 시험 배정", self.assign_exam), ("채점 · 성적표 작성", self.grade), ("저장 성적표 보기", self.show_report), ("오답 보완 문항 찾기", self.clinic)])
        self.row(layout, [("학생 삭제", lambda: self.trash_selected("student", self.student_table, self.students)), ("배정 취소 · 삭제", lambda: self.trash_selected("assignment", self.assignment_table, self.assignments))])
        self.student_table = self.table(layout, ["학생", "반", "학교급", "학년"])
        self.assignment_table = self.table(layout, ["학생", "시험지", "제출일", "상태"])

    def add_student(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("학생 등록")
        form = QFormLayout(dialog)
        fields = {}
        for key, title in (("name", "이름"), ("class", "반"), ("grade", "학년"), ("memo", "교사 메모")):
            fields[key] = QLineEdit()
            form.addRow(title, fields[key])
        school = QComboBox()
        school.addItems(["중등", "고등"])
        form.addRow("학교급", school)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.Accepted:
            result = {key: value.text().strip() for key, value in fields.items()}
            if not result["name"]:
                raise ValueError("학생 이름을 입력하세요.")
            result["school"] = school.currentText()
            self.store.put_record("student", result)
            self.refresh()

    def assign_exam(self):
        student = self.selected(self.student_table, self.students)
        exam = self.selected(self.exam_table, self.exams)
        deadline, ok = QInputDialog.getText(self, "과제 배정", "제출일 (YYYY-MM-DD)")
        if not ok:
            return
        from datetime import date
        date.fromisoformat(deadline)
        self.store.put_record("assignment", {"student": student, "exam": exam, "deadline": deadline, "status": "배정", "report_id": ""})
        self.refresh()

    def grade(self):
        assignment = self.selected(self.assignment_table, self.assignments)
        exam, student = assignment["exam"], assignment["student"]
        previous = self.store.record(assignment["report_id"]) if assignment.get("report_id") else None
        dialog = QDialog(self)
        dialog.setWindowTitle(student["name"] + " · 채점 · 성적표")
        dialog.resize(850, 760)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(exam["questions"]), 3)
        table.setHorizontalHeaderLabels(["번호", "상태", "부분점수"])
        controls = []
        for i in range(len(exam["questions"])):
            table.setItem(i, 0, QTableWidgetItem(str(i+1)))
            state = QComboBox()
            state.addItems(["미채점", "O", "X", "—", "부분점수"])
            points = QDoubleSpinBox()
            points.setRange(0, exam["points"][i])
            if previous:
                state.setCurrentText(previous["grades"][i]["status"])
                points.setValue(previous["grades"][i].get("score", 0))
            table.setCellWidget(i, 1, state)
            table.setCellWidget(i, 2, points)
            controls.append((state, points))
        layout.addWidget(table)
        notes = {}
        for key, title in (("weakness", "01 / 부족한 점과 보완 방법"), ("strength", "02 / 잘한 점과 강점"), ("summary", "TEACHER’S NOTE / 총평")):
            layout.addWidget(QLabel(title))
            editor = QPlainTextEdit(previous["notes"].get(key, "") if previous else "")
            editor.setMaximumHeight(80)
            layout.addWidget(editor)
            notes[key] = editor
        expected = QLineEdit(previous.get("expected_grade", "") if previous else "")
        expected.setPlaceholderText("교사 입력 예상등급 (선택)")
        layout.addWidget(expected)
        def save():
            result = grade_report(exam, student, [{"status": s.currentText(), "score": p.value()} for s, p in controls],
                                  {k: v.toPlainText() for k, v in notes.items()}, expected.text())
            identifier = self.store.put_record("report", result)
            assignment["report_id"] = identifier
            assignment["status"] = "채점 완료" if result["graded"] == len(exam["questions"]) else "채점 중"
            self.store.put_record("assignment", {k:v for k,v in assignment.items() if k != "id"}, assignment["id"])
            dialog.accept()
            self.refresh()
            Preview(report_html(result), self).exec()
        self.row(layout, [("저장 · 성적표 미리보기", save)])
        dialog.exec()

    def show_report(self):
        assignment = self.selected(self.assignment_table, self.assignments)
        if not assignment.get("report_id"):
            raise ValueError("먼저 채점 · 성적표를 저장하세요.")
        Preview(report_html(self.store.record(assignment["report_id"])), self).exec()

    def clinic(self):
        assignment = self.selected(self.assignment_table, self.assignments)
        if not assignment.get("report_id"):
            raise ValueError("채점 결과가 필요합니다.")
        report = self.store.record(assignment["report_id"])
        units = {q["content"].get("unit", "") for q, g in zip(report["exam"]["questions"], report["grades"]) if g["status"] in ("X", "—", "부분점수")}
        if not units:
            QMessageBox.information(self, "오답 보완", "기록된 오답·미응답·부분점수 문항이 없습니다.")
            return
        unit, ok = QInputDialog.getItem(self, "보완 단원 선택", "다른 문항을 선택해 새 과제로 배정할 수 있습니다.", sorted(units), 0, False)
        if ok:
            self.search.setText(unit)
            self.search_bank()
            self.nav.setCurrentRow(1)

    def build_jobs(self):
        layout = self.section("작업 큐 센터", "페이지·문항 단위 저장 · 최대 3가지 방법으로 재처리 · 인증/한도 오류 시 일시정지")
        self.row(layout, [("자동 처리 시작 · 재개", self.resume_jobs), ("진행 작업 취소", self.stop_processing), ("대기 작업 전체 취소", self.cancel_waiting), ("선택 예외 재시도", self.retry_job)])
        self.queue_status = QLabel()
        self.queue_status.setWordWrap(True)
        layout.addWidget(self.queue_status)
        self.jobs_table = self.table(layout, ["작업", "대상", "상태", "시도", "방법", "사유"])

    def resume_jobs(self):
        if self.thread and self.thread.is_alive():
            if self.pipeline.cancel.is_set():
                raise ValueError("이전 작업을 종료하는 중입니다. 종료 후 다시 시작해 주세요.")
            return
        # Starting the queue is an explicit request to use the subscription connection.
        self.ai_enabled.setChecked(True)
        self.provider.enabled = True
        self._auto_run = True
        self._worker_error = ""
        self.pipeline.cancel.clear()
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET status='queued',error='' WHERE status='paused'")
        self.start_worker()

    def retry_job(self):
        job = self.selected(self.jobs_table, self.job_rows)
        if job["status"] not in ("exception", "paused", "cancelled"):
            raise ValueError("예외·중단 작업만 재시도할 수 있습니다.")
        self._auto_run = True
        self.store.job_status(job["id"], "queued")
        self.start_worker()

    def build_settings(self):
        layout = self.section("AI · 백업 설정", "유료 API 자동 전환 없음. 기본 연결은 Codex CLI의 ChatGPT 로그인입니다.")
        self.ai_enabled = QCheckBox("Codex 구독 연결 사용 (현재 세션)")
        self.ai_enabled.toggled.connect(self.set_ai_enabled)
        layout.addWidget(self.ai_enabled)
        form = QFormLayout()
        self.model_field = QLineEdit(self.provider.model)
        self.model_field.setPlaceholderText("비워두면 현재 CLI 기본 모델 유지 (권장)")
        form.addRow("지정 모델", self.model_field)
        self.effort_field = QComboBox()
        self.effort_field.addItems(["기본값 유지", "medium", "high", "xhigh"])
        self.effort_field.setCurrentText(self.provider.effort or "기본값 유지")
        form.addRow("추론 강도", self.effort_field)
        self.worker_field = QSpinBox()
        self.worker_field.setRange(1, 2)
        self.worker_field.setValue(self.pipeline.workers)
        form.addRow("동시 작업 수 (한도 오류 시 1)", self.worker_field)
        layout.addLayout(form)
        self.row(layout, [("AI 설정 저장", self.save_ai_settings), ("최근 확인 모델 고정", self.pin_model), ("휴지통 · 복원", self.open_trash)])
        self.model_status = QLabel()
        layout.addWidget(self.model_status)
        self.ai_status = QLabel("연결 진단 전")
        self.ai_status.setWordWrap(True)
        layout.addWidget(self.ai_status)
        self.row(layout, [("연결 진단", self.check_ai), ("백업 ZIP 저장", self.backup), ("새 폴더로 복원", self.restore_backup), ("문항 요청 패키지 내보내기", self.export_request), ("결과 JSON 가져오기", self.import_response)])
        note = QLabel("Codex 설치·로그인은 공식 안내를 따르세요: https://developers.openai.com/codex/cli\n"
                      "운영 데이터: " + str(self.store.root) + "\n"
                      "복원은 새 폴더에서 무결성을 검사합니다. 현재 운영 데이터를 덮어쓰지 않습니다.\n"
                      "수식은 오프라인 KaTeX로 표시합니다. 구독 연결이 없어도 편집·저장·출력·채점이 가능합니다.\n"
                      "현재 Windows 설치 검증·복잡한 다페이지 분리·수학 도구 검산·DOCX 벡터 도형은 미완료입니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def idle_required(self):
        if self.thread and self.thread.is_alive():
            raise ValueError("진행 중인 작업을 취소하고 종료될 때까지 기다린 뒤 실행하세요.")

    def save_ai_settings(self):
        self.idle_required()
        import re
        model = self.model_field.text().strip()
        if model and not re.fullmatch(r'[a-zA-Z0-9._:/-]{1,100}', model):
            raise ValueError("모델 ID 형식을 확인하세요.")
        self.provider.model = model
        self.provider.effort = "" if self.effort_field.currentIndex() == 0 else self.effort_field.currentText()
        self.pipeline.workers = self.worker_field.value()
        self.store.put_record("ai_settings", {"model": model, "effort": self.provider.effort,
                              "workers": self.pipeline.workers}, "ai-settings")
        self.refresh_jobs()
        self.statusBar().showMessage("AI 설정 저장 완료. 다음 요청부터 적용합니다. 모델 자동 대체는 하지 않습니다.")

    def pin_model(self):
        if not self.provider.observed_model:
            raise ValueError("실제 AI 요청에서 모델이 확인된 뒤 사용할 수 있습니다.")
        self.model_field.setText(self.provider.observed_model)
        self.save_ai_settings()

    def cancel_waiting(self):
        self.store.cancel_jobs()
        self.refresh_jobs()

    def trash_selected(self, kind, table, data):
        self.idle_required()
        rows = sorted({i.row() for i in table.selectionModel().selectedRows()})
        if not rows:
            raise ValueError("삭제할 항목을 선택하세요.")
        extra = "자료에 속한 문항도 보관함에서 숨기고 관련 작업을 취소합니다. " if kind == "document" else ""
        message = f"선택한 {len(rows)}개 항목을 휴지통으로 이동할까요? " + extra + "기존 시험지·배정·성적표의 저장 사본은 유지됩니다. 설정의 휴지통에서 복원할 수 있습니다."
        if QMessageBox.question(self, "휴지통으로 이동", message) != QMessageBox.Yes:
            return
        self.store.move_to_trash(kind, [data[row]["id"] for row in rows])
        self.refresh()

    def open_trash(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("휴지통 · 원본 파일은 보존됩니다")
        dialog.resize(700, 450)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("복원은 목록을 되살립니다. 취소된 작업은 자동으로 다시 시작하지 않습니다."))
        entries = self.store.trashed()
        labels = {'document':'PDF 자료', 'question':'문항', 'exam':'시험지', 'student':'학생', 'assignment':'배정'}
        table = self.table(layout, ["종류", "이름 / 식별자", "삭제일"])
        display = []
        for entry in entries:
            kind, identifier = entry['kind'], entry['target']
            if kind == 'document': name = self.store.document(identifier)['name']
            elif kind == 'question':
                q = self.store.question(identifier)
                name = q['number'] or q['content'].get('text', identifier)[:50]
            else:
                record = self.store.record(identifier)
                name = record.get('name') or record.get('title') or record.get('student', {}).get('name', identifier)
            display.append((labels[kind], name, entry['created'][:19]))
        self.fill(table, display)
        def restore():
            self.idle_required()
            entry = self.selected(table, entries)
            self.store.restore_trash(entry['kind'], entry['target'])
            dialog.accept()
            self.refresh()
        self.row(layout, [("선택 항목 복원", restore)])
        dialog.exec()

    def check_ai(self):
        ok, message = self.provider.status()
        self.ai_status.setText(message)

    def backup(self):
        if self.thread and self.thread.is_alive():
            raise ValueError("일관된 원본 목록을 위해 진행 작업을 취소한 뒤 백업하세요.")
        path, _ = QFileDialog.getSaveFileName(self, "백업 저장", "MathBank-backup.zip", "ZIP (*.zip)")
        if path:
            self.store.backup(path)
            QMessageBox.information(self, "백업 완료", "DB 스냅샷과 원본 PDF, 파일 해시를 함께 저장했습니다.")

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "백업 선택", "", "ZIP (*.zip)")
        if not path:
            return
        parent = QFileDialog.getExistingDirectory(self, "복원할 새 폴더의 상위 위치")
        if not parent:
            return
        destination = Path(parent) / ("MathBank-restored-" + __import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S'))
        Store.restore(path, destination)
        QMessageBox.information(self, "검증 후 복원 완료", f"복원 위치: {destination}\nMATHBANK_DATA를 이 경로로 지정해 사용할 수 있습니다.")

    def export_request(self):
        from .exchange import export_request
        q = self.selected(self.bank_table, self.questions)
        path, _ = QFileDialog.getSaveFileName(self, "요청 패키지", "MathBank-request.zip", "ZIP (*.zip)")
        if path:
            export_request(self.store, q["id"], path)
            QMessageBox.information(self, "내보내기 완료", "원본 크롭·요청·문항 식별자·입력 해시가 포함되었습니다. 학생 정보는 포함하지 않습니다.")

    def import_response(self):
        from .exchange import import_response
        path, _ = QFileDialog.getOpenFileName(self, "AI 결과 JSON", "", "JSON (*.json)")
        if path:
            identifier = import_response(self.store, path)
            self.refresh()
            QMessageBox.information(self, "가져오기 완료", "결과는 자동 대조 대기로 보존했습니다. 독립 검사가 완료되기 전에는 초안으로만 출력할 수 있습니다.")
            if self.provider.enabled:
                self.start_worker()

    def refresh_bank(self):
        selected_ids = {self.questions[i.row()]['id'] for i in self.bank_table.selectionModel().selectedRows()
                        if hasattr(self, 'questions') and i.row() < len(self.questions)}
        scroll = self.bank_table.verticalScrollBar().value()
        self.questions, self.bank_total = self.store.questions(self.page, self.search.text(), exceptions=self.only_exceptions.isChecked())
        self.bank_count.setText(f"전체 {self.bank_total}문항 · {self.page+1}페이지")
        self.fill(self.bank_table, [(q["number"], q["content"].get("text", "미처리")[:70], q["content"].get("unit", "—"),
            q["content"].get("level", "—"), q["stages"]["comparison"]["state"], q["stages"]["answer"]["state"], q["stages"]["solution"]["state"]) for q in self.questions])

        from PySide6.QtCore import QItemSelectionModel
        self.bank_table.clearSelection()
        for row, q in enumerate(self.questions):
            if q['id'] in selected_ids:
                self.bank_table.selectionModel().select(self.bank_table.model().index(row, 0),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.bank_table.verticalScrollBar().setValue(scroll)
        from datetime import datetime
        self.bank_count.setText(self.bank_count.text() + " · 갱신 " + datetime.now().strftime('%H:%M:%S'))

    def set_ai_enabled(self, enabled):
        self.provider.enabled = enabled
        if enabled:
            self._auto_run = True
        else:
            self.stop_processing()

    def stop_processing(self):
        self._auto_run = False
        self.pipeline.cancel.set()

    def worker_finished(self):
        if self.thread and self.thread.is_alive():
            QTimer.singleShot(50, self.worker_finished)
            return
        if self.pipeline.cancel.is_set():
            self._auto_run = False
        self.refresh()

    def poll_work(self):
        self.refresh_jobs()
        active = bool(self.thread and self.thread.is_alive())
        if active and self.bank_auto.isChecked() and self.tabs.currentIndex() == 1:
            self.refresh_bank()
        if not active and self.pipeline.cancel.is_set():
            self._auto_run = False
        if not active and self._auto_run and self.provider.enabled and self.store.next_job():
            self.start_worker()

    def refresh_jobs(self):
        if hasattr(self, "model_status"):
            actual = self.provider.observed_model or "아직 확인되지 않음"
            self.model_status.setText(f"최근 CLI 실행 모델: {actual} · 지정: {self.provider.model or 'CLI 기본값'} · 동시 {self.pipeline.workers}개")
        with self.store.connect() as db:
            counts = dict(db.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status"))
            paused = db.execute("SELECT error FROM jobs WHERE status='paused' ORDER BY updated DESC LIMIT 1").fetchone()
        active = bool(self.thread and self.thread.is_alive())
        if active:
            state = "종료 중" if self.pipeline.cancel.is_set() else "자동 처리 중"
        elif not self.provider.enabled:
            state = "AI 연결 꺼짐 — ‘자동 처리 시작 · 재개’를 누르세요."
        elif self.pipeline.cancel.is_set() or not self._auto_run:
            reason = self._worker_error or (paused[0] if paused else "사용자 중지")
            state = f"처리 정지: {reason} — 원인 해결 후 ‘자동 처리 시작 · 재개’를 누르세요."
        elif counts.get('queued', 0):
            state = "자동 시작 대기 (최대 1.5초)"
        elif counts.get('paused', 0):
            state = "중단 작업 있음 — ‘자동 처리 시작 · 재개’를 누르세요."
        else:
            state = "처리할 대기 작업 없음"
        self.queue_status.setText(f"대기 {counts.get('queued', 0)} · 실행 {counts.get('running', 0)} · 중단 {counts.get('paused', 0)} · 완료 {counts.get('done', 0)}\n{state}")
        self.job_rows = self.store.jobs()
        self.fill(self.jobs_table, [(j["kind"], j["target"][:12], j["status"], j["attempt"], j["method"], j["error"]) for j in self.job_rows])

    def refresh(self):
        self.documents = self.store.documents()
        self.fill(self.documents_table, [(d["name"], d["course"], d["pages"], d["created"][:10]) for d in self.documents])
        self.refresh_bank()
        self.exams = self.store.records("exam")
        self.fill(self.exam_table, [(e["title"], len(e["questions"]), "초안" if e.get("draft") else "완료 문항") for e in self.exams])
        self.students = self.store.records("student")
        self.fill(self.student_table, [(s["name"], s["class"], s["school"], s["grade"]) for s in self.students])
        self.assignments = self.store.records("assignment")
        self.fill(self.assignment_table, [(a["student"]["name"], a["exam"]["title"], a["deadline"], a["status"]) for a in self.assignments])
        self.refresh_jobs()

    def closeEvent(self, event):
        if self.thread and self.thread.is_alive():
            self.pipeline.cancel.set()
            self.statusBar().showMessage("진행 중인 AI 프로세스를 종료하고 있습니다. 잠시 후 다시 닫아주세요.")
            event.ignore()
            return
        super().closeEvent(event)


def main():
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("MathBank Desktop")
    app.setOrganizationName("MathBank")
    window = MainWindow()
    window.show()
    return app.exec()
