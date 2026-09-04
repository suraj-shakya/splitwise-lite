"""Regenerate the four shell icons in `app/icons/`.

    uv run python scripts/make_icons.py

Standard library only: `zlib` and `struct` are enough to write a PNG, so the icons
are reproducible without a design tool or an image library and nobody has to wonder
where a committed binary came from. Running this leaves `git status` clean.

Every icon is 8-bit RGB with no alpha channel (PNG colour type 2). Transparency is
then structurally impossible, which matters twice: Android's maskable crop would
show transparent corners, and iOS renders alpha as black.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path
from typing import NamedTuple

ICON_DIR = Path(__file__).resolve().parent.parent / "app" / "icons"

# The two colours the rest of the shell uses: --theme and --bg in app/styles.css,
# theme_color and background_color in app/manifest.json.
THEME = (0x0F, 0x76, 0x6E)
LIGHT = (0xF4, 0xF6, 0xF5)


class Icon(NamedTuple):
    """One icon: a square canvas and how much of it the mark may take up."""

    size: int
    mark: float


# The maskable icon keeps its mark inside the middle 56% of the canvas, well within
# Android's 80% safe circle and inside the 60% the task asks for. The others are not
# cropped, so their mark can run larger.
ICONS = {
    "icon-192.png": Icon(192, 0.72),
    "icon-512.png": Icon(512, 0.72),
    "icon-maskable-512.png": Icon(512, 0.56),
    "apple-touch-icon-180.png": Icon(180, 0.72),
}


def _coverage(distance: float) -> float:
    """One pixel of antialiasing: 0 outside the shape, 1 inside, a ramp between."""
    return min(1.0, max(0.0, distance + 0.5))


def _blend(weight: float) -> bytes:
    """Mix the theme colour towards the light mark colour."""
    return bytes(
        int(round(base + (mark - base) * weight)) for base, mark in zip(THEME, LIGHT)
    )


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _png(size: int, rows: list[bytes]) -> bytes:
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB, no alpha
    raw = b"".join(b"\x00" + row for row in rows)  # filter type 0 on every row
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", zlib.compress(raw, 9)),
            _chunk(b"IEND", b""),
        ]
    )


def render(name: str) -> bytes:
    """Draw one icon: a light disc, split down the middle, on a full-bleed field.

    The mark is a plain geometric shape in the theme colour family. No wordmark, no
    text rendering, no third-party logo. The background reaches every edge so a
    maskable crop can never expose a corner.
    """
    icon = ICONS[name]
    centre = icon.size / 2.0
    radius = icon.size * icon.mark / 2.0
    split = icon.size * 0.05  # half-width of the gap that splits the disc
    rows = []
    for y in range(icon.size):
        row = bytearray()
        offset_y = y + 0.5 - centre
        for x in range(icon.size):
            offset_x = x + 0.5 - centre
            disc = _coverage(radius - math.hypot(offset_x, offset_y))
            gap = _coverage(split - abs(offset_x))
            row += _blend(disc * (1.0 - gap))
        rows.append(bytes(row))
    return _png(icon.size, rows)


def main() -> None:
    for name in sorted(ICONS):
        path = ICON_DIR / name
        path.write_bytes(render(name))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
