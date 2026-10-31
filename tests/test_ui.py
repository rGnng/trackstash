"""Qt widget smoke tests for the library browser and dialogs."""

from __future__ import annotations

import shutil
from pathlib import Path

from pytestqt.qtbot import QtBot

from trackstash.core.db import Database
from trackstash.core.library import LibraryService
from trackstash.core.metadata import write_tags
from trackstash.ui.dialogs import ImportDialog, TagEditorDialog
from trackstash.ui.main_window import MainWindow


def _library_with_tracks(tmp_path: Path, audio_factory: Path) -> tuple[Database, object]:
    root = tmp_path / "Library"
    root.mkdir()
    incoming = tmp_path / "Incoming"
    incoming.mkdir()
    source = incoming / "sample.flac"
    shutil.copy2(audio_factory / "sample.flac", source)
    write_tags(
        source,
        {
            "title": "UI Song",
            "artists": ["UI Artist"],
            "album": "UI Album",
            "album_artist": "UI Artist",
            "genres": ["Rock"],
        },
    )
    database = Database(tmp_path / "library.sqlite")
    service = LibraryService(database, artwork_dir=tmp_path / "Artwork")
    library = database.add_library(root, name="UI Library")
    plan = service.plan_import([incoming], library.id)
    service.execute_import(plan)
    return database, library


def test_main_window_lists_and_filters(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    database, library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database, artwork_dir=tmp_path / "Artwork")
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.refresh_tracks()

    assert window.model.rowCount() == 1
    window.search_edit.setText("UI Song")
    assert window.model.rowCount() == 1
    window.search_edit.setText("no such track")
    assert window.model.rowCount() == 0
    window.search_edit.clear()
    window.format_filter.setCurrentText("MP3")
    assert window.model.rowCount() == 0
    window.format_filter.setCurrentText("FLAC")
    assert window.model.rowCount() == 1
    assert library.id


def test_import_dialog_preview(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database, artwork_dir=tmp_path / "Artwork")
    incoming = tmp_path / "More"
    incoming.mkdir()
    shutil.copy2(audio_factory / "sample.mp3", incoming / "sample.mp3")
    write_tags(
        incoming / "sample.mp3",
        {
            "title": "Second Song",
            "artists": ["UI Artist"],
            "album": "UI Album",
            "album_artist": "UI Artist",
        },
    )
    dialog = ImportDialog(service, [library], library.id)
    qtbot.addWidget(dialog)
    dialog.source_edit.setText(str(incoming))
    dialog.preview()
    assert dialog.table.rowCount() == 1
    assert dialog.import_button.isEnabled()


def test_single_track_tag_editor(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database, artwork_dir=tmp_path / "Artwork")
    track = database.list_tracks(library_id=library.id)[0]
    dialog = TagEditorDialog(service, [track.id])
    qtbot.addWidget(dialog)
    assert dialog._lines["title"].text() == "UI Song"
    dialog._lines["title"].setText("Edited UI Song")
    assert dialog.edits()["title"] == "Edited UI Song"


def test_import_dialog_execute(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database, artwork_dir=tmp_path / "Artwork")
    incoming = tmp_path / "Execute"
    incoming.mkdir()
    shutil.copy2(audio_factory / "sample.mp3", incoming / "sample.mp3")
    write_tags(
        incoming / "sample.mp3",
        {
            "title": "Executed Song",
            "artists": ["UI Artist"],
            "album": "UI Album",
            "album_artist": "UI Artist",
        },
    )
    dialog = ImportDialog(service, [library], library.id)
    qtbot.addWidget(dialog)
    dialog.source_edit.setText(str(incoming))
    dialog.preview()
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    dialog.execute()
    assert dialog.import_result is not None
    assert len(dialog.import_result.imported) == 1
    assert database.track_count(library.id) == 2
