"""Generate the TrackStash macOS application icon."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
ICONSET = ROOT / "TrackStash.iconset"
MASTER = ROOT / "app-icon.png"
ICNS = ROOT / "TrackStash.icns"


def _rounded_rectangle(
    draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill: str
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def build_master() -> Image.Image:
    size = 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    _rounded_rectangle(draw, (32, 32, 992, 992), 220, "#151A22")
    _rounded_rectangle(draw, (64, 64, 960, 960), 190, "#1E2632")

    # A compact "stash" of tracks.
    bars = (
        (210, 250, 790, 300, "#48D1B5"),
        (210, 390, 690, 440, "#48D1B5"),
        (210, 530, 820, 580, "#48D1B5"),
        (210, 670, 610, 720, "#48D1B5"),
    )
    for left, top, right, bottom, color in bars:
        _rounded_rectangle(draw, (left, top, right, bottom), 25, color)

    # Accent marker on the leading edge.
    draw.ellipse((760, 640, 860, 740), fill="#F2A65A")
    draw.ellipse((790, 670, 830, 710), fill="#1E2632")
    return image


def main() -> None:
    image = build_master()
    image.save(MASTER)
    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir()
    for size in (16, 32, 128, 256, 512):
        image.resize((size, size), Image.Resampling.LANCZOS).save(
            ICONSET / f"icon_{size}x{size}.png"
        )
        image.resize((size * 2, size * 2), Image.Resampling.LANCZOS).save(
            ICONSET / f"icon_{size}x{size}@2x.png"
        )
    subprocess.run(["iconutil", "-c", "icns", str(ICONSET), "-o", str(ICNS)], check=True)
    shutil.rmtree(ICONSET)
    print(f"Wrote {ICNS}")


if __name__ == "__main__":
    main()
