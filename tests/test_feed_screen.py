"""Structural assertions over the expense feed screen in `app/`.

Task 11 of plans/backlog.md, sharpened in plans/tasks/11-expense-feed.md.

Standard library only, and nothing here imports `splitwise_lite`: the shell is
independent of the domain layer, and a test that reached into the package would
quietly undo that. Paths are resolved from this file, never from the current working
directory.

**What this file may and may not claim.** Every assertion below is one of two kinds:
a fact about the committed markup, which a browser reads the same way this parser
does, or a *ban* on a token appearing in a source file, which the file itself
falsifies. There is no JavaScript test runner in this repo and this task does not add
one, so nothing here reads `app/app.js` and claims a rendering behaviour works. That
second kind has been rejected three times, most recently on PR #30, where a reviewer
showed such a test passing two mutants that reintroduced the bug it claimed to cover.
Rendering behaviour is on the hand checklist in the task file instead, labelled as
unverified by the suite.

The small HTML parser is re-declared here rather than imported from
`tests/test_web_shell.py` on purpose: two branches are editing that file, and a dozen
duplicated lines are cheaper than a shared edit to it. This one builds a tree, because
these criteria are about containment ("inside `#screen-feed`", "inside `feed-error`")
and the flat parser next door cannot see nesting.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"

# The six elements the feed screen gains, each exactly once in the document.
FEED_IDS = [
    "feed-currency",
    "feed-loading",
    "feed-empty",
    "feed-error",
    "feed-retry",
    "feed-list",
]

# The four that must start hidden, so the first paint shows one state at most.
HIDDEN_AT_REST = ["feed-currency", "feed-loading", "feed-empty", "feed-error"]

ROUTES = ["#/feed", "#/add", "#/balances"]

# Elements that never have a closing tag, so the parser's stack must not wait for one.
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class Element:
    """One node: its tag, its attributes, and its children and text in order."""

    def __init__(self, tag: str, attrs: dict, parent: "Element | None") -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.nodes: list = []

    @property
    def children(self) -> list["Element"]:
        return [node for node in self.nodes if isinstance(node, Element)]

    def descendants(self):
        for node in self.nodes:
            if isinstance(node, Element):
                yield node
                yield from node.descendants()

    def contains(self, other: "Element") -> bool:
        walk = other.parent
        while walk is not None:
            if walk is self:
                return True
            walk = walk.parent
        return False

    @property
    def text(self) -> str:
        """Every text node under this element, with runs of whitespace collapsed."""
        parts: list[str] = []

        def collect(element: "Element") -> None:
            for node in element.nodes:
                if isinstance(node, Element):
                    collect(node)
                else:
                    parts.append(node)

        collect(self)
        return " ".join(" ".join(parts).split())


class Tree(HTMLParser):
    """The document as a tree, so containment can be asserted rather than guessed."""

    def __init__(self, markup: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {}, None)
        self.stack = [self.root]
        self.feed(markup)

    def handle_starttag(self, tag: str, attrs) -> None:
        element = Element(tag, dict(attrs), self.stack[-1])
        self.stack[-1].nodes.append(element)
        if tag not in VOID:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.stack[-1].nodes.append(Element(tag, dict(attrs), self.stack[-1]))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].nodes.append(data)

    def by_id(self, wanted: str) -> list[Element]:
        return [
            element
            for element in self.root.descendants()
            if element.attrs.get("id") == wanted
        ]

    def one(self, wanted: str) -> Element:
        found = self.by_id(wanted)
        assert len(found) == 1, f"{wanted} appears {len(found)} times"
        return found[0]

    def tagged(self, tag: str) -> list[Element]:
        return [
            element for element in self.root.descendants() if element.tag == tag
        ]


def markup() -> str:
    return (APP / "index.html").read_text(encoding="utf-8")


def tree() -> Tree:
    return Tree(markup())


def feed_screen(doc: Tree) -> Element:
    return doc.one("screen-feed")


def paragraphs(element: Element) -> list[str]:
    return [child.text for child in element.children if child.tag == "p"]


# --- The document region ----------------------------------------------------


def test_the_six_feed_elements_exist_once_each_inside_the_feed_screen() -> None:
    doc = tree()
    feed = feed_screen(doc)
    for wanted in FEED_IDS:
        element = doc.one(wanted)
        assert feed.contains(element), f"{wanted} is outside #screen-feed"


def test_the_feed_list_is_an_empty_ul_in_the_committed_document() -> None:
    # No sample row and no template markup: on a money app a plausible fake amount is
    # indistinguishable from a wrong real one.
    feed_list = tree().one("feed-list")
    assert feed_list.tag == "ul"
    assert feed_list.children == []
    assert feed_list.text == ""


def test_the_four_states_start_hidden() -> None:
    # So the first paint shows one state at most and never all four.
    doc = tree()
    for wanted in HIDDEN_AT_REST:
        assert "hidden" in doc.one(wanted).attrs, wanted


def test_the_retry_control_is_a_plain_button_inside_the_error_state() -> None:
    doc = tree()
    retry = doc.one("feed-retry")
    assert retry.tag == "button"
    assert retry.attrs.get("type") == "button"
    assert doc.one("feed-error").contains(retry)


def test_the_empty_state_offers_one_plain_anchor_to_the_add_screen() -> None:
    # Routing is anchors plus hashchange, per task 8, so no click handler is
    # registered on it and none is needed.
    empty = tree().one("feed-empty")
    anchors = [node for node in empty.descendants() if node.tag == "a"]
    assert len(anchors) == 1
    assert anchors[0].attrs.get("href") == "#/add"
    assert "onclick" not in anchors[0].attrs


def test_the_feed_screen_no_longer_carries_a_placeholder() -> None:
    assert "placeholder" not in feed_screen(tree()).text.lower()


def test_the_feed_heading_and_lede_are_unchanged_byte_for_byte() -> None:
    source = markup()
    assert '<h1 class="screen-title" id="title-feed" tabindex="-1">Feed</h1>' in source
    assert (
        '<p class="lede">Every expense the group has recorded, newest first.</p>'
        in source
    )


def test_the_committed_feed_markup_invents_no_data() -> None:
    # No amount, no currency symbol, no member name, no date and no description. A
    # digit anywhere in this screen's copy would be one of the first four.
    text = feed_screen(tree()).text
    for symbol in ("$", "£", "€", "%"):
        assert symbol not in text
    assert re.search(r"\d", text) is None


def test_every_new_feed_id_and_class_is_namespaced() -> None:
    # The sibling branch on task 12 edits the same three files. Namespacing every new
    # id and class under `feed-` or `expense-` is what stops the two sets of selectors
    # from colliding when the branches merge.
    inherited_ids = {"screen-feed", "title-feed"}
    inherited_classes = {"screen", "screen--feed", "screen-title", "lede"}
    feed = feed_screen(tree())
    for element in [feed, *feed.descendants()]:
        found = element.attrs.get("id")
        if found is not None and found not in inherited_ids:
            assert found.startswith(("feed-", "expense-")), found
        for name in (element.attrs.get("class") or "").split():
            if name not in inherited_classes:
                assert name.startswith(("feed-", "expense-")), name


# --- The copy ---------------------------------------------------------------


def test_the_in_flight_line_says_what_is_happening() -> None:
    assert tree().one("feed-loading").text == "Fetching the group's expenses."


def test_the_empty_state_reads_exactly_as_promised() -> None:
    empty = tree().one("feed-empty")
    assert paragraphs(empty) == [
        "Nobody has recorded an expense in this group yet.",
        "The app only knows what people enter. Once someone adds a spend it appears "
        "here, newest first.",
    ]
    anchors = [node for node in empty.descendants() if node.tag == "a"]
    assert [anchor.text for anchor in anchors] == ["Add the first expense"]


def test_the_error_state_reads_exactly_as_promised() -> None:
    doc = tree()
    assert paragraphs(doc.one("feed-error")) == [
        "The feed did not arrive. Nothing you have recorded is lost."
    ]
    assert doc.one("feed-retry").text == "Try again"


def test_the_empty_copy_never_says_the_ledger_is_settled() -> None:
    # The spec's largest risk is a half-filled ledger that looks authoritative while
    # being wrong. An empty group is not a settled one, and must not read as one.
    text = tree().one("feed-empty").text.lower()
    for banned in (
        "settled",
        "square",
        "balanced",
        "complete",
        "up to date",
        "nothing owed",
        "no debts",
        "all clear",
    ):
        assert banned not in text, banned


def test_the_error_copy_claims_nothing_about_the_ledger_contents() -> None:
    # A request that did not arrive is not an empty ledger and must never read as one.
    text = tree().one("feed-error").text.lower()
    for banned in ("no expenses", "nothing recorded", "nothing yet"):
        assert banned not in text, banned


def test_no_feed_copy_claims_the_ledger_is_current() -> None:
    # Task 16 owns the staleness signal. Nothing here may claim what it will have to
    # contradict, and there is no relative date vocabulary anywhere on this screen.
    text = feed_screen(tree()).text.lower()
    for banned in (
        "up to date",
        "everything is here",
        "today",
        "yesterday",
        "days ago",
        "just now",
        "last updated",
    ):
        assert banned not in text, banned


# --- The companion to the narrowed nav rule ---------------------------------


def test_no_anchor_in_the_document_points_outside_the_three_routes() -> None:
    """The companion to narrowing the nav test, the way tasks 7 and 9a wrote theirs.

    `test_the_nav_names_itself_and_lists_the_three_screens_in_order` used to sweep
    every anchor in the document, so it incidentally refused a fourth route appearing
    anywhere at all. Narrowing it to the tab bar gives that up, so the part worth
    keeping is asserted here instead: every anchor in the whole document names one of
    the three routes `ROUTES` holds, and none of them leaves the origin. Without this,
    a screen could quietly introduce `#/settings` and only the loosened rule would be
    there to notice.
    """
    anchors = [
        element
        for element in tree().tagged("a")
        if element.attrs.get("href") is not None
    ]
    assert anchors
    for anchor in anchors:
        href = anchor.attrs["href"]
        assert "://" not in href, href
        assert not href.startswith("//"), href
        assert href in ROUTES, href


# --- Token bans over app/app.js ---------------------------------------------
#
# Each of these is falsifiable by the file itself: a reader opens `app/app.js` and
# sees whether the token is there. None of them claims a feature works. That second
# kind of test is what PR #30 disproved, and rendering behaviour lives on the task
# file's hand checklist instead.


def app_js() -> str:
    return (APP / "app.js").read_text(encoding="utf-8")


def test_app_js_builds_the_dom_without_ever_parsing_markup() -> None:
    # Every piece of user data reaches the DOM through textContent, so an expense
    # described as `<img src=x onerror=alert(1)>` renders as literal characters.
    source = app_js()
    for banned in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        assert banned not in source, banned


def test_app_js_imposes_no_ordering_of_its_own() -> None:
    # web.py owns the ordering rule and has it written down. A second one here would
    # be a second contract to keep in step with the first.
    source = app_js()
    assert "sort(" not in source
    assert "reverse(" not in source


def test_app_js_never_reads_the_client_clock() -> None:
    # `new Date(created_at)` renders the server's instant in the reader's timezone.
    # A Date with no argument would be the client clock, which nothing here may read:
    # relative time is task 16's vocabulary.
    source = app_js()
    assert "Date.now(" not in source
    assert "new Date()" not in source


def test_the_feed_adds_no_history_entry_and_no_second_replace_state() -> None:
    """Toggling a row changes no URL and pushes nothing onto the history stack.

    `replaceState` is counted rather than banned outright. Task 8's router already
    holds one, so a whole-file ban would fail against `master` before this task wrote
    a line; see the correction dated 2026-09-06 in plans/tasks/11-expense-feed.md.
    Pinning the single occurrence to the router's own line keeps "the feed adds no
    second one" falsifiable instead of dropping the guard.
    """
    source = app_js()
    assert "pushState" not in source
    assert re.search(r"location\.hash\s*=[^=]", source) is None
    carrying = [line.strip() for line in source.splitlines() if "replaceState" in line]
    assert carrying == ["window.history.replaceState(null, '', DEFAULT_ROUTE);"]


def test_the_feed_keeps_nothing_in_browser_storage() -> None:
    # No response is cached anywhere that outlives the render: a copy of server state
    # kept in the browser is how a signed-out page keeps showing a ledger.
    source = app_js()
    for banned in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert banned not in source, banned


def test_the_feed_never_polls_or_refreshes_itself() -> None:
    # It loads when its route becomes current and when the frame is shown, and at no
    # other time. No polling, no timer, no interval, no visibility handler and no
    # reload when the window regains focus.
    source = app_js()
    for banned in ("setInterval", "setTimeout", "visibilitychange", "requestAnimationFrame"):
        assert banned not in source, banned
