"""Native widget smoke test; PDF WebEngine tests are separate scripts."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from mathbank.desktop import MainWindow
from mathbank.store import Store


def test_native_sections_and_empty_state(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Store(tmp_path / 'data'))
    window.show()
    app.processEvents()
    assert window.windowTitle() == 'MathBank Desktop'
    for index in range(6):
        window.nav.setCurrentRow(index)
        app.processEvents()
        assert window.tabs.currentIndex() == index
    assert window.documents_table.rowCount() == 0
    assert window.bank_total == 0
    assert not window.provider.enabled
    window.close()
    app.processEvents()


def test_queued_jobs_start_automatically_and_pause_stays_paused(tmp_path):
    import time
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / 'queue')
    window = MainWindow(store)
    calls = []
    def run():
        calls.append(1)
        job=store.claim_job()
        if job: store.job_status(job['id'], 'done')
    window.pipeline.run = run
    store.enqueue('page','fixture:0')
    window.set_ai_enabled(True)
    window.poll_work()
    window.thread.join(timeout=3)
    app.processEvents()
    assert len(calls)==1
    store.enqueue('page','fixture:1')
    window.poll_work()
    window.thread.join(timeout=3)
    app.processEvents()
    assert len(calls)==2
    window.stop_processing()
    store.enqueue('page','fixture:2')
    window.poll_work()
    assert len(calls)==2
    window.close()


def test_bank_refresh_keeps_selection_and_detects_new_items(tmp_path):
    import pymupdf
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / 'bank')
    pdf=pymupdf.open();pdf.new_page();path=tmp_path/'source.pdf';pdf.save(path);pdf.close()
    doc,_=store.add_document(path)
    first=store.add_question(doc,[{'page':0,'box':[0,0,100,100]}])
    window=MainWindow(store)
    window.bank_table.selectRow(0)
    store.add_question(doc,[{'page':0,'box':[0,100,100,200]}])
    window.refresh_bank()
    assert window.bank_total==2
    rows=window.bank_table.selectionModel().selectedRows()
    assert len(rows)==1 and window.questions[rows[0].row()]['id']==first
    assert '갱신' in window.bank_count.text()
    window.close()
