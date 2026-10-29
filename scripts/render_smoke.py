"""Generate actual Qt-rendered fixtures; no production data."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from mathbank.desktop import Preview, MainWindow
from mathbank.output import page_html
from mathbank.store import Store
import tempfile

app = QApplication([])
root = Path(__file__).resolve().parents[1] / 'artifacts'
root.mkdir(exist_ok=True)
temp = tempfile.TemporaryDirectory()
window = MainWindow(Store(temp.name))
window.show()
window.grab().save(str(root / 'desktop.png'))
preview = Preview(page_html('<h1>MathBank 출력 시험</h1><p>수식 $y=|x+1|-|x-2|$</p><p>직선 $mx-y+3m-4=0$</p><p>분수 $\\frac{x^2+1}{2}$</p><svg xmlns="http://www.w3.org/2000/svg" width="200" height="160"><circle cx="80" cy="80" r="50" fill="none" stroke="black"/></svg>'))
preview.show()
result = {'ok':False}
def done(path, ok):
    result['ok'] = ok
    QTimer.singleShot(500, app.quit)
preview.view.page().pdfPrintingFinished.connect(done)
def poll():
    if preview.ready:
        timer.stop()
        preview.view.grab().save(str(root / 'render-preview.png'))
        preview.write_pdf(root / 'render-smoke.pdf')
timer = QTimer()
timer.timeout.connect(poll)
timer.start(200)
QTimer.singleShot(45000, app.quit)
app.exec()
print(preview.message.text())
sys.exit(0 if result['ok'] else 1)
