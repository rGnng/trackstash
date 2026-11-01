"""Artwork image normalization for embedding."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, ImageStat

DEFAULT_ARTWORK_MAX_SIZE = 1000
DEFAULT_ARTWORK_QUALITY = 90
ARTWORK_ASPECTS = ("crop", "fit", "original")


def normalize_artwork(
    data: bytes,
    *,
    max_size: int = DEFAULT_ARTWORK_MAX_SIZE,
    quality: int = DEFAULT_ARTWORK_QUALITY,
    aspect: str = "crop",
) -> bytes:
    """Return a JPEG capped by its longest edge with the requested aspect mode."""
    if not data:
        raise ValueError("The image is empty")
    mode = aspect if aspect in ARTWORK_ASPECTS else "crop"
    try:
        with Image.open(BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            if mode == "crop":
                side = min(image.size)
                left = (image.width - side) // 2
                top = (image.height - side) // 2
                image = image.crop((left, top, left + side, top + side))
                image.thumbnail(
                    (max(1, max_size), max(1, max_size)),
                    Image.Resampling.LANCZOS,
                )
            elif mode == "fit":
                image.thumbnail(
                    (max(1, max_size), max(1, max_size)),
                    Image.Resampling.LANCZOS,
                )
                side = max(image.size)
                background = tuple(int(channel) for channel in ImageStat.Stat(image).mean)
                canvas = Image.new("RGB", (side, side), background)
                canvas.paste(
                    image,
                    ((side - image.width) // 2, (side - image.height) // 2),
                )
                image = canvas
            else:
                image.thumbnail(
                    (max(1, max_size), max(1, max_size)),
                    Image.Resampling.LANCZOS,
                )
            output = BytesIO()
            image.save(output, "JPEG", quality=max(1, min(100, quality)), optimize=True)
            return output.getvalue()
    except Exception as exc:
        raise ValueError(f"Could not read artwork image: {exc}") from exc
