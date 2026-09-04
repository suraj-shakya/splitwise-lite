"""Ledger events: the immutable, append-only record the balances are derived from.

Nothing here stores a balance. The ledger is a list of events, and every figure the
product shows is folded out of them, so any number can be traced back to the events
that produced it.

Ordering: events are ordered by ``(created_at, id)``. The id breaks the tie when two
events share a timestamp, which gives the log a total order rather than an arbitrary
one. Use ``ordering_key`` rather than re-deriving the rule.

Settlement state is derived, never stored. A settlement is born pending and its state
comes from the decision events that reference it, under two rules every consumer must
apply the same way:

* Conflicting decisions: the earliest decision for a given settlement id wins, by the
  ordering key above, and later decisions for the same settlement are ignored. A log
  can hold two answers for one settlement, from a retry or a race, and picking the
  first keeps every reader at the same answer.
* Balances: only confirmed settlements enter the balance fold.
  A pending settlement moves no balance, and neither does a rejected one. Until the
  receiver confirms, the claimed payment shows as awaiting them rather than as money
  that has moved.

Dependency direction: this module imports from ``money``; ``money`` imports nothing
from the package.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import NewType

from .money import Currency, DomainError

__all__ = [
    "Allocation",
    "ExpenseEvent",
    "ExpenseId",
    "GroupId",
    "InvalidAllocation",
    "InvalidEvent",
    "LedgerEvent",
    "MemberId",
    "SettlementDecisionEvent",
    "SettlementEvent",
    "SettlementId",
    "SettlementState",
    "new_id",
    "ordering_key",
]

MemberId = NewType("MemberId", str)
"""Identifies a member of a group. Distinct from every other id type when read."""

GroupId = NewType("GroupId", str)
"""Identifies a group. Every event carries one, so folding two groups together is a
detectable mistake rather than a silent one, with one deliberate exception:
``SettlementDecisionEvent`` inherits its group from the settlement it references. See
"A settlement decision has no ``group_id`` of its own" in plans/spec.md."""

ExpenseId = NewType("ExpenseId", str)
"""Identifies an expense event."""

SettlementId = NewType("SettlementId", str)
"""Identifies a settlement event. A decision event references one of these."""

# No type checker is configured in this repo, so the four NewTypes above are
# documentation and future-proofing: at runtime they are all str. The runtime guarantee
# is the constructor validation on every event, which rejects an id that is not a
# non-empty str.


class InvalidAllocation(DomainError):
    """Raised when an allocation is not a whole, non-negative share of a total."""


def new_id() -> str:
    """Mint a fresh id as a UUID4 string.

    Ids are random, never derived from a name, an email or a sequence number: a
    guessable or meaningful id leaks membership and breaks the moment someone is
    renamed. Callers wrap the result in the id type the field expects, for example
    ``MemberId(new_id())``.
    """
    return str(uuid.uuid4())


def _require_id(value: object, field: str, error: type[DomainError]) -> str:
    """Return ``value`` if it is a non-empty ``str``, else raise."""
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a str, got {type(value).__name__}: {value!r}")
    if not value:
        raise error(f"{field} must be a non-empty id")
    return value


def _require_int(value: object, field: str) -> int:
    """Return ``value`` if it is an ``int`` and not a ``bool``, else raise ``TypeError``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{field} must be an int, got {type(value).__name__}: {value!r}"
        )
    return value


@dataclass(frozen=True, slots=True)
class Allocation:
    """One participant's share of an expense, in whole cents.

    Invariants:

    * ``member_id`` is a non-empty ``str``.
    * ``cents`` is zero or positive. Zero is legal and must not be rejected: 2 cents
      split across 3 people gives 1, 1, 0, and the split resolver has to be able to
      express that share. A negative share is rejected.

    An allocation carries no currency of its own. The enclosing event carries one
    currency covering all of its amounts, which is what makes a mixed-currency event
    unrepresentable rather than merely discouraged.
    """

    member_id: MemberId
    cents: int

    def __post_init__(self) -> None:
        _require_id(self.member_id, "Allocation member_id", InvalidAllocation)
        _require_int(self.cents, "Allocation cents")
        if self.cents < 0:
            raise InvalidAllocation(
                f"allocation cents must be zero or positive, got {self.cents}"
            )


class InvalidEvent(DomainError):
    """Raised when an event would break one of the ledger's invariants."""


def _require_currency(value: object, field: str) -> Currency:
    """Return ``value`` if it is a ``Currency``, else raise ``TypeError``."""
    if not isinstance(value, Currency):
        raise TypeError(
            f"{field} must be a Currency, got {type(value).__name__}: {value!r}"
        )
    return value


def _require_utc(value: object, field: str) -> datetime:
    """Return ``value`` converted to UTC, else raise.

    A naive datetime is rejected rather than assumed to be local or UTC: guessing here
    would silently reorder the log for anyone in another timezone.
    """
    if not isinstance(value, datetime):
        raise TypeError(
            f"{field} must be a datetime, got {type(value).__name__}: {value!r}"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidEvent(f"{field} must be timezone-aware, got naive {value!r}")
    return value.astimezone(timezone.utc)


def _require_description(value: object, field: str) -> str:
    """Return ``value`` stripped of surrounding whitespace, else raise ``TypeError``."""
    if not isinstance(value, str):
        raise TypeError(
            f"{field} must be a str, got {type(value).__name__}: {value!r}"
        )
    return value.strip()


@dataclass(frozen=True, slots=True)
class ExpenseEvent:
    """One expense, recorded once and never edited.

    Invariants, all enforced at construction so no later layer has to re-check them:

    * Every id field is a non-empty ``str``.
    * ``total_cents`` is strictly positive. Zero is a data-entry error and a negative
      total is a refund; v1 has neither.
    * ``allocations`` is a non-empty ``tuple`` of ``Allocation``. A tuple, not a list,
      so the frozen dataclass is genuinely immutable and the event stays hashable.
    * ``sum(a.cents for a in allocations) == total_cents`` exactly. This is the
      invariant the split resolver is written to satisfy and the balance fold relies
      on: every cent of the total is somebody's share.
    * No member appears twice in ``allocations``. A duplicate makes the balance fold
      and the drill-down disagree quietly, so it fails here instead.
    * ``created_at`` is timezone-aware and stored in UTC.
    * ``description`` is stripped of surrounding whitespace and may be empty. Entering
      an expense in under ten seconds is a product requirement, so a description is
      never mandatory. No length cap is imposed here; storage picks a width.

    The payer is deliberately not required to appear in ``allocations``: someone can
    pay for a meal they did not eat. An expense where the payer is the only participant
    is equally legal and simply produces no debt.

    The event exposes no mutating method. Correcting an expense means appending a new
    event, never editing this one.
    """

    id: ExpenseId
    group_id: GroupId
    currency: Currency
    payer_id: MemberId
    total_cents: int
    allocations: tuple[Allocation, ...]
    description: str
    created_at: datetime
    created_by: MemberId

    def __post_init__(self) -> None:
        _require_id(self.id, "ExpenseEvent id", InvalidEvent)
        _require_id(self.group_id, "ExpenseEvent group_id", InvalidEvent)
        _require_id(self.payer_id, "ExpenseEvent payer_id", InvalidEvent)
        _require_id(self.created_by, "ExpenseEvent created_by", InvalidEvent)
        _require_currency(self.currency, "ExpenseEvent currency")
        _require_int(self.total_cents, "ExpenseEvent total_cents")
        if self.total_cents <= 0:
            raise InvalidEvent(
                f"expense total_cents must be strictly positive, got "
                f"{self.total_cents}"
            )
        if not isinstance(self.allocations, tuple):
            raise TypeError(
                f"ExpenseEvent allocations must be a tuple, got "
                f"{type(self.allocations).__name__}"
            )
        for allocation in self.allocations:
            if not isinstance(allocation, Allocation):
                raise TypeError(
                    f"ExpenseEvent allocations must contain Allocation, got "
                    f"{type(allocation).__name__}: {allocation!r}"
                )
        if not self.allocations:
            raise InvalidEvent("expense must have at least one allocation")
        members = [allocation.member_id for allocation in self.allocations]
        if len(set(members)) != len(members):
            raise InvalidEvent(
                f"expense allocations name a member more than once: {members}"
            )
        allocated = sum(allocation.cents for allocation in self.allocations)
        if allocated != self.total_cents:
            raise InvalidEvent(
                f"expense allocations sum to {allocated}, not total_cents "
                f"{self.total_cents}"
            )
        object.__setattr__(
            self,
            "description",
            _require_description(self.description, "ExpenseEvent description"),
        )
        object.__setattr__(
            self, "created_at", _require_utc(self.created_at, "ExpenseEvent created_at")
        )


class SettlementState(Enum):
    """The state of a settlement, derived from its decision events.

    ``PENDING`` is the state of a settlement with no decision yet: the payer has said
    they paid and the receiver has not answered. ``REJECTED`` is a state rather than a
    deletion, so a disputed settlement stays visible with its state changed instead of
    vanishing from the log.
    """

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class SettlementEvent:
    """A proposed payment from one member to another, recorded when it is claimed.

    Invariants:

    * Every id field is a non-empty ``str``.
    * ``amount_cents`` is strictly positive.
    * ``from_member_id != to_member_id``. Settling with yourself is meaningless.
    * ``created_at`` is timezone-aware and stored in UTC.

    A settlement is born pending and carries no state field, because a mutable state
    field on an immutable event is a contradiction. Its current state is derived from
    the ``SettlementDecisionEvent`` records that reference it.
    """

    id: SettlementId
    group_id: GroupId
    currency: Currency
    from_member_id: MemberId
    to_member_id: MemberId
    amount_cents: int
    created_at: datetime
    created_by: MemberId

    def __post_init__(self) -> None:
        _require_id(self.id, "SettlementEvent id", InvalidEvent)
        _require_id(self.group_id, "SettlementEvent group_id", InvalidEvent)
        _require_id(self.from_member_id, "SettlementEvent from_member_id", InvalidEvent)
        _require_id(self.to_member_id, "SettlementEvent to_member_id", InvalidEvent)
        _require_id(self.created_by, "SettlementEvent created_by", InvalidEvent)
        _require_currency(self.currency, "SettlementEvent currency")
        _require_int(self.amount_cents, "SettlementEvent amount_cents")
        if self.amount_cents <= 0:
            raise InvalidEvent(
                f"settlement amount_cents must be strictly positive, got "
                f"{self.amount_cents}"
            )
        if self.from_member_id == self.to_member_id:
            raise InvalidEvent(
                f"a member cannot settle with themselves: {self.from_member_id}"
            )
        object.__setattr__(
            self,
            "created_at",
            _require_utc(self.created_at, "SettlementEvent created_at"),
        )


@dataclass(frozen=True, slots=True)
class SettlementDecisionEvent:
    """The receiver's answer to one settlement, appended rather than applied.

    Invariants:

    * Every id field is a non-empty ``str``.
    * ``decision`` is ``SettlementState.CONFIRMED`` or ``SettlementState.REJECTED``.
      ``PENDING`` is not a decision: it is the absence of one, and recording it would
      let the log claim a settlement was decided into the state it started in.
    * ``created_at`` is timezone-aware and stored in UTC.

    It references the settlement by id and never restates the amount, so a decision
    cannot disagree with the settlement it decides.

    Whether the decider is entitled to decide is not checked here. A decision event
    cannot see the settlement it references, so the rule that only the receiver may
    confirm belongs to the service layer that can load both.
    """

    id: str
    settlement_id: SettlementId
    decision: SettlementState
    decided_by: MemberId
    created_at: datetime

    def __post_init__(self) -> None:
        _require_id(self.id, "SettlementDecisionEvent id", InvalidEvent)
        _require_id(
            self.settlement_id, "SettlementDecisionEvent settlement_id", InvalidEvent
        )
        _require_id(self.decided_by, "SettlementDecisionEvent decided_by", InvalidEvent)
        if not isinstance(self.decision, SettlementState):
            raise TypeError(
                f"SettlementDecisionEvent decision must be a SettlementState, got "
                f"{type(self.decision).__name__}: {self.decision!r}"
            )
        if self.decision is SettlementState.PENDING:
            raise InvalidEvent(
                "a decision must be CONFIRMED or REJECTED; PENDING is the absence of "
                "a decision"
            )
        object.__setattr__(
            self,
            "created_at",
            _require_utc(self.created_at, "SettlementDecisionEvent created_at"),
        )


LedgerEvent = ExpenseEvent | SettlementEvent | SettlementDecisionEvent
"""Any event in the ledger. Every one of them carries ``created_at`` and ``id``."""


def ordering_key(event: LedgerEvent) -> tuple[datetime, str]:
    """Return the total ordering key for an event: ``(created_at, id)``.

    Timestamps collide, and two events with the same timestamp must still have one
    agreed order or two readers of the same log will disagree. The id breaks the tie.
    Every consumer that folds or replays events sorts with this function rather than
    re-deriving the rule.
    """
    return (event.created_at, event.id)
