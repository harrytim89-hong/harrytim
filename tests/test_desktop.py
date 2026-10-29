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
