"""Application bootstrap for the TrackStash desktop client."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from trackstash import __version__
from trackstash.ui.main_window import MainWindow


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Return the process-wide QApplication, creating it when necessary."""
    existing = QApplication.instance()
    if existing is not None:
        if not isinstance(existing, QApplication):
            raise RuntimeError("A non-GUI Qt application already exists")
        return existing

    arguments = list(argv) if argv is not None else sys.argv
    return QApplication(arguments)


def configure_application(app: QApplication) -> None:
    """Apply application identity used by Qt and macOS."""
    app.setApplicationName("TrackStash")
    app.setApplicationDisplayName("TrackStash")
    app.setOrganizationName("TrackStash")
    app.setOrganizationDomain("trackstash.app")
    app.setApplicationVersion(__version__)


def run(argv: Sequence[str] | None = None) -> int:
    """Start the desktop application and return its exit code."""
    app = create_application(argv)
    configure_application(app)

    window = MainWindow()
    window.show()
    return app.exec()
