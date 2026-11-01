"""Tag-driven path templates and filesystem-safe sanitization."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from trackstash.core.metadata import TagSet, TrackMetadata

DEFAULT_TEMPLATE = "{album_artist}/{album}/{disc_prefix}{track:02} {title}"
LEGACY_DEFAULT_TEMPLATE = "{album_artist}/{album}/{disc_dir}{track:02} {title}"

_TOKEN_RE = re.compile(r"\{([a-zA-Z_]+)(?::(\d+))?(?:\|([^}]*))?\}")
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_component(value: str, *, max_length: int = 120) -> str:
    """Return a single path component that is safe on macOS and Windows."""
    cleaned = _ILLEGAL.sub("_", value).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "_"
    if cleaned.upper() in _RESERVED:
        cleaned = "_" + cleaned
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    return cleaned or "_"


def sanitize_relative_path(value: str) -> str:
    """Sanitize each segment of a relative path."""
    parts: list[str] = []
    for segment in value.replace("\\", "/").split("/"):
        segment = segment.strip()
        if not segment or segment in {".", ".."}:
            continue
        parts.append(sanitize_component(segment))
    return "/".join(parts)


def _number(value: str) -> int:
    return int(value) if value.isdigit() else 0


def _has_disc(value: str) -> bool:
    """Return whether a disc tag is present and not the "no disc" value."""
    text = value.strip()
    return bool(text) and (not text.isdigit() or int(text) > 0)


def _token_values(tags: TagSet, metadata: TrackMetadata) -> dict[str, str]:
    multi_disc = _number(tags.disc_total) > 1 or _number(tags.disc) > 1
    disc_label = tags.disc.strip()
    return {
        "title": tags.title or "Unknown Title",
        "artist": tags.primary_artist,
        "album_artist": tags.album_artist_or_primary,
        "album": tags.album or "Unknown Album",
        "year": tags.year,
        "date": tags.year,
        "genre": tags.primary_genre,
        "composer": tags.composer,
        "comment": tags.comment,
        "label": tags.label,
        "catalog": tags.catalog_number,
        "track": tags.track,
        "track_total": tags.track_total,
        "disc": tags.disc,
        "disc_total": tags.disc_total,
        "disc_dir": f"Disc {disc_label}/" if multi_disc else "",
        "disc_prefix": f"{disc_label}-" if _has_disc(disc_label) else "",
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
        if not value:
            value = fallback if fallback is not None else ""
        if width:
            value = value.zfill(width)
        return value

    rendered = _TOKEN_RE.sub(replace, template)
    rendered = sanitize_relative_path(rendered)
    suffix = (extension if extension is not None else Path(metadata.path).suffix).lower()
    if suffix and not Path(rendered).suffix:
        rendered += suffix
    return rendered


def with_collision_suffix(relative_path: str, index: int) -> str:
    """Append `` (n)`` before the final extension."""
    path = Path(relative_path)
    return str(path.with_name(f"{path.stem} ({index}){path.suffix}"))


def template_values(tags: TagSet, metadata: TrackMetadata) -> Mapping[str, str]:
    """Expose token values for previews and tests."""
    return _token_values(tags, metadata)
