"""Application bootstrap for the TrackStash desktop client."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import platformdirs
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from trackstash import __version__
from trackstash.core.db import Database
from trackstash.ui.main_window import MainWindow


def default_database_path() -> Path:
    """Return the default database location under Application Support."""
    return Path(platformdirs.user_data_dir("TrackStash")) / "library.sqlite"


def default_library_path() -> Path:
    """Return the default managed library location."""
    return Path.home() / "Music" / "TrackStash"


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Return the process-wide QApplication, creating it when necessary."""
    existing = QApplication.instance()
    if existing is not None:
        if not isinstance(existing, QApplication):
            raise RuntimeError("A non-GUI Qt application already exists")
        return existing

    arguments = list(argv) if argv is not None else [sys.argv[0]]
    return QApplication(arguments)


def configure_application(app: QApplication) -> None:
    """Apply application identity and the unified Qt-drawn visual style."""
    app.setApplicationName("TrackStash")
    app.setApplicationDisplayName("TrackStash")
    app.setOrganizationName("TrackStash")
    app.setOrganizationDomain("trackstash.app")
    app.setApplicationVersion(__version__)
    # Use one Qt style so controls and menus do not mix native and Qt-drawn looks.
    app.setStyle("Fusion")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="trackstash", description="TrackStash")
    parser.add_argument(
        "--database",
        type=Path,
        default=default_database_path(),
        help="Path to the TrackStash SQLite database.",
    )
    parser.add_argument(
        "--library-root",
        type=Path,
        default=default_library_path(),
        help="Default managed library root created when no library exists.",
    )
    parser.add_argument(
        "--no-default-library",
        action="store_true",
        help="Do not create the default library on first run.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Open the window and exit automatically after 800 ms.",
    )
    return parser.parse_args(list(argv) if argv is not None else sys.argv[1:])


def run(argv: Sequence[str] | None = None) -> int:
    """Start the desktop application and return its exit code."""
    args = _parse_args(argv)
    app = create_application([sys.argv[0]])
    configure_application(app)

    database = Database(args.database)
    if not args.no_default_library and not database.list_libraries():
        root = args.library_root.expanduser()
        try:
            root.mkdir(parents=True, exist_ok=True)
            database.add_library(root)
        except Exception as exc:
            QMessageBox.warning(
                None,
                "Default library",
                f"Could not create the default library at {root}:\n{exc}",
            )

    window = MainWindow(database)
    window.show()
    if args.smoke_test:
        QTimer.singleShot(800, app.quit)
    return app.exec()
