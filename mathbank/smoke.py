"""Packaged executable acceptance probe using synthetic content only."""
import json
import os
from pathlib import Path
import tempfile


def run(destination):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from .desktop import MainWindow, Preview
    from .store import Store
    from .output import page_html
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    temp = tempfile.TemporaryDirectory()
    window = MainWindow(Store(temp.name))
    window.show()
    preview = Preview(page_html('<h1>MathBank Windows 실행 검사</h1><p>수식 $x^2+1$ 및 $\\frac{1}{2}$</p>'))
    preview.show()
    result = {'native_window': True, 'render_ready': False, 'pdf_saved': False}
    def finish():
        result['message'] = preview.message.text()
        (destination / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        app.quit()
    def printed(path, ok):
        result['pdf_saved'] = bool(ok and Path(path).exists() and Path(path).stat().st_size > 100)
        QTimer.singleShot(250, finish)
    preview.view.page().pdfPrintingFinished.connect(printed)
    timer = QTimer()
    def poll():
        if preview.ready:
            timer.stop()
            result['render_ready'] = True
            window.grab().save(str(destination / 'window.png'))
            preview.write_pdf(destination / 'smoke.pdf')
    timer.timeout.connect(poll)
    timer.start(150)
    QTimer.singleShot(45000, finish)
    app.exec()
    window.close()
    preview.close()
    temp.cleanup()
    return 0 if result['pdf_saved'] else 1
