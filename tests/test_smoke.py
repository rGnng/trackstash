"""M0 smoke tests: application shell and required runtime capabilities."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import mutagen
from PySide6 import __version__ as pyside_version
from pytestqt.qtbot import QtBot

from trackstash import __version__
from trackstash.core.db import Database
from trackstash.ui.main_window import MainWindow


def test_package_version() -> None:
    assert __version__ == "0.1.0"


def test_pyside6_is_pinned() -> None:
    assert pyside_version == "6.11.3"


def test_main_window_starts(qtbot: QtBot, tmp_path: Path) -> None:
    database = Database(tmp_path / "library.sqlite")
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()

    assert window.windowTitle() == "TrackStash"
    assert window.centralWidget() is not None
    assert window.isVisible()


def test_application_uses_fusion_style(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QApplication

    from trackstash.app import configure_application

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    previous_style = app.style().objectName()
    try:
        configure_application(app)
        assert app.style().objectName().casefold() == "fusion"
    finally:
        app.setStyle(previous_style)


def test_songs_track_and_disc_columns_are_text(tmp_path: Path) -> None:
    database = Database(tmp_path / "schema.sqlite")
    with database.connect() as connection:
        columns = {
            row["name"]: row["type"]
            for row in connection.execute("PRAGMA table_info(songs)").fetchall()
        }
    assert columns["track"] == "TEXT"
    assert columns["track_total"] == "TEXT"
    assert columns["disc"] == "TEXT"
    assert columns["disc_total"] == "TEXT"


def test_sqlite_has_fts5() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE documents USING fts5(body)")
        connection.execute("INSERT INTO documents(body) VALUES (?)", ("TrackStash library",))
        row = connection.execute(
            "SELECT body FROM documents WHERE documents MATCH ?", ("trackstash",)
        ).fetchone()
    finally:
        connection.close()

    assert row == ("TrackStash library",)


def test_mutagen_is_importable() -> None:
    assert mutagen.version_string
