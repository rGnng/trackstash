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
    service = LibraryService(database)
    library = database.add_library(root, name="UI Library")
    plan = service.plan_import([incoming], library.id)
    service.execute_import(plan)
    return database, library


def test_main_window_lists_and_filters(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    database, library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
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
    service = LibraryService(database)
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
    dialog = ImportDialog(service, library)
    qtbot.addWidget(dialog)
    dialog.source_edit.setText(str(incoming))
    dialog.preview()
    assert dialog.table.rowCount() == 1
    assert dialog.import_button.isEnabled()


def test_single_track_tag_editor(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database)
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
    service = LibraryService(database)
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
    dialog = ImportDialog(service, library)
    qtbot.addWidget(dialog)
    dialog.source_edit.setText(str(incoming))
    dialog.preview()
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    dialog.execute()
    assert dialog.import_result is not None
    assert len(dialog.import_result.imported) == 1
    assert database.track_count(library.id) == 2


def test_album_grid_and_library_selector(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    database, library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()

    assert not hasattr(window, "library_combo")
    assert window._current_library_id == library.id
    assert window.tabs.count() == 2
    assert window.tabs.currentIndex() == 1
    assert window.albums_view_button.isChecked()
    assert not window.tracks_view_button.isChecked()
    assert window.albums_view_button.text() == "Albums"
    assert window.tracks_view_button.text() == "Tracks"
    assert window.album_model.rowCount() == 1
    assert window.album_model.data(window.album_model.index(0, 0)) is not None

    window.tracks_view_button.click()
    assert window.tabs.currentIndex() == 0
    assert window.tracks_view_button.isChecked()
    assert not window.albums_view_button.isChecked()
    window.albums_view_button.click()
    assert window.tabs.currentIndex() == 1

    window._album_activated(window.album_model.index(0, 0))
    assert window.tabs.currentIndex() == 0
    assert window.album_filter_label.isVisible()
    assert window.model.rowCount() == 1
    window.clear_album_filter()
    assert window.tabs.currentIndex() == 1
    assert window.album_view.selectionModel().hasSelection()
    assert window.model.rowCount() == 1


def test_album_grid_loads_cover_only_on_decoration(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from io import BytesIO

    from PIL import Image
    from PySide6.QtCore import Qt

    from trackstash.ui.models import AlbumGridModel

    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database)
    track = database.list_tracks(library_id=library.id)[0]
    cover = BytesIO()
    Image.new("RGB", (32, 32), (30, 90, 160)).save(cover, "JPEG")
    service.set_artwork([track.id], cover.getvalue(), mime="image/jpeg")
    albums = database.list_albums(library.id)
    model = AlbumGridModel(albums)
    assert not model._icons

    index = model.index(0, 0)
    model.data(index)
    assert not model._icons
    decoration = model.data(index, Qt.ItemDataRole.DecorationRole)
    assert len(model._icons) == 1
    assert decoration is not None


def test_album_grid_fills_viewport_with_fixed_gaps(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)

    window._update_album_grid(1100)
    assert window.album_view.iconSize().width() == 158
    assert window.album_view.gridSize().width() == 180
    assert window.album_view.gridSize().height() == 218

    window._update_album_grid(940)
    assert window.album_view.iconSize().width() == 162
    assert window.album_view.gridSize().width() == 184
    assert window.album_view.gridSize().height() == 222


def test_album_grid_does_not_show_year(qtbot: QtBot) -> None:
    from trackstash.core.db import AlbumRow
    from trackstash.ui.models import AlbumGridModel

    model = AlbumGridModel(
        [AlbumRow("album-id", "Album Title", "Album Artist", "2024", 1, None, "")]
    )
    text = model.data(model.index(0, 0))
    assert text == "Album Title\nAlbum Artist"
    assert "2024" not in str(text)


def test_qt_top_bar_replaces_menu(qtbot: QtBot, tmp_path: Path) -> None:
    database = Database(tmp_path / "menu.sqlite")
    window = MainWindow(database)
    qtbot.addWidget(window)
    assert window.menuBar().actions() == []
    assert not window.menuBar().isVisible()
    assert window.view_label.text() == "View"
    assert window.albums_view_button.text() == "Albums"
    assert window.tracks_view_button.text() == "Tracks"
    assert window.import_button.text() == "Import…"
    assert window.format_filter.currentText() == "All formats"
    assert window.missing_artwork_button.text() == "No artwork"
    assert window.undo_button.text() == "Undo"
    assert window.redo_button.text() == "Redo"
    assert window.settings_button.toolTip() == "Settings…"
    assert window.refresh_button.toolTip() == "Refresh (Ctrl+R)"
    assert not hasattr(window, "filters_button")
    assert not hasattr(window, "about_action")
    assert not hasattr(window, "help_action")
    assert not hasattr(window, "quit_action")
    assert not hasattr(window, "close_action")
    assert not hasattr(window, "selection_actions")
    assert not hasattr(window, "status_summary")


def test_inline_editor_and_column_persistence(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.tracks_view_button.click()
    window.table.selectRow(0)
    assert window.editor.lines["title"].text() == "UI Song"
    assert window.editor.edits()["title"] == "UI Song"
    assert window.import_action.text() == "Import…"
    assert window.import_button.text() == "Import…"

    from trackstash.ui.models import COLUMNS

    columns = [key for _, key in COLUMNS]
    assert "codec" in columns
    codec_index = columns.index("codec")
    bitrate_index = columns.index("bitrate")
    window.model.data(window.model.index(0, bitrate_index))
    assert "Kbps" in str(window.model.data(window.model.index(0, bitrate_index)))
    assert window.table.horizontalHeader().sectionsMovable()

    window._set_column_visible("codec", False)
    assert "codec" not in window.visible_columns()
    assert database.get_setting("track_columns")

    reopened = MainWindow(database)
    qtbot.addWidget(reopened)
    assert "codec" not in reopened.visible_columns()
    assert reopened.table.isColumnHidden(codec_index)


def test_library_manager_contains_scan_and_add(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from trackstash.ui.library_manager import LibraryManagerDialog

    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database)
    dialog = LibraryManagerDialog(database, service, library.id)
    qtbot.addWidget(dialog)
    assert dialog.quick_button.text() == "Quick Scan"
    assert dialog.full_button.text() == "Full Scan"
    assert dialog.library_combo.count() == 1


def test_left_editor_cannot_be_collapsed(qtbot: QtBot, tmp_path: Path) -> None:
    database = Database(tmp_path / "layout.sqlite")
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    assert not window.splitter.isCollapsible(0)
    window.splitter.setSizes([0, 1000])
    assert window.editor.isVisible()
    assert window.editor.width() >= 300


def test_window_size_persists(qtbot: QtBot, tmp_path: Path) -> None:
    database = Database(tmp_path / "window.sqlite")
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.resize(1360, 860)
    window.close()

    reopened = MainWindow(database)
    qtbot.addWidget(reopened)
    assert (reopened.width(), reopened.height()) == (1360, 860)


def test_legacy_default_template_is_migrated(qtbot: QtBot, tmp_path: Path) -> None:
    from trackstash.core.template import DEFAULT_TEMPLATE, LEGACY_DEFAULT_TEMPLATE

    database = Database(tmp_path / "template.sqlite")
    database.set_setting("default_template", LEGACY_DEFAULT_TEMPLATE)
    window = MainWindow(database)
    qtbot.addWidget(window)
    assert window.service.default_template == DEFAULT_TEMPLATE
    assert database.get_setting("default_template") == DEFAULT_TEMPLATE


def test_settings_can_choose_track_columns(qtbot: QtBot, tmp_path: Path) -> None:
    from trackstash.ui.dialogs import SettingsDialog
    from trackstash.ui.models import COLUMNS

    database = Database(tmp_path / "settings.sqlite")
    dialog = SettingsDialog(
        database,
        "{artist}/{album}/{title}",
        [(key, label) for label, key in COLUMNS],
        ["title", "codec"],
    )
    qtbot.addWidget(dialog)
    assert dialog.column_checks["codec"].isChecked()
    assert dialog.column_checks["path"].isChecked() is False
    assert dialog.values()[1] == ["title", "codec"]
    assert dialog.values()[2:] == ("date_added", "desc")


def test_settings_contains_library_actions(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QDialog

    from trackstash.ui.dialogs import SettingsDialog

    database = Database(tmp_path / "settings-library.sqlite")
    dialog = SettingsDialog(
        database,
        "{artist}/{album}/{title}",
        selection_available=True,
    )
    qtbot.addWidget(dialog)
    assert dialog.tabs.count() == 3
    assert set(dialog.library_buttons) == {
        "manage_libraries",
        "find_duplicates",
        "organize",
        "delete",
        "set_cover",
        "remove_cover",
        "extract_cover",
    }
    dialog.library_buttons["organize"].click()
    assert dialog.requested_action == "organize"
    assert dialog.result() == QDialog.DialogCode.Accepted

    empty = SettingsDialog(
        database,
        "{artist}/{album}/{title}",
        selection_available=False,
    )
    qtbot.addWidget(empty)
    assert empty.library_buttons["manage_libraries"].isEnabled()
    assert not empty.library_buttons["organize"].isEnabled()


def test_inline_save_and_table_sorting(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path, monkeypatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QMessageBox

    database, library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.tracks_view_button.click()
    window.table.selectRow(0)

    monkeypatch.setattr(
        "trackstash.ui.main_window.TagPreviewDialog.exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    window.save_inline_edits({"title": "Inline Edited"})
    tracks = database.list_tracks(library_id=library.id)
    assert tracks[0].title == "Inline Edited"
    assert window.editor.lines["title"].text() == "Inline Edited"

    window.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    assert window.model.rowCount() >= 1


def test_album_multi_selection(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QAbstractItemView

    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database)
    extra = tmp_path / "Extra"
    extra.mkdir()
    source = extra / "second.flac"
    shutil.copy2(audio_factory / "sample.flac", source)
    write_tags(
        source,
        {
            "title": "Second UI Song",
            "artists": ["UI Artist"],
            "album": "UI Album",
            "album_artist": "UI Artist",
        },
    )
    service.execute_import(service.plan_import([extra], library.id))
    from io import BytesIO

    from PIL import Image

    cover = BytesIO()
    Image.new("RGB", (32, 32), (20, 120, 180)).save(cover, "JPEG")
    track_ids = [track.id for track in database.list_tracks(library_id=library.id)]
    service.set_artwork(track_ids, cover.getvalue(), mime="image/jpeg")
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.tabs.setCurrentIndex(1)
    assert window.album_view.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
    window.album_view.selectAll()
    ids = window.selected_track_ids()
    assert len(ids) == 2
    assert window.editor.artwork_info.text()
    assert not window.editor._artwork_pixmap.isNull()
    assert window.editor.lines["title"].placeholderText() == "Multiple"
    assert window.editor.lines["title"].text() == ""

    from PySide6.QtWidgets import QDialog, QMessageBox

    monkeypatch.setattr(
        "trackstash.ui.main_window.TagPreviewDialog.exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    window.editor.lines["album"].setText("Batch Album")
    window.editor._field_changed("album")
    assert window.editor.pending_edits()["album"] == "Batch Album"
    window.save_inline_edits(window.editor.pending_edits())
    updated = database.list_tracks(library_id=library.id)
    assert all(track.album == "Batch Album" for track in updated)


def test_inline_pending_changes_and_go_to_album(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox

    database, library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.tracks_view_button.click()
    window.table.selectRow(0)
    editor = window.editor
    assert editor.has_pending_changes is False
    assert editor.pending_label.text() == ""

    editor.lines["title"].setText("Pending Title")
    editor._field_changed("title")
    assert editor.has_pending_changes is True
    assert editor.pending_edits()["title"] == "Pending Title"
    assert "pending change" in editor.pending_label.text()

    monkeypatch.setattr(
        "trackstash.ui.main_window.TagPreviewDialog.exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    window.save_inline_edits(editor.pending_edits())
    assert database.list_tracks(library_id=library.id)[0].title == "Pending Title"
    assert editor.has_pending_changes is False

    track = database.list_tracks(library_id=library.id)[0]
    window.go_to_album(track)
    assert window.tabs.currentIndex() == 1
    assert window.album_view.selectionModel().hasSelection()


def test_auto_fit_all_columns(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window._auto_fit_all_columns()
    assert database.get_setting("track_columns")


def test_track_and_disc_accept_text(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    from PySide6.QtWidgets import QLineEdit

    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.tracks_view_button.click()
    window.table.selectRow(0)
    editor = window.editor
    assert isinstance(editor.lines["track"], QLineEdit)
    assert isinstance(editor.lines["disc"], QLineEdit)
    assert not editor.lines["track"].isClearButtonEnabled()
    editor.lines["track"].setText("A1")
    editor._field_changed("track")
    assert editor.save_button.isEnabled() is True
    assert editor.pending_edits()["track"] == "A1"
