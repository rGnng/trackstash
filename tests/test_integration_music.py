"""Opt-in integration tests against real music folders.

Set ``TRACKSTASH_TEST_MUSIC`` to a folder containing audio files. The test only
copies a handful of files into a temporary managed library and removes them
afterwards; the source folders are never modified.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from trackstash.core.db import Database
from trackstash.core.library import LibraryService
from trackstash.core.metadata import read_metadata, supported_extensions, write_tags

pytestmark = pytest.mark.integration


def _sample_files(root: Path, limit: int = 3) -> list[Path]:
    result: list[Path] = []
    for current, directories, files in os.walk(root):
        directories[:] = [name for name in directories if not name.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            path = Path(current) / name
            if path.suffix.lower() in supported_extensions():
                result.append(path)
                if len(result) >= limit:
                    return result
    return result


def test_real_music_import_edit_organize_and_cleanup(tmp_path: Path) -> None:
    source_root = os.environ.get("TRACKSTASH_TEST_MUSIC")
    if not source_root:
        pytest.skip("TRACKSTASH_TEST_MUSIC is not set")
    root = Path(source_root).expanduser()
    if not root.is_dir():
        pytest.skip("TRACKSTASH_TEST_MUSIC does not exist")

    sources = _sample_files(root)
    if not sources:
        pytest.skip("No supported audio files found")

    library_root = tmp_path / "Managed"
    library_root.mkdir()
    database = Database(tmp_path / "library.sqlite")
    service = LibraryService(database, artwork_dir=tmp_path / "Artwork")
    library = database.add_library(library_root, name="Integration")
    plan = service.plan_import(sources, library.id)
    result = service.execute_import(plan)
    try:
        assert len(result.imported) == len(sources)
        assert all(source.exists() for source in sources)
        assert all(Path(track.path).exists() for track in result.imported)
        assert database.track_count(library.id) == len(sources)

        track = result.imported[0]
        original = read_metadata(track.path).tags.title
        updated = service.update_tags(
            [track.id],
            {"title": f"{original} (integration)", "genres": ["Integration"]},
        )
        assert not updated.errors
        assert read_metadata(track.path).tags.genres == ["Integration"]

        plan = service.preview_organize(
            [track.id],
            "{album_artist}/{album}/Int {track:02} - {title}",
        )
        moved = service.organize(plan)
        assert not moved.errors
        assert database.get_track(plan[0].new_id) is not None

        undo_move = service.undo_last()
        assert undo_move is not None and undo_move.undone == 1
        assert database.get_track(track.id) is not None
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_real_m4a_roundtrip_if_available(tmp_path: Path) -> None:
    source = os.environ.get("TRACKSTASH_TEST_M4A")
    if not source:
        pytest.skip("TRACKSTASH_TEST_M4A is not set")
    path = Path(source).expanduser()
    if not path.is_file():
        pytest.skip("TRACKSTASH_TEST_M4A does not exist")

    library_root = tmp_path / "Managed"
    library_root.mkdir()
    database = Database(tmp_path / "library.sqlite")
    service = LibraryService(database, artwork_dir=tmp_path / "Artwork")
    library = database.add_library(library_root, name="M4A")
    plan = service.plan_import([path], library.id)
    result = service.execute_import(plan)
    try:
        assert len(result.imported) == 1
        track = result.imported[0]
        metadata = read_metadata(track.path)
        assert metadata.format in {"M4A", "MP4"}
        write_tags(track.path, {"title": "TrackStash integration title"})
        assert read_metadata(track.path).tags.title == "TrackStash integration title"
        assert path.exists()
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
