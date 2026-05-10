"""
Gerenciador de PC — Ponto de entrada principal.

Uso:
    python -m src.main
    python -m src.main --auto-scan
"""

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.gui.styles import GLOBAL_STYLESHEET
from src.gui.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Base neutra para o tema custom
    app.setStyleSheet(GLOBAL_STYLESHEET)

    window = MainWindow()
    window.show()

    # Auto-scan: dispara a varredura 1s após a janela abrir.
    if "--auto-scan" in sys.argv:
        QTimer.singleShot(1000, window._on_start_scan)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
