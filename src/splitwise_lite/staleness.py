"""The incompleteness signal: how old a ledger is, and who has entered nothing into it.

The spec's largest risk is not the arithmetic. It is that "a half-filled ledger is
worse than memory, because it looks authoritative while being wrong". Every other
figure this package derives is a confident answer; this module is the one that says how
much the answer does not know. It computes two things from a ledger and a roster, both
on read and neither stored:

* how many whole elapsed days it has been since the newest expense was recorded, or
  that nothing has ever been recorded, which is its own answer and not a zero
* which members have entered no expense recently, excluding anybody who has not been
  in the group long enough to have had the chance

**It reads no clock.** ``now`` is supplied by the caller, keyword-only and with no
default, so forgetting it is a ``TypeError`` rather than a silently different answer.
The one clock read in this codebase is ``_now`` in ``web.py``, cached per request, and
``tests/test_web_api.py::test_the_clock_is_read_once_and_only_in_one_place`` holds it
there. Every figure below is therefore a pure function of its inputs: the same ledger
and the same instant always give the same answer, in any order and in any process.

**Nothing here is a notification.** This is a display signal. It moves no balance,
appends no event, stores nothing and tells nobody: people find it by opening a screen.

Dependency direction: this module imports from ``events`` and from nothing else in the
package, and nothing in the package imports it except ``web.py``, which is the only
module that has an instant to hand it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
# Imported under another name for the reason balances.py does it: an alias is not a
# hiding place, and the name is here to be read rather than to be asked the time.
#
# The purity rule over this module is deliberately NARROWER than balances.py's.
# balances.py forbids the runtime name ``datetime`` altogether, resolving aliases back
# to the module they name, and a threshold expressed as a ``timedelta`` there would
# fire it. Here the rule is
# ``tests/test_staleness.py::test_the_module_never_reads_the_clock``, which forbids
# clock *reads* and permits clock *arithmetic*, because subtracting two instants is the
# whole job. This name is used at runtime in exactly one place, ``_require_instant``'s
# type guard, and for nothing else: no arithmetic below names a class, because
# ``(later - earlier).days`` does not, and no threshold below is a ``timedelta``.
from datetime import datetime as _Instant
from enum import Enum
from typing import Final

from .events import (
    ExpenseEvent,
    InvalidEvent,
    LedgerEvent,
    MemberId,
    SettlementEvent,
    ordering_key,
)

__all__ = [
    "QUIET_AFTER_DAYS",
    "InvalidStaleness",
    "MixedGroupLedger",
    "Staleness",
    "StalenessState",
    "ledger_staleness",
]


QUIET_AFTER_DAYS: Final[int] = 7
"""How many whole elapsed days without an entry counts as quiet, and as stale.

Seven because the product is a flat, and a grocery shop is a weekly rhythm: three days
would nag a flat that shops on Saturdays, and fourteen is too late to reconstruct a
fortnight of receipts. This is a product judgement rather than a measurement, and it is
the one number in this feature anybody should feel free to overrule.

It lives here, once. It is not configuration, not a ``_Settings`` field, not a CLI flag
and not a query parameter: a client choosing what counts as stale would be a client
choosing a product rule, and two flats reading one sentence with two meanings. The cost,
stated honestly, is that changing it is a code edit and a release. It reaches the front
end on the wire, so no copy of it lives under ``app/``, because two spellings of one
number with nothing forcing them to agree is a defect this repository has paid for
twice.
"""


class InvalidStaleness(InvalidEvent):
    """Every value this module refuses, under one name.

    One named type for the whole module, on the terms ``balances.InvalidLedger`` sets,
    so the HTTP layer keeps mapping the domain family to one response rather than
    growing a row per module. A wrong Python type raises ``TypeError`` instead: that is
    a programming error, not rejected input.

    It subclasses ``events.InvalidEvent``, and so ``money.DomainError``, because
    ``events`` is the one module this one imports and ``InvalidEvent`` is the
    ledger-invariant family that module exports. Neither this nor its subclass is in
    ``web.ERROR_STATUS`` or ``web.ERROR_CODE``, deliberately: no endpoint can produce
    either, so reaching one is a server defect and the unmapped 500 is the honest
    answer, exactly as it is for ``balances.InvalidLedger``.
    """


class MixedGroupLedger(InvalidStaleness):
    """Raised when ``events`` holds events belonging to more than one group.

    The precondition is that the caller has already scoped ``events`` to one group, and
    this is the one breach of it that is detectable without being handed a
    ``group_id``: two events that disagree with each other. It is refused before any
    arithmetic runs, because the alternative is a plausible wrong number. Mixing a
    group whose newest expense is an hour old into a group whose newest expense is nine
    days old would report the flat as up to date, which is the one thing this feature
    exists to stop happening.

    ``SettlementDecisionEvent`` carries no ``group_id`` of its own, by the design
    ``events.GroupId`` records, so decisions are ignored by this check. That is the same
    asymmetry ``balances.derive_balances`` lives with.
    """


class StalenessState(Enum):
    """Whether a ledger's age is known, and if it is, whether it is old.

    Three states rather than a boolean and a nullable count, and this is the decision
    the whole type rests on. A boolean beside a count can express "stale, and I do not
    know how stale", which is the shape of issue #44: a roster known to be empty
    rendered with the words for a roster that has not arrived. Three states cannot
    express it, so a screen switching on this cannot say it.

    Members are valued as their names, following ``SettlementState``'s precedent. The
    HTTP layer maps them to its own lowercase wire strings rather than sending the
    values, so renaming a member here cannot silently rename a JSON value a client
    branches on.
    """

    NEVER = "NEVER"
    """no expense has ever been recorded, so the age is unknown and there is no number"""
    FRESH = "FRESH"
    """an expense was recorded inside the window, so the ledger is being kept up"""
    STALE = "STALE"
    """the newest expense is at or past the threshold, so recent spending may be missing"""


@dataclass(frozen=True, slots=True)
class Staleness:
    """What one ledger does not know, at one instant.

    Built by :func:`ledger_staleness`, and unable to express a contradiction. Two
    invariants are enforced here rather than left to each caller:

    * ``days_since_last_expense`` is ``None`` if and only if ``state`` is ``NEVER``. So
      "I do not know how old this is" cannot be paired with a number, and a known age
      cannot arrive without one.
    * ``quiet_member_ids`` is empty when ``state`` is ``NEVER``. Naming five people for
      one fact the sentence above them already states is noise, and it reads as an
      accusation of five people for one circumstance.

    ``quiet_member_ids`` is a tuple, not a list, so the frozen dataclass is genuinely
    immutable, and its **iteration order is the iteration order of the ``members``
    mapping it was derived from**. Nothing here sorts: the caller passes a mapping built
    in roster order and the result is in roster order, so two readers of one group see
    one order.

    ``quiet_after_days`` rides along so the wire can carry the threshold it was computed
    against and a screen can print it without knowing it.
    """

    state: StalenessState
    days_since_last_expense: int | None
    quiet_member_ids: tuple[MemberId, ...]
    quiet_after_days: int

    def __post_init__(self) -> None:
        if not isinstance(self.state, StalenessState):
            raise TypeError(
                f"Staleness state must be a StalenessState, got "
                f"{type(self.state).__name__}: {self.state!r}"
            )
        if not isinstance(self.quiet_member_ids, tuple):
            raise TypeError(
                f"Staleness quiet_member_ids must be a tuple, got "
                f"{type(self.quiet_member_ids).__name__}"
            )
        _require_count(self.quiet_after_days, "Staleness quiet_after_days")
        if self.days_since_last_expense is not None:
            _require_count(
                self.days_since_last_expense, "Staleness days_since_last_expense"
            )
        if self.state is StalenessState.NEVER:
            if self.days_since_last_expense is not None:
                raise InvalidStaleness(
                    f"Staleness days_since_last_expense must be None when the state "
                    f"is NEVER, got {self.days_since_last_expense!r}"
                )
            if self.quiet_member_ids:
                raise InvalidStaleness(
                    f"Staleness quiet_member_ids must be empty when the state is "
                    f"NEVER, got {list(self.quiet_member_ids)!r}"
                )
        elif self.days_since_last_expense is None:
            raise InvalidStaleness(
                f"Staleness days_since_last_expense must be an int when the state is "
                f"not NEVER, got state {self.state.name}"
            )


def ledger_staleness(
    events: Iterable[LedgerEvent],
    members: Mapping[MemberId, _Instant],
    *,
    now: _Instant,
    quiet_after_days: int = QUIET_AFTER_DAYS,
) -> Staleness:
    """What ``events`` does not know, as of ``now``.

    ``events`` may be any iterable, a generator included, and is consumed exactly once;
    the caller's own list is neither mutated nor reordered. ``members`` maps each member
    id to the instant that member's row was created, and its **iteration order is the
    result's order**, so the caller passes a mapping built in roster order.

    **The age comes from the newest ``ExpenseEvent`` and from nothing else.** Whichever
    expense is maximal under ``events.ordering_key``, which is the one tie-break rule
    every consumer of the log shares rather than a rule re-derived here. Settlements and
    settlement decisions are excluded on purpose: the risk being mitigated is
    unrecorded *spend*, and a flat that settles up but stops logging groceries is
    exactly the failure mode, so letting a settlement reset the clock would hide the
    thing the signal is for.

    **The figure is whole elapsed 24-hour periods, floored, and no timezone is chosen.**
    ``(now - newest.created_at).days``, which floors for a positive difference. Not
    calendar days: the ``groups`` table carries no zone column and the spec has made no
    zone decision, two readers in two zones must read one number, and a calendar rule
    computed in UTC would flip at 00:00 UTC, which is mid-afternoon in Australia and
    would make a test of this flaky by the hour. The boundary is exact: the comparison
    is ``>=``, so at exactly ``quiet_after_days`` days and zero microseconds the state
    is ``STALE``, and one microsecond short of it the figure is one lower and the state
    is ``FRESH``. It ticks over on the anniversary of the instant, not at any midnight.

    **A future timestamp is clamped to zero, never reported as a negative.**
    ``timedelta.days`` floors toward negative infinity, so half a day ahead is ``-1``,
    and "recorded minus one days ago" is nonsense on a screen. ``web.py`` stamps
    ``created_at`` from its own single clock read, so this should be unreachable through
    the API, but the store deliberately accepts timestamps that disagree, because
    "Phone clocks disagree" (``store.py``), and a row written by a future
    ``setup_group.py`` run or a hand-edited database would reach it.

    **A member is quiet only if both hold**: they have created no ``ExpenseEvent``
    inside the window, and their row has existed for the whole window
    (``member_created_at <= now - quiet_after_days``). Membership of that list is by
    ``created_by`` and never by ``payer_id``, because the spec's risk is that nothing
    gets recorded. The consequence is stated rather than discovered: a flatmate who
    pays for everything and never opens the app is listed, because somebody else
    entered it. Listing somebody who has not had time to enter anything would be
    reporting an absence of data as a finding, so a group set up yesterday names
    nobody.

    **``store.Member.created_at`` is when the member row was created**, which is when an
    operator ran ``setup_group.py apply``. It is not a join date and it cannot be: spec
    open question 1 records that membership is a flat list with no dated intervals and
    calls retrofitting them expensive. So a member re-added after leaving looks new, and
    a member whose row was created months after they moved in looks older than they
    are. This is the best available proxy and it is used deliberately.

    **Precondition: ``events`` are already scoped to one group.** No ``group_id`` is
    taken and nothing is compared against one, because there is no group to compare
    against unless the caller names one, both call sites read a group's events through
    ``store.list_events(group_id)``, and this function computes no money. The
    consequence of breaking it in the way that cannot be detected from here, a list
    scoped entirely to the *wrong* group, is that the ledger reads fresher than it is,
    so the precondition is load-bearing. The one breach that is detectable, a list
    holding two groups at once, raises ``MixedGroupLedger`` rather than folding them.

    Returns:
        A ``Staleness`` whose ``state`` is ``NEVER`` when no expense has ever been
        recorded, ``STALE`` when the age is at or above ``quiet_after_days``, and
        ``FRESH`` otherwise.

    Raises:
        TypeError: if ``now``, or a value in ``members``, is not a ``datetime``, or if
            ``quiet_after_days`` is not a non-negative ``int``.
        InvalidStaleness: if ``now``, or a value in ``members``, is naive. Guessing a
            zone here would silently move every figure for anybody outside UTC.
        MixedGroupLedger: if ``events`` names more than one group.
    """
    moment = _require_instant(now, "ledger_staleness now")
    window = _require_count(quiet_after_days, "ledger_staleness quiet_after_days")
    ages = {
        member_id: _require_instant(
            created_at, f"ledger_staleness members[{member_id!r}]"
        )
        for member_id, created_at in members.items()
    }

    expenses: list[ExpenseEvent] = []
    groups: set[str] = set()
    for event in events:
        if isinstance(event, (ExpenseEvent, SettlementEvent)):
            groups.add(event.group_id)
        if isinstance(event, ExpenseEvent):
            expenses.append(event)
    if len(groups) > 1:
        raise MixedGroupLedger(
            f"ledger_staleness events name more than one group: {sorted(groups)}; "
            f"scope them to one group before asking how stale it is"
        )

    if not expenses:
        # No last expense, so there is no number and there is nobody to name. This is
        # the case a zero would have lied about, and it is the state a brand-new flat
        # is in, which is the worst case for the spec's risk.
        return Staleness(
            state=StalenessState.NEVER,
            days_since_last_expense=None,
            quiet_member_ids=(),
            quiet_after_days=window,
        )

    newest = max(expenses, key=ordering_key)
    elapsed = _elapsed_days(moment, newest.created_at)
    days = elapsed if elapsed > 0 else 0
    state = StalenessState.STALE if days >= window else StalenessState.FRESH

    # By created_by, over the whole ledger rather than over the newest expense: what is
    # being asked is who has entered something lately, and that is a different question
    # from how old the newest entry is.
    recorded_lately = {
        expense.created_by
        for expense in expenses
        if _elapsed_days(moment, expense.created_at) < window
    }
    # A created_by the roster does not know is ignored rather than refused: an operator
    # who adds a member row late creates exactly that, and a display signal must not
    # become a 500 over it. A member the ledger has never seen can be quiet, which is
    # the other half of the same asymmetry.
    quiet = tuple(
        member_id
        for member_id, created_at in ages.items()
        if member_id not in recorded_lately
        and _elapsed_days(moment, created_at) >= window
    )
    return Staleness(
        state=state,
        days_since_last_expense=days,
        quiet_member_ids=quiet,
        quiet_after_days=window,
    )


def _elapsed_days(later: _Instant, earlier: _Instant) -> int:
    """Whole 24-hour periods from ``earlier`` to ``later``, floored.

    The one arithmetic rule in this module, written once so the age figure, the recency
    of an entry and the age of a member row cannot drift apart. ``timedelta.days``
    floors toward negative infinity, and for an integer ``count`` that makes
    ``_elapsed_days(a, b) >= count`` exactly ``b <= a - count days`` and
    ``_elapsed_days(a, b) < count`` exactly ``b > a - count days``, which is why no
    ``timedelta`` is constructed anywhere here.
    """
    return (later - earlier).days


def _require_instant(value: object, field: str) -> _Instant:
    """Return ``value`` if it is a timezone-aware ``datetime``, else raise.

    The same two refusals ``events._require_utc`` makes, in the same wording shape, and
    made here rather than inside the arithmetic: subtracting a naive datetime from an
    aware one raises a ``TypeError`` from three frames down that names neither the field
    nor what is wrong with it. A naive value is rejected rather than assumed to be local
    or UTC, because guessing would silently move every figure for anybody outside UTC.

    Nothing is converted. ``events._require_utc`` normalises because what it guards is
    stored; nothing here is stored and only differences are taken, and a difference
    between two aware instants is the same whatever zone either one spells itself in.
    """
    if not isinstance(value, _Instant):
        raise TypeError(
            f"{field} must be a datetime, got {type(value).__name__}: {value!r}"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidStaleness(f"{field} must be timezone-aware, got naive {value!r}")
    return value


def _require_count(value: object, field: str) -> int:
    """Return ``value`` if it is a non-negative ``int`` and not a ``bool``, else raise.

    A day count is a whole number of days. A float would make the ``>=`` boundary
    depend on a rounding rule nobody has chosen, and ``True`` is not a threshold.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{field} must be an int, got {type(value).__name__}: {value!r}"
        )
    if value < 0:
        raise TypeError(f"{field} must be zero or positive, got {value}")
    return value
