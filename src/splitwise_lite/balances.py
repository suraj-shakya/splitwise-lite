"""Balance derivation: a ledger folds into pairwise debts and net positions.

Nothing here is stored. ``derive_balances`` is a pure function of the events it is
handed, so the same log always produces the same answer, in any order and in any
process, and there is never a cached balance to go stale or to patch.

**Sign convention.** ``net[m]`` is positive when the group owes ``m`` and negative when
``m`` owes the group: a member who paid 3000 and consumed 1000 sits at +2000. The
``pairwise`` key is ``(debtor, creditor)`` and its value is always strictly positive, so
``(bo, ali): 1000`` reads as "Bo owes Ali ten dollars". A pair that nets to zero is
absent, only one direction of a pair is ever present, and a self pair never appears.

``net`` is a summary of ``pairwise`` and can be recomputed from it. The reverse is not
true, which is why the fold accumulates the pairwise map directly from each event rather
than distributing net positions afterwards: losing who owes whom is exactly what debt
simplification does, and that is a later, deliberate step.

**The two settlement rules**, stated in ``events.py`` and enforced here first, so every
consumer gets the same answer:

* *Earliest decision wins.* A settlement's state is decided by the earliest decision
  event referencing it, by ``ordering_key``. Later decisions for the same settlement are
  ignored, a later ``CONFIRMED`` after an earlier ``REJECTED`` included. A retry or a
  race can put two answers in the log, and picking the first keeps every reader on one.
* *Only confirmed settlements move money.* A ``PENDING`` or ``REJECTED`` settlement is
  inert: it changes no net position, creates no pairwise entry, and does not even
  put its two members into ``net``. Until the receiver confirms, the claimed payment
  is a row on a screen, not money that has moved.

**How a decision finds its group.** ``SettlementDecisionEvent`` carries no ``group_id``,
so the group is stated by the caller instead of inferred from whichever event sorts
first: ``group_id`` is a required argument. Every expense and settlement in the input
must carry it, and one that does not raises ``InvalidLedger`` rather than being silently
dropped, because folding two groups together has to stay a detectable mistake. A
decision is bound to its group indirectly, through ``settlement_id``, and a decision
naming no settlement in the input is *ignored rather than rejected*: without a group of
its own it cannot be attributed to anything, it may belong to another group or to a
settlement outside the window the caller loaded, and ignoring it is safe because a
decision never moves money by itself.

The consequence for the query layer: a group's settlements and their decisions must be
loaded **together**, because decisions cannot be filtered by group on their own.

Dependency direction: this module imports from ``money`` and ``events``; neither of them
knows it exists, and the split resolver is a sibling this module never touches.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .events import (
    ExpenseEvent,
    GroupId,
    LedgerEvent,
    MemberId,
    SettlementDecisionEvent,
    SettlementEvent,
    SettlementId,
    SettlementState,
    ordering_key,
)
from .money import Currency, CurrencyMismatch, DomainError, Money

__all__ = [
    "Balances",
    "InvalidLedger",
    "derive_balances",
    "settlement_states",
]


class InvalidLedger(DomainError):
    """Raised when a list of events cannot be folded into one group's balances.

    Covers a foreign group, an empty group id and a repeated event id. One named type
    for every value rejection in this module, so the HTTP layer keeps mapping the whole
    domain family to a single response. A wrong Python type raises ``TypeError``
    instead: that is a programming error, not rejected user input.
    """


@dataclass(frozen=True, slots=True)
class Balances:
    """The derived position of one group in one currency, at one point in the log.

    Built only by ``derive_balances``, which is where the invariants below are
    established:

    * ``net`` holds one entry per member the fold has seen, and its cents sum to exactly
      zero. Money only ever moves between members, never into or out of the group.
    * ``pairwise`` values are strictly positive, no pair appears in both directions, and
      no member owes themselves.
    * the two agree: for every member, ``net[m]`` equals what ``m`` is owed across
      ``pairwise`` minus what ``m`` owes.
    * iteration is deterministic: ``net`` ascends by member id and ``pairwise`` ascends
      by ``(debtor, creditor)``, so two readers of the same log see the same rows in the
      same order.

    Both mappings are read-only views, so no consumer can patch a derived figure in
    place. A balance is a value, not a cache. Equality is by value, so two folds of the
    same events compare equal; no ``__hash__`` is written, and the mappings make the
    generated one unusable, which is intended.
    """

    group_id: GroupId
    currency: Currency
    net: Mapping[MemberId, Money]
    pairwise: Mapping[tuple[MemberId, MemberId], Money]

    def net_for(self, member_id: MemberId) -> Money:
        """Return ``member_id``'s net position, or zero if the ledger has never seen it.

        Total by design, so a caller walking the group roster does not have to guard
        every lookup: a member who has been in no expense and no confirmed settlement is
        square with the group, and zero is the honest answer rather than a ``KeyError``.
        """
        found = self.net.get(member_id)
        if found is None:
            return Money(0, self.currency)
        return found

    def owed_between(self, debtor: MemberId, creditor: MemberId) -> Money:
        """Return what ``debtor`` owes ``creditor``, signed and total.

        Positive when the debt runs the way it was asked about, negative when it runs
        the other way, and zero when the pair has no debt at all. Only one direction of
        a pair is ever stored, so without the sign a caller would have to try both
        orders and would misread a stored reverse debt as no debt.
        """
        stored = self.pairwise.get((debtor, creditor))
        if stored is not None:
            return stored
        reverse = self.pairwise.get((creditor, debtor))
        if reverse is not None:
            return Money(-reverse.cents, self.currency)
        return Money(0, self.currency)


def derive_balances(
    events: Iterable[LedgerEvent],
    *,
    group_id: GroupId,
    currency: Currency,
) -> Balances:
    """Fold a whole ledger into one group's ``Balances``.

    Pass the whole log: expenses, settlements **and** decision events. This function
    works out which settlements are confirmed, because ``SettlementEvent`` deliberately
    carries no state field and a caller who pre-filtered to "confirmed" would have to
    duplicate the earliest-decision rule to do it.

    ``events`` may be any iterable, a generator included, and is consumed exactly once.
    The caller's own list is neither mutated nor reordered: a copy is sorted.

    Invariants established here, all of them eagerly, so no later layer re-checks them:

    * every expense and settlement carries ``group_id`` and ``currency``, or the call
      raises; there is no partial answer over the events that happen to match
    * only confirmed settlements move money, by the rule in the module docstring
    * ``net`` sums to zero, ``pairwise`` values are strictly positive, and the two agree
    * the result depends on the set of events, never on the order they arrived in

    Arithmetic is integer cents throughout, accumulated in plain ``int`` and wrapped
    into ``Money`` once, when the result is built. There is no division anywhere in this
    module: the fold only adds and subtracts, so no remainder can arise and no rounding
    rule may be invented here. Dividing a total across people is the split resolver's
    job and has already happened by the time an expense reaches this function.

    No bound is applied to a balance. Balances are derived and never stored, so there is
    no 64-bit column to overflow and Python integers do not wrap; the stored-amount
    bound belongs on the amounts, not on a sum of them.

    Raises:
        TypeError: if ``events`` is not an iterable of ledger events, if ``group_id`` is
            not a ``str``, or if ``currency`` is not a ``Currency``.
        InvalidLedger: if ``group_id`` is empty, if an expense or settlement belongs to
            another group, or if one event id appears twice.
        CurrencyMismatch: if an expense or settlement is in another currency. Adding NZD
            cents to AUD cents is exactly what that exception exists for.
    """
    group = _require_group_id(group_id)
    unit = _require_currency(currency)
    expenses, settlements, decisions = _partition(events)

    for expense in expenses:
        _require_group(expense, group, "expense")
        _require_currency_match(expense, unit, "expense")
    for settlement in settlements:
        _require_group(settlement, group, "settlement")
        _require_currency_match(settlement, unit, "settlement")

    states = _decided_states(settlements, decisions)
    net: dict[MemberId, int] = {}
    debts: dict[tuple[MemberId, MemberId], int] = {}

    for expense in expenses:
        # The payer is credited the total rather than the sum of the allocations.
        # ``ExpenseEvent`` guarantees the two are equal, and this fold re-checks none of
        # the construction invariants task 2 already enforces.
        _add(net, expense.payer_id, expense.total_cents)
        for allocation in expense.allocations:
            _add(net, allocation.member_id, -allocation.cents)
            if allocation.member_id != expense.payer_id and allocation.cents != 0:
                # Two exclusions, both deliberate: the payer's own share is not a debt
                # to themselves, and a zero share is not a debt at all. Both members
                # still hold a ``net`` entry, because being on an expense for nothing is
                # different from not being on it.
                _add_debt(
                    debts, allocation.member_id, expense.payer_id, allocation.cents
                )

    for settlement in settlements:
        if states[settlement.id] is not SettlementState.CONFIRMED:
            continue
        # The payer has handed over real money, so their position improves and the
        # receiver's falls: the debt created runs from the receiver back to the payer.
        # The amount is never validated against the pairwise debt it appears to clear.
        # A settlement larger than the debt flips the pair, and "confirm in full or not
        # at all" is a service and UI rule, not an arithmetic one.
        _add(net, settlement.from_member_id, settlement.amount_cents)
        _add(net, settlement.to_member_id, -settlement.amount_cents)
        _add_debt(
            debts,
            settlement.to_member_id,
            settlement.from_member_id,
            settlement.amount_cents,
        )

    return Balances(
        group_id=group,
        currency=unit,
        net=MappingProxyType(
            {member_id: Money(net[member_id], unit) for member_id in sorted(net)}
        ),
        pairwise=MappingProxyType(_directed(debts, unit)),
    )


def settlement_states(
    events: Iterable[LedgerEvent],
) -> dict[SettlementId, SettlementState]:
    """Return the state of every settlement in ``events``, by settlement id ascending.

    One entry per ``SettlementEvent`` in the input, ``PENDING`` for a settlement no
    decision references. Expense events are ignored rather than rejected, so the same
    whole-log list can be handed to this function and to ``derive_balances``, and
    ``derive_balances`` reaches this same code path, so a rendered state and a balance
    can never disagree about whether a settlement counted.

    The earliest decision by ``ordering_key`` decides, and the rest are ignored. A
    decision naming a settlement that is not in the input is ignored too, and adds no
    key to the result: it cannot be attributed to a group on its own, so rejecting it
    would make a caller's query window a source of errors.

    Whether ``decided_by`` is entitled to decide is not checked. A decision cannot see
    the settlement it references, so the rule that only the receiver may confirm belongs
    to the layer that can load both records.

    Raises:
        TypeError: if ``events`` is not an iterable of ledger events.
        InvalidLedger: if one event id appears twice within an event type.
    """
    _, settlements, decisions = _partition(events)
    return _decided_states(settlements, decisions)


def _decided_states(
    settlements: tuple[SettlementEvent, ...],
    decisions: tuple[SettlementDecisionEvent, ...],
) -> dict[SettlementId, SettlementState]:
    """Apply the earliest-decision rule to already sorted settlements and decisions.

    Both arguments arrive in ``ordering_key`` order, so the first decision seen for a
    settlement is the earliest one and every later answer for it is dropped. This is the
    single implementation of the rule; nothing else in the codebase re-derives it.
    """
    known = {settlement.id for settlement in settlements}
    earliest: dict[SettlementId, SettlementState] = {}
    for decision in decisions:
        if decision.settlement_id in known:
            earliest.setdefault(decision.settlement_id, decision.decision)
    return {
        settlement_id: earliest.get(settlement_id, SettlementState.PENDING)
        for settlement_id in sorted(known)
    }


def _partition(
    events: object,
) -> tuple[
    tuple[ExpenseEvent, ...],
    tuple[SettlementEvent, ...],
    tuple[SettlementDecisionEvent, ...],
]:
    """Split an iterable of events by type, sorted and free of repeated ids.

    Consumes ``events`` exactly once, so a generator is as acceptable as a list, and
    sorts copies, so a caller's list comes back in the order they built it.

    A ``str`` is an iterable of one-character strings and a ``Mapping`` is an iterable
    of its keys, so both are rejected outright rather than read as an event list,
    following the precedent the split resolver set.
    """
    if isinstance(events, (str, bytes, bytearray, Mapping)):
        raise TypeError(
            f"events must be an iterable of ledger events, got "
            f"{type(events).__name__}: {events!r}"
        )
    if not isinstance(events, Iterable):
        raise TypeError(
            f"events must be an iterable of ledger events, got "
            f"{type(events).__name__}: {events!r}"
        )

    expenses: list[ExpenseEvent] = []
    settlements: list[SettlementEvent] = []
    decisions: list[SettlementDecisionEvent] = []
    for event in events:
        if isinstance(event, ExpenseEvent):
            expenses.append(event)
        elif isinstance(event, SettlementEvent):
            settlements.append(event)
        elif isinstance(event, SettlementDecisionEvent):
            decisions.append(event)
        else:
            raise TypeError(
                f"events may only contain ledger events, got "
                f"{type(event).__name__}: {event!r}"
            )
    return (
        _sorted_unique(expenses, "expense"),
        _sorted_unique(settlements, "settlement"),
        _sorted_unique(decisions, "settlement decision"),
    )


def _sorted_unique[EventT: LedgerEvent](
    events: list[EventT], label: str
) -> tuple[EventT, ...]:
    """Return ``events`` sorted by ``ordering_key``, rejecting a repeated id.

    Sorting is by the total order ``events.py`` defines, never by list position and
    never by ``created_at`` alone: identical timestamps are the case the id tie-break
    exists for, and they decide which of two conflicting decisions wins.

    A repeated id is rejected because double-counting an expense is a money bug: a
    caller who concatenates two overlapping queries would otherwise get a plausible
    wrong answer. Two distinct events with equal amounts are untouched by this.
    """
    ordered = tuple(sorted(events, key=ordering_key))
    seen: set[str] = set()
    for event in ordered:
        if event.id in seen:
            raise InvalidLedger(
                f"the same {label} id appears twice in the ledger: {event.id!r}"
            )
        seen.add(event.id)
    return ordered


def _add(net: dict[MemberId, int], member_id: MemberId, cents: int) -> None:
    """Move ``member_id``'s net position by ``cents``, creating the entry if needed.

    Zero is a real move: it puts a member who was on an expense for nothing into the
    map, which is how a zero-cent allocation stays visible.
    """
    net[member_id] = net.get(member_id, 0) + cents


def _add_debt(
    debts: dict[tuple[MemberId, MemberId], int],
    debtor: MemberId,
    creditor: MemberId,
    cents: int,
) -> None:
    """Accumulate ``cents`` owed by ``debtor`` to ``creditor``.

    Both directions of a pair share one canonical key, the two ids in ascending order,
    with the amount signed against it. That is what makes opposing debts cancel into one
    entry instead of standing as two rows that a reader has to net themselves, and it is
    why a pair can never appear twice in the result.

    Callers must exclude a self pair; a member owing themselves is meaningless and would
    land on a degenerate key here.
    """
    if debtor < creditor:
        key, signed = (debtor, creditor), cents
    else:
        key, signed = (creditor, debtor), -cents
    debts[key] = debts.get(key, 0) + signed


def _directed(
    debts: dict[tuple[MemberId, MemberId], int], currency: Currency
) -> dict[tuple[MemberId, MemberId], Money]:
    """Turn canonical signed pairs into ``(debtor, creditor)`` entries, key ascending.

    A pair that has netted to zero is dropped: zero is not a debt, and storing it would
    put a settled pair on the balances screen. A negative canonical amount means the
    debt runs the other way, so the key is flipped and the amount made positive.
    """
    entries = []
    for (first, second), amount in debts.items():
        if amount > 0:
            entries.append(((first, second), amount))
        elif amount < 0:
            entries.append(((second, first), -amount))
    return {pair: Money(amount, currency) for pair, amount in sorted(entries)}


def _require_group_id(value: object) -> GroupId:
    """Return ``value`` if it is a non-empty ``str``, else raise."""
    if not isinstance(value, str):
        raise TypeError(
            f"group_id must be a str, got {type(value).__name__}: {value!r}"
        )
    if not value:
        raise InvalidLedger("group_id must be a non-empty id")
    return GroupId(value)


def _require_currency(value: object) -> Currency:
    """Return ``value`` if it is a ``Currency``, else raise ``TypeError``.

    The currency is an argument rather than something read off the first event, so an
    empty ledger still has one and no caller has to handle a ``None``.
    """
    if not isinstance(value, Currency):
        raise TypeError(
            f"currency must be a Currency, got {type(value).__name__}: {value!r}"
        )
    return value


def _require_group(
    event: ExpenseEvent | SettlementEvent, group_id: GroupId, label: str
) -> None:
    """Raise ``InvalidLedger`` unless ``event`` belongs to ``group_id``.

    Dropping the foreign event instead would make folding two groups together
    undetectable, which is the mistake ``group_id`` is on events to catch.
    """
    if event.group_id != group_id:
        raise InvalidLedger(
            f"{label} {event.id!r} belongs to group {event.group_id!r}, not the group "
            f"asked for, {group_id!r}"
        )


def _require_currency_match(
    event: ExpenseEvent | SettlementEvent, currency: Currency, label: str
) -> None:
    """Raise ``CurrencyMismatch`` unless ``event`` is in ``currency``."""
    if event.currency != currency:
        raise CurrencyMismatch(
            f"cannot combine {event.currency.code} and {currency.code}: {label} "
            f"{event.id!r} is in {event.currency.code} and the ledger is in "
            f"{currency.code}"
        )
