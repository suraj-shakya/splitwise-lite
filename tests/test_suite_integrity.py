"""The suite's check on itself.

Three failures in this repo reported success without exercising the thing they named,
and this module answers them with something that runs: GitHub issues #67, #65 and #60.

The duplicate-definition check refuses a test module that binds one name twice at
module level, because Python rebinds silently and pytest then collects only the last
definition, so the earlier test is deleted with nothing anywhere reporting an error.
The anchored-pin check refuses a ``pytest.raises(match=)`` whose pattern is not
anchored with ``^`` and carries no ``# unanchored:`` reason, because ``match=`` is an
``re.search`` and an unanchored pattern can be satisfied by a superstring that somebody
else's guard raised. A fourth failure, GitHub issue #58, gets the third refusal here and
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


def test_a_mutation_record_holds_no_prose_only_section() -> None:
    """Every section carries the record itself, not a description of one.

    This is the criterion that stops sentences creeping back in, which is the whole of
    #60: a mutation is an anchor and a replacement, never a sentence.
    """
    failures: list[str] = []
    for path in record_files():
        where = posix(path)
        text = read(path)
        starts = [match.start() for match in SECTION.finditer(text)]
        for position, start in enumerate(starts):
            end = starts[position + 1] if position + 1 < len(starts) else len(text)
            section = text[start:end]
            heading = section.split("\n", 1)[0].strip()
            if not JSON_BLOCK.search(section):
                failures.append(
                    f"{where} section {heading!r} holds no fenced JSON block, so it "
                    "describes a mutation instead of recording one. #60 is that a "
                    "description standing in for the thing itself produced a different "
                    "mutation and a different result."
                )
    assert not failures, "\n\n".join(failures)


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

ENFORCING_MECHANISMS = (
    "tests/test_suite_integrity.py",
    "plans/mutations/",
    "# unanchored:",
    "PYTHONDONTWRITEBYTECODE",
    "re.search",
    'match=r"^',
)


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
