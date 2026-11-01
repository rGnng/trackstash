"""Regression and performance guardrails for storage, search, and workflows."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from trackstash.core.db import Database, Library
from trackstash.core.identity import song_uuid
from trackstash.core.library import LibraryService
from trackstash.core.metadata import Artwork, TagSet, TrackMetadata, write_tags


def _tags(
    *,
    title: str,
    artist: str = "Test Artist",
    album: str = "Test Album",
    album_artist: str = "Test Artist",
    genre: str = "Rock",
    comment: str = "",
    track: str = "1",
) -> TagSet:
    return TagSet(
        title=title,
        artists=[artist],
        album=album,
        album_artist=album_artist,
        genres=[genre],
        comment=comment,
        track=track,
        track_total="10",
        year="2024",
    )


def _metadata(
    path: Path,
    tags: TagSet,
    *,
    artwork: list[Artwork] | None = None,
    format: str = "FLAC",
) -> TrackMetadata:
    return TrackMetadata(
        path=str(path),
        format=format,
        codec=format.lower(),
        duration=180.0,
        bitrate=900 if format == "FLAC" else 320,
        sample_rate=44100,
        channels=2,
        bit_depth=16,
        lossless=format == "FLAC",
        file_size=1000,
        mtime=1_700_000_000.0,
        tags=tags,
        artwork=artwork or [],
    )


def _library_with_tracks(
    tmp_path: Path, count: int = 3, *, name: str = "Regression Library"
) -> tuple[Database, Library, list[Path]]:
    database = Database(tmp_path / "library.sqlite")
    root = tmp_path / "Library"
    root.mkdir()
    library = database.add_library(root, name=name)
    paths: list[Path] = []
    metadata_list: list[TrackMetadata] = []
    for index in range(count):
        path = root / f"Track {index:03d}.flac"
        paths.append(path)
        metadata_list.append(
            _metadata(
                path,
                _tags(
                    title=f"Searchable Song {index}",
                    artist=f"Artist {index % 3}",
                    album=f"Album {index % 2}",
                    comment=f"note {index}",
                    track=str(index + 1),
                ),
            )
        )
    database.upsert_tracks(metadata_list, library)
    return database, library, paths


@contextmanager
def _count_connections(database: Database, counter: list[int]) -> Iterator[None]:
    original = database.connect

    @contextmanager
    def counted() -> Iterator[sqlite3.Connection]:
        counter[0] += 1
        with original() as connection:
            yield connection

    database.connect = counted  # type: ignore[method-assign]
    try:
        yield
    finally:
        database.connect = original  # type: ignore[method-assign]


def test_search_uses_fts_for_all_indexed_fields(tmp_path: Path) -> None:
    database = Database(tmp_path / "search.sqlite")
    root = tmp_path / "Library"
    root.mkdir()
    library = database.add_library(root, name="Search")
    path = root / "Folder" / "Searchable Song.flac"
    database.upsert_tracks(
        [
            _metadata(
                path,
                _tags(
                    title="Searchable Song",
                    artist="Alpha Artist",
                    album_artist="Beta Artist",
                    album="Gamma Album",
                    genre="Jazz",
                    comment="hidden note",
                ),
            )
        ],
        library,
    )

    for query in ("Sear", "Alpha", "Beta", "Gamma", "Jazz", "hidden", "Folder"):
        assert len(database.list_tracks(query=query)) == 1, query

    # FTS operators and punctuation must never leak into the MATCH expression.
    for query in ('Sear"ch*()', "!!!", "Alpha's"):
        database.list_tracks(query=query)
    assert database.list_tracks(query="!!!") == []
    assert len(database.list_tracks(query='"Searchable"')) == 1


def test_fts_rows_follow_updates_and_deletes(tmp_path: Path) -> None:
    database, library, paths = _library_with_tracks(tmp_path, count=1)
    path = paths[0]
    assert len(database.list_tracks(query="Searchable")) == 1
    database.upsert_tracks([_metadata(path, _tags(title="Renamed Track"))], library)
    assert database.list_tracks(query="Searchable") == []
    assert len(database.list_tracks(query="Renamed")) == 1

    track = database.list_tracks(library_id=library.id)[0]
    database.delete_tracks([track.id])
    assert database.list_tracks(query="Renamed") == []


def test_fts_index_is_rebuilt_for_an_older_database(tmp_path: Path) -> None:
    database, library, _ = _library_with_tracks(tmp_path)
    with sqlite3.connect(database.path) as connection:
        connection.execute("DELETE FROM ts_track_fts")
        connection.execute("PRAGMA user_version = 3")
        connection.commit()

    reopened = Database(database.path)
    assert reopened.list_tracks(query="Searchable Song 1")[0].library_id == library.id


def test_list_tracks_filters_format_and_missing_artwork_in_sql(tmp_path: Path) -> None:
    database = Database(tmp_path / "filters.sqlite")
    root = tmp_path / "Library"
    root.mkdir()
    library = database.add_library(root, name="Filters")
    artwork = [Artwork(data=b"cover", mime="image/jpeg", width=10, height=10)]
    database.upsert_tracks(
        [
            _metadata(root / "with-art.flac", _tags(title="With Art"), artwork=artwork),
            _metadata(root / "no-art.mp3", _tags(title="No Art"), format="MP3"),
            _metadata(root / "other-no-art.mp3", _tags(title="Other No Art"), format="MP3"),
        ],
        library,
    )

    assert [track.title for track in database.list_tracks(library_id=library.id)] == [
        "No Art",
        "Other No Art",
        "With Art",
    ]
    assert len(database.list_tracks(library_id=library.id, format_filter="FLAC")) == 1
    assert len(database.list_tracks(library_id=library.id, missing_artwork=True)) == 2
    assert (
        len(
            database.list_tracks(
                library_id=library.id,
                format_filter="mp3",
                missing_artwork=True,
            )
        )
        == 2
    )


def test_album_artwork_is_scoped_to_the_selected_library(tmp_path: Path) -> None:
    database = Database(tmp_path / "libraries.sqlite")
    root_a = tmp_path / "Library A"
    root_b = tmp_path / "Library B"
    root_a.mkdir()
    root_b.mkdir()
    library_a = database.add_library(root_a, name="A")
    library_b = database.add_library(root_b, name="B")
    tags = _tags(title="Shared Album")
    picture = [Artwork(data=b"cover-b", mime="image/jpeg", width=8, height=8)]
    database.upsert_tracks([_metadata(root_a / "a.flac", tags)], library_a)
    database.upsert_tracks([_metadata(root_b / "b.flac", tags, artwork=picture)], library_b)

    albums_a = database.list_albums(library_a.id)
    albums_b = database.list_albums(library_b.id)
    assert len(albums_a) == len(albums_b) == 1
    assert albums_a[0].id == albums_b[0].id
    assert albums_a[0].artwork_song_path is None
    assert albums_a[0].artwork_checksum == ""
    assert albums_b[0].artwork_song_path == str(root_b / "b.flac")


def test_duplicate_groups_and_hash_lookup_are_library_scoped(tmp_path: Path) -> None:
    database = Database(tmp_path / "duplicates.sqlite")
    root_a = tmp_path / "Library A"
    root_b = tmp_path / "Library B"
    root_a.mkdir()
    root_b.mkdir()
    library_a = database.add_library(root_a, name="A")
    library_b = database.add_library(root_b, name="B")
    first = database.upsert_tracks([_metadata(root_a / "a.flac", _tags(title="Same"))], library_a)[
        0
    ]
    second = database.upsert_tracks([_metadata(root_b / "b.flac", _tags(title="Same"))], library_b)[
        0
    ]
    database.update_content_hashes({first.id: "same-hash", second.id: "same-hash"})

    assert database.exact_duplicate_groups(library_a.id) == []
    assert database.exact_duplicate_groups(library_b.id) == []
    assert len(database.exact_duplicate_groups()) == 1
    assert database.find_by_content_hash("same-hash", library_a.id).id == first.id
    assert database.find_by_content_hash("same-hash", library_b.id).id == second.id


def test_import_duplicate_skip_does_not_cross_libraries(
    tmp_path: Path, audio_factory: Path
) -> None:
    source_root = tmp_path / "Source"
    source_root.mkdir()
    source = source_root / "same.flac"
    shutil.copy2(audio_factory / "sample.flac", source)
    write_tags(
        source,
        {
            "title": "Shared",
            "artists": ["Shared Artist"],
            "album": "Shared Album",
            "album_artist": "Shared Artist",
        },
    )
    database = Database(tmp_path / "import.sqlite")
    service = LibraryService(database)
    root_a = tmp_path / "A"
    root_b = tmp_path / "B"
    root_a.mkdir()
    root_b.mkdir()
    library_a = database.add_library(root_a, name="A")
    library_b = database.add_library(root_b, name="B")

    source_a = tmp_path / "Source A"
    source_a.mkdir()
    first_source = source_a / "same.flac"
    shutil.copy2(source, first_source)
    service.execute_import(service.plan_import([first_source], library_a.id))

    source_b = tmp_path / "Source B"
    source_b.mkdir()
    second_source = source_b / "same.flac"
    shutil.copy2(source, second_source)
    plan = service.plan_import([second_source], library_b.id, duplicate_policy="skip")
    assert plan.items[0].action == "import"
    result = service.execute_import(plan)
    assert len(result.imported) == 1
    assert database.track_count(library_a.id) == 1
    assert database.track_count(library_b.id) == 1


def test_plan_import_uses_constant_database_queries(tmp_path: Path, audio_factory: Path) -> None:
    incoming = tmp_path / "Incoming"
    incoming.mkdir()
    for index in range(6):
        source = incoming / f"track-{index}.flac"
        shutil.copy2(audio_factory / "sample.flac", source)
        write_tags(
            source,
            {
                "title": f"Import {index}",
                "artists": ["Import Artist"],
                "album": "Import Album",
                "album_artist": "Import Artist",
                "track": index + 1,
            },
        )
    database = Database(tmp_path / "plan.sqlite")
    root = tmp_path / "Library"
    root.mkdir()
    library = database.add_library(root, name="Plan")
    service = LibraryService(database)
    counter = [0]

    with _count_connections(database, counter):
        plan = service.plan_import([incoming], library.id, duplicate_policy="keep")

    assert len(plan.items) == 6
    assert counter[0] <= 3


def test_preview_tag_edits_batches_database_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, library, _ = _library_with_tracks(tmp_path, count=30)
    service = LibraryService(database)
    song_ids = [track.id for track in database.list_tracks(library_id=library.id)]
    counter = [0]

    with _count_connections(database, counter):
        changes = service.preview_tag_edits(song_ids, {"title": "Changed"})

    assert len(changes) == 30
    assert counter[0] <= 2


def test_preview_auto_number_batches_database_access(
    tmp_path: Path,
) -> None:
    database, library, _ = _library_with_tracks(tmp_path, count=20)
    service = LibraryService(database)
    song_ids = [track.id for track in database.list_tracks(library_id=library.id)]
    counter = [0]

    with _count_connections(database, counter):
        changes = service.preview_auto_number(song_ids)

    assert len(changes) == 20
    assert counter[0] <= 2


def test_preview_organize_uses_indexed_technical_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, library, _ = _library_with_tracks(tmp_path, count=1)
    service = LibraryService(database)

    def fail_read(_path: object) -> None:
        raise AssertionError("preview_organize should not read audio files")

    monkeypatch.setattr("trackstash.core.library.read_metadata", fail_read)
    track = database.list_tracks(library_id=library.id)[0]
    plan = service.preview_organize([track.id], "{format}-{bitrate}/{title}")
    assert plan[0].new_path.endswith("flac-900/Searchable Song 0.flac")


def test_delete_tracks_cleans_orphans_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, library, _ = _library_with_tracks(tmp_path, count=12)
    service = LibraryService(database)
    song_ids = [track.id for track in database.list_tracks(library_id=library.id)]
    calls = [0]
    original = Database._cleanup_orphans

    def counted(self: Database, connection: sqlite3.Connection) -> None:
        calls[0] += 1
        original(self, connection)

    monkeypatch.setattr(Database, "_cleanup_orphans", counted)
    result = service.delete_tracks(song_ids)

    assert result.deleted == 12
    assert result.errors == []
    assert calls[0] == 1
    assert database.track_count(library.id) == 0


def test_content_hash_indexing_only_processes_missing_tracks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, library, paths = _library_with_tracks(tmp_path, count=3)
    for path in paths:
        path.write_bytes(path.name.encode("utf-8"))
    service = LibraryService(database)
    assert len(database.track_ids_missing_content_hash(library.id)) == 3
    assert service.index_content_hashes(library.id) == 3
    assert database.track_ids_missing_content_hash(library.id) == []

    def fail_hash(_path: object) -> str:
        raise AssertionError("cached hashes should not be recomputed")

    monkeypatch.setattr("trackstash.core.library.content_hash", fail_hash)
    assert service.index_content_hashes(library.id) == 0


def test_tag_editor_loads_tags_in_one_batch(tmp_path: Path, qtbot: QtBot) -> None:
    from trackstash.ui.dialogs import TagEditorDialog

    database, library, _ = _library_with_tracks(tmp_path, count=25)
    service = LibraryService(database)
    song_ids = [track.id for track in database.list_tracks(library_id=library.id)]
    counter = [0]

    with _count_connections(database, counter):
        dialog = TagEditorDialog(service, song_ids)
    qtbot.addWidget(dialog)

    assert counter[0] <= 1
    dialog._checks["track"].setChecked(True)
    dialog._lines["track"].setText("A1")
    assert dialog.edits()["track"] == "A1"


def test_duplicate_identity_fallback_does_not_raise(tmp_path: Path) -> None:
    database, library, paths = _library_with_tracks(tmp_path, count=1)
    original = database.list_tracks(library_id=library.id)[0]
    new_id = song_uuid(library.id_namespace, "Track 000.flac")
    stale_id = "00000000-0000-0000-0000-000000000001"
    other_path = str(paths[0].with_name("Other.flac"))
    with database.transaction() as connection:
        for table in (
            "ts_song_tags",
            "ts_audio_properties",
            "ts_file_state",
            "ts_tag_value",
            "ts_artwork",
            "ts_operation_items",
            "ts_track_fts",
        ):
            connection.execute(f"DELETE FROM {table} WHERE song_id = ?", (original.id,))
        connection.execute("UPDATE songs SET id = ? WHERE id = ?", (stale_id, original.id))
        connection.execute(
            "INSERT INTO songs("
            "id, path, library_id, title, artist_id, album_id, genre, year,"
            " track, track_total, disc, disc_total, comments, duration,"
            " date_added, play_count, rating, loved, last_played, skip_count,"
            " mtime, file_size"
            ") SELECT ?, ?, library_id, title, artist_id, album_id, genre, year,"
            " track, track_total, disc, disc_total, comments, duration,"
            " date_added, play_count, rating, loved, last_played, skip_count,"
            " mtime, file_size FROM songs WHERE id = ?",
            (new_id, other_path, stale_id),
        )

    database.upsert_tracks([_metadata(paths[0], _tags(title="Resolved"))], library)
    resolved = database.get_track(new_id)
    assert resolved is not None
    assert resolved.path == str(paths[0])
    assert resolved.title == "Resolved"


def test_album_icon_is_cropped_to_a_square(qapp: object) -> None:
    from io import BytesIO

    from PIL import Image

    from trackstash.core.db import AlbumRow
    from trackstash.ui.models import AlbumGridModel

    buffer = BytesIO()
    Image.new("RGB", (200, 100), (30, 90, 160)).save(buffer, "PNG")
    album = AlbumRow("album-1", "Album", "Artist", "2024", 1, None, "")
    model = AlbumGridModel([album])
    model.set_cover_size(64)
    model._cover_loaded(model._key(album), buffer.getvalue())
    icon = model._icons[model._key(album)]
    pixmap = icon.pixmap(64, 64)
    assert (pixmap.width(), pixmap.height()) == (64, 64)


def test_repeated_artwork_selection_uses_cache(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    audio_factory: Path,
) -> None:
    from io import BytesIO

    from PIL import Image

    from trackstash.ui.main_window import MainWindow

    database = Database(tmp_path / "artwork.sqlite")
    root = tmp_path / "Library"
    root.mkdir()
    source = tmp_path / "cover.flac"
    shutil.copy2(audio_factory / "sample.flac", source)
    write_tags(
        source,
        {
            "title": "Cover",
            "artists": ["Cover Artist"],
            "album": "Cover Album",
            "album_artist": "Cover Artist",
        },
    )
    library = database.add_library(root, name="Artwork")
    service = LibraryService(database)
    result = service.execute_import(service.plan_import([source], library.id))
    track = result.imported[0]
    buffer = BytesIO()
    Image.new("RGB", (32, 32), (30, 90, 160)).save(buffer, "JPEG")
    assert service.set_artwork([track.id], buffer.getvalue()) == []

    window = MainWindow(database)
    qtbot.addWidget(window)
    refreshed = database.get_track(track.id)
    assert refreshed is not None

    import trackstash.ui.main_window as main_window

    calls: list[str] = []
    original = main_window.read_artwork

    def counted(value: str) -> object:
        calls.append(value)
        return original(value)

    monkeypatch.setattr(main_window, "read_artwork", counted)
    first = window._artwork_for_track(refreshed)
    second = window._artwork_for_track(refreshed)
    assert len(calls) == 1
    assert not first[0].isNull()
    assert not second[0].isNull()
