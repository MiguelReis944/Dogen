"""Launch Dogen's local desktop conversation coach."""

import sys
import uuid
from datetime import date

from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

from nlp.llm import ConversationContext, build_system_prompt
from storage.db import Database
from ui.dogen_logo import dogen_window_icon, set_windows_app_user_model_id
from ui.main_window import MainWindow
from ui.setup_wizard import SetupWizard, should_show_setup_wizard
from utils.config import load_config, save_config
from utils.diagnostics import (
    configure_local_diagnostics,
    local_diagnostics_path,
    log_diagnostic,
)
from utils.paths import (
    app_data_root,
    app_resource_root,
    configure_model_cache_dirs,
    conversations_path,
    is_frozen,
    settings_path,
    setup_marker_path,
)


def main():
    configure_model_cache_dirs()
    set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName("Dogen")
    app.setWindowIcon(dogen_window_icon())
    root = app_resource_root()
    data_root = app_data_root()
    data_root.mkdir(parents=True, exist_ok=True)
    user_settings_path = settings_path()
    config = load_config(user_settings_path)
    marker_path = setup_marker_path()
    if should_show_setup_wizard(is_frozen(), marker_path):
        wizard = SetupWizard(config)
        if wizard.exec_() != QDialog.Accepted:
            return 0
        save_config(config, user_settings_path)
        if wizard.hide_next_time.isChecked():
            marker_path.touch()
    if config.diagnostics_enabled:
        diagnostics_path = local_diagnostics_path()
        if diagnostics_path is None or not configure_local_diagnostics(diagnostics_path):
            QMessageBox.warning(
                None,
                "Diagnostics unavailable",
                "Dogen could not create its local diagnostics file. "
                "The app will continue without recording diagnostics.",
            )
    try:
        app.setStyleSheet((root / "ui" / "styles.qss").read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    try:
        import sounddevice as sd
        sd.check_input_settings(device=config.mic_device, samplerate=16000, channels=1)
    except Exception as exc:
        QMessageBox.critical(None, "Dogen", f"Microphone unavailable: {exc}")
        log_diagnostic("audio_error", stage="capture", error_type=type(exc).__name__)
        return 1
    try:
        with Database(conversations_path()) as db:
            today = str(date.today())
            if db.get_setting("session_date") == today:
                session_id = (
                    db.get_setting("session_id")
                    or db.latest_session_id()
                    or str(uuid.uuid4())
                )
            else:
                session_id = str(uuid.uuid4())
            db.set_setting("session_date", today)
            db.set_setting("session_id", session_id)
            # Prompt policy evolves with the app; do not revive a stale serialized prompt.
            context = ConversationContext(config.context_size, build_system_prompt())
            for message in db.recent_context_messages(session_id, 2 * config.context_size):
                context.add_message(message.role, message.content)
            window = MainWindow(config, db, context, session_id,
                                settings_path=user_settings_path)
            window.show()
            exit_code = app.exec_()
            log_diagnostic("app_shutdown", state="shutdown")
            return exit_code
    except Exception as exc:
        log_diagnostic("startup_failed", stage="startup", error_type=type(exc).__name__)
        QMessageBox.critical(None, "Dogen", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
