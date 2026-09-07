"""The suite's check on itself.

Three failures in this repo reported success without exercising the thing they named,
and this module answers them with something that runs: GitHub issues #67, #65 and #60.

The duplicate-definition check refuses a test module that binds one name twice at
module level, because Python rebinds silently and pytest then collects only the last
definition, so the earlier test is deleted with nothing anywhere reporting an error.
The anchored-pin check refuses a ``pytest.raises(match=)`` whose pattern is not
anchored with ``^`` and carries no ``# unanchored:`` reason, because ``match=`` is an
``re.search`` and an unanchored pattern can be satisfied by a superstring that somebody
else's guard raised.

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
