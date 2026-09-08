"""Tests for the incompleteness signal: how old the ledger is and who has logged nothing.

Task 16 of plans/backlog.md, sharpened in
plans/tasks/16-incompleteness-signal.md. GitHub issue #17; issue #16 is a different,
already closed task.

``ledger_staleness`` is a pure function and reads no clock, so every test here hands it
a literal ``now=``. There is no monkeypatching, no freezegun and no new dependency:
total control over the answer comes from choosing the two instants a difference is
taken between, which is the whole reason the clock stays at ``web.py::_now()`` and this
module never reads one.

Every figure is asserted as an exact integer. The boundaries are asserted a microsecond
either side, in one test each, so a test named for a boundary runs both sides of it
rather than only the side that happens to pass, per rule (c) of
`.claude/rules/testing.md`.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import pathlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import splitwise_lite
from splitwise_lite import events as events_module
from splitwise_lite import staleness as staleness_module
from splitwise_lite.events import (
    Allocation,
    ExpenseEvent,
    ExpenseId,
    GroupId,
    InvalidEvent,
    MemberId,
    SettlementDecisionEvent,
    SettlementEvent,
    SettlementId,
    SettlementState,
)
from splitwise_lite.money import Currency, DomainError
from splitwise_lite.staleness import (
    QUIET_AFTER_DAYS,
    InvalidStaleness,
    MixedGroupLedger,
    Staleness,
    StalenessState,
    ledger_staleness,
)

AUD = Currency("AUD")

GROUP = GroupId("group-flat")
OTHER_GROUP = GroupId("group-holiday")

ALI = MemberId("ali")
BO = MemberId("bo")
CASS = MemberId("cass")

NOW = datetime(2026, 9, 7, 9, 30, tzinfo=timezone.utc)
"""The instant every test below passes as ``now=``.

Fixed rather than read from the clock, so each fixture's answer is written down in the
test. A domain test can do this because the function is pure. The endpoint tests in
tests/test_web_api.py cannot: the clock there is web.py's, and they replace ``web._now``
for the request, which is a stub over the one seam rather than a second clock read.

**Corrected 2026-09-08, after review of PR #83.** This paragraph used to end "the
endpoint tests in tests/test_web_api.py choose their events relative to the real clock
instead, because there the clock is web.py's and only the difference is theirs to
control". That is withdrawn, and it mattered more than the other two corrections in
this file because it was written as guidance and the next author would have followed
it. It describes the style plans/tasks/16-incompleteness-signal.md's decision 1
suggested, and that style cannot control the member ages: ``seed_group`` stamps every
member row with ``at()``, a fixed instant, so a quiet-member assertion written against
the real clock passes today and fails in a fortnight. Deviation 3 in that file's
Findings records the choice and the block comment at the head of the new web-api block
records the reason.
"""

SRC = Path(inspect.getfile(staleness_module))


def source() -> str:
    return SRC.read_text(encoding="utf-8")


def module_tree(module) -> ast.Module:
    """The module under test as a syntax tree, read from its own file."""
    return ast.parse(
        pathlib.Path(inspect.getfile(module)).read_text(encoding="utf-8")
    )


def days_before(days: float, *, moment: datetime = NOW) -> datetime:
    """``days`` whole days before ``moment``, to the microsecond."""
    return moment - timedelta(days=days)


def microseconds_after(when: datetime, count: int) -> datetime:
    return when + timedelta(microseconds=count)


def expense(
    event_id: str,
    *,
    when: datetime,
    recorded_by: MemberId = ALI,
    payer: MemberId | None = None,
    group_id: GroupId = GROUP,
) -> ExpenseEvent:
    """One expense, with everything this task does not read filled in.

    ``payer`` defaults to ``recorded_by`` so a fixture that cares about neither says
    nothing about either, and a fixture that cares says which.
    """
    paid_by = recorded_by if payer is None else payer
    return ExpenseEvent(
        id=ExpenseId(event_id),
        group_id=group_id,
        currency=AUD,
        payer_id=paid_by,
        total_cents=1000,
        allocations=(Allocation(paid_by, 1000),),
        description="",
        created_at=when,
        created_by=recorded_by,
    )


def settlement(
    event_id: str,
    *,
    when: datetime,
    group_id: GroupId = GROUP,
) -> SettlementEvent:
    """A claimed payment from Ali to Bo, born pending."""
    return SettlementEvent(
        id=SettlementId(event_id),
        group_id=group_id,
        currency=AUD,
        from_member_id=ALI,
        to_member_id=BO,
        amount_cents=500,
        created_at=when,
        created_by=ALI,
    )


def decision(event_id: str, *, settlement_id: str, when: datetime) -> SettlementDecisionEvent:
    """Bo's answer to one settlement. Carries no group id of its own, by design."""
    return SettlementDecisionEvent(
        id=event_id,
        settlement_id=SettlementId(settlement_id),
        decision=SettlementState.CONFIRMED,
        decided_by=BO,
        created_at=when,
    )


def roster(**ages: datetime) -> dict[MemberId, datetime]:
    """A member id to row-creation-instant mapping, in the order it is written."""
    return {MemberId(name): when for name, when in ages.items()}


OLD_ENOUGH = days_before(400)
"""Long enough before ``NOW`` that no threshold any test passes makes them new."""


# --- The module and its shape -----------------------------------------------


def test_the_module_docstring_says_what_it_computes_and_who_owns_the_clock() -> None:
    text = " ".join((staleness_module.__doc__ or "").split())
    for stated in (
        "reads no clock",
        "supplied by the caller",
        "imports from ``events``",
        "web.py",
    ):
        assert stated in text, stated


def test_the_package_re_exports_the_public_names_of_this_module() -> None:
    # The same shape as test_the_package_re_exports_the_public_names_of_both_modules in
    # tests/test_events.py. This is also what puts the new module inside the
    # Flask-absent guarantee: test_importing_the_package_does_not_import_the_framework
    # imports the package in a fresh interpreter, so once the package imports this
    # module that check reaches it, with no list of modules to maintain.
    for name in staleness_module.__all__:
        assert getattr(splitwise_lite, name) is getattr(staleness_module, name), name
        assert name in splitwise_lite.__all__, name


def declaration_order(name: str) -> tuple[int, str]:
    """The order this package's ``__all__`` lists are kept in.

    Not ``sorted()``. Measured on 2026-09-07 against all eight existing modules and
    the package root: constants first, then classes, then functions, each group
    alphabetical, which is the isort convention and is what every one of those nine
    lists already satisfies. Written down here because criterion 2 says "sorted" and
    a reader who took that literally would reorder nine lists.
    """
    if name.isupper():
        return (0, name)
    if name[:1].isupper():
        return (1, name)
    return (2, name)


def test_the_public_names_are_declared_in_the_order_this_package_keeps() -> None:
    for listed in (staleness_module.__all__, splitwise_lite.__all__):
        assert listed == sorted(listed, key=declaration_order)
    # And the key is the package's own convention rather than one invented here, which
    # is only worth asserting because it is what makes the two lines above a rule.
    for module in (events_module, staleness_module):
        assert module.__all__ == sorted(module.__all__, key=declaration_order)
    assert declaration_order("QUIET_AFTER_DAYS") < declaration_order("Staleness")
    assert declaration_order("Staleness") < declaration_order("ledger_staleness")


def test_the_threshold_is_one_module_constant_carrying_the_product_reason() -> None:
    assert QUIET_AFTER_DAYS == 7
    tree = ast.parse(source())
    annotated = [
        node
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "QUIET_AFTER_DAYS"
    ]
    assert len(annotated) == 1, "the threshold is declared once, at module level"
    assert ast.unparse(annotated[0].annotation) == "Final[int]"
    # And the reason is beside it, because a bare 7 is a number nobody can argue with.
    text = source()
    assert "weekly" in text
    assert "product judgement" in text


def test_the_threshold_is_high_enough_that_no_day_is_ever_rendered_singular() -> None:
    assert QUIET_AFTER_DAYS >= 2, (
        f"QUIET_AFTER_DAYS is {QUIET_AFTER_DAYS}. The day count is only ever rendered "
        "when it is at or above the threshold, so at 2 or more no singular form of "
        '"day" can be needed and there is no pluralisation code anywhere in this '
        "feature: not in staleness.py, not in web.py, not in app/index.html and not in "
        "app/app.js. Lowering this to 1 makes the two sentences in app/index.html read "
        '"for 1 days", and the fix is then four files of pluralisation, not a smaller '
        "number here."
    )


def test_the_number_seven_is_written_down_in_exactly_one_place_under_src() -> None:
    # A threshold spelled twice is two numbers with nothing forcing them to agree,
    # which is the duplicated-claim defect this repository has already paid for twice.
    package = SRC.parent
    holders: dict[str, list[int]] = {}
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and type(node.value) is int
            and node.value == 7
        ]
        if found:
            holders[path.name] = found
    assert holders == {"staleness.py": holders.get("staleness.py", [])}, holders
    assert len(holders["staleness.py"]) == 1, holders


# --- The state enum ---------------------------------------------------------


def test_the_state_enum_has_exactly_three_members_valued_as_their_names() -> None:
    assert [member.name for member in StalenessState] == ["NEVER", "FRESH", "STALE"]
    for member in StalenessState:
        assert member.value == member.name, member


def test_every_state_carries_a_line_saying_what_it_means() -> None:
    # Read from the source rather than from __doc__, because an Enum member has no
    # docstring attribute: the line under each member is the documentation, and a
    # member added without one would otherwise be documented by nobody.
    tree = ast.parse(source())
    enum = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "StalenessState"
    )
    documented: dict[str, str] = {}
    body = enum.body
    for index, node in enumerate(body):
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        assert isinstance(target, ast.Name)
        following = body[index + 1] if index + 1 < len(body) else None
        assert (
            isinstance(following, ast.Expr)
            and isinstance(following.value, ast.Constant)
            and isinstance(following.value.value, str)
        ), f"{target.id} carries no line saying what it means"
        documented[target.id] = following.value.value
    assert set(documented) == {"NEVER", "FRESH", "STALE"}
    # NEVER is the distinction the whole three-valued design rests on, so its line has
    # to say "unknown" and not "none" or "zero".
    assert "no expense has ever been recorded" in documented["NEVER"]
    assert "unknown" in documented["NEVER"]


# --- The result type --------------------------------------------------------


def test_the_result_is_a_frozen_slotted_dataclass_of_exactly_four_fields() -> None:
    assert dataclasses.is_dataclass(Staleness)
    assert Staleness.__dataclass_params__.frozen is True
    assert "__slots__" in vars(Staleness)
    assert [field.name for field in dataclasses.fields(Staleness)] == [
        "state",
        "days_since_last_expense",
        "quiet_member_ids",
        "quiet_after_days",
    ]


def test_the_two_refusals_are_domain_errors_in_the_ledgers_own_family() -> None:
    assert issubclass(InvalidStaleness, DomainError)
    assert issubclass(InvalidStaleness, InvalidEvent)
    assert issubclass(MixedGroupLedger, InvalidStaleness)


def test_a_never_result_carrying_a_day_count_is_refused() -> None:
    with pytest.raises(
        InvalidStaleness,
        match=r"^Staleness days_since_last_expense must be None when the state is NEVER",
    ):
        Staleness(
            state=StalenessState.NEVER,
            days_since_last_expense=0,
            quiet_member_ids=(),
            quiet_after_days=QUIET_AFTER_DAYS,
        )


def test_a_known_age_carrying_no_day_count_is_refused() -> None:
    # The other direction of the same invariant, and the one that would let a payload
    # say "stale, and I do not know how stale", which is issue #44's shape exactly.
    for state in (StalenessState.FRESH, StalenessState.STALE):
        with pytest.raises(
            InvalidStaleness,
            match=(
                r"^Staleness days_since_last_expense must be an int when the state is "
                r"not NEVER"
            ),
        ):
            Staleness(
                state=state,
                days_since_last_expense=None,
                quiet_member_ids=(),
                quiet_after_days=QUIET_AFTER_DAYS,
            )


def test_a_never_result_naming_a_quiet_member_is_refused() -> None:
    with pytest.raises(
        InvalidStaleness,
        match=r"^Staleness quiet_member_ids must be empty when the state is NEVER",
    ):
        Staleness(
            state=StalenessState.NEVER,
            days_since_last_expense=None,
            quiet_member_ids=(ALI,),
            quiet_after_days=QUIET_AFTER_DAYS,
        )


def test_a_result_whose_fields_agree_is_accepted_in_all_three_states() -> None:
    # The positive control for the three refusals above: the invariants refuse a
    # contradiction and admit every shape the function itself can build.
    assert Staleness(
        state=StalenessState.NEVER,
        days_since_last_expense=None,
        quiet_member_ids=(),
        quiet_after_days=QUIET_AFTER_DAYS,
    ).state is StalenessState.NEVER
    for state in (StalenessState.FRESH, StalenessState.STALE):
        result = Staleness(
            state=state,
            days_since_last_expense=3,
            quiet_member_ids=(ALI,),
            quiet_after_days=QUIET_AFTER_DAYS,
        )
        assert result.days_since_last_expense == 3
        assert result.quiet_member_ids == (ALI,)


# --- The signature ----------------------------------------------------------


def test_now_is_keyword_only_and_has_no_default() -> None:
    # No default, so a caller cannot forget to supply it and silently get whatever a
    # clock read inside here would have returned. There is no clock read inside here.
    parameters = inspect.signature(ledger_staleness).parameters
    assert list(parameters) == ["events", "members", "now", "quiet_after_days"]
    assert parameters["now"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["now"].default is inspect.Parameter.empty
    assert parameters["quiet_after_days"].default == QUIET_AFTER_DAYS
    with pytest.raises(TypeError):
        ledger_staleness([], {})


def test_the_function_is_handed_no_group_id_to_check_against() -> None:
    # Criterion 10: the group scope is a documented precondition, and both call sites
    # obtain their events already filtered. Criterion 10a is what happens when the
    # precondition is broken in the one way that is detectable from here.
    assert "group_id" not in inspect.signature(ledger_staleness).parameters


def test_a_naive_now_is_refused_the_way_an_event_refuses_one() -> None:
    with pytest.raises(
        InvalidStaleness,
        match=r"^ledger_staleness now must be timezone-aware, got naive ",
    ):
        ledger_staleness([], {}, now=datetime(2026, 9, 7, 9, 30))


def test_a_naive_member_timestamp_is_refused_and_names_the_member() -> None:
    with pytest.raises(
        InvalidStaleness,
        match=r"^ledger_staleness members\['ali'\] must be timezone-aware, got naive ",
    ):
        ledger_staleness([], {ALI: datetime(2026, 9, 1, 9, 30)}, now=NOW)


def test_a_now_that_is_not_a_datetime_is_a_type_error_not_a_refusal() -> None:
    # A wrong Python type is a programming error, not rejected input, which is the
    # split events.py already makes.
    with pytest.raises(TypeError, match=r"^ledger_staleness now must be a datetime"):
        ledger_staleness([], {}, now="2026-09-07T09:30:00+00:00")


def test_a_now_in_another_zone_is_read_as_the_instant_it_names() -> None:
    # Accepted rather than rejected, so two readers in two zones handing over the same
    # instant get the same figure. Nothing is converted: a difference between two aware
    # instants is the same whatever zone either one spells itself in, which is why
    # _require_instant returns the value unchanged and only the subtraction matters.
    #
    # **Corrected 2026-09-08, after review of PR #83.** This comment used to read
    # "Normalised to UTC rather than rejected, exactly as events._require_utc does".
    # The assertion below was right and that reason was backwards: _require_instant's
    # own docstring says "Nothing is converted", and says why events._require_utc does
    # normalise, which is that what it guards is stored. Nothing here is stored.
    ledger = [expense("e1", when=days_before(9))]
    elsewhere = NOW.astimezone(timezone(timedelta(hours=10)))
    assert elsewhere.utcoffset() == timedelta(hours=10)
    here = ledger_staleness(ledger, {}, now=NOW)
    there = ledger_staleness(ledger, {}, now=elsewhere)
    assert there == here
    assert there.days_since_last_expense == 9


# --- No clock, and the ordering rule ----------------------------------------


CLOCK_READS = ("now(", "utcnow(", "today(", "time.time", "monotonic")
"""The five spellings of a clock read this module refuses, declared **once**.

Once, and referenced by both the ban and its control below, because the first version
of that control carried its own copy of this list and so asserted five hardcoded
strings against five other hardcoded strings. It never read ``staleness.py`` and never
ran the ban, and deleting an entry from the real list left it green while a
parametrised case silently vanished. That is how this repository once lost four tests
unnoticed, and one list is what stops it here.
"""


def clock_reads_in(text: str) -> set[str]:
    """Every forbidden spelling present in ``text``.

    The one checking function. The ban calls it and so does its control, so the control
    exercises the shipped check rather than a description of it.
    """
    return {spelling for spelling in CLOCK_READS if spelling in text}


def with_a_smuggled_line(text: str, statement: str) -> str:
    """``text`` with ``statement`` inserted into a real function body.

    Injected into the shipped source at a real anchor rather than concatenated onto the
    end, and the result is parsed, so what the control feeds the ban is a module that
    still compiles and not a string that happens to hold a token. This is the shape
    ``tests/test_balances.py``'s ``_with_a_smuggled_line`` uses, which injects into the
    real tree and asserts the real checking function reports it.
    """
    anchor = '    moment = _require_instant(now, "ledger_staleness now")\n'
    assert text.count(anchor) == 1, anchor
    smuggled = text.replace(anchor, anchor + statement + "\n")
    ast.parse(smuggled)
    return smuggled


@pytest.mark.parametrize("forbidden", CLOCK_READS)
def test_the_module_never_reads_the_clock(forbidden: str) -> None:
    # The same shape tests/test_store.py:1503 already uses, and deliberately NARROWER
    # than balances.py's purity proof: that one resolves aliases back to the module
    # they name and so forbids the name `datetime` at runtime altogether, which a
    # threshold expressed as a timedelta would fire. This rule forbids clock *reads*
    # and permits clock *arithmetic*, because subtracting two instants is the whole
    # job, and permitting it is what this narrower rule buys.
    #
    # The module does name `datetime` at runtime, in exactly one place: the isinstance
    # in _require_instant's type guard, which criterion 7 asks for, because refusing a
    # naive value the way events._require_utc does means naming the class. Nothing else
    # does: no timedelta is constructed anywhere and `(now - created_at).days` names no
    # class. An isinstance is not a clock read, so the rule above is unaffected.
    #
    # **Corrected 2026-09-08, after review of PR #83.** This comment used to read "As
    # implemented the module needs no runtime `datetime` name at all: `(now -
    # created_at).days` names no class, so the one import here is annotation only and
    # carries the same exemption balances.py's does." That is withdrawn as false.
    # staleness.py's own header and deviation 4 of the task Findings both state it
    # correctly, so this file was the one place in the PR still repeating a prediction
    # the implementation had already disproved, and two comments in one branch
    # disagreed about one fact.
    assert forbidden not in clock_reads_in(source()), forbidden


# Five real clock reads, each written the way somebody would actually write it. These
# are provocations rather than a second copy of CLOCK_READS: they are statements, and
# which spelling catches which is measured below rather than assumed.
SMUGGLED_READS = (
    "    moment = datetime.now(timezone.utc)",
    "    moment = _Instant.utcnow()",
    "    stamp = date.today()",
    "    seconds = time.time()",
    "    ticks = perf.monotonic()",
)


@pytest.mark.parametrize("statement", SMUGGLED_READS, ids=lambda s: s.strip())
def test_the_clock_ban_catches_a_read_smuggled_into_the_real_module(
    statement: str,
) -> None:
    """The ban is worth only what it catches, so this catches it catching.

    Each case injects a real read into the real ``staleness.py`` and asserts the same
    function the ban runs reports it. It reads the shipped source, it runs the shipped
    check, and it shares the shipped list.

    This replaces a control that did none of those things. The first version asserted
    five hardcoded smuggled strings against a hardcoded copy of the ban list, which is
    a tautology over two literals: it proved that ``_Instant.utcnow()`` contains
    ``utcnow(``, which is true by construction and independent of the module under
    test. QA measured it, and deleting an entry from the real ban left it at
    ``6 passed, 52 deselected``. It is the same copying error as mutation 5, one test
    away: a two-part precedent copied in name but not in substance.
    """
    shipped = source()
    # The shipped module is clean, so a hit below is the injection and not the module.
    assert clock_reads_in(shipped) == set()
    assert clock_reads_in(with_a_smuggled_line(shipped, statement)) != set(), statement


def test_every_spelling_in_the_ban_is_measured_for_what_it_alone_catches() -> None:
    """Which entries of the ban are load-bearing, measured rather than assumed.

    A ban entry that catches nothing no other entry catches is documentation, not
    coverage, and the difference decides what deleting it costs. Four of the five here
    are load-bearing: delete ``today(``, ``time.time`` or ``monotonic`` and the
    matching case above goes red, because nothing else in the list catches its
    provocation.

    ``utcnow(`` is the exception and it is **redundant, measured**: every string
    containing ``utcnow(`` contains ``now(``, so ``now(`` catches
    ``_Instant.utcnow()`` on its own and deleting ``utcnow(`` costs no coverage at all.
    That is why the control above cannot be made to fail on that particular deletion
    without pinning this list against a copy of itself, which is the defect it was
    written to remove. It stays in the list because criterion 8 names all five and
    because a reader searching for ``utcnow`` should find it here; this test is what
    stops it being mistaken for coverage. The same redundancy is in
    ``tests/test_store.py``'s list, which this one was modelled on.
    """
    alone: dict[str, list[str]] = {}
    for spelling in CLOCK_READS:
        alone[spelling] = [
            statement
            for statement in SMUGGLED_READS
            if spelling in statement
            and not any(
                other in statement for other in CLOCK_READS if other != spelling
            )
        ]
    load_bearing = {spelling for spelling, cases in alone.items() if cases}
    assert load_bearing == {"now(", "today(", "time.time", "monotonic"}, alone
    assert "utcnow(" in CLOCK_READS, (
        "utcnow( has been removed from CLOCK_READS. That is not a silent loss of "
        "coverage, because it is redundant with now( and this test is what measures "
        "that. It is still a change to a criterion: criterion 8 of "
        "plans/tasks/16-incompleteness-signal.md names all five spellings, so taking "
        "one out is a decision to record and not a tidy. This assertion exists so "
        "that decision cannot be made by deleting a line."
    )
    assert alone["utcnow("] == [], alone["utcnow("]
    # And the redundancy is exactly the superstring relation claimed above, not some
    # accident of these five provocations.
    assert "now(" in "utcnow("


def annotation_nodes(tree: ast.Module) -> set[int]:
    """Every node sitting inside an annotation, by ``id``.

    ``from __future__ import annotations`` is in force in the module under test, so an
    annotation is a string the interpreter never evaluates: nothing written in one can
    reach anything at run time. That is the only reason the check below may skip them,
    and it is the same exemption tests/test_balances.py carries for the same reason.
    """
    inside: set[int] = set()
    for node in ast.walk(tree):
        roots = []
        if isinstance(node, (ast.AnnAssign, ast.arg)) and node.annotation is not None:
            roots.append(node.annotation)
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.returns is not None
        ):
            roots.append(node.returns)
        for root in roots:
            inside.update(id(child) for child in ast.walk(root))
    return inside


def runtime_names(tree: ast.Module) -> set[str]:
    """Every name the module can reach when it runs, annotations excepted.

    Names only, never source text. A substring search would be satisfied by the import
    line alone, which is exactly the defect this function exists to avoid: an import
    that is present and never called is what the mutation below produces, and a check
    that reads text cannot tell the two apart. ``ast.alias`` is not an ``ast.Name``, so
    an import contributes nothing here and only a use does.
    """
    skip = annotation_nodes(tree)
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and id(node) not in skip
    } | {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and id(node) not in skip
    }


def test_the_newest_expense_is_chosen_with_the_ordering_key_events_py_defines() -> None:
    """Not re-derived here: one tie-break rule, shared by every consumer of the log.

    Three assertions, and the reason there are three is worth stating, because this
    test shipped in review with only the last of them and **could not fail**. The
    mutation that replaces ``max(expenses, key=ordering_key)`` with ``expenses[-1]``
    left it green: the import still resolves, so the identity still holds, and the
    module simply never calls what it imported. An identity check on an import is
    evidence that two names are the same object, and nothing at all about whether
    either is used. `plans/mutations/16-incompleteness-signal.md` records that run,
    and this is the repair.

    So, in the order they bite:

    * **the behaviour**, over a list whose newest expense is not its last element,
      which is what refuses "just take the end of the list";
    * **the name reached at run time**, read off the module's own syntax tree rather
      than out of its text, because a text search is satisfied by the import line and
      would repeat the defect it is meant to catch;
    * **the identity**, which is what criterion 11 asks for and which stops the name
      being rebound to a local re-derivation of the same rule.

    The tie-break itself is deliberately not asserted through the result, and that is
    the honest reason the structural half has to exist. Two expenses sharing an instant
    have the same ``created_at``, so which of them is "newest" cannot change the number
    of days this function returns: ``key=ordering_key`` and
    ``key=lambda expense: expense.created_at`` are indistinguishable from the outside.
    Only naming the shared function tells them apart, and only the syntax tree tells a
    named function from an imported one that is never called.
    """
    # A list whose newest expense is neither its last element nor its first.
    ledger = [
        expense("e1", when=days_before(9)),
        expense("e3", when=days_before(2)),
        expense("e2", when=days_before(30)),
    ]
    assert ledger_staleness(ledger, {}, now=NOW).days_since_last_expense == 2
    # And the answer does not depend on the order the caller happened to hand them
    # over in, which is the property a maximum has and an end-of-list read does not.
    for rotation in range(len(ledger)):
        rotated = ledger[rotation:] + ledger[:rotation]
        assert ledger_staleness(rotated, {}, now=NOW).days_since_last_expense == 2

    assert "ordering_key" in runtime_names(module_tree(staleness_module))
    assert staleness_module.ordering_key is events_module.ordering_key


def test_the_runtime_name_check_can_tell_a_used_import_from_an_unused_one() -> None:
    """The positive control for the middle assertion above.

    A green check is worth nothing until it has been shown to refuse the thing it
    claims to refuse, and this one exists because its absence let a test ship that
    could not fail. Two modules, one importing and calling and one importing only: the
    check must accept the first and refuse the second.
    """
    used = ast.parse(
        "from .events import ordering_key\n"
        "def newest(events):\n"
        "    return max(events, key=ordering_key)\n"
    )
    unused = ast.parse(
        "from .events import ordering_key\n"
        "def newest(events):\n"
        "    return events[-1]\n"
    )
    assert "ordering_key" in runtime_names(used)
    assert "ordering_key" not in runtime_names(unused)
    # And the text search that would have passed both, which is the repair this test
    # refuses: it is satisfied by the import line in either module.
    assert "ordering_key" in ast.unparse(unused)


def test_the_newest_expense_is_the_maximal_one_and_not_the_last_in_the_list() -> None:
    # The behavioural half of the criterion above: a list whose newest expense is not
    # its last element. Reading the last element instead would answer 2.
    ledger = [
        expense("e1", when=days_before(9)),
        expense("e3", when=days_before(2)),
        expense("e2", when=days_before(30)),
    ]
    assert ledger_staleness(ledger, {}, now=NOW).days_since_last_expense == 2


def test_a_tie_on_the_instant_is_broken_by_the_id_and_changes_no_figure() -> None:
    # Two expenses share an instant, so the ordering key's tie-break decides which one
    # is "newest". Both carry the same instant, so the figure is the same either way,
    # which is the point: the tie-break is about which event, never about the answer.
    when = days_before(4)
    ledger = [expense("e-b", when=when), expense("e-a", when=when)]
    assert ledger_staleness(ledger, {}, now=NOW).days_since_last_expense == 4
    assert ledger_staleness(list(reversed(ledger)), {}, now=NOW) == ledger_staleness(
        ledger, {}, now=NOW
    )


def test_the_input_may_be_any_iterable_and_is_consumed_once() -> None:
    ledger = (event for event in [expense("e1", when=days_before(9))])
    assert ledger_staleness(ledger, {}, now=NOW).days_since_last_expense == 9


def test_the_callers_own_list_is_neither_mutated_nor_reordered() -> None:
    ledger = [expense("e1", when=days_before(9)), expense("e2", when=days_before(30))]
    before = list(ledger)
    ledger_staleness(ledger, {}, now=NOW)
    assert ledger == before


# --- The group-scope precondition -------------------------------------------


def test_a_ledger_holding_two_groups_is_refused_rather_than_folded() -> None:
    with pytest.raises(
        MixedGroupLedger,
        match=r"^ledger_staleness events name more than one group: ",
    ):
        ledger_staleness(
            [
                expense("e1", when=days_before(9)),
                expense("e2", when=days_before(2), group_id=OTHER_GROUP),
            ],
            {},
            now=NOW,
        )


def test_a_two_group_ledger_is_refused_instead_of_read_as_fresher_than_it_is() -> None:
    # The reason the refusal is worth having: the foreign expense is the newest, so a
    # function that folded the two together would answer 2 where this group's own
    # newest expense is 9 days old. A plausible wrong number is worse than a
    # traceback, and both are worse than a named refusal.
    own = expense("e1", when=days_before(9))
    foreign = expense("e2", when=days_before(2), group_id=OTHER_GROUP)
    assert ledger_staleness([own], {}, now=NOW).days_since_last_expense == 9
    assert ledger_staleness([foreign], {}, now=NOW).days_since_last_expense == 2
    with pytest.raises(MixedGroupLedger):
        ledger_staleness([own, foreign], {}, now=NOW)


def test_a_settlement_from_another_group_is_refused_on_the_same_terms() -> None:
    with pytest.raises(MixedGroupLedger):
        ledger_staleness(
            [
                expense("e1", when=days_before(9)),
                settlement("s1", when=days_before(1), group_id=OTHER_GROUP),
            ],
            {},
            now=NOW,
        )


def test_a_decision_carries_no_group_and_never_trips_the_scope_refusal() -> None:
    # SettlementDecisionEvent has no group_id of its own by design (events.py), so the
    # check reads expenses and settlements and ignores decisions, which is the same
    # asymmetry balances.derive_balances lives with.
    result = ledger_staleness(
        [
            expense("e1", when=days_before(9)),
            settlement("s1", when=days_before(1)),
            decision("d1", settlement_id="s1", when=days_before(1)),
        ],
        {},
        now=NOW,
    )
    assert result.days_since_last_expense == 9


def test_one_groups_events_are_computed_and_never_refused() -> None:
    # The positive control for the three refusals above: the precondition holding is
    # the ordinary case, and it computes.
    result = ledger_staleness([expense("e1", when=days_before(9))], {}, now=NOW)
    assert result.state is StalenessState.STALE


# --- What it computes: the age ----------------------------------------------


def test_a_ledger_with_no_expense_at_all_is_never_whatever_the_roster_holds() -> None:
    result = ledger_staleness([], roster(ali=OLD_ENOUGH, bo=OLD_ENOUGH), now=NOW)
    assert result.state is StalenessState.NEVER
    assert result.days_since_last_expense is None
    assert result.quiet_member_ids == ()
    assert result.quiet_after_days == QUIET_AFTER_DAYS


def test_a_ledger_of_settlements_and_decisions_alone_is_still_never() -> None:
    result = ledger_staleness(
        [
            settlement("s1", when=days_before(1)),
            decision("d1", settlement_id="s1", when=days_before(1)),
        ],
        roster(ali=OLD_ENOUGH, bo=OLD_ENOUGH),
        now=NOW,
    )
    assert result.state is StalenessState.NEVER
    assert result.days_since_last_expense is None
    assert result.quiet_member_ids == ()


def test_the_age_is_whole_elapsed_days_since_the_newest_expense() -> None:
    for elapsed, expected in ((0, 0), (1, 1), (6, 6), (9, 9), (400, 400)):
        result = ledger_staleness(
            [expense("e1", when=days_before(elapsed))], {}, now=NOW
        )
        assert result.days_since_last_expense == expected, elapsed


def test_a_part_day_is_floored_rather_than_rounded_up() -> None:
    # Elapsed 24-hour periods, not calendar days: somebody who recorded at 23:00 last
    # night and looks at 08:00 today has elapsed 9 hours, so 0, where a calendar count
    # would say "yesterday". It errs toward not nagging, which is the right direction
    # for a signal whose failure mode is being ignored.
    result = ledger_staleness([expense("e1", when=days_before(6.9))], {}, now=NOW)
    assert result.days_since_last_expense == 6
    assert result.state is StalenessState.FRESH


def test_a_recent_settlement_does_not_reset_the_age_of_the_newest_expense() -> None:
    # The substance of "settlements do not reset the clock". A flat that settles up
    # but stops logging groceries is precisely the failure mode the signal is for, so
    # a settlement an hour old leaves a nine-day-old ledger reading nine days old.
    ledger = [
        expense("e1", when=days_before(9)),
        settlement("s1", when=days_before(1 / 24)),
        decision("d1", settlement_id="s1", when=days_before(1 / 24)),
    ]
    result = ledger_staleness(ledger, {}, now=NOW)
    assert result.days_since_last_expense == 9
    assert result.state is StalenessState.STALE


def test_exactly_the_threshold_elapsed_is_stale_and_a_microsecond_less_is_fresh() -> None:
    # The comparison is >=, so the figure ticks over on the anniversary of the instant
    # and not at any midnight. Both sides in one test, because a test named for a
    # boundary that runs one side of it could not fail for the reason its name gives.
    at_boundary = ledger_staleness(
        [expense("e1", when=days_before(QUIET_AFTER_DAYS))], {}, now=NOW
    )
    assert at_boundary.days_since_last_expense == QUIET_AFTER_DAYS
    assert at_boundary.state is StalenessState.STALE

    inside = ledger_staleness(
        [
            expense(
                "e1",
                when=microseconds_after(days_before(QUIET_AFTER_DAYS), 1),
            )
        ],
        {},
        now=NOW,
    )
    assert inside.days_since_last_expense == QUIET_AFTER_DAYS - 1
    assert inside.state is StalenessState.FRESH


def test_a_future_expense_reads_as_zero_days_and_never_as_a_negative() -> None:
    # timedelta.days floors toward negative infinity, so half a day in the future is
    # -1, and "recorded minus one days ago" is nonsense on a screen. web.py stamps
    # created_at from its own clock, so this should be unreachable through the API,
    # but store.py accepts timestamps that disagree because phone clocks disagree, and
    # a hand-edited database or a future setup_group.py run would reach it.
    one_microsecond = ledger_staleness(
        [expense("e1", when=microseconds_after(NOW, 1))], {}, now=NOW
    )
    assert one_microsecond.days_since_last_expense == 0
    assert one_microsecond.state is StalenessState.FRESH

    far_ahead = ledger_staleness(
        [expense("e1", when=days_before(-40))], {}, now=NOW
    )
    assert far_ahead.days_since_last_expense == 0
    assert far_ahead.state is StalenessState.FRESH


def test_the_state_is_stale_at_or_above_the_threshold_and_fresh_below_it() -> None:
    for elapsed, expected in (
        (0, StalenessState.FRESH),
        (6, StalenessState.FRESH),
        (7, StalenessState.STALE),
        (8, StalenessState.STALE),
    ):
        result = ledger_staleness(
            [expense("e1", when=days_before(elapsed))], {}, now=NOW
        )
        assert result.state is expected, elapsed


def test_the_caller_may_vary_the_threshold_and_the_result_says_which_it_used() -> None:
    # A parameter with a constant default is what a test needs: nothing here
    # monkeypatches a module constant, and the shipped answer stays one number in one
    # place. Not a query parameter, and not configuration: see decision 2.
    ledger = [expense("e1", when=days_before(9))]
    strict = ledger_staleness(ledger, {}, now=NOW, quiet_after_days=3)
    assert strict.state is StalenessState.STALE
    assert strict.quiet_after_days == 3
    lenient = ledger_staleness(ledger, {}, now=NOW, quiet_after_days=14)
    assert lenient.state is StalenessState.FRESH
    assert lenient.quiet_after_days == 14
    # And the age itself does not move with the threshold: one is a measurement and
    # the other is a product rule applied to it.
    assert strict.days_since_last_expense == lenient.days_since_last_expense == 9


# --- What it computes: who is quiet -----------------------------------------


def test_a_quiet_member_has_entered_nothing_and_has_been_here_all_window() -> None:
    result = ledger_staleness(
        [expense("e1", when=days_before(2), recorded_by=ALI)],
        roster(ali=OLD_ENOUGH, bo=OLD_ENOUGH),
        now=NOW,
    )
    # Ali entered something inside the window and Bo entered nothing at all.
    assert result.quiet_member_ids == (BO,)
    assert result.state is StalenessState.FRESH


def test_an_expense_older_than_the_window_does_not_keep_its_recorder_off_the_list() -> None:
    result = ledger_staleness(
        [expense("e1", when=days_before(9), recorded_by=ALI)],
        roster(ali=OLD_ENOUGH, bo=OLD_ENOUGH),
        now=NOW,
    )
    assert result.quiet_member_ids == (ALI, BO)
    assert result.state is StalenessState.STALE


def test_a_member_who_paid_but_did_not_enter_it_is_still_listed_as_quiet() -> None:
    # Membership of this list is by created_by and never by payer_id. The consequence
    # has to be said out loud because it will surprise somebody: a flatmate who pays
    # for everything and never opens the app is listed, because somebody else entered
    # it. That is correct for the risk being mitigated, which is that nothing gets
    # recorded, and it is why the copy states the bare fact rather than implying the
    # person owes anybody data.
    ledger = [expense("e1", when=days_before(2), recorded_by=ALI, payer=BO)]
    result = ledger_staleness(ledger, roster(ali=OLD_ENOUGH, bo=OLD_ENOUGH), now=NOW)
    assert result.quiet_member_ids == (BO,)
    # And the distinction is real rather than a coincidence of this fixture: swap the
    # two fields over and the answer swaps with them.
    swapped = [expense("e1", when=days_before(2), recorded_by=BO, payer=ALI)]
    assert ledger_staleness(
        swapped, roster(ali=OLD_ENOUGH, bo=OLD_ENOUGH), now=NOW
    ).quiet_member_ids == (ALI,)


def test_a_member_who_joined_inside_the_window_is_not_named(
) -> None:
    # Listing somebody who has not had time to log anything is #44's mistake: an
    # absence of data reported as a finding. On a group set up yesterday nobody is
    # quiet, and the "nothing recorded yet" sentence carries the whole message.
    result = ledger_staleness(
        [expense("e1", when=days_before(9), recorded_by=ALI)],
        roster(ali=OLD_ENOUGH, bo=days_before(1)),
        now=NOW,
    )
    assert result.quiet_member_ids == (ALI,)


def test_a_group_set_up_inside_the_window_names_nobody_at_all() -> None:
    result = ledger_staleness(
        [expense("e1", when=days_before(9), recorded_by=ALI)],
        roster(ali=days_before(2), bo=days_before(2)),
        now=NOW,
    )
    assert result.quiet_member_ids == ()
    # And the age signal still speaks, which is the half of the feature that can.
    assert result.state is StalenessState.STALE
    assert result.days_since_last_expense == 9


def test_a_ledger_with_no_expense_names_nobody_however_old_the_roster_is() -> None:
    # Naming five people for one fact the sentence above them already states is noise,
    # and it reads as an accusation of five people for one circumstance.
    result = ledger_staleness([], roster(ali=OLD_ENOUGH, bo=OLD_ENOUGH), now=NOW)
    assert result.state is StalenessState.NEVER
    assert result.quiet_member_ids == ()


def test_a_member_created_exactly_the_window_ago_is_quiet_and_later_is_not() -> None:
    # Both sides of the other boundary, in one test, for the reason the age boundary
    # gives: `member_created_at <= now - quiet_after_days` is a >= on elapsed days.
    boundary = days_before(QUIET_AFTER_DAYS)
    assert ledger_staleness(
        [], roster(ali=boundary), now=NOW, quiet_after_days=QUIET_AFTER_DAYS
    ).state is StalenessState.NEVER
    ledger = [expense("e1", when=days_before(1), recorded_by=CASS)]
    at_boundary = ledger_staleness(ledger, roster(ali=boundary), now=NOW)
    assert at_boundary.quiet_member_ids == (ALI,)
    inside = ledger_staleness(
        ledger, roster(ali=microseconds_after(boundary, 1)), now=NOW
    )
    assert inside.quiet_member_ids == ()


def test_the_quiet_order_is_the_order_the_roster_was_handed_in() -> None:
    # Pinned with a mapping whose insertion order is not sorted order, so the
    # guarantee is behaviour and not a comment. web.py hands over a mapping built from
    # store.list_members, which is roster order.
    unsorted = roster(cass=OLD_ENOUGH, ali=OLD_ENOUGH, bo=OLD_ENOUGH)
    assert list(unsorted) != sorted(unsorted)
    result = ledger_staleness(
        [expense("e1", when=days_before(9), recorded_by=MemberId("dee"))],
        unsorted,
        now=NOW,
    )
    assert result.quiet_member_ids == (CASS, ALI, BO)


def test_a_member_the_ledger_has_never_seen_can_be_quiet() -> None:
    result = ledger_staleness(
        [expense("e1", when=days_before(2), recorded_by=ALI)],
        roster(zed=OLD_ENOUGH),
        now=NOW,
    )
    assert result.quiet_member_ids == (MemberId("zed"),)


def test_a_recorder_the_roster_does_not_know_is_ignored_rather_than_raising() -> None:
    # The case an operator creates by adding a member row late, or by pointing this at
    # a window of the log older than the roster. It must not turn a display signal
    # into a 500.
    result = ledger_staleness(
        [expense("e1", when=days_before(2), recorded_by=MemberId("ghost"))],
        roster(ali=OLD_ENOUGH),
        now=NOW,
    )
    assert result.quiet_member_ids == (ALI,)
    assert result.days_since_last_expense == 2


def test_an_empty_roster_names_nobody_and_still_reports_the_age() -> None:
    result = ledger_staleness([expense("e1", when=days_before(9))], {}, now=NOW)
    assert result.quiet_member_ids == ()
    assert result.state is StalenessState.STALE
    assert result.days_since_last_expense == 9


def test_the_window_the_quiet_list_uses_is_the_threshold_the_caller_passed() -> None:
    ledger = [expense("e1", when=days_before(5), recorded_by=ALI)]
    members = roster(ali=OLD_ENOUGH, bo=OLD_ENOUGH)
    assert ledger_staleness(
        ledger, members, now=NOW, quiet_after_days=3
    ).quiet_member_ids == (ALI, BO)
    assert ledger_staleness(
        ledger, members, now=NOW, quiet_after_days=14
    ).quiet_member_ids == (BO,)


# --- The docstrings the next reader depends on ------------------------------


def test_the_docstrings_state_every_decision_this_module_makes() -> None:
    # Criterion 9: each of these is stated once, where it is implemented, because a
    # claim written into four documents and pinned by none left four documents false
    # with nothing going red.
    text = " ".join(
        " ".join((holder.__doc__ or "").split())
        for holder in (
            staleness_module,
            StalenessState,
            Staleness,
            ledger_staleness,
            InvalidStaleness,
            MixedGroupLedger,
        )
    )
    for stated in (
        # The newest ExpenseEvent only, and why a settlement does not reset it.
        "newest ``ExpenseEvent``",
        "settles up but stops logging",
        # The elapsed rule and its boundary.
        "elapsed 24-hour periods",
        "``>=``",
        # The clamp, and why a future timestamp is reachable at all.
        "clamped",
        "Phone clocks disagree",
        # The order of the result.
        "iteration order",
        # The proxy, named as a proxy.
        "row was created",
        "not a join date",
        "open question 1",
        # The precondition, and what a breach of it costs.
        "already scoped to one group",
        "fresher than it is",
    ):
        assert stated in text, stated
