"""Structural assertions over the static shell in `app/`.

Standard library only, and nothing here imports `splitwise_lite`: the shell is
deliberately independent of the domain layer, so a test that reached into the
package would quietly undo that.

Paths are resolved from this file, never from the current working directory, so
the suite passes from anywhere.
"""

from __future__ import annotations

import importlib.util
import json
import re
import struct
import zlib
from html.parser import HTMLParser
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
    for name in sorted(ICON_SIZES):
        generated = make_icons.render(name)
        committed = (ICONS / name).read_bytes()
        if generated == committed:
            continue
        # Report what changed instead of dumping two compressed blobs: compare the
        # header, then the pixels, and show only the first few that differ.
        assert read_ihdr(generated) == read_ihdr(committed), name
        width, fresh = decode_rgb(generated)
        _, stored = decode_rgb(committed)
        differences = [
            (x, y, fresh[y][x], stored[y][x])
            for y in range(len(fresh))
            for x in range(width)
            if fresh[y][x] != stored[y][x]
        ]
        assert (name, len(differences), differences[:3]) == (name, 0, [])
        raise AssertionError(f"{name}: pixels match but the encoded bytes differ")


def test_generator_declares_the_same_four_icons() -> None:
    make_icons = load_script("make_icons")
    assert sorted(make_icons.ICONS) == sorted(ICON_SIZES)
    for name, size in sorted(ICON_SIZES.items()):
        assert make_icons.ICONS[name].size == size


# --- The manifest ----------------------------------------------------------


def resolve_app_url(url: str) -> Path:
    """Resolve a URL used inside `app/` to the file it names.

    Every URL in the shell is relative, never rooted at `/`: that is what lets a
    later task mount the directory under a prefix without editing every file.
    """
    assert not url.startswith("/"), f"{url!r} is rooted, not relative"
    assert "://" not in url, f"{url!r} is absolute"
    path = url.partition("#")[0].partition("?")[0]
    target = (APP / path).resolve() if path else APP
    assert target == APP or APP in target.parents, f"{url!r} escapes app/"
    return target / "index.html" if target.is_dir() else target


def manifest() -> dict:
    return json.loads((APP / "manifest.json").read_text(encoding="utf-8"))


def manifest_urls() -> list[str]:
    data = manifest()
    urls = [data["start_url"], data["scope"]]
    urls += [icon["src"] for icon in data["icons"]]
    urls += [shortcut["url"] for shortcut in data["shortcuts"]]
    return urls


def test_manifest_parses_and_holds_every_required_key() -> None:
    data = manifest()
    assert set(data) >= {
        "name",
        "short_name",
        "id",
        "start_url",
        "scope",
        "display",
        "background_color",
        "theme_color",
        "icons",
    }


def test_short_name_fits_a_home_screen_label() -> None:
    assert len(manifest()["short_name"]) <= 12


def test_manifest_installs_as_a_standalone_app() -> None:
    assert manifest()["display"] == "standalone"


def test_app_identity_does_not_depend_on_start_url() -> None:
    # Without an explicit id, identity is derived from start_url, and a later task
    # changing start_url would install a second app on every existing device.
    identity = manifest()["id"]
    assert isinstance(identity, str)
    assert identity != ""


def test_start_url_and_scope_are_relative() -> None:
    data = manifest()
    assert data["start_url"] == "."
    assert data["scope"] == "."


def test_manifest_icons_cover_the_installability_floor() -> None:
    entries = {
        (icon["sizes"], icon["purpose"]): icon for icon in manifest()["icons"]
    }
    assert set(entries) == {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")}
    for icon in entries.values():
        assert icon["type"] == "image/png"


def test_declared_icon_sizes_match_the_png_headers() -> None:
    # A wrongly declared size is invisible until an install silently stops being
    # offered, so it is asserted against the IHDR the browser actually reads.
    for icon in manifest()["icons"]:
        header = read_ihdr(resolve_app_url(icon["src"]).read_bytes())
        assert icon["sizes"] == f"{header['width']}x{header['height']}"


def test_manifest_offers_a_shortcut_straight_to_add() -> None:
    shortcuts = manifest()["shortcuts"]
    assert len(shortcuts) == 1
    assert shortcuts[0]["url"] == "./#/add"
    assert shortcuts[0]["name"] == "Add an expense"


def test_every_manifest_url_resolves_to_a_file() -> None:
    # A manifest that names a missing icon is the single most common way an app
    # silently stops being installable.
    for url in manifest_urls():
        assert resolve_app_url(url).is_file(), url


# --- The document shell ----------------------------------------------------

APP_FILES = {
    "index.html",
    "styles.css",
    "app.js",
    "sw.js",
    "manifest.json",
    "icons/icon-192.png",
    "icons/icon-512.png",
    "icons/icon-maskable-512.png",
    "icons/apple-touch-icon-180.png",
}

SHELL_PRECACHE = [
    "index.html",
    "styles.css",
    "app.js",
    "manifest.json",
    "icons/icon-192.png",
    "icons/icon-512.png",
    "icons/icon-maskable-512.png",
    "icons/apple-touch-icon-180.png",
]

VIEWPORT = "width=device-width, initial-scale=1, viewport-fit=cover"

SCREEN_IDS = ["screen-feed", "screen-add", "screen-balances"]


class Document(HTMLParser):
    """Collect every tag and every run of text, in document order."""

    def __init__(self, markup: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []
        self.chunks: list[str] = []
        self.feed(markup)

    def handle_starttag(self, tag: str, attrs) -> None:
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)

    def find(self, tag: str, **match: str) -> list[dict]:
        return [
            attrs
            for name, attrs in self.tags
            if name == tag
            and all(attrs.get(key) == value for key, value in match.items())
        ]

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.chunks).split())


def markup() -> str:
    return (APP / "index.html").read_text(encoding="utf-8")


def document() -> Document:
    return Document(markup())


def styles() -> str:
    return (APP / "styles.css").read_text(encoding="utf-8")


def custom_property(name: str) -> str:
    found = re.search(rf"{name}:\s*(#[0-9a-f]{{6}});", styles())
    assert found is not None, f"{name} is declared in styles.css"
    return found.group(1)


def precache_entries() -> list[str]:
    source = (APP / "sw.js").read_text(encoding="utf-8")
    found = re.search(r"var SHELL = \[(.*?)\];", source, re.S)
    assert found is not None, "sw.js declares a SHELL precache list"
    return re.findall(r"'([^']+)'", found.group(1))


def test_app_holds_exactly_the_promised_files() -> None:
    found = {path.relative_to(APP).as_posix() for path in APP.rglob("*") if path.is_file()}
    assert found == APP_FILES


def test_scripts_holds_exactly_the_two_promised_python_files() -> None:
    assert {path.name for path in SCRIPTS.glob("*.py")} == {"make_icons.py", "serve.py"}


def test_document_opens_with_a_doctype_and_declares_its_language() -> None:
    assert markup().startswith("<!doctype html>\n")
    assert document().find("html") == [{"lang": "en"}]


def test_charset_is_the_first_thing_in_head() -> None:
    tags = document().tags
    head = next(index for index, (name, _) in enumerate(tags) if name == "head")
    assert tags[head + 1] == ("meta", {"charset": "utf-8"})


def test_the_viewport_keeps_pinch_zoom_and_covers_the_notch() -> None:
    # viewport-fit=cover is not decoration: without it env(safe-area-inset-*) is zero
    # on a notched iPhone and every safe-area rule below does nothing. No
    # user-scalable and no maximum-scale, so pinch zoom stays available.
    assert document().find("meta", name="viewport") == [
        {"name": "viewport", "content": VIEWPORT}
    ]


def test_theme_colour_agrees_across_the_meta_tag_the_css_and_the_manifest() -> None:
    meta = document().find("meta", name="theme-color")
    assert len(meta) == 1
    assert meta[0]["content"] == manifest()["theme_color"]
    assert custom_property("--theme") == manifest()["theme_color"]


def test_background_colour_agrees_between_the_css_and_the_manifest() -> None:
    # Android paints background_color as the splash screen; a mismatch flashes a
    # different colour before the app paints.
    assert custom_property("--bg") == manifest()["background_color"]


def test_the_installability_metas_are_present() -> None:
    # Chrome warns about the Apple one alone; older iOS needs it.
    doc = document()
    assert doc.find("meta", name="mobile-web-app-capable")[0]["content"] == "yes"
    assert doc.find("meta", name="apple-mobile-web-app-capable")[0]["content"] == "yes"
    assert (
        doc.find("meta", name="apple-mobile-web-app-title")[0]["content"]
        == manifest()["short_name"]
    )


def test_every_linked_asset_resolves_to_a_file() -> None:
    doc = document()
    hrefs = [attrs["href"] for attrs in doc.find("link") if attrs.get("href")]
    sources = [attrs["src"] for attrs in doc.find("script") if attrs.get("src")]
    assert hrefs and sources
    for url in hrefs + sources:
        assert resolve_app_url(url).is_file(), url


def test_the_document_links_the_manifest_the_stylesheet_and_the_icons() -> None:
    doc = document()
    assert doc.find("link", rel="manifest")[0]["href"] == "manifest.json"
    assert doc.find("link", rel="stylesheet")[0]["href"] == "styles.css"
    assert (
        doc.find("link", rel="apple-touch-icon")[0]["href"]
        == "icons/apple-touch-icon-180.png"
    )
    # An explicit icon link, so no route ever 404s on /favicon.ico.
    assert doc.find("link", rel="icon")[0]["href"] == "icons/icon-192.png"


def test_the_router_loads_as_a_classic_script() -> None:
    # Classic, not a module: a stdlib static server can hand back a MIME type that
    # the strict module check rejects, and there is only one file to load.
    scripts = document().find("script")
    assert len(scripts) == 1
    assert scripts[0] == {"src": "app.js"}


def test_the_nav_names_itself_and_lists_the_three_screens_in_order() -> None:
    doc = document()
    navs = doc.find("nav")
    assert len(navs) == 1
    assert navs[0]["aria-label"] == "Screens"
    # Add sits in the middle: the highest-frequency action gets the easiest thumb.
    hrefs = [attrs["href"] for attrs in doc.find("a") if attrs.get("href")]
    assert hrefs == ["#/feed", "#/add", "#/balances"]


def test_every_nav_item_carries_a_text_label() -> None:
    # No icon font, no emoji, no image-only buttons.
    text = document().text
    for label in ("Feed", "Add", "Balances"):
        assert label in text
    assert not document().find("img")


def test_each_screen_is_a_section_with_a_focusable_heading() -> None:
    doc = document()
    for screen_id in SCREEN_IDS:
        assert len(doc.find("section", id=screen_id)) == 1
    headings = [attrs for name, attrs in doc.tags if name == "h1"]
    assert len(headings) == len(SCREEN_IDS)
    for attrs in headings:
        # The router moves focus here on a route change, so a screen reader
        # announces the new view.
        assert attrs["tabindex"] == "-1"


def test_only_the_default_screen_starts_visible() -> None:
    # Inactive screens carry `hidden`, so assistive technology and find-in-page do
    # not reach them.
    sections = document().find("section")
    hidden = {attrs["id"]: "hidden" in attrs for attrs in sections if attrs.get("id")}
    assert hidden == {"screen-feed": False, "screen-add": True, "screen-balances": True}


def test_a_noscript_block_explains_that_the_app_needs_javascript() -> None:
    assert document().find("noscript")
    assert "JavaScript" in document().text


def test_every_screen_names_the_task_that_fills_it() -> None:
    text = document().text
    assert "Placeholder. Task 11 fills this with the expense feed." in text
    assert "Placeholder. Task 10 fills this with expense entry." in text
    assert "Placeholder. Task 12 fills this with balances and settle up." in text


def test_no_screen_shows_invented_data() -> None:
    # On a money app, plausible fake numbers are indistinguishable from wrong real
    # ones, and the spec names "looks authoritative while being wrong" as the
    # product's largest risk. No skeletons and no spinners either: nothing is
    # loading, and a skeleton reads as broken.
    text = document().text
    for symbol in ("$", "£", "€", "%"):
        assert symbol not in text
    assert re.search(r"\d+\.\d\d", text) is None
    for word in ("Loading", "loading", "skeleton", "spinner"):
        assert word not in text


@pytest.mark.parametrize("name", sorted(APP_FILES))
def test_no_shell_file_reaches_outside_the_origin(name: str) -> None:
    # No CDN, no web font, no analytics, no icon font: every asset is local.
    data = (APP / name).read_bytes()
    assert b"http://" not in data
    assert b"https://" not in data


@pytest.mark.parametrize("name", sorted(APP_FILES))
def test_no_shell_file_calls_a_back_end(name: str) -> None:
    # The shell is deliberately parallel to the whole 2 to 7 chain and has nothing
    # to call. The worker answers from its precache, so it never calls out either,
    # and no request can be cached beyond the shell files listed above.
    data = (APP / name).read_bytes()
    for forbidden in (b"fetch(", b"XMLHttpRequest", b"EventSource", b"WebSocket", b"/api"):
        assert forbidden not in data


def test_no_rule_sets_a_font_size_below_sixteen_pixels() -> None:
    # Anything smaller triggers iOS auto-zoom the moment task 10 adds a text input.
    css = styles()
    sizes = re.findall(r"font-size:\s*([0-9.]+)(px|rem)", css)
    sizes += re.findall(r"font:\s*(?:[^;]*?\s)?([0-9.]+)(px|rem)", css)
    assert sizes
    for amount, unit in sizes:
        assert float(amount) * (1 if unit == "px" else 16) >= 16


def test_no_rule_sets_a_hit_area_below_forty_four_pixels() -> None:
    heights = [float(value) for value in re.findall(r"min-height:\s*([0-9.]+)px", styles())]
    assert heights
    assert min(heights) >= 44


def test_the_layout_survives_a_collapsing_url_bar_and_a_notch() -> None:
    css = styles()
    assert "100vh" in css and "100dvh" in css  # dvh, with a vh fallback
    assert "touch-action: manipulation" in css
    insets = re.findall(r"env\(([^)]*)\)", css)
    assert insets
    for inset in insets:
        # Every env() carries a 0px fallback, so a browser without support renders
        # correctly rather than collapsing.
        assert inset.endswith(", 0px"), inset
    for side in ("top", "bottom", "left", "right"):
        assert f"safe-area-inset-{side}" in css


def test_motion_is_disabled_when_the_reader_asks_for_less() -> None:
    assert "@media (prefers-reduced-motion: reduce)" in styles()


def test_the_worker_precaches_exactly_the_shell() -> None:
    assert precache_entries() == SHELL_PRECACHE


def test_every_precache_entry_resolves_to_a_file() -> None:
    for entry in precache_entries():
        assert resolve_app_url(entry).is_file(), entry


# --- Docs ------------------------------------------------------------------

RUN_COMMAND = "uv run python scripts/serve.py"


def claude_md() -> str:
    return (REPO / "CLAUDE.md").read_text(encoding="utf-8")


def readme() -> str:
    return (REPO / "README.md").read_text(encoding="utf-8")


def test_claude_md_names_the_real_run_command() -> None:
    text = claude_md()
    assert RUN_COMMAND in text
    assert "nothing to run yet" not in text
    assert "http://localhost:8000" in text
    assert "no build step" in " ".join(text.split())


def test_claude_md_no_longer_says_the_front_end_is_missing() -> None:
    assert "not built yet" not in claude_md()


def test_claude_md_says_where_the_shell_and_the_scripts_live() -> None:
    text = claude_md()
    assert "`app/`" in text
    assert "`scripts/`" in text


def test_the_readme_documents_how_to_run_the_app() -> None:
    text = readme()
    assert "## Run the app" in text
    assert RUN_COMMAND in text
    assert "no product code yet" not in text


def paragraph_naming(text: str, needle: str) -> str:
    """The one paragraph naming `needle`, with its line wrapping flattened.

    Prose wraps, so a phrase can straddle a newline; searching the raw text would
    make these assertions depend on where a line happens to break.
    """
    blocks = [" ".join(block.split()) for block in text.split("\n\n")]
    matches = [block for block in blocks if needle in block]
    assert len(matches) == 1, f"expected exactly one paragraph naming {needle!r}"
    return matches[0]


def test_the_no_build_step_claim_carries_its_caveat_where_it_is_made() -> None:
    # The worker precaches the shell, so an edit to one of those eight files does not
    # show on reload, and the dev server's no-store header cannot help: the request
    # never reaches it. The caveat has to sit in the paragraph that makes the claim,
    # in both files, because a reader who stops at the claim is misled, and tasks 10
    # to 12 all edit app/index.html.
    for text in (claude_md(), readme()):
        caveat = paragraph_naming(text, "no build step")
        assert "VERSION" in caveat
        assert "app/sw.js" in caveat


def test_one_document_says_how_to_clear_a_stuck_service_worker() -> None:
    # The first person to hit a stale shell would otherwise lose an hour to it.
    combined = claude_md() + readme()
    assert "Service Workers" in combined
    assert "Unregister" in combined


def test_no_document_claims_the_shell_shows_real_data() -> None:
    combined = claude_md() + readme()
    assert "placeholder" in combined.lower()
