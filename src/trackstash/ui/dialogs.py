"""Modal workflows for tag editing, import, organization, and deletion."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from trackstash.core.db import Database, Library, Track
from trackstash.core.library import (
    ImportPlan,
    ImportResult,
    LibraryService,
    OrganizePlanItem,
    OrganizeResult,
    TagChange,
    collect_audio_files,
)
from trackstash.core.metadata import is_valid_numeric_tag
from trackstash.core.template import DEFAULT_TEMPLATE
from trackstash.ui.widgets import NoWheelComboBox, NoWheelSpinBox

TAG_FIELDS: tuple[tuple[str, str], ...] = (
    ("title", "Title"),
    ("artists", "Artists (comma separated)"),
    ("album_artist", "Album artist"),
    ("album", "Album"),
    ("genres", "Genres (comma separated)"),
    ("year", "Year"),
    ("track", "Track number"),
    ("track_total", "Track total"),
    ("disc", "Disc number"),
    ("disc_total", "Disc total"),
    ("comment", "Comment"),
    ("composer", "Composer"),
    ("bpm", "BPM"),
    ("musical_key", "Musical key"),
    ("isrc", "ISRC"),
    ("label", "Label"),
    ("catalog_number", "Catalog number"),
    ("original_date", "Original date"),
)


_TEMPLATE_HELP_ROWS: tuple[tuple[str, str], ...] = (
    ("{title}", "Song title"),
    ("{artist}", "Primary artist"),
    ("{album_artist}", "Album artist, falling back to the primary artist"),
    ("{artist_folder}", "Compilations for compilations, otherwise the album artist"),
    ("{album}", "Album title"),
    ("{year}", "Release year"),
    ("{date}", "Alias of {year}"),
    ("{genre}", "Primary genre"),
    ("{composer}", "Composer"),
    ("{comment}", "Comment"),
    ("{label}", "Record label"),
    ("{catalog}", "Catalog number"),
    ("{track}", "Track number"),
    ("{track_total}", "Total tracks on the disc"),
    ("{disc}", "Disc number"),
    ("{disc_total}", "Total discs"),
    ("{disc_dir}", "Disc 1/ for multi-disc albums; empty otherwise"),
    ("{disc_prefix}", "1- for a disc number other than a single-disc 1/1; empty otherwise"),
    ("{track_prefix}", "01 with the track number, empty when there is none"),
    ("{format}", "Lowercase source format, such as flac or mp3"),
    ("{bitrate}", "Bitrate in kbps"),
    ("{ext}", "File extension without the dot"),
)


class TemplateHelpDialog(QDialog):
    """Read-only reference for organization template variables."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Organization Template Variables")
        self.resize(760, 580)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Templates are used by Import and Organize to build destination "
            "paths. Select any text to copy it, or use Copy All.",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        rows = "".join(
            f"<tr><td><code>{token}</code></td><td>{description}</td></tr>"
            for token, description in _TEMPLATE_HELP_ROWS
        )
        self.browser = QTextBrowser(self)
        self.browser.setHtml(
            "<p><b>Variables</b></p>"
            "<table cellspacing='0' cellpadding='5' width='100%'>"
            "<tr><th align='left'>Variable</th><th align='left'>Description</th></tr>"
            f"{rows}</table>"
            "<p><b>Formatting</b></p>"
            "<table cellspacing='0' cellpadding='5' width='100%'>"
            "<tr><td><code>{track:02}</code></td>"
            "<td>Zero-pad a value to two digits; two- and three-digit values "
            "are preserved.</td></tr>"
            "<tr><td><code>{artist|Unknown Artist}</code></td>"
            "<td>Use the fallback when the value is empty.</td></tr>"
            "<tr><td><code>/</code></td><td>Create a subfolder.</td></tr>"
            "</table>"
            "<p><b>Default</b></p>"
            f"<pre>{DEFAULT_TEMPLATE}</pre>"
            "<p>The source file extension is added automatically when the "
            "rendered path has no extension.</p>"
        )
        layout.addWidget(self.browser, 1)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton("Copy All", self)
        self.copy_button.clicked.connect(self._copy)
        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)
        buttons.addWidget(self.copy_button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.browser.toPlainText())


def _template_field(
    value: str, parent: QWidget | None = None
) -> tuple[QWidget, QLineEdit, QPushButton, QPushButton]:
    host = QWidget(parent)
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    edit = QLineEdit(value, host)
    row.addWidget(edit, 1)
    default = QPushButton("Default", host)
    default.setAutoDefault(False)
    default.setToolTip("Restore the default template")
    default.clicked.connect(lambda: edit.setText(DEFAULT_TEMPLATE))
    row.addWidget(default)
    help_button = QPushButton("?", host)
    help_button.setAutoDefault(False)
    help_button.setFixedSize(28, 28)
    help_button.setToolTip("Show available template variables")
    help_button.clicked.connect(lambda: TemplateHelpDialog(host).exec())
    row.addWidget(help_button)
    return host, edit, default, help_button


def _duration_text(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _values_text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return str(value or "")


def _parse_value(key: str, text: str) -> object:
    if key in {"artists", "genres"}:
        return [part.strip() for part in text.split(",") if part.strip()]
    if key in {"track", "track_total", "disc", "disc_total"}:
        return text.strip()
    return text.strip()


class TagEditorDialog(QDialog):
    """Edit a single track or a checked subset of fields for many tracks."""

    def __init__(
        self,
        service: LibraryService,
        track_ids: Sequence[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.track_ids = list(track_ids)
        self._lines: dict[str, QLineEdit] = {}
        self._checks: dict[str, QCheckBox] = {}
        self.setWindowTitle("Edit Tags")
        self.setMinimumWidth(520)

        tags_by_id = service.db.load_tag_sets(self.track_ids)
        all_tags = [tags_by_id.get(track_id) for track_id in self.track_ids]
        tags = all_tags[0] if all_tags else None
        single = len(self.track_ids) == 1

        layout = QVBoxLayout(self)
        form = QFormLayout()
        for key, label in TAG_FIELDS:
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            check = QCheckBox(row)
            check.setChecked(single)
            check.setVisible(not single)
            line = QLineEdit(row)
            line.setPlaceholderText("Leave unchanged" if not single else "")
            if tags is not None:
                values = [
                    _values_text(getattr(tag, key)) if tag is not None else "" for tag in all_tags
                ]
                if single:
                    line.setText(values[0] if values else "")
                elif values and len(set(values)) == 1:
                    line.setText(values[0])
                else:
                    line.setPlaceholderText("Mixed values")
            row_layout.addWidget(check)
            row_layout.addWidget(line, 1)
            form.addRow(label, row)
            self._lines[key] = line
            self._checks[key] = check
        layout.addLayout(form)

        hint = QLabel(
            "Single track: every field is written. Multiple tracks: check only "
            "the fields to apply.",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def edits(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, line in self._lines.items():
            if not self._checks[key].isChecked():
                continue
            result[key] = _parse_value(key, line.text())
        return result

    def accept(self) -> None:
        edits = self.edits()
        if not edits:
            QMessageBox.warning(self, "No changes", "Select at least one field to apply.")
            return
        invalid = [
            label
            for key, label in TAG_FIELDS
            if key in edits and not is_valid_numeric_tag(key, edits[key])
        ]
        if invalid:
            QMessageBox.warning(
                self,
                "Invalid numbers",
                f"Track and disc values must be numeric. Check: {', '.join(invalid)}.",
            )
            return
        super().accept()


class TagPreviewDialog(QDialog):
    """Show a per-file tag diff before writing."""

    def __init__(self, changes: Sequence[TagChange], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview Tag Changes")
        self.resize(780, 420)
        layout = QVBoxLayout(self)
        table = QTableWidget(len(changes), 4, self)
        table.setHorizontalHeaderLabels(["File", "Changed fields", "Before -> After", "Warning"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        for row, change in enumerate(changes):
            table.setItem(row, 0, QTableWidgetItem(Path(change.path).name))
            table.setItem(row, 1, QTableWidgetItem(", ".join(change.changed_fields)))
            details: list[str] = []
            for field_name in change.changed_fields:
                before = getattr(change.before, field_name, "")
                after = getattr(change.after, field_name, "")
                if isinstance(before, list):
                    before = ", ".join(str(item) for item in before)
                if isinstance(after, list):
                    after = ", ".join(str(item) for item in after)
                if isinstance(before, bool):
                    before = "yes" if before else "no"
                if isinstance(after, bool):
                    after = "yes" if after else "no"
                details.append(f"{field_name}: {before or '—'} -> {after or '—'}")
            table.setItem(row, 2, QTableWidgetItem("; ".join(details)))
            table.setItem(row, 3, QTableWidgetItem(change.warning))
        layout.addWidget(table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class BulkImportEditDialog(QDialog):
    """Optional tag overrides applied to every file in an import."""

    FIELDS = (
        ("album_artist", "Album artist"),
        ("album", "Album"),
        ("genres", "Genres (comma separated)"),
        ("year", "Year"),
        ("comment", "Comment"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Tag Overrides")
        self._lines: dict[str, QLineEdit] = {}
        self._checks: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        for key, label in self.FIELDS:
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            check = QCheckBox(row)
            line = QLineEdit(row)
            line.setPlaceholderText("Leave unchanged")
            row_layout.addWidget(check)
            row_layout.addWidget(line, 1)
            form.addRow(label, row)
            self._lines[key] = line
            self._checks[key] = check
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def edits(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, line in self._lines.items():
            if self._checks[key].isChecked():
                result[key] = _parse_value(key, line.text())
        return result


class ImportDialog(QDialog):
    """Preview and execute a managed-library import."""

    def __init__(
        self,
        service: LibraryService,
        library: Library,
        parent: QWidget | None = None,
        sources: Sequence[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.library = library
        self.plan: ImportPlan | None = None
        self.import_result: ImportResult | None = None
        self.common_edits: dict[str, object] = {}
        self._sources: list[str] = []
        self.setWindowTitle(f"Import into {library.name}")
        self._restore_size()
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        source_row = QHBoxLayout()
        self.source_edit = QLineEdit(self)
        self.source_edit.setReadOnly(True)
        self.source_edit.setPlaceholderText("Drag files or folders here, or use Add Source…")
        self.source_button = QToolButton(self)
        self.source_button.setText("Add Source…")
        self.source_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        source_menu = QMenu(self.source_button)
        files_action = source_menu.addAction("Files…")
        files_action.triggered.connect(self._browse_files)
        folder_action = source_menu.addAction("Folder…")
        folder_action.triggered.connect(self._browse)
        self.source_button.setMenu(source_menu)
        source_row.addWidget(QLabel("Source", self))
        source_row.addWidget(self.source_edit, 1)
        source_row.addWidget(self.source_button)
        layout.addLayout(source_row)

        options = QHBoxLayout()
        options.addWidget(QLabel(f"Target: {library.name}", self))
        options.addWidget(QLabel("Mode", self))
        self.mode_combo = NoWheelComboBox(self)
        self.mode_combo.addItem("Copy (recommended)", "copy")
        self.mode_combo.addItem("Move", "move")
        self.mode_combo.currentIndexChanged.connect(self._options_changed)
        options.addWidget(self.mode_combo)
        options.addWidget(QLabel("Duplicates", self))
        self.duplicate_combo = NoWheelComboBox(self)
        self.duplicate_combo.addItem("Skip", "skip")
        self.duplicate_combo.addItem("Keep both", "keep")
        self.duplicate_combo.addItem("Replace", "replace")
        self.duplicate_combo.currentIndexChanged.connect(self._options_changed)
        options.addWidget(self.duplicate_combo)
        options.addStretch(1)
        overrides = QPushButton("Tag overrides…", self)
        overrides.clicked.connect(self._edit_overrides)
        options.addWidget(overrides)
        layout.addLayout(options)

        self.table = QTableWidget(0, 11, self)
        self.table.setHorizontalHeaderLabels(
            [
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
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for column, width in enumerate((58, 160, 120, 140, 120, 64, 64, 150, 160, 64)):
            self.table.setColumnWidth(column, width)
        layout.addWidget(self.table, 1)

        self.status = QLabel(
            "Drag files or folders here, or use Add Source to preview automatically.",
            self,
        )
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.import_button = QPushButton("Import", self)
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.execute)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.import_button)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        if sources:
            QTimer.singleShot(0, lambda: self.set_sources(list(sources)))

    def _restore_size(self) -> None:
        width, height = 1240, 680
        saved = self.service.db.get_setting("import_dialog_size", "")
        try:
            saved_width, saved_height = (int(part) for part in saved.lower().split("x", 1))
        except ValueError:
            pass
        else:
            width, height = max(900, saved_width), max(500, saved_height)
        self.resize(width, height)

    def done(self, result: int) -> None:
        self.service.db.set_setting("import_dialog_size", f"{self.width()}x{self.height()}")
        super().done(result)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.set_sources(paths)
            event.acceptProposedAction()

    def set_sources(self, sources: Sequence[str | Path]) -> None:
        self._sources = [str(source) for source in sources if str(source)]
        if not self._sources:
            self.source_edit.clear()
            self._invalidate_plan()
            self.status.setText(
                "Drag files or folders here, or use Add Source to preview automatically."
            )
            return
        if len(self._sources) == 1:
            self.source_edit.setText(self._sources[0])
        else:
            self.source_edit.setText(f"{len(self._sources)} sources selected")
        self.preview()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder to import")
        if folder:
            self.set_sources([folder])

    def _options_changed(self, *_args: object) -> None:
        self._invalidate_plan()
        if self._sources:
            self.preview()

    def _invalidate_plan(self, *_args: object) -> None:
        self.plan = None
        if hasattr(self, "import_button"):
            self.import_button.setEnabled(False)

    def _browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose files to import",
            str(Path.home()),
            "Audio (*.flac *.mp3 *.m4a *.mp4 *.ogg *.oga *.opus *.wav *.aiff "
            "*.aif *.ape *.wv *.dsf *.dff)",
        )
        if files:
            self.set_sources(files)

    def _edit_overrides(self) -> None:
        dialog = BulkImportEditDialog(self)
        if dialog.exec():
            self.common_edits = dialog.edits()
            self._invalidate_plan()
            self.status.setText("Tag overrides changed; previewing…")
            if self._sources:
                self.preview()

    def preview(self) -> None:
        sources = self._sources
        if not sources:
            self.status.setText(
                "Drag files or folders here, or use Add Source to preview automatically."
            )
            return
        try:
            files: list[Path] = []
            for item in sources:
                files.extend(collect_audio_files(item))
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        total_bytes = sum(path.stat().st_size for path in files)
        if len(files) > 1000 or total_bytes > 2 * 1024**3:
            size_text = f"{total_bytes / 1024**3:.1f} GB"
            answer = QMessageBox.question(
                self,
                "Large import",
                f"This import contains {len(files)} files ({size_text}).\\n\\n"
                "Copying the whole selection may consume significant disk space. "
                "Continue with the preview?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.status.setText("Planning import…")
        QApplication.processEvents()
        try:
            plan = self.service.plan_import(
                sources,
                self.library.id,
                mode=str(self.mode_combo.currentData()),
                common_edits=self.common_edits,
                duplicate_policy=str(self.duplicate_combo.currentData()),
                progress=self._progress,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        self.plan = plan
        self.table.setRowCount(len(plan.items))
        for row, plan_item in enumerate(plan.items):
            tags = plan_item.tags
            track_number = tags.track
            if track_number and tags.track_total:
                track_number = f"{track_number}/{tags.track_total}"
            values = (
                track_number,
                tags.title or Path(plan_item.source).stem,
                tags.primary_artist,
                tags.album,
                tags.album_artist_or_primary,
                plan_item.metadata.format.upper(),
                _duration_text(plan_item.metadata.duration),
                plan_item.source.name,
                plan_item.relative_path,
                plan_item.action,
            )
            tooltips = {
                7: str(plan_item.source),
                8: str(plan_item.destination),
            }
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column in tooltips:
                    cell.setToolTip(tooltips[column])
                self.table.setItem(row, column, cell)
            note = plan_item.warning
            if plan_item.collision:
                note = (note + " collision resolved").strip()
            self.table.setItem(row, 10, QTableWidgetItem(note))
        self.import_button.setEnabled(
            bool(plan.items) and any(item.action != "skip" for item in plan.items)
        )
        file_count = len(plan.items)
        error_count = len(plan.errors)
        file_word = "file" if file_count == 1 else "files"
        error_word = "error" if error_count == 1 else "errors"
        self.status.setText(f"{file_count} {file_word} planned, {error_count} {error_word}.")

    def _progress(self, phase: str, current: int, total: int, message: str) -> None:
        suffix = f" {current}/{total}" if total else ""
        self.status.setText(f"{phase}{suffix} {Path(message).name if message else ''}")
        QApplication.processEvents()

    def execute(self) -> None:
        if self.plan is None:
            self.preview()
        if self.plan is None:
            return
        self.import_button.setEnabled(False)
        try:
            result = self.service.execute_import(self.plan, progress=self._progress)
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            self.import_button.setEnabled(True)
            return
        self.import_result = result
        QMessageBox.information(
            self,
            "Import complete",
            f"Imported {len(result.imported)} tracks.\n"
            f"Skipped {len(result.skipped)}.\n"
            f"Errors {len(result.errors)}.",
        )
        self.accept()


class OrganizeDialog(QDialog):
    """Preview and execute a tag-driven organization pass."""

    def __init__(
        self,
        service: LibraryService,
        track_ids: Sequence[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.track_ids = list(track_ids)
        self.items: list[OrganizePlanItem] = []
        self.organize_result: OrganizeResult | None = None
        self.setWindowTitle("Organize Files")
        self.resize(980, 540)
        layout = QVBoxLayout(self)
        template_row = QHBoxLayout()
        template_row.addWidget(QLabel("Template", self))
        (
            template_host,
            self.template_edit,
            self.template_default_button,
            self.template_help_button,
        ) = _template_field(service.default_template, self)
        template_row.addWidget(template_host, 1)
        layout.addLayout(template_row)
        self.template_edit.textChanged.connect(self._template_changed)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Current path", "New path", "New UUID", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)

        self.status = QLabel("Preview the move before executing.", self)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        preview = QPushButton("Preview", self)
        preview.clicked.connect(self.preview)
        execute = QPushButton("Organize", self)
        execute.clicked.connect(self.execute)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(preview)
        buttons.addWidget(execute)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _template_changed(self, _text: str) -> None:
        self.items = []
        self.table.setRowCount(0)
        self.status.setText("Template changed; preview the move before executing.")

    def preview(self) -> None:
        self.status.setText("Planning…")
        QApplication.processEvents()
        try:
            self.items = self.service.preview_organize(
                self.track_ids, self.template_edit.text().strip() or DEFAULT_TEMPLATE
            )
        except Exception as exc:
            QMessageBox.critical(self, "Organize failed", str(exc))
            return
        self.table.setRowCount(len(self.items))
        for row, item in enumerate(self.items):
            self.table.setItem(row, 0, QTableWidgetItem(item.old_path))
            self.table.setItem(row, 1, QTableWidgetItem(item.new_path))
            self.table.setItem(row, 2, QTableWidgetItem(item.new_id))
            status = "unchanged" if item.unchanged else "collision" if item.collision else "move"
            self.table.setItem(row, 3, QTableWidgetItem(status))
        self.status.setText(f"{len(self.items)} tracks previewed.")

    def execute(self) -> None:
        if not self.items:
            self.preview()
        if not self.items:
            return
        try:
            self.organize_result = self.service.organize(self.items, progress=self._progress)
        except Exception as exc:
            QMessageBox.critical(self, "Organize failed", str(exc))
            return
        QMessageBox.information(
            self,
            "Organize complete",
            f"Moved {len(self.organize_result.moved)} tracks.\n"
            f"Errors {len(self.organize_result.errors)}.",
        )
        self.accept()

    def _progress(self, phase: str, current: int, total: int, message: str) -> None:
        self.status.setText(f"{phase} {current}/{total}")
        QApplication.processEvents()


class DeleteDialog(QDialog):
    """Choose index-only deletion or moving files to the macOS Trash."""

    def __init__(self, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Delete Tracks")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Delete {count} selected track(s).", self))
        self.index_only = QRadioButton("Remove from the library index only", self)
        self.index_only.setChecked(True)
        self.trash_files = QRadioButton("Remove from the index and move files to the Trash", self)
        layout.addWidget(self.index_only)
        layout.addWidget(self.trash_files)
        warning = QLabel(
            "Index-only removal leaves files on disk. Moving files to the macOS "
            "Trash cannot be undone inside TrackStash.",
            self,
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def delete_files(self) -> bool:
        return self.trash_files.isChecked()


class MissingFilesDialog(QDialog):
    """Review and select missing paths for index removal."""

    def __init__(self, paths: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Missing Files")
        self.resize(760, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "These files are indexed but no longer exist. Nothing is removed "
                "unless you select it.",
                self,
            )
        )
        self.list = QListWidget(self)
        for path in paths:
            item = QListWidgetItem(path, self.list)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
        layout.addWidget(self.list, 1)
        buttons_row = QHBoxLayout()
        select_all = QPushButton("Select all", self)
        select_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        clear = QPushButton("Clear", self)
        clear.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        buttons_row.addWidget(select_all)
        buttons_row.addWidget(clear)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, state: Qt.CheckState) -> None:
        for index in range(self.list.count()):
            self.list.item(index).setCheckState(state)

    def selected_paths(self) -> list[str]:
        return [
            self.list.item(index).text()
            for index in range(self.list.count())
            if self.list.item(index).checkState() == Qt.CheckState.Checked
        ]


class DuplicateDialog(QDialog):
    """Review exact and probable duplicate groups."""

    def __init__(
        self,
        exact_groups: Sequence[Sequence[Track]],
        probable_groups: Sequence[Sequence[Track]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Duplicate Review")
        self.resize(980, 560)
        self.selected_ids: list[str] = []
        self._tables: list[QTableWidget] = []
        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.addTab(self._make_table(exact_groups, "Exact"), "Exact content")
        tabs.addTab(self._make_table(probable_groups, "Probable"), "Probable matches")
        layout.addWidget(tabs, 1)
        hint = QLabel(
            "Select the rows to remove from the index. Files are never deleted here.",
            self,
        )
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        remove = QPushButton("Remove selected from index", self)
        remove.clicked.connect(self._remove_selected)
        close = QPushButton("Close", self)
        close.clicked.connect(self.reject)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _make_table(self, groups: Sequence[Sequence[Track]], label: str) -> QTableWidget:
        rows = sum(len(group) for group in groups)
        table = QTableWidget(rows, 7, self)
        table.setHorizontalHeaderLabels(
            [label, "Title", "Artist", "Album", "Format", "Bitrate", "Path"]
        )
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        row = 0
        for group_index, group in enumerate(groups, start=1):
            for track in group:
                table.setItem(row, 0, QTableWidgetItem(str(group_index)))
                table.setItem(row, 1, QTableWidgetItem(track.title))
                table.setItem(row, 2, QTableWidgetItem(track.artist))
                table.setItem(row, 3, QTableWidgetItem(track.album))
                table.setItem(row, 4, QTableWidgetItem(track.format))
                table.setItem(
                    row,
                    5,
                    QTableWidgetItem(f"{track.bitrate} Kbps" if track.bitrate else ""),
                )
                path_item = QTableWidgetItem(track.path)
                path_item.setData(Qt.ItemDataRole.UserRole, track.id)
                table.setItem(row, 6, path_item)
                row += 1
        self._tables.append(table)
        return table

    def _remove_selected(self) -> None:
        ids: list[str] = []
        for table in self._tables:
            for index in table.selectionModel().selectedRows():
                item = table.item(index.row(), 6)
                if item is not None:
                    track_id = item.data(Qt.ItemDataRole.UserRole)
                    if track_id:
                        ids.append(str(track_id))
        if not ids:
            QMessageBox.information(self, "Duplicates", "Select at least one duplicate row.")
            return
        self.selected_ids = sorted(set(ids))
        self.accept()


class SettingsDialog(QDialog):
    """Application settings, column layout, and library tools."""

    def __init__(
        self,
        database: Database,
        template: str,
        columns: Sequence[tuple[str, str]] = (),
        visible_columns: Sequence[str] = (),
        album_sort: str = "date_added",
        album_order: str = "desc",
        status_bar_visible: bool = True,
        strong_order: bool = True,
        preserve_mtime: bool = True,
        artwork_max_size: int = 1000,
        artwork_quality: int = 90,
        artwork_aspect: str = "crop",
        service: LibraryService | None = None,
        current_library_id: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.requested_action: str | None = None
        self.library_buttons: dict[str, QPushButton] = {}
        self.setWindowTitle("TrackStash Settings")
        self.setMinimumSize(680, 620)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)

        general_tab = QWidget(self.tabs)
        general_layout = QVBoxLayout(general_tab)
        form = QFormLayout()
        (
            template_host,
            self.template_edit,
            self.template_default_button,
            self.template_help_button,
        ) = _template_field(template, general_tab)
        form.addRow("Organization template", template_host)
        template_hint = QLabel(
            "Used by Import and Organize. {disc_prefix} adds the disc number "
            "before the track number unless the album is a single disc; {track_prefix} "
            "adds the track number only when there is one; {disc_dir} adds a Disc N/ "
            "folder for multi-disc albums.",
            general_tab,
        )
        template_hint.setWordWrap(True)
        form.addRow("", template_hint)
        self.database_label = QLineEdit(str(database.path), general_tab)
        self.database_label.setReadOnly(True)
        form.addRow("Database", self.database_label)
        general_layout.addLayout(form)

        albums_group = QGroupBox("Albums view", general_tab)
        albums_form = QFormLayout(albums_group)
        self.album_sort = NoWheelComboBox(albums_group)
        for label, value in (
            ("Date added", "date_added"),
            ("Album title", "title"),
            ("Artist", "artist"),
            ("Year", "year"),
        ):
            self.album_sort.addItem(label, value)
        sort_index = self.album_sort.findData(album_sort)
        self.album_sort.setCurrentIndex(sort_index if sort_index >= 0 else 0)
        albums_form.addRow("Sort by", self.album_sort)
        self.album_order = NoWheelComboBox(albums_group)
        self.album_order.addItem("Descending", "desc")
        self.album_order.addItem("Ascending", "asc")
        order_index = self.album_order.findData(album_order)
        self.album_order.setCurrentIndex(order_index if order_index >= 0 else 0)
        albums_form.addRow("Order", self.album_order)
        general_layout.addWidget(albums_group)

        editing_group = QGroupBox("Editing", general_tab)
        editing_layout = QVBoxLayout(editing_group)
        self.strong_order_checkbox = QCheckBox(
            "Strong ordering: move files immediately after tag changes", editing_group
        )
        self.strong_order_checkbox.setChecked(strong_order)
        editing_layout.addWidget(self.strong_order_checkbox)
        self.preserve_mtime_checkbox = QCheckBox(
            "Preserve file modification time when editing indexed files",
            editing_group,
        )
        self.preserve_mtime_checkbox.setChecked(preserve_mtime)
        editing_layout.addWidget(self.preserve_mtime_checkbox)
        general_layout.addWidget(editing_group)

        artwork_group = QGroupBox("Artwork", general_tab)
        artwork_form = QFormLayout(artwork_group)
        self.artwork_max_size = NoWheelSpinBox(artwork_group)
        self.artwork_max_size.setRange(64, 10000)
        self.artwork_max_size.setValue(artwork_max_size)
        artwork_form.addRow("Maximum long edge (px)", self.artwork_max_size)
        self.artwork_quality = NoWheelSpinBox(artwork_group)
        self.artwork_quality.setRange(1, 100)
        self.artwork_quality.setValue(artwork_quality)
        artwork_form.addRow("JPEG quality", self.artwork_quality)
        self.artwork_crop = NoWheelComboBox(artwork_group)
        self.artwork_crop.addItem("Fit to square", "fit")
        self.artwork_crop.addItem("Crop to square", "crop")
        self.artwork_crop.addItem("Original aspect ratio", "original")
        crop_index = self.artwork_crop.findData(artwork_aspect)
        self.artwork_crop.setCurrentIndex(crop_index if crop_index >= 0 else 1)
        artwork_form.addRow("Aspect ratio", self.artwork_crop)
        general_layout.addWidget(artwork_group)

        self.status_bar_checkbox = QCheckBox("Show status bar", general_tab)
        self.status_bar_checkbox.setChecked(status_bar_visible)
        general_layout.addWidget(self.status_bar_checkbox)

        general_layout.addStretch(1)
        self.tabs.addTab(general_tab, "General")

        columns_tab = QWidget(self.tabs)
        columns_layout = QVBoxLayout(columns_tab)
        columns_group = QGroupBox("Tracks view columns", columns_tab)
        columns_grid = QGridLayout(columns_group)
        self.column_checks: dict[str, QCheckBox] = {}
        visible = set(visible_columns) if visible_columns else {key for key, _ in columns}
        for index, (key, label) in enumerate(columns):
            check = QCheckBox(label, columns_group)
            check.setChecked(key in visible)
            columns_grid.addWidget(check, index // 2, index % 2)
            self.column_checks[key] = check
        columns_layout.addWidget(columns_group)
        columns_layout.addStretch(1)
        self.tabs.addTab(columns_tab, "Columns")

        library_tab = QWidget(self.tabs)
        library_layout = QVBoxLayout(library_tab)
        from trackstash.ui.library_manager import LibraryManagerPanel

        panel_service = service or LibraryService(database)
        self.library_panel = LibraryManagerPanel(
            database,
            panel_service,
            current_library_id,
            library_tab,
        )
        library_layout.addWidget(self.library_panel)

        library_row = QHBoxLayout()
        library_row.addWidget(
            self._library_button("find_duplicates", "Find Duplicates…", library_tab)
        )
        library_row.addStretch(1)
        library_layout.addLayout(library_row)

        database_group = QGroupBox("Database", library_tab)
        database_layout = QVBoxLayout(database_group)
        database_row = QHBoxLayout()
        database_row.addWidget(QLabel("Create a consistent SQLite backup.", database_group))
        database_row.addStretch(1)
        self.backup_button = QPushButton("Backup Database…", database_group)
        self.backup_button.clicked.connect(self._backup)
        database_row.addWidget(self.backup_button)
        database_layout.addLayout(database_row)
        library_layout.addWidget(database_group)
        library_layout.addStretch(1)
        self.tabs.addTab(library_tab, "Library")

        layout.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _library_button(self, key: str, text: str, parent: QWidget) -> QPushButton:
        button = QPushButton(text, parent)
        button.clicked.connect(
            lambda _checked=False, action=key: self._request_library_action(action)
        )
        self.library_buttons[key] = button
        return button

    def _request_library_action(self, action: str) -> None:
        self.requested_action = action
        self.accept()

    def _backup(self) -> None:
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Backup Database",
            str(Path.home() / "TrackStash-backup.sqlite"),
            "SQLite Database (*.sqlite)",
        )
        if not destination:
            return
        try:
            path = self.database.backup(destination)
            QMessageBox.information(self, "Backup", f"Backup written to {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Backup failed", str(exc))

    def values(self) -> tuple[str, list[str], str, str, bool, bool, bool, int, int, str]:
        visible = [key for key, check in self.column_checks.items() if check.isChecked()]
        return (
            self.template_edit.text().strip() or DEFAULT_TEMPLATE,
            visible or [key for key, _ in self.column_checks.items()],
            str(self.album_sort.currentData() or "date_added"),
            str(self.album_order.currentData() or "desc"),
            self.status_bar_checkbox.isChecked(),
            self.strong_order_checkbox.isChecked(),
            self.preserve_mtime_checkbox.isChecked(),
            self.artwork_max_size.value(),
            self.artwork_quality.value(),
            str(self.artwork_crop.currentData() or "crop"),
        )


class AutoNumberDialog(QDialog):
    """Choose how selected tracks are renumbered."""

    def __init__(self, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Auto-number Tracks")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Renumber {count} selected tracks.", self))
        self.per_disc = QCheckBox("Number each disc separately", self)
        self.per_disc.setChecked(True)
        layout.addWidget(self.per_disc)
        row = QHBoxLayout()
        row.addWidget(QLabel("Start at", self))
        self.start = NoWheelSpinBox(self)
        self.start.setRange(1, 999)
        self.start.setValue(1)
        row.addWidget(self.start)
        row.addStretch(1)
        layout.addLayout(row)
        hint = QLabel(
            "Tracks are ordered by their current track number, then title. "
            "A preview is shown before anything is written.",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[bool, int]:
        return self.per_disc.isChecked(), self.start.value()
