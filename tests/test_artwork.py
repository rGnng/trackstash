"""Artwork normalization tests."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from trackstash.core.artwork import normalize_artwork


def _png(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(buffer, "PNG")
    return buffer.getvalue()


def test_artwork_crops_square_and_limits_long_edge() -> None:
    normalized = normalize_artwork(_png(2000, 1000), max_size=1000, quality=90, aspect="crop")
    with Image.open(BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.size == (1000, 1000)


def test_artwork_can_preserve_original_aspect_ratio() -> None:
    normalized = normalize_artwork(_png(2000, 1000), max_size=1000, quality=90, aspect="original")
    with Image.open(BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.size == (1000, 500)


def test_artwork_can_fit_whole_image_into_square() -> None:
    normalized = normalize_artwork(_png(2000, 1000), max_size=1000, quality=90, aspect="fit")
    with Image.open(BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.size == (1000, 1000)
