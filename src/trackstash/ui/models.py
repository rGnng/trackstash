"""Qt table model for the track list."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel,
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from trackstash.core.db import AlbumRow, Track

COLUMNS: tuple[tuple[str, str], ...] = (
    ("Title", "title"),
    ("Artist", "artist"),
    ("Album Artist", "album_artist"),
    ("Album", "album"),
    ("Year", "year"),
    ("Track", "track"),
    ("Disc", "disc"),
    ("Genre", "genre"),
    ("Format", "format"),
    ("Codec", "codec"),
    ("Bitrate", "bitrate"),
    ("Duration", "duration"),
    ("Path", "path"),
)


def _duration_text(seconds: float) -> str:
    total = round(seconds)
    return f"{total // 60}:{total % 60:02d}"


class TrackTableModel(QAbstractTableModel):
    """A sortable, read-only track table backed by a list of Track rows."""

    def __init__(self, tracks: list[Track] | None = None) -> None:
        super().__init__()
        self._tracks = tracks or []
        self._sort_column = 2
        self._sort_order = Qt.SortOrder.AscendingOrder

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._tracks)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(COLUMNS)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or not (0 <= index.row() < len(self._tracks)):
            return None
        track = self._tracks[index.row()]
        column = COLUMNS[index.column()][1]
        if role == Qt.ItemDataRole.DisplayRole:
            value = getattr(track, column)
            if column == "track":
                return (
                    f"{track.track}/{track.track_total}" if track.track_total else str(track.track)
                )
            if column == "disc":
                return f"{track.disc}/{track.disc_total}" if track.disc_total else str(track.disc)
            if column == "bitrate":
                return f"{track.bitrate} Kbps" if track.bitrate else ""
            if column == "duration":
                return _duration_text(track.duration)
            return str(value or "")
        if role == Qt.ItemDataRole.ToolTipRole:
            return track.path
        if role == Qt.ItemDataRole.TextAlignmentRole and column in {
            "track",
            "disc",
            "bitrate",
            "duration",
        }:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section][0]
        return section + 1

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        if not COLUMNS:
            return
        self._sort_column = column
        self._sort_order = order
        field = COLUMNS[column][1]
        self.layoutAboutToBeChanged.emit()
        self._tracks.sort(
            key=lambda track: _sort_key(track, field),
            reverse=order == Qt.SortOrder.DescendingOrder,
        )
        self.layoutChanged.emit()

    def set_tracks(self, tracks: list[Track]) -> None:
        self.beginResetModel()
        self._tracks = tracks
        self.endResetModel()
        self.sort(self._sort_column, self._sort_order)

    def track_at(self, row: int) -> Track | None:
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    @property
    def tracks(self) -> list[Track]:
        return self._tracks


def _sort_key(track: Track, field: str) -> str | float:
    value = getattr(track, field)
    if field in {"track", "disc", "bitrate", "duration", "year"}:
        if field == "year":
            return str(value)
        return float(value or 0)
    return str(value or "").casefold()


class AlbumGridModel(QAbstractListModel):
    """A virtualized album grid model with lazy artwork icons."""

    def __init__(self, albums: list[AlbumRow] | None = None) -> None:
        super().__init__()
        self._albums = albums or []
        self._icons: dict[str, QIcon] = {}

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._albums)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or not (0 <= index.row() < len(self._albums)):
            return None
        album = self._albums[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{album.title}\n{album.artist}"
        if role == Qt.ItemDataRole.DecorationRole:
            return self._icon(album)
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{album.title}\n{album.artist}\n{album.track_count} tracks"
        if role == Qt.ItemDataRole.UserRole:
            return album.id
        return None

    def set_albums(self, albums: list[AlbumRow]) -> None:
        self.beginResetModel()
        self._albums = albums
        self._icons.clear()
        self.endResetModel()

    def album_at(self, row: int) -> AlbumRow | None:
        if 0 <= row < len(self._albums):
            return self._albums[row]
        return None

    def _icon(self, album: AlbumRow) -> QIcon:
        cached = self._icons.get(album.id)
        if cached is not None:
            return cached
        pixmap = QPixmap(180, 180)
        if album.artwork_path:
            source = QPixmap(album.artwork_path)
            if not source.isNull():
                pixmap = source.scaled(
                    180,
                    180,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
        if pixmap.isNull() or album.artwork_path is None:
            pixmap = QPixmap(180, 180)
            color = QColor.fromHsv(abs(hash(album.id)) % 360, 90, 120)
            pixmap.fill(color)
            painter = QPainter(pixmap)
            painter.setPen(QColor("#F5F7FA"))
            font = painter.font()
            font.setPointSize(42)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "♪")
            painter.end()
        icon = QIcon(pixmap)
        self._icons[album.id] = icon
        return icon
