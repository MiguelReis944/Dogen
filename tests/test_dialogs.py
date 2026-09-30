import ctypes
import sys

from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import QApplication, QDialog, QTableWidget, QVBoxLayout

from storage.progress import ProgressStats
from storage.models import VocabItem
from ui.dogen_logo import DogenLogo, add_dialog_header
from ui.progress_dialog import ProgressDialog
from ui.settings_dialog import SettingsDialog
from ui.session_summary_dialog import SessionSummaryDialog
from ui.vocab_dialog import VocabDialog
from utils.config import AppConfig


class EmptyProgress:
    def stats(self, period_days, today):
        return ProgressStats(period_days, 0, 0, 0.0, 0, 0, None, None, {}, 0)


def test_dialogs_share_face_and_hud_palette(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialogs = [
        ProgressDialog(EmptyProgress()),
        SettingsDialog(AppConfig(), tmp_path / "settings.json"),
        VocabDialog([], lambda: None),
        SessionSummaryDialog({}),
    ]
    for dialog in dialogs:
        assert dialog.findChild(DogenLogo) is not None
        assert dialog.palette().window().color().name() == "#0a0e14"
        assert "QHeaderView::section" in dialog.styleSheet()
        dialog.close()


def test_logo_scale_changes_render_size():
    app = QApplication.instance() or QApplication([])
    logo = DogenLogo()
    original = logo.sizeHint()
    logo.setScale(0.5)
    assert logo.sizeHint().width() < original.width()
    assert logo.sizeHint().height() < original.height()
    assert not logo.grab().isNull()
    logo.close()


def test_vocabulary_alternate_rows_use_hud_palette():
    app = QApplication.instance() or QApplication([])
    dialog = VocabDialog(
        [
            VocabItem("I goed", "I went", "2026-09-18"),
            VocabItem("She go", "She goes", "2026-09-19"),
        ],
        lambda: None,
    )
    table = dialog.findChild(QTableWidget)

    assert table.palette().color(QPalette.AlternateBase).name() == "#111720"
    dialog.show()
    app.processEvents()
    alternate_row = table.visualItemRect(table.item(1, 0))
    alternate_background = table.viewport().grab().toImage().pixelColor(
        alternate_row.center()
    )
    assert alternate_background.name() == "#111720"
    corner = table.grab().toImage().pixelColor(
        table.verticalHeader().width() // 2,
        table.horizontalHeader().height() // 2,
    )
    assert corner.name() == "#111720"

    dialog.close()


def test_dialogs_have_dogen_window_icons(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialogs = [
        ProgressDialog(EmptyProgress()),
        SettingsDialog(AppConfig(), tmp_path / "settings.json"),
        VocabDialog([], lambda: None),
        SessionSummaryDialog({}),
    ]

    assert all(not dialog.windowIcon().isNull() for dialog in dialogs)
    icon_sizes = {
        size.width() for size in dialogs[0].windowIcon().availableSizes()
    }
    assert {16, 24, 32, 48, 64, 128, 256} <= icon_sizes

    for dialog in dialogs:
        dialog.close()


def test_windows_title_bar_uses_hud_caption_and_text_colors(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []

    class DwmApi:
        def DwmSetWindowAttribute(self, hwnd, attribute, value_pointer, size):
            value = ctypes.cast(value_pointer, ctypes.POINTER(ctypes.c_uint)).contents.value
            calls.append((attribute, value))
            return 0

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", lambda _: DwmApi(), raising=False)
    dialog = QDialog()

    add_dialog_header(dialog, QVBoxLayout(dialog), "Test")

    assert calls == [
        (20, 1),
        (34, 0x00473726),
        (35, 0x00261B11),
        (36, 0x00F5F1E8),
    ]
    dialog.close()
