from PyQt5.QtWidgets import QApplication

from storage.progress import ProgressStats
from ui.dogen_logo import DogenLogo
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
