"""Structural assertions over the expense entry screen in `app/`.

Task 10 of plans/backlog.md, sharpened in plans/tasks/10-expense-entry-screen.md.

Standard library only, and nothing here imports `splitwise_lite`: the shell is
independent of the domain layer, and a test that reached into the package would
quietly undo that. Paths are resolved from this file, never from the current working
directory.

**What this file may and may not claim.** Every assertion below is one of two kinds:
a fact about the committed markup, which a browser reads the same way this parser
does, or a *ban* on a token appearing in a source file, which the file itself
falsifies. Nothing here reads `app/app.js` and claims a rendering behaviour works:
PR #30 showed such a test passing two mutants that reintroduced the bug it claimed to
cover. What this screen renders is covered by real scenarios in
`tests/shell_harness.mjs`, which drive the shipped files, and by the hand checklist in
the task file.

The small HTML parser is re-declared here rather than imported from
`tests/test_feed_screen.py` or `tests/test_web_shell.py` on purpose: two branches are
editing those files, and a few dozen duplicated lines are cheaper than a shared edit
to either. This one builds a tree, because these criteria are about containment
("inside `#screen-add`", "inside `add-roster-error`").
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"

# Every id the add screen gains, each exactly once in the whole document and none
# beyond these. The list is exhaustive on purpose: a stray id is as much a merge
# hazard for the sibling branches as a missing one is a blank screen.
ADD_IDS = [
    "add-currency",
    "add-currency-code",
    "add-form",
    "add-amount",
    "add-description",
    "add-payer",
    "add-mode-equal",
    "add-mode-some",
    "add-mode-exact",
    "add-hint-some",
    "add-hint-exact",
    "add-people",
    "add-roster-busy",
    "add-roster-error",
    "add-roster-retry",
    "add-empty-roster",
    "add-submit",
    "add-status",
    "add-saving",
    "add-saved",
    "add-saved-amount",
    "add-saved-description",
    "add-error",
    "add-error-amount",
    "add-error-roster",
    "add-error-server",
]

# The ids the router and the two sibling screens already own inside this section.
INHERITED_IDS = ["screen-add", "title-add"]

# Everything that ships `hidden`, so the first paint shows one state at most.
HIDDEN_AT_REST = [
    "add-currency",
    "add-hint-some",
    "add-hint-exact",
    "add-roster-busy",
    "add-roster-error",
    "add-empty-roster",
    "add-saving",
    "add-saved",
    "add-error",
    "add-error-amount",
    "add-error-roster",
    "add-error-server",
]

# The three radios, and the one that ships chosen: equal across everyone is the
# default in the markup, so nothing has to load, resolve or be chosen for the common
# case to be correct.
MODE_IDS = ["add-mode-equal", "add-mode-some", "add-mode-exact"]
CHECKED_AT_REST = "add-mode-equal"

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

    def tagged(self, tag: str) -> list["Element"]:
        return [element for element in self.descendants() if element.tag == tag]

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
        return [element for element in self.root.descendants() if element.tag == tag]


def markup() -> str:
    return (APP / "index.html").read_text(encoding="utf-8")


def tree() -> Tree:
    return Tree(markup())


def add_screen(doc: Tree) -> Element:
    return doc.one("screen-add")


def paragraphs(element: Element) -> list[str]:
    return [child.text for child in element.children if child.tag == "p"]


def label_for(doc: Tree, target: str) -> Element:
    found = [
        element for element in doc.tagged("label") if element.attrs.get("for") == target
    ]
    assert len(found) == 1, f"{target} has {len(found)} labels bound by `for`"
    return found[0]


def app_js() -> str:
    return (APP / "app.js").read_text(encoding="utf-8")


# --- The document region ----------------------------------------------------


def test_the_section_holds_exactly_the_declared_ids_and_no_others() -> None:
    doc = tree()
    section = add_screen(doc)
    found = [
        element.attrs["id"]
        for element in [section, *section.descendants()]
        if element.attrs.get("id") is not None
    ]
    assert sorted(found) == sorted([*INHERITED_IDS, *ADD_IDS])


def test_each_new_id_appears_exactly_once_in_the_whole_document() -> None:
    doc = tree()
    for wanted in ADD_IDS:
        assert len(doc.by_id(wanted)) == 1, wanted


def test_every_new_id_and_class_in_the_section_is_namespaced() -> None:
    # Two sibling branches edit this file at the same time. Namespacing every new id
    # and class under `add-` is what stops the three sets of selectors colliding.
    inherited_classes = {"screen", "screen--add", "screen-title", "lede"}
    section = add_screen(tree())
    for element in [section, *section.descendants()]:
        found = element.attrs.get("id")
        if found is not None and found not in INHERITED_IDS:
            assert found.startswith("add-"), found
        for name in (element.attrs.get("class") or "").split():
            if name not in inherited_classes:
                assert name.startswith("add-"), name


def test_the_section_keeps_its_router_attributes_and_its_heading() -> None:
    doc = tree()
    section = add_screen(doc)
    assert section.tag == "section"
    assert section.attrs.get("aria-labelledby") == "title-add"
    assert "hidden" in section.attrs
    source = markup()
    assert '<h1 class="screen-title" id="title-add" tabindex="-1">Add</h1>' in source
    assert (
        '<p class="lede">Record a new expense and choose how it is shared.</p>'
        in source
    )


def test_the_placeholder_is_gone_from_the_document() -> None:
    source = markup()
    assert "Placeholder" not in source
    section = markup()[markup().index('id="screen-add"') :]
    section = section[: section.index("</section>")]
    assert 'class="marker"' not in section
    assert 'class="notes"' not in section
    assert 'class="card"' not in section


def test_every_state_element_ships_hidden() -> None:
    doc = tree()
    for wanted in HIDDEN_AT_REST:
        assert "hidden" in doc.one(wanted).attrs, wanted


def test_the_form_refuses_the_browsers_own_error_bubbles() -> None:
    # Every refusal this form can make is one the server owns, and a bubble in the
    # browser's own words is a second error contract that drifts from the first.
    form = tree().one("add-form")
    assert form.tag == "form"
    assert "novalidate" in form.attrs


def test_the_amount_field_is_text_with_a_decimal_keypad() -> None:
    # Never type="number": it hands back a value the browser has normalised and
    # localised and exposes valueAsNumber as a float, which is the string money
    # contract being broken by the platform.
    amount = tree().one("add-amount")
    assert amount.tag == "input"
    assert amount.attrs.get("type") == "text"
    assert amount.attrs.get("inputmode") == "decimal"
    assert amount.attrs.get("autocomplete") == "off"
    assert 'type="number"' not in markup()


def test_the_description_cannot_reach_the_stores_length_check() -> None:
    # store's CHECK is `length(description) <= 500`, so 409 constraint_violated is
    # unreachable from this screen.
    description = tree().one("add-description")
    assert description.tag == "input"
    assert description.attrs.get("type") == "text"
    assert description.attrs.get("maxlength") == "500"


def test_the_payer_picker_and_the_people_list_ship_empty() -> None:
    doc = tree()
    payer = doc.one("add-payer")
    assert payer.tag == "select"
    assert payer.children == []
    assert payer.text == ""
    people = doc.one("add-people")
    assert people.children == []
    assert people.text == ""


def test_the_three_modes_are_one_radio_group_defaulting_to_equally() -> None:
    doc = tree()
    names = set()
    for wanted in MODE_IDS:
        radio = doc.one(wanted)
        assert radio.tag == "input"
        assert radio.attrs.get("type") == "radio"
        names.add(radio.attrs.get("name"))
        assert ("checked" in radio.attrs) == (wanted == CHECKED_AT_REST), wanted
    assert len(names) == 1, names
    assert None not in names


def test_every_field_carries_a_label_and_the_modes_carry_a_legend() -> None:
    doc = tree()
    assert label_for(doc, "add-amount").text == "Amount"
    assert label_for(doc, "add-description").text == "Description (optional)"
    assert label_for(doc, "add-payer").text == "Paid by"
    for wanted, reads in zip(MODE_IDS, ["Equally", "Some people", "Uneven amounts"]):
        radio = doc.one(wanted)
        wrapping = radio.parent
        assert wrapping is not None and wrapping.tag == "label", wanted
        assert wrapping.text == reads, wanted
    fieldsets = add_screen(doc).tagged("fieldset")
    assert len(fieldsets) == 1
    legends = fieldsets[0].tagged("legend")
    assert [legend.text for legend in legends] == ["Split"]
    for wanted in MODE_IDS:
        assert fieldsets[0].contains(doc.one(wanted)), wanted


def test_the_two_controls_are_a_submit_and_a_plain_retry() -> None:
    doc = tree()
    submit = doc.one("add-submit")
    assert submit.tag == "button"
    assert submit.attrs.get("type") == "submit"
    assert submit.text == "Save"
    assert doc.one("add-form").contains(submit)
    retry = doc.one("add-roster-retry")
    assert retry.tag == "button"
    assert retry.attrs.get("type") == "button"
    assert retry.text == "Try again"
    assert doc.one("add-roster-error").contains(retry)


def test_the_two_live_regions_announce_and_hold_the_right_children() -> None:
    doc = tree()
    status = doc.one("add-status")
    assert status.attrs.get("role") == "status"
    for wanted in ("add-saving", "add-saved"):
        assert status.contains(doc.one(wanted)), wanted
    alert = doc.one("add-error")
    assert alert.attrs.get("role") == "alert"
    for wanted in ("add-error-amount", "add-error-roster", "add-error-server"):
        assert alert.contains(doc.one(wanted)), wanted


def test_the_confirmation_offers_one_plain_anchor_to_the_feed() -> None:
    doc = tree()
    saved = doc.one("add-saved")
    anchors = saved.tagged("a")
    assert len(anchors) == 1
    assert anchors[0].attrs.get("href") == "#/feed"
    assert anchors[0].text == "See it in the feed"
    assert "onclick" not in anchors[0].attrs


def test_the_committed_add_markup_invents_no_data() -> None:
    # On a money app a plausible fake amount is indistinguishable from a wrong real
    # one, and a placeholder of "0.00" on the amount field is the easiest way to ship
    # one. No skeleton and no spinner either.
    section = add_screen(tree())
    text = section.text
    for symbol in ("$", "£", "€", "%"):
        assert symbol not in text
    assert re.search(r"\d", text) is None
    for word in ("Loading", "loading", "skeleton", "spinner"):
        assert word not in text
    for element in [section, *section.descendants()]:
        assert "placeholder" not in element.attrs


# --- The copy, exactly ------------------------------------------------------


def test_the_currency_line_names_a_code_it_ships_without() -> None:
    doc = tree()
    line = doc.one("add-currency")
    code = doc.one("add-currency-code")
    assert line.contains(code)
    assert code.text == ""
    assert line.text == "Amounts are in ."


def test_the_two_hints_read_exactly_as_promised() -> None:
    doc = tree()
    assert (
        doc.one("add-hint-some").text
        == "Untick anyone who is not sharing this expense."
    )
    assert doc.one("add-hint-exact").text == (
        "These shares must add up to the total exactly. Leave someone blank to keep "
        "them off this expense."
    )


def test_the_three_roster_states_read_exactly_as_promised() -> None:
    doc = tree()
    assert doc.one("add-roster-busy").text == "Fetching the people in this group."
    assert paragraphs(doc.one("add-roster-error")) == [
        "The people in this group did not arrive. Nothing you have typed is lost."
    ]
    assert doc.one("add-empty-roster").text == (
        "This group has no members yet, so there is nothing to record."
    )


def test_the_screens_own_two_refusals_read_exactly_as_promised() -> None:
    doc = tree()
    assert doc.one("add-error-amount").text == "Type an amount before saving."
    assert doc.one("add-error-roster").text == (
        "The people in this group have not arrived yet, so this cannot be saved."
    )
    # The server's own words go here and nothing ships in it.
    assert doc.one("add-error-server").text == ""


def test_the_two_save_states_read_exactly_as_promised() -> None:
    doc = tree()
    assert doc.one("add-saving").text == "Saving this expense."
    amount = doc.one("add-saved-amount")
    described = doc.one("add-saved-description")
    assert amount.text == ""
    assert described.text == ""
    line = amount.parent
    assert line is not None
    assert line.contains(described)
    assert line.text == "Saved"


def test_no_copy_on_this_screen_says_anything_about_balances() -> None:
    # This screen records a spend. It works nothing out, so it claims nothing about
    # who owes who, and it never says a ledger is complete or current.
    text = add_screen(tree()).text.lower()
    for banned in (
        "settled",
        "balanced",
        "square",
        "owes",
        "owed",
        "debt",
        "up to date",
        "all clear",
    ):
        assert banned not in text, banned


# --- Token bans over app/app.js ---------------------------------------------


def test_the_screen_never_exposes_a_weight_split() -> None:
    # `split_by_weight` stays in the domain layer and stays reachable through the
    # API. A weight needs explaining before anyone can use one, and a weight typo
    # silently produces a wrong but valid split where a wrong exact share is refused
    # with both figures named.
    assert "weight" not in app_js()


def test_the_screen_never_reads_an_amount_as_anything_but_a_string() -> None:
    # `valueAsNumber` is the type="number" hole in property form. `selectedIndex` and
    # `defaultValue` are the two ways a control's state gets read out of the browser's
    # own bookkeeping instead of being set explicitly.
    source = app_js()
    for banned in ("valueAsNumber", "selectedIndex", "defaultValue"):
        assert banned not in source, banned


# --- The service worker -----------------------------------------------------


def test_the_worker_version_has_been_bumped_past_the_two_screens_it_missed() -> None:
    # At v2 a returning user is served the shell as it was two tasks ago: no feed
    # screen, no balances screen and no entry form, because the worker answers every
    # navigation from the cache and never revalidates. Pinned as a floor rather than
    # a value, so the next task's bump needs no edit here.
    source = (APP / "sw.js").read_text(encoding="utf-8")
    found = re.search(r"var VERSION = '([^']+)';", source)
    assert found is not None, "sw.js declares a VERSION"
    version = found.group(1)
    matched = re.fullmatch(r"v([0-9]+)", version)
    assert matched is not None, version
    assert int(matched.group(1)) >= 3, version


def test_the_worker_says_when_to_bump_it() -> None:
    header = (APP / "sw.js").read_text(encoding="utf-8").split("*/")[0]
    assert "SHELL" in header
    assert "revalidate" in header
