"""Debt simplification: net positions become a short list of suggested transfers.

Nothing here is stored. ``simplify_debts`` is a pure function of the ``Balances`` it is
handed, so the same derived position always produces the same plan, in any process, and
there is never a cached plan to go stale. It reads no events, opens no store and never
recomputes a balance.

**Fewest transfers is a greedy result with a stated bound, not a proven minimum.** The
algorithm repeatedly pays the largest remaining debtor's balance to the largest
remaining creditor. Each round settles at least one member completely and the final
round settles two, so a group with ``n`` members holding a non-zero net needs at most
``n - 1`` transfers; and because every such member must appear in at least one transfer,
it needs at least ``max(debtors, creditors)``. The honest statement, and the one every
consumer is written against: *this is the fewest transfers this algorithm finds, at most
``n - 1``, and at least ``max(debtors, creditors)``. It is not guaranteed to be the
smallest plan that exists.* Minimising exactly is subset-sum in disguise, so no
docstring, comment or test in this codebase may claim minimality; where the two bounds
meet, as with one debtor against many creditors, the result happens to be minimal, and
a fixture in the suite pins a five-member case where it is not.

**Ties are broken by ascending ``member_id``, plainly, and there is no rotation.** The
split resolver faced a superficially similar choice with leftover cents and chose a
rotation; that precedent is deliberately not followed here, because the two ties decide
different things. There, the tie decides *who pays an extra cent*, so a plain sorted
tie-break would make the same flatmate pay one cent more forever. Here the tie decides
*who pays whom*, never how much anyone pays: each member's total outlay is fixed by
their ``net`` before any matching happens, so no member is a cent better or worse off
under any tie-break and there is nothing to rotate away from. A rotation would actively
hurt, because a payer taps a suggested transfer to record a settlement against it, and a
list that reshuffles between two page loads for no change in the underlying debts makes
that action feel unsafe. Stability is the requirement.

**Provenance is the deliverable, not a decoration.** Netting discards exactly the
information that "show me how you got there" needs, so every transfer keeps a pointer
back to the pairwise debts it absorbed, as ``Balances.pairwise`` keys left unchanged. It
keeps two such lists, because one payment raises two questions and one list answers only
one of them:

* ``payer_debts`` answers "why am I paying at all, and why this much?" Its rows all name
  the payer as debtor and their amounts sum to exactly the transfer amount.
* ``receiver_credits`` answers "why *them*, when I never bought anything together?" Its
  rows all name the receiver as creditor and their amounts sum to exactly the transfer
  amount too.

That is not double counting. They are two views of one payment from its two ends, kept
in separate books and attributed over separate remaining maps.

Two consequences of netting, stated here so nobody files them as bugs: a single pairwise
debt may be **split across two transfers**, each row carrying the whole debt as
``debt_total`` so a drill-down can say "400 of the 1000 you owe Ali"; and a pairwise
debt may be **absorbed by nothing at all**, which is what a pure cycle looks like. Cents
left unattributed on a debt are exactly the cents netting cancelled against something
the payer was owed. That leftover is a fact about the group, not a gap.

Dependency direction: this module imports from ``money``, ``events`` and ``balances``;
none of them knows it exists, and the split resolver and the store are modules it never
touches. Nothing here divides a total and nothing here reads a database.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .balances import Balances
from .events import GroupId, MemberId
from .money import Currency, CurrencyMismatch, DomainError, Money

__all__ = [
    "AbsorbedDebt",
    "InvalidBalances",
    "Transfer",
    "TransferPlan",
    "simplify_debts",
]

_Pair = tuple[MemberId, MemberId]
_Move = tuple[MemberId, MemberId, int]
_Row = tuple[_Pair, int]


class InvalidBalances(DomainError):
    """Raised when a ``Balances`` cannot be simplified into a plan.

    ``Balances`` is a public dataclass with no ``__post_init__``, so a hand-built one
    can break invariants ``derive_balances`` would never break: a ``net`` that does not
    sum to zero, a debt that is zero or negative, a pair stored in both directions, a
    member who owes themselves, or a ``net`` that disagrees with the ``pairwise`` map it
    is supposed to summarise. Producing a plausible plan from any of those would be a
    money bug, so each is refused by name. One named type for every value rejection in
    this module, so the HTTP layer keeps mapping the whole domain family to a single
    response. A wrong Python type raises ``TypeError`` instead: that is a programming
    error, not rejected user input.
    """


@dataclass(frozen=True, slots=True)
class AbsorbedDebt:
    """One pairwise debt, and the part of it a single transfer discharges.

    Invariants, all established by ``simplify_debts``:

    * ``pair`` is a key of the ``Balances.pairwise`` it came from, unchanged. That key
      is the stable identity of a pairwise debt and the whole handoff to the
      drill-down, which takes it and queries the store for the expenses behind it.
      Nothing is copied out of the expense log here.
    * ``0 < amount.cents <= debt_total.cents``, and ``debt_total`` is the whole debt as
      ``Balances.pairwise`` states it, so a row can say "400 of the 1000 you owe Ali"
      without a second lookup.
    * both amounts carry the currency of the balances.

    A row records what a transfer covers, never a schedule: a suggested transfer is
    confirmed in full or not at all.
    """

    debtor: MemberId
    creditor: MemberId
    amount: Money
    debt_total: Money

    @property
    def pair(self) -> _Pair:
        """Return ``(debtor, creditor)``, exactly a ``Balances.pairwise`` key."""
        return (self.debtor, self.creditor)


@dataclass(frozen=True, slots=True)
class Transfer:
    """One suggested payment, with both ends of its provenance.

    Invariants:

    * ``amount`` is strictly positive and ``from_member_id != to_member_id``.
    * ``payer_debts`` sums to exactly ``amount`` in cents, and every row names
      ``from_member_id`` as its debtor.
    * ``receiver_credits`` sums to exactly ``amount`` in cents too, and every row names
      ``to_member_id`` as its creditor. The two lists are separate books over one
      payment, not a duplicate of each other.
    * both lists are non-empty and sorted ascending by ``(debtor, creditor)``, and a
      given pair appears at most once within each. The same pair may appear in both,
      which is the two-ended view.

    The field names match ``SettlementEvent``'s, so a tapped transfer maps onto a
    settlement event without renaming anything. A transfer is a suggestion, so it
    carries no id and no timestamp and must not grow either.
    """

    from_member_id: MemberId
    to_member_id: MemberId
    amount: Money
    payer_debts: tuple[AbsorbedDebt, ...]
    receiver_credits: tuple[AbsorbedDebt, ...]


@dataclass(frozen=True, slots=True)
class TransferPlan:
    """Every suggested transfer that settles one group, in one currency.

    ``transfers`` is sorted ascending by ``(from_member_id, to_member_id)``, a pair
    appears at most once and never alongside its reverse, and the plan is empty for a
    group that is already settled. Empty is a real answer, not an error and not
    ``None``: a pure cycle holds live pairwise debts and still needs no payment.

    Equality is by value and the whole structure is tuples, so two plans compare with
    ``==`` and transfers collect into a set. This differs from ``Balances``, which holds
    mappings and cannot be hashed.
    """

    group_id: GroupId
    currency: Currency
    transfers: tuple[Transfer, ...]


def simplify_debts(balances: Balances) -> TransferPlan:
    """Turn one group's derived position into the transfers that would settle it.

    Takes a ``Balances`` and nothing else: it already carries the group and the
    currency, and a second source for either would be a second thing to disagree.

    ``net`` decides who pays whom and how much; ``pairwise`` is the vocabulary of
    provenance. The two are related by the identity this function leans on throughout
    and validates before it starts: for every member, ``net[m] == in(m) - out(m)``,
    where ``in`` is what they are owed and ``out`` is what they owe.

    Invariants established here, all of them eagerly, so no later layer re-checks them:

    * every transfer amount is strictly positive and no member pays themselves
    * a member with a negative ``net`` pays exactly what they owe and receives nothing;
      a member with a positive ``net`` receives exactly what they are owed and pays
      nothing; a member at zero, or absent from ``net``, appears in no transfer at all,
      though they may still appear inside provenance rows as a counterparty
    * ``max(debtors, creditors) <= len(transfers) <= max(0, debtors + creditors - 1)``,
      which is the bound the module docstring states and not a claim of minimality
    * both provenance lists of every transfer sum to exactly that transfer's amount,
      no pairwise debt is over-absorbed on either side, and every row's ``pair`` is a
      real ``Balances.pairwise`` key carrying that debt's true total

    Settling every transfer it returns and re-folding the log through
    ``derive_balances`` gives a ``net`` of exactly zero for every member. It does *not*
    empty ``pairwise``: simplification converts a chain into a residual cycle, and those
    live debts cancelling to zero in ``net`` are the visible price of netting.

    Arithmetic is integer cents throughout, accumulated in plain ``int`` and wrapped
    into ``Money`` once, when a row is built. There is no division anywhere in this
    module: the algorithm only compares, adds and subtracts, so no remainder can arise
    and no rounding rule may be invented here. Dividing a total across people is the
    split resolver's job and happened long before a balance reached this function.

    No bound is applied to an amount. A plan is derived and never stored, so there is no
    column to overflow, following the reasoning the balance fold already recorded.

    Raises:
        TypeError: if ``balances`` is not a ``Balances``.
        InvalidBalances: if ``net`` does not sum to zero, if a pairwise debt is not
            strictly positive, if a pair appears in both directions or names one member
            twice, or if ``net`` and ``pairwise`` disagree about a member.
        CurrencyMismatch: if a ``Money`` in ``net`` or ``pairwise`` is in another
            currency. No second name is invented for it.
    """
    if not isinstance(balances, Balances):
        raise TypeError(
            f"simplify_debts takes Balances, got {type(balances).__name__}: "
            f"{balances!r}"
        )

    currency = balances.currency
    net = _validated_net(balances, currency)
    debts = _validated_debts(balances, currency)
    _require_agreement(net, debts)

    moves = _greedy(net)
    payer_rows = _absorb(moves, debts, payer_side=True)
    receiver_rows = _absorb(moves, debts, payer_side=False)

    return TransferPlan(
        group_id=balances.group_id,
        currency=currency,
        transfers=tuple(
            Transfer(
                from_member_id=payer,
                to_member_id=receiver,
                amount=Money(amount, currency),
                payer_debts=_absorbed(payer_rows[(payer, receiver)], debts, currency),
                receiver_credits=_absorbed(
                    receiver_rows[(payer, receiver)], debts, currency
                ),
            )
            for payer, receiver, amount in moves
        ),
    )


def _validated_net(balances: Balances, currency: Currency) -> dict[MemberId, int]:
    """Return ``net`` as plain cents by member ascending, or raise.

    The cents must sum to exactly zero. Money only ever moves between members, so a
    residue means the value was not derived by the fold, and both the greedy's
    termination and the settle-to-zero guarantee depend on it: a non-zero residue would
    leave one pool non-empty with nothing to pair it against.
    """
    net = {
        member_id: _cents(
            balances.net[member_id], currency, f"the net position of {member_id!r}"
        )
        for member_id in sorted(balances.net)
    }
    residue = sum(net.values())
    if residue != 0:
        raise InvalidBalances(
            f"net positions must sum to zero cents, but they leave a residue of "
            f"{residue}"
        )
    return net


def _validated_debts(balances: Balances, currency: Currency) -> dict[_Pair, int]:
    """Return ``pairwise`` as plain cents by ``(debtor, creditor)`` ascending, or raise.

    Three rejections, each naming the offending pair. A zero or negative debt is not a
    debt and would put a settled or backwards pair into a provenance row. A self pair is
    meaningless. A pair held in both directions has no single answer to "what is owed",
    and provenance would attribute cents to both halves of it.

    The self-pair check runs first on purpose: ``(m, m)`` is trivially its own reverse,
    so the both-directions check would otherwise report it under the wrong name.
    """
    debts: dict[_Pair, int] = {}
    for pair in sorted(balances.pairwise):
        debtor, creditor = pair
        cents = _cents(balances.pairwise[pair], currency, f"the debt {pair!r}")
        if debtor == creditor:
            raise InvalidBalances(f"a member cannot owe themselves: {pair!r}")
        if cents <= 0:
            raise InvalidBalances(
                f"a pairwise debt must be strictly positive, but {pair!r} is {cents}"
            )
        if (creditor, debtor) in balances.pairwise:
            raise InvalidBalances(
                f"a pair may be stored in only one direction, but {pair!r} and "
                f"{(creditor, debtor)!r} are both present"
            )
        debts[pair] = cents
    return debts


def _require_agreement(net: Mapping[MemberId, int], debts: Mapping[_Pair, int]) -> None:
    """Raise unless ``net[m] == in(m) - out(m)`` for every member either map mentions.

    The feasibility of provenance rests entirely on this identity. A net debtor pays
    ``out(m) - in(m)``, which is at most ``out(m)``, so they always hold enough of their
    own outgoing debt to source every cent they pay, and a net creditor is the mirror
    image. If the two maps disagree, attribution can run out of debts to point at, so
    the identity is checked rather than assumed.

    A member absent from ``net`` is read as zero, which is what ``net_for`` already
    promises: never having been seen and being square with the group are the same
    position.
    """
    owed_to: dict[MemberId, int] = {}
    owes: dict[MemberId, int] = {}
    for (debtor, creditor), cents in debts.items():
        owes[debtor] = owes.get(debtor, 0) + cents
        owed_to[creditor] = owed_to.get(creditor, 0) + cents

    for member_id in sorted(set(net) | set(owes) | set(owed_to)):
        stated = net.get(member_id, 0)
        implied = owed_to.get(member_id, 0) - owes.get(member_id, 0)
        if stated != implied:
            raise InvalidBalances(
                f"net and pairwise disagree about {member_id!r}: net says {stated} "
                f"cents and the pairwise debts imply {implied}"
            )


def _cents(amount: Money, currency: Currency, label: str) -> int:
    """Return ``amount``'s cents, or raise ``CurrencyMismatch``.

    Adding NZD cents to AUD cents is exactly what that exception exists for, and one
    ``Balances`` is one group in one currency, so a stray amount is refused rather than
    reconciled.
    """
    if amount.currency != currency:
        raise CurrencyMismatch(
            f"cannot combine {amount.currency.code} and {currency.code}: {label} is "
            f"in {amount.currency.code} and the balances are in {currency.code}"
        )
    return amount.cents


def _greedy(net: Mapping[MemberId, int]) -> tuple[_Move, ...]:
    """Pair the largest debtor with the largest creditor until both pools empty.

    Members at zero, and members the ``net`` map has never seen, are not in either pool
    and so appear in no transfer. Both pools empty at the same moment because ``net``
    sums to zero, which is validated before this runs.

    Each round pays the smaller of the two outstanding amounts, so at least one of the
    two members is retired, and the last round retires both. That is where the ``n - 1``
    bound comes from, and it is also why a pair can never be emitted twice and why the
    reverse of an emitted pair never appears: a member is a debtor or a creditor, never
    both.

    Ties go to the smaller ``member_id``, and the result is returned sorted by
    ``(from_member_id, to_member_id)``, so two readers of one ledger see one list.
    """
    owing = {member_id: -cents for member_id, cents in net.items() if cents < 0}
    owed = {member_id: cents for member_id, cents in net.items() if cents > 0}

    moves: list[_Move] = []
    while owing and owed:
        payer = _largest(owing)
        receiver = _largest(owed)
        amount = min(owing[payer], owed[receiver])
        moves.append((payer, receiver, amount))
        owing[payer] -= amount
        owed[receiver] -= amount
        if owing[payer] == 0:
            del owing[payer]
        if owed[receiver] == 0:
            del owed[receiver]
    return tuple(sorted(moves, key=lambda move: (move[0], move[1])))


def _largest(pool: Mapping[MemberId, int]) -> MemberId:
    """Return the member holding the most, the smaller id winning a tie.

    The pool is sorted before it is walked rather than iterated in insertion order, so
    nothing about how the dict was built, and no per-process string hash, can reach the
    answer.
    """
    return sorted(pool, key=lambda member_id: (-pool[member_id], member_id))[0]


def _absorb(
    moves: tuple[_Move, ...],
    debts: Mapping[_Pair, int],
    *,
    payer_side: bool,
) -> dict[_Pair, tuple[_Row, ...]]:
    """Attribute every cent of every transfer to the pairwise debts it discharges.

    Run once per side over its own remaining map, both starting from ``pairwise``. On
    the payer side a transfer may only draw on debts its payer owes; on the receiver
    side, only on debts owed to its receiver. Those two candidate sets are disjoint
    between members, because a key names exactly one debtor and exactly one creditor, so
    two payers can never compete for the same debt.

    Two passes over the transfer list, both in ``(from_member_id, to_member_id)`` order:

    1. **The direct debt.** For a transfer ``d -> c``, absorb ``min(transfer, debt)`` of
       the key ``(d, c)`` if there is one. Every transfer claims its own direct debt
       before anything else touches it, which is what makes the simple case read
       perfectly: one debt between two people produces one transfer whose provenance is
       that debt and nothing else.
    2. **The rest.** While a transfer still has unattributed cents, take its member's
       key with the largest remaining capacity, ties broken by the ascending id of the
       counterparty, and absorb what is needed. Repeat.

    The two passes cannot collide within one transfer: if a transfer still needs cents
    after pass one, its direct key was drained to zero, so pass two can never pick it
    again and no key appears twice in one transfer's rows.

    Pass two always finds a key to draw on, because a net debtor pays at most the total
    they owe and a net creditor receives at most the total they are owed. That is the
    identity ``_require_agreement`` has already established; without it this loop could
    run out of debts to point at.
    """
    remaining = dict(debts)
    keys = [(payer, receiver) for payer, receiver, _ in moves]
    unattributed = {(payer, receiver): amount for payer, receiver, amount in moves}
    rows: dict[_Pair, list[_Row]] = {key: [] for key in keys}

    for key in keys:
        if remaining.get(key, 0) > 0:
            _take(key, key, remaining, unattributed, rows)

    for key in keys:
        member_id = key[0] if payer_side else key[1]
        while unattributed[key] > 0:
            _take(
                key,
                _fullest(remaining, member_id, payer_side=payer_side),
                remaining,
                unattributed,
                rows,
            )

    return {key: tuple(sorted(value)) for key, value in rows.items()}


def _take(
    key: _Pair,
    pair: _Pair,
    remaining: dict[_Pair, int],
    unattributed: dict[_Pair, int],
    rows: dict[_Pair, list[_Row]],
) -> None:
    """Move as much of ``pair`` as the transfer ``key`` still needs onto its row list.

    Bounded by both sides, so a debt is never over-absorbed and a transfer never
    over-explained: whichever of the two runs out first ends the row.
    """
    taken = min(unattributed[key], remaining[pair])
    rows[key].append((pair, taken))
    remaining[pair] -= taken
    unattributed[key] -= taken


def _fullest(
    remaining: Mapping[_Pair, int], member_id: MemberId, *, payer_side: bool
) -> _Pair:
    """Return ``member_id``'s live debt with the most left in it.

    Outgoing debts on the payer side, incoming debts on the receiver side. Candidates
    share the member's own end of the key, so ordering by ``(-remaining, pair)`` breaks
    a tie on the counterparty's id ascending, which is the same rule read from either
    side.

    The map is sorted before it is walked, so no dict insertion order and no per-process
    string hash reaches the plan.
    """
    end = 0 if payer_side else 1
    candidates = [
        pair
        for pair in sorted(remaining)
        if pair[end] == member_id and remaining[pair] > 0
    ]
    return sorted(candidates, key=lambda pair: (-remaining[pair], pair))[0]


def _absorbed(
    rows: tuple[_Row, ...], debts: Mapping[_Pair, int], currency: Currency
) -> tuple[AbsorbedDebt, ...]:
    """Wrap attributed cents into ``AbsorbedDebt`` rows, already in key order.

    Each row restates the whole debt from ``pairwise`` rather than the part left over,
    so a drill-down can read "400 of the 1000 you owe Ali" straight off one row.
    """
    return tuple(
        AbsorbedDebt(
            debtor=pair[0],
            creditor=pair[1],
            amount=Money(cents, currency),
            debt_total=Money(debts[pair], currency),
        )
        for pair, cents in rows
    )
