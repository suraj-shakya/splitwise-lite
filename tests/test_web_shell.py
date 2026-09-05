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


def gate_submit_handler() -> str:
    """The body of app.js's form submit handler, so the assertions below are about
    the one function that decides what a rejected sign-in shows."""
    router = (APP / "app.js").read_text(encoding="utf-8")
    start = router.index("function submitted(")
    end = router.index("function wire(", start)
    return router[start:end]


def test_a_refused_sign_in_tells_the_person_why() -> None:
    """A wrong password must put a message on the gate.

    The regression this pins: the 401 handler re-shows the gate with a blank message,
    so a submit handler that skips 401 leaves the button greying and un-greying as the
    entire feedback for a wrong password. There is no JavaScript runner in this repo
    and no browser in this suite, so this is asserted over the source of the one
    function involved rather than by driving it. It is named here as a structural
    check, not as a substitute for opening the page.
    """
    handler = gate_submit_handler()
    # The exact exclusion that caused it. 401 is the commonest refusal this form
    # produces, not one to stay quiet about.
    assert "status !== 401" not in handler
    assert "!== 401" not in handler
    # It writes the message and reveals the element that carries it.
    assert "gateError.textContent = error.message" in handler
    assert "gateError.hidden = false" in handler
    # And it re-shows the gate, because the 401 handler has just replaced what is on
    # screen and blanked the message.
    assert "show('gate')" in handler
    # The only thing it stays quiet about is a request that got no answer, because
    # the offline notice is up instead and the gate deliberately is not.
    assert "error.status === 0" in handler
    assert "error.status >= 500" in handler


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


def test_every_screen_names_the_task_that_fills_it() -> None:
    text = document().text
    assert "Placeholder. Task 11 fills this with the expense feed." in text
    assert "Placeholder. Task 10 fills this with expense entry." in text


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


def test_the_worker_precaches_exactly_the_shell() -> None:
    assert precache_entries() == SHELL_PRECACHE


def test_every_precache_entry_resolves_to_a_file() -> None:
    for entry in precache_entries():
        assert resolve_app_url(entry).is_file(), entry


# --- Docs ------------------------------------------------------------------

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


def test_no_document_claims_the_shell_shows_real_data() -> None:
    combined = claude_md() + readme()
    assert "placeholder" in combined.lower()


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


def test_the_two_lists_ship_empty_under_headings_in_the_stated_order() -> None:
    section = balances_section()
    headings = [
        " ".join(text.split())
        for text in re.findall(r"<h2\b[^>]*>(.*?)</h2>", section, re.S)
    ]
    assert headings == ["Net positions", "Suggested payments"]
    # No invented rows: the lists are filled from the API or not at all.
    for element_id in ("balances-net", "balances-transfers"):
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


def test_no_transfer_row_pretends_to_be_tappable() -> None:
    # Task 13 makes a transfer row expand into the pairwise debts it absorbed. Until
    # then an affordance that does nothing is worse than none, so the row is not an
    # anchor, a button or a disclosure, carries no interactive role or tab stop, and
    # has no click, key or pointer handler.
    region = balances_region()
    for forbidden in (
        "createElement('a')",
        "createElement('button')",
        "createElement('details')",
        "createElement('summary')",
        "aria-expanded",
        "tabindex",
        "setAttribute('role'",
        "addEventListener('click'",
        "addEventListener('keydown'",
        "addEventListener('keyup'",
        "addEventListener('keypress'",
        "addEventListener('pointerdown'",
        "addEventListener('touchstart'",
        "onclick",
    ):
        assert forbidden not in region, forbidden


def test_nothing_asks_for_provenance_that_is_not_in_the_payload() -> None:
    # `payer_debts` and `receiver_credits` are task 13's, along with the payload
    # change that carries them.
    source = (APP / "app.js").read_text(encoding="utf-8")
    assert "payer_debts" not in source
    assert "receiver_credits" not in source
