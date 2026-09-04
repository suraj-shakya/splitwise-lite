"""Structural assertions over the static shell in `app/`.

Standard library only, and nothing here imports `splitwise_lite`: the shell is
deliberately independent of the domain layer, so a test that reached into the
package would quietly undo that.

Paths are resolved from this file, never from the current working directory, so
the suite passes from anywhere.
"""

from __future__ import annotations

import importlib.util
import struct
import zlib
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"
ICONS = APP / "icons"
SCRIPTS = REPO / "scripts"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# name -> declared pixel size. The four icons the manifest and the HTML point at.
ICON_SIZES = {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "icon-maskable-512.png": 512,
    "apple-touch-icon-180.png": 180,
}


def load_script(name: str) -> ModuleType:
    """Import a file from `scripts/`, which is not a package."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_ihdr(data: bytes) -> dict[str, int]:
    """Parse a PNG's IHDR header. Exactly what a browser reads to size an icon."""
    assert data[:8] == PNG_SIGNATURE
    length, kind = struct.unpack(">I4s", data[8:16])
    assert kind == b"IHDR"
    assert length == 13
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", data[16:29]
    )
    return {
        "width": width,
        "height": height,
        "depth": depth,
        "colour_type": colour,
        "compression": compression,
        "filter": filtering,
        "interlace": interlace,
    }


def decode_rgb(data: bytes) -> tuple[int, list[list[tuple[int, int, int]]]]:
    """Decode an unfiltered 8-bit RGB PNG into rows of (r, g, b) pixels."""
    header = read_ihdr(data)
    assert header["colour_type"] == 2
    assert header["depth"] == 8
    assert header["interlace"] == 0

    payload = bytearray()
    offset = 8
    while offset < len(data):
        length, kind = struct.unpack(">I4s", data[offset : offset + 8])
        if kind == b"IDAT":
            payload += data[offset + 8 : offset + 8 + length]
        offset += 12 + length

    raw = zlib.decompress(bytes(payload))
    width = header["width"]
    stride = width * 3
    rows = []
    for y in range(header["height"]):
        start = y * (stride + 1)
        assert raw[start] == 0, "every row is written with filter type 0"
        line = raw[start + 1 : start + 1 + stride]
        rows.append([tuple(line[x * 3 : x * 3 + 3]) for x in range(width)])
    return width, rows


# --- Icons -----------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(ICON_SIZES))
def test_icon_file_exists(name: str) -> None:
    assert (ICONS / name).is_file()


@pytest.mark.parametrize("name, size", sorted(ICON_SIZES.items()))
def test_icon_pixel_dimensions_match_its_name(name: str, size: int) -> None:
    header = read_ihdr((ICONS / name).read_bytes())
    assert (header["width"], header["height"]) == (size, size)


@pytest.mark.parametrize("name", sorted(ICON_SIZES))
def test_icon_is_eight_bit_rgb_without_an_alpha_channel(name: str) -> None:
    # Colour type 2 makes transparency structurally impossible: Android's maskable
    # crop would show transparent corners, and iOS renders alpha as black.
    header = read_ihdr((ICONS / name).read_bytes())
    assert header["colour_type"] == 2
    assert header["depth"] == 8


@pytest.mark.parametrize("name", sorted(ICON_SIZES))
def test_icon_background_reaches_every_edge(name: str) -> None:
    width, rows = decode_rgb((ICONS / name).read_bytes())
    background = rows[0][0]
    edges = set(rows[0]) | set(rows[-1])
    for row in rows:
        edges.add(row[0])
        edges.add(row[-1])
    assert edges == {background}


def test_maskable_mark_sits_inside_the_central_sixty_percent() -> None:
    # Android crops a maskable icon to a circle covering the middle 80%. A mark
    # inside the middle 60% survives that crop on every device.
    width, rows = decode_rgb((ICONS / "icon-maskable-512.png").read_bytes())
    background = rows[0][0]
    low = int(width * 0.2)
    high = int(width * 0.8)
    outside = set()
    for y, row in enumerate(rows):
        for x, pixel in enumerate(row):
            if low <= x < high and low <= y < high:
                continue
            outside.add(pixel)
    assert outside == {background}


def test_icons_are_reproducible_from_the_generator() -> None:
    # `uv run python scripts/make_icons.py` must leave `git status` clean, so the
    # committed bytes are exactly what the generator produces today.
    make_icons = load_script("make_icons")
    for name, size in sorted(ICON_SIZES.items()):
        assert make_icons.render(name) == (ICONS / name).read_bytes()


def test_generator_declares_the_same_four_icons() -> None:
    make_icons = load_script("make_icons")
    assert sorted(make_icons.ICONS) == sorted(ICON_SIZES)
    for name, size in sorted(ICON_SIZES.items()):
        assert make_icons.ICONS[name].size == size
