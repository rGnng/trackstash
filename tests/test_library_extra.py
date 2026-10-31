"""Additional library lifecycle, move detection, and redo tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from trackstash.core.db import Database
from trackstash.core.library import LibraryService
from trackstash.core.metadata import read_metadata, write_tags


@pytest.fixture()
def setup(tmp_path: Path, audio_factory: Path) -> tuple[Database, LibraryService, object]:
    root = tmp_path / "Library"
    root.mkdir()
    incoming = tmp_path / "Incoming"
    incoming.mkdir()
    source = incoming / "sample.flac"
    shutil.copy2(audio_factory / "sample.flac", source)
    write_tags(
        source,
        {
            "title": "Redo Song",
            "artists": ["Redo Artist"],
            "album": "Redo Album",
            "album_artist": "Redo Artist",
            "track": 1,
        },
    )
    database = Database(tmp_path / "library.sqlite")
    service = LibraryService(database, artwork_dir=tmp_path / "Artwork")
    library = database.add_library(root, name="Lifecycle")
    plan = service.plan_import([incoming], library.id)
    service.execute_import(plan)
    return database, service, library


def test_library_rename_disable_remove(setup: tuple) -> None:
    database, _, library = setup
    renamed = database.rename_library(library.id, name="Renamed", identifier="collection")
    assert renamed.name == "Renamed"
    assert database.get_library(library.id).name == "Renamed"
    database.set_library_enabled(library.id, False)
    assert database.get_library(library.id).enabled is False
    database.set_library_enabled(library.id, True)
    assert database.get_library(library.id).enabled is True
    assert database.remove_library(library.id) == 1
    assert database.get_library(library.id) is None


def test_overlapping_library_is_rejected(setup: tuple, tmp_path: Path) -> None:
    database, _, library = setup
    nested = Path(library.path) / "Nested"
    nested.mkdir()
    with pytest.raises(ValueError):
        database.add_library(nested, name="Nested")


def test_backup_and_settings(setup: tuple, tmp_path: Path) -> None:
    database, _, _ = setup
    backup = database.backup(tmp_path / "backup.sqlite")
    assert backup.is_file()
    database.set_setting("default_template", "{artist}/{album}/{title}")
    assert database.get_setting("default_template") == "{artist}/{album}/{title}"
    stats = database.library_stats()
    assert stats["tracks"] == 1


def test_move_detection_on_full_scan(setup: tuple) -> None:
    database, service, library = setup
    track = database.list_tracks(library_id=library.id)[0]
    old_path = Path(track.path)
    new_path = old_path.with_name("Renamed By Finder.flac")
    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old_path), str(new_path))

    result = service.scan_library(library.id, mode="full")
    assert result.errors == []
    assert result.missing == []
    assert database.track_count(library.id) == 1
    moved = database.get_track_by_path(str(new_path))
    assert moved is not None
    assert moved.id != track.id


def test_redo_tag_and_organize(setup: tuple) -> None:
    database, service, library = setup
    track = database.list_tracks(library_id=library.id)[0]
    service.update_tags([track.id], {"title": "Redone Title"})
    assert service.undo_last() is not None
    assert database.get_track(track.id).title == "Redo Song"
    redo = service.redo_last()
    assert redo is not None and redo.undone == 1
    assert database.get_track(track.id).title == "Redone Title"

    plan = service.preview_organize([track.id], "{artist}/{album}/Redo {track:02} {title}")
    service.organize(plan)
    moved = database.get_track(plan[0].new_id)
    assert moved is not None
    assert service.undo_last() is not None
    assert database.get_track(track.id) is not None
    redo_move = service.redo_last()
    assert redo_move is not None and redo_move.undone == 1
    assert database.get_track(plan[0].new_id) is not None
    assert read_metadata(database.get_track(plan[0].new_id).path).tags.title == "Redone Title"


def test_artwork_embed_cache_extract_remove(setup: tuple, tmp_path: Path) -> None:
    from io import BytesIO

    from PIL import Image

    database, service, library = setup
    track = database.list_tracks(library_id=library.id)[0]
    buffer = BytesIO()
    Image.new("RGB", (32, 24), (10, 120, 200)).save(buffer, "JPEG")
    errors = service.set_artwork([track.id], buffer.getvalue(), mime="image/jpeg")
    assert errors == []
    refreshed = database.get_track(track.id)
    assert refreshed is not None
    cache = service.artwork_dir / f"{refreshed.album_id.upper()}.jpg"
    assert cache.is_file()

    extracted = service.extract_artwork(track.id, tmp_path / "extracted.jpg")
    assert extracted.is_file()
    assert extracted.stat().st_size > 0

    errors = service.remove_artwork([track.id])
    assert errors == []
    assert database.load_tag_set(track.id) is not None


def test_rekey_changes_song_ids_and_backs_up(setup: tuple) -> None:
    database, service, library = setup
    track = database.list_tracks(library_id=library.id)[0]
    database.rename_library(library.id, identifier="new-namespace")
    result = service.rekey_library(library.id)
    assert result.updated == 1
    assert Path(result.backup).is_file()
    assert result.namespace == "new-namespace"
    assert database.get_track(track.id) is None
    updated = database.list_tracks(library_id=library.id)[0]
    assert updated.id != track.id
    assert updated.path == track.path
