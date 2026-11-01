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
    qtbot.wait(300)
    assert window.model.rowCount() == 1
    window.search_edit.setText("no such track")
    qtbot.wait(300)
    assert window.model.rowCount() == 0
    window.search_edit.clear()
    window.format_actions["MP3"].trigger()
    assert window.model.rowCount() == 0
    window.format_actions["FLAC"].trigger()
    assert window.model.rowCount() == 1
    assert library.id


def test_import_dialog_preview(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database, default_template="{artist}/{album}/{title}")
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
            "track": 4,
            "track_total": 9,
        },
    )
    dialog = ImportDialog(service, library)
    qtbot.addWidget(dialog)
    assert dialog.table.columnCount() == 11
    assert [
        dialog.table.horizontalHeaderItem(column).text()
        for column in range(dialog.table.columnCount())
    ] == [
        "Track #",
        "Title",
        "Artist",
        "Album",
        "Album Artist",
        "Format",
        "Duration",
        "Source",
        "Destination",
        "Action",
        "Note",
    ]
    assert not hasattr(dialog, "template_edit")
    assert not hasattr(dialog, "preview_button")
    assert dialog.source_button.text() == "Add Source…"
    assert [action.text() for action in dialog.source_button.menu().actions()] == [
        "Files…",
        "Folder…",
    ]
    dialog.set_sources([str(incoming)])
    assert dialog.table.rowCount() == 1
    assert dialog.import_button.isEnabled()
    assert dialog.plan is not None
    assert dialog.table.item(0, 0).text() == "4/9"
    assert dialog.table.item(0, 1).text() == "Second Song"
    assert dialog.table.item(0, 2).text() == "UI Artist"
    assert dialog.table.item(0, 3).text() == "UI Album"
    assert dialog.table.item(0, 4).text() == "UI Artist"
    assert dialog.table.item(0, 5).text() == "MP3"
    assert dialog.table.item(0, 6).text() != ""
    assert dialog.plan.items[0].destination == (
        Path(library.path) / "UI Artist" / "UI Album" / "Second Song.mp3"
    )


def test_import_dialog_auto_previews_constructor_sources(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database)
    incoming = tmp_path / "Auto Preview"
    incoming.mkdir()
    shutil.copy2(audio_factory / "sample.mp3", incoming / "sample.mp3")
    dialog = ImportDialog(service, library, sources=[str(incoming)])
    qtbot.addWidget(dialog)
    qtbot.wait(20)
    assert dialog.plan is not None
    assert dialog.table.rowCount() == 1
    assert dialog.import_button.isEnabled()


def test_import_dialog_size_is_larger_and_persisted(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from PySide6.QtWidgets import QDialog

    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database)
    dialog = ImportDialog(service, library)
    qtbot.addWidget(dialog)
    assert (dialog.width(), dialog.height()) == (1240, 680)

    dialog.resize(1320, 720)
    dialog.done(QDialog.DialogCode.Rejected)
    assert database.get_setting("import_dialog_size") == "1320x720"

    reopened = ImportDialog(service, library)
    qtbot.addWidget(reopened)
    assert (reopened.width(), reopened.height()) == (1320, 720)


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
    dialog.set_sources([str(incoming)])
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


def test_album_grid_no_artwork_placeholder_is_dashed_outline(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from PySide6.QtCore import Qt

    from trackstash.ui.models import AlbumGridModel

    database, library = _library_with_tracks(tmp_path, audio_factory)
    model = AlbumGridModel(database.list_albums(library.id))
    model.set_cover_size(180)
    icon = model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole)
    assert icon is not None
    image = icon.pixmap(180, 180).toImage()
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(90, 90).alpha() == 0
    opaque = sum(
        1 for x in range(0, 180, 2) for y in range(0, 180, 2) if image.pixelColor(x, y).alpha()
    )
    assert 0 < opaque < 180 * 180 // 20


def test_import_dialog_accepts_dropped_folder(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database)
    incoming = tmp_path / "Dropped"
    incoming.mkdir()
    shutil.copy2(audio_factory / "sample.mp3", incoming / "sample.mp3")
    dialog = ImportDialog(service, library)
    qtbot.addWidget(dialog)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(incoming))])
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    dialog.dropEvent(event)
    assert dialog.plan is not None
    assert dialog.table.rowCount() == 1


def test_track_column_layout_round_trip(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    from trackstash.ui.models import COLUMNS

    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    keys = [key for _, key in COLUMNS]
    header = window.table.horizontalHeader()
    header.moveSection(header.visualIndex(keys.index("title")), 2)
    header.resizeSection(keys.index("title"), 333)
    window._set_column_visible("codec", False)
    window.close()

    reopened = MainWindow(database)
    qtbot.addWidget(reopened)
    reopened.show()
    reopened_header = reopened.table.horizontalHeader()
    order = [keys[reopened_header.logicalIndex(i)] for i in range(len(keys))]
    assert order.index("title") == 2
    assert reopened.table.columnWidth(keys.index("title")) == 333
    assert reopened.table.isColumnHidden(keys.index("codec"))


def test_back_to_albums_shortcut(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    from PySide6.QtGui import QKeySequence

    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window._album_activated(window.album_model.index(0, 0))
    assert window.tabs.currentIndex() == 0
    assert window._album_filter_id is not None

    assert window.back_to_albums_action.shortcut() == QKeySequence("Ctrl+[")
    window.back_to_albums_action.trigger()
    assert window.tabs.currentIndex() == 1
    assert window._album_filter_id is None


def test_album_grid_fills_viewport_with_fixed_gaps(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from trackstash.core.db import AlbumRow

    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.album_model.set_albums(
        [
            AlbumRow(f"album-{index}", f"Album {index}", "Artist", "2024", 1, None, "")
            for index in range(20)
        ]
    )

    from trackstash.ui.main_window import album_cover_layout

    assert album_cover_layout(1000) == (4, 216)
    assert album_cover_layout(1100) == (4, 241)
    assert album_cover_layout(1200) == (5, 207)
    assert album_cover_layout(1440) == (6, 208)
    assert album_cover_layout(1145) == (4, 252)

    window._update_album_grid(1000)
    assert window.album_view.iconSize().width() == 216
    assert window.album_view.spacing() == 22

    window._update_album_grid(1100)
    assert window.album_view.iconSize().width() == 241

    window._update_album_grid(1200)
    assert window.album_view.iconSize().width() == 207


def test_album_grid_cover_size_does_not_depend_on_album_count(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from trackstash.core.db import AlbumRow

    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    rows = [
        AlbumRow(f"album-{index}", f"Album {index}", "Artist", "2024", 1, None, "")
        for index in range(20)
    ]

    window.album_model.set_albums(rows[:3])
    window._update_album_grid(1145)
    few = window.album_view.iconSize().width()

    window.album_model.set_albums(rows)
    window._update_album_grid(1145)
    many = window.album_view.iconSize().width()

    assert few == many == 252


def test_album_context_menu_keeps_only_edit_and_delete(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    menu = window._album_menu()
    assert [action.text() for action in menu.actions()] == ["Edit Tags", "Delete"]


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
    assert not hasattr(window, "view_label")
    assert window.albums_view_button.text() == "Albums"
    assert window.tracks_view_button.text() == "Tracks"
    assert window.import_button.text() == "Import…"
    assert window.search_edit.placeholderText() == "Search"
    assert window.filter_button.text() == "Filter"
    assert not hasattr(window, "format_filter")
    assert not hasattr(window, "missing_artwork_button")
    filter_actions = window.filter_button.menu().actions()
    assert [action.text() for action in filter_actions[:10]] == [
        "All Formats",
        "FLAC",
        "MP3",
        "M4A",
        "OGG",
        "OPUS",
        "APE",
        "WV",
        "WAV",
        "AIFF",
    ]
    assert filter_actions[10].isSeparator()
    assert filter_actions[11].text() == "No Artwork"
    assert window.settings_button.toolTip() == "Settings…"
    assert window.refresh_button.toolTip() == "Refresh (Ctrl+R)"
    assert not hasattr(window, "filters_button")
    assert window.service.strong_order is True
    assert window.service.preserve_mtime is True
    assert window.service.artwork_max_size == 1000
    assert window.service.artwork_quality == 90
    assert window.service.artwork_aspect == "crop"
    assert not hasattr(window, "about_action")
    assert not hasattr(window, "help_action")
    assert not hasattr(window, "quit_action")
    assert not hasattr(window, "close_action")
    assert not hasattr(window, "selection_actions")
    assert not window.statusBar().isHidden()
    assert window.status_summary.text() == "No library selected"


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
    assert "path" not in window.visible_columns()
    assert window.table.isColumnHidden(columns.index("path"))
    window.model.data(window.model.index(0, bitrate_index))
    assert "Kbps" in str(window.model.data(window.model.index(0, bitrate_index)))
    assert window.table.horizontalHeader().sectionsMovable()

    window._set_column_visible("codec", False)
    window._set_column_visible("path", True)
    assert "codec" not in window.visible_columns()
    assert "path" in window.visible_columns()
    assert database.get_setting("track_columns")

    reopened = MainWindow(database)
    qtbot.addWidget(reopened)
    assert "codec" not in reopened.visible_columns()
    assert "path" in reopened.visible_columns()
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
    assert window.editor.width() >= 280


def test_editor_width_defaults_and_persists(qtbot: QtBot, tmp_path: Path) -> None:
    database = Database(tmp_path / "editor-width.sqlite")
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    assert window.editor.width() == 280

    window.splitter.setSizes([360, 800])
    window.close()
    reopened = MainWindow(database)
    qtbot.addWidget(reopened)
    reopened.show()
    assert reopened.editor.width() == 360


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
    assert dialog.values()[2:4] == ("date_added", "desc")
    assert dialog.values()[4:] == (True, True, True, 1000, 90, "crop")


def test_settings_column_changes_persist(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    from trackstash.ui.dialogs import SettingsDialog
    from trackstash.ui.models import COLUMNS

    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    columns = [(key, label) for label, key in COLUMNS]
    dialog = SettingsDialog(
        database,
        window.service.default_template,
        columns,
        window.visible_columns(),
    )
    qtbot.addWidget(dialog)
    assert dialog.column_checks["path"].isChecked() is False
    dialog.column_checks["path"].setChecked(True)
    dialog.column_checks["codec"].setChecked(False)
    window.set_visible_columns(dialog.values()[1])

    reopened = MainWindow(database)
    qtbot.addWidget(reopened)
    assert "path" in reopened.visible_columns()
    assert "codec" not in reopened.visible_columns()

    again = SettingsDialog(
        database,
        reopened.service.default_template,
        columns,
        reopened.visible_columns(),
    )
    qtbot.addWidget(again)
    assert again.column_checks["path"].isChecked()
    assert again.column_checks["codec"].isChecked() is False


def test_organize_dialog_template_controls(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from trackstash.core.template import DEFAULT_TEMPLATE
    from trackstash.ui.dialogs import OrganizeDialog

    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database)
    track = database.list_tracks(library_id=library.id)[0]
    dialog = OrganizeDialog(service, [track.id])
    qtbot.addWidget(dialog)
    assert dialog.template_edit.text() == service.default_template
    assert dialog.template_help_button.text() == "?"
    dialog.template_edit.setText("custom")
    dialog.template_default_button.click()
    assert dialog.template_edit.text() == DEFAULT_TEMPLATE
    assert dialog.items == []


def test_settings_contains_library_actions(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QDialog, QGroupBox

    from trackstash.ui.dialogs import SettingsDialog

    database = Database(tmp_path / "settings-library.sqlite")
    dialog = SettingsDialog(
        database,
        "{artist}/{album}/{title}",
    )
    qtbot.addWidget(dialog)
    from trackstash.core.template import DEFAULT_TEMPLATE

    assert dialog.tabs.count() == 3
    assert dialog.status_bar_checkbox.isChecked()
    assert set(dialog.library_buttons) == {"find_duplicates"}
    dialog.template_edit.setText("custom")
    dialog.template_default_button.click()
    assert dialog.template_edit.text() == DEFAULT_TEMPLATE
    assert "Current selection" not in [group.title() for group in dialog.findChildren(QGroupBox)]
    assert dialog.library_panel.library_combo.count() == 0
    library_tab = dialog.tabs.widget(2)
    general_tab = dialog.tabs.widget(0)
    assert library_tab.isAncestorOf(dialog.backup_button)
    assert not general_tab.isAncestorOf(dialog.backup_button)
    dialog.library_buttons["find_duplicates"].click()
    assert dialog.requested_action == "find_duplicates"
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_template_help_dialog_lists_and_copies_variables(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QApplication

    from trackstash.ui.dialogs import TemplateHelpDialog

    dialog = TemplateHelpDialog()
    qtbot.addWidget(dialog)
    text = dialog.browser.toPlainText()
    assert "{title}" in text
    assert "{track:02}" in text
    assert "{artist|Unknown Artist}" in text
    assert "{disc_prefix}" in text
    dialog.copy_button.click()
    assert "{title}" in QApplication.clipboard().text()


def test_status_bar_defaults_and_can_be_hidden(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.tracks_view_button.click()
    window.table.selectRow(0)
    assert window.statusBar().isVisible()
    assert window.status_summary.text() == "UI Library · 1 track"
    assert "TrackStash" not in window.status_summary.text()
    assert "1 selected" in window.status_selection.text()

    database.set_setting("status_bar_visible", "0")
    hidden = MainWindow(database)
    qtbot.addWidget(hidden)
    hidden.show()
    assert not hidden.statusBar().isVisible()


def test_settings_embeds_library_manager(qtbot: QtBot, tmp_path: Path, audio_factory: Path) -> None:
    from trackstash.ui.dialogs import SettingsDialog

    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database)
    dialog = SettingsDialog(
        database,
        "{artist}/{album}/{title}",
        service=service,
        current_library_id=library.id,
    )
    qtbot.addWidget(dialog)
    panel = dialog.library_panel
    assert panel.library_combo.count() == 1
    assert panel.library_combo.currentData() == library.id
    assert panel.path_value.text() == library.path
    assert "manage_libraries" not in dialog.library_buttons


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
    assert "Inline Edited" in tracks[0].path
    assert window.editor.lines["title"].text() == "Inline Edited"

    window.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    assert window.model.rowCount() >= 1


def test_tracks_and_album_detail_sorts_are_independent(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from PySide6.QtCore import Qt

    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.tracks_view_button.click()
    header = window.table.horizontalHeader()

    assert header.sortIndicatorSection() == window._column_index("added")
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder

    window.tabs.setCurrentIndex(1)
    window.refresh_albums()
    window._album_activated(window.album_model.index(0, 0))
    assert window._album_filter_id is not None
    assert header.sortIndicatorSection() == window._column_index("track")
    assert header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder

    window.table.sortByColumn(window._column_index("title"), Qt.SortOrder.DescendingOrder)
    assert database.get_setting("album_tracks_sort_field") == "title"
    assert database.get_setting("album_tracks_sort_order") == "desc"

    window.clear_album_filter()
    assert window._album_filter_id is None
    assert header.sortIndicatorSection() == window._column_index("added")
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder

    window.table.sortByColumn(window._column_index("artist"), Qt.SortOrder.AscendingOrder)
    assert database.get_setting("tracks_sort_field") == "artist"
    assert database.get_setting("tracks_sort_order") == "asc"

    reopened = MainWindow(database)
    qtbot.addWidget(reopened)
    reopened.show()
    reopened.refresh_libraries()
    reopened_header = reopened.table.horizontalHeader()
    assert reopened_header.sortIndicatorSection() == reopened._column_index("artist")
    assert reopened_header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder

    reopened.tabs.setCurrentIndex(1)
    reopened.refresh_albums()
    reopened._album_activated(reopened.album_model.index(0, 0))
    assert reopened_header.sortIndicatorSection() == reopened._column_index("title")
    assert reopened_header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder


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
    qtbot.wait(150)
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


def test_editor_reports_multiple_artworks(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from io import BytesIO

    from mutagen.flac import FLAC, Picture
    from PIL import Image

    from trackstash.core.metadata import read_metadata

    database, library = _library_with_tracks(tmp_path, audio_factory)
    track = database.list_tracks(library_id=library.id)[0]
    audio = FLAC(track.path)
    for kind in (3, 4):
        buffer = BytesIO()
        Image.new("RGB", (16, 16), (kind * 20, 50, 90)).save(buffer, "JPEG")
        picture = Picture()
        picture.type = kind
        picture.mime = "image/jpeg"
        picture.width = 16
        picture.height = 16
        picture.data = buffer.getvalue()
        audio.add_picture(picture)
    audio.save()
    LibraryService(database).db.upsert_tracks([read_metadata(track.path)], library)

    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.tracks_view_button.click()
    window.table.selectRow(0)
    assert "2 artworks" in window.editor.artwork_info.text()


def test_artwork_paste_is_applied_on_save(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    from trackstash.core.metadata import read_artwork

    database, library = _library_with_tracks(tmp_path, audio_factory)
    track = database.list_tracks(library_id=library.id)[0]
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.tracks_view_button.click()
    window.table.selectRow(0)
    assert track.has_artwork is False

    image = QImage(40, 20, QImage.Format.Format_RGB32)
    image.fill(QColor(20, 120, 180))
    QApplication.clipboard().setImage(image)
    window.editor._paste_artwork()
    assert window.editor.pending_artwork_data() is not None
    assert window.editor.save_button.isEnabled()
    assert database.get_track(track.id).has_artwork is False

    window.save_inline_edits({})
    refreshed = database.get_track(track.id)
    assert refreshed is not None
    assert refreshed.has_artwork is True
    assert len(read_artwork(refreshed.path)) == 1

    window.editor._set_pending_artwork_removal()
    assert window.editor.pending_artwork_removal()
    window.save_inline_edits({})
    assert database.get_track(track.id).has_artwork is False
    assert read_artwork(refreshed.path) == []
    QApplication.clipboard().clear()


def test_editor_copies_artwork_to_clipboard(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    from io import BytesIO

    from PIL import Image
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    database, library = _library_with_tracks(tmp_path, audio_factory)
    service = LibraryService(database)
    track = database.list_tracks(library_id=library.id)[0]
    cover = BytesIO()
    Image.new("RGB", (36, 24), (30, 90, 160)).save(cover, "JPEG")
    service.set_artwork([track.id], cover.getvalue(), mime="image/jpeg")

    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.tracks_view_button.click()
    window.table.selectRow(0)
    assert not window.editor._artwork_pixmap.isNull()

    QApplication.clipboard().clear()
    window.editor.artwork.setFocus()
    QTest.keyClick(window.editor.artwork, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    copied = QApplication.clipboard().image()
    assert not copied.isNull()
    assert copied.size() == window.editor._artwork_pixmap.size()
    QApplication.clipboard().clear()


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


def test_added_time_column_is_visible_and_formatted(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    import re

    from trackstash.ui.models import COLUMNS

    database, _library = _library_with_tracks(tmp_path, audio_factory)
    window = MainWindow(database)
    qtbot.addWidget(window)
    window.show()
    window.refresh_libraries()
    window.tracks_view_button.click()
    keys = [key for _, key in COLUMNS]
    added_index = keys.index("added")
    assert "added" in window.visible_columns()
    text = str(window.model.data(window.model.index(0, added_index)))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", text)


def test_added_column_is_migrated_into_old_column_config(
    qtbot: QtBot, tmp_path: Path, audio_factory: Path
) -> None:
    import json

    from trackstash.ui.models import COLUMNS

    database, _library = _library_with_tracks(tmp_path, audio_factory)
    keys = [key for _, key in COLUMNS]
    old_visible = [key for key in keys if key not in {"added", "album_artist", "path"}]
    database.set_setting(
        "track_columns",
        json.dumps(
            {
                "visible": old_visible,
                "order": [key for key in keys if key != "added"],
                "widths": {key: 100 for key in keys if key != "added"},
            }
        ),
    )
    window = MainWindow(database)
    qtbot.addWidget(window)
    assert "added" in window.visible_columns()


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
