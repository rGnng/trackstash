"""End-to-end library service tests using generated audio fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from trackstash.core.db import Database
from trackstash.core.identity import relative_path, song_uuid
from trackstash.core.library import LibraryService
from trackstash.core.metadata import read_metadata, write_tags


@pytest.fixture()
def service(tmp_path: Path) -> LibraryService:
    database = Database(tmp_path / "library.sqlite")
    return LibraryService(database, artwork_dir=tmp_path / "Artwork")


@pytest.fixture()
def populated(
    tmp_path: Path, audio_factory: Path, service: LibraryService
) -> tuple[LibraryService, Path, object, list]:
    library_root = tmp_path / "Library"
    library_root.mkdir()
    incoming = tmp_path / "Incoming"
    incoming.mkdir()
    for index, source_name in enumerate(("sample.flac", "sample.mp3"), start=1):
        destination = incoming / source_name
        shutil.copy2(audio_factory / source_name, destination)
        write_tags(
            destination,
            {
                "title": f"Song {index}",
                "artists": ["Test Artist"],
                "album_artist": "Test Artist",
                "album": "Test Album",
                "genres": ["Rock"],
                "track": index,
                "track_total": 2,
                "year": "2024",
            },
        )
    library = service.db.add_library(library_root, name="Test Library")
    plan = service.plan_import([incoming], library.id)
    result = service.execute_import(plan)
    assert len(result.imported) == 2
    return service, library_root, library, result.imported


def test_import_copies_and_computes_uuid(
    service: LibraryService, populated: tuple, tmp_path: Path
) -> None:
    service, library_root, library, imported = populated
    assert all(Path(track.path).exists() for track in imported)
    assert (library_root / "Test Artist" / "Test Album").is_dir()
    for track in imported:
        rel = relative_path(track.path, library_root)
        assert rel is not None
        assert track.id == song_uuid(library.id_namespace, rel)
    assert service.db.track_count(library.id) == 2
    assert len(service.db.list_tracks(query="Song 1")) == 1
    assert len(service.db.list_tracks(query="Test Artist")) == 2


def test_duplicate_import_skip(service: LibraryService, populated: tuple) -> None:
    service, _, library, _ = populated
    assert Path(service.db.list_tracks()[0].path).exists()
    source_root = Path(service.db.list_tracks()[0].path).parent.parent.parent
    plan = service.plan_import([source_root], library.id, duplicate_policy="skip")
    assert plan.items
    assert all(item.action == "skip" for item in plan.items)


def test_tag_edit_and_undo(service: LibraryService, populated: tuple) -> None:
    service, _, _, imported = populated
    song_id = imported[0].id
    changes = service.preview_tag_edits(
        [song_id], {"title": "Edited", "genres": ["Jazz", "Fusion"]}
    )
    assert "title" in changes[0].changed_fields
    result = service.update_tags([song_id], {"title": "Edited", "genres": ["Jazz", "Fusion"]})
    assert not result.errors
    assert service.db.get_track(song_id).title == "Edited"
    assert read_metadata(imported[0].path).tags.genres == ["Jazz", "Fusion"]

    undone = service.undo_last()
    assert undone is not None
    assert undone.undone == 1
    assert service.db.get_track(song_id).title == "Song 1"
    assert read_metadata(imported[0].path).tags.title == "Song 1"


def test_organize_changes_id_and_undo(service: LibraryService, populated: tuple) -> None:
    service, _, _, imported = populated
    track = imported[0]
    plan = service.preview_organize(
        [track.id], "{album_artist}/{album}/Disc {disc}/{track:02} - {title}"
    )
    assert plan[0].new_path != plan[0].old_path
    assert plan[0].new_id != plan[0].old_id
    result = service.organize(plan)
    assert not result.errors
    moved = service.db.get_track(plan[0].new_id)
    assert moved is not None
    assert Path(moved.path).exists()
    assert service.db.get_track(plan[0].old_id) is None

    undone = service.undo_last()
    assert undone is not None and undone.undone == 1
    restored = service.db.get_track(track.id)
    assert restored is not None
    assert Path(restored.path).exists()


def test_scan_and_missing_review(service: LibraryService, populated: tuple) -> None:
    service, library_root, library, _ = populated
    new_file = library_root / "Test Artist" / "Test Album" / "New.flac"
    shutil.copy2(service.db.list_tracks()[0].path, new_file)
    scan = service.scan_library(library.id, mode="quick")
    assert scan.updated == 1
    assert service.db.track_count(library.id) == 3

    missing_path = new_file
    missing_path.unlink()
    full = service.scan_library(library.id, mode="full")
    assert str(missing_path) in full.missing
    assert service.db.track_count(library.id) == 3
    pruned = service.scan_library(library.id, mode="full", prune=True)
    assert pruned.pruned == 1
    assert service.db.track_count(library.id) == 2


def test_delete_index_and_undo(service: LibraryService, populated: tuple) -> None:
    service, _, _, imported = populated
    song_id = imported[0].id
    result = service.delete_tracks([song_id])
    assert result.deleted == 1
    assert service.db.get_track(song_id) is None
    assert Path(imported[0].path).exists()

    undone = service.undo_last()
    assert undone is not None and undone.undone == 1
    assert service.db.get_track(song_id) is not None


def test_import_move_and_undo(service: LibraryService, tmp_path: Path, audio_factory: Path) -> None:
    library_root = tmp_path / "MoveLibrary"
    library_root.mkdir()
    incoming = tmp_path / "MoveIncoming"
    incoming.mkdir()
    source = incoming / "move.flac"
    shutil.copy2(audio_factory / "sample.flac", source)
    write_tags(
        source,
        {
            "title": "Move Me",
            "artists": ["Mover"],
            "album": "Move Album",
            "album_artist": "Mover",
        },
    )
    library = service.db.add_library(library_root, name="Move")
    plan = service.plan_import([incoming], library.id, mode="move")
    result = service.execute_import(plan)
    assert result.moved == 1
    assert not source.exists()
    assert Path(result.imported[0].path).exists()

    undone = service.undo_last()
    assert undone is not None and undone.undone == 1
    assert source.exists()
    assert service.db.track_count(library.id) == 0


def test_duplicate_import_skip_by_hash(
    service: LibraryService, tmp_path: Path, audio_factory: Path
) -> None:
    root = tmp_path / "HashLibrary"
    root.mkdir()
    library = service.db.add_library(root, name="Hash")
    first = tmp_path / "First"
    first.mkdir()
    source = first / "one.flac"
    shutil.copy2(audio_factory / "sample.flac", source)
    write_tags(
        source,
        {
            "title": "Duplicate",
            "artists": ["Hash Artist"],
            "album": "Hash Album",
            "album_artist": "Hash Artist",
        },
    )
    first_plan = service.plan_import([first], library.id)
    first_result = service.execute_import(first_plan)
    assert len(first_result.imported) == 1

    second = tmp_path / "Second"
    second.mkdir()
    duplicate = second / "two.flac"
    shutil.copy2(source, duplicate)
    plan = service.plan_import([second], library.id, duplicate_policy="skip")
    assert plan.items[0].action == "skip"
    assert plan.items[0].duplicate_of == first_result.imported[0].id
    result = service.execute_import(plan)
    assert result.imported == []
    assert service.db.track_count(library.id) == 1


def test_multi_disc_import_uses_disc_folders(
    service: LibraryService, tmp_path: Path, audio_factory: Path
) -> None:
    root = tmp_path / "MultiDisc"
    root.mkdir()
    incoming = tmp_path / "MultiIncoming"
    incoming.mkdir()
    for disc in (1, 2):
        source = incoming / f"disc{disc}.flac"
        shutil.copy2(audio_factory / "sample.flac", source)
        write_tags(
            source,
            {
                "title": "Same Song",
                "artists": ["Disc Artist"],
                "album": "Double Album",
                "album_artist": "Disc Artist",
                "track": 1,
                "track_total": 1,
                "disc": disc,
                "disc_total": 2,
            },
        )
    library = service.db.add_library(root, name="Multi")
    plan = service.plan_import([incoming], library.id)
    result = service.execute_import(plan)
    assert len(result.imported) == 2
    paths = sorted(track.path for track in result.imported)
    assert any("Disc 1" in path for path in paths)
    assert any("Disc 2" in path for path in paths)
    assert len(set(paths)) == 2
