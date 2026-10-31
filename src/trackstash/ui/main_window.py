"""Main application window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from trackstash import __version__


class MainWindow(QMainWindow):
    """Top-level TrackStash window.

    M0 intentionally contains only the application shell. Library, import, and
    tagging workflows are added in later milestones.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TrackStash")
        self.resize(1200, 800)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        placeholder = QLabel("TrackStash", central)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setObjectName("placeholderLabel")
        layout.addWidget(placeholder)
        self.setCentralWidget(central)

        self.statusBar().showMessage(f"M0 scaffold · v{__version__}")
