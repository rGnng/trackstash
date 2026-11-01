"""TrackStash main window: left media editor, right tracks/albums views."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PySide6.QtCore import (
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QProcess,
    QSize,
    Qt,
    QUrl,
)
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from trackstash import __version__
from trackstash.core.db import Database, Library, Track
from trackstash.core.library import LibraryService, content_hash
from trackstash.core.metadata import read_metadata
from trackstash.core.template import DEFAULT_TEMPLATE
from trackstash.ui.dialogs import (
    AutoNumberDialog,
    DeleteDialog,
    DuplicateDialog,
    ImportDialog,
    OrganizeDialog,
    SettingsDialog,
    TagEditorDialog,
    TagPreviewDialog,
)
from trackstash.ui.editor import TrackInfoEditor
from trackstash.ui.library_manager import LibraryManagerDialog
from trackstash.ui.models import COLUMNS, AlbumGridModel, TrackTableModel

DEFAULT_WIDTHS = {
    "title": 180,
    "artist": 130,
    "album_artist": 130,
    "album": 150,
    "year": 50,
    "track": 45,
    "disc": 40,
    "genre": 100,
    "format": 55,
    "codec": 65,
    "bitrate": 95,
    "duration": 55,
    "path": 220,
}


class MainWindow(QMainWindow):
    """Main library browser and editor."""

    def __init__(
        self,
        db: Database,
        *,
        artwork_dir: str | Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.service = LibraryService(db, artwork_dir=artwork_dir)
        self.service.default_template = db.get_setting("default_template", DEFAULT_TEMPLATE)
        try:
            self.service.cover_size = int(db.get_setting("cover_size", "500") or 500)
            self.service.cover_quality = int(db.get_setting("cover_quality", "80") or 80)
        except ValueError:
            self.service.cover_size = 500
            self.service.cover_quality = 80
        self._current_library_id: str | None = None
        self._album_filter_id: str | None = None
        self._album_filter_title = ""
        self._album_return_id: str | None = None
        self._libraries: list[Library] = []
        self._column_config: dict[str, object] = {}
        self._loading_columns = False
        self._columns_ready = False
        self.tabs: QStackedWidget

        self.setWindowTitle("TrackStash")
        self.resize(1440, 900)
        self.setMinimumSize(1280, 700)

        self._create_actions()
        self._create_menus()
        self._create_central_widget()
        self._create_status_bar()
        self.refresh_libraries()

    # ------------------------------------------------------------------
    # Actions and menus

    def _create_actions(self) -> None:
        self.import_action = QAction("Import…", self)
        self.import_action.setShortcut(QKeySequence("Ctrl+I"))
        self.import_action.triggered.connect(self.import_files)

        self.close_action = QAction("Close Window", self)
        self.close_action.setShortcut(QKeySequence.StandardKey.Close)
        self.close_action.triggered.connect(self.close)

        self.quit_action = QAction("Quit", self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)

        self.library_manager_action = QAction("Library Manager…", self)
        self.library_manager_action.setShortcut(QKeySequence("Ctrl+L"))
        self.library_manager_action.triggered.connect(self.open_library_manager)

        self.organize_action = QAction("Organize…", self)
        self.organize_action.triggered.connect(self.organize)
        self.delete_action = QAction("Delete…", self)
        self.delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.delete_action.triggered.connect(self.delete_tracks)
        self.duplicates_action = QAction("Find Duplicates…", self)
        self.duplicates_action.triggered.connect(self.find_duplicates)

        self.set_cover_action = QAction("Set Cover…", self)
        self.set_cover_action.triggered.connect(self.set_cover)
        self.remove_cover_action = QAction("Remove Cover", self)
        self.remove_cover_action.triggered.connect(self.remove_cover)
        self.extract_cover_action = QAction("Extract Cover…", self)
        self.extract_cover_action.triggered.connect(self.extract_cover)
        self.reveal_action = QAction("Reveal in Finder", self)
        self.reveal_action.triggered.connect(self.reveal_selected)

        self.edit_action = QAction("Edit Tags…", self)
        self.edit_action.setShortcut(QKeySequence("Ctrl+E"))
        self.edit_action.triggered.connect(self.edit_tags)
        self.auto_number_action = QAction("Auto-number Tracks…", self)
        self.auto_number_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.auto_number_action.triggered.connect(self.auto_number_tracks)
        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        self.redo_action.triggered.connect(self.redo)

        self.settings_action = QAction("Settings…", self)
        self.settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_action.triggered.connect(self.open_settings)

        self.tracks_view_action = QAction("Tracks", self)
        self.tracks_view_action.setShortcut(QKeySequence("Ctrl+1"))
        self.tracks_view_action.setCheckable(True)
        self.tracks_view_action.setChecked(False)
        self.tracks_view_action.triggered.connect(lambda: self.tabs.setCurrentIndex(0))
        self.albums_view_action = QAction("Albums", self)
        self.albums_view_action.setShortcut(QKeySequence("Ctrl+2"))
        self.albums_view_action.setCheckable(True)
        self.albums_view_action.setChecked(True)
        self.albums_view_action.triggered.connect(lambda: self.tabs.setCurrentIndex(1))
        self.focus_search_action = QAction("Search", self)
        self.focus_search_action.setShortcut(QKeySequence.StandardKey.Find)
        self.focus_search_action.triggered.connect(self.focus_search)
        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.refresh_action.triggered.connect(self.refresh_tracks)

        self.help_action = QAction("TrackStash Help", self)
        self.help_action.setShortcut(QKeySequence("F1"))
        self.help_action.triggered.connect(self.show_help)
        self.about_action = QAction("About TrackStash", self)
        self.about_action.triggered.connect(self.show_about)
        self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
        self.settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.quit_action.setMenuRole(QAction.MenuRole.QuitRole)

    def _create_menus(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.setNativeMenuBar(True)

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.import_action)
        file_menu.addSeparator()
        file_menu.addAction(self.close_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        library_menu = menu_bar.addMenu("&Library")
        library_menu.addAction(self.library_manager_action)
        library_menu.addSeparator()
        library_menu.addAction(self.organize_action)
        library_menu.addAction(self.delete_action)
        library_menu.addAction(self.duplicates_action)
        library_menu.addSeparator()
        library_menu.addAction(self.set_cover_action)
        library_menu.addAction(self.remove_cover_action)
        library_menu.addAction(self.extract_cover_action)
        library_menu.addAction(self.reveal_action)

        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self.edit_action)
        edit_menu.addAction(self.auto_number_action)
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.settings_action)

        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.tracks_view_action)
        view_menu.addAction(self.albums_view_action)
        view_menu.addSeparator()
        view_menu.addAction(self.focus_search_action)
        view_menu.addAction(self.refresh_action)

        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self.help_action)
        help_menu.addAction(self.about_action)

    # ------------------------------------------------------------------
    # Layout

    def _create_central_widget(self) -> None:
        outer = QWidget(self)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(4, 4, 4, 4)
        outer_layout.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal, outer)
        splitter.setHandleWidth(3)
        splitter.setStyleSheet(
            "QSplitter::handle { background-color: #1E2632; image: none; }"
            "QSplitter::handle:hover { background-color: #48D1B5; }"
        )
        self.editor = TrackInfoEditor(splitter)
        self.editor.setMinimumWidth(340)
        self.editor.setMaximumWidth(460)
        self.editor.save_requested.connect(self.save_inline_edits)
        self.editor.cover_requested.connect(self.set_cover)
        self.editor.remove_cover_requested.connect(self.remove_cover)
        self.editor.extract_cover_requested.connect(self.extract_cover)
        self.editor.reveal_requested.connect(self.reveal_selected)
        splitter.addWidget(self.editor)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(4)

        library_row = QHBoxLayout()
        view_label = QLabel("View:", right)
        library_row.addWidget(view_label)
        self.albums_view_button = QPushButton("Albums", right)
        self.tracks_view_button = QPushButton("Tracks", right)
        self.albums_view_button.setObjectName("viewSwitchFirst")
        self.tracks_view_button.setObjectName("viewSwitchLast")
        view_button_style = (
            "QPushButton { border: 1px solid palette(mid); padding: 3px 10px; }"
            "QPushButton#viewSwitchFirst { border-top-left-radius: 5px;"
            " border-bottom-left-radius: 5px; }"
            "QPushButton#viewSwitchLast { border-left: none;"
            " border-top-right-radius: 5px; border-bottom-right-radius: 5px; }"
            "QPushButton:checked { background-color: palette(highlight);"
            " color: palette(highlighted-text); border-color: palette(highlight); }"
        )
        self._view_button_group = QButtonGroup(right)
        self._view_button_group.setExclusive(True)
        for button, index in (
            (self.albums_view_button, 1),
            (self.tracks_view_button, 0),
        ):
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setStyleSheet(view_button_style)
            button.setMinimumWidth(70)
            button.clicked.connect(
                lambda _checked=False, page=index: self.tabs.setCurrentIndex(page)
            )
            self._view_button_group.addButton(button)
            library_row.addWidget(button)
        self.albums_view_button.setChecked(True)
        self.albums_view_button.setToolTip("Albums view (Ctrl+2)")
        self.tracks_view_button.setToolTip("Tracks view (Ctrl+1)")
        library_row.addSpacing(10)
        library_row.addWidget(QLabel("Library", right))
        self.library_combo = QComboBox(right)
        self.library_combo.setMinimumWidth(150)
        self.library_combo.setMaximumWidth(220)
        self.library_combo.currentIndexChanged.connect(self._library_changed)
        library_row.addWidget(self.library_combo)
        manage = QPushButton("Manage…", right)
        manage.clicked.connect(self.open_library_manager)
        library_row.addWidget(manage)
        self.search_edit = QLineEdit(right)
        self.search_edit.setPlaceholderText("Search title, artist, album, genre, path…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(170)
        self.search_edit.textChanged.connect(self.refresh_tracks)
        library_row.addWidget(self.search_edit, 1)
        self.format_filter = QComboBox(right)
        self.format_filter.addItem("All formats", "")
        for extension in ("FLAC", "MP3", "M4A", "OGG", "OPUS", "APE", "WV", "WAV", "AIFF"):
            self.format_filter.addItem(extension, extension)
        self.format_filter.currentIndexChanged.connect(self.refresh_tracks)
        library_row.addWidget(self.format_filter)
        self.missing_artwork = QCheckBox("Missing artwork", right)
        self.missing_artwork.stateChanged.connect(self.refresh_tracks)
        library_row.addWidget(self.missing_artwork)
        right_layout.addLayout(library_row)

        self.tabs = QStackedWidget(right)
        self.tabs.currentChanged.connect(self._tab_changed)

        tracks_tab = QWidget(self.tabs)
        tracks_layout = QVBoxLayout(tracks_tab)
        tracks_layout.setContentsMargins(0, 0, 0, 0)
        filter_row = QHBoxLayout()
        self.album_filter_label = QLabel("", tracks_tab)
        self.album_filter_label.setVisible(False)
        self.clear_album_filter_button = QPushButton("Show all albums", tracks_tab)
        self.clear_album_filter_button.setVisible(False)
        self.clear_album_filter_button.clicked.connect(self.clear_album_filter)
        filter_row.addWidget(self.album_filter_label)
        filter_row.addWidget(self.clear_album_filter_button)
        filter_row.addStretch(1)
        tracks_layout.addLayout(filter_row)

        self.model = TrackTableModel()
        self.table = QTableView(tracks_tab)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setStretchLastSection(False)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._column_context_menu)
        header.sectionMoved.connect(self._column_layout_changed)
        header.sectionResized.connect(self._column_layout_changed)
        header.sectionHandleDoubleClicked.connect(self._auto_fit_column)
        header.sectionDoubleClicked.connect(self._auto_fit_column)
        self.table.doubleClicked.connect(self.edit_tags)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._track_context_menu)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        tracks_layout.addWidget(self.table, 1)
        self.tabs.addWidget(tracks_tab)

        albums_tab = QWidget(self.tabs)
        albums_layout = QVBoxLayout(albums_tab)
        albums_layout.setContentsMargins(0, 0, 0, 0)
        self.album_model = AlbumGridModel()
        self.album_view = QListView(albums_tab)
        self.album_view.setModel(self.album_model)
        self.album_view.setViewMode(QListView.ViewMode.IconMode)
        self.album_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.album_view.setMovement(QListView.Movement.Static)
        self.album_view.setUniformItemSizes(True)
        self.album_view.setWordWrap(True)
        self.album_view.setIconSize(QSize(180, 180))
        self.album_view.setGridSize(QSize(220, 260))
        self.album_view.setSpacing(8)
        self.album_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.album_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.album_view.setSelectionRectVisible(True)
        self.album_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.album_view.customContextMenuRequested.connect(self._album_context_menu)
        self.album_view.doubleClicked.connect(self._album_activated)
        self.album_view.selectionModel().selectionChanged.connect(self._selection_changed)
        albums_layout.addWidget(self.album_view, 1)
        self.tabs.addWidget(albums_tab)
        right_layout.addWidget(self.tabs, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 1060])
        outer_layout.addWidget(splitter, 1)

        self.setCentralWidget(outer)

        self._load_column_config()
        self.tabs.setCurrentIndex(1)

    def _create_status_bar(self) -> None:
        self.status_summary = QLabel("", self)
        self.status_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.statusBar().addWidget(self.status_summary)
        self.status_selection = QLabel("", self)
        self.status_selection.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.statusBar().addWidget(self.status_selection)
        self._library_label = ""
        self._total_tracks = 0
        self._status_message = ""
        self._update_status()

    def set_status_message(self, message: str) -> None:
        self._status_message = message
        self._update_status()

    def _selection_item_count(self) -> int:
        if hasattr(self, "tabs") and self.tabs.currentIndex() == 1 and hasattr(self, "album_view"):
            selection = self.album_view.selectionModel()
            return len(selection.selectedIndexes()) if selection is not None else 0
        return len(self.selected_track_ids())

    def _update_status(self) -> None:
        if not hasattr(self, "status_summary"):
            return
        base = (
            f"{self._library_label} · {self._total_tracks} tracks"
            if self._library_label
            else "No library selected"
        )
        details: list[str] = []
        selected = self._selection_item_count()
        if selected:
            details.append(f"{selected} selected")
        if self._status_message:
            details.append(self._status_message)
        self.status_summary.setText(base)
        self.status_selection.setText(" · ".join(details))

    # ------------------------------------------------------------------
    # Library selection

    def refresh_libraries(self) -> None:
        previous = self._current_library_id
        self._libraries = self.db.list_libraries()
        self.library_combo.blockSignals(True)
        self.library_combo.clear()
        for library in self._libraries:
            count = self.db.library_track_count(library.id)
            suffix = "" if library.enabled else " · disabled"
            self.library_combo.addItem(f"{library.name}  ({count}){suffix}", library.id)
        self.library_combo.blockSignals(False)
        if not self._libraries:
            self.library_combo.setEnabled(False)
            self._current_library_id = None
            self._album_filter_id = None
            self.refresh_tracks()
            return
        self.library_combo.setEnabled(True)
        index = self.library_combo.findData(previous) if previous else 0
        if index < 0:
            index = 0
        self.library_combo.blockSignals(True)
        self.library_combo.setCurrentIndex(index)
        self.library_combo.blockSignals(False)
        self._current_library_id = str(self.library_combo.currentData() or "") or None
        if previous != self._current_library_id:
            self._album_filter_id = None
            self._album_filter_title = ""
        self.refresh_tracks()

    def _library_changed(self, _index: int) -> None:
        self._current_library_id = str(self.library_combo.currentData() or "") or None
        self._album_filter_id = None
        self._album_filter_title = ""
        self._album_return_id = None
        self.refresh_tracks()

    def open_library_manager(self) -> None:
        dialog = LibraryManagerDialog(self.db, self.service, self._current_library_id, self)
        dialog.exec()
        if dialog.current_library_id:
            self._current_library_id = dialog.current_library_id
        self.refresh_libraries()

    # ------------------------------------------------------------------
    # Track and album views

    def refresh_tracks(self) -> None:
        query = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        if not self._current_library_id:
            self.model.set_tracks([])
            self.editor.clear()
            self._update_album_filter_ui()
            self._library_label = ""
            self._total_tracks = 0
            self._status_message = ""
            self._update_status()
            if hasattr(self, "album_model"):
                self.album_model.set_albums([])
            return
        tracks = self.db.list_tracks(
            library_id=self._current_library_id,
            album_id=self._album_filter_id,
            query=query,
        )
        format_value = str(self.format_filter.currentData() or "")
        if format_value:
            tracks = [track for track in tracks if track.format.upper() == format_value]
        if self.missing_artwork.isChecked():
            tracks = [track for track in tracks if not self._track_has_artwork(track)]
        self.model.set_tracks(tracks)
        library = self.db.get_library(self._current_library_id)
        label = library.name if library else "Library"
        self._update_album_filter_ui()
        self._library_label = label
        self._total_tracks = len(tracks)
        self._status_message = ""
        self._update_status()
        self.refresh_albums()
        if not self.selected_track_ids():
            self.editor.clear()

    def refresh_albums(self) -> None:
        if not hasattr(self, "album_model"):
            return
        if not self._current_library_id:
            self.album_model.set_albums([])
            return
        query = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        albums = self.db.list_albums(self._current_library_id, query=query)
        self.album_model.set_albums(albums)

    def _tab_changed(self, index: int) -> None:
        if hasattr(self, "tracks_view_action"):
            self.tracks_view_action.setChecked(index == 0)
            self.albums_view_action.setChecked(index == 1)
        if hasattr(self, "albums_view_button"):
            self.albums_view_button.setChecked(index == 1)
            self.tracks_view_button.setChecked(index == 0)
        if index == 1:
            self.refresh_albums()
        self._selection_changed()
        self._update_status()

    def _album_context_menu(self, position: QPoint) -> None:
        index = self.album_view.indexAt(position)
        if not index.isValid():
            return
        selection = self.album_view.selectionModel()
        if not selection.isSelected(index):
            self.album_view.setCurrentIndex(index)
            selection.select(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )
        menu = QMenu(self)
        edit = menu.addAction("Edit Tags for Selected Albums…")
        auto = menu.addAction("Auto-number Tracks…")
        organize = menu.addAction("Organize…")
        delete = menu.addAction("Delete…")
        chosen = menu.exec(self.album_view.viewport().mapToGlobal(position))
        if chosen == edit:
            self.edit_tags()
        elif chosen == auto:
            self.auto_number_tracks()
        elif chosen == organize:
            self.organize()
        elif chosen == delete:
            self.delete_tracks()

    def _album_activated(self, index: QModelIndex) -> None:
        album = self.album_model.album_at(index.row())
        if album is None:
            return
        self._album_filter_id = album.id
        self._album_filter_title = album.title
        self._album_return_id = album.id
        self.tabs.setCurrentIndex(0)
        self.refresh_tracks()
        if self.model.rowCount():
            self.table.selectRow(0)

    def clear_album_filter(self) -> None:
        return_id = self._album_return_id
        self._album_filter_id = None
        self._album_filter_title = ""
        self._album_return_id = None
        self.refresh_tracks()
        if return_id:
            self.tabs.setCurrentIndex(1)
            self.refresh_albums()
            for row in range(self.album_model.rowCount()):
                album = self.album_model.album_at(row)
                if album is not None and album.id == return_id:
                    index = self.album_model.index(row, 0)
                    self.album_view.setCurrentIndex(index)
                    self.album_view.selectionModel().select(
                        index,
                        QItemSelectionModel.SelectionFlag.ClearAndSelect,
                    )
                    self.album_view.scrollTo(index)
                    break

    def _update_album_filter_ui(self) -> None:
        if not hasattr(self, "album_filter_label"):
            return
        visible = self._album_filter_id is not None
        self.album_filter_label.setVisible(visible)
        self.clear_album_filter_button.setVisible(visible)
        if visible:
            self.album_filter_label.setText(f"Album: {self._album_filter_title}")

    def _track_has_artwork(self, track: Track) -> bool:
        if track.artwork_path and Path(track.artwork_path).is_file():
            return True
        return (self.service.artwork_dir / f"{track.album_id.upper()}.jpg").is_file()

    # ------------------------------------------------------------------
    # Selection and inline editor

    def selected_track_ids(self) -> list[str]:
        if hasattr(self, "tabs") and self.tabs.currentIndex() == 1 and hasattr(self, "album_view"):
            selection = self.album_view.selectionModel()
            if selection is None:
                return []
            ids: list[str] = []
            for index in selection.selectedIndexes():
                album = self.album_model.album_at(index.row())
                if album is not None:
                    ids.extend(self.db.track_ids_for_album(album.id, self._current_library_id))
            return list(dict.fromkeys(ids))
        selection = self.table.selectionModel()
        if selection is None:
            return []
        ids = []
        for index in selection.selectedRows():
            track = self.model.track_at(index.row())
            if track is not None:
                ids.append(track.id)
        return ids

    def _track_context_menu(self, position: QPoint) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        selection = self.table.selectionModel()
        if not selection.isSelected(index):
            self.table.clearSelection()
            self.table.selectRow(index.row())
        ids = self.selected_track_ids()
        if not ids:
            return
        track = self.db.get_track(ids[0])
        if track is None:
            return
        menu = QMenu(self)
        edit = menu.addAction("Edit Tags")
        menu.addSeparator()
        go_to_album = None
        if self.tabs.currentIndex() == 0 and self._album_filter_id is None:
            go_to_album = menu.addAction("Go to Album")
            menu.addSeparator()
        open_action = menu.addAction("Open")
        open_with_action = menu.addAction("Open with")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        menu.addSeparator()
        finder_action = menu.addAction("Show in Finder")
        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen == edit:
            self.edit_tags()
        elif go_to_album is not None and chosen == go_to_album:
            self.go_to_album(track)
        elif chosen == open_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(track.path))
        elif chosen == open_with_action:
            self.open_with(track)
        elif chosen == delete_action:
            self.delete_tracks()
        elif chosen == finder_action:
            self.show_in_finder(track)

    def go_to_album(self, track: Track) -> None:
        self.tabs.setCurrentIndex(1)
        self.refresh_albums()
        for row in range(self.album_model.rowCount()):
            album = self.album_model.album_at(row)
            if album is not None and album.id == track.album_id:
                index = self.album_model.index(row, 0)
                self.album_view.setCurrentIndex(index)
                self.album_view.selectionModel().select(
                    index,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect,
                )
                self.album_view.scrollTo(index)
                return

    def open_with(self, track: Track) -> None:
        script = 'POSIX path of (choose application with prompt "Open with")'
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return
        if result.returncode != 0:
            return
        application = result.stdout.strip()
        if application:
            QProcess.startDetached("open", ["-a", application, track.path])

    def show_in_finder(self, track: Track) -> None:
        QProcess.startDetached("open", ["-R", track.path])

    def _selection_changed(self, *_args: object) -> None:
        ids = self.selected_track_ids()
        if not ids:
            self.editor.clear()
            self._update_status()
            return
        tracks = [track for song_id in ids if (track := self.db.get_track(song_id))]
        tags_list = [tags for song_id in ids if (tags := self.db.load_tag_set(song_id))]
        if not tracks or len(tracks) != len(tags_list):
            self.editor.clear()
            self._update_status()
            return
        if len(tracks) == 1:
            self.editor.load_track(tracks[0], tags_list[0])
            pixmap, info = self._artwork_for_track(tracks[0])
        else:
            self.editor.load_multi(tracks, tags_list)
            pixmap, info = self._common_artwork(tracks)
        self.editor.set_artwork(pixmap, info)
        self._update_status()

    def _artwork_for_track(self, track: Track) -> tuple[QPixmap, str]:
        candidates: list[Path] = []
        if track.artwork_path:
            candidates.append(Path(track.artwork_path))
        candidates.append(self.service.artwork_dir / f"{track.album_id.upper()}.jpg")
        for candidate in candidates:
            if candidate.is_file():
                pixmap = QPixmap(str(candidate))
                if not pixmap.isNull():
                    info = f"{pixmap.width()}x{pixmap.height()} · {track.format}"
                    try:
                        metadata = read_metadata(track.path)
                        if metadata.artwork:
                            info = (
                                f"{metadata.artwork[0].width}x"
                                f"{metadata.artwork[0].height} · "
                                f"{metadata.artwork[0].mime}"
                            )
                    except Exception:
                        pass
                    return pixmap, info
        return QPixmap(), "No artwork"

    def _cover_path(self, track: Track) -> Path | None:
        candidates: list[Path] = []
        if track.artwork_path:
            candidates.append(Path(track.artwork_path))
        candidates.append(self.service.artwork_dir / f"{track.album_id.upper()}.jpg")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _common_artwork(self, tracks: list[Track]) -> tuple[QPixmap, str]:
        paths = [self._cover_path(track) for track in tracks]
        if not paths or any(path is None for path in paths):
            return QPixmap(), f"{len(tracks)} tracks selected · no common cover"
        if len({str(path) for path in paths}) != 1:
            return QPixmap(), f"{len(tracks)} tracks selected · different covers"
        path = paths[0]
        assert path is not None
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return QPixmap(), f"{len(tracks)} tracks selected"
        return pixmap, f"{pixmap.width()}x{pixmap.height()} · {len(tracks)} tracks"

    def _select_song(self, song_id: str) -> None:
        for row, track in enumerate(self.model.tracks):
            if track.id == song_id:
                self.table.selectRow(row)
                self.table.scrollTo(self.model.index(row, 0))
                return

    def save_inline_edits(self, edits: dict[str, object]) -> None:
        ids = self.selected_track_ids()
        if not ids:
            return
        changes = self.service.preview_tag_edits(ids, edits)
        if not any(change.changed_fields for change in changes):
            QMessageBox.information(self, "No changes", "The selected fields are unchanged.")
            return
        preview = TagPreviewDialog(changes, self)
        if preview.exec() != QDialog.DialogCode.Accepted:
            return
        song_id = ids[0]
        result = self.service.update_tags(ids, edits)
        self.refresh_libraries()
        self.refresh_tracks()
        if self.tabs.currentIndex() == 0:
            self._select_song(song_id)
        if result.errors:
            QMessageBox.warning(self, "Tag update warnings", "\n".join(result.errors[:10]))
        self.set_status_message(f"Updated {len(result.updated)} tracks")

    def edit_tags(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        editor = TagEditorDialog(self.service, ids, self)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        edits = editor.edits()
        changes = self.service.preview_tag_edits(ids, edits)
        if not any(change.changed_fields for change in changes):
            QMessageBox.information(self, "No changes", "The selected fields are unchanged.")
            return
        if TagPreviewDialog(changes, self).exec() != QDialog.DialogCode.Accepted:
            return
        first = ids[0]
        result = self.service.update_tags(ids, edits)
        self.refresh_libraries()
        self.refresh_tracks()
        self._select_song(first)
        if result.errors:
            QMessageBox.warning(self, "Tag update warnings", "\n".join(result.errors[:10]))

    def auto_number_tracks(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        options = AutoNumberDialog(len(ids), self)
        if options.exec() != QDialog.DialogCode.Accepted:
            return
        per_disc, start = options.values()
        changes = self.service.preview_auto_number(ids, per_disc=per_disc, start=start)
        if not changes or not any(change.changed_fields for change in changes):
            QMessageBox.information(
                self, "Auto-number", "The selected tracks are already numbered."
            )
            return
        if TagPreviewDialog(changes, self).exec() != QDialog.DialogCode.Accepted:
            return
        first = ids[0]
        result = self.service.auto_number_tracks(ids, per_disc=per_disc, start=start)
        self.refresh_libraries()
        self.refresh_tracks()
        self._select_song(first)
        if result.errors:
            QMessageBox.warning(self, "Auto-number warnings", "\n".join(result.errors[:10]))

    def _require_selection(self) -> list[str] | None:
        ids = self.selected_track_ids()
        if not ids:
            QMessageBox.information(self, "No selection", "Select one or more tracks first.")
            return None
        return ids

    def _require_library(self) -> Library | None:
        if self._current_library_id:
            return self.db.get_library(self._current_library_id)
        QMessageBox.information(self, "No library", "Open Library Manager and add a library first.")
        return None

    # ------------------------------------------------------------------
    # Import, organize, delete, undo

    def import_files(self) -> None:
        library = self._require_library()
        if library is None:
            return
        dialog = ImportDialog(self.service, library, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_libraries()
            self.set_status_message("Import complete")

    def organize(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        dialog = OrganizeDialog(self.service, ids, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_libraries()
            self.refresh_tracks()

    def delete_tracks(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        dialog = DeleteDialog(len(ids), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = self.service.delete_tracks(ids, delete_files=dialog.delete_files())
        self.refresh_libraries()
        self.refresh_tracks()
        if result.errors:
            QMessageBox.warning(self, "Delete warnings", "\n".join(result.errors[:10]))

    def undo(self) -> None:
        result = self.service.undo_last()
        if result is None:
            QMessageBox.information(self, "Undo", "There is no operation to undo.")
            return
        self.refresh_libraries()
        self.refresh_tracks()
        message = f"Undid {result.kind}: {result.undone} changes."
        if result.errors:
            message += "\n" + "\n".join(result.errors[:10])
            QMessageBox.warning(self, "Undo warnings", message)

    def redo(self) -> None:
        result = self.service.redo_last()
        if result is None:
            QMessageBox.information(self, "Redo", "There is no operation to redo.")
            return
        self.refresh_libraries()
        self.refresh_tracks()
        message = f"Redid {result.kind}: {result.undone} changes."
        if result.errors:
            message += "\n" + "\n".join(result.errors[:10])
            QMessageBox.warning(self, "Redo warnings", message)

    # ------------------------------------------------------------------
    # Artwork and duplicates

    def find_duplicates(self) -> None:
        library = self._require_library()
        if library is None:
            return
        self.set_status_message("Hashing tracks…")
        QApplication.processEvents()
        tracks = self.db.list_tracks(library_id=library.id)
        for index, track in enumerate(tracks, start=1):
            if self.db.get_content_hash(track.id):
                continue
            try:
                self.db.update_content_hash(track.id, content_hash(track.path))
            except OSError:
                continue
            if index % 25 == 0:
                self.set_status_message(f"Hashing tracks… {index}/{len(tracks)}")
                QApplication.processEvents()
        exact = self.service.exact_duplicates()
        probable = self.db.probable_duplicate_groups()
        if not exact and not probable:
            QMessageBox.information(self, "Duplicates", "No duplicate groups were found.")
            return
        dialog = DuplicateDialog(exact, probable, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_ids:
            result = self.service.delete_tracks(dialog.selected_ids)
            self.refresh_libraries()
            self.refresh_tracks()
            if result.errors:
                QMessageBox.warning(self, "Duplicate removal", "\n".join(result.errors[:10]))

    def set_cover(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Choose Cover Image", str(Path.home()), "Images (*.jpg *.jpeg *.png)"
        )
        if not filename:
            return
        try:
            data = Path(filename).read_bytes()
        except OSError as exc:
            QMessageBox.critical(self, "Cover", str(exc))
            return
        first = ids[0]
        errors = self.service.set_artwork(ids, data)
        self.refresh_tracks()
        self._select_song(first)
        if errors:
            QMessageBox.warning(self, "Cover warnings", "\n".join(errors[:10]))

    def remove_cover(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove Artwork",
            f"Remove embedded artwork from {len(ids)} selected track(s)?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        first = ids[0]
        errors = self.service.remove_artwork(ids)
        self.refresh_tracks()
        self._select_song(first)
        if errors:
            QMessageBox.warning(self, "Artwork warnings", "\n".join(errors[:10]))

    def extract_cover(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        if len(ids) != 1:
            QMessageBox.information(
                self, "Extract Cover", "Select exactly one track to extract its cover."
            )
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Extract Cover", str(Path.home() / "cover.jpg"), "Images (*.jpg *.png)"
        )
        if not filename:
            return
        try:
            path = self.service.extract_artwork(ids[0], filename)
        except Exception as exc:
            QMessageBox.critical(self, "Extract Cover", str(exc))
            return
        self.set_status_message(f"Cover written to {path}")

    def reveal_selected(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        track = self.db.get_track(ids[0])
        if track is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(track.path).parent)))

    # ------------------------------------------------------------------
    # Settings and column configuration

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self.db,
            self.service.default_template,
            self.service.cover_size,
            self.service.cover_quality,
            [(key, label) for label, key in COLUMNS],
            self.visible_columns(),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        template, cover_size, quality, visible = dialog.values()
        self.db.set_setting("default_template", template)
        self.db.set_setting("cover_size", str(cover_size))
        self.db.set_setting("cover_quality", str(quality))
        self.service.default_template = template
        self.service.cover_size = cover_size
        self.service.cover_quality = quality
        self.set_visible_columns(visible)
        self.set_status_message("Settings saved")

    def default_column_config(self) -> dict[str, object]:
        keys = [key for _, key in COLUMNS]
        visible = [key for key in keys if key not in {"album_artist", "path"}]
        return {
            "visible": visible,
            "order": keys,
            "widths": {key: DEFAULT_WIDTHS.get(key, 120) for key in keys},
        }

    def _load_column_config(self) -> None:
        raw = self.db.get_setting("track_columns", "")
        config = self.default_column_config()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    config.update(parsed)
            except json.JSONDecodeError:
                pass
        self._column_config = config
        self._apply_column_config()
        self._columns_ready = True

    def _column_index(self, key: str) -> int:
        for index, (_, column_key) in enumerate(COLUMNS):
            if column_key == key:
                return index
        return -1

    def _apply_column_config(self) -> None:
        if not hasattr(self, "table"):
            return
        self._loading_columns = True
        keys = [key for _, key in COLUMNS]
        visible_raw = self._column_config.get("visible", keys)
        visible = set(visible_raw) if isinstance(visible_raw, (list, tuple, set)) else set(keys)
        for index, key in enumerate(keys):
            self.table.setColumnHidden(index, key not in visible)
        order_raw = self._column_config.get("order", keys)
        order = (
            [str(key) for key in order_raw if isinstance(key, str) and key in keys]
            if isinstance(order_raw, (list, tuple))
            else list(keys)
        )
        order.extend(key for key in keys if key not in order)
        header = self.table.horizontalHeader()
        for target, key in enumerate(order):
            source = header.visualIndex(self._column_index(key))
            if source != target:
                header.moveSection(source, target)
        widths = self._column_config.get("widths", {})
        if isinstance(widths, dict):
            for key, width in widths.items():
                index = self._column_index(key)
                if index >= 0:
                    header.resizeSection(index, int(width))
        self._loading_columns = False

    def _column_layout_changed(self, *_args: object) -> None:
        if self._columns_ready and not self._loading_columns:
            self._save_column_config()

    def _save_column_config(self) -> None:
        if not self._columns_ready or not hasattr(self, "table"):
            return
        header = self.table.horizontalHeader()
        keys = [key for _, key in COLUMNS]
        visible = [key for index, key in enumerate(keys) if not self.table.isColumnHidden(index)]
        order = sorted(keys, key=lambda key: header.visualIndex(self._column_index(key)))
        previous_widths = self._column_config.get("widths", {})
        previous_widths = previous_widths if isinstance(previous_widths, dict) else {}
        widths: dict[str, int] = {}
        for key in keys:
            width = header.sectionSize(self._column_index(key))
            if width <= 0:
                width = int(previous_widths.get(key, DEFAULT_WIDTHS.get(key, 120)))
            widths[key] = width
        self._column_config = {"visible": visible, "order": order, "widths": widths}
        self.db.set_setting("track_columns", json.dumps(self._column_config))

    def visible_columns(self) -> list[str]:
        if not hasattr(self, "table"):
            return [key for _, key in COLUMNS]
        return [
            key for index, (_, key) in enumerate(COLUMNS) if not self.table.isColumnHidden(index)
        ]

    def set_visible_columns(self, visible: list[str]) -> None:
        if not visible:
            return
        self._column_config["visible"] = visible
        self._apply_column_config()
        self._save_column_config()

    def _column_context_menu(self, position: QPoint) -> None:
        header = self.table.horizontalHeader()
        menu = QMenu(self)
        for index, (label, key) in enumerate(COLUMNS):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(index))
            action.toggled.connect(
                lambda checked, column_key=key: self._set_column_visible(column_key, checked)
            )
        menu.addSeparator()
        fit = menu.addAction("Auto-fit All Columns")
        chosen = menu.exec(header.mapToGlobal(position))
        if chosen == fit:
            self._auto_fit_all_columns()

    def _set_column_visible(self, key: str, visible: bool) -> None:
        if not visible and len(self.visible_columns()) <= 1:
            QMessageBox.information(self, "Columns", "At least one column must remain visible.")
            return
        index = self._column_index(key)
        if index >= 0:
            self.table.setColumnHidden(index, not visible)
            self._save_column_config()

    def _auto_fit_column(self, section: int) -> None:
        self.table.resizeColumnToContents(section)
        header = self.table.horizontalHeader()
        if header.sectionSize(section) < 60:
            header.resizeSection(section, 60)
        self._save_column_config()

    def _auto_fit_all_columns(self) -> None:
        header = self.table.horizontalHeader()
        for index in range(self.model.columnCount()):
            if self.table.isColumnHidden(index):
                continue
            self.table.resizeColumnToContents(index)
            if header.sectionSize(index) < 60:
                header.resizeSection(index, 60)
        self._save_column_config()

    # ------------------------------------------------------------------
    # Misc

    def focus_search(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def show_help(self) -> None:
        QDesktopServices.openUrl(QUrl("https://github.com/rGnng/trackstash#readme"))

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "About TrackStash",
            f"TrackStash {__version__}\n\n"
            "A local-first managed music library.\n"
            "Licensed under GPL-3.0-only.",
        )
