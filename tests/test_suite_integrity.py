"""The suite's check on itself.

Four failures in this repo reported success without exercising the thing they named,
and this module answers them with something that runs: GitHub issues #67, #65, #70
and #60.

The duplicate-definition check refuses a test module that binds one name twice at
module level, because Python rebinds silently and pytest then collects only the last
definition, so the earlier test is deleted with nothing anywhere reporting an error.
The anchored-pin check refuses a ``pytest.raises(match=)`` whose pattern is not
anchored with ``^`` and carries no ``# unanchored:`` reason, because ``match=`` is an
``re.search`` and an unanchored pattern can be satisfied by a superstring that somebody
else's guard raised. The unanchored-block check, GitHub issue #70, states the converse
for the commoner form: a ``pytest.raises`` block that reads the exception's message has
to carry an anchor somewhere, because ``"x" in str(exc.value)`` is the same operation
``match="x"`` performs and there were sixteen pins against a hundred-odd of those. It
carries the blocks that were already loose in a declared baseline that only shrinks, so
**it makes no existing assertion able to fail**; that is the audit, issue #70's slices
70b to 70h, and reading this module's green run as covering them is the misreading it is
written to prevent. A further failure, GitHub issue #58, gets the last refusal here and
is refused in the documents rather than in the code: no specification under ``plans/``,
and neither ``README.md`` nor ``CLAUDE.md``, may ask outside a blockquote for
``document.documentElement.scrollWidth`` against its ``clientWidth``, because ``body``
clips and ``.content`` scrolls in this shell, so that equality is constant and the four
task specs that asked for it as the test for horizontal overflow could not have failed.

Neither could be a rule. Nobody can follow a rule against a duplicate name, because the
whole difficulty is that neither author can see the other's definition; #67's own
"Related" section says so. And a rule about anchoring lasts exactly as long as the next
author who has not read it, which is the failure mode
``plans/tasks/46-shell-precache-digest.md`` records for ``VERSION``.

The third issue, #60, is answered by a format rather than by a check on behaviour:
``plans/mutations/`` holds mutation records an anchor and a replacement at a time, and
the last two checks here keep those records machine readable so the next person can
re-run one instead of reconstructing it from a sentence.

Standard library and pytest only, and nothing from ``splitwise_lite``, so these checks
still run on a checkout where the package will not import.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path
from typing import NamedTuple

import pytest

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
MUTATIONS = REPO / "plans" / "mutations"
RULES = REPO / ".claude" / "rules" / "testing.md"


def posix(path: Path) -> str:
    """``path`` relative to the repo root in POSIX form.

    So a message and a parameter id read the same on Windows and on Linux.
    """
    return path.relative_to(REPO).as_posix()


def read(path: Path) -> str:
    """The text of ``path``, decoded as UTF-8.

    ``read_text`` translates newlines, so a checkout with CRLF line endings yields the
    same string, the same line numbers and the same findings as one with LF. Both
    checks below read every file through here for that reason, and CI runs one leg
    under each convention.
    """
    return path.read_text(encoding="utf-8")


# Derived from the filesystem rather than written out, so a test module added later is
# covered without anybody remembering to add it to a list.
TEST_SOURCES = sorted(TESTS.rglob("*.py"))
SOURCE_IDS = [posix(path) for path in TEST_SOURCES]


def test_test_sources_is_every_test_module() -> None:
    """TEST_SOURCES is the filesystem's answer, not a list somebody maintains."""
    assert TEST_SOURCES, "TEST_SOURCES is empty, so both checks below check nothing."
    assert "tests/test_suite_integrity.py" in SOURCE_IDS, (
        "TEST_SOURCES does not contain this module, so the checks here do not run "
        "over themselves."
    )
    assert set(SOURCE_IDS) == {posix(path) for path in TESTS.rglob("*.py")}


def parsed(source: str, where: str) -> ast.Module:
    """``source`` as a module tree, or an assertion naming the file that will not parse.

    A test module that does not parse is this suite's failure to report, with the file
    named and the SyntaxError quoted, rather than a traceback out of ``ast.parse`` or a
    collection error somewhere else entirely.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        raise AssertionError(unparsable_message(where, exc)) from None


def unparsable_message(where: str, exc: SyntaxError) -> str:
    """What the checks say when a test module will not parse."""
    return (
        f"{where} does not parse as Python, so neither check in "
        "tests/test_suite_integrity.py can read it.\n"
        f"Python says: {exc.msg} (line {exc.lineno}).\n"
        "\n"
        "Fix the syntax error. Until it parses, this file could hide a duplicate "
        "definition or an unanchored pin and nothing here would see it."
    )


# --- The duplicate-definition check (#67) ----------------------------------
#
# There is no exemption mechanism here on purpose: no allowlist, no marker comment and
# no per-file escape. A duplicate module-level definition in a test file is always a
# bug, and an exemption is how a check stops being one. This is deliberately unlike the
# pin check below, which does take a marker, because a deliberate substring pin is a
# real thing and a deliberate duplicate definition is not.
#
# Fixtures, helpers and classes are covered as well as `test_*`. A shadowed fixture is
# the same failure with a wider blast radius, the same walk already sees it, and
# narrowing to `test_*` would be an extra condition that buys nothing.
#
# Cross-module duplicates are NOT checked. Two modules are separate namespaces, pytest
# reports them by path, and `tests/` is flat, so two modules cannot share a basename
# and cannot collide on import either.
#
# Module-level assignments are NOT checked. A rebound constant is visible where it is
# written and deletes no collected case; a rebound `def` does. Including assignments
# would add false positives for a failure of a different kind.
#
# Read that narrowly: it is a claim about assignment over assignment, not about the
# whole category. One case IS uncovered and is knowingly left so. An assignment or an
# import that lands on a name a `def` in the same module body already bound does delete
# a collected test — `def test_a` then `test_a = None`, or `def helper` then
# `from os.path import join as helper` — and neither is flagged here, because neither
# is a FunctionDef, AsyncFunctionDef or ClassDef. Nothing in `tests/` looks like that
# today. If it is ever worth closing, the cheap form is to flag only a binding that
# collides with a `def` already made in the same module body, which has almost none of
# the false-positive surface that checking assignments at large would.


def module_definitions(source: str, where: str) -> list[tuple[str, int]]:
    """Every name bound by a direct child of the module body, with its line number.

    Direct child is the whole of it: a definition nested inside a function, a class
    body, an ``if``, a ``try`` or a ``with`` does not rebind a module-level name and is
    not returned.
    """
    tree = parsed(source, where)
    definitions: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions.append((node.name, node.lineno))
    return definitions


def duplicate_definitions(source: str, where: str) -> list[tuple[str, list[int]]]:
    """One finding per name the module body binds more than once.

    A name bound three times is one finding carrying three line numbers, not two
    findings. Findings are ordered by the line that first binds the name.
    """
    lines_by_name: dict[str, list[int]] = {}
    for name, lineno in module_definitions(source, where):
        lines_by_name.setdefault(name, []).append(lineno)
    findings = [
        (name, linenos) for name, linenos in lines_by_name.items() if len(linenos) > 1
    ]
    findings.sort(key=lambda finding: finding[1][0])
    return findings


def duplicate_definition_message(where: str, name: str, lines: list[int]) -> str:
    """What the check says when one module binds a name twice."""
    spelled = ", ".join(str(line) for line in lines)
    return (
        f"{where} defines {name} more than once, at lines {spelled}.\n"
        "\n"
        "Python rebinds a module-level name silently, so only the last definition is "
        "collected, and the earlier one is indistinguishable from a test that was "
        "never written. If the earlier one was parametrised, its cases are gone and "
        "nothing anywhere reports an error.\n"
        "\n"
        "This has happened twice in this repo in one day, once deleting four "
        "parametrised cases on PR #64 with the suite still green.\n"
        "\n"
        f"The fix is to rename one of them to what it actually tests. Never delete "
        f"either {name} before checking they are not two different tests."
    )


@pytest.mark.parametrize("path", TEST_SOURCES, ids=SOURCE_IDS)
def test_no_test_module_defines_a_name_twice(path: Path) -> None:
    """No test module loses a definition to a later one with the same name."""
    where = posix(path)
    findings = duplicate_definitions(read(path), where)
    assert not findings, "\n\n".join(
        duplicate_definition_message(where, name, lines) for name, lines in findings
    )


DUPLICATE_TEST = """\
def test_x() -> None:
    assert True


def test_x() -> None:
    assert True
"""

DUPLICATE_FIXTURE = """\
import pytest


@pytest.fixture
def store():
    return 1


@pytest.fixture
def store():
    return 2
"""

NESTED_ONLY = """\
class First:
    def helper(self):
        return 1


class Second:
    def helper(self):
        return 2


def outer():
    def helper():
        return 3

    return helper


if True:
    def helper():
        return 4


def helper():
    return 5
"""

ASYNC_AND_CLASS = """\
async def test_x() -> None:
    assert True


async def test_x() -> None:
    assert True


class Thing:
    pass


class Thing:
    pass
"""

THREE_BINDINGS = """\
def shadowed() -> None:
    pass


def shadowed() -> None:
    pass


def shadowed() -> None:
    pass
"""


def test_the_duplicate_check_catches_a_duplicate_test() -> None:
    findings = duplicate_definitions(DUPLICATE_TEST, "<synthetic>")
    assert len(findings) == 1
    name, lines = findings[0]
    assert name == "test_x"
    assert lines == [1, 5]
    # The line numbers are where the synthetic source really puts them.
    numbered = DUPLICATE_TEST.split("\n")
    assert numbered[0].startswith("def test_x")
    assert numbered[4].startswith("def test_x")


def test_the_duplicate_check_catches_a_duplicate_fixture() -> None:
    """Not restricted to `test_*`: a shadowed fixture is the same failure."""
    findings = duplicate_definitions(DUPLICATE_FIXTURE, "<synthetic>")
    assert len(findings) == 1
    name, lines = findings[0]
    assert name == "store"
    assert lines == [5, 10]


def test_the_duplicate_check_leaves_a_nested_definition_alone() -> None:
    """The criterion that stops the check flagging ordinary code.

    Two classes with a method of the same name, an inner def, and a def inside an if
    beside a module-level def of that name: none of those rebinds a module-level name
    twice, so none of them is a finding.
    """
    assert duplicate_definitions(NESTED_ONLY, "<synthetic>") == []


def test_the_duplicate_check_reports_three_bindings_as_one_finding() -> None:
    """A name bound three times is one finding carrying three line numbers.

    Not two findings, and not one finding naming only the first collision. The message
    helper is fed three line numbers by its own test; this pins that the walk really
    produces three, which nothing else asserted.
    """
    findings = duplicate_definitions(THREE_BINDINGS, "<synthetic>")
    assert len(findings) == 1
    name, lines = findings[0]
    assert name == "shadowed"
    assert lines == [1, 5, 9]


def test_the_duplicate_check_looks_at_one_module_at_a_time() -> None:
    """Cross-module duplicates are out, pinned as behaviour rather than as a comment."""
    assert duplicate_definitions(DUPLICATE_TEST.split("\n\n\n")[0], "<one>") == []
    assert duplicate_definitions(DUPLICATE_TEST.split("\n\n\n")[1], "<two>") == []


def test_the_duplicate_check_reads_async_and_class_definitions() -> None:
    findings = duplicate_definitions(ASYNC_AND_CLASS, "<synthetic>")
    assert len(findings) == 2
    assert [name for name, _ in findings] == ["test_x", "Thing"]


def test_a_module_that_will_not_parse_names_the_file_and_quotes_the_error() -> None:
    """A file that will not parse is a failure naming it, not a raw SyntaxError."""
    with pytest.raises(AssertionError) as raised:
        duplicate_definitions("def broken(:\n    pass\n", "tests/test_pretend.py")
    message = str(raised.value)
    assert "tests/test_pretend.py" in message
    assert "does not parse as Python" in message


def test_the_duplicate_definition_message_says_what_happened() -> None:
    """Every element the message has to carry, fed a synthetic name and three lines."""
    message = duplicate_definition_message("tests/test_pretend.py", "test_thing", [4, 9, 15])
    assert "tests/test_pretend.py" in message
    assert "test_thing" in message
    for line in ("4", "9", "15"):
        assert line in message
    assert "rebinds a module-level name silently" in message
    assert "only the last definition is collected" in message
    assert "indistinguishable from a test that was never written" in message
    assert "parametrised, its cases are gone" in message
    assert "nothing anywhere reports an error" in message
    assert "twice in this repo in one day" in message
    assert "four parametrised cases on PR #64" in message
    assert "rename one of them to what it actually tests" in message
    assert "before checking they are not two different tests" in message


# --- The anchored-pin check (#65) ------------------------------------------

MARKER = re.compile(r"#\s*unanchored:\s*(.+)")
# A reason has to be long enough to be a reason. The same shape as NOT_PRECACHED and
# test_an_omission_with_no_reason_is_refused in tests/test_web_shell.py: a deliberate
# omission stays legal and becomes visible, and an accidental one goes red.
MINIMUM_REASON = 20


def callee_name(node: ast.Call) -> str | None:
    """The bare name of whatever is being called, attribute or plain name."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def message_pins(source: str, where: str) -> list[tuple[int, int, str | None]]:
    """Every ``match=`` belonging to a ``raises`` or ``warns`` call.

    Returns the call's first and last line numbers and, when the value is a plain
    ``str`` constant, its pattern; ``None`` when the pattern is anything else.

    The callee decides candidacy before any keyword is read, so ``re.match(...)`` is
    never a candidate in the first place rather than being excluded by a later test,
    and an assignment to a variable named ``match`` is not a keyword argument at all.

    What that also excludes, so the next author does not read this as broader than it
    is: ``excinfo.match(...)``, pytest's other pin idiom with identical ``re.search``
    semantics, gets no check at all; nor does ``raises`` aliased to another name at
    import, nor a ``match`` passed through ``**kwargs``, where the keyword's ``arg`` is
    ``None``. All three have zero occurrences in ``tests/`` today. Matching on the bare
    attribute name also means an unrelated ``foo.raises(X, match="y")`` would be treated
    as a pin, which criterion 18 asks for, since the check must accept both
    ``pytest.raises(...)`` and a bare ``raises(...)``; it errs toward flagging, which is
    the safe direction.
    """
    tree = parsed(source, where)
    pins: list[tuple[int, int, str | None]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if callee_name(node) not in ("raises", "warns"):
            continue
        for keyword in node.keywords:
            if keyword.arg != "match":
                continue
            value = keyword.value
            pattern = (
                value.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
                else None
            )
            pins.append((node.lineno, node.end_lineno or node.lineno, pattern))
    pins.sort()
    return pins


def marked_lines(source: str, where: str) -> set[int]:
    """Physical lines carrying an ``# unanchored:`` comment with a real reason.

    Comments are found with ``tokenize`` because the AST does not hold them, and a
    ``#`` inside a string literal is a STRING token rather than a COMMENT one, so it
    cannot mark anything by accident.
    """
    text = source if source.endswith("\n") else source + "\n"
    marked: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type != tokenize.COMMENT:
                continue
            found = MARKER.search(token.string)
            if found is not None and len(found.group(1).strip()) >= MINIMUM_REASON:
                marked.add(token.start[0])
    except tokenize.TokenError:
        # parsed() has already reported anything that will not tokenize cleanly.
        pass
    return marked


def unanchored_pins(source: str, where: str) -> list[tuple[int, int, str | None]]:
    """The pins that are neither anchored nor marked.

    Anchored means the pattern is a ``str`` constant whose first character is ``^``.
    Marked means some physical line of the call carries ``# unanchored:`` with a reason
    of at least MINIMUM_REASON characters.
    """
    marked = marked_lines(source, where)
    offending: list[tuple[int, int, str | None]] = []
    for lineno, end_lineno, pattern in message_pins(source, where):
        if pattern is not None and pattern.startswith("^"):
            continue
        if any(line in marked for line in range(lineno, end_lineno + 1)):
            continue
        offending.append((lineno, end_lineno, pattern))
    return offending


def unanchored_pin_message(where: str, line: int, pattern: str | None) -> str:
    """What the check says about one pin that pins less than it looks like it does."""
    if pattern is None:
        opening = (
            f"{where}:{line} pins an exception message with a match= whose pattern is "
            "not a string literal, so this check cannot read it. The pattern has to be "
            "a literal for this check to read it, or the call has to carry the marker "
            "described below."
        )
    else:
        opening = (
            f"{where}:{line} pins an exception message with match={pattern!r}, which "
            "does not start with '^'."
        )
    return (
        opening + "\n"
        "\n"
        "match= is an re.search, not a full match, so a pattern that matches a "
        "superstring pins nothing. Measured on 7bf518c (2026-09-07), money.py:148 said "
        "'Money currency must be a Currency, ...', which contained "
        "'currency must be a Currency' from index 6, so on PR #62 both the broken "
        "test and its first proposed repair passed with the guard deleted. That "
        "wording is quoted as it was on that date and is not re-read from source "
        "here; if it has changed, the collision is a different one and this rule is "
        "unchanged.\n"
        "\n"
        "The fix is a leading ^ plus enough of the message that no other exception "
        "the same call can raise would match it.\n"
        "\n"
        "If the substring is deliberate, say so: put "
        "'# unanchored: <why>' on the pytest.raises call, with a reason of at least "
        f"{MINIMUM_REASON} characters."
    )


@pytest.mark.parametrize("path", TEST_SOURCES, ids=SOURCE_IDS)
def test_every_message_pin_is_anchored_or_says_why(path: Path) -> None:
    """No pin in the suite can be satisfied by somebody else's exception unnoticed."""
    where = posix(path)
    offending = unanchored_pins(read(path), where)
    assert not offending, "\n\n".join(
        unanchored_pin_message(where, line, pattern)
        for line, _end, pattern in offending
    )


# Every spelling the check must catch and every near miss it must not, in the shape of
# test_the_narrowed_status_rule_still_bites in tests/test_shell_behaviour.py. A green
# run of a check means nothing on its own; what makes it worth having is proof that it
# still matches the shapes it claims to.
FLAGGED_PLAIN = 'with pytest.raises(TypeError, match="currency must be a Currency"):\n    pass\n'
ACCEPTED_ANCHORED = (
    'with pytest.raises(TypeError, match=r"^currency must be a Currency"):\n    pass\n'
)
ACCEPTED_MARKED = (
    'with pytest.raises(TypeError, match="the id"):  '
    "# unanchored: the id is all this refuses to name\n    pass\n"
)
FLAGGED_EMPTY_MARKER = (
    'with pytest.raises(TypeError, match="the id"):  # unanchored:\n    pass\n'
)
FLAGGED_SHORT_MARKER = (
    'with pytest.raises(TypeError, match="the id"):  # unanchored: too short\n    pass\n'
)
ACCEPTED_MARKER_ON_LAST_LINE = (
    "with pytest.raises(\n"
    "    TypeError,\n"
    '    match="the id",\n'
    "):  # unanchored: the id is all this refuses to name\n"
    "    pass\n"
)
FLAGGED_NAME_PATTERN = "with pytest.raises(TypeError, match=PATTERN):\n    pass\n"
# Both of these are real lines in tests/test_web_shell.py today, at 1325 and 1352.
NOT_A_PIN_RE_MATCH = 'if re.match(r"#{1,6} ", line):\n    pass\n'
NOT_A_PIN_ASSIGNED = 'match = re.match(r"\\*\\*(.+?)\\*\\*", bullet)\n'
# Not required by the criteria, but it is the case that fails if the callee filter in
# message_pins is ever removed or reordered: a match= keyword on a call that is not
# raises or warns. Without this, every near miss above would pass by construction.
NOT_A_PIN_OTHER_CALL = 'record = dict(match="not a pin at all")\n'
NO_MATCH_AT_ALL = "with pytest.raises(TypeError):\n    pass\n"


def test_the_pin_check_still_bites() -> None:
    """Proof that the check refuses what it must and accepts what it must not refuse."""
    # a. A plain substring pin is flagged.
    assert len(unanchored_pins(FLAGGED_PLAIN, "<a>")) == 1
    # b. A leading ^ is accepted.
    assert unanchored_pins(ACCEPTED_ANCHORED, "<b>") == []
    # c. A marker with a reason over MINIMUM_REASON characters is accepted.
    assert unanchored_pins(ACCEPTED_MARKED, "<c>") == []
    # d. A marker with nothing after it, or too short a reason, is not a reason.
    assert len(unanchored_pins(FLAGGED_EMPTY_MARKER, "<d1>")) == 1
    assert len(unanchored_pins(FLAGGED_SHORT_MARKER, "<d2>")) == 1
    # e. The marker may sit on the last line of a call wrapped over several lines.
    assert unanchored_pins(ACCEPTED_MARKER_ON_LAST_LINE, "<e>") == []
    # f. A pattern that is a name rather than a literal is flagged.
    flagged = unanchored_pins(FLAGGED_NAME_PATTERN, "<f>")
    assert len(flagged) == 1
    assert flagged[0][2] is None
    # g. re.match is not a pin, in either of the two shapes test_web_shell.py holds.
    #
    # These two hold by construction and cannot fail under any mutation of this AST
    # implementation: re.match passes its pattern positionally, so there is no match=
    # keyword to find, and `match = re.match(...)` is an assignment rather than a
    # keyword argument. They guard against a future rewrite that scans text or regexes
    # instead of the tree, not against this one. The assertion that keeps this section
    # from being vacuous today is the dict(match=...) one below, which is the only case
    # here that goes red if the callee filter is dropped or reordered.
    assert message_pins(NOT_A_PIN_RE_MATCH, "<g1>") == []
    assert message_pins(NOT_A_PIN_ASSIGNED, "<g2>") == []
    assert unanchored_pins(NOT_A_PIN_RE_MATCH, "<g1>") == []
    assert unanchored_pins(NOT_A_PIN_ASSIGNED, "<g2>") == []
    # And a match= on a call that is neither raises nor warns is not a pin either,
    # which is what keeps the three cases above from holding for the wrong reason.
    assert message_pins(NOT_A_PIN_OTHER_CALL, "<g3>") == []
    # h. A bare raises with no match= at all is not a pin.
    assert message_pins(NO_MATCH_AT_ALL, "<h>") == []
    assert unanchored_pins(NO_MATCH_AT_ALL, "<h>") == []
    # And pytest.warns is read the same way pytest.raises is.
    assert len(unanchored_pins('with pytest.warns(UserWarning, match="x"):\n    pass\n', "<w>")) == 1


def test_a_pin_whose_pattern_is_not_a_literal_is_flagged() -> None:
    """A variable, an f-string or a concatenation cannot be read, so it is flagged."""
    for source in (
        "with pytest.raises(TypeError, match=PATTERN):\n    pass\n",
        'with pytest.raises(TypeError, match=f"^{prefix} must be"):\n    pass\n',
        'with pytest.raises(TypeError, match="^a" + "b"):\n    pass\n',
    ):
        found = unanchored_pins(source, "<synthetic>")
        assert len(found) == 1, source
        assert found[0][2] is None, source


def test_the_unanchored_pin_message_says_what_happened() -> None:
    """Every element the message has to carry."""
    message = unanchored_pin_message("tests/test_pretend.py", 12, "currency must be a Currency")
    assert "tests/test_pretend.py" in message
    assert "12" in message
    assert "currency must be a Currency" in message
    assert "re.search" in message
    assert "not a full match" in message
    assert "superstring" in message
    assert "Money currency must be a Currency" in message
    assert "from index 6" in message
    assert "PR #62" in message
    assert "first proposed repair passed with the guard deleted" in message
    assert "leading ^" in message
    assert "no other exception the same call can raise would match it" in message
    assert "# unanchored:" in message
    # And the non-literal case carries its own explanation instead of a pattern.
    other = unanchored_pin_message("tests/test_pretend.py", 12, None)
    assert "not a string literal" in other
    assert "has to be a literal for this check to read it" in other


# --- The unanchored-block check (#70) --------------------------------------
#
# The guarantee here is one sentence and it is the converse of the one above: a
# `match=` (or an equivalent whole-message comparison) EXISTS wherever a block reads
# the exception's message. `test_every_message_pin_is_anchored_or_says_why` owns the
# other half, that any `match=` which exists is anchored. Neither check restates the
# other's guarantee, and neither re-decides the other's question: nothing here reads a
# pattern for a leading `^`.
#
# What this check does NOT do, stated where a reader will hit it before drawing the
# wrong conclusion from a green run: it makes no existing assertion able to fail. Every
# block carried in CARRIED_UNANCHORED_BLOCKS below is exactly as loose after this check
# as before it. Making them able to fail is the audit, issue #70's slices 70b to 70h,
# one deleted guard at a time. This is the mechanism only.

# The unit is the block, not the assertion, and the reason is measurable. A block
# routinely asserts several fragments about one message — tests/test_store.py:2983 and
# :2984 assert "u1" and "u2" — and at most one fragment can be at the start of a
# message, so "put ^ on each" is unsatisfiable. Once one anchor in a block has
# established which guard raised, every fragment assertion beside it stops being a pin
# and becomes documentation.
#
# WHAT A BLOCK IS HERE, and this is a correction to the wording of criterion 5 of
# plans/tasks/70-substring-assertions-on-exception-messages.md, recorded rather than
# quietly applied. That criterion says the candidate is a `with` "whose body reads that
# name's message". Measured on this branch 2026-09-08 over tests/*.py: of the 132
# `str(NAME.value)` calls in the suite, **zero** are inside the `with` body and 132 are
# after it. They cannot be inside: pytest populates `excinfo.value` in `__exit__`, and
# the body has already been left by the exception in any case. Read literally, that
# criterion finds nothing anywhere, CARRIED_TOTAL is 0, and this becomes a fourth check
# that cannot fail — the exact defect this module exists to refuse. So the block is the
# `with` statement TOGETHER WITH the statements that follow it in the same suite, up to
# the next `raises`-binding `with` in that suite or the end of the suite: the region in
# which that block's bound name is the live one. Criterion 15 already assumes this
# reading, because it asks the baseline to notice "one of two blocks in a function"
# being anchored, which only has a referent when a function's statements are divided
# between its blocks.
#
# Shapes deliberately NOT seen, with the count each has on this branch, in the manner
# message_pins' docstring lists its exclusions. Measured 2026-09-08 over tests/*.py:
#   NAME.value.args                     0 occurrences
#   repr(NAME.value)                    0 occurrences
#   an f-string holding {NAME.value}    0 occurrences
#   an annotated assignment `m: str = str(NAME.value)`   0 occurrences
#   a walrus `(m := str(NAME.value))`   0 occurrences
#   pytest.warns(...) as NAME           0 occurrences
# A future occurrence of any of them is invisible to this check: the block would not be
# a candidate at all, so it would be neither flagged nor carried, and nothing anywhere
# would report it. Two levels of local binding are also not followed, and a binding made
# outside the block is not followed across the function boundary.


class MessageBlock(NamedTuple):
    """One ``pytest.raises`` block that reads the exception's message.

    ``lineno`` and ``end_lineno`` are the block's first and last physical lines, the
    last being the end of the region described above rather than the end of the ``with``
    suite. ``header_end`` is the last line of the ``with`` header, which is where the
    marker is looked for. ``enclosing`` is the innermost definition's name, or
    ``"<module>"``, taken the way ``four_hundred_raise_sites`` takes it.
    """

    lineno: int
    end_lineno: int
    header_end: int
    name: str
    enclosing: str
    anchored: bool


def message_call(node: ast.AST, name: str) -> bool:
    """``node`` is a call to ``str`` whose single argument is ``NAME.value``."""
    return (
        isinstance(node, ast.Call)
        and callee_name(node) == "str"
        and not node.keywords
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Attribute)
        and node.args[0].attr == "value"
        and isinstance(node.args[0].value, ast.Name)
        and node.args[0].value.id == name
    )


def message_locals(region: list[ast.stmt], name: str) -> set[str]:
    """Names an assignment in this block binds to ``str(NAME.value)``.

    One level of binding. A local bound to another local is not followed, and neither is
    a binding made outside the block, so nothing here crosses a function boundary.
    """
    bound: set[str] = set()
    for statement in region:
        for node in ast.walk(statement):
            if isinstance(node, ast.Assign) and message_call(node.value, name):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bound.add(target.id)
    return bound


def is_message(node: ast.AST, name: str, bound: set[str]) -> bool:
    """``node`` is the exception's message, in either of the two shapes seen."""
    if message_call(node, name):
        return True
    return (
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in bound
    )


def region_reads_message(region: list[ast.stmt], name: str) -> bool:
    """The block reads the message, which is what makes it a candidate at all."""
    bound = message_locals(region, name)
    return any(
        is_message(node, name, bound)
        for statement in region
        for node in ast.walk(statement)
    )


def region_is_anchored(call: ast.Call, region: list[ast.stmt], name: str) -> bool:
    """Whether anything in the block establishes which guard raised.

    Three of the four accepted anchors; the fourth, the ``# unanchored:`` marker, is a
    comment and is applied by ``unanchored_message_blocks``. The ``match=`` keyword is
    read off the ``raises`` call itself and never off some other call in the block, for
    the same reason ``NOT_A_PIN_OTHER_CALL`` exists. Whether that pattern starts with
    ``^`` is not re-decided here: the sibling check owns that guarantee.
    """
    if any(keyword.arg == "match" for keyword in call.keywords):
        return True
    bound = message_locals(region, name)
    for statement in region:
        for node in ast.walk(statement):
            if isinstance(node, ast.Compare) and any(
                isinstance(op, ast.Eq) for op in node.ops
            ):
                if is_message(node.left, name, bound) or any(
                    is_message(other, name, bound) for other in node.comparators
                ):
                    return True
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "startswith"
                and is_message(node.func.value, name, bound)
            ):
                return True
    return False


def raises_bindings(
    statements: list[ast.stmt],
) -> list[tuple[int, ast.With | ast.AsyncWith, ast.Call, ast.Name]]:
    """Every ``with ... raises(...) as NAME:`` directly in one suite, in order."""
    found: list[tuple[int, ast.With | ast.AsyncWith, ast.Call, ast.Name]] = []
    for index, statement in enumerate(statements):
        if not isinstance(statement, (ast.With, ast.AsyncWith)):
            continue
        for item in statement.items:
            call, bound = item.context_expr, item.optional_vars
            if (
                isinstance(call, ast.Call)
                and callee_name(call) == "raises"
                and isinstance(bound, ast.Name)
            ):
                found.append((index, statement, call, bound))
                break
    return found


def message_blocks(source: str, where: str) -> list[MessageBlock]:
    """One entry per candidate block in ``source``, ordered by line."""
    tree = parsed(source, where)
    found: list[MessageBlock] = []
    stack: list[str] = []

    def read_suite(statements: list[ast.stmt]) -> None:
        starts = raises_bindings(statements)
        for order, (index, statement, call, bound) in enumerate(starts):
            end = starts[order + 1][0] if order + 1 < len(starts) else len(statements)
            region = statements[index:end]
            if not region_reads_message(region, bound.id):
                continue
            found.append(
                MessageBlock(
                    statement.lineno,
                    max(node.end_lineno or node.lineno for node in region),
                    max(
                        call.end_lineno or call.lineno,
                        bound.end_lineno or bound.lineno,
                    ),
                    bound.id,
                    stack[-1] if stack else "<module>",
                    region_is_anchored(call, region, bound.id),
                )
            )

    def walk(node: ast.AST) -> None:
        named = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        if named:
            stack.append(node.name)  # type: ignore[attr-defined]
        for field in ("body", "orelse", "finalbody"):
            suite = getattr(node, field, None)
            if isinstance(suite, list) and suite and isinstance(suite[0], ast.stmt):
                read_suite(suite)
        for child in ast.iter_child_nodes(node):
            walk(child)
        if named:
            stack.pop()

    walk(tree)
    found.sort()
    return found


def unanchored_message_blocks(source: str, where: str) -> list[MessageBlock]:
    """The candidate blocks that are neither anchored nor marked."""
    marked = marked_lines(source, where)
    return [
        block
        for block in message_blocks(source, where)
        if not block.anchored
        and not any(
            line in marked for line in range(block.lineno, block.header_end + 1)
        )
    ]


def unanchored_block_message(where: str, line: int, name: str) -> str:
    """What the check says about one block that pins nothing."""
    return (
        f"{where}:{line} opens a pytest.raises block that reads {name}.value's "
        "message, and nothing in the block establishes which guard raised it.\n"
        "\n"
        f'\'"x" in str({name}.value)\' is the same operation match="x" performs. For a '
        "pattern with no metacharacters an re.search is a substring test, so the PR #62 "
        "collision applies to it unchanged: the assertion passes for any message "
        "holding that fragment, including one somebody else's guard raised.\n"
        "\n"
        "The fix goes on the block, not on each assertion. A block routinely asserts "
        "several fragments about one message and at most one can start the message, so "
        "there is no per-assertion form of it. Once one anchor has established which "
        "guard raised, every fragment assertion beside it stops being a pin and becomes "
        "documentation, and none of them has to change.\n"
        "\n"
        "A negative assertion is weaker still rather than safer: any message lacking "
        "the string satisfies it, including one from an entirely different guard.\n"
        "\n"
        "Any one of these anchors the block, and they are the whole accepted set:\n"
        "\n"
        '    match=r"^..." on the pytest.raises call\n'
        f'    assert str({name}.value) == "..."\n'
        f'    assert str({name}.value).startswith("...")\n'
        "    # unanchored: <why> on the with statement, with a reason of at least "
        f"{MINIMUM_REASON} characters\n"
        "\n"
        "Whether a match= pattern really starts with ^ is not decided here. "
        "test_every_message_pin_is_anchored_or_says_why already guarantees that, and "
        "these two checks state one guarantee each."
    )


# The blocks that were already unanchored when this check landed, carried so that the
# check can refuse everything new without either fixing a hundred assertions in one
# unauditable merge or converting them unaudited, which is the worse defect.
#
# This is not an allowlist, and it is not the equal of the `# unanchored:` hatch either.
# Four properties separate it from an allowlist, and all four are checked below: it is
# checked in BOTH directions, so a carried entry that is no longer unanchored is a
# failure naming it and the baseline cannot outlive its subject; its entries carry
# counts, not just names, so anchoring one of two blocks in a function moves a number;
# its total is a single declared integer, so growing it is a one-line diff a reviewer
# cannot miss; and each entry names the audit slice that will retire it, under the same
# floor MINIMUM_REASON puts under the marker.
#
# Stated exactly and not claimed as more: a determined author can still legalise a new
# unanchored block by editing three places, and that costs a placement plus a bump to a
# visible integer, not a written justification per block. That is weaker than
# `# unanchored:` demands, which enforces twenty characters of reason, and stronger than
# a bare allowlist. It is temporary by construction, because the last audit slice
# deletes this constant, CARRIED_TOTAL, and the carried direction of the check.
#
# Never keyed by a line number and never by an ordinal. Line numbers churn on every edit
# above them, which would make this a merge-conflict generator, and an ordinal is bound
# to its subject only by position in a list, which is the defect that put a correct
# number against the wrong mutation in this repo. A name and a count is bound to
# neither.
CARRIED_UNANCHORED_BLOCKS: dict[str, tuple[frozenset[tuple[str, int]], str]] = {
    "tests/test_accounts.py": (
        frozenset(
            {
                ("test_every_login_failure_is_the_same_type_with_the_same_message", 1),
            }
        ),
        "no row of the 70b to 70h slice table covers this module; 70h, last, takes it",
    ),
    "tests/test_balances.py": (
        frozenset(
            {
                ("test_a_foreign_currency_raises_currency_mismatch_for_a_walk_too", 1),
                ("test_a_foreign_currency_raises_currency_mismatch_naming_both_codes", 1),
                ("test_a_foreign_group_is_refused_on_the_same_terms_as_the_fold", 1),
                ("test_a_foreign_group_names_the_event_and_both_groups", 1),
                ("test_a_member_cannot_owe_themselves", 1),
                ("test_a_member_id_that_is_not_a_str_raises_type_error_naming_the_type", 1),
                ("test_a_repeated_event_id_is_refused_for_a_walk_too", 1),
            }
        ),
        "slice 70c retires this module, one deleted guard in balances.py at a time",
    ),
    "tests/test_groups.py": (
        frozenset(
            {
                ("test_a_definition_cannot_carry_an_address", 1),
                ("test_a_different_currency_is_refused_naming_both_codes", 1),
                ("test_a_different_group_name_is_refused_naming_both", 1),
                ("test_a_directory_is_named_rather_than_raising_an_os_error", 1),
                ("test_a_file_that_is_not_utf_8_is_named_rather_than_raising_a_decode_error", 1),
                ("test_a_group_name_that_is_not_a_string_is_refused", 1),
                ("test_a_lowercase_currency_is_refused_and_the_message_names_the_fix", 1),
                ("test_a_member_of_another_group_is_refused_naming_both_groups", 1),
                ("test_a_member_pointing_at_another_user_is_refused_and_left_alone", 1),
                ("test_a_missing_key_is_named", 1),
                ("test_a_path_that_does_not_exist_is_named", 1),
                ("test_a_user_another_member_of_that_group_holds_is_refused", 1),
                ("test_an_omitted_name_is_refused_and_writes_nothing", 1),
                ("test_an_unknown_key_is_named_rather_than_ignored", 1),
                ("test_an_unknown_member_id_or_user_id_is_named", 2),
                ("test_an_unlinked_user_and_an_unknown_group_are_told_apart_by_type", 1),
                ("test_apply_with_an_unknown_group_id_raises_record_not_found", 1),
                ("test_apply_with_two_groups_and_no_id_raises_ambiguous", 1),
                ("test_malformed_toml_carries_the_decode_error_as_its_cause", 1),
                ("test_max_members_is_fifty_and_is_enforced", 1),
                ("test_members_must_be_an_array_of_strings", 1),
                ("test_resolve_on_an_empty_store_names_the_setup_command", 1),
                ("test_resolve_with_two_groups_names_every_id", 1),
                ("test_two_names_that_casefold_equal_are_refused_and_the_message_says_what_to_do", 1),
                ("test_two_names_that_differ_only_by_unicode_normalisation_are_refused", 1),
                ("test_two_stored_members_of_one_name_refuse_a_reconcile", 1),
            }
        ),
        "slice 70e retires this module, one deleted guard in groups.py at a time",
    ),
    "tests/test_money.py": (
        frozenset(
            {
                ("test_currency_rejects_lowercase_rather_than_coercing", 1),
                ("test_parse_amount_error_message_carries_the_offending_input", 1),
            }
        ),
        "slice 70b retires this module, one deleted guard in money.py at a time",
    ),
    "tests/test_simplify.py": (
        frozenset(
            {
                ("test_a_member_in_pairwise_but_absent_from_net_still_has_to_agree", 1),
                ("test_a_member_owing_themselves_is_refused", 1),
                ("test_a_money_in_another_currency_raises_currency_mismatch", 1),
                ("test_a_net_that_does_not_sum_to_zero_is_refused_by_its_residue", 1),
                ("test_a_pair_stored_in_both_directions_is_refused_naming_both", 1),
                ("test_a_pairwise_debt_that_is_not_strictly_positive_is_refused", 1),
                ("test_anything_that_is_not_a_balances_is_a_type_error", 1),
                ("test_net_and_pairwise_disagreeing_is_refused_naming_both_figures", 1),
            }
        ),
        "slice 70b retires this module, one deleted guard in simplify.py at a time",
    ),
    "tests/test_split.py": (
        frozenset(
            {
                ("test_split_exact_rejects_amounts_that_fall_short", 1),
                ("test_split_exact_rejects_amounts_that_overshoot", 1),
            }
        ),
        "slice 70b retires this module, one deleted guard in split.py at a time",
    ),
    "tests/test_store.py": (
        frozenset(
            {
                ("test_a_duplicate_decision_leaves_the_stored_row_untouched", 1),
                ("test_a_duplicate_email_is_rejected", 1),
                ("test_a_duplicate_expense_id_leaves_the_stored_row_untouched", 1),
                ("test_a_duplicate_settlement_id_leaves_the_stored_row_untouched", 1),
                ("test_a_duplicate_token_hash_is_rejected_and_overwrites_nothing", 1),
                ("test_a_duplicate_user_id_is_rejected_and_leaves_the_row_alone", 1),
                ("test_a_raw_delete_of_an_allocation_is_rejected", 1),
                ("test_a_raw_delete_of_an_expense_is_rejected", 1),
                ("test_a_raw_settlement_in_the_wrong_currency_is_rejected_by_the_foreign_key", 1),
                ("test_a_raw_update_of_a_groups_currency_is_rejected", 1),
                ("test_a_raw_update_of_an_allocation_is_rejected", 1),
                ("test_a_raw_update_of_an_expense_is_rejected", 1),
                ("test_a_raw_update_or_delete_of_a_decision_is_rejected", 2),
                ("test_a_raw_update_or_delete_of_a_settlement_is_rejected", 2),
                ("test_a_settlement_amount_above_the_bound_is_rejected", 1),
                ("test_a_settlement_in_the_wrong_currency_raises_currency_mismatch", 1),
                ("test_a_total_above_the_bound_is_rejected_naming_the_field", 1),
                ("test_add_user_with_credential_rejects_a_taken_id_or_address", 2),
                ("test_an_allocation_above_the_bound_is_rejected_naming_the_field", 1),
                ("test_an_expense_in_the_wrong_currency_raises_currency_mismatch", 1),
                ("test_delete_sessions_for_an_unknown_user_raises_not_found", 1),
                ("test_get_member_for_user_for_an_unknown_group_raises_not_found", 1),
                ("test_get_member_for_user_raises_not_found_naming_both_ids", 1),
                ("test_get_password_hash_raises_not_found_for_a_user_with_no_credential", 1),
                ("test_get_session_raises_not_found_naming_the_hash", 1),
                ("test_get_user_by_email_raises_not_found_naming_the_address", 1),
                ("test_list_events_for_an_unknown_group_raises_not_found", 1),
                ("test_list_expenses_for_an_unknown_group_raises_not_found", 1),
                ("test_list_settlement_decisions_for_an_unknown_settlement_raises_not_found", 1),
                ("test_list_settlements_for_an_unknown_group_raises_not_found", 1),
                ("test_opening_a_file_that_is_not_a_database_names_the_path", 1),
                ("test_opening_a_newer_schema_version_raises_rather_than_reading_it", 1),
                ("test_opening_a_version_3_database_still_raises", 1),
                ("test_opening_an_old_sqlite_library_raises_a_named_error", 1),
                ("test_opening_under_a_missing_directory_names_the_path", 1),
                ("test_reading_an_unknown_id_raises_not_found_naming_it", 1),
                ("test_set_member_user_for_an_unknown_member_names_the_id", 1),
                ("test_set_member_user_for_an_unknown_user_names_the_id", 1),
                ("test_set_member_user_refuses_a_member_that_already_points_at_a_user", 1),
                ("test_set_member_user_refuses_a_second_member_for_one_user_in_a_group", 1),
                ("test_strict_tables_reject_text_in_an_integer_column", 1),
            }
        ),
        "slices 70g and 70h split this module, at a point taken from this census",
    ),
    "tests/test_suite_integrity.py": (
        frozenset(
            {
                ("test_a_module_that_will_not_parse_names_the_file_and_quotes_the_error", 1),
            }
        ),
        "slice 70f retires this module, whose guard sits in tests/ and not under src/",
    ),
    "tests/test_web_api.py": (
        frozenset(
            {
                ("test_a_declared_route_the_app_does_not_serve_is_refused", 1),
                ("test_a_declared_shell_route_the_app_does_not_serve_is_refused", 1),
                ("test_a_route_outside_the_api_prefix_is_refused_by_the_audit_too", 1),
                ("test_a_route_row_refuses_a_field_it_cannot_use", 1),
                ("test_a_route_row_refuses_an_access_that_is_not_an_access_level", 1),
                ("test_a_shell_row_under_the_api_prefix_is_refused_at_build_time", 1),
                ("test_an_api_route_added_after_the_factory_is_refused_by_the_audit", 1),
                ("test_an_in_memory_store_is_refused_with_a_reason", 1),
                ("test_the_api_prefix_is_a_path_segment_and_not_a_string_prefix", 1),
                ("test_the_decision_route_must_be_declared_or_the_app_will_not_build", 1),
                ("test_the_request_time_refusal_claims_no_provenance_it_cannot_see", 1),
                ("test_the_settlements_route_must_be_declared_or_the_app_will_not_build", 1),
                ("test_two_rows_sharing_an_endpoint_name_are_refused_by_the_access_map", 1),
            }
        ),
        "slice 70d retires this module, one deleted guard in web.py at a time",
    ),
    "tests/test_web_shell.py": (
        frozenset(
            {
                ("test_an_omission_with_no_reason_is_refused", 1),
                ("test_the_digest_refuses_an_entry_it_cannot_classify", 1),
            }
        ),
        "slice 70f retires this module, whose guards sit in tests/ and not under src/",
    ),
}

# The sum of every count above, declared once. Produced by the check itself and pasted
# back; no number here is a hand count.
CARRIED_TOTAL = 107

# The reason each entry carries has to name the slice that retires it, so an entry
# cannot be added with a reason that commits nobody to anything.
RETIRING_SLICE = re.compile(r"\b70[b-h]\b")

NO_REASON_YET = "<why this module is carried, and which of 70b to 70h retires it>"


def carried_counts(source: str, where: str) -> dict[str, int]:
    """How many unanchored blocks each definition in ``source`` holds."""
    counts: dict[str, int] = {}
    for block in unanchored_message_blocks(source, where):
        counts[block.enclosing] = counts.get(block.enclosing, 0) + 1
    return counts


def carried_entry_literal(where: str, counts: dict[str, int], reason: str) -> str:
    """The CARRIED_UNANCHORED_BLOCKS entry for ``where``, ready to paste back."""
    if not counts:
        return f'    (delete the "{where}" entry: it carries nothing now)'
    pairs = "\n".join(
        f'                ("{name}", {count}),' for name, count in sorted(counts.items())
    )
    return (
        f'    "{where}": (\n'
        "        frozenset(\n"
        "            {\n"
        f"{pairs}\n"
        "            }\n"
        "        ),\n"
        f'        "{reason}",\n'
        "    ),"
    )


def computed_carried_total() -> int:
    """What CARRIED_TOTAL should read, over every test module."""
    return sum(
        len(unanchored_message_blocks(read(path), posix(path))) for path in TEST_SOURCES
    )


def spelled_entries(entries: set[tuple[str, int]]) -> str:
    """One ``name: count`` per line, ordered, for a failure to list."""
    return "\n".join(f"    {name}: {count}" for name, count in sorted(entries))


def carried_baseline_message(
    where: str,
    unlisted: set[tuple[str, int]],
    stale: set[tuple[str, int]],
    literal: str,
    total: int,
) -> str:
    """What the check says when the walk and the baseline disagree.

    Following ``stale_digest_message`` in tests/test_web_shell.py, which is how this
    repo maintains a constant the suite computes: the message ends with the exact text
    to paste back, so nobody counts anything by hand.
    """
    parts = [
        f"{where}: the unanchored pytest.raises blocks in this module and the entry "
        "CARRIED_UNANCHORED_BLOCKS holds for it have gone out of step."
    ]
    if unlisted:
        parts.append(
            "These are unanchored and not carried, so they are new:\n"
            f"{spelled_entries(unlisted)}\n"
            "\n"
            'A new one is not carried. Anchor the block instead: put match=r"^..." on '
            "the pytest.raises call, or compare the whole message with == or "
            ".startswith, or say why not with '# unanchored: <why>' on the with "
            f"statement, with a reason of at least {MINIMUM_REASON} characters. "
            "The baseline may only shrink, and nothing enforces that: it is a "
            "convention this message is asking you to keep."
        )
    if stale:
        parts.append(
            "These are carried but are no longer unanchored, so the entry has outlived "
            f"its subject:\n{spelled_entries(stale)}\n"
            "\n"
            "That is the direction that stops this baseline becoming an allowlist "
            "nobody retires. If an audit slice anchored them, take them out of the "
            "entry and lower CARRIED_TOTAL by the same number."
        )
    # The literal is printed in both directions, because a computed constant's failure
    # ends with the text to paste back and that is how this repo maintains one. But a
    # failure's last line is what people act on, and in the new-block direction the
    # paste-back is the anti-instruction: it carries the block instead of anchoring it.
    # So it is labelled rather than withheld, which keeps it available for the
    # retirement direction in a failure that reports both.
    handed = (
        "Paste this in place of this module's entry in CARRIED_UNANCHORED_BLOCKS:"
        if not unlisted
        else (
            "Below is that entry as it would now read. It is here for the retirement "
            "direction, and it is NOT the answer to a new unanchored block: pasting it "
            "carries the block instead of anchoring it, and grows the baseline, which "
            "is the one thing the baseline is not for. Anchor the block instead, as "
            "above."
        )
    )
    parts.append(
        f"{handed}\n"
        "\n"
        f"{literal}\n"
        "\n"
        "and set:\n"
        "\n"
        f"    CARRIED_TOTAL = {total}"
    )
    return "\n\n".join(parts)


def test_the_carried_baseline_message_says_which_direction_it_is_for() -> None:
    """The paste-back is labelled, so it is not read as the fix for a new block.

    A failure's last line is what people act on, and this check prints the same literal
    whichever direction it fired in. Without the label the new-block direction ends by
    handing the reader the text that carries the block rather than anchors it.
    """
    literal = '    "tests/test_pretend.py": (...),'
    new_block = carried_baseline_message(
        "tests/test_pretend.py", {("test_thing", 1)}, set(), literal, 108
    )
    assert "test_thing: 1" in new_block
    assert "NOT the answer to a new unanchored block" in new_block
    assert "carries the block instead of anchoring it" in new_block
    # The honest form of the convention, in the same message that asks for it.
    assert "nothing enforces that" in new_block
    # Criterion 18 still holds in both directions: the text ends with the entry and the
    # CARRIED_TOTAL line, so a computed constant is still maintained by pasting back.
    assert new_block.rstrip().endswith("CARRIED_TOTAL = 108")
    retirement = carried_baseline_message(
        "tests/test_pretend.py", set(), {("test_thing", 1)}, literal, 106
    )
    assert "Paste this in place of" in retirement
    assert "NOT the answer" not in retirement
    assert retirement.rstrip().endswith("CARRIED_TOTAL = 106")


@pytest.mark.parametrize("path", TEST_SOURCES, ids=SOURCE_IDS)
def test_every_message_block_is_anchored_or_carried(path: Path) -> None:
    """A raises block that reads a message either anchors, or is one of the carried."""
    where = posix(path)
    counts = carried_counts(read(path), where)
    found = set(counts.items())
    carried, reason = CARRIED_UNANCHORED_BLOCKS.get(where, (frozenset(), NO_REASON_YET))
    if found != carried:
        pytest.fail(
            carried_baseline_message(
                where,
                found - carried,
                set(carried) - found,
                carried_entry_literal(where, counts, reason),
                computed_carried_total(),
            )
        )


def test_the_carried_total_is_the_sum_of_the_baseline() -> None:
    """One declared integer, so growing the baseline is a diff a reviewer reads."""
    counted = sum(
        count
        for carried, _ in CARRIED_UNANCHORED_BLOCKS.values()
        for _, count in carried
    )
    assert CARRIED_TOTAL == counted, (
        f"CARRIED_TOTAL says {CARRIED_TOTAL} and the entries sum to {counted}. "
        "The entries are the subject; set CARRIED_TOTAL to what they sum to."
    )


def test_every_carried_module_names_the_slice_that_retires_it() -> None:
    """No entry is added with a reason that commits nobody to retiring it."""
    for where, (_, reason) in sorted(CARRIED_UNANCHORED_BLOCKS.items()):
        assert len(reason) >= MINIMUM_REASON, f"{where}: {reason!r} is not a reason"
        assert RETIRING_SLICE.search(reason), (
            f"{where}: {reason!r} names no audit slice. An entry carried by nobody is "
            "an allowlist entry, and the reason is what stops it becoming one."
        )


BLOCK_FLAGGED_PLAIN = (
    "with pytest.raises(TypeError) as raised:\n"
    "    Money(1, None)\n"
    'assert "currency must be a Currency" in str(raised.value)\n'
)
# That constant is not a hypothetical shape. Measured on this branch 2026-09-08,
# src/splitwise_lite/money.py raises "currency must be a Currency, got ..." at line 246
# and "Money currency must be a Currency, got ..." at line 148, and the shorter sentence
# sits inside the longer one from index 6. So that one assertion is satisfied by either
# of two live guards, and it is the `in` spelling of the repair PR #62 approved and then
# found defective. Quoted as measured on that date and not re-read from source: if the
# wording has changed the collision is a different one and the check is unchanged.
BLOCK_ACCEPTED_MATCH = (
    'with pytest.raises(TypeError, match=r"^currency must be a Currency") as raised:\n'
    "    Money(1, None)\n"
    'assert "Currency" in str(raised.value)\n'
)
BLOCK_ACCEPTED_EQUALITY = (
    "with pytest.raises(TypeError) as raised:\n"
    "    Money(1, None)\n"
    'assert str(raised.value) == "currency must be a Currency, got NoneType: None"\n'
)
BLOCK_ACCEPTED_STARTSWITH = (
    "with pytest.raises(TypeError) as raised:\n"
    "    Money(1, None)\n"
    'assert str(raised.value).startswith("currency must be a Currency")\n'
)
BLOCK_FLAGGED_BOUND = (
    "with pytest.raises(TypeError) as raised:\n"
    "    Money(1, None)\n"
    "message = str(raised.value)\n"
    'assert "currency must be a Currency" in message\n'
)
BLOCK_ACCEPTED_BOUND_EQUALITY = (
    "with pytest.raises(TypeError) as raised:\n"
    "    Money(1, None)\n"
    "message = str(raised.value)\n"
    'assert message == "currency must be a Currency, got NoneType: None"\n'
)
BLOCK_ACCEPTED_MARKED = (
    "with pytest.raises(TypeError) as raised:  "
    "# unanchored: the arrangement can raise nothing else\n"
    "    Money(1, None)\n"
    'assert "Currency" in str(raised.value)\n'
)
BLOCK_FLAGGED_EMPTY_MARKER = (
    "with pytest.raises(TypeError) as raised:  # unanchored:\n"
    "    Money(1, None)\n"
    'assert "Currency" in str(raised.value)\n'
)
BLOCK_FLAGGED_SHORT_MARKER = (
    "with pytest.raises(TypeError) as raised:  # unanchored: too short\n"
    "    Money(1, None)\n"
    'assert "Currency" in str(raised.value)\n'
)
BLOCK_ACCEPTED_MARKER_ON_LAST_LINE = (
    "with pytest.raises(\n"
    "    TypeError,\n"
    ") as raised:  # unanchored: the arrangement can raise nothing else\n"
    "    Money(1, None)\n"
    'assert "Currency" in str(raised.value)\n'
)
BLOCK_NOT_A_CANDIDATE_NO_BINDING = (
    "with pytest.raises(TypeError):\n    Money(1, None)\n"
)
BLOCK_NOT_A_CANDIDATE_UNREAD = (
    "with pytest.raises(TypeError) as raised:\n"
    "    Money(1, None)\n"
    "assert raised.type is TypeError\n"
)
BLOCK_FLAGGED_NEGATIVE_ONLY = (
    "with pytest.raises(TypeError) as raised:\n"
    "    Money(1, None)\n"
    'assert "the secret" not in str(raised.value)\n'
)
BLOCK_ACCEPTED_MANY_FRAGMENTS = (
    "def test_it() -> None:\n"
    "    with pytest.raises("
    'TypeError, match=r"^currency must be a Currency") as raised:\n'
    "        Money(1, None)\n"
    '    assert "NoneType" in str(raised.value)\n'
    '    assert "None" in str(raised.value)\n'
    '    assert "Currency" in str(raised.value)\n'
)
BLOCK_FLAGGED_MANY_FRAGMENTS = (
    "def test_it() -> None:\n"
    "    with pytest.raises(TypeError) as raised:\n"
    "        Money(1, None)\n"
    '    assert "NoneType" in str(raised.value)\n'
    '    assert "None" in str(raised.value)\n'
    '    assert "Currency" in str(raised.value)\n'
)
BLOCK_FLAGGED_OTHER_CALL_MATCH = (
    "with pytest.raises(TypeError) as raised:\n"
    "    Money(1, None)\n"
    'record = dict(match="^currency must be a Currency")\n'
    'assert "Currency" in str(raised.value)\n'
)
BLOCK_TWO_IN_ONE_FUNCTION = (
    "def test_two() -> None:\n"
    "    with pytest.raises(TypeError) as first:\n"
    "        Money(1, None)\n"
    '    assert "Currency" in str(first.value)\n'
    "    with pytest.raises("
    'ValueError, match=r"^cents must be an int") as second:\n'
    "        Money(None, AUD)\n"
    '    assert "int" in str(second.value)\n'
)


def test_the_message_block_check_still_bites() -> None:
    """Proof that the check refuses what it must and accepts what it must not refuse.

    Every accepted case below is labelled with the branch of the accepted set it is the
    positive control for, so removing that branch reds a named assertion here. The two
    cases that hold by construction say so and say what they do guard against instead. A
    section of self-tests that cannot fail is the defect this module exists to refuse.
    """
    # a. A bare substring assertion on the message is flagged. Positive control for the
    #    walk itself: if message_blocks stops finding candidates, this reds first.
    flagged = unanchored_message_blocks(BLOCK_FLAGGED_PLAIN, "<a>")
    assert len(flagged) == 1
    assert flagged[0].name == "raised"
    assert flagged[0].enclosing == "<module>"
    assert flagged[0].lineno == 1
    # b. match= on the raises call is accepted. Positive control for branch (a) of the
    #    accepted set; delete that branch and this reds.
    assert unanchored_message_blocks(BLOCK_ACCEPTED_MATCH, "<b>") == []
    # c. An equality against the message is accepted. Positive control for branch (b);
    #    delete that branch and this reds.
    assert unanchored_message_blocks(BLOCK_ACCEPTED_EQUALITY, "<c>") == []
    # d. .startswith on the message is accepted. Positive control for branch (c);
    #    delete that branch and this reds.
    assert unanchored_message_blocks(BLOCK_ACCEPTED_STARTSWITH, "<d>") == []
    # e. The bound form is a candidate and is flagged.
    #
    #    This one is flagged by construction under any mutation of the local-binding
    #    walk, because `message = str(raised.value)` is itself the str() call shape, so
    #    the block is a candidate whether or not the local is followed. What it guards
    #    against is a walk that only looks at `assert` statements. The case that really
    #    exercises the local-binding walk is the one below it.
    assert len(unanchored_message_blocks(BLOCK_FLAGGED_BOUND, "<e>")) == 1
    # e2. An equality against a local the block bound to the message is accepted.
    #     Positive control for the one level of local binding in criterion 6(b): stop
    #     following the local and this block is no longer anchored, so this reds. That
    #     is 27 lines of the real population, so a walk that misses it misses a quarter
    #     of the job.
    assert unanchored_message_blocks(BLOCK_ACCEPTED_BOUND_EQUALITY, "<e2>") == []
    # f. The marker with a real reason is accepted; empty or too short is not a reason.
    #    Positive control for branch (d) and for MINIMUM_REASON.
    assert unanchored_message_blocks(BLOCK_ACCEPTED_MARKED, "<f1>") == []
    assert len(unanchored_message_blocks(BLOCK_FLAGGED_EMPTY_MARKER, "<f2>")) == 1
    assert len(unanchored_message_blocks(BLOCK_FLAGGED_SHORT_MARKER, "<f3>")) == 1
    # g. The marker may sit on the last line of a raises call wrapped over several
    #    lines. Positive control for the header range: narrow it to the first line and
    #    this reds.
    assert unanchored_message_blocks(BLOCK_ACCEPTED_MARKER_ON_LAST_LINE, "<g>") == []
    # h. A raises that binds no name is not a candidate.
    #
    #    Partly by construction: with no name bound there is no message expression to
    #    find either, so this stays empty under a mutation of the `as` condition alone.
    #    What it guards against is a future rewrite that treats every raises block as a
    #    candidate and then asks separately whether it is anchored, which would report a
    #    finding on every `with pytest.raises(X):` in the suite.
    assert message_blocks(BLOCK_NOT_A_CANDIDATE_NO_BINDING, "<h>") == []
    # i. A block that binds a name and never reads its message is not a candidate.
    #    Positive control for the reads-the-message condition: drop it and this reds.
    #    A block that asserts nothing about a message has nothing to anchor.
    assert message_blocks(BLOCK_NOT_A_CANDIDATE_UNREAD, "<i>") == []
    # j. A block holding only a negative assertion is still a candidate and is still
    #    flagged, because reading the message is what makes it one.
    #
    #    By construction here, since this walk never looks at the `in` operator at all.
    #    What it guards against is the rewrite issue #70 itself proposes, which keys on
    #    `assert X in str(Y)`: that shape would drop all 17 negative assertions in the
    #    suite, and a negative is the weaker case, not the safer one — any message
    #    lacking the string satisfies it, including one from an entirely different
    #    guard.
    assert len(unanchored_message_blocks(BLOCK_FLAGGED_NEGATIVE_ONLY, "<j>")) == 1
    # k. Several fragment assertions with one anchor are accepted once, and the same
    #    block without the anchor is one finding rather than one per fragment. Positive
    #    control for the unit being the block: count per assertion and both of these
    #    read 3.
    assert unanchored_message_blocks(BLOCK_ACCEPTED_MANY_FRAGMENTS, "<k1>") == []
    assert len(message_blocks(BLOCK_ACCEPTED_MANY_FRAGMENTS, "<k1>")) == 1
    many = unanchored_message_blocks(BLOCK_FLAGGED_MANY_FRAGMENTS, "<k2>")
    assert len(many) == 1
    assert many[0].enclosing == "test_it"
    # l. A match= on a call that is not the raises is not an anchor, for the same reason
    #    NOT_A_PIN_OTHER_CALL exists. Positive control for reading the keyword off the
    #    context expression rather than off any call in the region.
    assert len(unanchored_message_blocks(BLOCK_FLAGGED_OTHER_CALL_MATCH, "<l>")) == 1
    # m. Two blocks in one function are two candidates, and anchoring one moves the
    #    count from two to one. This is the case criterion 15 keys the baseline on a
    #    count for, and a baseline keyed by name alone would miss it.
    assert len(message_blocks(BLOCK_TWO_IN_ONE_FUNCTION, "<m>")) == 2
    two = unanchored_message_blocks(BLOCK_TWO_IN_ONE_FUNCTION, "<m>")
    assert len(two) == 1
    assert two[0].name == "first"
    assert two[0].enclosing == "test_two"


def test_the_unanchored_block_message_says_what_happened() -> None:
    """Every element the message has to carry, fed a synthetic path, line and name."""
    message = unanchored_block_message("tests/test_pretend.py", 12, "raised")
    assert "tests/test_pretend.py" in message
    assert "12" in message
    assert "raised" in message
    # `in` is the same operation, so the PR #62 collision applies to it unchanged.
    assert "re.search" in message
    assert "no metacharacters" in message
    assert "PR #62" in message
    # The anchor goes on the block, and why.
    assert "on the block" in message
    assert "several fragments" in message
    assert "at most one can start the message" in message
    # A negative assertion is weaker still.
    assert "any message lacking the string satisfies it" in message
    # All four accepted anchors, spelled.
    assert "match=" in message
    assert "==" in message
    assert ".startswith" in message
    assert "# unanchored:" in message
    assert str(MINIMUM_REASON) in message


# --- The mutation records (#60) --------------------------------------------
#
# These two checks read the records as data: that a record parses, that it is complete,
# and that no section is prose only. They deliberately do NOT re-verify a record's
# anchor against the live source file. Re-verifying would put every past mutation in
# the path of every future refactor, which is exactly the ossification #60 warns
# against, and it would turn a re-runnable record back into a maintenance burden. A
# committed mutant is re-run every suite, and mutated() in tests/test_shell_behaviour.py
# is what makes its anchor self-checking; a recorded one is re-runnable on demand. That
# difference is the whole reason both exist, so do not "improve" these checks into the
# thing the issue argued against.

JSON_BLOCK = re.compile(r"^```json\n(.*?)^```", re.MULTILINE | re.DOTALL)
SECTION = re.compile(r"^## ", re.MULTILINE)
REQUIRED_KEYS = {"id", "file", "find", "replace", "kills", "survives", "result"}
RESULTS = {"killed", "survived", "killed-for-the-wrong-reason"}


def record_files() -> list[Path]:
    """Every mutation record file, which is every markdown file but the README.

    Refuses an empty answer, for the same reason ``TEST_SOURCES`` does: returning ``[]``
    when the directory is gone would let both checks below pass green over nothing,
    which is the shape of defect this whole module exists to refuse. The rules file
    names this directory in rule (e), and
    ``test_the_testing_rules_name_the_mechanisms_that_enforce_them`` cannot catch its
    deletion, because that check greps the literal string out of the rules file and the
    string survives the directory.
    """
    assert MUTATIONS.is_dir(), (
        f"{posix(MUTATIONS)} does not exist, so both mutation checks below would "
        "check nothing and pass. Rule (e) of .claude/rules/testing.md names that "
        "directory as where a mutation is recorded; if it has moved, move the rule and "
        "this constant with it rather than leaving a green suite behind."
    )
    found = sorted(p for p in MUTATIONS.glob("*.md") if p.name != "README.md")
    assert found, (
        f"{posix(MUTATIONS)} holds no record file, so both mutation checks below would "
        "check nothing and pass. Every mutation claimed in a PR is recorded there, one "
        "file per task or issue, and README.md alone is not a record."
    )
    return found


def mutation_record_problems(record: object, seen: set[str]) -> list[str]:
    """Everything wrong with one record, so a failure lists them all at once."""
    problems: list[str] = []
    if not isinstance(record, dict):
        return [f"the block is a {type(record).__name__}, not a JSON object"]
    keys = set(record)
    if keys != REQUIRED_KEYS:
        missing = sorted(REQUIRED_KEYS - keys)
        extra = sorted(keys - REQUIRED_KEYS)
        if missing:
            problems.append(f"missing keys: {', '.join(missing)}")
        if extra:
            problems.append(f"keys that do not belong: {', '.join(extra)}")
        return problems
    identifier = record["id"]
    if not isinstance(identifier, str) or not identifier:
        problems.append("id is not a non-empty string")
    elif identifier in seen:
        problems.append(f"id {identifier!r} is used by another record in this file")
    target = record["file"]
    if not isinstance(target, str) or not target:
        problems.append("file is not a non-empty string")
    else:
        if target.startswith("/") or ".." in Path(target).parts:
            problems.append(f"file {target!r} is not a relative path without '..'")
        if "\\" in target or re.match(r"^[A-Za-z]:", target):
            problems.append(f"file {target!r} is not a POSIX path")
    if not isinstance(record["find"], str) or not record["find"]:
        problems.append("find is not a non-empty string")
    if record["find"] == record["replace"]:
        problems.append("find and replace are the same, so the record mutates nothing")
    for key in ("kills", "survives"):
        value = record[key]
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            problems.append(f"{key} is not a list of strings")
    if record["result"] not in RESULTS:
        problems.append(
            f"result {record['result']!r} is not one of {', '.join(sorted(RESULTS))}"
        )
    if record["result"] == "killed" and not record["kills"]:
        problems.append("result is 'killed' but kills is empty, so nothing killed it")
    return problems


def mutation_record_message(where: str, index: int, problems: list[str]) -> str:
    """What the check says about one malformed record."""
    listed = "\n".join(f"    {problem}" for problem in problems)
    return (
        f"{where}, JSON block {index}, is not a usable mutation record:\n"
        f"{listed}\n"
        "\n"
        "A record exists so the next person can re-run the mutation instead of "
        "reconstructing it from a sentence, which is what #60 found produced a "
        "different mutation and a different result. "
        "plans/mutations/README.md states the format."
    )


def test_every_recorded_mutation_is_machine_readable() -> None:
    """Each record parses and is complete, so it can be applied without guesswork."""
    failures: list[str] = []
    for path in record_files():
        where = posix(path)
        seen: set[str] = set()
        for index, block in enumerate(JSON_BLOCK.findall(read(path)), start=1):
            try:
                record = json.loads(block)
            except json.JSONDecodeError as exc:
                failures.append(mutation_record_message(where, index, [f"invalid JSON: {exc}"]))
                continue
            problems = mutation_record_problems(record, seen)
            if problems:
                failures.append(mutation_record_message(where, index, problems))
            elif isinstance(record, dict) and isinstance(record.get("id"), str):
                seen.add(record["id"])
    assert not failures, "\n\n".join(failures)


def record_sections(text: str) -> list[tuple[str, str]]:
    """Each ``##`` section of a record file, as ``(heading, section text)``.

    Whatever a file writes above its first ``##`` is its introduction rather than a
    record, and is not returned. That is the residual of the check below, stated rather
    than left to be discovered: a node id named in an introduction is nobody's ``kills``
    and could not be checked against one.
    """
    starts = [match.start() for match in SECTION.finditer(text)]
    sections: list[tuple[str, str]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(text)
        section = text[start:end]
        sections.append((section.split("\n", 1)[0].strip(), section))
    return sections


def test_a_mutation_record_holds_no_prose_only_section() -> None:
    """Every section carries the record itself, not a description of one.

    This is the criterion that stops sentences creeping back in, which is the whole of
    #60: a mutation is an anchor and a replacement, never a sentence.
    """
    failures: list[str] = []
    for path in record_files():
        where = posix(path)
        for heading, section in record_sections(read(path)):
            if not JSON_BLOCK.search(section):
                failures.append(
                    f"{where} section {heading!r} holds no fenced JSON block, so it "
                    "describes a mutation instead of recording one. #60 is that a "
                    "description standing in for the thing itself produced a different "
                    "mutation and a different result."
                )
    assert not failures, "\n\n".join(failures)


# A record's prose and its JSON have to agree about which tests a mutation touched.
# mutation_record_problems type-checks `kills` and `survives` and never reads the list
# of covered tests written beside them, so a wrong entry there is invisible to the
# suite. plans/mutations/65-message-pins.md is the worked example of the shape that goes
# wrong: it numbers its pins 1 to 13 across sections, so an entry is bound to its
# subject only by its position in a list that lives in a different section from the
# guard it describes. At thirteen that survives; at the fifty-odd guards issue #70's
# audit will delete, it is a defect generator, and this repo has already published a
# number attached to the wrong mutation for exactly that reason.
#
# So a node id is the vocabulary: it is unique, it carries its own subject, and it is
# already what `kills` and `survives` hold. This check makes the two agree in the one
# direction that matters, prose to JSON. It does not require the reverse: a record may
# list a node id in `kills` and not mention it in prose, because `kills` is the complete
# list and the prose is commentary on it.
#
# REQUIRED_KEYS does not change and no new JSON key is added; this reads the seven that
# exist.
NODE_ID_SEPARATOR = "::"


def prose_node_ids(prose: str) -> set[str]:
    """Every pytest node id the prose names, recognised by holding ``::``.

    Markdown decoration is stripped from both ends, and sentence punctuation from the
    end only, so a parametrised id keeps its trailing ``]``.
    """
    found: set[str] = set()
    for token in re.split(r"[\s`]+", prose):
        candidate = token.strip("`\"'*()").rstrip(".,;:")
        if NODE_ID_SEPARATOR in candidate:
            found.add(candidate)
    return found


def stray_node_ids(section: str) -> list[str]:
    """Node ids this section's prose names that its JSON blocks do not list."""
    listed: set[str] = set()
    for block in JSON_BLOCK.findall(section):
        try:
            record = json.loads(block)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        for key in ("kills", "survives"):
            value = record.get(key)
            if isinstance(value, list):
                listed.update(item for item in value if isinstance(item, str))
    prose = JSON_BLOCK.sub("", section)
    return sorted(prose_node_ids(prose) - listed)


def stray_node_id_message(where: str, heading: str, identifier: str) -> str:
    """What the check says about a node id a record names but does not list."""
    return (
        f"{where} section {heading!r} names {identifier} in its prose, and neither "
        "kills nor survives in that section's record lists it.\n"
        "\n"
        "So the claim and the record disagree about which tests the mutation touched, "
        "and only the record is checked by anything. Put the id in kills if the "
        "mutation reddened that test, or in survives if it stayed green. If the prose "
        "meant a different test, the id is the thing to correct: a claim bound to its "
        "subject by position in a list is how a correct number ended up against the "
        "wrong mutation in this repo."
    )


def test_every_node_id_a_record_names_is_one_it_lists() -> None:
    """A record's prose names no test that its own kills and survives do not."""
    failures: list[str] = []
    for path in record_files():
        where = posix(path)
        for heading, section in record_sections(read(path)):
            failures += [
                stray_node_id_message(where, heading, identifier)
                for identifier in stray_node_ids(section)
            ]
    assert not failures, "\n\n".join(failures)


RECORD_WITH_A_STRAY_NODE_ID = """\
## A guard

```json
{
  "id": "g1",
  "file": "src/splitwise_lite/example.py",
  "find": "raise X",
  "replace": "pass",
  "kills": ["tests/test_example.py::test_one"],
  "survives": ["tests/test_example.py::test_two"],
  "result": "killed"
}
```

Covers `tests/test_example.py::test_one` and `tests/test_example.py::test_three`.
"""

RECORD_WITH_ONLY_LISTED_NODE_IDS = """\
## A guard

```json
{
  "id": "g1",
  "file": "src/splitwise_lite/example.py",
  "find": "raise X",
  "replace": "pass",
  "kills": ["tests/test_example.py::test_one[a-case]"],
  "survives": ["tests/test_example.py::test_two"],
  "result": "killed"
}
```

Covers `tests/test_example.py::test_one[a-case]`, and
**tests/test_example.py::test_two** stayed green.
"""


def test_the_node_id_check_still_bites() -> None:
    """The positive control: a stray id is a finding and a listed one is not.

    Every record on the branch today names no node id in prose at all, so without these
    two the check would be green over the whole directory whatever it did.
    """
    stray = stray_node_ids(RECORD_WITH_A_STRAY_NODE_ID)
    assert stray == ["tests/test_example.py::test_three"]
    # Not the ids that are listed, and a parametrised id keeps its trailing bracket
    # rather than being trimmed into a different id that would then read as stray.
    assert stray_node_ids(RECORD_WITH_ONLY_LISTED_NODE_IDS) == []
    assert "tests/test_example.py::test_one[a-case]" in prose_node_ids(
        RECORD_WITH_ONLY_LISTED_NODE_IDS
    )


def test_the_stray_node_id_message_says_what_happened() -> None:
    """The message names the file, the section, the id, and what to do about it."""
    message = stray_node_id_message(
        "plans/mutations/70a-pretend.md", "## A guard", "tests/test_x.py::test_y"
    )
    assert "plans/mutations/70a-pretend.md" in message
    assert "## A guard" in message
    assert "tests/test_x.py::test_y" in message
    assert "neither kills nor survives" in message
    assert "Put the id in kills" in message
    assert "wrong mutation" in message


# --- The measurement that could not fail, refused in the documents (#58) ---

# What is scanned: every Markdown document under plans/, plus README.md and CLAUDE.md.
# Not tests/ and not app/, and neither omission is laziness.
#
# tests/ cannot be scanned because this check's own source and its own message have to
# write the banned literal out in order to say what is banned, so a scan over tests/
# would flag the very lines that make it work. app/ is not scanned because the shell is
# code rather than a specification, and the one occurrence it has today is the comment
# on `body` in app/styles.css that says what to measure instead, which is the thing
# being asked for rather than the defect. Somebody will eventually read this scan as
# arbitrarily narrow and reach to widen it; a check that flags itself is precisely the
# shape of defect this module exists to refuse, so do not.

# The one document the scan cannot cover, for exactly the reason given above for
# tests/: this file is the specification of this check, so its criteria have to write
# the banned literal out to say what is banned, and three of them name it with no
# `document.` prefix and no quotation to put in a blockquote. Criterion 23 of that spec
# asks for no per-file skip at all, and this is a deviation from it, recorded here
# rather than hidden: with the spec committed under plans/tasks/ as criterion 41
# requires, criteria 20, 23 and 41 cannot all hold at once. It is the specification of
# the mechanism and nothing else, it is not a licence for a second entry, and a rename
# does not quietly widen the scan: the path stops matching and the scan goes red naming
# the renamed file.
SPECIFIES_THE_SCAN = (
    REPO / "plans" / "tasks" / "58-the-overflow-check-that-measured-the-wrong-element.md"
)


def scanned_documents() -> list[Path]:
    """Every specification document the scan covers, taken from the filesystem.

    Derived rather than written out, so a task spec written later is covered without
    anybody remembering to add it to a list. That is the property the per-class
    ``CARRIES_A_NAME`` list in PR #56 did not have, and its absence is why that list
    shipped wrong and why issue #58 deleted it.
    """
    # An exclusion that outlives the file it excludes is dead weight nothing reports.
    # A rename already fails loudly, because the path stops matching and the renamed
    # file gets scanned; a deletion would not, so it is asserted here instead.
    assert SPECIFIES_THE_SCAN.exists(), (
        f"{posix(SPECIFIES_THE_SCAN)} is excluded from this scan but no longer "
        "exists, so the exclusion is dead. Delete it, or point it at the document "
        "that specifies this check."
    )
    found = list((REPO / "plans").rglob("*.md"))
    found += [REPO / "README.md", REPO / "CLAUDE.md"]
    return sorted(path for path in found if path != SPECIFIES_THE_SCAN)


# A date, in the form every dated note in this repo already carries. Shape only: no
# calendar validation and no minimum prose, so this recognises the form a correction
# note takes rather than proving one was written. What it buys is that an exemption has
# to be placed inside a dated note and shows in a diff as one, where a bare '>' is one
# character and shows as nothing.
DATED_NOTE = re.compile(r"\d{4}-\d{2}-\d{2}")


def blockquote_run(lines: list[str], index: int) -> list[str]:
    """The contiguous run of blockquote lines containing ``lines[index]``, or nothing.

    The run and not the line. A dated note opens with its marker and the wording it
    quotes sits below that marker, so looking for the date on the line that carries the
    banned literal would refuse every real note in this repo.

    Measured 2026-09-07 rather than assumed, because that reason otherwise reads as a
    guess. The five surviving blockquoted occurrences sit in runs of **10, 10, 12, 14
    and 21 lines**. In all five the date is on the run's opening line and the literal is
    **one or two lines below it**, so the date is never on the line carrying the literal
    and a line-local predicate would have reddened all five. That is the load-bearing
    part: the runs are long, but the distance that matters is small and it is never zero.

    An earlier draft of the paragraph above said the quoted wording "usually sits several
    lines below". The measurement does not support that, and the clause is quoted here
    rather than silently dropped because two distances standing side by side, one of them
    superseded and unmarked, is the defect this whole module is about.

    A blank line breaks the run, which is Markdown's own rule for where a blockquote
    ends, and that is the residual worth stating plainly: an undated ``>`` line glued
    directly onto a dated note, with no blank line between them, is exempt, and so is an
    indented list-level quote glued to a top-level dated one, which Markdown renders as
    two containers while this walk sees one. Left as it is deliberately. The cost of
    that route is writing your new criterion physically inside somebody else's dated
    correction note, where it renders as part of that note, and a blank line anywhere
    between restores the refusal.
    """
    if not lines[index].strip().startswith(">"):
        return []
    start = index
    while start > 0 and lines[start - 1].strip().startswith(">"):
        start -= 1
    end = index
    while end + 1 < len(lines) and lines[end + 1].strip().startswith(">"):
        end += 1
    return lines[start : end + 1]


def wrong_measurement_message(where: str, line: int, text: str) -> str:
    """What the check says about one line asking for a measurement that cannot fail."""
    return (
        f"{where}:{line} names `documentElement`:\n"
        f"    {text.strip()}\n"
        "\n"
        "In this shell that measurement cannot fail. app/styles.css sets "
        "`overflow: hidden` on `body`, and `.content` is the element that scrolls. The "
        "viewport's scrolling area is propagated from the root element, and the root "
        "clips, so nothing inside `.content` can extend it and the root's scrollable "
        "area can never grow. `documentElement.scrollWidth` therefore equals its "
        "`clientWidth` whether or not content overflows: the equality is not weak, it "
        "is constant. A criterion asking for it reports success in exactly the case it "
        "was written to catch. Four task specs asked for it, and the PR #56 defect "
        "would have gone green on every one of them.\n"
        "\n"
        "Write this instead:\n"
        "\n"
        "    el.scrollWidth > el.clientWidth, over `.content` and every element "
        "inside it, and over each rendered row container\n"
        "\n"
        "and say that the sweep reports how many elements it examined, because both "
        "properties are integer-rounded, so a sub-pixel overflow reads as none, and a "
        "hidden element reports 0 for both, so every collapsed region passes trivially "
        "unless it is opened first.\n"
        "\n"
        "Quoting the old wording is legal, in one shape only: a blockquote carrying a "
        "date, in the form this repo already uses for a correction note, opening "
        "'**Corrected 2026-09-07 for issue #58**' or '**Stale ...**' and quoting the "
        "wording that was wrong. The date is what the exemption is for. A bare '>' is "
        "not enough and is refused, because an exemption a criterion can claim by "
        "writing one character next to itself is not an exemption, it is a hole, and "
        "this whole check exists because a check that does not exercise what it names "
        "was believed."
    )


def test_no_document_asks_for_the_measurement_that_cannot_fail() -> None:
    """No specification asks for `documentElement.scrollWidth` against `clientWidth`.

    This is the durable half of issue #58. The stylesheet half of that issue is fixed
    once; this is what stops the wrong measurement being copied into the next task
    spec that thinks about small screens, which #58's own scope line predicted it
    would be. It could not be a rule instead: a rule lasts exactly as long as the next
    author who has not read it, which is the failure mode
    ``plans/tasks/46-shell-precache-digest.md`` records for ``VERSION``.

    A wrong measurement written into a criterion belongs in this module rather than
    beside the stylesheet checks, because it is a check that reports success without
    exercising what it names, which is what all three of the issues above are.
    """
    failures: list[str] = []
    for path in scanned_documents():
        where = posix(path)
        lines = read(path).splitlines()
        for index, text in enumerate(lines):
            if "documentElement" not in text:
                continue
            # The dated-note exemption, and the only exemption a document can claim
            # for itself. Quoting the wording that was wrong stays legal so the
            # historical record survives; writing it into a criterion does not.
            #
            # The date is the whole exemption. An earlier version of this check accepted
            # any line starting with '>', which meant a future author facing this red
            # test could prefix one character and go green with no date and no reason,
            # and nothing in the diff would read as a claimed exemption. That is a check
            # that does not exercise what it names, which is the defect this module
            # exists to refuse, so it was refusing it everywhere except in itself.
            #
            # What the predicate actually costs, stated exactly, because this is not the
            # `# unanchored:` hatch above and must not be described as its equal: that
            # hatch enforces twenty characters of real reason, while `DATED_NOTE` is
            # shape only, so `> per 1234-56-78` is exempt with no reason and no calendar
            # validation. The deterrent here is different and weaker: the escape route
            # costs writing your new criterion physically inside somebody else's dated
            # correction note, where it renders as part of that note and reads as one.
            # That is a long way above one character and it is enough, but it is a
            # placement cost rather than a written justification.
            if DATED_NOTE.search("\n".join(blockquote_run(lines, index))):
                continue
            failures.append(wrong_measurement_message(where, index + 1, text))
    assert not failures, "\n\n".join(failures)


def test_the_wrong_measurement_message_says_what_to_write_instead() -> None:
    """The message names the place, quotes the line, and gives the replacement.

    Following ``stale_digest_message`` in tests/test_web_shell.py. The message is the
    entire product of a check that fires, so it gets a test of its own rather than
    being read once by its author and then left to rot behind a green suite.
    """
    message = wrong_measurement_message(
        "plans/tasks/08-mobile-web-shell.md",
        214,
        "- At 320 CSS px wide there is no horizontal scroll: "
        "`document.documentElement.scrollWidth`",
    )
    assert message.startswith("plans/tasks/08-mobile-web-shell.md:214")
    # The offending line is quoted, so the reader does not have to open the file to
    # see which of several similar checklist lines was meant.
    assert "`document.documentElement.scrollWidth`" in message
    # Why it cannot fail, in terms of the two declarations that cause it.
    assert "overflow: hidden" in message
    assert "`.content`" in message
    # What to write instead, and the two caveats that make the replacement honest.
    assert "el.scrollWidth > el.clientWidth" in message
    assert "integer-rounded" in message
    assert "reports 0 for both" in message
    # And the one way to keep the old wording legally, stated as the dated note it
    # actually requires rather than as the bare '>' an earlier version accepted. A
    # message that advertises a wider hatch than the check honours sends the reader
    # to write something that will still be refused.
    assert "blockquote carrying a date" in message
    assert "A bare '>' is not enough and is refused" in message


# --- The rules the three issues land in ------------------------------------

THE_THREE_BULLETS = (
    "- Tests are pytest, run with `uv run python -m pytest` (plain `uv run pytest` "
    "fails on\n  Windows with an access-denied spawn error)",
    "- Test settle-up with exact integer assertions, never approximate",
    "- Never mark a test skipped or xfail to make the suite green",
)

# Entries naming a definition this module really makes. These get a second check,
# because a substring assertion on markdown cannot see a rename: change the name in the
# code and in the tuple literal together, and the rules text and the substring check are
# both untouched and green while the rule names a function that is gone. That is the #70
# defect inside the mechanism meant to prevent it, and it is measured rather than
# argued: mutation m4-a-named-check-renamed in plans/mutations/70a-message-block-check.md
# renames one of these and only the resolution check below reds.
ENFORCING_SYMBOLS = (
    "test_every_message_pin_is_anchored_or_says_why",
    "test_every_message_block_is_anchored_or_carried",
    "CARRIED_UNANCHORED_BLOCKS",
    "CARRIED_TOTAL",
)

# Entries naming a path, resolved against the filesystem for the same reason.
ENFORCING_PATHS = (
    "tests/test_suite_integrity.py",
    "plans/mutations/",
)

# Entries resolving to nothing but themselves: a marker, an environment variable, a
# standard-library function named in prose and a source form. There is no definition and
# no path to resolve, so a substring in the rules text is the whole of the check for
# these four. Stated rather than assumed, because the claim this comment used to make,
# that a rename would go red, was true of none of them.
ENFORCING_CONVENTIONS = (
    "# unanchored:",
    "PYTHONDONTWRITEBYTECODE",
    "re.search",
    'match=r"^',
)

ENFORCING_MECHANISMS = ENFORCING_SYMBOLS + ENFORCING_PATHS + ENFORCING_CONVENTIONS


def unresolved_mechanisms(
    symbols: tuple[str, ...], paths: tuple[str, ...], namespace: dict[str, object]
) -> list[str]:
    """Named mechanisms that resolve to nothing, so the rule names something gone."""
    problems: list[str] = []
    for symbol in symbols:
        if symbol not in namespace:
            problems.append(
                f"{posix(RULES)} names {symbol}, and tests/test_suite_integrity.py "
                "defines no such name. Either the rule is naming something that was "
                "renamed or deleted, or this tuple is. A rule naming something gone is "
                "the shape of defect every issue in this module is about."
            )
    for path in paths:
        if not (REPO / path).exists():
            problems.append(
                f"{posix(RULES)} names {path}, which does not exist in this checkout."
            )
    return problems


def test_the_testing_rules_keep_the_three_they_had() -> None:
    """The three bullets that were there before this task are still there.

    Nothing is removed from that file, by this task or a later one, without this test
    going red.
    """
    text = read(RULES)
    for bullet in THE_THREE_BULLETS:
        assert bullet in text, bullet


def test_the_testing_rules_name_the_mechanisms_that_enforce_them() -> None:
    """A rule whose mechanism was renamed or deleted goes red.

    Rather than sitting there naming something that is gone, which is the shape of
    every defect these three issues are about.
    """
    text = read(RULES)
    for mechanism in ENFORCING_MECHANISMS:
        assert mechanism in text, mechanism


def test_every_named_mechanism_resolves_to_something_that_exists() -> None:
    """A mechanism the rules file names is a definition or a path, not just a string.

    The check above asserts the name appears in the markdown, which a rename does not
    disturb: rename the function and the tuple entry together and it stays green while
    the rule names something gone. This one resolves the identifier-shaped entries
    against this module's namespace and the path-shaped ones against the filesystem, so
    the rename reds here instead.
    """
    assert unresolved_mechanisms(ENFORCING_SYMBOLS, ENFORCING_PATHS, globals()) == []


def test_every_named_mechanism_is_classified() -> None:
    """No entry escapes into the substring-only group by being added unclassified."""
    grouped = ENFORCING_SYMBOLS + ENFORCING_PATHS + ENFORCING_CONVENTIONS
    assert sorted(ENFORCING_MECHANISMS) == sorted(grouped)
    assert len(set(grouped)) == len(grouped), "an entry is in two groups"
    # The conventions are the entries with nothing to resolve to. Shape is the wrong
    # test for that: PYTHONDONTWRITEBYTECODE is a valid identifier and is an environment
    # variable, not a definition. What matters is that a convention resolves to neither
    # a name this module defines nor a path on disk, because if it ever did it would
    # belong in a group that gets the resolution check and leaving it here would exempt
    # it silently.
    for convention in ENFORCING_CONVENTIONS:
        assert convention not in globals(), convention
        assert not (REPO / convention).exists(), convention


def test_the_mechanism_resolution_check_still_bites() -> None:
    """Proof the resolution check refuses a name that resolves to nothing.

    Without this the check would be green over a tuple whose entries all happen to
    exist, and nothing would show that it had ever looked.
    """
    # a. A symbol this module does not define is a finding naming it.
    gone = unresolved_mechanisms(("test_a_check_that_was_renamed",), (), globals())
    assert len(gone) == 1
    assert "test_a_check_that_was_renamed" in gone[0]
    assert "defines no such name" in gone[0]
    # b. A path that does not exist is a finding naming it.
    missing = unresolved_mechanisms((), ("plans/nowhere-at-all/",), globals())
    assert len(missing) == 1
    assert "plans/nowhere-at-all/" in missing[0]
    # c. A real definition and a real path are not findings, which is what keeps (a)
    #    and (b) from passing because the helper always returns something.
    assert unresolved_mechanisms(("posix",), ("README.md",), globals()) == []
