"""TrackStash main window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, QSize, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from trackstash import __version__
from trackstash.core.db import Database, Library, Track
from trackstash.core.library import LibraryService, content_hash
from trackstash.core.template import DEFAULT_TEMPLATE
from trackstash.ui.dialogs import (
    DeleteDialog,
    DuplicateDialog,
    ImportDialog,
    MissingFilesDialog,
    OrganizeDialog,
    SettingsDialog,
    TagEditorDialog,
    TagPreviewDialog,
)
from trackstash.ui.models import AlbumGridModel, TrackTableModel


class MainWindow(QMainWindow):
    """Library browser and entry point for all M1-M6 workflows."""

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
        self._album_filter_title: str = ""
        self._libraries: list[Library] = []

        self.setWindowTitle("TrackStash")
        self.resize(1400, 900)
        self.setMinimumSize(1000, 650)

        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_central_widget()
        self._create_status_bar()

        self.refresh_libraries()
        self.refresh_tracks()

    # ------------------------------------------------------------------
    # Construction

    def _create_actions(self) -> None:
        self.add_library_action = QAction("Add Library…", self)
        self.add_library_action.setShortcut(QKeySequence.StandardKey.Open)
        self.add_library_action.triggered.connect(self.add_library)

        self.import_action = QAction("Import…", self)
        self.import_action.setShortcut(QKeySequence("Ctrl+I"))
        self.import_action.triggered.connect(self.import_files)

        self.scan_quick_action = QAction("Quick Scan", self)
        self.scan_quick_action.triggered.connect(lambda: self.scan("quick"))
        self.scan_full_action = QAction("Full Scan", self)
        self.scan_full_action.triggered.connect(lambda: self.scan("full"))

        self.edit_action = QAction("Edit Tags…", self)
        self.edit_action.setShortcut(QKeySequence("Ctrl+E"))
        self.edit_action.triggered.connect(self.edit_tags)

        self.organize_action = QAction("Organize…", self)
        self.organize_action.triggered.connect(self.organize)

        self.delete_action = QAction("Delete…", self)
        self.delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.delete_action.triggered.connect(self.delete_tracks)

        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)

        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        self.redo_action.triggered.connect(self.redo)

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

        self.settings_action = QAction("Settings…", self)
        self.settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_action.triggered.connect(self.open_settings)

        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.refresh_action.triggered.connect(self.refresh_tracks)

        self.quit_action = QAction("Quit", self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)

        self.about_action = QAction("About TrackStash", self)
        self.about_action.triggered.connect(self.show_about)
        self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
        self.settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.quit_action.setMenuRole(QAction.MenuRole.QuitRole)

    def _create_menus(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.setNativeMenuBar(True)
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.add_library_action)
        file_menu.addAction(self.import_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        library_menu = self.menuBar().addMenu("&Library")
        library_menu.addAction(self.scan_quick_action)
        library_menu.addAction(self.scan_full_action)
        library_menu.addSeparator()
        library_menu.addAction(self.organize_action)
        library_menu.addAction(self.delete_action)
        library_menu.addSeparator()
        library_menu.addAction(self.duplicates_action)
        library_menu.addAction(self.set_cover_action)
        library_menu.addAction(self.remove_cover_action)
        library_menu.addAction(self.extract_cover_action)
        library_menu.addSeparator()
        library_menu.addAction(self.reveal_action)

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self.edit_action)
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.settings_action)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self.about_action)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        toolbar.addAction(self.add_library_action)
        toolbar.addAction(self.import_action)
        toolbar.addAction(self.scan_quick_action)
        toolbar.addAction(self.scan_full_action)
        toolbar.addAction(self.edit_action)
        toolbar.addAction(self.organize_action)
        toolbar.addAction(self.delete_action)
        toolbar.addAction(self.duplicates_action)
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        self.addToolBar(toolbar)

    def _create_central_widget(self) -> None:
        outer = QWidget(self)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(8, 8, 8, 8)

        library_row = QHBoxLayout()
        library_row.addWidget(QLabel("Library", outer))
        self.library_combo = QComboBox(outer)
        self.library_combo.setMinimumWidth(280)
        self.library_combo.currentIndexChanged.connect(self._library_changed)
        library_row.addWidget(self.library_combo)
        manage_button = QPushButton("Manage…", outer)
        manage_button.clicked.connect(self.open_library_menu)
        library_row.addWidget(manage_button)
        add_button = QPushButton("Add Library…", outer)
        add_button.clicked.connect(self.add_library)
        library_row.addWidget(add_button)
        library_row.addStretch(1)
        outer_layout.addLayout(library_row)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit(outer)
        self.search_edit.setPlaceholderText("Search title, artist, album, genre, path…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.refresh_tracks)
        self.format_filter = QComboBox(outer)
        self.format_filter.addItem("All formats", "")
        for extension in ("FLAC", "MP3", "M4A", "OGG", "OPUS", "APE", "WV", "WAV", "AIFF"):
            self.format_filter.addItem(extension, extension)
        self.format_filter.currentIndexChanged.connect(self.refresh_tracks)
        self.missing_artwork = QCheckBox("Missing artwork", outer)
        self.missing_artwork.stateChanged.connect(self.refresh_tracks)
        self.missing_artwork.setToolTip("Show only tracks without a cached cover")
        refresh_button = QPushButton("Refresh", outer)
        refresh_button.clicked.connect(self.refresh_tracks)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.format_filter)
        search_row.addWidget(self.missing_artwork)
        search_row.addWidget(refresh_button)
        outer_layout.addLayout(search_row)

        splitter = QSplitter(Qt.Orientation.Horizontal, outer)
        center = QWidget(splitter)
        center_layout = QVBoxLayout(center)
        self.tabs = QTabWidget(center)
        self.tabs.currentChanged.connect(self._tab_changed)

        tracks_tab = QWidget(self.tabs)
        tracks_layout = QVBoxLayout(tracks_tab)
        tracks_layout.setContentsMargins(0, 0, 0, 0)
        filter_row = QHBoxLayout()
        self.album_filter_label = QLabel("", tracks_tab)
        self.album_filter_label.setVisible(False)
        clear_filter = QPushButton("Show all albums", tracks_tab)
        clear_filter.setVisible(False)
        self.clear_album_filter_button = clear_filter
        clear_filter.clicked.connect(self.clear_album_filter)
        filter_row.addWidget(self.album_filter_label)
        filter_row.addWidget(clear_filter)
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
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.doubleClicked.connect(self.edit_tags)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        tracks_layout.addWidget(self.table, 1)
        self.tabs.addTab(tracks_tab, "Tracks")

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
        self.album_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.album_view.doubleClicked.connect(self._album_activated)
        albums_layout.addWidget(self.album_view, 1)
        self.tabs.addTab(albums_tab, "Albums")

        center_layout.addWidget(self.tabs, 1)
        splitter.addWidget(center)

        detail = QWidget(splitter)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(8, 8, 8, 8)
        self.artwork_label = QLabel(detail)
        self.artwork_label.setFixedSize(240, 240)
        self.artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.artwork_label.setText("No artwork")
        detail_layout.addWidget(self.artwork_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.detail_title = QLabel("No track selected", detail)
        self.detail_title.setWordWrap(True)
        self.detail_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        detail_layout.addWidget(self.detail_title)
        self.detail_subtitle = QLabel("", detail)
        self.detail_subtitle.setWordWrap(True)
        detail_layout.addWidget(self.detail_subtitle)

        detail_scroll = QScrollArea(detail)
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_body = QWidget(detail_scroll)
        self.detail_form = QFormLayout(detail_body)
        self.detail_values: dict[str, QLabel] = {}
        for key, label in (
            ("path", "File"),
            ("album_artist", "Album artist"),
            ("genre", "Genre"),
            ("year", "Year"),
            ("track", "Track"),
            ("format", "Format"),
            ("bitrate", "Bitrate"),
            ("sample_rate", "Sample rate"),
            ("duration", "Duration"),
            ("tags", "Extended tags"),
        ):
            value = QLabel("", detail_body)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.detail_values[key] = value
            self.detail_form.addRow(label, value)
        detail_scroll.setWidget(detail_body)
        detail_layout.addWidget(detail_scroll, 1)

        self.edit_button = QPushButton("Edit Tags…", detail)
        self.edit_button.clicked.connect(self.edit_tags)
        detail_layout.addWidget(self.edit_button)
        artwork_buttons = QHBoxLayout()
        set_cover = QPushButton("Cover…", detail)
        set_cover.clicked.connect(self.set_cover)
        remove_cover = QPushButton("Remove", detail)
        remove_cover.clicked.connect(self.remove_cover)
        extract_cover = QPushButton("Extract…", detail)
        extract_cover.clicked.connect(self.extract_cover)
        reveal = QPushButton("Reveal", detail)
        reveal.clicked.connect(self.reveal_selected)
        artwork_buttons.addWidget(set_cover)
        artwork_buttons.addWidget(remove_cover)
        artwork_buttons.addWidget(extract_cover)
        artwork_buttons.addWidget(reveal)
        detail_layout.addLayout(artwork_buttons)
        splitter.addWidget(detail)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1000, 320])
        outer_layout.addWidget(splitter, 1)
        self.setCentralWidget(outer)

    def _create_status_bar(self) -> None:
        self.statusBar().showMessage(f"TrackStash {__version__}")

    # ------------------------------------------------------------------
    # Library browsing

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
        self.refresh_tracks()

    def open_library_menu(self) -> None:
        library = self._require_library()
        if library is None:
            return
        menu = QMenu(self)
        rename = menu.addAction("Rename / Change Identifier…")
        rekey = menu.addAction("ReKey IDs…")
        toggle = menu.addAction("Disable Library" if library.enabled else "Enable Library")
        menu.addSeparator()
        remove = menu.addAction("Remove Library Index…")
        chosen = menu.exec(self.library_combo.mapToGlobal(self.library_combo.rect().bottomLeft()))
        if chosen == rename:
            name, accepted = QInputDialog.getText(
                self, "Library Name", "Display name:", text=library.name
            )
            if not accepted:
                return
            identifier, accepted = QInputDialog.getText(
                self,
                "Library Identifier",
                "Identifier (namespace stays unchanged until ReKey):",
                text=library.identifier,
            )
            if not accepted:
                return
            try:
                self.db.rename_library(library.id, name=name or library.name, identifier=identifier)
            except Exception as exc:
                QMessageBox.critical(self, "Rename failed", str(exc))
            self.refresh_libraries()
        elif chosen == rekey:
            answer = QMessageBox.question(
                self,
                "ReKey Library",
                f"Recompute all song IDs for “{library.name}” using the current "
                "identifier? A database backup is written first.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                result = self.service.rekey_library(library.id)
            except Exception as exc:
                QMessageBox.critical(self, "ReKey failed", str(exc))
                return
            self.refresh_libraries()
            QMessageBox.information(
                self,
                "ReKey complete",
                f"Updated {result.updated} song IDs.\nBackup: {result.backup}",
            )
        elif chosen == toggle:
            self.db.set_library_enabled(library.id, not library.enabled)
            self.refresh_libraries()
        elif chosen == remove:
            answer = QMessageBox.question(
                self,
                "Remove Library",
                f"Remove the index for “{library.name}”?\n\n"
                "Files on disk are never touched. This cannot be undone.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.db.remove_library(library.id)
            self._current_library_id = None
            self.refresh_libraries()

    def refresh_tracks(self) -> None:
        query = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        if not self._current_library_id:
            self.model.set_tracks([])
            self._update_album_filter_ui()
            self.statusBar().showMessage("No library selected")
            if hasattr(self, "album_model"):
                self.album_model.set_albums([])
            return
        tracks = self.db.list_tracks(
            library_id=self._current_library_id,
            album_id=self._album_filter_id,
            query=query,
        )
        if hasattr(self, "format_filter"):
            format_value = str(self.format_filter.currentData() or "")
            if format_value:
                tracks = [track for track in tracks if track.format.upper() == format_value]
        if hasattr(self, "missing_artwork") and self.missing_artwork.isChecked():
            tracks = [track for track in tracks if not self._track_has_artwork(track)]
        self.model.set_tracks(tracks)
        library = self.db.get_library(self._current_library_id)
        library_label = library.name if library else "Library"
        self._update_album_filter_ui()
        self.statusBar().showMessage(f"{library_label} · {len(tracks)} tracks")
        self.refresh_albums()

    def refresh_albums(self) -> None:
        if not hasattr(self, "album_model"):
            return
        if not self._current_library_id:
            self.album_model.set_albums([])
            return
        query = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        albums = self.db.list_albums(self._current_library_id, query=query)
        self.album_model.set_albums(albums)
        if hasattr(self, "tabs"):
            self.tabs.setTabText(1, f"Albums ({len(albums)})")

    def _tab_changed(self, index: int) -> None:
        if index == 1:
            self.refresh_albums()

    def _album_activated(self, index: QModelIndex) -> None:
        row = index.row()
        album = self.album_model.album_at(row)
        if album is None:
            return
        self._album_filter_id = album.id
        self._album_filter_title = album.title
        self.tabs.setCurrentIndex(0)
        self.refresh_tracks()

    def clear_album_filter(self) -> None:
        self._album_filter_id = None
        self._album_filter_title = ""
        self.refresh_tracks()

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

    def _selection_changed(self, *_args: object) -> None:
        ids = self.selected_track_ids()
        if not ids:
            self.detail_title.setText("No track selected")
            self.detail_subtitle.setText("")
            self.artwork_label.setPixmap(QPixmap())
            self.artwork_label.setText("No artwork")
            for label in self.detail_values.values():
                label.setText("")
            return
        if len(ids) > 1:
            self.detail_title.setText(f"{len(ids)} tracks selected")
            self.detail_subtitle.setText("Use Edit Tags to apply fields to the selection.")
            self.artwork_label.setPixmap(QPixmap())
            self.artwork_label.setText(f"{len(ids)} tracks")
            for label in self.detail_values.values():
                label.setText("")
            return
        track = self.db.get_track(ids[0])
        if track is None:
            return
        self._show_track(track)

    def _show_track(self, track: Track) -> None:
        self.detail_title.setText(track.title or "Untitled")
        self.detail_subtitle.setText(f"{track.artist} — {track.album}")
        self.detail_values["path"].setText(track.path)
        self.detail_values["album_artist"].setText(track.album_artist)
        self.detail_values["genre"].setText(track.genre)
        self.detail_values["year"].setText(track.year)
        track_text = str(track.track)
        if track.track_total:
            track_text += f" / {track.track_total}"
        self.detail_values["track"].setText(track_text)
        self.detail_values["format"].setText(track.format)
        self.detail_values["bitrate"].setText(f"{track.bitrate} kbps" if track.bitrate else "—")
        self.detail_values["sample_rate"].setText(
            f"{track.sample_rate} Hz" if track.sample_rate else "—"
        )
        minutes = track.duration // 60
        seconds = round(track.duration % 60)
        self.detail_values["duration"].setText(f"{int(minutes)}:{seconds:02d}")
        tags = self.db.load_tag_set(track.id)
        extended: list[str] = []
        if tags is not None:
            for key, label in (
                ("composer", "Composer"),
                ("bpm", "BPM"),
                ("musical_key", "Key"),
                ("label", "Label"),
                ("catalog_number", "Catalog"),
                ("isrc", "ISRC"),
            ):
                value = getattr(tags, key)
                if value:
                    extended.append(f"{label}: {value}")
        self.detail_values["tags"].setText("\n".join(extended) or "—")
        self._show_artwork(track)

    def _show_artwork(self, track: Track) -> None:
        candidates: list[Path] = []
        if track.artwork_path:
            candidates.append(Path(track.artwork_path))
        candidates.append(self.service.artwork_dir / f"{track.album_id.upper()}.jpg")
        for candidate in candidates:
            if candidate.is_file():
                pixmap = QPixmap(str(candidate))
                if not pixmap.isNull():
                    self.artwork_label.setPixmap(
                        pixmap.scaled(
                            240,
                            240,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    self.artwork_label.setText("")
                    return
        self.artwork_label.setPixmap(QPixmap())
        self.artwork_label.setText("No artwork")

    # ------------------------------------------------------------------
    # Selection helpers

    def selected_track_ids(self) -> list[str]:
        selection = self.table.selectionModel()
        if selection is None:
            return []
        ids: list[str] = []
        for index in selection.selectedRows():
            track = self.model.track_at(index.row())
            if track is not None:
                ids.append(track.id)
        return ids

    def _require_selection(self) -> list[str] | None:
        ids = self.selected_track_ids()
        if not ids:
            QMessageBox.information(self, "No selection", "Select one or more tracks first.")
            return None
        return ids

    def _require_library(self) -> Library | None:
        if self._current_library_id:
            return self.db.get_library(self._current_library_id)
        if self._libraries:
            return self._libraries[0]
        QMessageBox.information(self, "No library", "Add a library first.")
        return None

    # ------------------------------------------------------------------
    # Actions

    def add_library(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a Library Folder", str(Path.home() / "Music")
        )
        if not folder:
            return
        identifier, accepted = QInputDialog.getText(
            self,
            "Library Identifier",
            "Identifier (leave empty for the next libraryN):",
        )
        if not accepted:
            return
        try:
            library = self.db.add_library(folder, identifier=identifier or None)
        except Exception as exc:
            QMessageBox.critical(self, "Could not add library", str(exc))
            return
        self._current_library_id = library.id
        self.refresh_libraries()

    def import_files(self) -> None:
        library = self._require_library()
        if library is None:
            return
        dialog = ImportDialog(self.service, library, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_libraries()
            self.refresh_tracks()
            self.statusBar().showMessage("Import complete")

    def scan(self, mode: str) -> None:
        library = self._require_library()
        if library is None:
            return
        progress = QProgressDialog("Scanning…", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        def report(phase: str, current: int, total: int, message: str) -> None:
            text = f"{phase} {current}/{total}" if total else phase
            progress.setLabelText(text)
            QApplication.processEvents()
            if progress.wasCanceled():
                raise RuntimeError("Scan cancelled")

        try:
            result = self.service.scan_library(library.id, mode=mode, progress=report)
        except RuntimeError as exc:
            progress.close()
            QMessageBox.information(self, "Scan", str(exc))
            self.refresh_tracks()
            return
        progress.close()
        self.refresh_libraries()
        if result.missing:
            dialog = MissingFilesDialog(sorted(set(result.missing)), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected = dialog.selected_paths()
                ids = [
                    track.id
                    for path in selected
                    if (track := self.db.get_track_by_path(path)) is not None
                ]
                if ids:
                    self.service.delete_tracks(ids)
                    self.refresh_libraries()
                    self.refresh_tracks()
        message = f"Discovered {result.discovered} files, updated {result.updated}."
        if result.errors:
            message += f"\n{len(result.errors)} errors."
            QMessageBox.warning(self, "Scan warnings", "\n".join(result.errors[:10]))
        self.statusBar().showMessage(message)

    def edit_tags(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        editor = TagEditorDialog(self.service, ids, self)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        edits = editor.edits()
        try:
            changes = self.service.preview_tag_edits(ids, edits)
        except Exception as exc:
            QMessageBox.critical(self, "Tag preview failed", str(exc))
            return
        if not any(change.changed_fields for change in changes):
            QMessageBox.information(self, "No changes", "The selected fields are unchanged.")
            return
        preview = TagPreviewDialog(changes, self)
        if preview.exec() != QDialog.DialogCode.Accepted:
            return
        result = self.service.update_tags(ids, edits)
        self.refresh_libraries()
        self.refresh_tracks()
        if result.errors:
            QMessageBox.warning(self, "Tag update warnings", "\n".join(result.errors[:10]))
        self.statusBar().showMessage(f"Updated {len(result.updated)} tracks")

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
        self.statusBar().showMessage(
            f"Deleted {result.deleted} tracks, trashed {result.trashed} files"
        )

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
        self.statusBar().showMessage(message)

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
        self.statusBar().showMessage(message)

    def find_duplicates(self) -> None:
        library = self._require_library()
        if library is None:
            return
        self.statusBar().showMessage("Hashing tracks…")
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
                self.statusBar().showMessage(f"Hashing tracks… {index}/{len(tracks)}")
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
            self.statusBar().showMessage(f"Removed {result.deleted} duplicate rows from the index")

    def set_cover(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Cover Image",
            str(Path.home()),
            "Images (*.jpg *.jpeg *.png)",
        )
        if not filename:
            return
        try:
            data = Path(filename).read_bytes()
        except OSError as exc:
            QMessageBox.critical(self, "Cover", str(exc))
            return
        errors = self.service.set_artwork(ids, data)
        self.refresh_tracks()
        if errors:
            QMessageBox.warning(self, "Cover warnings", "\n".join(errors[:10]))
        else:
            self.statusBar().showMessage(f"Updated cover for {len(ids)} tracks")

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
        errors = self.service.remove_artwork(ids)
        self.refresh_tracks()
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
            self,
            "Extract Cover",
            str(Path.home() / "cover.jpg"),
            "Images (*.jpg *.png)",
        )
        if not filename:
            return
        try:
            path = self.service.extract_artwork(ids[0], filename)
        except Exception as exc:
            QMessageBox.critical(self, "Extract Cover", str(exc))
            return
        self.statusBar().showMessage(f"Cover written to {path}")

    def reveal_selected(self) -> None:
        ids = self._require_selection()
        if ids is None:
            return
        track = self.db.get_track(ids[0])
        if track is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(track.path).parent)))

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self.db,
            self.service.default_template,
            self.service.cover_size,
            self.service.cover_quality,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        template, cover_size, quality = dialog.values()
        self.db.set_setting("default_template", template)
        self.db.set_setting("cover_size", str(cover_size))
        self.db.set_setting("cover_quality", str(quality))
        self.service.default_template = template
        self.service.cover_size = cover_size
        self.service.cover_quality = quality
        self.statusBar().showMessage("Settings saved")

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "About TrackStash",
            f"TrackStash {__version__}\n\n"
            "A local-first managed music library.\n"
            "Licensed under GPL-3.0-only.",
        )
