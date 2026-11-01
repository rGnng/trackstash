"""Left-side media information and inline tag editor."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from trackstash.core.db import Track
from trackstash.core.metadata import TagSet

NUMERIC_TEXT_FIELDS = {"track", "track_total", "disc", "disc_total"}
FIELD_KEYS = (
    "title",
    "artists",
    "album",
    "album_artist",
    "genres",
    "year",
    "track",
    "track_total",
    "disc",
    "disc_total",
    "comment",
    "composer",
    "bpm",
    "musical_key",
    "isrc",
    "label",
    "catalog_number",
)
MIXED = object()


class TrackInfoEditor(QWidget):
    """Displays and edits one track or a batch of selected tracks."""

    save_requested = Signal(dict)
    cover_requested = Signal()
    remove_cover_requested = Signal()
    extract_cover_requested = Signal()
    reveal_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._track: Track | None = None
        self._tags: TagSet | None = None
        self._multi_mode = False
        self._multi_tracks: list[Track] = []
        self._multi_tags: list[TagSet] = []
        self._multi_base: dict[str, object] = {}
        self._baseline: dict[str, object] = {}
        self._dirty: set[str] = set()
        self._invalid: set[str] = set()
        self._loading = False
        self._artwork_pixmap = QPixmap()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.save_button = QPushButton("Save Changes", self)
        self.save_button.clicked.connect(self._emit_save)
        self.revert_button = QPushButton("Revert", self)
        self.revert_button.clicked.connect(self._revert)
        self.pending_label = QLabel("No pending changes", self)
        self.pending_label.setStyleSheet("color: palette(mid);")
        save_row = QHBoxLayout()
        save_row.addWidget(self.save_button)
        save_row.addWidget(self.revert_button)
        save_row.addWidget(self.pending_label, 1)
        layout.addLayout(save_row)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(4)

        self.artwork = QLabel(body)
        self.artwork.setMinimumSize(160, 160)
        self.artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork.setStyleSheet(
            "border: 1px solid #3A4554; background-color: #1B212B; color: #AAB4C3;"
        )
        self.artwork.setText("No artwork")
        body_layout.addWidget(self.artwork)
        self.artwork_info = QLabel("", body)
        self.artwork_info.setWordWrap(True)
        self.artwork_info.setStyleSheet("color: palette(mid);")
        body_layout.addWidget(self.artwork_info)

        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.form.setVerticalSpacing(4)
        self.lines: dict[str, QLineEdit] = {}
        for key, label in (
            ("title", "Title"),
            ("artists", "Artist"),
            ("album", "Album"),
            ("album_artist", "Album artist"),
            ("genres", "Genre"),
            ("year", "Year"),
            ("track", "Track"),
            ("track_total", "Track total"),
            ("disc", "Disc"),
            ("disc_total", "Disc total"),
            ("comment", "Comment"),
            ("composer", "Composer"),
            ("bpm", "BPM"),
            ("musical_key", "Key"),
            ("isrc", "ISRC"),
            ("label", "Label"),
            ("catalog_number", "Catalog"),
        ):
            line = QLineEdit(body)
            line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            line.textEdited.connect(lambda _text, field=key: self._field_changed(field))
            self.lines[key] = line
            self.form.addRow(label, line)
        self._normal_font = QFont(self.lines["title"].font())
        self._italic_font = QFont(self._normal_font)
        self._italic_font.setItalic(True)
        body_layout.addLayout(self.form)
        body_layout.addStretch(1)

        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.setEnabled(False)
        self._set_fields_enabled(False)
        self._refresh_dirty()

    def resizeEvent(self, event: QResizeEvent) -> None:
        if hasattr(self, "artwork"):
            width = max(160, self.width() - 40)
            self.artwork.setFixedSize(width, width)
            self._render_artwork()
        super().resizeEvent(event)

    def _render_artwork(self) -> None:
        if self._artwork_pixmap.isNull():
            self.artwork.setPixmap(QPixmap())
            self.artwork.setText("No artwork")
            return
        self.artwork.setPixmap(
            self._artwork_pixmap.scaled(
                self.artwork.width(),
                self.artwork.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.artwork.setText("")

    def _set_fields_enabled(self, enabled: bool) -> None:
        for widget in self.lines.values():
            widget.setEnabled(enabled)
        self.save_button.setEnabled(False)
        self.revert_button.setEnabled(False)

    def _set_line(self, key: str, value: object, *, mixed: bool = False) -> None:
        line = self.lines[key]
        if mixed:
            line.clear()
            line.setPlaceholderText("Multiple")
            line.setFont(self._italic_font)
        else:
            line.setText(self._display_value(value))
            line.setPlaceholderText("")
            line.setFont(self._normal_font)

    @staticmethod
    def _display_value(value: object) -> str:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value or "")

    def _values_from_tags(self, tags: TagSet) -> dict[str, object]:
        return {
            "title": tags.title,
            "artists": list(tags.artists),
            "album": tags.album,
            "album_artist": tags.album_artist,
            "genres": list(tags.genres),
            "year": tags.year,
            "track": str(tags.track) if tags.track else "",
            "track_total": str(tags.track_total) if tags.track_total else "",
            "disc": str(tags.disc) if tags.disc else "",
            "disc_total": str(tags.disc_total) if tags.disc_total else "",
            "comment": tags.comment,
            "composer": tags.composer,
            "bpm": tags.bpm,
            "musical_key": tags.musical_key,
            "isrc": tags.isrc,
            "label": tags.label,
            "catalog_number": tags.catalog_number,
        }

    def _field_changed(self, field: str) -> None:
        if self._loading:
            return
        line = self.lines.get(field)
        if line is not None and line.text():
            line.setFont(self._normal_font)
            line.setPlaceholderText("")
        self._refresh_dirty()

    def _field_is_valid(self, key: str) -> bool:
        text = self.lines[key].text().strip()
        if key not in NUMERIC_TEXT_FIELDS:
            return True
        if key in {"track", "disc"}:
            if not text:
                return True
            parts = text.split("/")
            return len(parts) <= 2 and all(part.isdigit() for part in parts)
        return not text or text.isdigit()

    def _refresh_dirty(self) -> None:
        if self._track is None and not self._multi_mode:
            self._dirty.clear()
            self._invalid.clear()
            self.pending_label.setText("No pending changes")
            self.pending_label.setStyleSheet("color: palette(mid);")
            self.save_button.setEnabled(False)
            self.revert_button.setEnabled(False)
            for widget in self.lines.values():
                widget.setStyleSheet("")
            return
        current = self.edits()
        invalid = {key for key in NUMERIC_TEXT_FIELDS if not self._field_is_valid(key)}
        self._invalid = invalid
        dirty: set[str] = set()
        if self._multi_mode:
            for key in FIELD_KEYS:
                base = self._multi_base.get(key, MIXED)
                value = current.get(key)
                if base is MIXED:
                    if isinstance(value, list):
                        if value:
                            dirty.add(key)
                    elif str(value or "").strip():
                        dirty.add(key)
                elif value != base:
                    dirty.add(key)
        else:
            for key, value in current.items():
                if value != self._baseline.get(key):
                    dirty.add(key)
        self._dirty = dirty
        for key, widget in self.lines.items():
            if key in invalid:
                widget.setStyleSheet("border: 1px solid #D9534F; background-color: #FFF0F0;")
            elif key in dirty:
                widget.setStyleSheet("border: 1px solid #D99A3D; background-color: #FFF7E6;")
            else:
                widget.setStyleSheet("")
        if invalid:
            self.pending_label.setText("Track and disc values must be numeric")
            self.pending_label.setStyleSheet("color: #C9302C; font-weight: 600;")
            self.save_button.setEnabled(False)
            self.revert_button.setEnabled(True)
        elif dirty:
            count = len(dirty)
            self.pending_label.setText(f"{count} pending change{'s' if count != 1 else ''}")
            self.pending_label.setStyleSheet("color: #B7791F; font-weight: 600;")
            self.save_button.setEnabled(True)
            self.revert_button.setEnabled(True)
        else:
            self.pending_label.setText("No pending changes")
            self.pending_label.setStyleSheet("color: palette(mid);")
            self.save_button.setEnabled(False)
            self.revert_button.setEnabled(False)

    def clear(self) -> None:
        self._loading = True
        self._track = None
        self._tags = None
        self._multi_mode = False
        self._multi_tracks = []
        self._multi_tags = []
        self._multi_base = {}
        for line in self.lines.values():
            line.clear()
            line.setPlaceholderText("")
            line.setFont(self._normal_font)
        self.set_artwork(QPixmap(), "No track selected")
        self._set_fields_enabled(False)
        self._loading = False
        self._refresh_dirty()

    def load_track(self, track: Track, tags: TagSet) -> None:
        self._loading = True
        self._track = track
        self._tags = tags
        self._multi_mode = False
        self._multi_tracks = []
        self._multi_tags = []
        values = self._values_from_tags(tags)
        for key in FIELD_KEYS:
            self._set_line(key, values[key])
        self.setEnabled(True)
        self._set_fields_enabled(True)
        self._baseline = self.edits()
        self._loading = False
        self._refresh_dirty()

    def load_multi(self, tracks: list[Track], tags_list: list[TagSet]) -> None:
        self._loading = True
        self._track = None
        self._tags = None
        self._multi_mode = True
        self._multi_tracks = list(tracks)
        self._multi_tags = list(tags_list)
        values = [self._values_from_tags(tags) for tags in tags_list]
        base: dict[str, object] = {}
        for key in FIELD_KEYS:
            field_values = [value[key] for value in values]
            if field_values and all(value == field_values[0] for value in field_values):
                base[key] = field_values[0]
                self._set_line(key, field_values[0])
            else:
                base[key] = MIXED
                self._set_line(key, "", mixed=True)
        self._multi_base = base
        self.setEnabled(True)
        self._set_fields_enabled(True)
        self._loading = False
        self._refresh_dirty()

    def set_artwork(self, pixmap: QPixmap, info: str) -> None:
        self._artwork_pixmap = pixmap
        self._render_artwork()
        self.artwork_info.setText(info)

    def edits(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, line in self.lines.items():
            if key in {"artists", "genres"}:
                result[key] = [part.strip() for part in line.text().split(",") if part.strip()]
            else:
                result[key] = line.text().strip()
        return result

    def pending_edits(self) -> dict[str, object]:
        current = self.edits()
        result: dict[str, object] = {key: current[key] for key in self._dirty if key in current}
        for key, total_key in (("track", "track_total"), ("disc", "disc_total")):
            text = str(result.get(key, "")).strip()
            if "/" in text:
                first, _, second = text.partition("/")
                result[key] = first
                if second:
                    result[total_key] = second
        return result

    @property
    def has_pending_changes(self) -> bool:
        return bool(self._dirty)

    @property
    def multi_mode(self) -> bool:
        return self._multi_mode

    def _emit_save(self) -> None:
        if (self._track is not None or self._multi_mode) and self._dirty and not self._invalid:
            self.save_requested.emit(self.pending_edits())

    def _revert(self) -> None:
        if self._multi_mode:
            self.load_multi(self._multi_tracks, self._multi_tags)
        elif self._track is not None and self._tags is not None:
            self.load_track(self._track, self._tags)
