"""Structural assertions over the static shell in `app/`.

Standard library only, and nothing here imports `splitwise_lite`: the shell is
deliberately independent of the domain layer, so a test that reached into the
package would quietly undo that.

Paths are resolved from this file, never from the current working directory, so
the suite passes from anywhere.
"""

from __future__ import annotations

import hashlib
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
    # Task 9a: the one file under app/ that talks to the back end.
    "api.js",
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
    "api.js",
    "manifest.json",
    "icons/icon-192.png",
    "icons/icon-512.png",
    "icons/icon-maskable-512.png",
    "icons/apple-touch-icon-180.png",
]

VIEWPORT = "width=device-width, initial-scale=1, viewport-fit=cover"

SCREEN_IDS = ["screen-feed", "screen-add", "screen-balances"]

# Task 9a: the gate and the two notices. Deliberately not sections and deliberately
# without an h1, so the three screens stay the only sections and the only headings
# the router knows about.
GATE_IDS = ["gate", "notice"]


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


def test_scripts_holds_exactly_the_promised_python_files() -> None:
    # Task 9 added setup_group.py, the operator command for group and member setup.
    # Widened rather than relaxed: the set is still exhaustive, so a stray script or a
    # scratch file left in scripts/ still fails here.
    assert {path.name for path in SCRIPTS.glob("*.py")} == {
        "make_icons.py",
        "serve.py",
        "setup_group.py",
    }


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
    hrefs = [attrs["href"] for attrs in doc.find("a", **{"class": "tab"})]
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


def test_the_gate_is_not_a_fourth_route() -> None:
    # The router owns the route-to-screen mapping, and the gate is shown in place of
    # <main> and the tab bar rather than being routed to, so the current hash is left
    # alone and signing in returns the user to the screen they were on.
    router = (APP / "app.js").read_text(encoding="utf-8")
    found = re.search(r"var ROUTES = \{(.*?)\};", router, re.S)
    assert found is not None
    assert re.findall(r"'(#/[a-z]+)'", found.group(1)) == [
        "#/feed",
        "#/add",
        "#/balances",
    ]
    doc = document()
    for gate_id in GATE_IDS:
        assert len(doc.find("div", id=gate_id)) == 1
        assert "hidden" in doc.find("div", id=gate_id)[0]
    assert not doc.find("section", id="gate")


def test_the_gate_has_both_fields_both_controls_and_a_way_out() -> None:
    doc = document()
    email = doc.find("input", id="gate-email")[0]
    assert email["type"] == "email"
    assert email["autocomplete"] == "username"
    password = doc.find("input", id="gate-password")[0]
    assert password["type"] == "password"
    assert password["autocomplete"] == "current-password"
    # Switched to new-password when the gate is creating an account, so a password
    # manager offers to save a new secret rather than to fill an old one.
    assert "'new-password'" in (APP / "app.js").read_text(encoding="utf-8")
    assert doc.find("button", id="gate-submit")
    assert doc.find("button", id="gate-mode")
    assert doc.find("button", id="sign-out")


def test_the_document_says_what_an_unlinked_account_sees() -> None:
    text = document().text
    assert "Nobody has linked you to a member yet." in text
    assert "The app cannot reach the server" in text


def test_the_gate_carries_somewhere_to_put_that_message() -> None:
    doc = document()
    error = doc.find("p", id="gate-error")
    assert len(error) == 1
    # Announced when it appears, because it appears in response to an action.
    assert error[0]["role"] == "alert"
    assert "hidden" in error[0]


def test_every_element_the_router_reaches_for_exists_in_the_document() -> None:
    """The boot wiring is the one thing a mistyped id turns into a blank page.

    There is no browser in this suite, so a getElementById that returns null would
    otherwise only be found by opening the app. Every id and class app.js looks up is
    checked against the document instead.
    """
    router = (APP / "app.js").read_text(encoding="utf-8")
    doc = document()
    present = {attrs["id"] for _, attrs in doc.tags if attrs.get("id")}
    for wanted in re.findall(r"getElementById\('([^']+)'\)", router):
        assert wanted in present, wanted

    classes = set()
    for _, attrs in doc.tags:
        classes.update((attrs.get("class") or "").split())
    for selector in re.findall(r"querySelector\('\.([^']+)'\)", router):
        assert selector in classes, selector


def test_a_noscript_block_explains_that_the_app_needs_javascript() -> None:
    assert document().find("noscript")
    assert "JavaScript" in document().text


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


# Task 9a gave the shell a back end to call and narrowed this rule rather than
# removing it. `api.js` is the one network chokepoint, so there is one answer to a
# 401 and one place to change when the contract does; `sw.js` may name `/api` only so
# that it can refuse to cache it. Everything else is still forbidden everywhere, and
# `XMLHttpRequest`, `EventSource` and `WebSocket` are still forbidden outright:
# nothing here needs them.
FETCH_ALLOWED = {"api.js"}
# sw.js may say the word because `addEventListener('fetch', ...)` is the worker's own
# event name. It still may not call it: the `fetch(` rule below covers every file but
# the client.
FETCH_WORD_ALLOWED = {"api.js", "sw.js"}
API_PATH_ALLOWED = {"api.js", "sw.js"}


@pytest.mark.parametrize("name", sorted(APP_FILES))
def test_only_the_api_client_calls_the_back_end(name: str) -> None:
    data = (APP / name).read_bytes()
    for forbidden in (b"XMLHttpRequest", b"EventSource", b"WebSocket"):
        assert forbidden not in data, name
    if name not in FETCH_ALLOWED:
        assert b"fetch(" not in data, name
    if name not in FETCH_WORD_ALLOWED:
        # The bare word too, so window['fetch'] and any other indirect spelling is
        # refused rather than slipping past a check for the call syntax.
        assert b"fetch" not in data, name
    if name not in API_PATH_ALLOWED:
        assert b"/api" not in data, name


def test_the_narrowed_rule_still_bites() -> None:
    # The companion to the test above: proof that narrowing it to one file left a
    # rule that still refuses the thing it was written to refuse. Without this, a
    # screen task could add its own fetch to app.js and only the loosened rule would
    # be there to notice.
    router = (APP / "app.js").read_bytes()
    assert b"fetch(" not in router
    assert b"fetch" not in router
    assert b"/api" not in router

    callers = {
        name for name in APP_FILES if b"fetch(" in (APP / name).read_bytes()
    }
    assert callers == {"api.js"}

    builders = {
        name for name in APP_FILES if b"/api" in (APP / name).read_bytes()
    }
    assert builders == {"api.js", "sw.js"}

    # And the client really is a client: it is the file the rule was widened for.
    assert b"fetch(" in (APP / "api.js").read_bytes()
    assert b"/api" in (APP / "api.js").read_bytes()
    # The worker says the word only as its own event name, and never calls it.
    assert b"fetch(" not in (APP / "sw.js").read_bytes()


def test_the_api_client_holds_no_state_of_its_own() -> None:
    # The session cookie is HttpOnly and unreadable here by design, and a copy of
    # server state kept in the browser is how a signed-out page keeps showing a
    # ledger.
    source = (APP / "api.js").read_text(encoding="utf-8")
    for forbidden in ("localStorage", "sessionStorage", "indexedDB", "document.cookie ="):
        assert forbidden not in source
    assert "credentials: 'same-origin'" in source
    # Read at request time, never cached, so a rotated token is picked up next time.
    assert "readCookie(CSRF_COOKIE)" in source


def test_the_client_names_its_three_failure_paths() -> None:
    # A 401, a 403 member_not_linked and a request that got no answer are three
    # different screens, and which is which is decided in one file.
    source = (APP / "api.js").read_text(encoding="utf-8")
    for named in ("member_not_linked", "onUnauthenticated", "onNotLinked", "onOffline"):
        assert named in source


def test_the_worker_refuses_to_cache_the_api() -> None:
    # An offline write must fail loudly rather than looking like a success.
    source = (APP / "sw.js").read_text(encoding="utf-8")
    assert "pathname.indexOf('/api') === 0" in source
    assert "'/api'" in source


@pytest.mark.parametrize("name", sorted(APP_FILES - {"manifest.json"}))
def test_no_shell_file_does_money_or_split_arithmetic(name: str) -> None:
    # Task 8's independence rule, unchanged by task 9a and made easy to keep by the
    # string-only money contract: the front end is handed nothing it could do
    # arithmetic on, so it must not start.
    if not name.endswith((".js", ".html", ".css")):
        return
    source = (APP / name).read_text(encoding="utf-8")
    for forbidden in ("toFixed", "parseFloat", "Math.round", "Math.floor", "/ 100"):
        assert forbidden not in source, name


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


# --- The one break rule, and the ways it could be taken back ---------------
#
# These three replace a hand-maintained list of nine `.balances-*` class names. The
# list could not be right: it derived nothing from app/app.js, and on the day it
# shipped it named a description-bearing class as name-bearing, protected two classes
# that carry no server string at all, and missed `.curtain-error` and `.curtain-text`,
# which carry the server's own prose and sit outside all three screens. These derive
# from the stylesheet instead, and cover the file rather than one block of it.


def test_one_declaration_lets_every_long_word_in_the_shell_break() -> None:
    """`overflow-wrap: anywhere` is declared once, on `body`, and nowhere else.

    `overflow-wrap` is inherited, so one declaration on `body` covers all three
    screens, the gate, the notice, the header, the tab bar, and every text-bearing
    class nobody has written yet: a class a later task adds is protected without its
    author remembering anything. That is the property a per-class list cannot have,
    and PR #56 is the proof it needed one. Three `.balances-*` classes carrying a
    display name shipped there with no break rule of their own, on a branch whose
    author had read the comment naming the hazard, and the list of nine meant to
    catch them named neither `.curtain-error` nor `.curtain-text`, which render the
    server's own sentences at unbounded length.

    `anywhere` and not `break-word`. The two differ only in intrinsic sizing, and that
    difference is the whole hazard: under `break-word` the soft wrap opportunities the
    property introduces are not counted when min-content is computed, so a flex item
    still takes an unbroken 100-character name as its width floor and pushes its
    container wide unless `min-width: 0` is remembered beside it. Under `anywhere`
    they are counted, so one declaration is sufficient on its own and there is no
    second thing to remember.
    """
    css = styles()
    values = re.findall(r"overflow-wrap:\s*([a-z-]+)", css)
    if values != ["anywhere"]:
        found = (
            "no overflow-wrap declaration was found in app/styles.css"
            if not values
            else (
                f"app/styles.css declares overflow-wrap {len(values)} times, with "
                f"values {values}"
            )
        )
        pytest.fail(
            f"{found}.\n"
            "\n"
            "It must declare it exactly once, as `overflow-wrap: anywhere`, in the "
            "`body` rule. Once, because a second declaration is a second place to "
            "update and a per-class copy is how PR #56 shipped three unprotected "
            "classes. On `body`, because that is the only selector that reaches "
            "everything the shell renders, the gate and the notice included. "
            "`anywhere`, because only `anywhere` counts its own break opportunities "
            "when min-content is computed, so only `anywhere` stops a flex item "
            "taking an unbroken name as its width floor."
        )
    rule = re.search(r"(?<![-\w])body\s*\{[^}]*\}", css)
    assert rule is not None, "app/styles.css declares a `body` rule"
    assert "overflow-wrap: anywhere;" in rule.group(0), (
        "The one overflow-wrap declaration in app/styles.css is not inside the `body` "
        "rule, so it is not inherited by everything the shell renders. The `body` "
        f"rule found was:\n{rule.group(0)}"
    )


def test_nothing_in_the_shell_takes_the_break_rule_back() -> None:
    """Nothing in app/styles.css suppresses, revokes or hides an inherited break.

    Five declarations could, and each defeats it differently. `white-space` set to
    `nowrap` suppresses every soft wrap opportunity in a box, so the inherited rule
    has nothing left to act on. `overflow-wrap` set back to `normal` revokes the rule
    outright. `word-break` is the neighbouring property whose values move where a
    break may fall, so it can undo the effect while leaving the declaration in place.
    `text-overflow` and `-webkit-line-clamp` do something worse than overflowing:
    they hide the part that did not fit, and a silently truncated name or amount on a
    money screen is a wrong answer rather than an ugly one.

    `.balances-figure` and `.tab` are the two selectors allowed to refuse a wrap, and
    both hold text of fixed shape: a server-formatted amount that must never break
    mid-number, and the three literal tab labels. A sorted equality and not a
    membership, so a third selector reaching for `nowrap` fails here rather than
    passing because the two named ones still have theirs.
    """
    css = styles()
    block = without_comments(css)
    # The selectors first and the count second, deliberately: a third `nowrap` fails
    # both, and the message worth reading is the one that names the selector, so that
    # is the assertion that fires.
    #
    # The two do not overlap, and the second is not redundant. The selector regex only
    # matches a rule containing `white-space: nowrap`, so `white-space: pre` on a new
    # class leaves `refusing` unchanged and sails past the first assertion; the second
    # sees `['nowrap', 'pre', 'nowrap']` and fires. `pre`, `pre-wrap` and
    # `break-spaces` all preserve sequences of spaces and suppress the wrapping this
    # rule depends on, so the count is what covers every wrap-suppressing value other
    # than the one spelling the selector check knows about. Do not delete it as a
    # duplicate of the line above.
    refusing = sorted(
        head.strip()
        for head in re.findall(r"([^{}]*)\{[^}]*white-space:\s*nowrap", block)
    )
    assert refusing == [".balances-figure", ".tab"], (
        f"The selectors in app/styles.css refusing a wrap are {refusing}. Exactly "
        "two are allowed, .balances-figure and .tab, because both hold text of fixed "
        "shape. Anything else carrying `white-space: nowrap` cannot use the inherited "
        "`overflow-wrap: anywhere`, because nowrap leaves it no soft wrap opportunity "
        "to take, which is the form the PR #56 defect can still take."
    )
    spacing = re.findall(r"white-space:\s*([a-z-]+)", block)
    assert spacing == ["nowrap", "nowrap"], (
        f"app/styles.css declares white-space {len(spacing)} times, with values "
        f"{spacing}. Exactly two are allowed, both `nowrap`, on the two selectors "
        "above."
    )
    revoked = re.findall(r"overflow-wrap:\s*normal", block)
    assert not revoked, (
        f"app/styles.css takes the break rule back {len(revoked)} times with "
        "`overflow-wrap: normal`. Implied by "
        "test_one_declaration_lets_every_long_word_in_the_shell_break, and asserted "
        "here too, because this is the test whose name says it."
    )
    for prop in ("text-overflow", "-webkit-line-clamp", "word-break"):
        assert prop not in block, (
            f"app/styles.css declares `{prop}`. It hides or relocates an overflow "
            "instead of letting the text wrap, and on a money screen a name or an "
            "amount that is quietly cut short is a wrong answer."
        )
    clipping = re.findall(r"(?<![-\w])overflow:\s*hidden", block)
    assert len(clipping) == 1, (
        f"app/styles.css declares `overflow: hidden` {len(clipping)} times. Exactly "
        "one is allowed, on `body`, and it is what makes the document element the "
        "wrong thing to measure. A second one clips text somewhere else."
    )
    rule = re.search(r"(?<![-\w])body\s*\{[^}]*\}", css)
    assert rule is not None, "app/styles.css declares a `body` rule"
    assert "overflow: hidden;" in rule.group(0), (
        "The one `overflow: hidden` in app/styles.css is not on `body`, so it clips "
        f"something other than the viewport. The `body` rule found was:\n"
        f"{rule.group(0)}"
    )


def test_the_scroll_container_is_the_content_area_and_not_the_document() -> None:
    """`body` clips and `.content` scrolls, so the root's scrollable area cannot grow.

    Which is the whole of issue #58. The viewport's scrolling area is propagated from
    the root element; `body` clips, so nothing inside `.content` can extend it, and
    `document.documentElement.scrollWidth` equals its `clientWidth` whether or not
    content overflows. Four task specs asked an implementer to confirm exactly that
    equality in a browser as the test for horizontal overflow, so the check would
    have reported success in precisely the case it was written to catch. The
    measurement that works is `el.scrollWidth > el.clientWidth` on `.content` and on
    each rendered row container.

    This test is also what says so when it stops being true. If either declaration is
    ever removed, the dated correction notes in `plans/tasks/` stop describing this
    shell, and this is the check that goes red rather than nine documents quietly
    going stale.
    """
    css = styles()
    body_rule = re.search(r"(?<![-\w])body\s*\{[^}]*\}", css)
    assert body_rule is not None, "app/styles.css declares a `body` rule"
    assert "overflow: hidden;" in body_rule.group(0), (
        "`body` no longer sets `overflow: hidden`, so the root element may now scroll "
        f"and the notes in plans/tasks/ are stale. The `body` rule found was:\n"
        f"{body_rule.group(0)}"
    )
    content_rule = re.search(r"(?<![-\w])\.content\s*\{[^}]*\}", css)
    assert content_rule is not None, "app/styles.css declares a `.content` rule"
    assert "overflow-y: auto;" in content_rule.group(0), (
        "`.content` no longer sets `overflow-y: auto`, so it is no longer the scroll "
        f"container the notes in plans/tasks/ name. The `.content` rule found was:\n"
        f"{content_rule.group(0)}"
    )
    horizontal = re.findall(r"overflow-x\s*:\s*([a-z-]+)", css)
    assert not horizontal, (
        f"app/styles.css declares overflow-x, with values {horizontal}. Per CSS "
        "Overflow, `.content`'s `visible` horizontal axis already computes to `auto` "
        "beside its `overflow-y: auto`; declaring overflow-x explicitly changes which "
        "box scrolls and makes the corrected measurement in plans/tasks/ wrong again."
    )


def test_the_worker_precaches_exactly_the_shell() -> None:
    assert precache_entries() == SHELL_PRECACHE


def test_every_precache_entry_resolves_to_a_file() -> None:
    for entry in precache_entries():
        assert resolve_app_url(entry).is_file(), entry


# --- The precache digest ---------------------------------------------------

# The worker answers the shell from Cache Storage and never revalidates it, so a
# changed shell file reaches nobody who already has the app until the cache *name*
# changes. Until now the only thing that changed the name was a human remembering
# to edit VERSION, and that convention has failed twice: tasks 11 and 12 shipped
# two whole screens at v2, and task 32 rewrote three precached files at v3. Both
# failures looked exactly like success. So the cache name now carries a digest of
# the files it caches, and the test below fails when the two drift apart.

# The extensions the digest knows how to read. Text is normalised so a checkout
# under `core.autocrlf=true` and one under `core.autocrlf=false` agree; the PNGs
# are hashed exactly as they sit on disk.
DIGEST_TEXT_SUFFIXES = (".html", ".css", ".js", ".json")
DIGEST_BINARY_SUFFIXES = (".png",)


def shell_digest(
    entries: list[str] | None = None,
    contents: dict[str, bytes] | None = None,
) -> str:
    r"""Twelve hex characters over the precached files, and nothing else.

    The whole rule, so it can be read here rather than reconstructed: the entries
    are sorted with Python's default string ordering, and one sha256 is fed, for
    each entry in that order, the entry's path as UTF-8, a NUL, the decimal length
    of its content bytes as ASCII, a NUL, and then those content bytes. The length
    is what keeps the framing unambiguous: without it two entries could shift bytes
    across the boundary between them and leave the digest where it was.

    Content bytes are the file's bytes with `\r\n` replaced by `\n` for the text
    entries, and the raw bytes for the PNGs. That normalisation is not about churn.
    This repo pins no `.gitattributes` rule for `.js`, `.html`, `.css` or `.json`,
    so a checkout under `core.autocrlf=true` holds different bytes on disk from one
    without, and a raw digest could never be green on Windows and on Linux at once.
    It makes the digest a property of the committed content instead of the checkout.

    Twelve characters is enough because this detects change, it does not resist
    tampering. There is no adversary: anyone who can edit a file under `app/` can
    edit `app/sw.js` in the same commit, and the mechanism is aimed at the engineer
    who forgot, not one who is trying. Twelve hex characters is 48 bits, far more
    than the handful of shell edits this repo will ever make, and short enough to
    read out of a Cache Storage row in DevTools at a glance.

    `entries` overrides the list and `contents` overrides individual entries' bytes,
    so a test can hash a hypothetical `app/` without writing anything to disk.
    """
    if entries is None:
        entries = precache_entries()
    if contents is None:
        contents = {}
    running = hashlib.sha256()
    for entry in sorted(entries):
        raw = (
            contents[entry]
            if entry in contents
            else resolve_app_url(entry).read_bytes()
        )
        if entry.endswith(DIGEST_TEXT_SUFFIXES):
            content = raw.replace(b"\r\n", b"\n")
        elif entry.endswith(DIGEST_BINARY_SUFFIXES):
            content = raw
        else:
            raise AssertionError(
                f"{entry} is precached, but the digest has no rule for that kind of "
                f"file, and it will not guess one. Somebody has to decide whether "
                f"{entry} is text, in which case its line endings are normalised and "
                f"its extension belongs in DIGEST_TEXT_SUFFIXES, or binary, in which "
                f"case it is hashed exactly as it sits on disk and its extension "
                f"belongs in DIGEST_BINARY_SUFFIXES. Guessing either way is wrong for "
                f"the other: a text file hashed raw makes the digest depend on the "
                f"checkout, and a binary file with its CRLF pairs rewritten is corrupt."
            )
        running.update(entry.encode("utf-8"))
        running.update(b"\0")
        running.update(str(len(content)).encode("ascii"))
        running.update(b"\0")
        running.update(content)
    return running.hexdigest()[:12]


def recorded_digest() -> str:
    """The digest `app/sw.js` currently claims, read straight out of the source."""
    source = (APP / "sw.js").read_text(encoding="utf-8")
    found = re.findall(r"var SHELL_DIGEST = '([0-9a-f]{12})';", source)
    assert len(found) == 1, (
        "app/sw.js declares SHELL_DIGEST exactly once, as twelve lowercase hex "
        f"characters in single quotes. Found {len(found)}."
    )
    return found[0]


def stale_digest_message(recorded: str, computed: str, covered: int) -> str:
    """What the enforcing test says when the recorded value has gone stale.

    Written for somebody who has just edited `app/app.js`, has never opened
    `app/sw.js`, and has no reason to know what a service worker precache is. It
    says what is wrong, what it costs, and the one line to change. If reading it
    does not make the fix obvious, the message is the thing to improve.

    `covered` is how many files the digest is taken over, passed in rather than
    written into the prose. Saying "the files in app/" would be wrong: app/sw.js is
    in app/, is not one of them, and is the very file the reader is being sent to
    edit. Anybody chasing that would have to open a second file to find out which
    set is meant, which is the one thing this message exists not to require.
    """
    return (
        f"app/sw.js records the shell as '{recorded}'.\n"
        f"The {covered} files it precaches now come to '{computed}'.\n"
        "\n"
        "So one of the files the app keeps a copy of has changed, and the cache "
        "name in app/sw.js has not. Every browser that has already installed this "
        "app keeps its own copy of the shell files, filed under that cache name, "
        "and serves that copy without asking the server again. Until the name "
        "changes, everyone who already has the app goes on getting the old files, "
        "your change reaches nobody, and nothing anywhere reports an error. That "
        "has happened twice in this repo, and both times it looked like success.\n"
        "\n"
        "Fix it by changing one line in app/sw.js to read exactly:\n"
        "\n"
        f"    var SHELL_DIGEST = '{computed}';\n"
        "\n"
        "That is the whole fix, and it is the whole of what this test is asking "
        "for. VERSION needs bumping only if you changed how the worker itself "
        "behaves; editing a file under app/ is not that, so leave VERSION where "
        "it is.\n"
        "\n"
        "This does not know which files changed: it is one number over all of "
        "them together. `git status app/` will tell you."
    )


def test_the_cache_name_is_built_from_the_version_and_the_digest() -> None:
    # A SHELL_DIGEST that the cache name does not use is an inert constant, and the
    # whole mechanism would be decorative: the value would still have to be pasted
    # in to go green, and every installed client would still be served the old shell
    # out of a cache whose name never moved. The name is what the browser keys on,
    # so the digest has to be in the name.
    source = (APP / "sw.js").read_text(encoding="utf-8")
    assert (
        "var CACHE = 'splitwise-lite-shell-' + VERSION + '-' + SHELL_DIGEST;" in source
    )
    assignments = re.findall(r"^\s*(?:var )?CACHE = .*$", source, re.M)
    assert len(assignments) == 1, assignments


def test_the_recorded_digest_matches_the_files_it_covers() -> None:
    # The one test this whole section exists for. pytest.fail rather than a bare
    # assert, so the reader gets the prose and not a two-string repr diff.
    recorded = recorded_digest()
    computed = shell_digest()
    if recorded != computed:
        pytest.fail(stale_digest_message(recorded, computed, len(precache_entries())))


def test_the_digest_refuses_an_entry_it_cannot_classify() -> None:
    # Nothing under app/ has an unknown extension today. When something does, the
    # digest must not guess: a text file hashed raw is machine-dependent, and a
    # binary file with its CRLF pairs rewritten is simply corrupt.
    with pytest.raises(AssertionError) as raised:
        shell_digest(entries=["notes.txt"], contents={"notes.txt": b"hello"})
    message = str(raised.value)
    assert "notes.txt" in message
    assert "text" in message
    assert "binary" in message


def test_one_appended_byte_in_app_js_moves_the_digest() -> None:
    # A whitespace-only edit retiring the cache is the accepted trade, not an
    # oversight. Over-invalidating costs one shell download and corrects itself;
    # under-invalidating is silent, permanent, and has already happened twice.
    # Normalising past it would need a JavaScript parser, which is a dependency.
    entries = precache_entries()
    appended = (APP / "app.js").read_bytes() + b"\n"
    assert shell_digest(entries=entries, contents={"app.js": appended}) != shell_digest(
        entries=entries
    )


def test_one_changed_byte_in_an_icon_moves_the_digest() -> None:
    # The icons are covered, not merely listed: they are precached like everything
    # else, and a regenerated icon that never reaches an installed client is the
    # same bug as a stale script.
    entries = precache_entries()
    flipped = bytearray((ICONS / "icon-192.png").read_bytes())
    flipped[-1] ^= 0xFF
    assert shell_digest(
        entries=entries, contents={"icons/icon-192.png": bytes(flipped)}
    ) != shell_digest(entries=entries)


def test_line_endings_do_not_move_the_digest() -> None:
    # `.gitattributes` pins no rule for .js, so the same commit is CRLF on one
    # machine and LF on another. Without this the digest would be a property of
    # the checkout rather than of the content, and could never be green on both.
    entries = precache_entries()
    unix = (APP / "app.js").read_bytes().replace(b"\r\n", b"\n")
    windows = unix.replace(b"\n", b"\r\n")
    assert shell_digest(entries=entries, contents={"app.js": unix}) == shell_digest(
        entries=entries, contents={"app.js": windows}
    )


def test_reordering_the_entries_leaves_the_digest_alone() -> None:
    # The entries are sorted before hashing, so shuffling SHELL never demands a
    # cache retirement that no user would benefit from.
    entries = precache_entries()
    assert shell_digest(entries=list(reversed(entries))) == shell_digest(entries=entries)


# --- The precache list against app/ ----------------------------------------

# The same bug, one level out. A file added to app/ and not to SHELL is not
# precached, does not work offline, and the digest does not cover it either, because
# the digest only ever sees what SHELL names. test_app_holds_exactly_the_promised_files
# forces the new file into APP_FILES and test_the_worker_precaches_exactly_the_shell
# compares SHELL against SHELL_PRECACHE, but nothing related the two: both literals
# could be edited consistently with SHELL left short and the suite stayed green. This
# relates them, so the omission has to be deliberate and has to carry its reason.

# path -> why it is in app/ and deliberately not in SHELL. One entry today.
NOT_PRECACHED = {
    "sw.js": (
        "SHELL_DIGEST is recorded inside sw.js, so hashing sw.js into the digest is "
        "a self-reference with no fixed point: every edit changes the digest, "
        "pasting the digest changes the file, and the new file has a new digest "
        "again. There is no value that could ever be correct. That reason is "
        "unconditional and is the one to keep. Secondarily, and only as long as the "
        "specification says so: the browser fetches the worker script itself with "
        "service-workers mode 'none', so that fetch reaches no worker's fetch "
        "handler and a worker cannot be served its own cached self today. Were it "
        "ever intercepted, the byte-compare against the running script is the only "
        "thing that ever replaces a worker, a worker handed its own cached self "
        "would compare equal forever and could never be replaced, and that is the "
        "one failure with no way out short of unregistering by hand."
    ),
}


def unlisted_shell_file_message(missing: list[str], unknown: list[str]) -> str:
    """What the test below says when SHELL and app/ have come apart.

    Written for whoever has just added a file to app/ and has no reason to know
    that a second list decides what the installed app is made of.
    """
    parts = []
    if missing:
        parts.append(
            "These files are in app/, and the worker does not precache them:\n\n"
            + "\n".join(f"    {path}" for path in missing)
            + "\n\n"
            "So they are not part of the installed app. They are fetched from the "
            "network every time, the app does not open offline without them, and "
            "the cache name does not move when they change, because it only covers "
            "what the worker precaches. Somebody has to decide which of two things "
            "is meant. Either add the path to SHELL in app/sw.js, which precaches "
            "it and folds it into the digest; or add it to NOT_PRECACHED in "
            "tests/test_web_shell.py with a sentence saying why it stays out, the "
            "way sw.js does."
        )
    if unknown:
        parts.append(
            "The worker precaches these, and app/ does not hold them:\n\n"
            + "\n".join(f"    {path}" for path in unknown)
            + "\n\n"
            "A SHELL entry with no file behind it fails the whole install, so no "
            "visitor gets a worker at all. Either the file was deleted and SHELL in "
            "app/sw.js still names it, or APP_FILES in this file has not been told "
            "the file exists."
        )
    return "\n\n".join(parts)


def omissions_carry_their_reasons(omissions: dict[str, str]) -> None:
    """Fail unless every omission above is justified in prose.

    Without this the mapping checks only its keys, so a blank string buys a file its
    way out of the precache list for nothing, which is the one thing the mapping
    exists to prevent.
    """
    blank = sorted(path for path, reason in omissions.items() if not reason.strip())
    assert not blank, (
        "These paths are named as deliberate omissions with no reason given:\n\n"
        + "\n".join(f"    {path}" for path in blank)
        + "\n\n"
        "A reason is the price of the omission. Naming a file here takes it out of "
        "the installed app: it is fetched from the network every time, it is not "
        "there offline, and the cache name does not move when it changes. That can "
        "be the right call, and sw.js is one, but it has to be a call somebody made "
        "and wrote down, in a sentence that lands in the diff where a reviewer can "
        "disagree with it. An empty reason is the same omission with nobody's name "
        "on it. Write the sentence, or add the path to SHELL in app/sw.js."
    )


def test_the_precache_list_covers_app_minus_the_named_omissions() -> None:
    for path in NOT_PRECACHED:
        assert path in APP_FILES, f"{path} is named as an omission but is not in app/"
    omissions_carry_their_reasons(NOT_PRECACHED)
    entries = set(precache_entries())
    # Against app/ as it actually is, first. A file dropped into the directory has
    # to fail here on its own, without waiting for anyone to add it to APP_FILES:
    # the whole point is that no pair of literals can be kept agreeing with each
    # other while the shell the browser installs is quietly short of a file.
    on_disk = {
        path.relative_to(APP).as_posix() for path in APP.rglob("*") if path.is_file()
    }
    expected = on_disk - set(NOT_PRECACHED)
    if entries != expected:
        pytest.fail(
            unlisted_shell_file_message(
                missing=sorted(expected - entries), unknown=sorted(entries - expected)
            )
        )
    # And against the promised set, so APP_FILES cannot drift out of the relation
    # and leave the check above comparing the directory only with itself.
    assert entries == APP_FILES - set(NOT_PRECACHED)


def test_an_omission_with_no_reason_is_refused() -> None:
    # The mapping is a toll, not a list. Its whole worth is that dropping a file out
    # of the precache costs a sentence in the diff, where a reviewer reads it and can
    # disagree. Checking only the keys leaves the cheapest way out of the test above
    # open: name the file, say nothing, go green, and the file is outside the
    # installed app with nothing on record saying anybody meant it.
    for blank in ("", "   ", "\n\t "):
        with pytest.raises(AssertionError) as raised:
            omissions_carry_their_reasons({"probe.txt": blank})
        message = str(raised.value)
        assert "probe.txt" in message
        assert "a reason is the price of the omission" in message.lower()
    omissions_carry_their_reasons(NOT_PRECACHED)


# --- Docs ------------------------------------------------------------------

# The two documents a person or an agent reads before touching this repo, and the
# capability claims they make. This section used to assert that the word
# `placeholder` appeared somewhere across the two files: true while the three
# screens were empty, and a lie held in place by a test the moment they were
# filled. What replaces it reads the two lists each document declares and checks
# every claim in them against the shipped files in `app/`.

RUN_COMMAND = "uv run python scripts/serve.py --store ledger.sqlite3"


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


# The capability claims. Both documents carry two delimited lists, `What works today`
# and `What does not exist yet`, and every bullet in them is checked against the files
# in `app/` rather than against a phrase. It fails in both directions: a claim with no
# machinery behind it, and machinery with no claim in front of it.

# The keys of `window.SplitwiseApi`. `app/api.js` is the only file under `app/` allowed
# to call the back end, which `test_only_the_api_client_calls_the_back_end` enforces, so
# this set is the whole server-backed surface of the app: no capability reaches the
# server without a name in here.
API_SURFACE = {
    "ApiError",
    "onUnauthenticated",
    "onNotLinked",
    "onOffline",
    "session",
    "cachedSession",
    "signUp",
    "signIn",
    "signOut",
    "members",
    "expenses",
    "addExpense",
    "balances",
    "debt",
    # Task 14. The key that fired this section's `Mark as paid` prompt: it arrived, this
    # test went red naming both documents, and the bullets moved.
    "addSettlement",
    # Task 15. The same prompt fired the same way for `Receiver confirmation`.
    "decideSettlement",
}

# Capability key -> the (file under `app/`, substring) pairs that must all be PRESENT.
# These bite when machinery vanishes under a claim that still stands. They do not bite
# when a claim is dropped from both documents and from here at once, because then
# there is nothing left for the pair to disagree about; see the note on NOT_YET below
# for the same limit stated from the other side.
WORKS_TODAY = {
    "Sign in": (("index.html", 'id="gate-form"'), ("api.js", "signIn:")),
    "The expense feed": (("index.html", 'id="feed-list"'), ("api.js", "expenses:")),
    "Adding an expense": (("index.html", 'id="add-form"'), ("api.js", "addExpense:")),
    "Balances": (
        ("index.html", 'id="balances-transfers"'),
        ("api.js", "balances:"),
    ),
    # Backlog task 13. Until it landed this key sat in NOT_YET, with `.debt(` asserted
    # absent from app/app.js, and that rule is what turned red when the drill-down
    # shipped ahead of these documents. The same fact, read the other way: the screen
    # asks the client for a debt, and index.html carries the hint that says a payment
    # can be opened at all.
    "Transfer drill-down": (
        ("index.html", 'id="balances-drill-hint"'),
        ("app.js", "api.debt("),
    ),
    # Backlog task 14. Until it landed this key sat in NOT_YET as a PROMPT with no
    # absent rule, and the prompt did what it said it would: `addSettlement` arrived on
    # window.SplitwiseApi, test_the_api_client_offers_exactly_the_named_calls went red
    # naming both documents, and that is what moved these bullets. The evidence is the
    # block the payer's claim is drawn in and the call the screen makes, not the client
    # key alone, which would prove only that the method exists unused.
    "Mark as paid": (
        ("index.html", 'id="balances-pending-block"'),
        ("app.js", "api.addSettlement("),
    ),
    # Backlog task 15. Until it landed this key sat in NOT_YET as a PROMPT with no
    # absent rule, and the prompt did what it said it would: `decideSettlement`
    # arrived on window.SplitwiseApi, test_the_api_client_offers_exactly_the_named_calls
    # went red naming both documents, and that is what moved these bullets. The
    # evidence is the list the refused claims are drawn in and the call the screen
    # makes, not the client key alone, which would prove only that the method exists
    # unused.
    "Receiver confirmation": (
        ("index.html", 'id="balances-rejected"'),
        ("app.js", "api.decideSettlement("),
    ),
    "Install and open offline": (
        ("app.js", "navigator.serviceWorker.register('sw.js')"),
        ("sw.js", "var SHELL = ["),
    ),
    # Backlog task 16, GitHub issue #17. What actually happened, recorded here in the
    # shape the entries for tasks 13, 14 and 15 carry, because this one is the first to
    # spend a SILENCE rather than an INTERLOCK or a PROMPT:
    #
    #   The entry was SILENCE and the silence held. Nothing in this suite fired. No name
    #   arrived on window.SplitwiseApi, so test_the_api_client_offers_exactly_the_named_calls
    #   stayed green with both documents stale, exactly as the reason predicted, and the
    #   bullets were moved by hand. The verdict was right.
    #
    #   **Correction, 2026-09-08, by the engineer who built it.** Its reason said
    #   "Staleness can be computed on the client from the feed payload the app already
    #   fetches". That clause is withdrawn: it is false and always was. Two lines of
    #   tests/test_feed_screen.py::test_app_js_never_reads_the_client_clock ban `Date.now(`
    #   and `new Date()` from the whole of app/app.js, on the stated grounds that relative
    #   time is task 16's vocabulary, so the client cannot know what time it is and cannot
    #   compute this. Staleness is computed in src/splitwise_lite/staleness.py from the
    #   instant web.py::_now() reads, and rides on the two payloads the app already asks
    #   for. The conclusion the false clause was supporting still stands, and stands for a
    #   different reason: the build added no API method and no new call either, so neither
    #   API_SURFACE nor an absent-substring rule would have noticed it land. A reason can
    #   be wrong while the verdict it supports is right, and quoting the withdrawn clause
    #   here rather than deleting it is what lets a reader who meets it elsewhere see that
    #   it was withdrawn.
    #
    # The evidence below is machinery rather than prose: the block the quiet list is drawn
    # in, and the key the screen reads to decide what to draw at all.
    "The incompleteness signal": (
        ("index.html", 'id="balances-quiet-block"'),
        ("app.js", "staleness"),
    ),
}

# Capability key -> the `plans/backlog.md` task both documents cite, the (file,
# substring) pairs that must be ABSENT, and a reason. An entry with no substring rule
# still carries a reason naming what covers it instead, because an empty rule with no
# explanation is a guard nobody can audit.
#
# Every reason says which of three strengths it has, and the words are used strictly,
# because reading a prompt as an interlock is exactly the mistake this section exists to
# stop somebody making:
#
#   INTERLOCK. An `absent` rule names a substring in a file under `app/`. While the
#   capability is in the shell there is no green tree that also calls it missing here,
#   so the documents have to move. Routing around it means deleting an evidence rule
#   and writing a reason that is false, which is a deliberate edit and reads as one in
#   a diff.
#
#   PROMPT. No `absent` rule. Some other test goes red on the obvious way of building
#   the capability, and its message says to move the bullets. It is not a guarantee,
#   for two measured reasons: one string added to a literal clears that red while both
#   documents stay stale, and the red only comes at all if the capability is built the
#   way the house style suggests. See the note on API_SURFACE below.
#
#   SILENCE. Neither. Nothing in this suite would notice the capability landing.
#
# Nothing below is an interlock. `Transfer drill-down` was the only one this section
# ever had, and it has been spent: task 13 shipped, `.debt(` appeared in app/app.js
# while both documents still called the capability missing, the rule fired, and the
# entry moved to WORKS_TODAY.
#
# One prompt has now been spent too, and it worked: `Mark as paid` was a PROMPT with no
# absent rule, task 14 built it in house style, `addSettlement` arrived on
# window.SplitwiseApi, test_the_api_client_offers_exactly_the_named_calls went red
# naming both documents, and the bullets moved. One observation is not a guarantee, and
# the reasons below still say what each entry is worth on its own terms: the two things
# that keep a prompt short of a guarantee, a name added to API_SURFACE with the bullets
# untouched and a round trip made from inside an existing method, were both open on that
# build too and neither happened to be taken.
#
# What API_SURFACE catches, measured rather than reasoned about, on 2026-09-07: it
# compares the set of TOP-LEVEL KEYS of window.SplitwiseApi against a literal. A
# capability arriving as a new key fires it. A capability arriving inside an existing
# method does not. An expense-correction round trip added to the body of `addExpense`
# was run against this suite's own parse and left the key set at fourteen, unchanged,
# so test_the_api_client_offers_exactly_the_named_calls never fired. The three reasons
# below that name that test describe the likely build, not a guarantee, and each says
# so. Nothing here claims a capability cannot arrive without a new name.
#
# Both measurements in this section were taken while the set held fourteen keys.
#
# **Correction, 2026-09-08.** The sentence that followed used to read "Task 14 has since
# added `addSettlement` and it holds fifteen." It holds **sixteen**: task 14 added
# `addSettlement` and task 15 added `decideSettlement`, and the count was stale through
# both. Measured on 2026-09-07 by running this file's own parse over app/api.js, which
# returned sixteen keys equal to API_SURFACE exactly. The number was also given as
# fourteen in one brief and fifteen here, which is three figures for one literal and is
# the whole argument for measuring rather than quoting.
#
# The substantive point is unchanged and is the reason the correction is only to the
# number: the measurements above are about what the parse notices, not about how many
# keys there are, so they stand exactly as taken.
NOT_YET = {
    "Expense correction": {
        "task": 17,
        "absent": (),
        "reason": (
            "A PROMPT on paper and, for the build that was actually tried, SILENCE. "
            "Editing or voiding an expense appends an event through the server, so in "
            "house style it adds a name to API_SURFACE and "
            "test_the_api_client_offers_exactly_the_named_calls fails when it does. It "
            "does not have to: a void route reached through the existing addExpense "
            "key was run against this suite's own parse on 2026-09-07 and left the key "
            "set unchanged at fourteen, so nothing fired. Treat a red here as a "
            "reminder to move the bullets, and never treat its absence as evidence "
            "that nothing landed."
        ),
    },
}


def backlog_md() -> str:
    return (REPO / "plans" / "backlog.md").read_text(encoding="utf-8")


def capability_bullets(text: str, heading: str, where: str) -> list[str]:
    """The bullets under `heading`, one flattened string each.

    No Markdown parser: the section runs from its heading to the next heading, and
    inside it a bullet starts at column zero with `- ` and carries on over any indented
    line. Prose before the first bullet is the lead-in and is ignored, so the wording of
    these documents stays free; the keys are the only thing pinned.
    """
    lines = text.split("\n")
    starts = [
        index + 1
        for index, line in enumerate(lines)
        if re.fullmatch(r"#{2,4} " + re.escape(heading), line.rstrip())
    ]
    assert len(starts) == 1, (
        f"{where} should carry exactly one `{heading}` heading, at level 2, 3 or 4, and "
        f"it carries {len(starts)}. Both CLAUDE.md and README.md declare what the app "
        "can and cannot do under that heading, and this suite reads the claims from "
        "there."
    )
    bullets: list[str] = []
    for line in lines[starts[0] :]:
        if re.match(r"#{1,6} ", line):
            break
        if not line.strip():
            continue
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        elif bullets and line.startswith("  "):
            bullets[-1] += " " + line.strip()
        elif bullets:
            raise AssertionError(
                f"The `{heading}` list in {where} is interrupted by a line that is "
                f"neither a bullet nor a continuation of one: {line.strip()[:60]!r}. "
                "Between the first bullet and the next heading that list holds bullets, "
                "their indented continuation lines and blank lines only, so a claim "
                "cannot be smuggled in as prose this guard does not read."
            )
    assert bullets, (
        f"The `{heading}` list in {where} has no bullets. That list is where this "
        "document states what the app can do, and an empty one claims nothing at all."
    )
    return bullets


def bold_keys(bullets: list[str], heading: str, where: str) -> list[str]:
    """The bold key that opens each bullet, in order."""
    keys: list[str] = []
    for bullet in bullets:
        match = re.match(r"\*\*(.+?)\*\*", bullet)
        assert match is not None, (
            f"A bullet under `{heading}` in {where} does not open with a bold key: "
            f"{bullet[:60]!r}. Every bullet there names one capability in bold, because "
            "the keys are what this suite compares between the two documents and "
            "against the files in app/. An unkeyed bullet is a claim nothing checks."
        )
        keys.append(match.group(1))
    assert len(set(keys)) == len(keys), (
        f"{where} names a capability twice under `{heading}`: {sorted(keys)}. Each "
        "capability is claimed once per list."
    )
    return keys


def test_the_api_client_offers_exactly_the_named_calls() -> None:
    # Keys are matched by their indentation rather than by brace matching, because the
    # values are functions and following braces would need a JavaScript parser, which is
    # a dependency. API_SURFACE is not empty, so a regex that matched nothing would fail
    # this test rather than quietly pass it.
    source = (APP / "api.js").read_text(encoding="utf-8")
    marker = "window.SplitwiseApi = {"
    start = source.find(marker)
    assert start != -1, (
        f"app/api.js no longer assigns {marker!r}. That object is the whole "
        "server-backed surface of the app and this test reads its keys from there, so "
        "if the client was restructured this parse moves with it."
    )
    body = source[start + len(marker) :]
    keys = set(re.findall(r"^    ([A-Za-z][A-Za-z0-9]*):", body, re.MULTILINE))
    assert keys == API_SURFACE, (
        "app/api.js does not offer the calls this suite records.\n"
        f"  added:   {sorted(keys - API_SURFACE) or 'none'}\n"
        f"  removed: {sorted(API_SURFACE - keys) or 'none'}\n"
        "app/api.js is the only file under app/ allowed to reach the back end, so a "
        "method arriving or leaving here is a capability arriving or leaving the app. "
        "Before editing API_SURFACE, read the `What works today` and `What does not "
        "exist yet` lists in CLAUDE.md and README.md: a new call almost always means a "
        "bullet moves between those two lists in both documents, and its entry moves "
        "between WORKS_TODAY and NOT_YET here."
    )


def test_both_documents_agree_on_what_works_today() -> None:
    # Each file is compared with the same literal, which is what makes the two files
    # agree with each other: editing one and not the other turns this red.
    heading = "What works today"
    for where, text in (("CLAUDE.md", claude_md()), ("README.md", readme())):
        keys = set(bold_keys(capability_bullets(text, heading, where), heading, where))
        assert keys == set(WORKS_TODAY), (
            f"The `{heading}` list in {where} and the WORKS_TODAY literal in "
            "tests/test_web_shell.py disagree.\n"
            f"  claimed in {where} but not recorded here: "
            f"{sorted(keys - set(WORKS_TODAY)) or 'none'}\n"
            f"  recorded here but not claimed in {where}: "
            f"{sorted(set(WORKS_TODAY) - keys) or 'none'}\n"
            "Both documents carry the same keys. If the capability has landed, "
            "move its bullet from `What does not exist yet` to `What works today` in "
            "BOTH CLAUDE.md and README.md and move its entry from NOT_YET to "
            "WORKS_TODAY here, with evidence in app/ that must now be present. If it "
            "has not landed, the document is claiming something that does not exist: "
            "take the bullet out."
        )


def test_both_documents_agree_on_what_does_not_exist_yet() -> None:
    heading = "What does not exist yet"
    backlog = backlog_md()
    for where, text in (("CLAUDE.md", claude_md()), ("README.md", readme())):
        bullets = capability_bullets(text, heading, where)
        keys = bold_keys(bullets, heading, where)
        assert set(keys) == set(NOT_YET), (
            f"The `{heading}` list in {where} and the NOT_YET literal in "
            "tests/test_web_shell.py disagree.\n"
            f"  called missing in {where} but not recorded here: "
            f"{sorted(set(keys) - set(NOT_YET)) or 'none'}\n"
            f"  recorded here but not called missing in {where}: "
            f"{sorted(set(NOT_YET) - set(keys)) or 'none'}\n"
            "Both documents carry the same keys. If the capability has landed, "
            "move its bullet to `What works today` in BOTH CLAUDE.md and README.md and "
            "move its entry to WORKS_TODAY here. If it has not, the list it was taken "
            "out of is the honest place for it."
        )
        for key, bullet in zip(keys, bullets):
            cited = re.findall(r"\(backlog task (\d+)\)", bullet)
            assert len(cited) == 1, (
                f"The `{key}` bullet in {where} should cite its backlog task exactly "
                f"once, as `(backlog task N)`, and it cites it {len(cited)} times. The "
                "citation is how a reader gets from the missing capability to the plan "
                "for it."
            )
            expected = NOT_YET[key]["task"]
            assert int(cited[0]) == expected, (
                f"The `{key}` bullet in {where} cites backlog task {cited[0]}, and this "
                f"suite records task {expected}. GitHub issue numbers and "
                "plans/backlog.md task numbers are not the same in this range, so check "
                "the `## N.` heading in plans/backlog.md before changing either. If the "
                "number here is the wrong one, it is wrong in the other document too."
            )
            assert re.search(rf"^## {expected}\. ", backlog, re.MULTILINE), (
                f"plans/backlog.md has no `## {expected}.` heading, and the `{key}` "
                f"bullet in {where} cites backlog task {expected}. Either the backlog "
                "was renumbered, in which case both documents and NOT_YET move with it, "
                "or the citation points at nothing."
            )


def test_every_capability_the_documents_claim_is_in_the_shell() -> None:
    for key, evidence in WORKS_TODAY.items():
        for filename, needle in evidence:
            text = (APP / filename).read_text(encoding="utf-8")
            assert needle in text, (
                f"CLAUDE.md and README.md both claim `{key}` works today, and "
                f"app/{filename} no longer contains {needle!r}, which is the machinery "
                "that claim stands on.\n"
                "If the shell lost a capability the documents still promise, move its "
                "bullet to `What does not exist yet` in BOTH documents and move its "
                "entry from WORKS_TODAY to NOT_YET here. If the capability is still "
                "there and only the machinery moved, point this pair at whatever proves "
                "it now."
            )


def test_nothing_the_documents_call_missing_is_in_the_shell() -> None:
    for key, entry in NOT_YET.items():
        assert str(entry["reason"]).strip(), (
            f"The NOT_YET entry for `{key}` carries no reason. An entry with no "
            "absent-substring rule needs one in prose, naming what covers it instead, "
            "or nobody can tell a deliberate gap from an oversight."
        )
        for filename, needle in entry["absent"]:
            text = (APP / filename).read_text(encoding="utf-8")
            assert needle not in text, (
                f"CLAUDE.md and README.md both say `{key}` does not exist yet (backlog "
                f"task {entry['task']}), and app/{filename} now contains {needle!r}.\n"
                "If the capability landed, move its bullet from `What does not exist "
                "yet` to `What works today` in BOTH documents and move its entry from "
                "NOT_YET to WORKS_TODAY here, with evidence that must now be present. "
                "If it did not land, the documents are right and this line in app/ is "
                "reaching for something that is not finished."
            )


# --- Task 12: the balances screen, the markup ------------------------------

# Every id this task adds is prefixed `balances-`; the section id and the heading id
# are task 8's and are left alone.
BALANCES_IDS = {
    "balances-derived",
    "balances-status",
    "balances-busy",
    "balances-error",
    "balances-none",
    "balances-empty-roster",
    "balances-currency",
    "balances-currency-code",
    "balances-net",
    "balances-transfers",
    # Task 13's one added sentence, hidden until a payment can actually be opened.
    "balances-drill-hint",
    # Task 14. One wrapper with one hidden flag over the heading, the note and the
    # list, so they cannot be half-shown.
    "balances-pending-block",
    "balances-pending",
    # Task 15. The outcome of an answer, above every list a confirmation rebuilds,
    # and the refused claims in a block of their own on the same terms as the one
    # above.
    "balances-decision",
    "balances-rejected-block",
    "balances-rejected",
    # Task 16. Two standalone sentences, at most one of them ever shown, and one
    # wrapper over a note and a list on task 14's terms. The two spans are where the
    # only numbers on this screen that are not amounts are written.
    "balances-stale",
    "balances-stale-days",
    "balances-never",
    "balances-quiet-block",
    "balances-quiet-days",
    "balances-quiet",
}

# Every fixed sentence the screen can show lives in the markup, so a Python test can
# pin it exactly and a reviewer can read it in a diff. The code only toggles `hidden`
# and composes one row: a name, a verb and an amount.
BALANCES_MESSAGES = {
    "balances-busy": "Working these out.",
    "balances-error": "These figures could not be worked out just now.",
    "balances-none": "No payments needed. Every net position is zero.",
    "balances-empty-roster": (
        "This group has no members yet, so there is nothing to work out."
    ),
}

BALANCES_DERIVED = (
    "These figures are worked out from the recorded expenses each time this screen "
    "opens, and are never stored. An expense nobody recorded is not in them."
)


def balances_section() -> str:
    """The raw markup of `<section id="screen-balances">`, and nothing else."""
    found = re.search(
        r'<section\b[^>]*\bid="screen-balances".*?</section>', markup(), re.S
    )
    assert found is not None, "index.html carries a balances section"
    return found.group(0)


def balances_markup() -> Document:
    return Document(balances_section())


def inner(source: str, element_id: str, tag: str) -> str:
    """The inner markup of one element, with its line wrapping flattened.

    Prose wraps in the source, so a sentence can straddle a newline; comparing the
    raw text would make these assertions depend on where a line happens to break.
    """
    found = re.search(
        rf'<{tag}\b[^>]*\bid="{element_id}"[^>]*>(.*?)</{tag}>', source, re.S
    )
    assert found is not None, element_id
    return " ".join(found.group(1).split())


def test_the_balances_section_carries_every_id_the_screen_toggles() -> None:
    # A mistyped id is a blank screen and there is no browser here to catch it, so
    # the set is pinned exactly rather than checked one at a time.
    present = {attrs["id"] for _, attrs in balances_markup().tags if attrs.get("id")}
    assert present == BALANCES_IDS | {"screen-balances", "title-balances"}


def test_the_balances_heading_and_lede_say_what_the_screen_is() -> None:
    section = balances_section()
    heading = re.search(
        r'<h1\b[^>]*\bid="title-balances"[^>]*>(.*?)</h1>', section, re.S
    )
    assert heading is not None
    assert " ".join(heading.group(1).split()) == "Balances"
    lede = re.search(r'<p class="lede">(.*?)</p>', section, re.S)
    assert lede is not None
    assert " ".join(lede.group(1).split()) == "Who owes who, in the fewest payments."


def test_the_balances_section_keeps_its_router_attributes() -> None:
    # The router hides the section, labels it by its heading and moves focus there,
    # so none of these may drift while the screen is being filled.
    doc = balances_markup()
    section = doc.find("section", id="screen-balances")[0]
    assert section["class"] == "screen screen--balances"
    assert section["aria-labelledby"] == "title-balances"
    assert "hidden" in section
    assert doc.find("h1", id="title-balances")[0]["tabindex"] == "-1"


def test_the_derived_note_is_always_visible_and_says_nothing_is_stored() -> None:
    # Balances are folded out of the event log on every read and never stored. This
    # note is the screen's one honest sentence about that, so it never hides.
    note = balances_markup().find("p", id="balances-derived")[0]
    assert "hidden" not in note
    assert inner(balances_section(), "balances-derived", "p") == BALANCES_DERIVED


def test_the_status_region_announces_and_ships_every_message_hidden() -> None:
    doc = balances_markup()
    assert doc.find("div", id="balances-status")[0]["role"] == "status"
    section = balances_section()
    for element_id, sentence in BALANCES_MESSAGES.items():
        assert "hidden" in doc.find("p", id=element_id)[0], element_id
        assert inner(section, element_id, "p") == sentence


def test_the_four_lists_ship_empty_under_headings_in_the_stated_order() -> None:
    # Task 14 puts "Awaiting confirmation" between the two, so the sentence saying why
    # a payment is still suggested is read before the suggestion, and so "the figures
    # above" and "the list below" both point at something the reader can see. Task 15
    # puts "Not confirmed" below it and above the suggestions, so the two things that
    # explain why a payment is still suggested are read together. Renamed rather than
    # widened in place, because the old name stated a number that is no longer true;
    # every rule it had is kept.
    section = balances_section()
    headings = [
        " ".join(text.split())
        for text in re.findall(r"<h2\b[^>]*>(.*?)</h2>", section, re.S)
    ]
    assert headings == [
        "Net positions",
        "Awaiting confirmation",
        "Not confirmed",
        "Suggested payments",
    ]
    # No invented rows: the lists are filled from the API or not at all.
    for element_id in (
        "balances-net",
        "balances-pending",
        "balances-rejected",
        "balances-transfers",
    ):
        assert inner(section, element_id, "ul") == "", element_id


def test_the_currency_line_ships_hidden_with_no_code_in_it() -> None:
    # The code comes from the payload's `currency` field and is never hard-coded,
    # so the span is empty in the committed markup and the line starts hidden.
    section = balances_section()
    assert "hidden" in balances_markup().find("p", id="balances-currency")[0]
    assert (
        inner(section, "balances-currency", "p")
        == 'Amounts are in <span id="balances-currency-code"></span>.'
    )
    assert inner(section, "balances-currency-code", "span") == ""


def test_the_balances_placeholder_is_gone() -> None:
    section = balances_section()
    assert "Placeholder" not in section
    assert 'class="marker"' not in section
    assert 'class="notes"' not in section


# --- Task 12: the balances screen, the router region -----------------------

# These are bans, and a ban is falsified by a single occurrence. Nothing below
# claims a rendering behaviour works because a string appears in app.js: PR #30
# demonstrated that such a test passes against a mutant that reintroduces the bug.
# What the screen renders is on the hand checklist in the task file instead.


def balances_region() -> str:
    """The task 12 region of app.js: its banner comment to the end of the file."""
    source = (APP / "app.js").read_text(encoding="utf-8")
    marker = "/* --- The balances screen ---"
    assert marker in source, "app.js opens the balances region with a banner comment"
    return source[source.index(marker) :]


def test_the_balances_screen_reimplements_no_money_handling() -> None:
    # `format_amount` in src/splitwise_lite/money.py is the one display edge. Amount
    # strings arrive formatted and are inserted exactly as received, and the verb on
    # a row comes from `direction` alone, so nothing here ever reads "0.00".
    source = (APP / "app.js").read_text(encoding="utf-8")
    for forbidden in (
        "toFixed",
        "parseFloat",
        "parseInt",
        "Number(",
        "Math.round",
        "Math.floor",
        "/ 100",
        "Intl",
        "toLocaleString",
        "NumberFormat",
        "0.00",
    ):
        assert forbidden not in source, forbidden


def test_the_shell_builds_rows_without_parsing_markup() -> None:
    # Every server-provided string reaches the DOM as text, so a display name holding
    # `<`, `&` or a quote renders as those characters and is never parsed as markup.
    source = (APP / "app.js").read_text(encoding="utf-8")
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert forbidden not in source, forbidden


def test_the_shell_never_reorders_what_the_server_sent() -> None:
    # `net` is roster order and `transfers` is (from_member_id, to_member_id) order,
    # both fixed in the domain layer. The screen preserves them exactly.
    source = (APP / "app.js").read_text(encoding="utf-8")
    assert ".sort(" not in source
    assert ".reverse(" not in source


def test_the_balances_screen_keeps_no_copy_of_a_derived_figure() -> None:
    # The spec forbids a stored balance outright, and a figure held over from a
    # previous visit is "authoritative while being wrong" in miniature. There is also
    # no polling, no timer and no automatic retry.
    region = balances_region()
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "setInterval",
        "setTimeout",
        "requestAnimationFrame",
    ):
        assert forbidden not in region, forbidden


def test_the_balances_screen_registers_none_of_the_three_global_handlers() -> None:
    # A 401, a 403 member_not_linked and a request that got no answer are task 9a's
    # three screens, reused unchanged. This screen owns only "anything else", and
    # shows no sign-in prompt, no "not linked" notice and no offline message.
    region = balances_region()
    for forbidden in ("onUnauthenticated", "onNotLinked", "onOffline", "location.hash ="):
        assert forbidden not in region, forbidden


def test_the_transfer_row_is_a_disclosure_and_nothing_hand_rolled() -> None:
    # Task 13 made a transfer row a real <button type="button"> that opens on the
    # debts the payment absorbed, so `createElement('button')`, `aria-expanded` and a
    # click listener are now the shape this screen is meant to have, and those three
    # are exactly what the task 12 ban list loses. Everything else it forbade holds
    # for a stronger reason than before: a native button gets Enter, Space, the tab
    # order and the semantics for free, so an anchor, a <details>, a hand-set role, a
    # tab stop or a key, pointer or touch listener appearing here would mean somebody
    # had rebuilt a button badly.
    region = balances_region()
    for forbidden in (
        "createElement('a')",
        "createElement('details')",
        "createElement('summary')",
        "tabindex",
        "addEventListener('keydown'",
        "addEventListener('keyup'",
        "addEventListener('keypress'",
        "addEventListener('pointerdown'",
        "addEventListener('touchstart'",
        "onclick",
    ):
        assert forbidden not in region, forbidden
    # `role` is the one item on that list this test reasons about rather than
    # forbids outright. A ban on the byte sequence forbade what criterion 51
    # requires this region to ship, a role="status" live region in every debt
    # region, and the answer to that is not to spell the attribute through a
    # variable: an indirection is a hole in the ban, and it takes the word out of
    # the source where a reader and a grep both look for it. So the rule is the one
    # the ban always meant. Every attribute here is named by a literal, which is
    # what makes the source readable in full, and the only role this region sets is
    # `status`. An interactive role hand-set on a div still cannot get in, and now
    # neither can a double-quoted, templated or aliased spelling of one.
    for named in re.findall(r"setAttribute\(\s*([^,]+),", region):
        assert re.fullmatch(r"'[a-z-]+'", named.strip()), named
    for value in re.findall(
        r"""setAttribute\(\s*['"`]role['"`]\s*,\s*([^)]*)\)""", region
    ):
        assert value.strip() == "'status'", value
    # The property form of the same act, which no rule about setAttribute can see.
    assert re.search(r"\.role\s*=", region) is None


def test_the_drill_down_never_moves_focus() -> None:
    # The button that was activated keeps focus when its region opens and keeps it
    # when the region closes. The only control that closes a region sits outside it
    # and takes focus when it is activated, so focus is never inside a region at the
    # moment that region becomes hidden and the browser never has to move it to
    # <body>. Issue #37 records that the harness counts focus() on a hidden element
    # as a focus, so a scenario asserting a focus move here would report a pass it
    # had not earned; this ban is what covers it instead.
    assert ".focus(" not in balances_region()


# --- Task 12: the balances screen, the layout ------------------------------


def balances_styles() -> str:
    """The task 12 block of styles.css: its banner comment to the end of the file."""
    css = styles()
    marker = "/* Balances ---"
    assert marker in css, "styles.css opens the balances block with a banner comment"
    return css[css.index(marker) :]


def without_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_every_balances_selector_is_namespaced_to_this_screen() -> None:
    # Two other branches edit styles.css at the same time, so a prefixed selector
    # cannot collide with a name of theirs or restyle a component they share.
    selectors = []
    for rule in without_comments(balances_styles()).split("}"):
        head = rule.split("{")[0].strip()
        if head:
            selectors.extend(part.strip() for part in head.split(","))
    assert selectors
    for selector in selectors:
        assert selector.startswith(".balances-"), selector


def test_the_balances_block_never_moves_a_row_out_of_document_order() -> None:
    # Visual order matches DOM order in both lists, so an amount can never be read
    # ahead of the name it belongs to.
    block = without_comments(balances_styles())
    for forbidden in ("row-reverse", "column-reverse", "position: absolute"):
        assert forbidden not in block, forbidden
    # `order`, and not the `order` inside `border`.
    assert re.search(r"(?<![-\w])order\s*:", block) is None


def test_only_the_five_controls_that_really_do_something_look_tappable() -> None:
    # The pointer cursor is the one affordance this screen offers and exactly the
    # five controls that really do something offer it: the two disclosures that open
    # a region, task 14's Mark as paid, which records a payment, and task 15's Confirm
    # and Reject, which answer one. A transfer row whose payload carries no usable
    # provenance is drawn inert and has to look inert, so a cursor on the row itself,
    # on a debt row, on a pending row, on a rejected row or on a list would be a
    # promise the screen cannot keep. Still no generated glyph either: the open and
    # closed indicators are text app.js writes, which a reader can be told to ignore
    # and a copy carries. Renamed rather than widened in place, because the old name
    # stated a number that is no longer true; every rule it had is kept.
    block = without_comments(balances_styles())
    # `content`, and not the `content` inside `justify-content`.
    assert re.search(r"(?<![-\w])content\s*:", block) is None
    carrying = []
    for rule in block.split("}"):
        head, _, body = rule.partition("{")
        if "cursor" not in body:
            continue
        assert re.findall(r"cursor:\s*([a-z-]+)", body) == ["pointer"], head
        selectors = [part.strip() for part in head.split(",")]
        assert selectors
        carrying.extend(selectors)
    # Counted by selector rather than by rule, and pinned as an equality rather than a
    # membership, so a sixth control cannot be admitted by adding it to the list a
    # rule already carries.
    assert sorted(carrying) == [
        ".balances-confirm-button",
        ".balances-debt-button",
        ".balances-mark-button",
        ".balances-reject-button",
        ".balances-transfer-button",
    ]


def test_all_five_controls_show_a_keyboard_user_where_they_are() -> None:
    # Five controls now, all five in the tab order with no tabindex written for any of
    # them, so all five have to say which one the keyboard is on. Renamed rather than
    # widened in place, because the old name stated a number that is no longer true;
    # every rule it had is kept.
    block = without_comments(balances_styles())
    focused = []
    for rule in block.split("}"):
        head, _, body = rule.partition("{")
        for selector in [part.strip() for part in head.split(",")]:
            if not selector.endswith(":focus-visible"):
                continue
            found = re.search(r"outline:\s*([^;]+);", body)
            assert found is not None, selector
            assert "none" not in found.group(1), selector
            focused.append(selector)
    # An equality, so a sixth control that skipped its focus ring fails here rather
    # than passing because the five named ones still have theirs.
    assert sorted(focused) == [
        ".balances-confirm-button:focus-visible",
        ".balances-debt-button:focus-visible",
        ".balances-mark-button:focus-visible",
        ".balances-reject-button:focus-visible",
        ".balances-transfer-button:focus-visible",
    ]


def test_every_transfer_row_clears_the_hit_area_floor() -> None:
    # Already 44px tall, so no layout shifts when task 13 makes the row tappable.
    heights = [
        float(value)
        for value in re.findall(r"min-height:\s*([0-9.]+)px", balances_styles())
    ]
    assert heights
    assert min(heights) >= 44


def test_no_balances_rule_declares_a_break_of_its_own() -> None:
    """No rule on this screen declares `overflow-wrap`. The root declares it once.

    This inverts the test it replaces. `test_a_long_display_name_wraps_rather_than_
    being_cut_off` asserted that `overflow-wrap: break-word` appeared somewhere in
    this block, and that was satisfied by one declaration anywhere in it, which is
    how three name-bearing classes shipped on PR #56 with no break rule at all. It
    is now one inherited declaration on `body`, so a copy here is not belt and
    braces: it is a second place to update, and the class of defect the deleted test
    was written to catch was a class that fell off a hand-maintained list.

    The three things the replaced test asserted are all still asserted, wider. That
    `break-word` appears in this block is inverted here. That nothing in this block
    carries `text-overflow` or `overflow: hidden`, and that `.balances-figure` is the
    only selector refusing a wrap, both widen from this block to the whole file in
    `test_nothing_in_the_shell_takes_the_break_rule_back`.
    """
    declaring = sorted(
        selector
        for selector, body in balances_declarations().items()
        if "overflow-wrap" in body
    )
    assert not declaring, (
        f"The balances block declares overflow-wrap on {declaring}. The root "
        "declaration on `body` already covers every one of them, so a per-class copy "
        "here is a second place to update and nothing else. Delete it."
    )


def balances_declarations() -> dict[str, str]:
    """Selector to declarations, over every rule in the balances block.

    The block carries no @media and no nesting, which
    `test_every_balances_selector_is_namespaced_to_this_screen` pins, so splitting on
    the braces is the whole parse.
    """
    rules: dict[str, str] = {}
    for rule in without_comments(balances_styles()).split("}"):
        if "{" not in rule:
            continue
        head, body = rule.split("{", 1)
        for selector in head.split(","):
            name = selector.strip()
            if name:
                rules[name] = rules.get(name, "") + body
    return rules


def test_no_row_carries_its_meaning_in_colour_alone() -> None:
    # "owes" and "is owed" are told apart by the words first, and rows are separated
    # by a rule rather than by a tint.
    block = without_comments(balances_styles())
    assert "border-top" in block or "border-bottom" in block


def test_no_shell_file_prints_a_currency_symbol() -> None:
    # One group, one currency, named once above the net list. `format_amount`
    # produces "12.50" without a symbol and the front end does not get to add one.
    for name in ("index.html", "styles.css", "app.js"):
        source = (APP / name).read_text(encoding="utf-8")
        for symbol in ("$", "£", "€"):
            assert symbol not in source, name


def test_the_balances_block_adds_no_animation() -> None:
    # Nothing on this screen moves, so there is nothing for the reduced-motion block
    # at the end of the file to have to switch off.
    block = without_comments(balances_styles())
    for forbidden in ("animation", "transition", "@keyframes"):
        assert forbidden not in block, forbidden


# --- Task 13: the transfer drill-down --------------------------------------

DRILL_HINT = "Open a payment to see the debts behind it."


def test_the_drill_down_hint_ships_hidden_between_the_heading_and_the_list() -> None:
    # The one sentence task 13 adds to the markup. It is shown at most once on the
    # screen, so it lives here rather than in app.js, where a Python test can pin it
    # exactly and a reviewer can read it in a diff. It ships hidden and is revealed
    # only once at least one rendered transfer row is a control that really opens.
    section = balances_section()
    assert inner(section, "balances-drill-hint", "p") == DRILL_HINT
    opening = re.search(r'<p\b[^>]*\bid="balances-drill-hint"[^>]*>', section)
    assert opening is not None
    assert " hidden" in opening.group(0)
    # Between the heading it belongs to and the list it talks about, so a screen
    # reader meets it before the rows rather than after them.
    heading = section.index("Suggested payments")
    hint = section.index('id="balances-drill-hint"')
    transfers = section.index('id="balances-transfers"')
    assert heading < hint < transfers
    # Outside #balances-status: that region holds exactly the four fixed messages
    # task 12 wrote, of which at most one is ever visible, and this hint is shown
    # alongside a list rather than instead of one.
    status = re.search(r'<div\b[^>]*\bid="balances-status".*?</div>', section, re.S)
    assert status is not None
    assert "balances-drill-hint" not in status.group(0)


# --- Task 14: the pending block and the action on a transfer row ------------

BALANCES_PENDING_NOTE = (
    "These are marked as paid and not confirmed yet. They are not counted in the "
    "figures above, and they stay in the suggested payments below, until the person "
    "receiving the money confirms."
)


def test_the_pending_block_ships_hidden_with_its_heading_and_its_note() -> None:
    # One wrapper with one hidden flag, so the heading, the note and the list cannot
    # be half-shown: a bare "Awaiting confirmation" over an empty list on an ordinary
    # day is noise. The prose is pinned exactly, because it is the sentence that stops
    # a standing suggestion beside a recorded payment reading as a bug.
    section = balances_section()
    block = re.search(
        r'<div\b[^>]*\bid="balances-pending-block"[^>]*>(.*?)</div>', section, re.S
    )
    assert block is not None
    assert "hidden" in balances_markup().find("div", id="balances-pending-block")[0]
    inside = block.group(1)
    heading = re.search(r"<h2\b[^>]*>(.*?)</h2>", inside, re.S)
    assert heading is not None
    assert " ".join(heading.group(1).split()) == "Awaiting confirmation"
    note = re.search(r'<p class="balances-note">(.*?)</p>', inside, re.S)
    assert note is not None
    assert " ".join(note.group(1).split()) == BALANCES_PENDING_NOTE
    assert '<ul class="balances-list" id="balances-pending"></ul>' in " ".join(
        inside.split()
    )


def test_the_pending_block_sits_between_the_net_list_and_the_suggestions() -> None:
    # Above the suggested payments, so the sentence explaining why a payment is still
    # suggested is read before the suggestion.
    section = balances_section()
    assert (
        section.index('id="balances-net"')
        < section.index('id="balances-pending-block"')
        < section.index("Suggested payments")
    )


def test_the_pending_block_is_the_only_thing_task_fourteen_added_to_the_document(
) -> None:
    # Every other section of the document is untouched: one block goes in, inside the
    # balances section, and nothing else in index.html changes.
    document_text = markup()
    outside = document_text.replace(balances_section(), "")
    for owned in ("balances-pending", "Awaiting confirmation", "marked as paid"):
        assert owned not in outside, owned


def test_the_action_region_never_takes_space_while_it_is_empty() -> None:
    # The status line ships empty and is never hidden, because a live region whose
    # text changes while it is hidden announces nothing in several screen readers. So
    # it must take no vertical space of its own until there is something to say. Task
    # 15's two are here on the same terms: the line a pending row says while it is
    # answering, and the sentence at the top of the screen saying what an answer did.
    rules = balances_declarations()
    for selector in (
        ".balances-action-status",
        ".balances-answer-status",
        ".balances-decision",
    ):
        assert selector in rules, selector
        assert "min-height" not in rules[selector], selector
        assert "padding" not in rules[selector], selector
    assert ":empty" not in without_comments(balances_styles())
    # And neither of task 15's is ever given `hidden`, in the markup or in the code.
    section = balances_section()
    assert 'id="balances-decision" role="status"></p>' in section
    assert "balancesDecision.hidden" not in (APP / "app.js").read_text(
        encoding="utf-8"
    )


def test_the_figure_is_still_the_only_thing_that_refuses_to_wrap() -> None:
    # An amount never breaks mid-number, and nothing else on this screen is allowed to
    # refuse a wrap, however long a display name is.
    nowrap = [
        selector
        for selector, body in balances_declarations().items()
        if "white-space: nowrap" in body
    ]
    assert nowrap == [".balances-figure"]


# --- Task 15: the receiver answers a claim ----------------------------------


BALANCES_REJECTED_NOTE = (
    "These were marked as paid and the person receiving the money did not confirm "
    "them. They are not counted in the figures above, and whoever paid can mark the "
    "payment again."
)


def test_the_rejected_block_ships_hidden_with_its_heading_note_and_empty_list() -> None:
    # One wrapper with one hidden flag over the heading, the note and the list, for
    # the reason task 14 gave: a bare "Not confirmed" over an empty list on an
    # ordinary day is noise.
    section = balances_section()
    block = re.search(
        r'<div\b[^>]*\bid="balances-rejected-block"[^>]*>(.*?)</div>', section, re.S
    )
    assert block is not None
    assert "hidden" in balances_markup().find("div", id="balances-rejected-block")[0]
    inside = block.group(1)
    heading = re.search(r"<h2\b[^>]*>(.*?)</h2>", inside, re.S)
    assert heading is not None
    assert " ".join(heading.group(1).split()) == "Not confirmed"
    note = re.search(r'<p class="balances-note">(.*?)</p>', inside, re.S)
    assert note is not None
    assert " ".join(note.group(1).split()) == BALANCES_REJECTED_NOTE
    assert '<ul class="balances-list" id="balances-rejected"></ul>' in " ".join(
        inside.split()
    )


def test_the_decision_line_ships_empty_and_announces_without_ever_hiding() -> None:
    # A live region whose text changes while it is hidden announces nothing in several
    # screen readers, so it is in the document from the start, empty, and is never
    # given `hidden` in the markup or by the code. The app.js half is a ban, which is
    # what PR #30 permits: one occurrence falsifies it.
    section = balances_section()
    line = balances_markup().find("p", id="balances-decision")[0]
    assert "hidden" not in line
    assert line["role"] == "status"
    assert line["class"] == "balances-decision"
    assert inner(section, "balances-decision", "p") == ""
    source = (APP / "app.js").read_text(encoding="utf-8")
    assert "decisionLine.hidden" not in source


def test_the_two_things_task_fifteen_added_sit_in_the_stated_order() -> None:
    # The outcome above every list a confirmation rebuilds, and the refused claims
    # between the awaiting block and the suggestions, so the two things that explain
    # why a payment is still suggested are read together.
    section = balances_section()
    assert (
        section.index('id="balances-derived"')
        < section.index('id="balances-decision"')
        < section.index("Net positions")
        < section.index('id="balances-pending-block"')
        < section.index('id="balances-rejected-block"')
        < section.index("Suggested payments")
    )


def test_the_two_additions_are_the_only_thing_task_fifteen_put_in_the_document() -> None:
    # Every other section of the document is untouched: two elements go in, inside the
    # balances section, and nothing else in index.html changes.
    outside = markup().replace(balances_section(), "")
    for owned in (
        "balances-rejected",
        "balances-decision",
        "Not confirmed",
        "did not confirm them",
    ):
        assert owned not in outside, owned


# --- Task 16: the incompleteness signal, the markup -------------------------
#
# Appended as one block. Every sentence below is fixed prose in the markup and the code
# only toggles `hidden` and writes one number or one name, which is the rule
# app/index.html states: prose in markup is prose a Python test can pin exactly and a
# reviewer can read in a diff.

BALANCES_STALE = (
    "Nothing new has been recorded for "
    '<span id="balances-stale-days"></span> days. These figures may be missing recent '
    "spending."
)

BALANCES_NEVER = (
    "Nothing has been recorded in this group yet, so there is nothing behind these "
    "figures."
)

BALANCES_QUIET_NOTE = (
    "No expense entered in the last "
    '<span id="balances-quiet-days"></span> days by:'
)

FEED_STALE = (
    "Nothing new has been recorded here for "
    '<span id="feed-stale-days"></span> days. The app only knows what people enter.'
)

# The six ids task 16 adds to the two screens, which is what criterion 33 reads.
STALENESS_IDS = (
    "balances-stale",
    "balances-stale-days",
    "balances-never",
    "balances-quiet-block",
    "balances-quiet-days",
    "balances-quiet",
    "feed-stale",
    "feed-stale-days",
)


def test_the_two_age_sentences_ship_hidden_with_their_number_left_empty() -> None:
    # Standalone <p hidden> elements, like balances-drill-hint, because each is
    # self-contained and at most one of the two is ever shown. The span is empty in the
    # committed document: every number on screen comes from the payload.
    section = balances_section()
    doc = balances_markup()
    for element_id, sentence in (
        ("balances-stale", BALANCES_STALE),
        ("balances-never", BALANCES_NEVER),
    ):
        note = doc.find("p", id=element_id)[0]
        assert "hidden" in note, element_id
        assert note["class"] == "balances-note", element_id
        assert inner(section, element_id, "p") == sentence, element_id
    assert inner(section, "balances-stale-days", "span") == ""


def test_the_quiet_block_is_one_wrapper_over_a_note_and_an_empty_list() -> None:
    # One wrapper carrying one hidden flag, for the reason task 14 gave: a bare intro
    # over an empty list on an ordinary day is noise. The list ships empty like every
    # other list on this screen, because every row comes from the API or there is no
    # row.
    section = balances_section()
    block = re.search(
        r'<div\b[^>]*\bid="balances-quiet-block"[^>]*>(.*?)</div>', section, re.S
    )
    assert block is not None
    assert "hidden" in balances_markup().find("div", id="balances-quiet-block")[0]
    inside = block.group(1)
    note = re.search(r'<p class="balances-note">(.*?)</p>', inside, re.S)
    assert note is not None
    assert " ".join(note.group(1).split()) == BALANCES_QUIET_NOTE
    assert '<ul class="balances-list" id="balances-quiet"></ul>' in " ".join(
        inside.split()
    )
    # No heading of its own, so the four headings this screen carries stay four and
    # test_the_four_lists_ship_empty_under_headings_in_the_stated_order is untouched.
    assert "<h2" not in inside


def test_the_signal_sits_between_the_derived_note_and_everything_it_qualifies() -> None:
    # Immediately after the note saying the figures are derived, because these three
    # are the rest of that sentence: what the figures are worked out from, and what is
    # missing from them. Inserted between balances-derived and balances-decision, which
    # leaves every link of task 15's chain intact.
    section = balances_section()
    assert (
        section.index('id="balances-derived"')
        < section.index('id="balances-stale"')
        < section.index('id="balances-never"')
        < section.index('id="balances-quiet-block"')
        < section.index('id="balances-decision"')
        < section.index("Net positions")
    )


def test_no_new_sentence_on_either_screen_carries_a_digit() -> None:
    # Criterion 33. Every number on screen comes from the payload, so the threshold
    # cannot be stated in two places that disagree. Read over the new elements' own
    # text rather than over the whole document, so this fails for the reason it names.
    doc = Document(markup())
    source = markup()
    for element_id in STALENESS_IDS:
        found = [attrs for _, attrs in doc.tags if attrs.get("id") == element_id]
        assert len(found) == 1, element_id
    for element_id, tag in (
        ("balances-stale", "p"),
        ("balances-never", "p"),
        ("balances-quiet-block", "div"),
        ("feed-stale", "p"),
    ):
        text = re.sub(r"<[^>]*>", " ", inner(source, element_id, tag))
        assert re.search(r"\d", text) is None, (element_id, text)
    # And the threshold itself appears nowhere under app/, in any file, so there is one
    # copy of it and it is in src/.
    for filename in ("index.html", "app.js", "styles.css"):
        assert "QUIET_AFTER_DAYS" not in (APP / filename).read_text(encoding="utf-8")


def test_the_feed_carries_one_age_sentence_above_the_list_it_qualifies() -> None:
    source = markup()
    feed = re.search(
        r'<section\b[^>]*\bid="screen-feed".*?</section>', source, re.S
    )
    assert feed is not None
    section = feed.group(0)
    assert inner(section, "feed-stale", "p") == FEED_STALE
    assert 'id="feed-stale" hidden' in section
    assert (
        section.index('id="feed-stale"')
        < section.index('id="feed-currency"')
        < section.index('id="feed-list"')
    )
    # One element, and the balances sentences are not in the feed section.
    assert section.count('id="feed-stale"') == 1
    for owned in ("balances-stale", "balances-quiet", "may be missing recent spending"):
        assert owned not in section, owned


def test_the_balances_sentences_are_the_only_thing_task_sixteen_put_outside_the_feed() -> None:
    # Every other section of the document is untouched: the feed gains one element and
    # the balances screen gains three, and nothing else in index.html changes.
    source = markup()
    outside = source.replace(balances_section(), "")
    for owned in (
        "balances-stale",
        "balances-never",
        "balances-quiet",
        "may be missing recent spending",
        "nothing behind these figures",
        "No expense entered in the last",
    ):
        assert owned not in outside, owned


def test_the_feed_sentence_reuses_no_balances_class_and_gains_one_rule() -> None:
    # Criterion 31. The balances sentences reuse .balances-note and need no rule; the
    # feed one is a new class and gets one, in the feed block of styles.css where every
    # selector is namespaced feed- or expense-, never in the balances block, whose own
    # test refuses a selector that is not prefixed .balances-.
    css = styles()
    assert ".feed-stale" in css
    assert ".feed-stale" not in balances_styles()
    # And it introduces neither of the two things the balances block is held to.
    block = without_comments(styles())
    rule = re.search(r"\.feed-stale\s*\{([^}]*)\}", block)
    assert rule is not None
    assert "white-space: nowrap" not in rule.group(1)
    assert ":empty" not in rule.group(1)
