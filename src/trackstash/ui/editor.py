"""Left-side media information and inline tag editor."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFont, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
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
        self.setObjectName("trackInfoEditor")
        self.setStyleSheet("#trackInfoEditor { background-color: palette(base); }")
        self._track: Track | None = None
        self._tags: TagSet | None = None
        self._multi_mode = False
        self._multi_tracks: list[Track] = []
        self._multi_tags: list[TagSet] = []
        self._multi_base: dict[str, object] = {}
        self._baseline: dict[str, object] = {}
        self._dirty: set[str] = set()
        self._loading = False
        self._artwork_pixmap = QPixmap()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.save_button = QPushButton("Save Changes", self)
        self.save_button.clicked.connect(self._emit_save)
        self.revert_button = QPushButton("Revert", self)
        self.revert_button.clicked.connect(self._revert)
        self.pending_label = QLabel("", self)
        self.pending_label.setStyleSheet("color: palette(text);")
        scroll = QScrollArea(self)
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().installEventFilter(self)
        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(4)

        self.artwork = QLabel(body)
        self.artwork.setMinimumSize(1, 1)
        self.artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork.setStyleSheet(
            "border: 1px solid #3A4554; background-color: #1B212B; color: #AAB4C3;"
        )
        self.artwork.setText("No artwork")
        body_layout.addWidget(self.artwork)
        self.artwork_info = QLabel("", body)
        self.artwork_info.setWordWrap(True)
        self.artwork_info.setStyleSheet("color: palette(text);")
        body_layout.addWidget(self.artwork_info)

        self.lines: dict[str, QLineEdit] = {}
        self.labels: dict[str, QLabel] = {}
        fields_host = QWidget(body)
        fields_layout = QVBoxLayout(fields_host)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(4)

        def make_block(key: str, label: str) -> QWidget:
            block = QWidget(fields_host)
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(0, 0, 0, 0)
            block_layout.setSpacing(1)
            caption = QLabel(label, block)
            caption.setStyleSheet("font-size: 11px;")
            self.labels[key] = caption
            line = QLineEdit(block)
            line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            line.textEdited.connect(lambda _text, field=key: self._field_changed(field))
            block_layout.addWidget(caption)
            block_layout.addWidget(line)
            self.lines[key] = line
            return block

        def add_full(key: str, label: str) -> None:
            fields_layout.addWidget(make_block(key, label))

        def add_row(specs: tuple[tuple[str, str], ...]) -> None:
            row = QHBoxLayout()
            row.setSpacing(4)
            for key, label in specs:
                row.addWidget(make_block(key, label), 1)
            fields_layout.addLayout(row)

        add_full("title", "Title")
        add_full("artists", "Artist")
        add_full("album", "Album")
        add_full("album_artist", "Album Artist")
        add_row((("genres", "Genre"), ("year", "Year")))
        add_row(
            (
                ("track", "Track"),
                ("track_total", "Track Total"),
                ("disc", "Disc"),
                ("disc_total", "Disc Total"),
            )
        )
        add_full("comment", "Comment")
        add_row(
            (
                ("composer", "Composer"),
                ("bpm", "BPM"),
                ("musical_key", "Key"),
            )
        )
        self._normal_font = QFont(self.lines["title"].font())
        self._italic_font = QFont(self._normal_font)
        self._italic_font.setItalic(True)
        body_layout.addWidget(fields_host)
        body_layout.addStretch(1)

        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        save_row = QHBoxLayout()
        save_row.addWidget(self.save_button)
        save_row.addWidget(self.revert_button)
        save_row.addWidget(self.pending_label, 1)
        layout.addLayout(save_row)
        self.setEnabled(False)
        self._set_fields_enabled(False)
        self._refresh_dirty()

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._update_artwork_size()
        super().resizeEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            hasattr(self, "_scroll")
            and watched is self._scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._update_artwork_size()
        return super().eventFilter(watched, event)

    def _update_artwork_size(self) -> None:
        if not hasattr(self, "artwork"):
            return
        viewport = self._scroll.viewport().width()
        width = max(1, viewport if viewport > 1 else self.width() - 8)
        if self.artwork.width() != width:
            self.artwork.setFixedSize(width, width)
            self._render_artwork()

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
            "track": tags.track,
            "track_total": tags.track_total,
            "disc": tags.disc,
            "disc_total": tags.disc_total,
            "comment": tags.comment,
            "composer": tags.composer,
            "bpm": tags.bpm,
            "musical_key": tags.musical_key,
        }

    def _field_changed(self, field: str) -> None:
        if self._loading:
            return
        line = self.lines.get(field)
        if line is not None and line.text():
            line.setFont(self._normal_font)
            line.setPlaceholderText("")
        self._refresh_dirty()

    def _refresh_dirty(self) -> None:
        if self._track is None and not self._multi_mode:
            self._dirty.clear()
            self.pending_label.setText("")
            self.pending_label.setStyleSheet("color: palette(text);")
            self.save_button.setEnabled(False)
            self.revert_button.setEnabled(False)
            for widget in self.lines.values():
                widget.setStyleSheet("")
            for label in self.labels.values():
                label.setStyleSheet("font-size: 11px;")
            return
        current = self.edits()
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
            caption = self.labels.get(key)
            if key in dirty:
                widget.setStyleSheet("border: 1px solid #D99A3D;")
                if caption is not None:
                    caption.setStyleSheet("font-size: 11px; color: #D99A3D; font-weight: 600;")
            else:
                widget.setStyleSheet("")
                if caption is not None:
                    caption.setStyleSheet("font-size: 11px;")
        if dirty:
            count = len(dirty)
            self.pending_label.setText(f"{count} pending change{'s' if count != 1 else ''}")
            self.pending_label.setStyleSheet("color: #D99A3D; font-weight: 600;")
            self.save_button.setEnabled(True)
            self.revert_button.setEnabled(True)
        else:
            self.pending_label.setText("")
            self.pending_label.setStyleSheet("color: palette(text);")
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
        if (self._track is not None or self._multi_mode) and self._dirty:
            self.save_requested.emit(self.pending_edits())

    def _revert(self) -> None:
        if self._multi_mode:
            self.load_multi(self._multi_tracks, self._multi_tags)
        elif self._track is not None and self._tags is not None:
            self.load_track(self._track, self._tags)
