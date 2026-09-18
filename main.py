"""Launch Dogen's local desktop conversation coach."""

import logging
import sys
import uuid
from datetime import date
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QMessageBox

from nlp.llm import ConversationContext
from storage.db import Database
from ui.main_window import MainWindow
from utils.config import load_config


def main():
    root = Path(__file__).resolve().parent
    config = load_config(root / "settings.json")
    logging.basicConfig(filename=root / "app.log", level=logging.INFO)
    app = QApplication(sys.argv)
    try:
        app.setStyleSheet((root / "ui" / "styles.qss").read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    try:
        import sounddevice as sd
        sd.check_input_settings(device=config.mic_device, samplerate=16000, channels=1)
    except Exception as exc:
        QMessageBox.critical(None, "Dogen", f"Microphone unavailable: {exc}")
        return 1
    try:
        with Database(root / "conversations.db") as db:
            today = str(date.today())
            if db.get_setting("session_date") == today:
                session_id = db.latest_session_id() or str(uuid.uuid4())
            else:
                session_id = str(uuid.uuid4())
                db.set_setting("session_date", today)
            context = ConversationContext(config.context_size, config.system_prompt)
            for message in db.recent_messages(session_id, 2 * config.context_size):
                context.add_message(message.role, message.content)
            window = MainWindow(config, db, context, session_id)
            window.show()
            return app.exec_()
    except Exception as exc:
        logging.exception("Dogen startup failed")
        QMessageBox.critical(None, "Dogen", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
