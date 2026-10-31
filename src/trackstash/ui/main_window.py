"""TrackStash main window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from trackstash import __version__
from trackstash.core.db import Database, Library, Track
from trackstash.core.library import LibraryService, ScanResult
from trackstash.ui.dialogs import (
    DeleteDialog,
    ImportDialog,
    MissingFilesDialog,
    OrganizeDialog,
    TagEditorDialog,
    TagPreviewDialog,
)
from trackstash.ui.models import TrackTableModel


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
        self._current_library_id: str | None = None
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

        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.refresh_action.triggered.connect(self.refresh_tracks)

        self.quit_action = QAction("Quit", self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)

        self.about_action = QAction("About TrackStash", self)
        self.about_action.triggered.connect(self.show_about)

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
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

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self.edit_action)
        edit_menu.addAction(self.undo_action)

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
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        self.addToolBar(toolbar)

    def _create_central_widget(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        sidebar = QWidget(splitter)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        heading = QLabel("Libraries", sidebar)
        heading.setStyleSheet("font-weight: 600;")
        sidebar_layout.addWidget(heading)
        self.library_list = QListWidget(sidebar)
        self.library_list.currentItemChanged.connect(self._library_changed)
        sidebar_layout.addWidget(self.library_list, 1)
        add_button = QPushButton("Add Library…", sidebar)
        add_button.clicked.connect(self.add_library)
        sidebar_layout.addWidget(add_button)
        splitter.addWidget(sidebar)

        center = QWidget(splitter)
        center_layout = QVBoxLayout(center)
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit(center)
        self.search_edit.setPlaceholderText("Search title, artist, album, genre, path…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.refresh_tracks)
        refresh_button = QPushButton("Refresh", center)
        refresh_button.clicked.connect(self.refresh_tracks)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(refresh_button)
        center_layout.addLayout(search_row)

        self.model = TrackTableModel()
        self.table = QTableView(center)
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
        center_layout.addWidget(self.table, 1)
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
        splitter.addWidget(detail)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([220, 860, 320])
        self.setCentralWidget(splitter)

    def _create_status_bar(self) -> None:
        self.statusBar().showMessage(f"TrackStash {__version__}")

    # ------------------------------------------------------------------
    # Library browsing

    def refresh_libraries(self) -> None:
        previous = self._current_library_id
        self._libraries = self.db.list_libraries()
        self.library_list.blockSignals(True)
        self.library_list.clear()
        all_item = QListWidgetItem("All Tracks")
        all_item.setData(Qt.ItemDataRole.UserRole, None)
        self.library_list.addItem(all_item)
        for library in self._libraries:
            count = self.db.library_track_count(library.id)
            item = QListWidgetItem(f"{library.name}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, library.id)
            self.library_list.addItem(item)
        self.library_list.blockSignals(False)

        target_row = 0
        for row in range(self.library_list.count()):
            if self.library_list.item(row).data(Qt.ItemDataRole.UserRole) == previous:
                target_row = row
                break
        self.library_list.setCurrentRow(target_row)

    def _library_changed(self, current: QListWidgetItem | None, _previous: object) -> None:
        self._current_library_id = (
            current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        )
        self.refresh_tracks()

    def refresh_tracks(self) -> None:
        query = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        tracks = self.db.list_tracks(library_id=self._current_library_id, query=query)
        self.model.set_tracks(tracks)
        library_label = "All Tracks"
        if self._current_library_id:
            library = self.db.get_library(self._current_library_id)
            library_label = library.name if library else "Library"
        self.statusBar().showMessage(f"{library_label} · {len(tracks)} tracks")

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
        dialog = ImportDialog(self.service, self.db.list_libraries(), library.id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_libraries()
            self.refresh_tracks()
            self.statusBar().showMessage("Import complete")

    def scan(self, mode: str) -> None:
        libraries = (
            [self.db.get_library(self._current_library_id)]
            if self._current_library_id
            else self._libraries
        )
        libraries = [library for library in libraries if library is not None]
        if not libraries:
            QMessageBox.information(self, "No library", "Add a library first.")
            return
        progress = QProgressDialog("Scanning…", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        all_missing: list[str] = []
        errors: list[str] = []
        results: list[ScanResult] = []

        def report(phase: str, current: int, total: int, message: str) -> None:
            text = f"{phase} {current}/{total}" if total else phase
            progress.setLabelText(text)
            QApplication.processEvents()
            if progress.wasCanceled():
                raise RuntimeError("Scan cancelled")

        try:
            for library in libraries:
                result = self.service.scan_library(library.id, mode=mode, progress=report)
                results.append(result)
                all_missing.extend(result.missing)
                errors.extend(result.errors)
        except RuntimeError as exc:
            progress.close()
            QMessageBox.information(self, "Scan", str(exc))
            self.refresh_tracks()
            return
        progress.close()
        self.refresh_libraries()
        self.refresh_tracks()
        message = (
            f"Discovered {sum(result.discovered for result in results)} files, "
            f"updated {sum(result.updated for result in results)}."
        )
        if all_missing:
            dialog = MissingFilesDialog(sorted(set(all_missing)), self)
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
        if errors:
            message += f"\n{len(errors)} errors."
            QMessageBox.warning(self, "Scan warnings", "\n".join(errors[:10]))
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

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "About TrackStash",
            f"TrackStash {__version__}\n\n"
            "A local-first managed music library.\n"
            "Licensed under GPL-3.0-only.",
        )
