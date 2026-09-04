"""Split resolver: a total and a mode become explicit per-person allocations.

The spec collapses all three split rules into one shape: an expense stores a list of
``(member, cents)`` and nothing else. This module is where that collapse happens.
Equal, subset and uneven splits are all resolved to explicit cents here, at entry time,
so the ledger carries no rule types and there is one rounding problem instead of three.

The three modes the backlog names map onto three functions:

* equal across everyone, and equal across a subset, are both ``split_equally`` over the
  member list the caller assembles
* uneven by weight is ``split_by_weight``
* uneven by exact amount is ``split_exact``

**The remainder rule.** A total rarely divides evenly, so somebody has to absorb the
leftover cents. Both fair-share modes go through one allocator, ``_allocate``, which
uses the largest-remainder method on integer arithmetic: each member's floor share is
``(total * weight) // weight_total`` with remainder ``(total * weight) % weight_total``,
and the leftover cents go one each to the largest remainders.

Under an equal split every remainder is identical, so the tie-break decides. It is a
rotation: members are placed in ascending ``member_id`` order and the walk starts at
index ``(total // n) % n``, wrapping around. That is deliberate. Handing the extra cent
to the member who sorts first would mean the same flatmate quietly pays one cent more on
every single expense, which is the outcome both the spec and the backlog reject.
Offsetting by the base share moves the recipient as the total moves, so across a series
of expenses the extra cent lands on everyone. Offsetting by ``total % n`` would not
work: that value *is* the leftover count, so a one-cent remainder would always land on
the same index.

The result is a pure function of the total and the set of members. No clock, no
randomness and no ``hash`` of a string (which is salted per process and would give two
readers two different answers), so the same expense resolves the same way forever.

Every allocation is a real ``Allocation``, so the returned tuple drops straight into
``ExpenseEvent.allocations`` and satisfies its sum invariant by construction.

Dependency direction: this module imports from ``money`` and ``events``; neither of them
knows it exists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .events import Allocation, MemberId
from .money import MAX_CENTS, DomainError

__all__ = [
    "InvalidSplit",
    "split_by_weight",
    "split_equally",
    "split_exact",
]


class InvalidSplit(DomainError):
    """Raised when a split cannot be resolved to whole cents summing to the total.

    One named type for every value rejection in this module, so the HTTP layer maps the
    whole domain family to a single response. A wrong Python type raises ``TypeError``
    instead: that is a programming error, not rejected user input.
    """


def split_equally(
    total_cents: int, member_ids: Iterable[MemberId]
) -> tuple[Allocation, ...]:
    """Split ``total_cents`` evenly across ``member_ids``.

    Covers two of the three modes: pass every member for "equal across all", or the
    chosen few for "equal across a subset". This module has no membership roster, so
    which of those it is depends entirely on the list handed in.

    Invariants:

    * the allocations sum to ``total_cents`` exactly
    * every share is within one cent of every other, so exactly ``total_cents % n``
      members pay the extra cent
    * a share of zero is returned rather than dropped: 2 cents across 3 people is
      ``1, 1, 0``, and all three members stay on the expense
    * the result is ordered by ``member_id`` and does not depend on the order the
      members were supplied in

    The extra cents are assigned by the rotation described in the module docstring, not
    to whoever sorts first.

    Raises:
        TypeError: if ``total_cents`` is not an ``int``, if ``member_ids`` is not an
            iterable of ids (a bare ``str`` or a mapping is rejected rather than read as
            one), or if a member id is not a ``str``.
        InvalidSplit: if ``total_cents`` is not strictly positive or is above
            ``MAX_CENTS``, if the member list is empty, if a member id is empty, or if a
            member appears more than once.
    """
    total = _require_total(total_cents)
    ordered = _ordered_from_iterable(member_ids)
    return _allocate(total, ordered, [1] * len(ordered))


def split_by_weight(
    total_cents: int, weights: Mapping[MemberId, int]
) -> tuple[Allocation, ...]:
    """Split ``total_cents`` across members in proportion to integer ``weights``.

    Two people on a 1 and 2 weighting split $10 into $3.33 and $6.67, which resolves to
    3 and 7 cents of leftover-adjusted shares. Weights are integers on purpose: a share
    of one and a half is expressed as weights 3 and 2, so no fraction ever enters the
    money path.

    Invariants:

    * the allocations sum to ``total_cents`` exactly
    * every share is within one cent of its exact quota, by the largest-remainder rule
    * a weight of zero is allocated zero cents and keeps that member on the expense
    * the result is ordered by ``member_id``

    Raises:
        TypeError: if ``total_cents`` is not an ``int``, if ``weights`` is not a
            mapping, if a member id is not a ``str``, or if a weight is not an ``int``.
        InvalidSplit: if ``total_cents`` is not strictly positive or is above
            ``MAX_CENTS``, if ``weights`` is empty, if a member id is empty, if a weight
            is negative, or if the weights sum to zero.
    """
    total = _require_total(total_cents)
    ordered, values = _ordered_from_mapping(weights, "weight")
    return _allocate(total, ordered, values)


def split_exact(
    total_cents: int, amounts: Mapping[MemberId, int]
) -> tuple[Allocation, ...]:
    """Return the exact per-member ``amounts`` a caller has already decided.

    There is no remainder to assign here, so the only question is whether the amounts
    add up. They must, exactly: the resolver never absorbs a difference into somebody's
    share and never adjusts the total to fit. A mismatch is a rejection carrying both
    figures, so the entry screen can tell the user by how much they are out.

    Invariants:

    * the allocations sum to ``total_cents`` exactly, or the call raises
    * amounts are returned unchanged, ordered by ``member_id``
    * an amount of zero is accepted

    Raises:
        TypeError: if ``total_cents`` is not an ``int``, if ``amounts`` is not a
            mapping, if a member id is not a ``str``, or if an amount is not an ``int``.
        InvalidSplit: if ``total_cents`` is not strictly positive or is above
            ``MAX_CENTS``, if ``amounts`` is empty, if a member id is empty, if an
            amount is negative, or if the amounts do not sum to the total.
    """
    total = _require_total(total_cents)
    ordered, values = _ordered_from_mapping(amounts, "amount")
    allocated = sum(values)
    if allocated != total:
        raise InvalidSplit(
            f"exact amounts sum to {allocated}, not the total {total}"
        )
    return tuple(
        Allocation(member_id, cents)
        for member_id, cents in zip(ordered, values, strict=True)
    )


def _allocate(
    total_cents: int, ordered_member_ids: tuple[MemberId, ...], weights: list[int]
) -> tuple[Allocation, ...]:
    """Allocate ``total_cents`` by weight, largest remainder first, rotating ties.

    The one place the remainder rule is written. ``split_equally`` reaches it with every
    weight set to 1, so the two fair-share modes cannot drift apart.

    ``weights`` is positional-aligned with ``ordered_member_ids``, and both have already
    been validated. The leftover is always smaller than the number of members, because
    each member's discarded remainder is smaller than ``weight_total``.
    """
    count = len(ordered_member_ids)
    weight_total = sum(weights)
    if weight_total == 0:
        raise InvalidSplit(
            "weights sum to zero, so there is no share to divide the total into"
        )

    shares = []
    remainders = []
    for weight in weights:
        share, remainder = divmod(total_cents * weight, weight_total)
        shares.append(share)
        remainders.append(remainder)

    leftover = total_cents - sum(shares)
    offset = (total_cents // count) % count
    by_claim = sorted(
        range(count),
        key=lambda index: (-remainders[index], (index - offset) % count),
    )
    for index in by_claim[:leftover]:
        shares[index] += 1

    return tuple(
        Allocation(member_id, cents)
        for member_id, cents in zip(ordered_member_ids, shares, strict=True)
    )


def _require_total(total_cents: object) -> int:
    """Return ``total_cents`` if it is a storable, strictly positive ``int``, else raise.

    Strictly positive matches ``ExpenseEvent.total_cents``, so the resolver cannot hand
    back allocations for an expense that would not construct. The upper bound is the one
    ``parse_amount`` enforces, which keeps every allocation inside a signed 64-bit
    column.
    """
    if isinstance(total_cents, bool) or not isinstance(total_cents, int):
        raise TypeError(
            f"total_cents must be an int, got {type(total_cents).__name__}: "
            f"{total_cents!r}"
        )
    if total_cents <= 0:
        raise InvalidSplit(
            f"total_cents must be strictly positive, got {total_cents}"
        )
    if total_cents > MAX_CENTS:
        raise InvalidSplit(f"total_cents is too large to store: {total_cents}")
    return total_cents


def _require_member_id(value: object) -> MemberId:
    """Return ``value`` if it is a non-empty ``str``, else raise.

    ``Allocation`` guards this too, but the resolver checks first so every rejection it
    makes carries one exception type, and so an unusable id fails before any arithmetic
    is done with it.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"member id must be a str, got {type(value).__name__}: {value!r}"
        )
    if not value:
        raise InvalidSplit("member id must be a non-empty id")
    return MemberId(value)


def _ordered_from_iterable(member_ids: object) -> tuple[MemberId, ...]:
    """Validate a member list and return it sorted by id.

    A ``str`` is an iterable of one-character strings and a ``Mapping`` is an iterable
    of its keys, so both are rejected outright rather than silently read as a member
    list. Duplicates are rejected because ``ExpenseEvent`` rejects duplicate
    allocations, and the resolver must not manufacture what the event will refuse.
    """
    if isinstance(member_ids, (str, bytes, bytearray, Mapping)):
        raise TypeError(
            f"member_ids must be a list of ids, got {type(member_ids).__name__}: "
            f"{member_ids!r}"
        )
    if not isinstance(member_ids, Iterable):
        raise TypeError(
            f"member_ids must be a list of ids, got {type(member_ids).__name__}: "
            f"{member_ids!r}"
        )
    ordered = tuple(_require_member_id(value) for value in member_ids)
    if not ordered:
        raise InvalidSplit("a split needs at least one member")
    if len(set(ordered)) != len(ordered):
        raise InvalidSplit(
            f"member_ids names a member more than once: {list(ordered)}"
        )
    return tuple(sorted(ordered))


def _ordered_from_mapping(
    mapping: object, field: str
) -> tuple[tuple[MemberId, ...], list[int]]:
    """Validate a member-to-int mapping and return its ids and values, id-ordered.

    Returns the ids sorted and the values aligned to them, so every mode produces its
    allocations in the same order regardless of how the caller built the mapping. A
    mapping cannot carry a duplicate key, so there is no duplicate check here.
    """
    if not isinstance(mapping, Mapping):
        raise TypeError(
            f"{field}s must be a mapping of member id to int, got "
            f"{type(mapping).__name__}: {mapping!r}"
        )
    if not mapping:
        raise InvalidSplit("a split needs at least one member")

    validated: dict[MemberId, int] = {}
    for key, value in mapping.items():
        member_id = _require_member_id(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                f"{field} for {member_id!r} must be an int, got "
                f"{type(value).__name__}: {value!r}"
            )
        if value < 0:
            raise InvalidSplit(
                f"{field} for {member_id!r} must be zero or positive, got {value}"
            )
        validated[member_id] = value

    ordered = tuple(sorted(validated))
    return ordered, [validated[member_id] for member_id in ordered]
