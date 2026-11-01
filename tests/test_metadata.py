"""Metadata round-trip tests across supported containers."""

from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from trackstash.core.metadata import (
    read_artwork,
    read_metadata,
    remove_artwork,
    supported_extensions,
    write_artwork,
    write_tags,
)

AUDIO_EXTENSIONS = ["flac", "mp3", "m4a", "ogg", "opus", "wav", "aiff", "wv"]


def _tag_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 16), (180, 40, 40)).save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.mark.parametrize("extension", AUDIO_EXTENSIONS)
def test_metadata_round_trip(audio_factory: Path, extension: str) -> None:
    path = audio_factory / f"sample.{extension}"
    metadata = read_metadata(path)

    assert metadata.format
    assert metadata.duration > 0
    assert metadata.file_size > 0
    assert 0 < metadata.bitrate < 20000

    updated = write_tags(
        path,
        {
            "title": "Round Trip",
            "artists": ["Artist One", "Artist Two"],
            "album": "Test Album",
            "album_artist": "Artist One",
            "genres": ["Rock", "Pop"],
            "year": "2024",
            "track": 2,
            "track_total": 9,
            "disc": 1,
            "disc_total": 2,
            "comment": "A comment",
            "composer": "Composer",
            "bpm": "128",
            "musical_key": "Am",
            "isrc": "ABC123",
        },
    )

    assert updated.tags.title == "Round Trip"
    assert updated.tags.artists == ["Artist One", "Artist Two"]
    assert updated.tags.album == "Test Album"
    assert updated.tags.album_artist == "Artist One"
    assert updated.tags.genres == ["Rock", "Pop"]
    assert updated.tags.track == "2"
    assert updated.tags.track_total == "9"
    assert updated.tags.disc == "1"
    assert updated.tags.disc_total == "2"
    assert updated.tags.bpm == "128"
    assert updated.tags.musical_key == "Am"

    write_artwork(path, _tag_bytes(), mime="image/jpeg")
    artwork = read_artwork(path)
    assert len(artwork) == 1
    assert artwork[0].mime == "image/jpeg"
    assert artwork[0].width == 16

    remove_artwork(path)
    assert read_artwork(path) == []


@pytest.mark.parametrize("extension", ["flac", "mp3", "m4a", "ogg", "opus", "wav", "aiff"])
def test_clearing_fields(audio_factory: Path, extension: str) -> None:
    path = audio_factory / f"sample.{extension}"
    write_tags(path, {"title": "Temporary", "artists": ["Temporary Artist"]})
    cleared = write_tags(path, {"title": "", "artists": []})

    assert cleared.tags.title == ""
    assert cleared.tags.artists == []


@pytest.mark.parametrize("extension", ["flac", "mp3"])
def test_text_track_and_disc_round_trip(
    audio_factory: Path, tmp_path: Path, extension: str
) -> None:
    path = tmp_path / f"text-numbers.{extension}"
    shutil.copy2(audio_factory / f"sample.{extension}", path)
    updated = write_tags(
        path,
        {
            "title": "Text Numbers",
            "track": "A1",
            "track_total": "Side A",
            "disc": "B",
            "disc_total": "2",
        },
    )
    assert updated.tags.track == "A1"
    assert updated.tags.track_total == "Side A"
    assert updated.tags.disc == "B"
    assert updated.tags.disc_total == "2"


def test_supported_extensions_include_target_formats() -> None:
    extensions = supported_extensions()
    for extension in (".flac", ".mp3", ".m4a", ".ogg", ".opus", ".ape", ".wv"):
        assert extension in extensions


@pytest.mark.parametrize("extension", ["mp3", "m4a"])
def test_bitrate_is_reported_in_kbps(audio_factory: Path, extension: str) -> None:
    import mutagen

    path = audio_factory / f"sample.{extension}"
    audio = mutagen.File(str(path), easy=False)
    assert audio is not None
    raw_bitrate = int(getattr(audio.info, "bitrate", 0))
    assert raw_bitrate > 0
    assert read_metadata(path).bitrate == round(raw_bitrate / 1000)


def test_unknown_tags_survive_known_edits(audio_factory: Path) -> None:
    import mutagen
    from mutagen.flac import FLAC
    from mutagen.id3 import TXXX

    flac_path = audio_factory / "sample.flac"
    flac = mutagen.File(flac_path, easy=False)
    assert isinstance(flac, FLAC)
    flac.tags["CUSTOMFIELD"] = ["keep me"]
    flac.save()
    write_tags(flac_path, {"title": "Known Edit"})
    reread = read_metadata(flac_path)
    assert reread.raw_tags.get("customfield") == ["keep me"]

    mp3_path = audio_factory / "sample.mp3"
    mp3 = mutagen.File(mp3_path, easy=False)
    assert mp3 is not None and mp3.tags is not None
    mp3.tags.add(TXXX(encoding=3, desc="CustomField", text=["keep me"]))
    mp3.save(v2_version=4)
    write_tags(mp3_path, {"title": "Known Edit"})
    reread = read_metadata(mp3_path)
    assert reread.raw_tags.get("TXXX:CustomField") == ["keep me"]
