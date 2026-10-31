"""Reference vectors for Tracks/WebTracks-compatible identity."""

from __future__ import annotations

from trackstash.core.identity import (
    album_uuid,
    artist_uuid,
    normalize_relative_path,
    song_uuid,
    swift_lower,
)


def test_song_uuid_matches_reference() -> None:
    assert (
        song_uuid("iTunes", "Raver Rage Records/レレレコンピ/01 related.m4a")
        == "0B161D2F-A164-B19B-9D78-B2C4B1E72589"
    )


def test_artist_uuid_matches_reference() -> None:
    assert artist_uuid("Raver Rage Records") == "43054C1F-0026-CD2F-C882-2A741E57531E"


def test_album_uuid_matches_reference() -> None:
    artist_id = "43054C1F-0026-CD2F-C882-2A741E57531E"
    assert album_uuid(artist_id, "レレレコンピ") == "5411E3DF-F842-42D2-C519-201B354AEA96"


def test_swift_characterwise_lowercase() -> None:
    assert swift_lower("I.M-P.U.L.S.Σ") == "i.m-p.u.l.s.σ"


def test_relative_path_strips_leading_slash() -> None:
    assert normalize_relative_path("/A/B.flac") == "A/B.flac"
