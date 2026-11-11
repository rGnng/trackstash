"""Tag-driven path templates and filesystem-safe sanitization."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path

from trackstash.core.metadata import TagSet, TrackMetadata

DEFAULT_TEMPLATE = "{artist_folder}/{album}/{disc_prefix}{track_prefix}{title}"
LEGACY_DEFAULT_TEMPLATE = "{album_artist}/{album}/{disc_dir}{track:02} {title}"

MAX_COMPONENT_UNITS = 253

_TOKEN_RE = re.compile(r"\{([a-zA-Z_]+)(?::(\d+))?(?:\|([^}]*))?\}")
_STRUCTURAL_TOKENS = {"disc_dir", "disc_prefix", "track_prefix"}
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f\u2018\u2019\u201c\u201d]')
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def clean_value(value: str) -> str:
    """Make one tag value safe for a path component.

    Separators and reserved characters, plus curly quotes, become underscores.
    Trailing whitespace is removed. Leading whitespace is handled where the
    component starts, see ``sanitize_component``.
    """
    return _ILLEGAL.sub("_", value).rstrip()


def _units(value: str) -> int:
    """Length in UTF-16 code units, which is how the file system counts names."""
    return len(value.encode("utf-16-le")) // 2


def _truncate_units(value: str, limit: int) -> str:
    """Cut a string to at most ``limit`` UTF-16 code units, keeping characters whole."""
    if _units(value) <= limit:
        return value
    kept: list[str] = []
    used = 0
    for character in value:
        width = 2 if ord(character) > 0xFFFF else 1
        if used + width > limit:
            break
        kept.append(character)
        used += width
    return "".join(kept).rstrip()


def sanitize_component(value: str, *, final: bool = False) -> str:
    """Return a single path component that is safe on macOS and Windows.

    Matches Apple Music: a leading whitespace character becomes an underscore
    (only that one character), trailing whitespace is removed, and internal
    spacing is kept. A trailing dot becomes an underscore in directory names,
    but the final component keeps it because the extension is appended later.
    A reserved name keeps its length with its last character replaced by an
    underscore, in upper case (``CON`` and ``con`` both become ``CO_``).
    """
    cleaned = _ILLEGAL.sub("_", value).rstrip()
    if cleaned[:1].isspace() or cleaned[:1] == ".":
        cleaned = "_" + cleaned[1:]
    if not final and cleaned.endswith("."):
        cleaned = cleaned[:-1] + "_"
    if not cleaned:
        cleaned = "_"
    stem = cleaned.split(".", 1)[0]
    if stem.rstrip(" ").upper() in _RESERVED:
        cleaned = stem.upper()[:-1] + "_" + cleaned[len(stem) :]
    return cleaned


def sanitize_relative_path(value: str) -> str:
    """Sanitize each segment of a relative path."""
    segments = [part for part in value.replace("\\", "/").split("/")]
    segments = [
        segment for segment in segments if segment.strip() and segment.strip() not in {".", ".."}
    ]
    if not segments:
        return ""
    *directories, last = segments
    parts = [
        _truncate_units(sanitize_component(segment), MAX_COMPONENT_UNITS) for segment in directories
    ]
    parts.append(sanitize_component(last, final=True))
    return "/".join(parts)


def _number(value: str) -> int:
    return int(value) if value.isdigit() else 0


def _split_pair(value: str) -> tuple[str, str]:
    """Split a "N/M" tag value (common in ID3 TRCK and TPOS) into its parts."""
    head, _, tail = value.strip().partition("/")
    return head.strip(), tail.strip()


def _disc_prefix(disc: str, disc_total: str) -> str:
    """Return "N-" for a real disc number, unless the album is a single disc (1/1)."""
    disc_number, disc_of = _split_pair(disc)
    total_text = _split_pair(disc_total)[0] or disc_of
    number = _number(disc_number)
    if number <= 0 or _number(total_text) == 1:
        return ""
    return f"{number}-"


def _track_prefix(track: str) -> str:
    number = _number(_split_pair(track)[0])
    return f"{number:02d} " if number > 0 else ""


_YEAR_PREFIX = re.compile(r"^(\d{4}|\d{2})(?!\d)")


def _music_year(value: str) -> str:
    text = value.strip()
    if not text or text == "0":
        return ""
    match = _YEAR_PREFIX.match(text)
    return match.group(1) if match else text


def _music_genre(tags: TagSet) -> str:
    return tags.genres[-1] if tags.genres else ""


def _music_artist(tags: TagSet) -> str:
    return tags.primary_artist if tags.artists else tags.album_artist


def _token_values(tags: TagSet, metadata: TrackMetadata) -> dict[str, str]:
    disc_number, disc_of = _split_pair(tags.disc)
    multi_disc = _number(_split_pair(tags.disc_total)[0] or disc_of) > 1 or _number(disc_number) > 1
    disc_label = disc_number
    source_stem = Path(metadata.path).stem
    return {
        "title": tags.title or source_stem or "Unknown Title",
        "artist": _music_artist(tags),
        "album_artist": tags.album_artist_or_primary,
        "artist_folder": "Compilations" if tags.compilation else tags.album_artist_or_primary,
        "album": tags.album or "Unknown Album",
        "year": _music_year(tags.year),
        "date": _music_year(tags.year),
        "genre": _music_genre(tags),
        "composer": tags.composer,
        "comment": tags.comment,
        "label": tags.label,
        "catalog": tags.catalog_number,
        "track": tags.track,
        "track_total": tags.track_total,
        "track_prefix": _track_prefix(tags.track),
        "disc": tags.disc,
        "disc_total": tags.disc_total,
        "disc_dir": f"Disc {disc_label}/" if multi_disc else "",
        "disc_prefix": _disc_prefix(tags.disc, tags.disc_total),
        "format": metadata.format.lower(),
        "bitrate": str(metadata.bitrate),
        "ext": Path(metadata.path).suffix.lstrip("."),
    }


def render_template(
    template: str,
    tags: TagSet,
    metadata: TrackMetadata,
    *,
    extension: str | None = None,
) -> str:
    """Render a relative destination path from tags and technical metadata."""
    values = _token_values(tags, metadata)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        width = int(match.group(2)) if match.group(2) else 0
        fallback = match.group(3)
        if key not in values:
            raise ValueError(f"Unknown template token: {{{key}}}")
        value = values[key]
        if key not in _STRUCTURAL_TOKENS:
            value = clean_value(value)
        if not value:
            value = fallback if fallback is not None else ""
        if width:
            value = value.zfill(width)
        return value

    rendered = _TOKEN_RE.sub(replace, template)
    segments = [part for part in rendered.split("/")]
    segments = [
        segment for segment in segments if segment.strip() and segment.strip() not in {".", ".."}
    ]
    if not segments:
        segments = ["_"]
    *directories, last = segments
    suffix = extension if extension is not None else Path(metadata.path).suffix
    parts = [
        _truncate_units(sanitize_component(segment), MAX_COMPONENT_UNITS) for segment in directories
    ]
    final = sanitize_component(last, final=True)
    if suffix and final.lower().endswith(suffix.lower()):
        stem, ext = final[: -len(suffix)], final[-len(suffix) :]
    else:
        stem, ext = final, suffix
    budget = MAX_COMPONENT_UNITS - _units(ext)
    parts.append(_truncate_units(stem, budget) + ext)
    return unicodedata.normalize("NFC", "/".join(parts))


def with_collision_suffix(relative_path: str, index: int) -> str:
    """Append `` (n)`` before the final extension."""
    path = Path(relative_path)
    return str(path.with_name(f"{path.stem} ({index}){path.suffix}"))


def template_values(tags: TagSet, metadata: TrackMetadata) -> Mapping[str, str]:
    """Expose token values for previews and tests."""
    return _token_values(tags, metadata)
