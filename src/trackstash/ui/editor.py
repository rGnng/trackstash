"""Left-side media information and inline tag editor."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from trackstash.core.db import Track
from trackstash.core.metadata import TagSet


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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.save_button = QPushButton("Save Changes", self)
        self.save_button.clicked.connect(self._emit_save)
        self.revert_button = QPushButton("Revert", self)
        self.revert_button.clicked.connect(self._revert)
        save_row = QHBoxLayout()
        save_row.addWidget(self.save_button)
        save_row.addWidget(self.revert_button)
        save_row.addStretch(1)
        layout.addLayout(save_row)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)

        self.artwork = QLabel(body)
        self.artwork.setFixedSize(260, 260)
        self.artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork.setStyleSheet("border: 1px solid palette(mid);")
        self.artwork.setText("No artwork")
        body_layout.addWidget(self.artwork, 0, Qt.AlignmentFlag.AlignHCenter)
        self.artwork_info = QLabel("", body)
        self.artwork_info.setWordWrap(True)
        self.artwork_info.setStyleSheet("color: palette(mid);")
        body_layout.addWidget(self.artwork_info)

        self.form = QFormLayout()
        self.lines: dict[str, QLineEdit] = {}
        self.spins: dict[str, QSpinBox] = {}
        for key, label in (
            ("title", "Title"),
            ("artists", "Artist"),
            ("album", "Album"),
            ("album_artist", "Album artist"),
            ("genres", "Genre"),
            ("year", "Year"),
            ("comment", "Comment"),
            ("composer", "Composer"),
            ("bpm", "BPM"),
            ("musical_key", "Key"),
            ("isrc", "ISRC"),
            ("label", "Label"),
            ("catalog_number", "Catalog"),
        ):
            line = QLineEdit(body)
            line.setClearButtonEnabled(True)
            self.lines[key] = line
            self.form.addRow(label, line)
        for key, label in (
            ("track", "Track"),
            ("track_total", "Track total"),
            ("disc", "Disc"),
            ("disc_total", "Disc total"),
        ):
            spin = QSpinBox(body)
            spin.setRange(0, 9999)
            self.spins[key] = spin
            self.form.addRow(label, spin)
        self.compilation = QCheckBox("Compilation", body)
        self.form.addRow("", self.compilation)
        body_layout.addLayout(self.form)

        technical = QFormLayout()
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

        artwork_buttons = QHBoxLayout()
        cover = QPushButton("Cover…", body)
        cover.clicked.connect(self.cover_requested)
        remove = QPushButton("Remove", body)
        remove.clicked.connect(self.remove_cover_requested)
        extract = QPushButton("Extract…", body)
        extract.clicked.connect(self.extract_cover_requested)
        reveal = QPushButton("Reveal", body)
        reveal.clicked.connect(self.reveal_requested)
        artwork_buttons.addWidget(cover)
        artwork_buttons.addWidget(remove)
        artwork_buttons.addWidget(extract)
        artwork_buttons.addWidget(reveal)
        body_layout.addLayout(artwork_buttons)
        body_layout.addStretch(1)

        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.setEnabled(False)
        self._set_fields_enabled(False)

    def _set_fields_enabled(self, enabled: bool) -> None:
        for widget in (*self.lines.values(), *self.spins.values(), self.compilation):
            widget.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        self.revert_button.setEnabled(enabled)
        for button in self.findChildren(QPushButton):
            if button.text() in {"Cover…", "Remove", "Extract…", "Reveal"}:
                button.setEnabled(enabled)

    def clear(self) -> None:
        self._track = None
        self._tags = None
        for line in self.lines.values():
            line.clear()
        for spin in self.spins.values():
            spin.setValue(0)
        self.compilation.setChecked(False)
        for label in self.technical.values():
            label.clear()
        self.set_artwork(QPixmap(), "No track selected")
        self._set_fields_enabled(False)

    def set_multi(self, count: int) -> None:
        self._track = None
        self._tags = None
        for line in self.lines.values():
            line.clear()
        for spin in self.spins.values():
            spin.setValue(0)
        self.compilation.setChecked(False)
        for label in self.technical.values():
            label.clear()
        self.set_artwork(QPixmap(), "Use Edit → Edit Tags… for batch changes.")
        self._set_fields_enabled(False)

    def load_track(self, track: Track, tags: TagSet) -> None:
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
        for key, spin in self.spins.items():
            spin.setValue(int(getattr(tags, key) or 0))
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

    def set_artwork(self, pixmap: QPixmap, info: str) -> None:
        if pixmap.isNull():
            self.artwork.setPixmap(QPixmap())
            self.artwork.setText("No artwork")
        else:
            self.artwork.setPixmap(
                pixmap.scaled(
                    260,
                    260,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.artwork.setText("")
        self.artwork_info.setText(info)

    def edits(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, line in self.lines.items():
            if key in {"artists", "genres"}:
                result[key] = [part.strip() for part in line.text().split(",") if part.strip()]
            else:
                result[key] = line.text().strip()
        for key, spin in self.spins.items():
            result[key] = spin.value()
        result["compilation"] = self.compilation.isChecked()
        return result

    def _emit_save(self) -> None:
        if self._track is not None:
            self.save_requested.emit(self.edits())

    def _revert(self) -> None:
        if self._track is not None and self._tags is not None:
            self.load_track(self._track, self._tags)
