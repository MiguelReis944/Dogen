"""Render the Dogen face as a Windows executable and installer icon."""

from pathlib import Path
import sys

from PyQt5.QtWidgets import QApplication


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ui.dogen_logo import dogen_window_icon  # noqa: E402


def main():
    app = QApplication.instance() or QApplication([])
    target = PROJECT_ROOT / "build" / "artifacts" / "dogen.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not dogen_window_icon().pixmap(256, 256).save(str(target), "ICO"):
        raise RuntimeError(f"Could not generate the Dogen icon at {target}")
    app.quit()


if __name__ == "__main__":
    main()
