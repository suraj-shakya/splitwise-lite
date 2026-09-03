"""Ledger events: the immutable, append-only record the balances are derived from.

Nothing here stores a balance. The ledger is a list of events, and every figure the
product shows is folded out of them, so any number can be traced back to the events
that produced it.

Ordering: events are ordered by ``(created_at, id)``. The id breaks the tie when two
events share a timestamp, which gives the log a total order rather than an arbitrary
one. Use ``ordering_key`` rather than re-deriving the rule.

Dependency direction: this module imports from ``money``; ``money`` imports nothing
from the package.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import NewType

from .money import DomainError

__all__ = [
    "Allocation",
    "ExpenseId",
    "GroupId",
    "InvalidAllocation",
    "MemberId",
    "SettlementId",
    "new_id",
]

MemberId = NewType("MemberId", str)
"""Identifies a member of a group. Distinct from every other id type when read."""

GroupId = NewType("GroupId", str)
"""Identifies a group. Every event carries one, so folding two groups together is a
detectable mistake rather than a silent one."""

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
