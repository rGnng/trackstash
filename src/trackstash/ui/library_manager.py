"""Library management window: add, scan, relocate, rekey, enable, remove."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from trackstash.core.db import Database, Library
from trackstash.core.library import LibraryService
from trackstash.ui.dialogs import MissingFilesDialog


class LibraryManagerDialog(QDialog):
    """Manage the currently selected managed library."""

    changed = Signal()

    def __init__(
        self,
        database: Database,
        service: LibraryService,
        current_library_id: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.service = service
        self.current_library_id = current_library_id
        self.setWindowTitle("Library Manager")
        self.setMinimumWidth(620)
        self.resize(680, 460)
        self._libraries: list[Library] = []

        layout = QVBoxLayout(self)
        selector = QHBoxLayout()
        selector.addWidget(QLabel("Library", self))
        self.library_combo = QComboBox(self)
        self.library_combo.setMinimumWidth(320)
        self.library_combo.currentIndexChanged.connect(self._selection_changed)
        selector.addWidget(self.library_combo, 1)
        add_button = QPushButton("Add Library…", self)
        add_button.clicked.connect(self.add_library)
        selector.addWidget(add_button)
        layout.addLayout(selector)

        form = QFormLayout()
        self.path_value = QLabel("", self)
        self.path_value.setWordWrap(True)
        self.path_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.identifier_value = QLabel("", self)
        self.namespace_value = QLabel("", self)
        self.tracks_value = QLabel("", self)
        form.addRow("Folder", self.path_value)
        form.addRow("Identifier", self.identifier_value)
        form.addRow("Namespace", self.namespace_value)
        form.addRow("Tracks", self.tracks_value)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self.quick_button = QPushButton("Quick Scan", self)
        self.quick_button.clicked.connect(lambda: self.scan("quick"))
        self.full_button = QPushButton("Full Scan", self)
        self.full_button.clicked.connect(lambda: self.scan("full"))
        self.relocate_button = QPushButton("Change Location…", self)
        self.relocate_button.clicked.connect(self.change_location)
        self.rekey_button = QPushButton("ReKey IDs…", self)
        self.rekey_button.clicked.connect(self.rekey)
        actions.addWidget(self.quick_button)
        actions.addWidget(self.full_button)
        actions.addWidget(self.relocate_button)
        actions.addWidget(self.rekey_button)
        layout.addLayout(actions)

        secondary = QHBoxLayout()
        self.toggle_button = QPushButton("Disable Library", self)
        self.toggle_button.clicked.connect(self.toggle_enabled)
        self.remove_button = QPushButton("Remove Library Index…", self)
        self.remove_button.clicked.connect(self.remove_library)
        secondary.addWidget(self.toggle_button)
        secondary.addWidget(self.remove_button)
        secondary.addStretch(1)
        layout.addLayout(secondary)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.refresh()

    def selected_library(self) -> Library | None:
        library_id = self.library_combo.currentData()
        return self.database.get_library(library_id) if library_id else None

    def refresh(self) -> None:
        self._libraries = self.database.list_libraries()
        self.library_combo.blockSignals(True)
        self.library_combo.clear()
        for library in self._libraries:
            self.library_combo.addItem(library.name, library.id)
        index = self.library_combo.findData(self.current_library_id)
        if index < 0 and self.library_combo.count():
            index = 0
        if index >= 0:
            self.library_combo.setCurrentIndex(index)
        self.library_combo.blockSignals(False)
        self.current_library_id = str(self.library_combo.currentData() or "") or None
        self._show_library()

    def _selection_changed(self, _index: int) -> None:
        self.current_library_id = str(self.library_combo.currentData() or "") or None
        self._show_library()
        self.changed.emit()

    def _show_library(self) -> None:
        library = self.selected_library()
        enabled = library is not None
        for button in (
            self.quick_button,
            self.full_button,
            self.relocate_button,
            self.rekey_button,
            self.toggle_button,
            self.remove_button,
        ):
            button.setEnabled(enabled)
        if library is None:
            self.path_value.setText("No library selected")
            self.identifier_value.setText("")
            self.namespace_value.setText("")
            self.tracks_value.setText("")
            return
        self.path_value.setText(library.path)
        self.identifier_value.setText(library.identifier)
        self.namespace_value.setText(library.id_namespace)
        self.tracks_value.setText(str(self.database.library_track_count(library.id)))
        self.toggle_button.setText("Disable Library" if library.enabled else "Enable Library")

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
            library = self.database.add_library(folder, identifier=identifier or None)
        except Exception as exc:
            QMessageBox.critical(self, "Could not add library", str(exc))
            return
        self.current_library_id = library.id
        self.refresh()
        self.changed.emit()

    def scan(self, mode: str) -> None:
        library = self.selected_library()
        if library is None:
            return
        progress = QProgressDialog("Scanning…", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        def report(phase: str, current: int, total: int, _message: str) -> None:
            progress.setLabelText(f"{phase} {current}/{total}" if total else phase)
            QApplication.processEvents()
            if progress.wasCanceled():
                raise RuntimeError("Scan cancelled")

        try:
            result = self.service.scan_library(library.id, mode=mode, progress=report)
        except RuntimeError as exc:
            progress.close()
            QMessageBox.information(self, "Scan", str(exc))
            self.refresh()
            return
        progress.close()
        if result.missing:
            dialog = MissingFilesDialog(sorted(result.missing), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                ids = [
                    track.id
                    for path in dialog.selected_paths()
                    if (track := self.database.get_track_by_path(path)) is not None
                ]
                if ids:
                    self.service.delete_tracks(ids)
        if result.errors:
            QMessageBox.warning(self, "Scan warnings", "\n".join(result.errors[:10]))
        self.refresh()
        self.changed.emit()

    def change_location(self) -> None:
        library = self.selected_library()
        if library is None:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the New Library Folder", str(Path(library.path).parent)
        )
        if not folder:
            return
        answer = QMessageBox.question(
            self,
            "Change Library Location",
            f"Re-root “{library.name}” at:\n{folder}\n\n"
            "Move the files there first. Relative paths and song IDs must stay the same. "
            "A database backup is written before the change.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            updated = self.service.relocate_library(library.id, folder)
        except Exception as exc:
            QMessageBox.critical(self, "Relocate failed", str(exc))
            return
        self.current_library_id = updated.id
        self.refresh()
        self.changed.emit()

    def rekey(self) -> None:
        library = self.selected_library()
        if library is None:
            return
        answer = QMessageBox.question(
            self,
            "ReKey Library",
            f"Recompute all song IDs for “{library.name}” using the current identifier? "
            "A database backup is written first.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self.service.rekey_library(library.id)
        except Exception as exc:
            QMessageBox.critical(self, "ReKey failed", str(exc))
            return
        self.refresh()
        self.changed.emit()
        QMessageBox.information(
            self,
            "ReKey complete",
            f"Updated {result.updated} song IDs.\nBackup: {result.backup}",
        )

    def toggle_enabled(self) -> None:
        library = self.selected_library()
        if library is None:
            return
        self.database.set_library_enabled(library.id, not library.enabled)
        self.refresh()
        self.changed.emit()

    def remove_library(self) -> None:
        library = self.selected_library()
        if library is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove Library",
            f"Remove the index for “{library.name}”?\n\n"
            "Files on disk are never touched. This cannot be undone.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.database.remove_library(library.id)
        self.current_library_id = None
        self.refresh()
        self.changed.emit()
