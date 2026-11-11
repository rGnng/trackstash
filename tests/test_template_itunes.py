"""Path rules verified against an Apple Music / iTunes library."""

from __future__ import annotations

import unicodedata

from trackstash.core.metadata import TagSet, TrackMetadata
from trackstash.core.template import DEFAULT_TEMPLATE, render_template


def _render(path: str = "/music/track.m4a", **tags: object) -> str:
    tagset = TagSet(**tags)
    metadata = TrackMetadata(
        path=path,
        format="MP4",
        codec="AAC",
        duration=1.0,
        bitrate=256,
        sample_rate=44100,
        channels=2,
        bit_depth=0,
        lossless=False,
        file_size=1,
        mtime=0.0,
        tags=tagset,
    )
    return render_template(DEFAULT_TEMPLATE, tagset, metadata)


def test_title_with_dot_keeps_extension() -> None:
    assert _render(title="O.O.H", track="16", album_artist="A", album="B") == "A/B/16 O.O.H.m4a"
    assert (
        _render(title="Mr. Hyde", track="1", album_artist="A", album="B") == "A/B/01 Mr. Hyde.m4a"
    )


def test_title_trailing_dot_is_kept() -> None:
    assert (
        _render(title="Gabber is loud.", track="4", album_artist="A", album="B")
        == "A/B/04 Gabber is loud..m4a"
    )


def test_slash_in_tag_becomes_underscore_not_a_folder() -> None:
    assert (
        _render(title="Artificial (Rework) w/FullMoon", track="6", album_artist="A", album="B")
        == "A/B/06 Artificial (Rework) w_FullMoon.m4a"
    )
    assert (
        _render(album_artist="黄昏フロンティア/上海アリス幻樂団", album="B", title="T", track="1")
        == "黄昏フロンティア_上海アリス幻樂団/B/01 T.m4a"
    )


def test_colon_star_question_and_quotes_are_replaced() -> None:
    assert (
        _render(album_artist="Glassy:oceaN", album="TANO*C", title="Why?", track="2")
        == "Glassy_oceaN/TANO_C/02 Why_.m4a"
    )
    assert (
        _render(album_artist="A", album="B", title="Shelter\u2019s \u201cX\u201d", track="3")
        == "A/B/03 Shelter_s _X_.m4a"
    )


def test_album_artist_trailing_dot_and_space() -> None:
    assert (
        _render(album_artist="V.A.", album="HYPER", title="T", track="1") == "V.A_/HYPER/01 T.m4a"
    )
    assert (
        _render(album_artist="Cosmo Burst ", album="Stardust", title="T", track="1")
        == "Cosmo Burst/Stardust/01 T.m4a"
    )


def test_title_trailing_space_is_removed() -> None:
    assert (
        _render(title="Desire Drive ", track="3", album_artist="A", album="B")
        == "A/B/03 Desire Drive.m4a"
    )


def test_missing_or_zero_track_has_no_prefix() -> None:
    assert _render(title="Otenba", track="", album_artist="A", album="B") == "A/B/Otenba.m4a"
    assert _render(title="Zero", track="0", album_artist="A", album="B") == "A/B/Zero.m4a"


def test_single_disc_1_of_1_has_no_disc_prefix() -> None:
    assert (
        _render(title="Neon", track="7", disc="1", disc_total="1", album_artist="A", album="B")
        == "A/B/07 Neon.m4a"
    )


def test_disc_prefix_when_disc_total_is_unknown_or_multi() -> None:
    assert (
        _render(title="Memory", track="1", disc="1", disc_total="", album_artist="A", album="B")
        == "A/B/1-01 Memory.m4a"
    )
    assert (
        _render(title="Lacrimosa", track="9", disc="1", disc_total="2", album_artist="A", album="B")
        == "A/B/1-09 Lacrimosa.m4a"
    )
    assert (
        _render(title="Night", track="2", disc="12", disc_total="12", album_artist="A", album="B")
        == "A/B/12-02 Night.m4a"
    )


def test_disc_zero_has_no_prefix() -> None:
    assert (
        _render(title="X", track="1", disc="0", disc_total="", album_artist="A", album="B")
        == "A/B/01 X.m4a"
    )


def test_compilation_goes_to_compilations_folder() -> None:
    assert (
        _render(title="Song", track="1", album_artist="VA", album="Comp", compilation=True)
        == "Compilations/Comp/01 Song.m4a"
    )
    assert (
        _render(title="Song", track="1", album_artist="VA", album="Comp", compilation=False)
        == "VA/Comp/01 Song.m4a"
    )


def test_brackets_and_punctuation_are_kept() -> None:
    assert (
        _render(title="31 days [MUSIC SELECT]", track="31", album_artist="A", album="B")
        == "A/B/31 31 days [MUSIC SELECT].m4a"
    )


def test_output_is_nfc_even_when_tags_are_nfd() -> None:
    nfd_title = unicodedata.normalize("NFD", "\u304c")
    rendered = _render(title=nfd_title, track="1", album_artist="A", album="B")
    assert rendered == unicodedata.normalize("NFC", rendered)
    assert rendered.endswith("\u304c.m4a")


def test_extension_is_not_duplicated_when_template_already_has_it() -> None:
    tagset = TagSet(title="T", album_artist="A", album="B", track="1")
    metadata = TrackMetadata(
        path="/x/a.MP3",
        format="MP3",
        codec="MP3",
        duration=1.0,
        bitrate=128,
        sample_rate=44100,
        channels=2,
        bit_depth=0,
        lossless=False,
        file_size=1,
        mtime=0.0,
        tags=tagset,
    )
    assert render_template("{album_artist}/{album}/{title}.{ext}", tagset, metadata) == "A/B/T.MP3"


def _render_path(path: str, **tags: object) -> str:
    tagset = TagSet(**tags)
    metadata = TrackMetadata(
        path=path,
        format="MP4",
        codec="AAC",
        duration=1.0,
        bitrate=256,
        sample_rate=44100,
        channels=2,
        bit_depth=0,
        lossless=False,
        file_size=1,
        mtime=0.0,
        tags=tagset,
    )
    return render_template(DEFAULT_TEMPLATE, tagset, metadata)


def test_empty_title_uses_source_file_stem() -> None:
    assert (
        _render_path("/incoming/E25 source.m4a", title="", track="2", album_artist="A", album="B")
        == "A/B/02 E25 source.m4a"
    )


def test_reserved_names_replace_last_character() -> None:
    assert _render(title="T", track="1", album_artist="A", album="CON") == "A/CO_/01 T.m4a"
    assert _render(title="T", track="1", album_artist="A", album="con") == "A/CO_/01 T.m4a"
    assert _render(title="T", track="1", album_artist="A", album="COM1") == "A/COM_/01 T.m4a"
    assert _render(title="T", track="1", album_artist="A", album="LPT1") == "A/LPT_/01 T.m4a"
    assert _render(title="T", track="1", album_artist="A", album="AUX") == "A/AU_/01 T.m4a"


def test_uppercase_extension_is_kept() -> None:
    assert (
        _render_path("/x/a.MP3", title="Upper", track="1", album_artist="A", album="B")
        == "A/B/01 Upper.MP3"
    )


def test_component_limit_counts_utf16_units_and_keeps_extension() -> None:
    short = _render(title="あ" * 84, track="1", album_artist="A", album="B")
    assert short == "A/B/01 " + "あ" * 84 + ".m4a"
    long = _render(title="あ" * 300, track="1", album_artist="A", album="B")
    name = long.rsplit("/", 1)[1]
    assert name == "01 " + "あ" * 246 + ".m4a"
    assert len(name.encode("utf-16-le")) // 2 == 253


def test_nfd_album_name_is_cut_by_utf16_units() -> None:
    album = unicodedata.normalize("NFD", "EDGE" + "é" * 200)
    rendered = _render(title="T", track="1", album_artist="A", album=album)
    directory = rendered.split("/")[1]
    assert len(directory.encode("utf-16-le")) // 2 <= 253


def test_long_ascii_title_is_cut_but_extension_survives() -> None:
    title = "T" * 300
    rendered = _render(title=title, track="1", album_artist="A", album="B")
    name = rendered.rsplit("/", 1)[1]
    assert name.endswith(".m4a")
    assert len(name.encode("utf-16-le")) // 2 == 253


def test_long_album_directory_is_cut_to_253_units() -> None:
    album = "B" * 300
    rendered = _render(title="T", track="1", album_artist="A", album=album)
    assert len(rendered.split("/")[1].encode("utf-16-le")) // 2 == 253


def test_leading_whitespace_in_album_artist_becomes_underscore() -> None:
    assert (
        _render(title="T", track="1", album_artist=" pomme'tto", album="B")
        == "_pomme'tto/B/01 T.m4a"
    )


def test_only_the_first_leading_character_is_replaced() -> None:
    assert (
        _render(title="T", track="1", album_artist="  TwoSpace", album="B")
        == "_ TwoSpace/B/01 T.m4a"
    )


def test_leading_whitespace_in_album_becomes_underscore() -> None:
    assert (
        _render(title="T", track="1", album_artist="A", album=" EDGE SP F")
        == "A/_EDGE SP F/01 T.m4a"
    )


def test_leading_whitespace_in_title_without_track_becomes_underscore() -> None:
    assert _render(title=" NoTrack", album_artist="A", album="B") == "A/B/_NoTrack.m4a"


def test_leading_whitespace_in_title_with_track_is_kept() -> None:
    assert (
        _render(title=" LeadTitle", track="1", album_artist="A", album="B")
        == "A/B/01  LeadTitle.m4a"
    )


def test_internal_double_spaces_are_kept() -> None:
    assert (
        _render(title="Sturm  und Drang", track="8", album_artist="A", album="B")
        == "A/B/08 Sturm  und Drang.m4a"
    )


def test_reserved_name_with_extension_is_renamed() -> None:
    assert _render(title="CON.x", album_artist="A", album="B") == "A/B/CO_.x.m4a"
    assert _render(title="T", track="1", album_artist="A", album="AUX.txt") == "A/AU_.txt/01 T.m4a"
    assert (
        _render(title="T", track="1", album_artist="A", album="nul.tar.gz")
        == "A/NU_.tar.gz/01 T.m4a"
    )


def test_reserved_name_check_does_not_touch_normal_names() -> None:
    assert _render(title="T", track="1", album_artist="A", album="CONTRA") == "A/CONTRA/01 T.m4a"
    assert _render(title="T", track="1", album_artist="A", album="COM10") == "A/COM10/01 T.m4a"


def test_disc_total_in_n_of_m_form_is_read() -> None:
    assert (
        _render(title="Intro", track="1/3", disc="1/1", album_artist="A", album="B")
        == "A/B/01 Intro.m4a"
    )
    assert (
        _render(title="Intro", track="1/3", disc="1/2", album_artist="A", album="B")
        == "A/B/1-01 Intro.m4a"
    )


def test_leading_dot_in_folder_becomes_underscore() -> None:
    assert (
        _render(title="T", track="1", album_artist=".banbanshi", album="Matsuri Scape")
        == "_banbanshi/Matsuri Scape/01 T.m4a"
    )


def test_missing_artist_uses_album_artist() -> None:
    assert (
        _render(title="T", track="1", album_artist="Album Artist", album="B")
        == "Album Artist/B/01 T.m4a"
    )


def test_multiple_genres_use_the_last_value() -> None:
    tagset = TagSet(
        title="T",
        album_artist="A",
        album="B",
        track="1",
        genres=["Symphonic Rock", "Symphonic Metal"],
    )
    metadata = TrackMetadata(
        path="/x.m4a",
        format="MP4",
        codec="AAC",
        duration=1.0,
        bitrate=1,
        sample_rate=1,
        channels=1,
        bit_depth=0,
        lossless=False,
        file_size=1,
        mtime=0.0,
        tags=tagset,
    )
    from trackstash.core.template import template_values

    assert template_values(tagset, metadata)["genre"] == "Symphonic Metal"


def test_year_keeps_leading_digits() -> None:
    tagset = TagSet(title="T", album_artist="A", album="B", track="1", year="24-0")
    metadata = TrackMetadata(
        path="/x.m4a",
        format="MP4",
        codec="AAC",
        duration=1.0,
        bitrate=1,
        sample_rate=1,
        channels=1,
        bit_depth=0,
        lossless=False,
        file_size=1,
        mtime=0.0,
        tags=tagset,
    )
    from trackstash.core.template import template_values

    assert template_values(tagset, metadata)["year"] == "24"
    assert template_values(tagset, metadata)["date"] == "24"
