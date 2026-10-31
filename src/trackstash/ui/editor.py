"""Left-side media information and inline tag editor."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
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


class TrackInfoEditor(QWidget):
    """Displays and edits the selected track's tags and artwork."""

    save_requested = Signal(dict)
    cover_requested = Signal()
    remove_cover_requested = Signal()
    extract_cover_requested = Signal()
    reveal_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._track: Track | None = None
        self._tags: TagSet | None = None
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
        self.compilation = QCheckBox("Compilation", body)
        self.compilation.stateChanged.connect(lambda _state: self._field_changed("compilation"))
        self.form.addRow("", self.compilation)
        body_layout.addLayout(self.form)

        technical = QFormLayout()
        technical.setVerticalSpacing(4)
        self.technical: dict[str, QLabel] = {}
        for key, label in (
            ("format", "Format"),
            ("codec", "Codec"),
            ("bitrate", "Bitrate"),
            ("sample_rate", "Sample rate"),
            ("duration", "Duration"),
            ("path", "File"),
        ):
            value = QLabel("", body)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.technical[key] = value
            technical.addRow(label, value)
        body_layout.addLayout(technical)
        body_layout.addStretch(1)

        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.setEnabled(False)
        self._set_fields_enabled(False)
        self._refresh_dirty()

    def resizeEvent(self, event: QResizeEvent) -> None:
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
        for widget in (*self.lines.values(), self.compilation):
            widget.setEnabled(enabled)
        self.save_button.setEnabled(False)
        self.revert_button.setEnabled(False)

    def _reset_pending(self) -> None:
        self._baseline = self.edits() if self._track is not None else {}
        self._dirty.clear()
        self._invalid.clear()
        self._refresh_dirty()

    def _field_changed(self, _field: str) -> None:
        if not self._loading:
            self._refresh_dirty()

    def _field_is_numeric(self, key: str) -> bool:
        text = self.lines[key].text().strip()
        return not text or text.isdigit()

    def _refresh_dirty(self) -> None:
        if self._track is None:
            self._dirty.clear()
            self._invalid.clear()
            self.pending_label.setText("No pending changes")
            self.pending_label.setStyleSheet("color: palette(mid);")
            self.save_button.setEnabled(False)
            self.revert_button.setEnabled(False)
            for widget in self.lines.values():
                widget.setStyleSheet("")
            self.compilation.setStyleSheet("")
            return
        current = self.edits()
        invalid = {key for key in NUMERIC_TEXT_FIELDS if not self._field_is_numeric(key)}
        self._invalid = invalid
        dirty = {key for key, value in current.items() if value != self._baseline.get(key)}
        self._dirty = dirty
        for key, widget in self.lines.items():
            if key in invalid:
                widget.setStyleSheet("border: 1px solid #D9534F; background-color: #FFF0F0;")
            elif key in dirty:
                widget.setStyleSheet("border: 1px solid #D99A3D; background-color: #FFF7E6;")
            else:
                widget.setStyleSheet("")
        self.compilation.setStyleSheet(
            "font-weight: 600; color: #B7791F;" if "compilation" in dirty else ""
        )
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
        for line in self.lines.values():
            line.clear()
        self.compilation.setChecked(False)
        for label in self.technical.values():
            label.clear()
        self.set_artwork(QPixmap(), "No track selected")
        self._set_fields_enabled(False)
        self._loading = False
        self._refresh_dirty()

    def set_multi(self, count: int) -> None:
        self._loading = True
        self._track = None
        self._tags = None
        for line in self.lines.values():
            line.clear()
        self.compilation.setChecked(False)
        for label in self.technical.values():
            label.clear()
        self.set_artwork(
            QPixmap(),
            f"{count} tracks selected. Use Edit → Edit Tags… for batch changes.",
        )
        self._set_fields_enabled(False)
        self._loading = False
        self._refresh_dirty()

    def load_track(self, track: Track, tags: TagSet) -> None:
        self._loading = True
        self._track = track
        self._tags = tags
        self.lines["title"].setText(tags.title)
        self.lines["artists"].setText(", ".join(tags.artists))
        self.lines["album"].setText(tags.album)
        self.lines["album_artist"].setText(tags.album_artist)
        self.lines["genres"].setText(", ".join(tags.genres))
        self.lines["year"].setText(tags.year)
        self.lines["comment"].setText(tags.comment)
        self.lines["composer"].setText(tags.composer)
        self.lines["bpm"].setText(tags.bpm)
        self.lines["musical_key"].setText(tags.musical_key)
        self.lines["isrc"].setText(tags.isrc)
        self.lines["label"].setText(tags.label)
        self.lines["catalog_number"].setText(tags.catalog_number)
        for key in NUMERIC_TEXT_FIELDS:
            value = getattr(tags, key) or 0
            self.lines[key].setText(str(value) if value else "")
        self.compilation.setChecked(tags.compilation)
        self.technical["format"].setText(track.format)
        self.technical["codec"].setText(track.codec)
        self.technical["bitrate"].setText(f"{track.bitrate} Kbps" if track.bitrate else "—")
        self.technical["sample_rate"].setText(
            f"{track.sample_rate} Hz" if track.sample_rate else "—"
        )
        minutes = int(track.duration // 60)
        seconds = round(track.duration % 60)
        self.technical["duration"].setText(f"{minutes}:{seconds:02d}")
        self.technical["path"].setText(track.path)
        self.setEnabled(True)
        self._set_fields_enabled(True)
        self._loading = False
        self._reset_pending()

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
        result["compilation"] = self.compilation.isChecked()
        return result

    def pending_edits(self) -> dict[str, object]:
        current = self.edits()
        return {key: current[key] for key in self._dirty if key in current}

    @property
    def has_pending_changes(self) -> bool:
        return bool(self._dirty)

    def _emit_save(self) -> None:
        if self._track is not None and self._dirty and not self._invalid:
            self.save_requested.emit(self.pending_edits())

    def _revert(self) -> None:
        if self._track is not None and self._tags is not None:
            self.load_track(self._track, self._tags)
