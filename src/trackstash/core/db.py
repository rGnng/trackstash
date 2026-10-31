"""SQLite storage for the TrackStash managed library."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trackstash.core.identity import (
    album_uuid,
    artist_uuid,
    canonical_path,
    library_uuid,
    normalize_identifier,
    relative_path,
    song_uuid,
    stable_uuid,
)
from trackstash.core.metadata import TagSet, TrackMetadata

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS libraries (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'managed',
    name TEXT NOT NULL,
    identifier TEXT NOT NULL DEFAULT '',
    id_namespace TEXT NOT NULL DEFAULT '',
    date_added REAL NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_libraries_identifier
    ON libraries(identifier COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS artists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS albums (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    artist_id TEXT NOT NULL,
    genre TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '',
    artwork BLOB,
    UNIQUE(title, artist_id)
);

CREATE TABLE IF NOT EXISTS songs (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    library_id TEXT,
    title TEXT NOT NULL,
    artist_id TEXT NOT NULL,
    album_id TEXT NOT NULL,
    genre TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '',
    track INTEGER NOT NULL DEFAULT 0,
    track_total INTEGER NOT NULL DEFAULT 0,
    disc INTEGER NOT NULL DEFAULT 0,
    disc_total INTEGER NOT NULL DEFAULT 0,
    comments TEXT NOT NULL DEFAULT '',
    duration REAL NOT NULL DEFAULT 0,
    date_added REAL NOT NULL,
    play_count INTEGER NOT NULL DEFAULT 0,
    rating INTEGER NOT NULL DEFAULT 0,
    loved INTEGER NOT NULL DEFAULT 0,
    last_played REAL,
    skip_count INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL DEFAULT 0,
    file_size INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_songs_album ON songs(album_id);
CREATE INDEX IF NOT EXISTS idx_songs_artist ON songs(artist_id);
CREATE INDEX IF NOT EXISTS idx_songs_library ON songs(library_id);

CREATE TABLE IF NOT EXISTS ts_song_tags (
    song_id TEXT PRIMARY KEY REFERENCES songs(id) ON DELETE CASCADE,
    album_artist TEXT NOT NULL DEFAULT '',
    composer TEXT NOT NULL DEFAULT '',
    lyricist TEXT NOT NULL DEFAULT '',
    lyrics TEXT NOT NULL DEFAULT '',
    isrc TEXT NOT NULL DEFAULT '',
    bpm TEXT NOT NULL DEFAULT '',
    musical_key TEXT NOT NULL DEFAULT '',
    compilation INTEGER NOT NULL DEFAULT 0,
    sort_title TEXT NOT NULL DEFAULT '',
    sort_artist TEXT NOT NULL DEFAULT '',
    sort_album_artist TEXT NOT NULL DEFAULT '',
    sort_album TEXT NOT NULL DEFAULT '',
    musicbrainz_recording_id TEXT NOT NULL DEFAULT '',
    musicbrainz_release_id TEXT NOT NULL DEFAULT '',
    musicbrainz_artist_id TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    catalog_number TEXT NOT NULL DEFAULT '',
    barcode TEXT NOT NULL DEFAULT '',
    release_country TEXT NOT NULL DEFAULT '',
    media TEXT NOT NULL DEFAULT '',
    script TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    conductor TEXT NOT NULL DEFAULT '',
    orchestra TEXT NOT NULL DEFAULT '',
    ensemble TEXT NOT NULL DEFAULT '',
    work TEXT NOT NULL DEFAULT '',
    movement TEXT NOT NULL DEFAULT '',
    movement_number TEXT NOT NULL DEFAULT '',
    original_date TEXT NOT NULL DEFAULT '',
    replaygain_track_gain TEXT NOT NULL DEFAULT '',
    replaygain_track_peak TEXT NOT NULL DEFAULT '',
    replaygain_album_gain TEXT NOT NULL DEFAULT '',
    replaygain_album_peak TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ts_audio_properties (
    song_id TEXT PRIMARY KEY REFERENCES songs(id) ON DELETE CASCADE,
    format TEXT NOT NULL DEFAULT '',
    codec TEXT NOT NULL DEFAULT '',
    bitrate INTEGER NOT NULL DEFAULT 0,
    sample_rate INTEGER NOT NULL DEFAULT 0,
    channels INTEGER NOT NULL DEFAULT 0,
    bit_depth INTEGER NOT NULL DEFAULT 0,
    lossless INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ts_file_state (
    song_id TEXT PRIMARY KEY REFERENCES songs(id) ON DELETE CASCADE,
    content_hash TEXT,
    hash_state TEXT NOT NULL DEFAULT '',
    last_scan REAL NOT NULL DEFAULT 0,
    scan_error TEXT NOT NULL DEFAULT '',
    offline INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ts_tag_value (
    song_id TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    field_key TEXT NOT NULL,
    position INTEGER NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (song_id, field_key, position)
);

CREATE TABLE IF NOT EXISTS ts_artwork (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'front',
    mime TEXT NOT NULL DEFAULT '',
    width INTEGER,
    height INTEGER,
    checksum TEXT NOT NULL DEFAULT '',
    cache_path TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ts_artwork_song ON ts_artwork(song_id);

CREATE TABLE IF NOT EXISTS ts_operations (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    dry_run INTEGER NOT NULL DEFAULT 0,
    undoable INTEGER NOT NULL DEFAULT 1,
    undone INTEGER NOT NULL DEFAULT 0,
    started_at REAL NOT NULL,
    finished_at REAL
);

CREATE TABLE IF NOT EXISTS ts_operation_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL REFERENCES ts_operations(id) ON DELETE CASCADE,
    song_id TEXT,
    path TEXT NOT NULL DEFAULT '',
    prior_json TEXT,
    result_json TEXT,
    error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ts_operation_items_op
    ON ts_operation_items(operation_id);

CREATE TABLE IF NOT EXISTS ts_saved_views (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    query_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ts_presets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    values_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ts_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS ts_track_fts USING fts5(
    song_id UNINDEXED,
    title,
    artist,
    album_artist,
    album,
    genre,
    comment,
    path,
    tokenize = 'unicode61'
);
"""


@dataclass(slots=True)
class Library:
    """A managed library root."""

    id: str
    path: str
    name: str
    identifier: str
    id_namespace: str
    date_added: float
    enabled: bool
    kind: str = "managed"


@dataclass(slots=True)
class Track:
    """A flattened song row used by views and services."""

    id: str
    path: str
    library_id: str | None
    title: str
    artist: str
    album_artist: str
    album: str
    genre: str
    year: str
    track: int
    track_total: int
    disc: int
    disc_total: int
    comment: str
    duration: float
    date_added: float
    play_count: int
    rating: int
    loved: bool
    last_played: float | None
    skip_count: int
    mtime: float
    file_size: int
    format: str
    bitrate: int
    sample_rate: int
    channels: int
    bit_depth: int
    lossless: bool
    artwork_path: str | None
    album_id: str


@dataclass(slots=True)
class Operation:
    """An operation journal entry."""

    id: str
    kind: str
    status: str
    summary: str
    dry_run: bool
    undoable: bool
    undone: bool
    started_at: float
    finished_at: float | None


def _now() -> float:
    return time.time()


def _row_to_library(row: sqlite3.Row) -> Library:
    return Library(
        id=row["id"],
        path=row["path"],
        name=row["name"],
        identifier=row["identifier"],
        id_namespace=row["id_namespace"],
        date_added=float(row["date_added"]),
        enabled=bool(row["enabled"]),
        kind=row["kind"],
    )


def _row_to_track(row: sqlite3.Row) -> Track:
    return Track(
        id=row["id"],
        path=row["path"],
        library_id=row["library_id"],
        title=row["title"],
        artist=row["artist"],
        album_artist=row["album_artist"],
        album=row["album"],
        genre=row["genre"],
        year=row["year"],
        track=int(row["track"]),
        track_total=int(row["track_total"]),
        disc=int(row["disc"]),
        disc_total=int(row["disc_total"]),
        comment=row["comments"],
        duration=float(row["duration"]),
        date_added=float(row["date_added"]),
        play_count=int(row["play_count"]),
        rating=int(row["rating"]),
        loved=bool(row["loved"]),
        last_played=float(row["last_played"]) if row["last_played"] is not None else None,
        skip_count=int(row["skip_count"]),
        mtime=float(row["mtime"]),
        file_size=int(row["file_size"]),
        format=row["format"] or "",
        bitrate=int(row["bitrate"] or 0),
        sample_rate=int(row["sample_rate"] or 0),
        channels=int(row["channels"] or 0),
        bit_depth=int(row["bit_depth"] or 0),
        lossless=bool(row["lossless"]),
        artwork_path=row["artwork_path"],
        album_id=row["album_id"],
    )


class Database:
    """Thin SQLite DAO for Tracks-compatible library tables."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(Path(path).expanduser())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            try:
                connection.execute("BEGIN")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def ensure_schema(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA_SQL)
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current < SCHEMA_VERSION:
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()

    # ------------------------------------------------------------------
    # Libraries

    def add_library(
        self, root: str | Path, *, name: str | None = None, identifier: str | None = None
    ) -> Library:
        root_path = canonical_path(str(root))
        if not Path(root_path).is_dir():
            raise ValueError(f"Library folder does not exist: {root_path}")
        if not identifier:
            with self.connect() as connection:
                identifiers = {
                    row["identifier"].lower()
                    for row in connection.execute("SELECT identifier FROM libraries")
                }
            number = 1
            while f"library{number}" in identifiers:
                number += 1
            identifier = f"library{number}"
        identifier = identifier.strip()
        namespace = normalize_identifier(identifier)
        if not namespace:
            raise ValueError("Library identifier must not be empty")

        library_id = library_uuid(root_path)
        library_name = name or Path(root_path).name or "Music"
        with self.transaction() as connection:
            for row in connection.execute("SELECT identifier, id_namespace FROM libraries"):
                if row["identifier"].lower() == namespace or row["id_namespace"] == namespace:
                    raise ValueError(f"Library identifier is already in use: {identifier}")
            connection.execute(
                "INSERT INTO libraries"
                "(id, path, kind, name, identifier, id_namespace, date_added, enabled)"
                " VALUES(?, ?, 'managed', ?, ?, ?, ?, 1)",
                (library_id, root_path, library_name, identifier, namespace, _now()),
            )
            row = connection.execute(
                "SELECT * FROM libraries WHERE id = ?", (library_id,)
            ).fetchone()
        return _row_to_library(row)

    def list_libraries(self) -> list[Library]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM libraries ORDER BY name COLLATE NOCASE, path"
            ).fetchall()
        return [_row_to_library(row) for row in rows]

    def get_library(self, library_id: str) -> Library | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM libraries WHERE id = ?", (library_id,)
            ).fetchone()
        return _row_to_library(row) if row else None

    def get_library_by_path(self, path: str | Path) -> Library | None:
        root = canonical_path(str(path))
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM libraries WHERE path = ?", (root,)).fetchone()
        return _row_to_library(row) if row else None

    def set_library_enabled(self, library_id: str, enabled: bool) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE libraries SET enabled = ? WHERE id = ?", (int(enabled), library_id)
            )

    def remove_library(self, library_id: str) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM songs WHERE library_id = ?", (library_id,))
            connection.execute("DELETE FROM libraries WHERE id = ?", (library_id,))
            self._cleanup_orphans(connection)

    def library_track_count(self, library_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM songs WHERE library_id = ?", (library_id,)
            ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Tracks and metadata

    def _ensure_artist(self, connection: sqlite3.Connection, name: str) -> str:
        clean_name = name.strip() or "Unknown Artist"
        fallback = artist_uuid(clean_name)
        connection.execute(
            "INSERT OR IGNORE INTO artists(id, name) VALUES(?, ?)",
            (fallback, clean_name),
        )
        row = connection.execute("SELECT id FROM artists WHERE name = ?", (clean_name,)).fetchone()
        return str(row["id"]) if row else fallback

    def _ensure_album(
        self,
        connection: sqlite3.Connection,
        title: str,
        artist_id: str,
        genre: str,
        year: str,
    ) -> str:
        clean_title = title.strip() or "Unknown Album"
        fallback = album_uuid(artist_id, clean_title)
        connection.execute(
            "INSERT INTO albums(id, title, artist_id, genre, year, artwork)"
            " VALUES(?, ?, ?, ?, ?, NULL)"
            " ON CONFLICT DO UPDATE SET genre = excluded.genre, year = excluded.year",
            (fallback, clean_title, artist_id, genre, year),
        )
        row = connection.execute(
            "SELECT id FROM albums WHERE title = ? AND artist_id = ?",
            (clean_title, artist_id),
        ).fetchone()
        return str(row["id"]) if row else fallback

    def _track_values(
        self, metadata: TrackMetadata, library: Library
    ) -> tuple[str, str, str, str, str]:
        tags = metadata.tags
        artist_name = tags.primary_artist
        album_artist_name = tags.album_artist_or_primary
        album_title = tags.album.strip() or "Unknown Album"
        rel = relative_path(metadata.path, library.path)
        song_id = (
            song_uuid(library.id_namespace, rel)
            if rel is not None
            else stable_uuid(canonical_path(metadata.path))
        )
        return song_id, artist_name, album_artist_name, album_title, tags.primary_genre

    def upsert_tracks(
        self, metadata_list: Sequence[TrackMetadata], library: Library
    ) -> list[Track]:
        """Insert or update tracks, preserving user-owned columns."""
        if not metadata_list:
            return []
        now = _now()
        written_ids: list[str] = []
        with self.transaction() as connection:
            for metadata in metadata_list:
                tags = metadata.tags
                song_id, artist_name, album_artist_name, album_title, genre = self._track_values(
                    metadata, library
                )
                artist_id = self._ensure_artist(connection, artist_name)
                album_artist_id = self._ensure_artist(connection, album_artist_name)
                album_id = self._ensure_album(
                    connection, album_title, album_artist_id, genre, tags.year
                )
                path_value = canonical_path(metadata.path)
                existing = connection.execute(
                    "SELECT id, date_added FROM songs WHERE path = ?", (path_value,)
                ).fetchone()
                if existing is None:
                    date_added = metadata.mtime if metadata.mtime > 0 else now
                else:
                    date_added = float(existing["date_added"])
                    old_id = str(existing["id"])
                    if old_id != song_id:
                        self._remap_song_id(connection, old_id, song_id, path_value)

                connection.execute(
                    "INSERT INTO songs"
                    "(id, path, library_id, title, artist_id, album_id, genre, year,"
                    " track, track_total, disc, disc_total, comments, duration,"
                    " date_added, mtime, file_size)"
                    " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(path) DO UPDATE SET"
                    " id = excluded.id, library_id = excluded.library_id,"
                    " title = excluded.title, artist_id = excluded.artist_id,"
                    " album_id = excluded.album_id, genre = excluded.genre,"
                    " year = excluded.year, track = excluded.track,"
                    " track_total = excluded.track_total, disc = excluded.disc,"
                    " disc_total = excluded.disc_total, comments = excluded.comments,"
                    " duration = excluded.duration, mtime = excluded.mtime,"
                    " file_size = excluded.file_size",
                    (
                        song_id,
                        path_value,
                        library.id,
                        tags.title,
                        artist_id,
                        album_id,
                        genre,
                        tags.year,
                        tags.track,
                        tags.track_total,
                        tags.disc,
                        tags.disc_total,
                        tags.comment,
                        metadata.duration,
                        date_added,
                        metadata.mtime,
                        metadata.file_size,
                    ),
                )
                self._upsert_song_tags(connection, song_id, tags)
                self._upsert_audio_properties(connection, song_id, metadata)
                self._upsert_tag_values(connection, song_id, tags)
                self._upsert_artwork(connection, song_id, metadata)
                connection.execute(
                    "INSERT INTO ts_file_state(song_id, last_scan) VALUES(?, ?)"
                    " ON CONFLICT(song_id) DO UPDATE SET last_scan = excluded.last_scan,"
                    " offline = 0, scan_error = ''",
                    (song_id, now),
                )
                self._update_fts(
                    connection,
                    song_id,
                    tags.title,
                    artist_name,
                    album_artist_name,
                    album_title,
                    genre,
                    tags.comment,
                    path_value,
                )
                written_ids.append(song_id)
            connection.execute(
                "UPDATE libraries SET date_added = date_added WHERE id = ?", (library.id,)
            )
        return self.get_tracks_by_ids(written_ids)

    def _upsert_song_tags(self, connection: sqlite3.Connection, song_id: str, tags: TagSet) -> None:
        connection.execute(
            "INSERT INTO ts_song_tags("
            "song_id, album_artist, composer, lyricist, lyrics, isrc, bpm,"
            " musical_key, compilation, sort_title, sort_artist, sort_album_artist,"
            " sort_album, musicbrainz_recording_id, musicbrainz_release_id,"
            " musicbrainz_artist_id, label, catalog_number, barcode, release_country,"
            " media, script, language, conductor, orchestra, ensemble, work, movement,"
            " movement_number, original_date, replaygain_track_gain,"
            " replaygain_track_peak, replaygain_album_gain, replaygain_album_peak"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
            " ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(song_id) DO UPDATE SET"
            " album_artist = excluded.album_artist, composer = excluded.composer,"
            " lyricist = excluded.lyricist, lyrics = excluded.lyrics,"
            " isrc = excluded.isrc, bpm = excluded.bpm,"
            " musical_key = excluded.musical_key,"
            " compilation = excluded.compilation, sort_title = excluded.sort_title,"
            " sort_artist = excluded.sort_artist,"
            " sort_album_artist = excluded.sort_album_artist,"
            " sort_album = excluded.sort_album,"
            " musicbrainz_recording_id = excluded.musicbrainz_recording_id,"
            " musicbrainz_release_id = excluded.musicbrainz_release_id,"
            " musicbrainz_artist_id = excluded.musicbrainz_artist_id,"
            " label = excluded.label, catalog_number = excluded.catalog_number,"
            " barcode = excluded.barcode, release_country = excluded.release_country,"
            " media = excluded.media, script = excluded.script,"
            " language = excluded.language, conductor = excluded.conductor,"
            " orchestra = excluded.orchestra, ensemble = excluded.ensemble,"
            " work = excluded.work, movement = excluded.movement,"
            " movement_number = excluded.movement_number,"
            " original_date = excluded.original_date,"
            " replaygain_track_gain = excluded.replaygain_track_gain,"
            " replaygain_track_peak = excluded.replaygain_track_peak,"
            " replaygain_album_gain = excluded.replaygain_album_gain,"
            " replaygain_album_peak = excluded.replaygain_album_peak",
            (
                song_id,
                tags.album_artist,
                tags.composer,
                tags.lyricist,
                tags.lyrics,
                tags.isrc,
                tags.bpm,
                tags.musical_key,
                int(tags.compilation),
                tags.sort_title,
                tags.sort_artist,
                tags.sort_album_artist,
                tags.sort_album,
                tags.musicbrainz_recording_id,
                tags.musicbrainz_release_id,
                tags.musicbrainz_artist_id,
                tags.label,
                tags.catalog_number,
                tags.barcode,
                tags.release_country,
                tags.media,
                tags.script,
                tags.language,
                tags.conductor,
                tags.orchestra,
                tags.ensemble,
                tags.work,
                tags.movement,
                tags.movement_number,
                tags.original_date,
                tags.replaygain_track_gain,
                tags.replaygain_track_peak,
                tags.replaygain_album_gain,
                tags.replaygain_album_peak,
            ),
        )

    def _upsert_audio_properties(
        self, connection: sqlite3.Connection, song_id: str, metadata: TrackMetadata
    ) -> None:
        connection.execute(
            "INSERT INTO ts_audio_properties("
            "song_id, format, codec, bitrate, sample_rate, channels, bit_depth, lossless"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(song_id) DO UPDATE SET format = excluded.format,"
            " codec = excluded.codec, bitrate = excluded.bitrate,"
            " sample_rate = excluded.sample_rate, channels = excluded.channels,"
            " bit_depth = excluded.bit_depth, lossless = excluded.lossless",
            (
                song_id,
                metadata.format,
                metadata.codec,
                metadata.bitrate,
                metadata.sample_rate,
                metadata.channels,
                metadata.bit_depth,
                int(metadata.lossless),
            ),
        )

    def _upsert_tag_values(
        self, connection: sqlite3.Connection, song_id: str, tags: TagSet
    ) -> None:
        connection.execute("DELETE FROM ts_tag_value WHERE song_id = ?", (song_id,))
        values: list[tuple[str, str, int, str]] = []
        for position, artist in enumerate(tags.artists):
            values.append((song_id, "artists", position, artist))
        for position, genre in enumerate(tags.genres):
            values.append((song_id, "genres", position, genre))
        for key, items in tags.custom.items():
            for position, value in enumerate(items):
                values.append((song_id, key, position, value))
        if values:
            connection.executemany(
                "INSERT INTO ts_tag_value(song_id, field_key, position, value) VALUES(?, ?, ?, ?)",
                values,
            )

    def _upsert_artwork(
        self, connection: sqlite3.Connection, song_id: str, metadata: TrackMetadata
    ) -> None:
        connection.execute("DELETE FROM ts_artwork WHERE song_id = ?", (song_id,))
        for index, art in enumerate(metadata.artwork):
            checksum = hashlib.sha256(art.data).hexdigest()
            values = (
                song_id,
                art.kind if index == 0 else "other",
                art.mime,
                art.width,
                art.height,
                checksum,
                "",
                art.description,
            )
            connection.execute(
                "INSERT INTO ts_artwork("
                "song_id, kind, mime, width, height, checksum, cache_path, description"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )

    def _update_fts(
        self,
        connection: sqlite3.Connection,
        song_id: str,
        title: str,
        artist: str,
        album_artist: str,
        album: str,
        genre: str,
        comment: str,
        path: str,
    ) -> None:
        connection.execute("DELETE FROM ts_track_fts WHERE song_id = ?", (song_id,))
        connection.execute(
            "INSERT INTO ts_track_fts("
            "song_id, title, artist, album_artist, album, genre, comment, path"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (song_id, title, artist, album_artist, album, genre, comment, path),
        )

    def _remap_song_id(
        self,
        connection: sqlite3.Connection,
        old_id: str,
        new_id: str,
        new_path: str,
    ) -> None:
        if old_id == new_id:
            return
        existing = connection.execute("SELECT id FROM songs WHERE id = ?", (new_id,)).fetchone()
        if existing is not None and str(existing["id"]) != old_id:
            # The new identity already belongs to another row; keep the existing
            # identity and remove the stale row. This is a defensive fallback for
            # duplicate paths produced by external tools.
            connection.execute("DELETE FROM songs WHERE id = ?", (old_id,))
            return
        connection.execute(
            "UPDATE songs SET id = ?, path = ? WHERE id = ?", (new_id, new_path, old_id)
        )
        for table in (
            "ts_song_tags",
            "ts_audio_properties",
            "ts_file_state",
            "ts_tag_value",
            "ts_artwork",
        ):
            connection.execute(
                f"UPDATE {table} SET song_id = ? WHERE song_id = ?", (new_id, old_id)
            )
        connection.execute(
            "UPDATE ts_operation_items SET song_id = ? WHERE song_id = ?",
            (new_id, old_id),
        )
        connection.execute("DELETE FROM ts_track_fts WHERE song_id = ?", (old_id,))

    # ------------------------------------------------------------------
    # Track queries

    _TRACK_SELECT = """
        SELECT s.id, s.path, s.library_id, s.title, ar.name AS artist,
               COALESCE(NULLIF(t.album_artist, ''), ar.name) AS album_artist,
               al.title AS album, s.genre, s.year, s.track, s.track_total,
               s.disc, s.disc_total, s.comments, s.duration, s.date_added,
               s.play_count, s.rating, s.loved, s.last_played, s.skip_count,
               s.mtime, s.file_size, p.format, p.bitrate, p.sample_rate,
               p.channels, p.bit_depth, p.lossless,
               a.cache_path AS artwork_path, s.album_id
        FROM songs s
        JOIN artists ar ON ar.id = s.artist_id
        JOIN albums al ON al.id = s.album_id
        LEFT JOIN ts_song_tags t ON t.song_id = s.id
        LEFT JOIN ts_audio_properties p ON p.song_id = s.id
        LEFT JOIN ts_artwork a ON a.id = (
            SELECT MIN(id) FROM ts_artwork
            WHERE song_id = s.id AND kind = 'front'
        )
    """

    def list_tracks(
        self,
        *,
        library_id: str | None = None,
        query: str = "",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Track]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if library_id:
            clauses.append("s.library_id = ?")
            parameters.append(library_id)
        words = query.strip()
        if words:
            clauses.append(
                "(s.title LIKE ? OR ar.name LIKE ? OR al.title LIKE ?"
                " OR s.genre LIKE ? OR s.comments LIKE ? OR s.path LIKE ?"
                " OR t.album_artist LIKE ?)"
            )
            pattern = f"%{words}%"
            parameters.extend([pattern] * 7)
        sql = self._TRACK_SELECT
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY al.title COLLATE NOCASE, s.disc, s.track, s.title COLLATE NOCASE"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            parameters.extend([limit, max(0, offset)])
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [_row_to_track(row) for row in rows]

    def get_track(self, song_id: str) -> Track | None:
        with self.connect() as connection:
            row = connection.execute(self._TRACK_SELECT + " WHERE s.id = ?", (song_id,)).fetchone()
        return _row_to_track(row) if row else None

    def get_tracks_by_ids(self, song_ids: Sequence[str]) -> list[Track]:
        if not song_ids:
            return []
        marks = ",".join("?" for _ in song_ids)
        with self.connect() as connection:
            rows = connection.execute(
                self._TRACK_SELECT + f" WHERE s.id IN ({marks})", list(song_ids)
            ).fetchall()
        by_id = {row["id"]: _row_to_track(row) for row in rows}
        return [by_id[song_id] for song_id in song_ids if song_id in by_id]

    def get_track_by_path(self, path: str | Path) -> Track | None:
        with self.connect() as connection:
            row = connection.execute(
                self._TRACK_SELECT + " WHERE s.path = ?", (canonical_path(str(path)),)
            ).fetchone()
        return _row_to_track(row) if row else None

    def track_count(self, library_id: str | None = None) -> int:
        with self.connect() as connection:
            if library_id:
                row = connection.execute(
                    "SELECT COUNT(*) FROM songs WHERE library_id = ?", (library_id,)
                ).fetchone()
            else:
                row = connection.execute("SELECT COUNT(*) FROM songs").fetchone()
        return int(row[0]) if row else 0

    def paths_for_library(self, library_id: str) -> dict[str, tuple[str, float, int]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, path, mtime, file_size FROM songs WHERE library_id = ?",
                (library_id,),
            ).fetchall()
        return {
            row["path"]: (row["id"], float(row["mtime"]), int(row["file_size"])) for row in rows
        }

    def missing_paths(self, library_id: str, discovered: set[str]) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT path FROM songs WHERE library_id = ?", (library_id,)
            ).fetchall()
        return [row["path"] for row in rows if row["path"] not in discovered]

    def load_tag_set(self, song_id: str) -> TagSet | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT s.title, s.genre, s.year, s.track, s.track_total,"
                " s.disc, s.disc_total, s.comments, al.title AS album,"
                " t.* FROM songs s JOIN albums al ON al.id = s.album_id"
                " LEFT JOIN ts_song_tags t ON t.song_id = s.id WHERE s.id = ?",
                (song_id,),
            ).fetchone()
            if row is None:
                return None
            values = connection.execute(
                "SELECT field_key, value FROM ts_tag_value"
                " WHERE song_id = ? ORDER BY field_key, position",
                (song_id,),
            ).fetchall()
        tags = TagSet(
            title=row["title"],
            album=row["album"],
            year=row["year"],
            track=int(row["track"]),
            track_total=int(row["track_total"]),
            disc=int(row["disc"]),
            disc_total=int(row["disc_total"]),
            comment=row["comments"],
        )
        for key in (
            "album_artist",
            "composer",
            "lyricist",
            "lyrics",
            "isrc",
            "bpm",
            "musical_key",
            "sort_title",
            "sort_artist",
            "sort_album_artist",
            "sort_album",
            "musicbrainz_recording_id",
            "musicbrainz_release_id",
            "musicbrainz_artist_id",
            "label",
            "catalog_number",
            "barcode",
            "release_country",
            "media",
            "script",
            "language",
            "conductor",
            "orchestra",
            "ensemble",
            "work",
            "movement",
            "movement_number",
            "original_date",
            "replaygain_track_gain",
            "replaygain_track_peak",
            "replaygain_album_gain",
            "replaygain_album_peak",
        ):
            setattr(tags, key, row[key] or "")
        tags.compilation = bool(row["compilation"])
        for value_row in values:
            key = value_row["field_key"]
            value = value_row["value"]
            if key == "artists":
                tags.artists.append(value)
            elif key == "genres":
                tags.genres.append(value)
            else:
                tags.custom.setdefault(key, []).append(value)
        if not tags.genres and row["genre"]:
            tags.genres = [row["genre"]]
        return tags

    def delete_tracks(self, song_ids: Sequence[str]) -> int:
        if not song_ids:
            return 0
        with self.transaction() as connection:
            removed = 0
            for start in range(0, len(song_ids), 300):
                chunk = list(song_ids[start : start + 300])
                marks = ",".join("?" for _ in chunk)
                connection.execute(f"DELETE FROM ts_track_fts WHERE song_id IN ({marks})", chunk)
                cursor = connection.execute(f"DELETE FROM songs WHERE id IN ({marks})", chunk)
                removed += cursor.rowcount
            self._cleanup_orphans(connection)
        return removed

    def delete_library_rows(self, library_id: str) -> int:
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM ts_track_fts WHERE song_id IN"
                " (SELECT id FROM songs WHERE library_id = ?)",
                (library_id,),
            )
            cursor = connection.execute("DELETE FROM songs WHERE library_id = ?", (library_id,))
            removed = cursor.rowcount
            connection.execute("DELETE FROM libraries WHERE id = ?", (library_id,))
            self._cleanup_orphans(connection)
        return removed

    def move_song(self, song_id: str, new_path: str, new_id: str) -> Track:
        """Move a song row to a new path and identity, remapping references."""
        path_value = canonical_path(new_path)
        with self.transaction() as connection:
            connection.execute("PRAGMA defer_foreign_keys=ON")
            row = connection.execute(
                "SELECT s.*, ar.name AS artist_name, al.title AS album_title,"
                " t.album_artist"
                " FROM songs s JOIN artists ar ON ar.id = s.artist_id"
                " JOIN albums al ON al.id = s.album_id"
                " LEFT JOIN ts_song_tags t ON t.song_id = s.id"
                " WHERE s.id = ?",
                (song_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Track not found")
            if new_id != song_id:
                conflict = connection.execute(
                    "SELECT id FROM songs WHERE id = ?", (new_id,)
                ).fetchone()
                if conflict is not None:
                    raise ValueError("The new track identity already exists")
            connection.execute(
                "UPDATE songs SET id = ?, path = ? WHERE id = ?",
                (new_id, path_value, song_id),
            )
            for table in (
                "ts_song_tags",
                "ts_audio_properties",
                "ts_file_state",
                "ts_tag_value",
                "ts_artwork",
            ):
                connection.execute(
                    f"UPDATE {table} SET song_id = ? WHERE song_id = ?",
                    (new_id, song_id),
                )
            connection.execute(
                "UPDATE ts_operation_items SET song_id = ? WHERE song_id = ?",
                (new_id, song_id),
            )
            connection.execute("DELETE FROM ts_track_fts WHERE song_id = ?", (song_id,))
            self._update_fts(
                connection,
                new_id,
                str(row["title"]),
                str(row["artist_name"]),
                str(row["album_artist"] or row["artist_name"]),
                str(row["album_title"]),
                str(row["genre"]),
                str(row["comments"] or ""),
                path_value,
            )
        track = self.get_track(new_id)
        if track is None:
            raise RuntimeError("Track disappeared after move")
        return track

    def find_by_content_hash(self, content_hash: str) -> Track | None:
        if not content_hash:
            return None
        with self.connect() as connection:
            row = connection.execute(
                self._TRACK_SELECT
                + " JOIN ts_file_state f ON f.song_id = s.id"
                + " WHERE f.content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
        return _row_to_track(row) if row else None

    def set_artwork_cache(self, song_id: str, cache_path: str) -> None:
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM ts_artwork WHERE song_id = ? AND kind = 'front'"
                " ORDER BY id LIMIT 1",
                (song_id,),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    "UPDATE ts_artwork SET cache_path = ? WHERE id = ?",
                    (cache_path, existing["id"]),
                )
            elif cache_path:
                connection.execute(
                    "INSERT INTO ts_artwork(song_id, kind, cache_path) VALUES(?, 'front', ?)",
                    (song_id, cache_path),
                )

    def artwork_path_for_album(self, album_id: str) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT cache_path FROM ts_artwork a JOIN songs s ON s.id = a.song_id"
                " WHERE s.album_id = ? AND a.kind = 'front' AND a.cache_path != ''"
                " ORDER BY a.id LIMIT 1",
                (album_id,),
            ).fetchone()
        return str(row["cache_path"]) if row else ""

    def latest_undoable_operation(self) -> Operation | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM ts_operations"
                " WHERE undoable = 1 AND undone = 0 AND status = 'completed'"
                " ORDER BY finished_at DESC, started_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return Operation(
            id=row["id"],
            kind=row["kind"],
            status=row["status"],
            summary=row["summary"],
            dry_run=bool(row["dry_run"]),
            undoable=bool(row["undoable"]),
            undone=bool(row["undone"]),
            started_at=float(row["started_at"]),
            finished_at=float(row["finished_at"]) if row["finished_at"] is not None else None,
        )

    def _cleanup_orphans(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            "DELETE FROM albums WHERE id NOT IN (SELECT DISTINCT album_id FROM songs)"
        )
        connection.execute(
            "DELETE FROM artists WHERE id NOT IN ("
            " SELECT artist_id FROM songs UNION SELECT artist_id FROM albums)"
        )

    def set_loved(self, song_id: str, loved: bool) -> None:
        with self.transaction() as connection:
            connection.execute("UPDATE songs SET loved = ? WHERE id = ?", (int(loved), song_id))

    def track_paths_under(self, root: str) -> list[str]:
        root_path = canonical_path(root)
        with self.connect() as connection:
            rows = connection.execute("SELECT path FROM songs").fetchall()
        return [
            row["path"]
            for row in rows
            if row["path"] == root_path or row["path"].startswith(root_path + "/")
        ]

    # ------------------------------------------------------------------
    # Operations

    def create_operation(
        self, kind: str, summary: str, *, dry_run: bool = False, undoable: bool = True
    ) -> str:
        operation_id = str(uuid.uuid4()).upper()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO ts_operations("
                "id, kind, status, summary, dry_run, undoable, undone, started_at"
                ") VALUES(?, ?, 'running', ?, ?, ?, 0, ?)",
                (operation_id, kind, summary, int(dry_run), int(undoable), _now()),
            )
        return operation_id

    def add_operation_item(
        self,
        operation_id: str,
        *,
        song_id: str | None,
        path: str,
        prior: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO ts_operation_items("
                "operation_id, song_id, path, prior_json, result_json, error"
                ") VALUES(?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    song_id,
                    path,
                    json.dumps(prior, ensure_ascii=False) if prior is not None else None,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    error,
                ),
            )

    def finish_operation(self, operation_id: str, status: str = "completed") -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE ts_operations SET status = ?, finished_at = ? WHERE id = ?",
                (status, _now(), operation_id),
            )

    def mark_operation_undone(self, operation_id: str, undone: bool = True) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE ts_operations SET undone = ?, status = ? WHERE id = ?",
                (int(undone), "undone" if undone else "completed", operation_id),
            )

    def list_operations(self, limit: int = 50) -> list[Operation]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ts_operations ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            Operation(
                id=row["id"],
                kind=row["kind"],
                status=row["status"],
                summary=row["summary"],
                dry_run=bool(row["dry_run"]),
                undoable=bool(row["undoable"]),
                undone=bool(row["undone"]),
                started_at=float(row["started_at"]),
                finished_at=float(row["finished_at"]) if row["finished_at"] is not None else None,
            )
            for row in rows
        ]

    def get_operation_items(self, operation_id: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM ts_operation_items WHERE operation_id = ? ORDER BY id",
                (operation_id,),
            ).fetchall()

    # ------------------------------------------------------------------
    # Settings and duplicates

    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM ts_settings WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO ts_settings(key, value) VALUES(?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def exact_duplicate_groups(self) -> list[list[Track]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT s.id, f.content_hash, s.file_size FROM songs s"
                " JOIN ts_file_state f ON f.song_id = s.id"
                " WHERE f.content_hash IS NOT NULL AND f.content_hash != ''"
            ).fetchall()
        groups: dict[str, list[str]] = {}
        for row in rows:
            groups.setdefault(row["content_hash"], []).append(row["id"])
        result: list[list[Track]] = []
        for ids in groups.values():
            if len(ids) > 1:
                result.append(self.get_tracks_by_ids(ids))
        return result

    def probable_duplicate_groups(self) -> list[list[Track]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT s.id, lower(ar.name) AS artist, lower(s.title) AS title,"
                " round(s.duration) AS duration FROM songs s"
                " JOIN artists ar ON ar.id = s.artist_id"
            ).fetchall()
        groups: dict[tuple[str, str, int], list[str]] = {}
        for row in rows:
            key = (row["artist"], row["title"], int(row["duration"] or 0))
            groups.setdefault(key, []).append(row["id"])
        return [self.get_tracks_by_ids(ids) for ids in groups.values() if len(ids) > 1]

    def update_content_hash(self, song_id: str, content_hash: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO ts_file_state(song_id, content_hash, hash_state)"
                " VALUES(?, ?, 'complete')"
                " ON CONFLICT(song_id) DO UPDATE SET content_hash = excluded.content_hash,"
                " hash_state = 'complete'",
                (song_id, content_hash),
            )

    def get_content_hash(self, song_id: str) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM ts_file_state WHERE song_id = ?", (song_id,)
            ).fetchone()
        return str(row["content_hash"] or "") if row else ""
