"""TrackStash main window: left media editor, right tracks/albums views."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QProcess,
    QSize,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
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
    QStyle,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from trackstash.core.db import Database, Library, Track
from trackstash.core.library import LibraryService, content_hash
from trackstash.core.metadata import read_artwork
from trackstash.core.template import DEFAULT_TEMPLATE, LEGACY_DEFAULT_TEMPLATE
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

ALBUM_MIN_COVER = 158
ALBUM_COLUMN_GAP = 22
ALBUM_ROW_GAP = 26
ALBUM_TEXT_HEIGHT = 34


class AlbumGridView(QListView):
    """Album icon grid that keeps gaps fixed while covers fill the viewport."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.resize_callback: Callable[[int], None] | None = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(60)
        self._resize_timer.timeout.connect(self._notify_resize)

    def _notify_resize(self) -> None:
        if self.resize_callback is not None:
            self.resize_callback(self.viewport().width())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()


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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.service = LibraryService(db)
        template = db.get_setting("default_template", DEFAULT_TEMPLATE)
        if template == LEGACY_DEFAULT_TEMPLATE:
            template = DEFAULT_TEMPLATE
            db.set_setting("default_template", template)
        self.service.default_template = template
        self.service.strong_order = db.get_setting("strong_order", "1") != "0"
        self.service.preserve_mtime = db.get_setting("preserve_mtime", "1") != "0"
        try:
            self.service.artwork_max_size = int(db.get_setting("artwork_max_size", "1000") or 1000)
            self.service.artwork_quality = int(db.get_setting("artwork_quality", "90") or 90)
        except ValueError:
            self.service.artwork_max_size = 1000
            self.service.artwork_quality = 90
        self.service.artwork_crop_square = db.get_setting("artwork_crop_square", "1") != "0"
        self._album_sort = db.get_setting("album_sort_field", "date_added")
        self._album_sort_desc = db.get_setting("album_sort_order", "desc") != "asc"
        self._status_bar_visible = db.get_setting("status_bar_visible", "1") != "0"
        try:
            self._editor_width = int(db.get_setting("editor_width", "280") or 280)
        except ValueError:
            self._editor_width = 280
        self._editor_width = max(280, min(400, self._editor_width))
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(100)
        self._selection_timer.timeout.connect(self._apply_selection)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.refresh_tracks)
        self._albums_dirty = True
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
        self.setMinimumSize(1280, 700)
        saved_size = db.get_setting("window_size", "")
        try:
            width, height = (int(part) for part in saved_size.lower().split("x", 1))
        except ValueError:
            width, height = 1440, 900
        self.resize(width, height)

        self._create_actions()
        self.menuBar().setVisible(False)
        self._create_central_widget()
        self._create_status_bar()
        self.statusBar().setVisible(self._status_bar_visible)
        self.refresh_libraries()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.db.set_setting("window_size", f"{self.width()}x{self.height()}")
        self.db.set_setting("editor_width", str(self.editor.width()))
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Actions

    def _create_actions(self) -> None:
        self.import_action = QAction("Import…", self)
        self.import_action.setShortcut(QKeySequence("Ctrl+I"))
        self.import_action.triggered.connect(self.import_files)

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
        refresh_icon = QIcon.fromTheme("view-refresh")
        if refresh_icon.isNull():
            refresh_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        self.refresh_action.setIcon(refresh_icon)

        undo_icon = QIcon.fromTheme("edit-undo")
        if undo_icon.isNull():
            undo_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack)
        self.undo_action.setIcon(undo_icon)
        redo_icon = QIcon.fromTheme("edit-redo")
        if redo_icon.isNull():
            redo_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward)
        self.redo_action.setIcon(redo_icon)

        for action in (
            self.import_action,
            self.library_manager_action,
            self.organize_action,
            self.delete_action,
            self.duplicates_action,
            self.set_cover_action,
            self.remove_cover_action,
            self.extract_cover_action,
            self.edit_action,
            self.auto_number_action,
            self.undo_action,
            self.redo_action,
            self.settings_action,
            self.tracks_view_action,
            self.albums_view_action,
            self.focus_search_action,
            self.refresh_action,
        ):
            self.addAction(action)

    # ------------------------------------------------------------------
    # Layout

    def _create_central_widget(self) -> None:
        outer = QWidget(self)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(4, 4, 4, 4)
        outer_layout.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal, outer)
        self.splitter = splitter
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(3)
        splitter.setStyleSheet(
            "QSplitter::handle { background: transparent; image: none; }"
            "QSplitter::handle:hover { background-color: #48D1B5; }"
        )
        self.editor = TrackInfoEditor(splitter)
        self.editor.setMinimumWidth(280)
        self.editor.setMaximumWidth(400)
        self.editor.save_requested.connect(self.save_inline_edits)
        self.editor.cover_requested.connect(self.stage_cover)
        self.editor.remove_cover_requested.connect(self.remove_cover)
        self.editor.extract_cover_requested.connect(self.extract_cover)
        self.editor.reveal_requested.connect(self.reveal_selected)
        splitter.addWidget(self.editor)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(4)

        library_row = QHBoxLayout()
        self.view_label = QLabel("View", right)
        library_row.addWidget(self.view_label)
        view_switch = QWidget(right)
        view_switch_layout = QHBoxLayout(view_switch)
        view_switch_layout.setContentsMargins(0, 0, 0, 0)
        view_switch_layout.setSpacing(0)
        self.albums_view_button = QPushButton("Albums", view_switch)
        self.tracks_view_button = QPushButton("Tracks", view_switch)
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
            button.setFixedSize(70, 28)
            button.clicked.connect(
                lambda _checked=False, page=index: self.tabs.setCurrentIndex(page)
            )
            self._view_button_group.addButton(button)
            view_switch_layout.addWidget(button)
        self.albums_view_button.setChecked(True)
        self.albums_view_button.setToolTip("Albums view (Ctrl+2)")
        self.tracks_view_button.setToolTip("Tracks view (Ctrl+1)")
        library_row.addWidget(view_switch)
        library_row.addSpacing(10)
        self.search_edit = QLineEdit(right)
        self.search_edit.setPlaceholderText("Search title, artist, album, genre, path…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedSize(180, 28)
        self.search_edit.textChanged.connect(self._search_changed)
        library_row.addWidget(self.search_edit)

        self.format_filter = QComboBox(right)
        self.format_filter.addItem("All formats", "")
        for extension in ("FLAC", "MP3", "M4A", "OGG", "OPUS", "APE", "WV", "WAV", "AIFF"):
            self.format_filter.addItem(extension, extension)
        self.format_filter.setFixedSize(112, 28)
        self.format_filter.currentIndexChanged.connect(self._filters_changed)
        library_row.addWidget(self.format_filter)
        self.missing_artwork_button = QToolButton(right)
        self.missing_artwork_button.setText("No artwork")
        self.missing_artwork_button.setToolTip("Show only tracks that have no artwork")
        self.missing_artwork_button.setCheckable(True)
        self.missing_artwork_button.setFixedHeight(28)
        self.missing_artwork_button.toggled.connect(self._filters_changed)
        library_row.addWidget(self.missing_artwork_button)
        library_row.addStretch(1)

        self.undo_button = QToolButton(right)
        self.undo_button.setDefaultAction(self.undo_action)
        self.undo_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.undo_button.setToolTip("Undo (Ctrl+Z)")
        self.undo_button.setFixedHeight(28)
        library_row.addWidget(self.undo_button)
        self.redo_button = QToolButton(right)
        self.redo_button.setDefaultAction(self.redo_action)
        self.redo_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.redo_button.setToolTip("Redo (Ctrl+Shift+Z)")
        self.redo_button.setFixedHeight(28)
        library_row.addWidget(self.redo_button)

        self.refresh_button = QToolButton(right)
        self.refresh_button.setDefaultAction(self.refresh_action)
        self.refresh_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.refresh_button.setToolTip("Refresh (Ctrl+R)")
        self.refresh_button.setFixedSize(30, 28)
        library_row.addWidget(self.refresh_button)
        self.import_button = QPushButton("Import…", right)
        self.import_button.clicked.connect(self.import_action.trigger)
        self.import_button.setFixedSize(88, 28)
        library_row.addWidget(self.import_button)
        self.settings_button = QToolButton(right)
        settings_icon = QIcon.fromTheme("preferences-system")
        if settings_icon.isNull():
            self.settings_button.setText("⚙")
        else:
            self.settings_button.setIcon(settings_icon)
        self.settings_button.setToolTip("Settings…")
        self.settings_button.setIconSize(QSize(16, 16))
        self.settings_button.setFixedSize(30, 28)
        self.settings_button.clicked.connect(self.settings_action.trigger)
        library_row.addWidget(self.settings_button)
        for tool_button in (self.undo_button, self.redo_button, self.refresh_button):
            tool_button.setIconSize(QSize(16, 16))
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
        # The icon delegate adds half a cell gap around each cover; 11 px here
        # yields the reference 22 px visual inset used by the Tracks grid.
        albums_layout.setContentsMargins(11, 4, 11, 11)
        self.album_model = AlbumGridModel()
        self.album_view = AlbumGridView(albums_tab)
        self.album_view.setModel(self.album_model)
        self.album_view.setFrameShape(QFrame.Shape.NoFrame)
        self.album_view.setLineWidth(0)
        self.album_view.setViewMode(QListView.ViewMode.IconMode)
        self.album_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.album_view.setMovement(QListView.Movement.Static)
        self.album_view.setUniformItemSizes(True)
        self.album_view.setWordWrap(True)
        self.album_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.album_view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.album_view.setIconSize(QSize(ALBUM_MIN_COVER, ALBUM_MIN_COVER))
        self.album_view.setSpacing(0)
        self.album_view.resize_callback = self._update_album_grid
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

        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([self._editor_width, 1100])
        outer_layout.addWidget(splitter, 1)

        self.setCentralWidget(outer)

        self._load_column_config()
        self.tabs.setCurrentIndex(1)

    def _filters_changed(self, *_args: object) -> None:
        self.refresh_tracks()

    def _create_status_bar(self) -> None:
        self.status_summary = QLabel("", self)
        self.status_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.statusBar().addWidget(self.status_summary)
        self.status_selection = QLabel("", self)
        self.status_selection.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.statusBar().addWidget(self.status_selection)
        self._library_label = ""
        self._total_tracks = 0
        self._update_status()

    def _selection_item_count(self) -> int:
        if self.tabs.currentIndex() == 1:
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
        selected = self._selection_item_count()
        self.status_summary.setText(base)
        self.status_selection.setText(f"{selected} selected" if selected else "")

    # ------------------------------------------------------------------
    # Library selection

    def refresh_libraries(self) -> None:
        previous = self._current_library_id
        self._libraries = self.db.list_libraries()
        if not self._libraries:
            self._current_library_id = None
            self._album_filter_id = None
            self._album_filter_title = ""
            self._album_return_id = None
            self.refresh_tracks()
            return
        current = next(
            (library for library in self._libraries if library.id == previous and library.enabled),
            None,
        )
        if current is None:
            current = next(
                (library for library in self._libraries if library.enabled),
                self._libraries[0],
            )
        self._current_library_id = current.id
        if previous != self._current_library_id:
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

    def _search_changed(self, text: str) -> None:
        if not text.strip():
            self._search_timer.stop()
            self.refresh_tracks()
            return
        self._search_timer.start()

    def refresh_tracks(self) -> None:
        query = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        if not self._current_library_id:
            self.model.set_tracks([])
            self.editor.clear()
            self._update_album_filter_ui()
            self._library_label = ""
            self._total_tracks = 0
            self._update_status()
            if hasattr(self, "album_model"):
                self.album_model.set_albums([])
            self._albums_dirty = False
            return
        tracks = self.db.list_tracks(
            library_id=self._current_library_id,
            album_id=self._album_filter_id,
            query=query,
        )
        format_value = str(self.format_filter.currentData() or "")
        if format_value:
            tracks = [track for track in tracks if track.format.upper() == format_value]
        if self.missing_artwork_button.isChecked():
            tracks = [track for track in tracks if not self._track_has_artwork(track)]
        self.model.set_tracks(tracks)
        library = self.db.get_library(self._current_library_id)
        self._library_label = library.name if library else "Library"
        self._total_tracks = len(tracks)
        self._update_album_filter_ui()
        self._update_status()
        if self.tabs.currentIndex() == 1:
            self.refresh_albums()
        else:
            self._albums_dirty = True
        if not self.selected_track_ids():
            self.editor.clear()

    def refresh_albums(self) -> None:
        if not hasattr(self, "album_model"):
            return
        if not self._current_library_id:
            self.album_model.set_albums([])
            return
        query = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        albums = self.db.list_albums(
            self._current_library_id,
            query=query,
            sort=self._album_sort,
            descending=self._album_sort_desc,
        )
        self.album_model.set_albums(albums)
        self._albums_dirty = False

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

    def _update_album_grid(self, width: int | None = None) -> None:
        if not hasattr(self, "album_view"):
            return
        available = width if width is not None else self.album_view.viewport().width()
        # QListView reserves a small internal margin around its cell grid.
        available = max(1, available - 16)
        columns = max(1, available // (ALBUM_MIN_COVER + ALBUM_COLUMN_GAP))
        cover = max(1, (available - columns * ALBUM_COLUMN_GAP) // columns)
        self.album_model.set_cover_size(cover)
        self.album_view.setIconSize(QSize(cover, cover))
        self.album_view.setGridSize(
            QSize(
                cover + ALBUM_COLUMN_GAP,
                cover + ALBUM_TEXT_HEIGHT + ALBUM_ROW_GAP,
            )
        )

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
        return track.has_artwork

    # ------------------------------------------------------------------
    # Selection and inline editor

    def selected_track_ids(self) -> list[str]:
        if hasattr(self, "tabs") and self.tabs.currentIndex() == 1 and hasattr(self, "album_view"):
            selection = self.album_view.selectionModel()
            if selection is None:
                return []
            album_ids: list[str] = []
            for index in selection.selectedIndexes():
                album = self.album_model.album_at(index.row())
                if album is not None and album.id not in album_ids:
                    album_ids.append(album.id)
            return self.db.track_ids_for_albums(album_ids, self._current_library_id)
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
        self._update_status()
        if self.tabs.currentIndex() == 1 and self._selection_item_count() > 0:
            self._selection_timer.start()
            return
        self._selection_timer.stop()
        self._apply_selection()

    def _apply_selection(self) -> None:
        ids = self.selected_track_ids()
        if not ids:
            self.editor.clear()
            self._update_status()
            return
        tracks = self.db.get_tracks_by_ids(ids)
        tags_by_id = self.db.load_tag_sets(ids)
        tags_list = [tags_by_id[song_id] for song_id in ids if song_id in tags_by_id]
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

    def _front_artwork(self, track: Track) -> tuple[bytes, str, int] | None:
        if not track.has_artwork:
            return None
        try:
            artworks = read_artwork(track.path)
        except Exception:
            return None
        if not artworks:
            return None
        artwork = artworks[0]
        return (
            artwork.data,
            f"{artwork.width}x{artwork.height} · {artwork.mime}",
            len(artworks),
        )

    def _artwork_for_track(self, track: Track) -> tuple[QPixmap, str]:
        artwork = self._front_artwork(track)
        if artwork is None:
            return QPixmap(), "No artwork"
        data, info, count = artwork
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            if count > 1:
                info = f"{info} · {count} artworks"
            return pixmap, info
        return QPixmap(), "No artwork"

    def _common_artwork(self, tracks: list[Track]) -> tuple[QPixmap, str]:
        if not tracks or any(not track.has_artwork for track in tracks):
            return QPixmap(), f"{len(tracks)} tracks selected · no common cover"
        checksums = {track.artwork_checksum for track in tracks}
        if "" in checksums:
            values = [self._front_artwork(track) for track in tracks]
            if any(value is None for value in values):
                return QPixmap(), f"{len(tracks)} tracks selected · no common cover"
            if len({value[0] for value in values if value is not None}) != 1:
                return QPixmap(), f"{len(tracks)} tracks selected · different covers"
            artwork = values[0]
        else:
            if len(checksums) != 1:
                return QPixmap(), f"{len(tracks)} tracks selected · different covers"
            artwork = self._front_artwork(tracks[0])
        if artwork is None:
            return QPixmap(), f"{len(tracks)} tracks selected · no common cover"
        pixmap = QPixmap()
        if not pixmap.loadFromData(artwork[0]):
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
        art_data = self.editor.pending_artwork_data()
        art_remove = self.editor.pending_artwork_removal()
        changes = self.service.preview_tag_edits(ids, edits)
        tag_changes = any(change.changed_fields for change in changes)
        if not tag_changes and art_data is None and not art_remove:
            QMessageBox.information(self, "No changes", "The selected fields are unchanged.")
            return
        if tag_changes:
            preview = TagPreviewDialog(changes, self)
            if preview.exec() != QDialog.DialogCode.Accepted:
                return
        art_errors: list[str] = []
        if art_data is not None:
            art_errors = self.service.set_artwork(ids, art_data)
        elif art_remove:
            art_errors = self.service.remove_artwork(ids)
        result = self.service.update_tags(ids, edits) if tag_changes else None
        song_id = result.updated[0].id if result is not None and result.updated else ids[0]
        self.refresh_libraries()
        self.refresh_tracks()
        if self.tabs.currentIndex() == 0:
            self._select_song(song_id)
        else:
            self._apply_selection()
        if result is not None and result.errors:
            QMessageBox.warning(self, "Tag update warnings", "\n".join(result.errors[:10]))
        if art_errors:
            QMessageBox.warning(self, "Artwork warnings", "\n".join(art_errors[:10]))

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
        result = self.service.update_tags(ids, edits)
        first = result.updated[0].id if result.updated else ids[0]
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
        result = self.service.auto_number_tracks(ids, per_disc=per_disc, start=start)
        first = result.updated[0].id if result.updated else ids[0]
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
        QMessageBox.information(
            self,
            "No library",
            "Open Settings → Library and add a library first.",
        )
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

    def _pick_cover_data(self) -> bytes | None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Choose Cover Image", str(Path.home()), "Images (*.jpg *.jpeg *.png)"
        )
        if not filename:
            return None
        try:
            return Path(filename).read_bytes()
        except OSError as exc:
            QMessageBox.critical(self, "Cover", str(exc))
            return None

    def stage_cover(self) -> None:
        data = self._pick_cover_data()
        if data is not None:
            self.editor.set_pending_artwork(data)

    def set_cover(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        data = self._pick_cover_data()
        if data is None:
            return
        first = ids[0]
        errors = self.service.set_artwork(ids, data)
        self.refresh_tracks()
        self._select_song(first)
        if errors:
            QMessageBox.warning(self, "Artwork warnings", "\n".join(errors[:10]))

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
            self.service.extract_artwork(ids[0], filename)
        except Exception as exc:
            QMessageBox.critical(self, "Extract Cover", str(exc))
            return

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
            [(key, label) for label, key in COLUMNS],
            self.visible_columns(),
            album_sort=self._album_sort,
            album_order="desc" if self._album_sort_desc else "asc",
            status_bar_visible=self._status_bar_visible,
            strong_order=self.service.strong_order,
            preserve_mtime=self.service.preserve_mtime,
            artwork_max_size=self.service.artwork_max_size,
            artwork_quality=self.service.artwork_quality,
            artwork_crop_square=self.service.artwork_crop_square,
            selection_available=bool(self.selected_track_ids()),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        (
            template,
            visible,
            album_sort,
            album_order,
            status_bar_visible,
            strong_order,
            preserve_mtime,
            artwork_max_size,
            artwork_quality,
            artwork_crop_square,
        ) = dialog.values()
        self.db.set_setting("default_template", template)
        self.db.set_setting("album_sort_field", album_sort)
        self.db.set_setting("album_sort_order", album_order)
        self.db.set_setting("status_bar_visible", "1" if status_bar_visible else "0")
        self.db.set_setting("strong_order", "1" if strong_order else "0")
        self.db.set_setting("preserve_mtime", "1" if preserve_mtime else "0")
        self.db.set_setting("artwork_max_size", str(artwork_max_size))
        self.db.set_setting("artwork_quality", str(artwork_quality))
        self.db.set_setting("artwork_crop_square", "1" if artwork_crop_square else "0")
        self.service.default_template = template
        self.service.strong_order = strong_order
        self.service.preserve_mtime = preserve_mtime
        self.service.artwork_max_size = artwork_max_size
        self.service.artwork_quality = artwork_quality
        self.service.artwork_crop_square = artwork_crop_square
        self._album_sort = album_sort
        self._album_sort_desc = album_order != "asc"
        self._status_bar_visible = status_bar_visible
        self.statusBar().setVisible(status_bar_visible)
        self.set_visible_columns(visible)
        self.refresh_albums()
        self._update_status()
        actions = {
            "manage_libraries": self.open_library_manager,
            "find_duplicates": self.find_duplicates,
            "organize": self.organize,
            "delete": self.delete_tracks,
            "set_cover": self.set_cover,
            "remove_cover": self.remove_cover,
            "extract_cover": self.extract_cover,
        }
        requested = dialog.requested_action
        if requested in actions:
            actions[requested]()

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
