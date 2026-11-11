"""Audio metadata reading and writing built on mutagen.

The module exposes a canonical tag model so the rest of TrackStash does not need
to know about ID3 frames, Vorbis comments, MP4 atoms, or APE items.
"""

from __future__ import annotations

import base64
import copy
import mimetypes
import struct
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import mutagen
from mutagen.apev2 import APEv2
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    COMM,
    ID3,
    TALB,
    TBPM,
    TCMP,
    TCOM,
    TCON,
    TDOR,
    TDRC,
    TEXT,
    TIT2,
    TKEY,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
    TSO2,
    TSOA,
    TSOP,
    TSOT,
    TSRC,
    TXXX,
    USLT,
)
from mutagen.mp4 import MP4, Atoms, MP4Cover, MP4FreeForm, MP4Tags
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow is a required dependency
    Image = None  # type: ignore[assignment]

__all__ = [
    "Artwork",
    "TagSet",
    "TrackMetadata",
    "apply_tag_edits",
    "is_valid_numeric_tag",
    "read_artwork",
    "read_metadata",
    "remove_artwork",
    "supported_extensions",
    "tagset_to_dict",
    "write_artwork",
    "write_tags",
]

SUPPORTED_EXTENSIONS = {
    ".flac",
    ".mp3",
    ".m4a",
    ".mp4",
    ".aac",
    ".ogg",
    ".oga",
    ".opus",
    ".wav",
    ".aiff",
    ".aif",
    ".aifc",
    ".ape",
    ".wv",
    ".dsf",
    ".dff",
}


_CODEC_LABELS = {
    "mp4a.40.2": "AAC",
    "mp4a.40.5": "HE-AAC",
    "alac": "ALAC",
    "OggVorbis": "Vorbis",
    "OggOpus": "Opus",
    "WavPack": "WavPack",
    "WAVE": "PCM",
    "AIFF": "PCM",
    "MPEGInfo": "MP3",
    "FLAC": "FLAC",
    "MP3": "MP3",
}


def _codec_label(raw: str, format_name: str) -> str:
    return _CODEC_LABELS.get(raw, raw or format_name)


_TAG_FIELDS: tuple[str, ...] = (
    "title",
    "artists",
    "album_artist",
    "album",
    "genres",
    "year",
    "original_date",
    "track",
    "track_total",
    "disc",
    "disc_total",
    "comment",
    "composer",
    "lyricist",
    "lyrics",
    "isrc",
    "bpm",
    "musical_key",
    "compilation",
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
    "replaygain_track_gain",
    "replaygain_track_peak",
    "replaygain_album_gain",
    "replaygain_album_peak",
)


@dataclass(slots=True)
class Artwork:
    """An embedded picture."""

    data: bytes
    mime: str
    width: int | None = None
    height: int | None = None
    kind: str = "front"
    description: str = ""


@dataclass(slots=True)
class TagSet:
    """Canonical tags for one track."""

    title: str = ""
    artists: list[str] = field(default_factory=list)
    album_artist: str = ""
    album: str = ""
    genres: list[str] = field(default_factory=list)
    year: str = ""
    original_date: str = ""
    track: str = ""
    track_total: str = ""
    disc: str = ""
    disc_total: str = ""
    comment: str = ""
    composer: str = ""
    lyricist: str = ""
    lyrics: str = ""
    isrc: str = ""
    bpm: str = ""
    musical_key: str = ""
    compilation: bool = False
    sort_title: str = ""
    sort_artist: str = ""
    sort_album_artist: str = ""
    sort_album: str = ""
    musicbrainz_recording_id: str = ""
    musicbrainz_release_id: str = ""
    musicbrainz_artist_id: str = ""
    label: str = ""
    catalog_number: str = ""
    barcode: str = ""
    release_country: str = ""
    media: str = ""
    script: str = ""
    language: str = ""
    conductor: str = ""
    orchestra: str = ""
    ensemble: str = ""
    work: str = ""
    movement: str = ""
    movement_number: str = ""
    replaygain_track_gain: str = ""
    replaygain_track_peak: str = ""
    replaygain_album_gain: str = ""
    replaygain_album_peak: str = ""
    custom: dict[str, list[str]] = field(default_factory=dict)

    @property
    def primary_artist(self) -> str:
        return self.artists[0] if self.artists else "Unknown Artist"

    @property
    def primary_genre(self) -> str:
        return self.genres[0] if self.genres else ""

    @property
    def album_artist_or_primary(self) -> str:
        return self.album_artist or self.primary_artist


@dataclass(slots=True)
class TrackMetadata:
    """Technical properties and canonical tags for one audio file."""

    path: str
    format: str
    codec: str
    duration: float
    bitrate: int
    sample_rate: int
    channels: int
    bit_depth: int
    lossless: bool
    file_size: int
    mtime: float
    tags: TagSet
    artwork: list[Artwork] = field(default_factory=list)
    raw_tags: dict[str, list[str]] = field(default_factory=dict)


def supported_extensions() -> frozenset[str]:
    """Return the supported lowercase file extensions."""
    return frozenset(SUPPORTED_EXTENSIONS)


def _clean(value: Any) -> str:
    """Return a tag value without trailing whitespace.

    Leading whitespace is kept because Apple Music keeps it and turns it into
    an underscore only where a path component starts.
    """
    if value is None:
        return ""
    return str(value).rstrip()


def _values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [text for item in value if (text := _clean(item))]
    text = _clean(value)
    return [text] if text else []


def _pair(value: Any) -> tuple[str, str]:
    text = _clean(value)
    if not text:
        return "", ""
    first, _, second = text.partition("/")
    return first.strip(), second.strip()


def _natural(value: Any) -> str:
    return _clean(value)


def _int_value(value: object) -> int:
    text = _clean(value)
    return int(text) if text.isdigit() else 0


_NUMERIC_TAG_FIELDS = frozenset({"track", "track_total", "disc", "disc_total"})
_PAIRED_NUMERIC_TAG_FIELDS = frozenset({"track", "disc"})


def is_valid_numeric_tag(field_name: str, value: object) -> bool:
    """Validate a track/disc value edited by the user.

    Track and disc numbers are numeric. They may also be entered as a
    ``number/total`` pair, and values are not limited to one digit.
    Totals accept a single number only. Empty values clear the field.
    """
    if field_name not in _NUMERIC_TAG_FIELDS:
        return True
    text = _clean(value)
    if not text:
        return True
    parts = [part.strip() for part in text.split("/")]
    if len(parts) > 2 or any(not part for part in parts):
        return False
    if len(parts) == 2 and field_name not in _PAIRED_NUMERIC_TAG_FIELDS:
        return False
    return all(part.isdigit() for part in parts)


def _artwork_meta(
    data: bytes, mime: str = "", kind: str = "front", description: str = ""
) -> Artwork:
    width: int | None = None
    height: int | None = None
    detected_mime = mime
    if Image is not None:
        try:
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
                if not detected_mime:
                    detected_mime = Image.MIME.get(image.format or "", "")
        except Exception:
            pass
    if not detected_mime:
        detected_mime = mimetypes.guess_type("cover")[0] or "application/octet-stream"
    return Artwork(
        data=data,
        mime=detected_mime,
        width=width,
        height=height,
        kind=kind,
        description=description,
    )


def _classify(value: Any) -> str:
    module = type(value).__module__
    tags = getattr(value, "tags", None)
    if isinstance(tags, ID3) or module.startswith(
        (
            "mutagen.mp3",
            "mutagen.aac",
            "mutagen.aiff",
            "mutagen.wave",
            "mutagen.dsf",
            "mutagen.dsdiff",
        )
    ):
        return "id3"
    if isinstance(value, FLAC):
        return "flac"
    if isinstance(value, (OggVorbis, OggOpus)) or module.startswith("mutagen.ogg"):
        return "vorbis"
    if isinstance(value, MP4):
        return "mp4"
    if isinstance(tags, APEv2) or module.startswith(
        ("mutagen.apev2", "mutagen.monkeysaudio", "mutagen.wavpack")
    ):
        return "ape"
    return ""


def _read_vorbis(audio: Any, tags: Mapping[str, Any]) -> TagSet:
    result = TagSet()

    def first(*keys: str) -> str:
        for key in keys:
            values = _values(tags.get(key))
            if values:
                return values[0]
        return ""

    def many(*keys: str) -> list[str]:
        for key in keys:
            values = _values(tags.get(key))
            if values:
                return values
        return []

    result.title = first("TITLE")
    result.artists = many("ARTIST")
    result.album_artist = first("ALBUMARTIST", "ALBUM ARTIST", "ENSEMBLE", "BAND")
    result.album = first("ALBUM")
    result.genres = many("GENRE")
    result.year = first("DATE", "YEAR")
    result.original_date = first("ORIGINALDATE", "ORIGINALYEAR")
    result.track, result.track_total = _pair(first("TRACKNUMBER"))
    if not result.track_total:
        result.track_total = _natural(first("TRACKTOTAL", "TOTALTRACKS"))
    result.disc, result.disc_total = _pair(first("DISCNUMBER"))
    if not result.disc_total:
        result.disc_total = _natural(first("DISCTOTAL", "TOTALDISCS"))
    result.comment = first("COMMENT", "DESCRIPTION")
    result.composer = first("COMPOSER")
    result.lyricist = first("LYRICIST")
    result.lyrics = first("LYRICS", "UNSYNCEDLYRICS")
    result.isrc = first("ISRC")
    result.bpm = first("BPM")
    result.musical_key = first("KEY", "INITIALKEY")
    result.compilation = first("COMPILATION").lower() in {"1", "true", "yes"}
    result.sort_title = first("TITLESORT")
    result.sort_artist = first("ARTISTSORT")
    result.sort_album_artist = first("ALBUMARTISTSORT")
    result.sort_album = first("ALBUMSORT")
    result.musicbrainz_recording_id = first("MUSICBRAINZ_TRACKID", "MUSICBRAINZ_RECORDINGID")
    result.musicbrainz_release_id = first(
        "MUSICBRAINZ_RELEASEGROUPID", "MUSICBRAINZ_ALBUMID", "MUSICBRAINZ_RELEASEID"
    )
    result.musicbrainz_artist_id = first("MUSICBRAINZ_ARTISTID")
    result.label = first("LABEL", "ORGANIZATION", "PUBLISHER")
    result.catalog_number = first("CATALOGNUMBER")
    result.barcode = first("BARCODE")
    result.release_country = first("RELEASECOUNTRY")
    result.media = first("MEDIA")
    result.script = first("SCRIPT")
    result.language = first("LANGUAGE")
    result.conductor = first("CONDUCTOR")
    result.orchestra = first("ORCHESTRA")
    result.ensemble = first("ENSEMBLE")
    result.work = first("WORK")
    result.movement = first("MOVEMENT")
    result.movement_number = first("MOVEMENTNUMBER")
    result.replaygain_track_gain = first("REPLAYGAIN_TRACK_GAIN")
    result.replaygain_track_peak = first("REPLAYGAIN_TRACK_PEAK")
    result.replaygain_album_gain = first("REPLAYGAIN_ALBUM_GAIN")
    result.replaygain_album_peak = first("REPLAYGAIN_ALBUM_PEAK")
    return result


def _frame_text(tags: ID3, frame_id: str) -> list[str]:
    frame = tags.get(frame_id)
    if frame is None:
        return []
    return [_clean(value) for value in getattr(frame, "text", []) if _clean(value)]


def _txxx(tags: ID3, description: str) -> str:
    frame = tags.get(f"TXXX:{description}")
    if frame is None:
        return ""
    values = getattr(frame, "text", [])
    return _clean(values[0]) if values else ""


def _read_id3(audio: Any) -> TagSet:
    tags = audio.tags
    result = TagSet()
    if tags is None:
        return result

    result.title = (_frame_text(tags, "TIT2") or [""])[0]
    result.artists = _frame_text(tags, "TPE1")
    result.album_artist = (_frame_text(tags, "TPE2") or [""])[0]
    result.album = (_frame_text(tags, "TALB") or [""])[0]
    result.genres = _frame_text(tags, "TCON")
    result.year = (_frame_text(tags, "TDRC") or _frame_text(tags, "TYER") or [""])[0]
    result.original_date = (_frame_text(tags, "TDOR") or [""])[0]
    result.track, result.track_total = _pair((_frame_text(tags, "TRCK") or [""])[0])
    result.disc, result.disc_total = _pair((_frame_text(tags, "TPOS") or [""])[0])

    comments = tags.getall("COMM")
    if comments:
        result.comment = _clean(comments[0].text[0]) if comments[0].text else ""
    lyrics = tags.getall("USLT")
    if lyrics:
        result.lyrics = _clean(lyrics[0].text)
    result.composer = (_frame_text(tags, "TCOM") or [""])[0]
    result.lyricist = (_frame_text(tags, "TEXT") or [""])[0]
    result.isrc = (_frame_text(tags, "TSRC") or [""])[0]
    result.bpm = (_frame_text(tags, "TBPM") or [""])[0]
    result.musical_key = (_frame_text(tags, "TKEY") or [""])[0]
    result.compilation = (_frame_text(tags, "TCMP") or [""])[0].lower() in {
        "1",
        "true",
        "yes",
    }
    result.sort_title = (_frame_text(tags, "TSOT") or [""])[0]
    result.sort_artist = (_frame_text(tags, "TSOA") or [""])[0]
    result.sort_album_artist = (_frame_text(tags, "TSO2") or [""])[0]
    result.sort_album = (_frame_text(tags, "TSOP") or [""])[0]
    result.musicbrainz_recording_id = _txxx(tags, "MusicBrainz Track Id")
    result.musicbrainz_release_id = _txxx(tags, "MusicBrainz Album Id")
    result.musicbrainz_artist_id = _txxx(tags, "MusicBrainz Artist Id")
    result.label = _txxx(tags, "LABEL")
    result.catalog_number = _txxx(tags, "CATALOGNUMBER")
    result.barcode = _txxx(tags, "BARCODE")
    result.release_country = _txxx(tags, "RELEASECOUNTRY")
    result.media = _txxx(tags, "MEDIA")
    result.script = _txxx(tags, "SCRIPT")
    result.language = _txxx(tags, "LANGUAGE")
    result.conductor = _txxx(tags, "CONDUCTOR")
    result.orchestra = _txxx(tags, "ORCHESTRA")
    result.ensemble = _txxx(tags, "ENSEMBLE")
    result.work = _txxx(tags, "WORK")
    result.movement = _txxx(tags, "MOVEMENT")
    result.movement_number = _txxx(tags, "MOVEMENTNUMBER")
    result.replaygain_track_gain = _txxx(tags, "REPLAYGAIN_TRACK_GAIN")
    result.replaygain_track_peak = _txxx(tags, "REPLAYGAIN_TRACK_PEAK")
    result.replaygain_album_gain = _txxx(tags, "REPLAYGAIN_ALBUM_GAIN")
    result.replaygain_album_peak = _txxx(tags, "REPLAYGAIN_ALBUM_PEAK")
    return result


def _mp4_compilation(audio: Any) -> bool:
    """Return the MP4 compilation flag the way Apple Music reads it.

    mutagen turns any non-zero integer into True, but Music only treats the
    value 1 as a compilation. A stray text "0" (0x30) is therefore false.
    """
    try:
        with open(audio.filename, "rb") as handle:
            cpil = Atoms(handle).path(b"moov", b"udta", b"meta", b"ilst", b"cpil")[-1]
            handle.seek(cpil.offset + 8)
            size, name = struct.unpack(">I4s", handle.read(8))
            if name != b"data":
                return False
            handle.seek(cpil.offset + 8 + 8 + 8)
            payload = handle.read(size - 16)
        return bool(payload) and payload[-1] == 1
    except (OSError, KeyError, IndexError, struct.error, AttributeError):
        return bool(audio.tags.get("cpil")) if audio.tags is not None else False


def _read_mp4(audio: Any) -> TagSet:
    tags = audio.tags
    result = TagSet()
    if tags is None:
        return result

    def value(key: str) -> Any:
        return tags.get(key)

    def first(key: str) -> str:
        values = _values(value(key))
        return values[0] if values else ""

    result.title = first("\xa9nam")
    result.artists = _values(value("\xa9ART"))
    result.album_artist = first("aART")
    result.album = first("\xa9alb")
    result.genres = _values(value("\xa9gen"))
    result.year = first("\xa9day")
    trkn = value("trkn") or []
    if trkn:
        pair = trkn[0]
        result.track = str(pair[0]) if pair[0] else ""
        result.track_total = str(pair[1]) if pair[1] else ""
    disk = value("disk") or []
    if disk:
        pair = disk[0]
        result.disc = str(pair[0]) if pair[0] else ""
        result.disc_total = str(pair[1]) if pair[1] else ""
    result.comment = first("\xa9cmt")
    result.composer = first("\xa9wrt")
    result.lyrics = first("\xa9lyr")
    result.compilation = _mp4_compilation(audio)
    result.sort_title = first("sonm")
    result.sort_artist = first("soar")
    result.sort_album_artist = first("soaa")
    result.sort_album = first("soal")

    def freeform(name: str) -> str:
        item = tags.get(f"----:com.apple.iTunes:{name}")
        if not item:
            return ""
        raw = item[0]
        if isinstance(raw, MP4FreeForm):
            return raw.decode("utf-8", "replace")
        return _clean(raw)

    result.isrc = freeform("ISRC")
    result.bpm = freeform("BPM")
    result.musical_key = freeform("KEY")
    result.original_date = freeform("ORIGINALDATE")
    result.musicbrainz_recording_id = freeform("MusicBrainz Track Id")
    result.musicbrainz_release_id = freeform("MusicBrainz Album Id")
    result.musicbrainz_artist_id = freeform("MusicBrainz Artist Id")
    result.label = freeform("LABEL")
    result.catalog_number = freeform("CATALOGNUMBER")
    result.barcode = freeform("BARCODE")
    result.release_country = freeform("RELEASECOUNTRY")
    result.media = freeform("MEDIA")
    result.script = freeform("SCRIPT")
    result.language = freeform("LANGUAGE")
    result.conductor = freeform("CONDUCTOR")
    result.orchestra = freeform("ORCHESTRA")
    result.ensemble = freeform("ENSEMBLE")
    result.work = freeform("WORK")
    result.movement = freeform("MOVEMENT")
    result.movement_number = freeform("MOVEMENTNUMBER")
    result.replaygain_track_gain = freeform("REPLAYGAIN_TRACK_GAIN")
    result.replaygain_track_peak = freeform("REPLAYGAIN_TRACK_PEAK")
    result.replaygain_album_gain = freeform("REPLAYGAIN_ALBUM_GAIN")
    result.replaygain_album_peak = freeform("REPLAYGAIN_ALBUM_PEAK")
    return result


def _read_ape(audio: Any) -> TagSet:
    tags = audio.tags
    result = TagSet()
    if tags is None:
        return result

    def first(*keys: str) -> str:
        for key in keys:
            item = tags.get(key)
            if item is not None:
                return _clean(item)
        return ""

    result.title = first("Title")
    result.artists = [part.strip() for part in first("Artist").split(";") if part.strip()]
    result.album_artist = first("Album Artist")
    result.album = first("Album")
    result.genres = [part.strip() for part in first("Genre").split(";") if part.strip()]
    result.year = first("Year")
    result.original_date = first("Original Date")
    result.track, result.track_total = _pair(first("Track"))
    result.disc, result.disc_total = _pair(first("Disc"))
    result.comment = first("Comment")
    result.composer = first("Composer")
    result.lyricist = first("Lyricist")
    result.lyrics = first("Lyrics")
    result.isrc = first("ISRC")
    result.bpm = first("BPM")
    result.musical_key = first("Key")
    result.compilation = first("Compilation").lower() in {"1", "true", "yes"}
    result.sort_title = first("Title Sort")
    result.sort_artist = first("Artist Sort")
    result.sort_album_artist = first("Album Artist Sort")
    result.sort_album = first("Album Sort")
    result.musicbrainz_recording_id = first("MusicBrainz Track Id")
    result.musicbrainz_release_id = first("MusicBrainz Album Id")
    result.musicbrainz_artist_id = first("MusicBrainz Artist Id")
    result.label = first("Label")
    result.catalog_number = first("Catalog Number")
    result.barcode = first("Barcode")
    result.release_country = first("Release Country")
    result.media = first("Media")
    result.script = first("Script")
    result.language = first("Language")
    result.conductor = first("Conductor")
    result.orchestra = first("Orchestra")
    result.ensemble = first("Ensemble")
    result.work = first("Work")
    result.movement = first("Movement")
    result.movement_number = first("Movement Number")
    result.replaygain_track_gain = first("REPLAYGAIN_TRACK_GAIN")
    result.replaygain_track_peak = first("REPLAYGAIN_TRACK_PEAK")
    result.replaygain_album_gain = first("REPLAYGAIN_ALBUM_GAIN")
    result.replaygain_album_peak = first("REPLAYGAIN_ALBUM_PEAK")
    return result


def _read_artwork(audio: Any, kind: str) -> list[Artwork]:
    pictures: list[Artwork] = []
    if kind == "flac":
        for picture in getattr(audio, "pictures", []):
            pictures.append(
                _artwork_meta(
                    bytes(picture.data),
                    mime=getattr(picture, "mime", ""),
                    kind="front" if getattr(picture, "type", 3) == 3 else "other",
                    description=getattr(picture, "desc", ""),
                )
            )
        return pictures
    if kind == "vorbis":
        raw = _values(audio.tags.get("METADATA_BLOCK_PICTURE")) if audio.tags else []
        for encoded in raw:
            try:
                picture = Picture(base64.b64decode(encoded))
                pictures.append(
                    _artwork_meta(
                        bytes(picture.data),
                        mime=getattr(picture, "mime", ""),
                        kind="front" if getattr(picture, "type", 3) == 3 else "other",
                        description=getattr(picture, "desc", ""),
                    )
                )
            except Exception:
                continue
        return pictures
    if kind == "id3":
        tags = audio.tags
        if tags is None:
            return pictures
        for frame in tags.getall("APIC"):
            picture_type = int(getattr(frame, "type", 3))
            pictures.append(
                _artwork_meta(
                    bytes(frame.data),
                    mime=str(getattr(frame, "mime", "")),
                    kind="front" if picture_type == 3 else "back" if picture_type == 4 else "other",
                    description=str(getattr(frame, "desc", "")),
                )
            )
        return pictures
    if kind == "mp4":
        tags = audio.tags
        if tags is None:
            return pictures
        for cover in tags.get("covr", []):
            mime = "image/png" if cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
            pictures.append(_artwork_meta(bytes(cover), mime=mime))
        return pictures
    if kind == "ape":
        tags = audio.tags
        if tags is None:
            return pictures
        item = tags.get("Cover Art (Front)")
        if item is None:
            return pictures
        raw = bytes(item.value)
        marker = raw.find(b"\x00")
        data = raw[marker + 1 :] if marker >= 0 else raw
        pictures.append(_artwork_meta(data))
    return pictures


def read_artwork(path: str | Path) -> list[Artwork]:
    """Return embedded artwork from a file."""
    audio = mutagen.File(str(path), easy=False)
    if audio is None:
        return []
    return _read_artwork(audio, _classify(audio))


def read_metadata(path: str | Path) -> TrackMetadata:
    """Read technical properties and canonical tags from an audio file."""
    path_value = str(Path(path))
    audio = mutagen.File(path_value, easy=False)
    if audio is None:
        raise ValueError(f"Unsupported or unreadable audio file: {path_value}")

    stat = Path(path_value).stat()
    info = getattr(audio, "info", None)
    duration = float(getattr(info, "length", 0.0) or 0.0)
    # Mutagen exposes bitrates in bits per second; store the displayed Kbps value.
    bitrate = int(getattr(info, "bitrate", 0) or 0)
    if bitrate:
        bitrate = round(bitrate / 1000)
    elif duration > 0:
        bitrate = round((stat.st_size * 8) / duration / 1000)
    sample_rate = int(getattr(info, "sample_rate", 0) or 0)
    channels = int(getattr(info, "channels", 0) or 0)
    bit_depth = int(getattr(info, "bits_per_sample", 0) or 0)
    kind = _classify(audio)
    extension = Path(path_value).suffix.lower().lstrip(".").upper()
    format_name = extension or type(audio).__name__.upper()
    codec = _codec_label(str(getattr(info, "codec", "") or type(audio).__name__), format_name)
    lossless = format_name in {"FLAC", "WAV", "AIFF", "AIF", "AIFC", "APE", "WV", "DSF", "DFF"} or (
        "ALAC" in codec.upper()
    )

    if kind in {"flac", "vorbis"}:
        tags = _read_vorbis(audio, audio.tags or {})
    elif kind == "id3":
        tags = _read_id3(audio)
    elif kind == "mp4":
        tags = _read_mp4(audio)
    elif kind == "ape":
        tags = _read_ape(audio)
    else:
        tags = TagSet()

    raw_tags: dict[str, list[str]] = {}
    if audio.tags is not None:
        if isinstance(audio.tags, ID3):
            for frame_id in audio.tags:
                values: list[str] = []
                for frame in audio.tags.getall(frame_id):
                    text = getattr(frame, "text", None)
                    if text is not None:
                        values.extend(_clean(item) for item in text if _clean(item))
                    elif getattr(frame, "data", None):
                        values.append(f"<{len(frame.data)} bytes>")
                    else:
                        values.append(str(frame))
                raw_tags[str(frame_id)] = values
        else:
            for key, value in audio.tags.items():
                raw_tags[str(key)] = _values(value)

    return TrackMetadata(
        path=path_value,
        format=format_name,
        codec=codec,
        duration=duration,
        bitrate=bitrate,
        sample_rate=sample_rate,
        channels=channels,
        bit_depth=bit_depth,
        lossless=lossless,
        file_size=stat.st_size,
        mtime=stat.st_mtime,
        tags=tags,
        artwork=_read_artwork(audio, kind),
        raw_tags=raw_tags,
    )


def _tag_values(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [_clean(item) for item in value if _clean(item)]
    text = _clean(value)
    return [text] if text else []


def apply_tag_edits(tags: TagSet, edits: Mapping[str, object]) -> TagSet:
    """Return a copy of ``tags`` with canonical edits applied."""
    updated = copy.deepcopy(tags)
    for field_name in _TAG_FIELDS:
        if field_name not in edits:
            continue
        value = edits[field_name]
        if field_name in {"artists", "genres"}:
            setattr(updated, field_name, _tag_values(value))
        elif field_name in {"track", "track_total", "disc", "disc_total"}:
            setattr(updated, field_name, _clean(value))
        elif field_name == "compilation":
            setattr(updated, field_name, bool(value))
        else:
            setattr(updated, field_name, _clean(value))
    return updated


def tagset_to_dict(tags: TagSet) -> dict[str, object]:
    """Serialize a TagSet for the operation journal."""
    return asdict(tags)


def _vc_delete(tags: Any, key: str) -> None:
    """Delete a Vorbis comment; VCommentDict.pop does not accept a default."""
    try:
        del tags[key]
    except KeyError:
        pass


def _set_vorbis(audio: Any, edits: Mapping[str, object]) -> None:
    tags = audio.tags
    if tags is None:
        audio.add_tags()
        tags = audio.tags
    key_map = {
        "title": "TITLE",
        "album_artist": "ALBUMARTIST",
        "album": "ALBUM",
        "year": "DATE",
        "original_date": "ORIGINALDATE",
        "comment": "COMMENT",
        "composer": "COMPOSER",
        "lyricist": "LYRICIST",
        "lyrics": "LYRICS",
        "isrc": "ISRC",
        "bpm": "BPM",
        "musical_key": "KEY",
        "sort_title": "TITLESORT",
        "sort_artist": "ARTISTSORT",
        "sort_album_artist": "ALBUMARTISTSORT",
        "sort_album": "ALBUMSORT",
        "musicbrainz_recording_id": "MUSICBRAINZ_TRACKID",
        "musicbrainz_release_id": "MUSICBRAINZ_ALBUMID",
        "musicbrainz_artist_id": "MUSICBRAINZ_ARTISTID",
        "label": "LABEL",
        "catalog_number": "CATALOGNUMBER",
        "barcode": "BARCODE",
        "release_country": "RELEASECOUNTRY",
        "media": "MEDIA",
        "script": "SCRIPT",
        "language": "LANGUAGE",
        "conductor": "CONDUCTOR",
        "orchestra": "ORCHESTRA",
        "ensemble": "ENSEMBLE",
        "work": "WORK",
        "movement": "MOVEMENT",
        "movement_number": "MOVEMENTNUMBER",
        "replaygain_track_gain": "REPLAYGAIN_TRACK_GAIN",
        "replaygain_track_peak": "REPLAYGAIN_TRACK_PEAK",
        "replaygain_album_gain": "REPLAYGAIN_ALBUM_GAIN",
        "replaygain_album_peak": "REPLAYGAIN_ALBUM_PEAK",
    }
    for field_name, key in key_map.items():
        if field_name not in edits:
            continue
        values = _tag_values(edits[field_name])
        if values:
            tags[key] = values
        else:
            _vc_delete(tags, key)

    if "artists" in edits:
        values = _tag_values(edits["artists"])
        if values:
            tags["ARTIST"] = values
        else:
            _vc_delete(tags, "ARTIST")
    if "genres" in edits:
        values = _tag_values(edits["genres"])
        if values:
            tags["GENRE"] = values
        else:
            _vc_delete(tags, "GENRE")
    if "track" in edits or "track_total" in edits:
        track = _clean(edits.get("track", ""))
        total = _clean(edits.get("track_total", ""))
        if track:
            tags["TRACKNUMBER"] = [track]
        else:
            _vc_delete(tags, "TRACKNUMBER")
        if total:
            tags["TRACKTOTAL"] = [total]
        else:
            _vc_delete(tags, "TRACKTOTAL")
    if "disc" in edits or "disc_total" in edits:
        disc = _clean(edits.get("disc", ""))
        total = _clean(edits.get("disc_total", ""))
        if disc:
            tags["DISCNUMBER"] = [disc]
        else:
            _vc_delete(tags, "DISCNUMBER")
        if total:
            tags["DISCTOTAL"] = [total]
        else:
            _vc_delete(tags, "DISCTOTAL")
    if "compilation" in edits:
        tags["COMPILATION"] = ["1" if edits["compilation"] else "0"]
    audio.save()


_ID3_TEXT_FRAMES: dict[str, type] = {
    "title": TIT2,
    "album_artist": TPE2,
    "album": TALB,
    "year": TDRC,
    "original_date": TDOR,
    "composer": TCOM,
    "lyricist": TEXT,
    "isrc": TSRC,
    "bpm": TBPM,
    "musical_key": TKEY,
    "sort_title": TSOT,
    "sort_artist": TSOA,
    "sort_album_artist": TSO2,
    "sort_album": TSOP,
}

_ID3_TXXX: dict[str, str] = {
    "musicbrainz_recording_id": "MusicBrainz Track Id",
    "musicbrainz_release_id": "MusicBrainz Album Id",
    "musicbrainz_artist_id": "MusicBrainz Artist Id",
    "label": "LABEL",
    "catalog_number": "CATALOGNUMBER",
    "barcode": "BARCODE",
    "release_country": "RELEASECOUNTRY",
    "media": "MEDIA",
    "script": "SCRIPT",
    "language": "LANGUAGE",
    "conductor": "CONDUCTOR",
    "orchestra": "ORCHESTRA",
    "ensemble": "ENSEMBLE",
    "work": "WORK",
    "movement": "MOVEMENT",
    "movement_number": "MOVEMENTNUMBER",
    "replaygain_track_gain": "REPLAYGAIN_TRACK_GAIN",
    "replaygain_track_peak": "REPLAYGAIN_TRACK_PEAK",
    "replaygain_album_gain": "REPLAYGAIN_ALBUM_GAIN",
    "replaygain_album_peak": "REPLAYGAIN_ALBUM_PEAK",
}


def _ensure_id3(audio: Any) -> ID3:
    if audio.tags is None:
        audio.add_tags()
    if not isinstance(audio.tags, ID3):
        raise ValueError("Could not create ID3 tags")
    return audio.tags


def _set_id3(audio: Any, edits: Mapping[str, object]) -> None:
    tags = _ensure_id3(audio)
    for field_name, frame_class in _ID3_TEXT_FRAMES.items():
        if field_name not in edits:
            continue
        values = _tag_values(edits[field_name])
        frame_id = frame_class.__name__
        if not isinstance(frame_id, str):
            frame_id = frame_class.__name__
        tags.delall(frame_id)
        if values:
            tags.add(frame_class(encoding=3, text=values))

    if "artists" in edits:
        values = _tag_values(edits["artists"])
        tags.delall("TPE1")
        if values:
            tags.add(TPE1(encoding=3, text=values))
    if "genres" in edits:
        values = _tag_values(edits["genres"])
        tags.delall("TCON")
        if values:
            tags.add(TCON(encoding=3, text=values))
    if "comment" in edits:
        tags.delall("COMM")
        value = _clean(edits["comment"])
        if value:
            tags.add(COMM(encoding=3, lang="eng", desc="", text=[value]))
    if "lyrics" in edits:
        tags.delall("USLT")
        value = _clean(edits["lyrics"])
        if value:
            tags.add(USLT(encoding=3, lang="eng", desc="", text=value))
    if "track" in edits or "track_total" in edits:
        tags.delall("TRCK")
        track = _clean(edits.get("track", ""))
        total = _clean(edits.get("track_total", ""))
        if track or total:
            text = f"{track or '0'}/{total}" if total else track
            tags.add(TRCK(encoding=3, text=[text]))
    if "disc" in edits or "disc_total" in edits:
        tags.delall("TPOS")
        disc = _clean(edits.get("disc", ""))
        total = _clean(edits.get("disc_total", ""))
        if disc or total:
            text = f"{disc or '0'}/{total}" if total else disc
            tags.add(TPOS(encoding=3, text=[text]))
    if "compilation" in edits:
        tags.delall("TCMP")
        tags.add(TCMP(encoding=3, text=["1" if edits["compilation"] else "0"]))
    for field_name, description in _ID3_TXXX.items():
        if field_name not in edits:
            continue
        tags.delall(f"TXXX:{description}")
        value = _clean(edits[field_name])
        if value:
            tags.add(TXXX(encoding=3, desc=description, text=[value]))
    audio.save(v2_version=4)


_MP4_KEYS = {
    "title": "\xa9nam",
    "album_artist": "aART",
    "album": "\xa9alb",
    "year": "\xa9day",
    "comment": "\xa9cmt",
    "composer": "\xa9wrt",
    "lyrics": "\xa9lyr",
    "sort_title": "sonm",
    "sort_artist": "soar",
    "sort_album_artist": "soaa",
    "sort_album": "soal",
}

_MP4_FREEFORM = {
    "original_date": "ORIGINALDATE",
    "isrc": "ISRC",
    "bpm": "BPM",
    "musical_key": "KEY",
    "musicbrainz_recording_id": "MusicBrainz Track Id",
    "musicbrainz_release_id": "MusicBrainz Album Id",
    "musicbrainz_artist_id": "MusicBrainz Artist Id",
    "label": "LABEL",
    "catalog_number": "CATALOGNUMBER",
    "barcode": "BARCODE",
    "release_country": "RELEASECOUNTRY",
    "media": "MEDIA",
    "script": "SCRIPT",
    "language": "LANGUAGE",
    "conductor": "CONDUCTOR",
    "orchestra": "ORCHESTRA",
    "ensemble": "ENSEMBLE",
    "work": "WORK",
    "movement": "MOVEMENT",
    "movement_number": "MOVEMENTNUMBER",
    "replaygain_track_gain": "REPLAYGAIN_TRACK_GAIN",
    "replaygain_track_peak": "REPLAYGAIN_TRACK_PEAK",
    "replaygain_album_gain": "REPLAYGAIN_ALBUM_GAIN",
    "replaygain_album_peak": "REPLAYGAIN_ALBUM_PEAK",
}


def _set_mp4(audio: Any, edits: Mapping[str, object]) -> None:
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    if not isinstance(tags, MP4Tags):
        raise ValueError("Unexpected tag type for MP4 container")
    for field_name, key in _MP4_KEYS.items():
        if field_name not in edits:
            continue
        value = _clean(edits[field_name])
        if value:
            tags[key] = [value]
        else:
            tags.pop(key, None)
    if "artists" in edits:
        values = _tag_values(edits["artists"])
        if values:
            tags["\xa9ART"] = values
        else:
            tags.pop("\xa9ART", None)
    if "genres" in edits:
        values = _tag_values(edits["genres"])
        if values:
            tags["\xa9gen"] = values
        else:
            tags.pop("\xa9gen", None)
    if "track" in edits or "track_total" in edits:
        track = _int_value(edits.get("track", ""))
        total = _int_value(edits.get("track_total", ""))
        if track or total:
            tags["trkn"] = [(track, total)]
        else:
            tags.pop("trkn", None)
    if "disc" in edits or "disc_total" in edits:
        disc = _int_value(edits.get("disc", ""))
        total = _int_value(edits.get("disc_total", ""))
        if disc or total:
            tags["disk"] = [(disc, total)]
        else:
            tags.pop("disk", None)
    if "compilation" in edits:
        tags["cpil"] = bool(edits["compilation"])
    for field_name, name in _MP4_FREEFORM.items():
        if field_name not in edits:
            continue
        key = f"----:com.apple.iTunes:{name}"
        value = _clean(edits[field_name])
        if value:
            tags[key] = [MP4FreeForm(value.encode("utf-8"))]
        else:
            tags.pop(key, None)
    audio.save()


_APE_KEYS = {
    "title": "Title",
    "album_artist": "Album Artist",
    "album": "Album",
    "year": "Year",
    "original_date": "Original Date",
    "comment": "Comment",
    "composer": "Composer",
    "lyricist": "Lyricist",
    "lyrics": "Lyrics",
    "isrc": "ISRC",
    "bpm": "BPM",
    "musical_key": "Key",
    "sort_title": "Title Sort",
    "sort_artist": "Artist Sort",
    "sort_album_artist": "Album Artist Sort",
    "sort_album": "Album Sort",
    "musicbrainz_recording_id": "MusicBrainz Track Id",
    "musicbrainz_release_id": "MusicBrainz Album Id",
    "musicbrainz_artist_id": "MusicBrainz Artist Id",
    "label": "Label",
    "catalog_number": "Catalog Number",
    "barcode": "Barcode",
    "release_country": "Release Country",
    "media": "Media",
    "script": "Script",
    "language": "Language",
    "conductor": "Conductor",
    "orchestra": "Orchestra",
    "ensemble": "Ensemble",
    "work": "Work",
    "movement": "Movement",
    "movement_number": "Movement Number",
    "replaygain_track_gain": "REPLAYGAIN_TRACK_GAIN",
    "replaygain_track_peak": "REPLAYGAIN_TRACK_PEAK",
    "replaygain_album_gain": "REPLAYGAIN_ALBUM_GAIN",
    "replaygain_album_peak": "REPLAYGAIN_ALBUM_PEAK",
}


def _set_ape(audio: Any, edits: Mapping[str, object]) -> None:
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    if not isinstance(tags, APEv2):
        raise ValueError("Unexpected tag type for APE container")
    for field_name, key in _APE_KEYS.items():
        if field_name not in edits:
            continue
        value = _clean(edits[field_name])
        if value:
            tags[key] = value
        else:
            tags.pop(key, None)
    if "artists" in edits:
        values = _tag_values(edits["artists"])
        if values:
            tags["Artist"] = "; ".join(values)
        else:
            tags.pop("Artist", None)
    if "genres" in edits:
        values = _tag_values(edits["genres"])
        if values:
            tags["Genre"] = "; ".join(values)
        else:
            tags.pop("Genre", None)
    if "track" in edits or "track_total" in edits:
        track = _clean(edits.get("track", ""))
        total = _clean(edits.get("track_total", ""))
        if track or total:
            tags["Track"] = f"{track or '0'}/{total}" if total else track
        else:
            tags.pop("Track", None)
    if "disc" in edits or "disc_total" in edits:
        disc = _clean(edits.get("disc", ""))
        total = _clean(edits.get("disc_total", ""))
        if disc or total:
            tags["Disc"] = f"{disc or '0'}/{total}" if total else disc
        else:
            tags.pop("Disc", None)
    if "compilation" in edits:
        tags["Compilation"] = "1" if edits["compilation"] else "0"
    audio.save()


def write_tags(path: str | Path, edits: Mapping[str, object]) -> TrackMetadata:
    """Apply canonical tag edits and return the re-read metadata.

    Only fields present in ``edits`` are changed. Unknown tags are left alone.
    """
    path_value = str(Path(path))
    audio = mutagen.File(path_value, easy=False)
    if audio is None:
        raise ValueError(f"Unsupported or unreadable audio file: {path_value}")
    kind = _classify(audio)
    if kind in {"flac", "vorbis"}:
        _set_vorbis(audio, edits)
    elif kind == "id3":
        _set_id3(audio, edits)
    elif kind == "mp4":
        _set_mp4(audio, edits)
    elif kind == "ape":
        _set_ape(audio, edits)
    else:
        raise ValueError(f"Tag writing is not implemented for {path_value}")
    return read_metadata(path_value)


def write_artwork(
    path: str | Path,
    data: bytes,
    *,
    mime: str = "",
    kind: str = "front",
    description: str = "",
) -> None:
    """Embed artwork, replacing pictures of the same kind."""
    path_value = str(Path(path))
    audio = mutagen.File(path_value, easy=False)
    if audio is None:
        raise ValueError(f"Unsupported or unreadable audio file: {path_value}")
    artwork = _artwork_meta(data, mime=mime, kind=kind, description=description)
    picture_type = 3 if kind == "front" else 4 if kind == "back" else 0
    audio_kind = _classify(audio)
    if audio_kind == "flac":
        audio.clear_pictures()
        picture = Picture()
        picture.type = picture_type
        picture.mime = artwork.mime
        picture.desc = description
        picture.width = artwork.width or 0
        picture.height = artwork.height or 0
        picture.depth = 24
        picture.data = data
        audio.add_picture(picture)
        audio.save()
        return
    if audio_kind == "vorbis":
        if audio.tags is None:
            audio.add_tags()
        picture = Picture()
        picture.type = picture_type
        picture.mime = artwork.mime
        picture.desc = description
        picture.width = artwork.width or 0
        picture.height = artwork.height or 0
        picture.depth = 24
        picture.data = data
        audio.tags["METADATA_BLOCK_PICTURE"] = [base64.b64encode(picture.write()).decode("ascii")]
        audio.save()
        return
    if audio_kind == "id3":
        tags = _ensure_id3(audio)
        tags.delall("APIC")
        tags.add(
            APIC(
                encoding=3,
                mime=artwork.mime,
                type=picture_type,
                desc=description,
                data=data,
            )
        )
        audio.save(v2_version=4)
        return
    if audio_kind == "mp4":
        tags = audio.tags
        if tags is None:
            tags = audio.add_tags()
        if not isinstance(tags, MP4Tags):
            raise ValueError("Unexpected tag type for MP4 container")
        image_format = MP4Cover.FORMAT_PNG if artwork.mime == "image/png" else MP4Cover.FORMAT_JPEG
        tags["covr"] = [MP4Cover(data, imageformat=image_format)]
        audio.save()
        return
    if audio_kind == "ape":
        tags = audio.tags
        if tags is None:
            tags = audio.add_tags()
        if not isinstance(tags, APEv2):
            raise ValueError("Unexpected tag type for APE container")
        filename = "cover.png" if artwork.mime == "image/png" else "cover.jpg"
        tags["Cover Art (Front)"] = filename.encode("ascii") + b"\x00" + data
        audio.save()
        return
    raise ValueError(f"Artwork writing is not implemented for {path_value}")


def remove_artwork(path: str | Path) -> None:
    """Remove all embedded artwork."""
    path_value = str(Path(path))
    audio = mutagen.File(path_value, easy=False)
    if audio is None:
        raise ValueError(f"Unsupported or unreadable audio file: {path_value}")
    audio_kind = _classify(audio)
    if audio_kind == "flac":
        audio.clear_pictures()
        audio.save()
    elif audio_kind == "vorbis":
        if audio.tags is not None:
            _vc_delete(audio.tags, "METADATA_BLOCK_PICTURE")
            audio.save()
    elif audio_kind == "id3":
        if audio.tags is not None:
            audio.tags.delall("APIC")
            audio.save(v2_version=4)
    elif audio_kind == "mp4":
        if audio.tags is not None:
            audio.tags.pop("covr", None)
            audio.save()
    elif audio_kind == "ape":
        if audio.tags is not None:
            audio.tags.pop("Cover Art (Front)", None)
            audio.save()
    else:
        raise ValueError(f"Artwork removal is not implemented for {path_value}")
