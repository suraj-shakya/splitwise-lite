"""Split resolver: a total and a mode become explicit per-person allocations.

The spec collapses all three split rules into one shape: an expense stores a list of
``(member, cents)`` and nothing else. This module is where that collapse happens.
Equal, subset and uneven splits are all resolved to explicit cents here, at entry time,
so the ledger carries no rule types and there is one rounding problem instead of three.

The three split rules ``plans/spec.md`` locks map onto two functions:

* equal across everyone, and equal across a subset, are both ``split_equally`` over the
  member list the caller assembles
* uneven shares are ``split_exact``

**The remainder rule.** A total rarely divides evenly, so somebody has to absorb the
leftover cents. The one fair-share mode goes through one allocator, ``_allocate``,
which uses the largest-remainder method on integer arithmetic: each member's floor
share is ``(total * weight) // weight_total`` with remainder
``(total * weight) % weight_total``, and the leftover cents go one each to the largest
remainders.

``_allocate`` still takes a weight per member, and its signature, its guard and its
arithmetic are deliberately left byte for byte as issue #78 found them: the rule it
implements is a locked modelling decision in ``plans/spec.md``, not an implementation
detail of the mode that used to exercise it. Its docstring prose was corrected, because
one sentence of it counted two fair-share modes; the dated resolution under criterion A6
of ``plans/tasks/78-split-by-weight-has-no-product-behind-it.md`` records why that was
in scope and the arithmetic was not, and which two mutation records anchor into which
lines.

One consequence to state rather than tidy away: ``_allocate``'s weights-sum-to-zero
guard can no longer fire, because ``split_equally`` is its only caller and passes
``[1] * n`` over a list ``_ordered_from_iterable`` has already refused to leave empty,
so the weight total is at least 1. ``tests/test_error_messages.py`` carries it as an
unreachable row with the same reason.

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

**A refusal names the money, not the cents.** Every refusal this module makes about an
amount is rendered by ``money.format_amount``, so somebody who typed ``10.00`` is told
about ``10.00`` rather than about ``1000``. That is the only reason each resolver is
handed a ``currency`` it never otherwise uses: ``format_amount`` takes ``Money``, and
``Money`` cannot be built without one. The sentence is written here rather than in the
HTTP layer so that every caller gets it, not only the one that speaks JSON. The
argument is keyword-only and has no default, because a defaulted currency in the money
path is a bug waiting for a second currency.

Dependency direction: this module imports from ``money`` and ``events``; neither of them
knows it exists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .events import Allocation, MemberId
from .money import MAX_CENTS, Currency, DomainError, Money, format_amount

__all__ = [
    "InvalidSplit",
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
    total_cents: int, member_ids: Iterable[MemberId], *, currency: Currency
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

    ``currency`` is never allocated, compared or printed on its own: it is here only so
    a refusal about the total can be written in money rather than in cents. See the
    module docstring for why it has no default.

    Raises:
        TypeError: if ``currency`` is not a ``Currency``, if ``total_cents`` is not an
            ``int``, if ``member_ids`` is not an iterable of ids (a bare ``str`` or a
            mapping is rejected rather than read as one), or if a member id is not a
            ``str``.
        InvalidSplit: if ``total_cents`` is not strictly positive or is above
            ``MAX_CENTS``, if the member list is empty, if a member id is empty, or if a
            member appears more than once.
    """
    _require_currency(currency)
    total = _require_total(total_cents, currency)
    ordered = _ordered_from_iterable(member_ids)
    return _allocate(total, ordered, [1] * len(ordered))


def split_exact(
    total_cents: int, amounts: Mapping[MemberId, int], *, currency: Currency
) -> tuple[Allocation, ...]:
    """Return the exact per-member ``amounts`` a caller has already decided.

    There is no remainder to assign here, so the only question is whether the amounts
    add up. They must, exactly: the resolver never absorbs a difference into somebody's
    share and never adjusts the total to fit.

    A mismatch is refused in ``currency``, naming what the shares came to and what the
    total was ("the shares add up to 9.50, but the total is 10.00"), so the entry screen
    can show that sentence as it stands and the person can see by how much they are out.
    Both figures are named and the difference between them is not: that would be a third
    figure, and a claim the shares' own sum does not make. ``shares`` and ``total`` are
    the words the screen already uses.

    Invariants:

    * the allocations sum to ``total_cents`` exactly, or the call raises
    * amounts are returned unchanged, ordered by ``member_id``
    * an amount of zero is accepted

    Raises:
        TypeError: if ``currency`` is not a ``Currency``, if ``total_cents`` is not an
            ``int``, if ``amounts`` is not a mapping, if a member id is not a ``str``,
            or if an amount is not an ``int``.
        InvalidSplit: if ``total_cents`` is not strictly positive or is above
            ``MAX_CENTS``, if ``amounts`` is empty, if a member id is empty, if an
            amount is negative, or if the amounts do not sum to the total.
    """
    _require_currency(currency)
    total = _require_total(total_cents, currency)
    ordered, values = _ordered_from_mapping(amounts, "amount")
    allocated = sum(values)
    if allocated != total:
        raise InvalidSplit(
            f"the shares add up to {_formatted(allocated, currency)}, "
            f"but the total is {_formatted(total, currency)}"
        )
    return tuple(
        Allocation(member_id, cents)
        for member_id, cents in zip(ordered, values, strict=True)
    )


def _allocate(
    total_cents: int, ordered_member_ids: tuple[MemberId, ...], weights: list[int]
) -> tuple[Allocation, ...]:
    """Allocate ``total_cents`` by weight, largest remainder first, rotating ties.

    The one place the remainder rule is written. ``split_equally`` has been its only
    caller since issue #78 removed the weighted mode, and reaches it with every weight
    set to 1. It still takes a weight per member, and the arithmetic below is unchanged,
    because the rule is a locked modelling decision in ``plans/spec.md`` rather than an
    implementation detail of the caller that used to exercise it. One consequence of
    having a single caller: the guard below can no longer fire, and the module docstring
    says why.

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


def _formatted(cents: int, currency: Currency) -> str:
    """Render ``cents`` as money, through ``money.py``'s one display edge.

    ``format_amount`` is that edge, and there is deliberately no cents-only variant of
    it to reach for instead. Every refusal this module makes about an amount comes
    through here, so a person who typed ``10.00`` is refused in ``10.00``. It mirrors
    ``web.py::_amount`` on purpose: the two cannot share code, because the domain layer
    may not import the web layer, but they go through the same one function.
    """
    return format_amount(Money(cents, currency))


def _require_currency(value: object) -> Currency:
    """Return ``value`` if it is a ``Currency``, else raise ``TypeError``.

    Called on the first line of all three resolvers, before the total is looked at, so a
    wrong currency is a ``TypeError`` a programmer sees rather than an ``InvalidSplit``
    dressed up as somebody's rejected entry. Ordering is the whole point of the call
    site: ``_require_total`` reaches ``_formatted`` on a refusable total, and ``Money``
    would reject the same currency a moment later with a message of its own, so without
    this the resolver would refuse in the right family for the wrong reason.

    Body and message are ``balances.py::_require_currency``'s, deliberately and to the
    character. The two cannot share code: neither domain module may import the other,
    which is what ``test_split_imports_only_money_and_events_from_the_package`` holds
    ``split.py`` to. Same compulsion as ``_formatted`` and ``web.py::_amount``.
    """
    if not isinstance(value, Currency):
        raise TypeError(
            f"currency must be a Currency, got {type(value).__name__}: {value!r}"
        )
    return value


def _require_total(total_cents: object, currency: Currency) -> int:
    """Return ``total_cents`` if it is a storable, strictly positive ``int``, else raise.

    Strictly positive matches ``ExpenseEvent.total_cents``, so the resolver cannot hand
    back allocations for an expense that would not construct. The upper bound is the one
    ``parse_amount`` enforces, which keeps every allocation inside a signed 64-bit
    column.

    Both rejections name the amount in ``currency``, through ``_formatted``, because
    both reach a person: "the amount must be more than zero, but it is 0.00" and "the
    amount is too large to record: 92,233,720,368,547,758.08". ``amount`` is the word
    the entry screen puts on the field. The two ``TypeError`` messages below keep the
    parameter name on purpose: a wrong Python type is a programming error that becomes a
    generic 500 with a logged traceback, and the reader of that traceback is a
    programmer looking for the parameter.
    """
    if isinstance(total_cents, bool) or not isinstance(total_cents, int):
        raise TypeError(
            f"total_cents must be an int, got {type(total_cents).__name__}: "
            f"{total_cents!r}"
        )
    if total_cents <= 0:
        raise InvalidSplit(
            "the amount must be more than zero, but it is "
            f"{_formatted(total_cents, currency)}"
        )
    if total_cents > MAX_CENTS:
        raise InvalidSplit(
            f"the amount is too large to record: {_formatted(total_cents, currency)}"
        )
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
        # The payload key, not the ids: this is a mapped 400 and no 4xx body this repo
        # sends names a member id. The caller holds the list it sent.
        raise InvalidSplit("member_ids names a member more than once")
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
            # This one keeps the id and the value. A wrong Python type is a
            # programming error, not a refusable request: it is unmapped, so it
            # becomes a generic 500 with the real exception logged, and the reader of
            # that traceback is a programmer who needs to know which entry it was.
            # Same rule as ``_require_total``'s ``TypeError`` above.
            raise TypeError(
                f"{field} for {member_id!r} must be an int, got "
                f"{type(value).__name__}: {value!r}"
            )
        if value < 0:
            # ``InvalidSplit`` is a mapped 400, so the message names the field and
            # nothing else. Issue #78 left this function one caller, so ``field`` is
            # always "amount" and the value is always cents for ``split_exact``. The
            # parameter and the dropped integer both survive that: rendering cents as
            # money would need a ``currency`` here that ``_ordered_from_mapping``
            # deliberately does not take, and the interpolation is the leak issue #61
            # removed, so restoring either is a change a reviewer sees.
            raise InvalidSplit(f"every {field} must be zero or positive")
        validated[member_id] = value

    ordered = tuple(sorted(validated))
    return ordered, [validated[member_id] for member_id in ordered]
