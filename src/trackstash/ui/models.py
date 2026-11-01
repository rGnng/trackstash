"""Qt table model for the track list."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime

from PySide6.QtCore import (
    QAbstractListModel,
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from trackstash.core.db import AlbumRow, Track
from trackstash.core.metadata import read_artwork

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
    ("Added", "added"),
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
            value = track.date_added if column == "added" else getattr(track, column)
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
            if column == "added":
                if not track.date_added:
                    return ""
                return datetime.fromtimestamp(track.date_added).strftime("%Y-%m-%d %H:%M")
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


def _sort_key(track: Track, field: str) -> str | float | tuple[int, str]:
    value = track.date_added if field == "added" else getattr(track, field)
    if field in {"track", "disc"}:
        text = str(value or "")
        return (int(text) if text.isdigit() else 0, text)
    if field in {"bitrate", "duration", "added"}:
        return float(value or 0)
    if field == "year":
        return str(value)
    return str(value or "").casefold()


class _CoverSignals(QObject):
    loaded = Signal(str, bytes)
    failed = Signal(str)


class _CoverTask(QRunnable):
    def __init__(self, key: str, path: str, signals: _CoverSignals) -> None:
        super().__init__()
        self.key = key
        self.path = path
        self.signals = signals

    def _emit(self, name: str, *args: object) -> None:
        try:
            signal = getattr(self.signals, name)
            signal.emit(*args)
        except RuntimeError:
            pass

    def run(self) -> None:
        try:
            artworks = read_artwork(self.path)
            if artworks and artworks[0].data:
                self._emit("loaded", self.key, artworks[0].data)
            else:
                self._emit("failed", self.key)
        except Exception:
            self._emit("failed", self.key)


class AlbumGridModel(QAbstractListModel):
    """A virtualized album grid model with lazy artwork icons."""

    def __init__(self, albums: list[AlbumRow] | None = None) -> None:
        super().__init__()
        self._albums = albums or []
        self._icons: OrderedDict[str, QIcon] = OrderedDict()
        self._pending: set[str] = set()
        self._row_by_key: dict[str, int] = {}
        self._cover_size = 180
        self._cover_pool = QThreadPool.globalInstance()
        self._cover_pool.setMaxThreadCount(4)
        self._cover_signals = _CoverSignals()
        self._cover_signals.loaded.connect(self._cover_loaded, Qt.ConnectionType.QueuedConnection)
        self._cover_signals.failed.connect(self._cover_failed, Qt.ConnectionType.QueuedConnection)

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
        self._row_by_key = {self._key(album): row for row, album in enumerate(albums)}
        self.endResetModel()

    def set_cover_size(self, size: int) -> None:
        size = max(1, int(size))
        if size == self._cover_size:
            return
        self._cover_size = size
        self._icons.clear()

    def album_at(self, row: int) -> AlbumRow | None:
        if 0 <= row < len(self._albums):
            return self._albums[row]
        return None

    @staticmethod
    def _key(album: AlbumRow) -> str:
        return f"{album.id}:{album.artwork_checksum}:{album.artwork_song_path or ''}"

    def _store_icon(self, key: str, icon: QIcon) -> None:
        self._icons[key] = icon
        self._icons.move_to_end(key)
        while len(self._icons) > 256:
            self._icons.popitem(last=False)

    def _placeholder_icon(self, album: AlbumRow) -> QIcon:
        size = self._cover_size
        pixmap = QPixmap(size, size)
        color = QColor.fromHsv(abs(hash(album.id)) % 360, 90, 120)
        pixmap.fill(color)
        painter = QPainter(pixmap)
        painter.setPen(QColor("#F5F7FA"))
        font = painter.font()
        font.setPointSize(max(10, int(size * 0.23)))
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "♪")
        painter.end()
        return QIcon(pixmap)

    def _icon(self, album: AlbumRow) -> QIcon:
        key = self._key(album)
        cached = self._icons.get(key)
        if cached is not None:
            self._icons.move_to_end(key)
            return cached
        icon = self._placeholder_icon(album)
        self._store_icon(key, icon)
        if album.artwork_song_path and key not in self._pending:
            self._pending.add(key)
            self._cover_pool.start(_CoverTask(key, album.artwork_song_path, self._cover_signals))
        return icon

    def _cover_loaded(self, key: str, data: bytes) -> None:
        self._pending.discard(key)
        source = QPixmap()
        if not source.loadFromData(data) or source.isNull():
            return
        pixmap = source.scaled(
            self._cover_size,
            self._cover_size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._store_icon(key, QIcon(pixmap))
        row = self._row_by_key.get(key)
        if row is not None and 0 <= row < len(self._albums):
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])

    def _cover_failed(self, key: str) -> None:
        self._pending.discard(key)
