"""Paths recorded in the database must match the spelling used on disk."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from trackstash.core.db import Database
from trackstash.core.identity import relative_path, resolve_disk_path, song_uuid
from trackstash.core.library import LibraryService
from trackstash.core.metadata import write_tags
from trackstash.core.template import DEFAULT_TEMPLATE


def _case_insensitive(directory: Path) -> bool:
    probe = directory / "CaseProbe"
    probe.write_text("x", encoding="utf-8")
    try:
        return (directory / "caseprobe").exists()
    finally:
        probe.unlink()


requires_case_insensitive = pytest.mark.skipif(
    not _case_insensitive(Path(os.sep + "tmp") if Path(os.sep + "tmp").is_dir() else Path.cwd()),
    reason="file system is case sensitive",
)


def test_resolve_disk_path_returns_real_spelling(tmp_path: Path) -> None:
    real = tmp_path / "Real Artist" / "Real Album"
    real.mkdir(parents=True)
    (real / "Song.m4a").write_bytes(b"x")
    assert resolve_disk_path(str(tmp_path / "real artist" / "real album" / "song.m4a")) == str(
        real / "Song.m4a"
    )
    # A missing component leaves the path untouched.
    missing = str(tmp_path / "real artist" / "missing" / "song.m4a")
    assert resolve_disk_path(missing) == missing


def test_resolve_disk_path_keeps_unicode_form_used_on_disk(tmp_path: Path) -> None:
    directory = tmp_path / "unicode"
    directory.mkdir()
    name = "が.m4a"
    (directory / name).write_bytes(b"x")
    stored = next(entry for entry in os.listdir(directory) if entry.endswith(".m4a"))
    assert resolve_disk_path(str(directory / name)) == str(directory / stored)


@requires_case_insensitive
def test_import_records_the_existing_folder_spelling(tmp_path: Path, audio_factory: Path) -> None:
    root = tmp_path / "Library"
    existing = root / "Test Artist" / "Test Album"
    existing.mkdir(parents=True)
    incoming = tmp_path / "Incoming"
    incoming.mkdir()
    source = incoming / "sample.flac"
    shutil.copy2(audio_factory / "sample.flac", source)
    write_tags(
        source,
        {
            "title": "Song",
            "artists": ["Test Artist"],
            "album": "Test Album",
            "album_artist": "test artist",
            "track": 1,
        },
    )
    database = Database(tmp_path / "library.sqlite")
    service = LibraryService(database)
    library = database.add_library(root, name="Case")
    service.execute_import(service.plan_import([incoming], library.id))
    track = service.db.list_tracks()[0]
    assert Path(track.path).parent == existing
    assert str(track.path) == str(existing / Path(track.path).name)
    rel = relative_path(track.path, library.path)
    assert rel is not None
    assert track.id == song_uuid(library.id_namespace, rel)


@requires_case_insensitive
def test_organize_case_only_change_keeps_the_file_and_records_real_path(
    tmp_path: Path, audio_factory: Path
) -> None:
    root = tmp_path / "Library"
    root.mkdir()
    incoming = tmp_path / "Incoming"
    incoming.mkdir()
    source = incoming / "sample.flac"
    shutil.copy2(audio_factory / "sample.flac", source)
    write_tags(
        source,
        {
            "title": "Song",
            "artists": ["Test Artist"],
            "album": "Test Album",
            "album_artist": "Test Artist",
            "track": 1,
        },
    )
    database = Database(tmp_path / "library.sqlite")
    service = LibraryService(database)
    library = database.add_library(root, name="Case")
    service.execute_import(service.plan_import([incoming], library.id))
    track = service.db.list_tracks()[0]
    original = Path(track.path)
    assert original.exists()

    write_tags(original, {"album_artist": "test artist"})
    plan = service.preview_organize([track.id], DEFAULT_TEMPLATE)
    result = service.organize(plan)
    assert result.errors == []
    updated = service.db.get_track(track.id)
    assert updated is not None
    assert updated.path == str(original)
    assert updated.id == track.id
