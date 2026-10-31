"""Deterministic identity compatible with the Tracks macOS app and WebTracks.

Core IDs are derived from MD5 over UTF-8 strings. No UUID version or variant
bits are applied. The formulas are a compatibility contract; see
``docs/COMPATIBILITY.md``.
"""

from __future__ import annotations

import hashlib
import os
import unicodedata
import uuid

__all__ = [
    "album_uuid",
    "artist_uuid",
    "canonical_path",
    "is_under",
    "library_uuid",
    "normalize_identifier",
    "normalize_name",
    "normalize_nfc",
    "normalize_relative_path",
    "relative_path",
    "song_uuid",
    "stable_uuid",
    "swift_lower",
]


def normalize_nfc(value: str) -> str:
    """Return the canonical composed form of ``value``."""
    return unicodedata.normalize("NFC", value)


def swift_lower(value: str) -> str:
    """Lowercase like Swift's locale-independent ``lowercased()``.

    Swift maps one scalar at a time. Python's ``str.lower()`` applies the
    contextual final-sigma rule, which would produce a different UUID for names
    ending in a capital sigma.
    """
    return "".join(character.lower() for character in normalize_nfc(value))


def normalize_identifier(raw: str | None) -> str:
    """Normalize a user-editable library identifier."""
    return swift_lower((raw or "").strip())


def normalize_name(raw: str | None) -> str:
    """Normalize an artist or album name."""
    return swift_lower(raw or "")


def normalize_relative_path(raw: str | None) -> str:
    """Normalize a library-relative path."""
    return normalize_nfc(raw or "").lstrip("/")


def stable_uuid(text: str) -> str:
    """Return the uppercase MD5-derived UUID for ``text``."""
    digest = hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()
    return str(uuid.UUID(hex=digest)).upper()


def song_uuid(namespace: str, relative_path_value: str) -> str:
    """Return the Tracks-compatible song UUID."""
    return stable_uuid(
        "song|"
        + normalize_identifier(namespace)
        + "|"
        + normalize_relative_path(relative_path_value)
    )


def artist_uuid(name: str) -> str:
    """Return the Tracks-compatible artist UUID."""
    return stable_uuid("artist|" + normalize_name(name))


def album_uuid(artist_id: str, title: str) -> str:
    """Return the Tracks-compatible album UUID."""
    return stable_uuid("album|" + artist_id + "|" + normalize_name(title))


def library_uuid(path: str) -> str:
    """Return the Tracks-compatible library UUID for a canonical root path."""
    return stable_uuid("library|" + canonical_path(path))


def canonical_path(path: str) -> str:
    """Expand a user path and resolve symlinks."""
    return os.path.realpath(os.path.expanduser(path))


def is_under(path: str, root: str) -> bool:
    """Return whether ``path`` is equal to or below ``root``."""
    if path == root:
        return True
    if root == "/":
        return path.startswith("/")
    return path.startswith(root.rstrip("/") + "/")


def relative_path(file_path: str, library_root: str) -> str | None:
    """Return the normalized path of ``file_path`` relative to ``library_root``."""
    file_value = canonical_path(file_path)
    root_value = canonical_path(library_root)
    if not is_under(file_value, root_value):
        return None
    if file_value == root_value:
        return ""
    root = root_value.rstrip("/")
    prefix = "/" if root == "" else root + "/"
    return normalize_relative_path(file_value[len(prefix) :])
