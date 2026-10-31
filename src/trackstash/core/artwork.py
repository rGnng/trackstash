"""Album artwork cache generation."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from trackstash.core.metadata import Artwork

DEFAULT_COVER_SIZE = 500
DEFAULT_JPEG_QUALITY = 80


def write_album_cover(
    artwork: Artwork | None,
    album_id: str,
    cache_dir: str | Path,
    *,
    size: int = DEFAULT_COVER_SIZE,
    quality: int = DEFAULT_JPEG_QUALITY,
) -> Path | None:
    """Write a normalized JPEG cover to ``<cache_dir>/<ALBUM-ID>.jpg``."""
    if artwork is None or not artwork.data:
        return None
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{album_id.upper()}.jpg"
    try:
        with Image.open(BytesIO(artwork.data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            temporary = destination.with_suffix(".jpg.tmp")
            image.save(temporary, "JPEG", quality=quality, optimize=True)
            temporary.replace(destination)
            return destination
    except Exception:
        return None


def cover_path(album_id: str, cache_dir: str | Path) -> Path:
    """Return the expected cache path for an album."""
    return Path(cache_dir) / f"{album_id.upper()}.jpg"
