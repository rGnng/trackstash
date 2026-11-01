"""Artwork image normalization for embedding."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps

DEFAULT_ARTWORK_MAX_SIZE = 1000
DEFAULT_ARTWORK_QUALITY = 90


def normalize_artwork(
    data: bytes,
    *,
    max_size: int = DEFAULT_ARTWORK_MAX_SIZE,
    quality: int = DEFAULT_ARTWORK_QUALITY,
    crop_square: bool = True,
) -> bytes:
    """Return a JPEG image capped by its longest edge, optionally square-cropped."""
    if not data:
        raise ValueError("The image is empty")
    try:
        with Image.open(BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            if crop_square:
                side = min(image.size)
                left = (image.width - side) // 2
                top = (image.height - side) // 2
                image = image.crop((left, top, left + side, top + side))
            image.thumbnail(
                (max(1, max_size), max(1, max_size)),
                Image.Resampling.LANCZOS,
            )
            output = BytesIO()
            image.save(output, "JPEG", quality=max(1, min(100, quality)), optimize=True)
            return output.getvalue()
    except Exception as exc:
        raise ValueError(f"Could not read artwork image: {exc}") from exc
