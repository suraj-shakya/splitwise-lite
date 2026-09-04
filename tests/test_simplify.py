"""Tests for debt simplification: a ``Balances`` becomes suggested transfers.

Task 5 of plans/backlog.md, sharpened in plans/tasks/05-debt-simplification.md.

Nothing here asserts that the plan is minimal. The module implements a greedy pass with
a stated bound, and one fixture below pins a five-member case where the greedy takes
four transfers and three exist, so a false optimality claim fails loudly.

Property coverage is standard library rather than hypothesis, matching the dependency
decision tasks 3 and 4 made. Generated ledgers are folded through ``derive_balances``
so the two modules stay in step, and the generator is seeded from a fixed constant so
any failure reproduces from the test alone.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import itertools
import os
import random
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import splitwise_lite
from splitwise_lite import balances as balances_module
from splitwise_lite import events as events_module
from splitwise_lite import money as money_module
from splitwise_lite import simplify as simplify_module
from splitwise_lite import split as split_module
from splitwise_lite import store as store_module
from splitwise_lite.balances import Balances, derive_balances
from splitwise_lite.events import (
    Allocation,
    ExpenseEvent,
    ExpenseId,
    GroupId,
    LedgerEvent,
    MemberId,
    SettlementDecisionEvent,
    SettlementEvent,
    SettlementId,
    SettlementState,
)
from splitwise_lite.money import (
    MAX_CENTS,
    Currency,
    CurrencyMismatch,
    DomainError,
    Money,
)
from splitwise_lite.simplify import (
    AbsorbedDebt,
    InvalidBalances,
    Transfer,
    TransferPlan,
    simplify_debts,
)

AUD = Currency("AUD")
NZD = Currency("NZD")

GROUP = GroupId("group-dinner")

ALI = MemberId("ali")
BO = MemberId("bo")
CASS = MemberId("cass")
DEE = MemberId("dee")
EVE = MemberId("eve")

SEED = 20260905

EPOCH = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

Pair = tuple[MemberId, MemberId]


# --- Fixture builders -------------------------------------------------------


def balances_of(
    net: dict[MemberId, int],
    pairwise: dict[Pair, int],
    *,
    group_id: GroupId = GROUP,
    currency: Currency = AUD,
) -> Balances:
    """A hand-built ``Balances`` holding exactly what it is given.

    ``Balances`` has no ``__post_init__``, so this builder is also how the invalid
    inputs below are constructed: it never repairs or reorders what it is handed.
    """
    return Balances(
        group_id=group_id,
        currency=currency,
        net={member_id: Money(cents, currency) for member_id, cents in net.items()},
        pairwise={pair: Money(cents, currency) for pair, cents in pairwise.items()},
    )


def from_debts(
    pairwise: dict[Pair, int],
    *,
    also: Iterable[MemberId] = (),
    currency: Currency = AUD,
) -> Balances:
    """A consistent ``Balances`` whose ``net`` is derived from ``pairwise``.

    ``also`` names members to place in ``net`` at zero, which is how a fixture puts a
    member who is square with the group into the map rather than leaving them out.
    """
    net = {member_id: 0 for member_id in also}
    for (debtor, creditor), cents in pairwise.items():
        net[debtor] = net.get(debtor, 0) - cents
        net[creditor] = net.get(creditor, 0) + cents
    return balances_of(
        {member_id: net[member_id] for member_id in sorted(net)},
        dict(sorted(pairwise.items())),
        currency=currency,
    )


def moves(plan: TransferPlan) -> list[tuple[str, str, int]]:
    """The plan as plain ``(payer, receiver, cents)`` rows, for exact comparison."""
    return [
        (transfer.from_member_id, transfer.to_member_id, transfer.amount.cents)
        for transfer in plan.transfers
    ]


def rows(debts: tuple[AbsorbedDebt, ...]) -> list[tuple[Pair, int, int]]:
    """Provenance as plain ``(pair, absorbed cents, whole debt cents)`` rows."""
    return [(debt.pair, debt.amount.cents, debt.debt_total.cents) for debt in debts]


# --- Shape and contract -----------------------------------------------------


def test_invalid_balances_is_a_domain_error() -> None:
    assert issubclass(InvalidBalances, DomainError)


@pytest.mark.parametrize(
    ("value_type", "fields"),
    [
        (AbsorbedDebt, ["debtor", "creditor", "amount", "debt_total"]),
        (
            Transfer,
            [
                "from_member_id",
                "to_member_id",
                "amount",
                "payer_debts",
                "receiver_credits",
            ],
        ),
        (TransferPlan, ["group_id", "currency", "transfers"]),
    ],
    ids=["AbsorbedDebt", "Transfer", "TransferPlan"],
)
def test_each_value_type_is_frozen_slotted_and_holds_exactly_its_fields(
    value_type: type, fields: list[str]
) -> None:
    assert dataclasses.is_dataclass(value_type)
    assert value_type.__dataclass_params__.frozen is True
    assert "__slots__" in vars(value_type)
    assert [field.name for field in dataclasses.fields(value_type)] == fields


def test_simplify_debts_takes_one_positional_balances() -> None:
    parameters = list(inspect.signature(simplify_debts).parameters.values())
    assert [parameter.name for parameter in parameters] == ["balances"]
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert isinstance(simplify_debts(from_debts({(BO, ALI): 1000})), TransferPlan)


def test_the_plan_carries_the_group_and_currency_off_the_balances() -> None:
    """No second source for either: a second source is a second thing to disagree."""
    balances = from_debts({(BO, ALI): 1000}, currency=NZD)
    plan = simplify_debts(balances)
    assert plan.group_id == balances.group_id
    assert plan.currency == balances.currency


def test_every_money_in_the_plan_carries_the_currency_of_the_balances() -> None:
    plan = simplify_debts(from_debts(OVERSIZED, currency=NZD))
    for transfer in plan.transfers:
        assert transfer.amount.currency == NZD
        for debt in transfer.payer_debts + transfer.receiver_credits:
            assert debt.amount.currency == NZD
            assert debt.debt_total.currency == NZD


def test_a_plan_compares_by_value_and_hashes_all_the_way_down() -> None:
    """Unlike ``Balances``, which holds mappings and cannot be hashed."""
    balances = from_debts({(BO, ALI): 1000, (ALI, CASS): 400})
    first = simplify_debts(balances)
    second = simplify_debts(balances)
    assert first == second
    assert hash(first) == hash(second)
    assert set(first.transfers) == set(second.transfers)
    assert len({first, second}) == 1


def test_absorbed_debt_pair_is_the_pairwise_key_in_order() -> None:
    debt = AbsorbedDebt(
        debtor=BO, creditor=ALI, amount=Money(1, AUD), debt_total=Money(2, AUD)
    )
    assert debt.pair == (BO, ALI)


def test_every_provenance_pair_is_a_key_of_the_balances_it_came_from() -> None:
    balances = from_debts({(BO, ALI): 1000, (ALI, CASS): 400})
    plan = simplify_debts(balances)
    for transfer in plan.transfers:
        for debt in transfer.payer_debts + transfer.receiver_credits:
            assert debt.pair in balances.pairwise


def test_simplify_debts_does_not_mutate_the_balances_it_is_given() -> None:
    balances = from_debts({(BO, ALI): 1000, (ALI, CASS): 400})
    net_before = dict(balances.net)
    pairwise_before = dict(balances.pairwise)
    simplify_debts(balances)
    assert dict(balances.net) == net_before
    assert dict(balances.pairwise) == pairwise_before


@pytest.mark.parametrize(
    "value",
    [None, 0, "balances", {"net": {}}, [], object()],
    ids=["none", "int", "str", "dict", "list", "object"],
)
def test_anything_that_is_not_a_balances_is_a_type_error(value: object) -> None:
    with pytest.raises(TypeError) as raised:
        simplify_debts(value)
    assert type(value).__name__ in str(raised.value)


# --- Input validation -------------------------------------------------------


def test_a_net_that_does_not_sum_to_zero_is_refused_by_its_residue() -> None:
    """Money only moves between members, so a residue means this was not derived."""
    with pytest.raises(InvalidBalances) as raised:
        simplify_debts(balances_of({ALI: 700, BO: -400}, {(BO, ALI): 400}))
    assert "300" in str(raised.value)


@pytest.mark.parametrize("cents", [0, -100], ids=["zero", "negative"])
def test_a_pairwise_debt_that_is_not_strictly_positive_is_refused(cents: int) -> None:
    with pytest.raises(InvalidBalances) as raised:
        simplify_debts(balances_of({ALI: cents, BO: -cents}, {(BO, ALI): cents}))
    message = str(raised.value)
    assert "bo" in message and "ali" in message


def test_a_pair_stored_in_both_directions_is_refused_naming_both() -> None:
    with pytest.raises(InvalidBalances) as raised:
        simplify_debts(
            balances_of({ALI: 0, BO: 0}, {(BO, ALI): 100, (ALI, BO): 100})
        )
    message = str(raised.value)
    assert "('ali', 'bo')" in message
    assert "('bo', 'ali')" in message


def test_a_member_owing_themselves_is_refused() -> None:
    """Checked before the both-directions rule: ``(m, m)`` is its own reverse."""
    with pytest.raises(InvalidBalances) as raised:
        simplify_debts(balances_of({ALI: 0}, {(ALI, ALI): 100}))
    message = str(raised.value)
    assert "('ali', 'ali')" in message
    assert "themselves" in message


def test_net_and_pairwise_disagreeing_is_refused_naming_both_figures() -> None:
    """The provenance feasibility proof rests on the identity, so it is checked."""
    with pytest.raises(InvalidBalances) as raised:
        simplify_debts(balances_of({ALI: 50, BO: -50}, {(BO, ALI): 100}))
    message = str(raised.value)
    assert "ali" in message
    assert "50" in message
    assert "100" in message


def test_a_member_in_pairwise_but_absent_from_net_still_has_to_agree() -> None:
    with pytest.raises(InvalidBalances) as raised:
        simplify_debts(balances_of({}, {(BO, ALI): 100}))
    assert "100" in str(raised.value)


@pytest.mark.parametrize("field", ["net", "pairwise"], ids=["net", "pairwise"])
def test_a_money_in_another_currency_raises_currency_mismatch(field: str) -> None:
    """No second name is invented for it: this is what ``money.py`` already has."""
    net = {ALI: Money(100, AUD), BO: Money(-100, AUD)}
    pairwise = {(BO, ALI): Money(100, AUD)}
    if field == "net":
        net[ALI] = Money(100, NZD)
    else:
        pairwise[(BO, ALI)] = Money(100, NZD)
    balances = Balances(group_id=GROUP, currency=AUD, net=net, pairwise=pairwise)

    with pytest.raises(CurrencyMismatch) as raised:
        simplify_debts(balances)
    assert "NZD" in str(raised.value) and "AUD" in str(raised.value)


def test_currency_mismatch_is_a_domain_error_like_the_rest() -> None:
    assert issubclass(CurrencyMismatch, DomainError)


def test_validation_is_eager_so_a_rejected_input_yields_no_partial_plan() -> None:
    """The bad member sits alongside a pair that would otherwise produce a transfer."""
    with pytest.raises(InvalidBalances):
        simplify_debts(
            balances_of(
                {ALI: 100, BO: -100, CASS: 0, DEE: 0},
                {(BO, ALI): 100, (DEE, CASS): 0},
            )
        )


# --- The four worked fixtures -----------------------------------------------

# Bo owes Ali 1000 and Ali owes Cass 400, so one debt splits across two transfers.
CHAIN = {(BO, ALI): 1000, (ALI, CASS): 400}

# Bo owes Ali 300, Bo owes Cass 300, Cass owes Ali 300: one transfer twice the size of
# any debt on either provenance list, and Cass nets to zero.
OVERSIZED = {(BO, ALI): 300, (BO, CASS): 300, (CASS, ALI): 300}

# Ali owes Bo, Bo owes Cass, Cass owes Ali, all 500: three live debts, no transfers.
CYCLE = {(ALI, BO): 500, (BO, CASS): 500, (CASS, ALI): 500}

# net: ali -400, bo -200, cass +500, dee +400, eve -300.
NOT_MINIMAL = {(ALI, CASS): 400, (BO, DEE): 200, (EVE, CASS): 100, (EVE, DEE): 200}


def cents(balances: Balances) -> dict[str, int]:
    """The net map as plain cents, for exact integer comparison."""
    return {member_id: money.cents for member_id, money in balances.net.items()}


def test_the_chain_fixture_nets_to_two_transfers_from_one_debtor() -> None:
    """Two transfers with one debtor is the lower bound ``max(1, 2)``, so minimal."""
    balances = from_debts(CHAIN)
    assert cents(balances) == {ALI: 600, BO: -1000, CASS: 400}
    assert moves(simplify_debts(balances)) == [(BO, ALI, 600), (BO, CASS, 400)]


def test_the_oversized_fixture_is_one_transfer_past_a_zero_net_bystander() -> None:
    balances = from_debts(OVERSIZED)
    assert cents(balances) == {ALI: 600, BO: -600, CASS: 0}
    assert moves(simplify_debts(balances)) == [(BO, ALI, 600)]


def test_a_pure_cycle_needs_no_transfers_even_though_debts_are_live() -> None:
    balances = from_debts(CYCLE)
    assert set(cents(balances).values()) == {0}
    assert len(balances.pairwise) == 3
    assert simplify_debts(balances).transfers == ()


def test_the_greedy_takes_four_transfers_where_three_exist() -> None:
    """Five members, and the greedy does not find the shorter plan.

    Three transfers settle this group: ``ali -> dee 400``, ``bo -> cass 200`` and
    ``eve -> cass 300``. The greedy finds four, because it pairs the largest debtor with
    the largest creditor and never looks for a zero-sum block. That is the documented
    behaviour, not a defect, and this test asserts nothing about optimality: the module
    claims a bound, never a minimum.
    """
    balances = from_debts(NOT_MINIMAL)
    assert cents(balances) == {ALI: -400, BO: -200, CASS: 500, DEE: 400, EVE: -300}
    assert moves(simplify_debts(balances)) == [
        (ALI, CASS, 400),
        (BO, CASS, 100),
        (BO, DEE, 100),
        (EVE, DEE, 300),
    ]


# --- The transfer set -------------------------------------------------------


def test_every_transfer_amount_is_positive_and_nobody_pays_themselves() -> None:
    plan = simplify_debts(from_debts(NOT_MINIMAL))
    for transfer in plan.transfers:
        assert transfer.amount.cents > 0
        assert transfer.from_member_id != transfer.to_member_id


def test_transfers_are_sorted_by_payer_then_receiver() -> None:
    plan = simplify_debts(from_debts(NOT_MINIMAL))
    keys = [(t.from_member_id, t.to_member_id) for t in plan.transfers]
    assert keys == sorted(keys)


def test_a_pair_appears_once_and_never_alongside_its_reverse() -> None:
    """No member is both a debtor and a creditor, and every round retires one."""
    plan = simplify_debts(from_debts(NOT_MINIMAL))
    keys = [(t.from_member_id, t.to_member_id) for t in plan.transfers]
    assert len(set(keys)) == len(keys)
    assert not any((to, frm) in set(keys) for frm, to in keys)


def test_the_transfers_total_the_positive_net_and_the_negative_net() -> None:
    balances = from_debts(NOT_MINIMAL)
    plan = simplify_debts(balances)
    positions = cents(balances)
    paid = sum(transfer.amount.cents for transfer in plan.transfers)
    assert paid == sum(c for c in positions.values() if c > 0)
    assert paid == -sum(c for c in positions.values() if c < 0)


def test_the_plan_settles_every_member_to_zero_on_the_plan_itself() -> None:
    """The backlog asks that simplified transfers settle the group to zero.

    The identity is ``net[m] + paid(m) - received(m) == 0``. The acceptance criteria
    write it with ``paid`` and ``received`` the other way round, which cannot hold under
    the sign convention ``balances.py`` states and the next criterion repeats: ``net``
    is negative for a member who owes the group, a confirmed settlement moves its payer
    *up* by what they paid, and a debtor at -400 who pays 400 and receives nothing lands
    on zero only this way round. Raised rather than quietly reversed.
    """
    balances = from_debts(NOT_MINIMAL)
    plan = simplify_debts(balances)
    for member_id, position in cents(balances).items():
        received = sum(
            t.amount.cents for t in plan.transfers if t.to_member_id == member_id
        )
        paid = sum(
            t.amount.cents for t in plan.transfers if t.from_member_id == member_id
        )
        assert position + paid - received == 0


def test_a_debtor_pays_what_they_owe_and_receives_nothing() -> None:
    balances = from_debts(NOT_MINIMAL)
    plan = simplify_debts(balances)
    for member_id, position in cents(balances).items():
        if position >= 0:
            continue
        paid = sum(
            t.amount.cents for t in plan.transfers if t.from_member_id == member_id
        )
        assert paid == -position
        assert [t for t in plan.transfers if t.to_member_id == member_id] == []


def test_a_creditor_receives_what_they_are_owed_and_pays_nothing() -> None:
    balances = from_debts(NOT_MINIMAL)
    plan = simplify_debts(balances)
    for member_id, position in cents(balances).items():
        if position <= 0:
            continue
        received = sum(
            t.amount.cents for t in plan.transfers if t.to_member_id == member_id
        )
        assert received == position
        assert [t for t in plan.transfers if t.from_member_id == member_id] == []


def test_a_zero_net_member_is_in_no_transfer_but_still_in_provenance() -> None:
    plan = simplify_debts(from_debts(OVERSIZED))
    assert CASS not in {t.from_member_id for t in plan.transfers}
    assert CASS not in {t.to_member_id for t in plan.transfers}
    counterparties = {
        member
        for transfer in plan.transfers
        for debt in transfer.payer_debts + transfer.receiver_credits
        for member in debt.pair
    }
    assert CASS in counterparties


def test_a_member_absent_from_net_entirely_appears_in_no_transfer() -> None:
    balances = from_debts(CHAIN)
    assert DEE not in balances.net
    plan = simplify_debts(balances)
    assert DEE not in {t.from_member_id for t in plan.transfers}
    assert DEE not in {t.to_member_id for t in plan.transfers}


# --- The transfer count -----------------------------------------------------


def assert_within_bounds(balances: Balances, plan: TransferPlan) -> None:
    """The two bounds the module claims, and never a claim of minimality."""
    positions = cents(balances)
    debtors = len([c for c in positions.values() if c < 0])
    creditors = len([c for c in positions.values() if c > 0])
    assert max(debtors, creditors) <= len(plan.transfers)
    assert len(plan.transfers) <= max(0, debtors + creditors - 1)


@pytest.mark.parametrize(
    "pairwise",
    [CHAIN, OVERSIZED, CYCLE, NOT_MINIMAL],
    ids=["chain", "oversized", "cycle", "not minimal"],
)
def test_every_worked_fixture_sits_inside_both_bounds(pairwise: dict) -> None:
    balances = from_debts(pairwise)
    assert_within_bounds(balances, simplify_debts(balances))


@pytest.mark.parametrize(
    ("net", "pairwise"),
    [
        ({}, {}),
        ({ALI: 0, BO: 0}, {}),
        (None, CYCLE),
    ],
    ids=["empty net", "all-zero net", "pure cycle"],
)
def test_an_already_settled_group_produces_an_empty_tuple(
    net: dict | None, pairwise: dict
) -> None:
    """Empty is a real answer: not an error, and never ``None``."""
    balances = from_debts(pairwise) if net is None else balances_of(net, pairwise)
    plan = simplify_debts(balances)
    assert isinstance(plan, TransferPlan)
    assert plan.transfers == ()


def test_one_debtor_and_many_creditors_is_minimal_because_the_bounds_meet() -> None:
    """``max(1, 3) == 3 == 1 + 3 - 1``, so the greedy result is the smallest plan."""
    balances = from_debts({(BO, ALI): 300, (BO, CASS): 200, (BO, DEE): 100})
    plan = simplify_debts(balances)
    assert moves(plan) == [(BO, ALI, 300), (BO, CASS, 200), (BO, DEE, 100)]
    positions = cents(balances)
    for transfer in plan.transfers:
        assert transfer.amount.cents == positions[transfer.to_member_id]
    assert len(plan.transfers) == 3
    assert_within_bounds(balances, plan)


def test_many_debtors_and_one_creditor_is_minimal_by_the_same_argument() -> None:
    """``max(3, 1) == 3 == 3 + 1 - 1``, so the bounds meet here too."""
    balances = from_debts({(ALI, DEE): 300, (BO, DEE): 200, (CASS, DEE): 100})
    plan = simplify_debts(balances)
    assert moves(plan) == [(ALI, DEE, 300), (BO, DEE, 200), (CASS, DEE, 100)]
    positions = cents(balances)
    for transfer in plan.transfers:
        assert transfer.amount.cents == -positions[transfer.from_member_id]
    assert len(plan.transfers) == 3
    assert_within_bounds(balances, plan)


def test_ties_go_to_the_smaller_member_id_on_both_sides() -> None:
    """Two debtors holding 100 each and two creditors owed 100 each.

    The debts run ali to dee and bo to cass, so a plan that crosses them into ali to
    cass and bo to dee shows the tie-break deciding who pays whom, never how much: each
    member's outlay was fixed by their ``net`` before any matching happened.
    """
    balances = from_debts({(ALI, DEE): 100, (BO, CASS): 100})
    assert cents(balances) == {ALI: -100, BO: -100, CASS: 100, DEE: 100}
    assert moves(simplify_debts(balances)) == [(ALI, CASS, 100), (BO, DEE, 100)]


# --- Provenance -------------------------------------------------------------

# Ali owes Cass and Dee 100 each, and Dee owes Bo 100, so Dee nets to zero. The greedy
# sends Ali to Bo before Ali to Cass, and Ali to Bo has no direct debt to draw on, so
# this is the fixture where an earlier transfer could eat the later one's direct match.
DIRECT_LAST = {(ALI, CASS): 100, (ALI, DEE): 100, (DEE, BO): 100}


def absorbed_by_pair(plan: TransferPlan, *, payer_side: bool) -> dict[Pair, int]:
    """Total cents absorbed per pairwise key, on one side of the plan."""
    totals: dict[Pair, int] = {}
    for transfer in plan.transfers:
        debts = transfer.payer_debts if payer_side else transfer.receiver_credits
        for debt in debts:
            totals[debt.pair] = totals.get(debt.pair, 0) + debt.amount.cents
    return totals


def assert_provenance_holds(balances: Balances, plan: TransferPlan) -> None:
    """Every provenance criterion that is expressible as an invariant.

    Exact integer comparison throughout: provenance that is one cent out is wrong, and
    an approximate assertion would not notice.
    """
    positions = cents(balances)
    debts = {pair: money.cents for pair, money in balances.pairwise.items()}
    owed_to: dict[str, int] = {}
    owes: dict[str, int] = {}
    for (debtor, creditor), amount in debts.items():
        owes[debtor] = owes.get(debtor, 0) + amount
        owed_to[creditor] = owed_to.get(creditor, 0) + amount

    for transfer in plan.transfers:
        sides = (
            (transfer.payer_debts, 0, transfer.from_member_id),
            (transfer.receiver_credits, 1, transfer.to_member_id),
        )
        for side_rows, end, owner in sides:
            assert side_rows != ()
            assert sum(row.amount.cents for row in side_rows) == transfer.amount.cents
            pairs = [row.pair for row in side_rows]
            assert pairs == sorted(pairs)
            assert len(set(pairs)) == len(pairs)
            for row in side_rows:
                assert row.pair[end] == owner
                assert row.pair in balances.pairwise
                assert row.debt_total == balances.pairwise[row.pair]
                assert 0 < row.amount.cents <= row.debt_total.cents

        direct = (transfer.from_member_id, transfer.to_member_id)
        if direct in debts:
            expected = min(transfer.amount.cents, debts[direct])
            for side_rows, _, _ in sides:
                taken = {row.pair: row.amount.cents for row in side_rows}
                assert taken[direct] == expected

    payer = absorbed_by_pair(plan, payer_side=True)
    receiver = absorbed_by_pair(plan, payer_side=False)
    for pair, amount in debts.items():
        assert payer.get(pair, 0) <= amount
        assert receiver.get(pair, 0) <= amount

    for pair in payer:
        assert positions.get(pair[0], 0) < 0
    for pair in receiver:
        assert positions.get(pair[1], 0) > 0

    for member_id, position in positions.items():
        if position < 0:
            taken = sum(c for pair, c in payer.items() if pair[0] == member_id)
            unabsorbed = sum(
                amount - payer.get(pair, 0)
                for pair, amount in debts.items()
                if pair[0] == member_id
            )
            assert taken == -position
            assert unabsorbed == owed_to.get(member_id, 0)
        if position > 0:
            given = sum(c for pair, c in receiver.items() if pair[1] == member_id)
            unabsorbed = sum(
                amount - receiver.get(pair, 0)
                for pair, amount in debts.items()
                if pair[1] == member_id
            )
            assert given == position
            assert unabsorbed == owes.get(member_id, 0)


@pytest.mark.parametrize(
    "pairwise",
    [CHAIN, OVERSIZED, CYCLE, NOT_MINIMAL, DIRECT_LAST],
    ids=["chain", "oversized", "cycle", "not minimal", "direct last"],
)
def test_every_worked_fixture_holds_every_provenance_invariant(pairwise: dict) -> None:
    balances = from_debts(pairwise)
    assert_provenance_holds(balances, simplify_debts(balances))


def test_the_chain_splits_one_debt_across_two_transfers() -> None:
    """600 and 400 of the same 1000, each row carrying the whole 1000."""
    balances = from_debts(CHAIN)
    first, second = simplify_debts(balances).transfers

    assert rows(first.payer_debts) == [((BO, ALI), 600, 1000)]
    assert rows(first.receiver_credits) == [((BO, ALI), 600, 1000)]
    assert rows(second.payer_debts) == [((BO, ALI), 400, 1000)]
    assert rows(second.receiver_credits) == [((ALI, CASS), 400, 400)]
    assert 600 + 400 == 1000


def test_the_chain_reads_end_to_end_on_the_second_transfer() -> None:
    """Bo pays Cass because Bo owes Ali, and Ali owes Cass."""
    second = simplify_debts(from_debts(CHAIN)).transfers[1]
    assert (second.from_member_id, second.to_member_id) == (BO, CASS)
    assert [debt.pair for debt in second.payer_debts] == [(BO, ALI)]
    assert [debt.pair for debt in second.receiver_credits] == [(ALI, CASS)]


def test_a_debt_may_be_absorbed_by_nothing_on_a_side_or_at_all() -> None:
    """Neither is an error: no criterion requires every debt to be absorbed."""
    cycle = simplify_debts(from_debts(CYCLE))
    assert absorbed_by_pair(cycle, payer_side=True) == {}
    assert absorbed_by_pair(cycle, payer_side=False) == {}

    chain = simplify_debts(from_debts(CHAIN))
    assert (ALI, CASS) not in absorbed_by_pair(chain, payer_side=True)
    assert absorbed_by_pair(chain, payer_side=False)[(ALI, CASS)] == 400


def test_a_transfer_routinely_exceeds_every_debt_it_absorbs() -> None:
    """One 600 payment explained by four 300 debts, two on each side."""
    only = simplify_debts(from_debts(OVERSIZED)).transfers[0]
    assert only.amount == Money(600, AUD)
    assert rows(only.payer_debts) == [
        ((BO, ALI), 300, 300),
        ((BO, CASS), 300, 300),
    ]
    assert rows(only.receiver_credits) == [
        ((BO, ALI), 300, 300),
        ((CASS, ALI), 300, 300),
    ]
    for debt in only.payer_debts + only.receiver_credits:
        assert debt.amount.cents < only.amount.cents


def test_one_debt_between_two_people_is_its_own_whole_provenance() -> None:
    """The simple case reads perfectly: one transfer, one debt, nothing else."""
    only = simplify_debts(from_debts({(BO, ALI): 1000})).transfers[0]
    assert rows(only.payer_debts) == [((BO, ALI), 1000, 1000)]
    assert rows(only.receiver_credits) == [((BO, ALI), 1000, 1000)]


def test_an_earlier_transfer_never_eats_a_later_transfer_direct_debt() -> None:
    """Every transfer claims its own direct debt before anything else touches it.

    Ali pays Bo first and has no debt to Bo, so that transfer has to draw on one of
    Ali's other debts. Both of them hold 100, so the one it takes decides whether Ali
    to Cass still finds its direct match. Direct debts are claimed for the whole plan
    before any transfer reaches for a substitute, so it does.
    """
    balances = from_debts(DIRECT_LAST)
    assert cents(balances) == {ALI: -200, BO: 100, CASS: 100, DEE: 0}
    plan = simplify_debts(balances)
    assert moves(plan) == [(ALI, BO, 100), (ALI, CASS, 100)]

    to_bo, to_cass = plan.transfers
    assert rows(to_cass.payer_debts) == [((ALI, CASS), 100, 100)]
    assert rows(to_cass.receiver_credits) == [((ALI, CASS), 100, 100)]
    assert rows(to_bo.payer_debts) == [((ALI, DEE), 100, 100)]
    assert rows(to_bo.receiver_credits) == [((DEE, BO), 100, 100)]


def test_a_pair_may_appear_on_both_sides_of_one_transfer() -> None:
    """The two-ended view of one payment, not a duplicate."""
    only = simplify_debts(from_debts(OVERSIZED)).transfers[0]
    assert (BO, ALI) in {debt.pair for debt in only.payer_debts}
    assert (BO, ALI) in {debt.pair for debt in only.receiver_credits}


def test_the_two_sides_are_attributed_over_separate_books() -> None:
    """Each side accounts for the whole amount independently. Not double counting."""
    for transfer in simplify_debts(from_debts(NOT_MINIMAL)).transfers:
        payer = sum(debt.amount.cents for debt in transfer.payer_debts)
        receiver = sum(debt.amount.cents for debt in transfer.receiver_credits)
        assert payer == transfer.amount.cents
        assert receiver == transfer.amount.cents


# --- Settling to zero, through task 4 ---------------------------------------


def at(minute: int) -> datetime:
    """A UTC timestamp ``minute`` minutes after a fixed instant.

    Fixed rather than ``now()`` so the ordering key of every fixture is written down in
    the test rather than depending on when the suite runs.
    """
    return EPOCH + timedelta(minutes=minute)


def expense(
    event_id: str,
    *,
    payer: MemberId,
    total: int,
    shares: dict[MemberId, int],
    minute: int = 0,
) -> ExpenseEvent:
    """An expense event, with the boilerplate task 5 does not care about filled in."""
    return ExpenseEvent(
        id=ExpenseId(event_id),
        group_id=GROUP,
        currency=AUD,
        payer_id=payer,
        total_cents=total,
        allocations=tuple(
            Allocation(member_id, cents) for member_id, cents in shares.items()
        ),
        description="",
        created_at=at(minute),
        created_by=payer,
    )


def confirmed(
    event_id: str, *, payer: MemberId, receiver: MemberId, amount: int, minute: int
) -> list[LedgerEvent]:
    """A settlement and the decision that makes it move money."""
    return [
        SettlementEvent(
            id=SettlementId(event_id),
            group_id=GROUP,
            currency=AUD,
            from_member_id=payer,
            to_member_id=receiver,
            amount_cents=amount,
            created_at=at(minute),
            created_by=payer,
        ),
        SettlementDecisionEvent(
            id=f"d-{event_id}",
            settlement_id=SettlementId(event_id),
            decision=SettlementState.CONFIRMED,
            decided_by=receiver,
            created_at=at(minute),
        ),
    ]


def ledger_for(pairwise: dict[Pair, int]) -> list[LedgerEvent]:
    """A real event log that folds to exactly ``pairwise``.

    One expense per debt: the creditor pays and the debtor is the only participant, so
    the fold credits the creditor, debits the debtor and records the pair unchanged.
    """
    return [
        expense(f"e{index}", payer=creditor, total=cents, shares={debtor: cents},
                minute=index)
        for index, ((debtor, creditor), cents) in enumerate(sorted(pairwise.items()))
    ]


def fold(events: list[LedgerEvent]) -> Balances:
    return derive_balances(events, group_id=GROUP, currency=AUD)


def paying_off(events: list[LedgerEvent], plan: TransferPlan) -> list[LedgerEvent]:
    """The log plus one confirmed settlement per suggested transfer."""
    settled = list(events)
    for index, transfer in enumerate(plan.transfers):
        settled += confirmed(
            f"pay{index}",
            payer=transfer.from_member_id,
            receiver=transfer.to_member_id,
            amount=transfer.amount.cents,
            minute=1000 + index,
        )
    return settled


@pytest.mark.parametrize(
    "pairwise",
    [CHAIN, OVERSIZED, CYCLE, NOT_MINIMAL, DIRECT_LAST],
    ids=["chain", "oversized", "cycle", "not minimal", "direct last"],
)
def test_a_ledger_folds_to_the_hand_built_fixture_it_stands_for(
    pairwise: dict,
) -> None:
    """The hand-built fixtures and the real fold agree, so the rest is comparable."""
    assert fold(ledger_for(pairwise)) == from_debts(pairwise)


@pytest.mark.parametrize(
    "pairwise",
    [CHAIN, OVERSIZED, CYCLE, NOT_MINIMAL, DIRECT_LAST],
    ids=["chain", "oversized", "cycle", "not minimal", "direct last"],
)
def test_settling_every_suggested_transfer_zeroes_every_net_position(
    pairwise: dict,
) -> None:
    """Checked through the real fold, never by re-implementing it."""
    events = ledger_for(pairwise)
    plan = simplify_debts(fold(events))
    settled = fold(paying_off(events, plan))
    assert set(cents(settled).values()) <= {0}


def test_the_refold_leaves_live_debts_and_that_is_correct() -> None:
    """Simplification converts a chain into a residual cycle.

    ``pairwise`` is deliberately not asserted empty here or anywhere else in this file.
    The three debts below cancel to zero in ``net``, which is the visible price of
    netting, so an emptiness assertion would be asserting a bug.
    """
    events = ledger_for(CHAIN)
    plan = simplify_debts(fold(events))
    settled = fold(paying_off(events, plan))

    assert {pair: money.cents for pair, money in settled.pairwise.items()} == {
        (ALI, CASS): 400,
        (BO, ALI): 400,
        (CASS, BO): 400,
    }
    assert set(cents(settled).values()) == {0}


@pytest.mark.parametrize(
    "pairwise",
    [CHAIN, OVERSIZED, CYCLE, NOT_MINIMAL, DIRECT_LAST],
    ids=["chain", "oversized", "cycle", "not minimal", "direct last"],
)
def test_simplifying_the_refolded_balances_suggests_nothing_further(
    pairwise: dict,
) -> None:
    """Zero net positions mean nothing left to suggest, live debts or not."""
    events = ledger_for(pairwise)
    settled = fold(paying_off(events, simplify_debts(fold(events))))
    assert simplify_debts(settled).transfers == ()


# --- The shapes that are easy to miss ---------------------------------------


def flipped_by_an_over_payment() -> list[LedgerEvent]:
    """Bo owes Ali 500 and settles 800, which task 4 documents as flipping the pair."""
    return [
        expense("e1", payer=ALI, total=500, shares={BO: 500}),
        *confirmed("s1", payer=BO, receiver=ALI, amount=800, minute=1),
    ]


SHAPES: dict[str, list[LedgerEvent]] = {
    "already settled": [],
    "pure cycle": ledger_for(CYCLE),
    "one debtor, several creditors": ledger_for(
        {(BO, ALI): 300, (BO, CASS): 200, (BO, DEE): 100}
    ),
    "several debtors, one creditor": ledger_for(
        {(ALI, DEE): 300, (BO, DEE): 200, (CASS, DEE): 100}
    ),
    "a zero net between two live debts": ledger_for(OVERSIZED),
    "a settlement larger than the debt": flipped_by_an_over_payment(),
}


@pytest.mark.parametrize("shape", list(SHAPES), ids=list(SHAPES))
def test_each_easily_missed_shape_holds_every_invariant(shape: str) -> None:
    events = SHAPES[shape]
    balances = fold(events)
    plan = simplify_debts(balances)
    assert_within_bounds(balances, plan)
    assert_provenance_holds(balances, plan)
    assert set(cents(fold(paying_off(events, plan))).values()) <= {0}


def test_an_over_payment_flips_the_pair_and_the_plan_follows_it() -> None:
    balances = fold(flipped_by_an_over_payment())
    assert cents(balances) == {ALI: -300, BO: 300}
    assert {pair: m.cents for pair, m in balances.pairwise.items()} == {(ALI, BO): 300}
    only = simplify_debts(balances).transfers[0]
    assert (only.from_member_id, only.to_member_id, only.amount.cents) == (ALI, BO, 300)
    assert rows(only.payer_debts) == [((ALI, BO), 300, 300)]


# --- Property: every invariant, over generated ledgers ----------------------


ROSTER = [MemberId(f"m{index}") for index in range(5)]


def assert_plan_holds(balances: Balances, plan: TransferPlan) -> None:
    """Every criterion expressible as an invariant, asserted on one plan."""
    assert plan.group_id == balances.group_id
    assert plan.currency == balances.currency

    keys = [(t.from_member_id, t.to_member_id) for t in plan.transfers]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    for from_member_id, to_member_id in keys:
        assert from_member_id != to_member_id
        assert (to_member_id, from_member_id) not in set(keys)

    for transfer in plan.transfers:
        assert transfer.amount.cents > 0
        assert transfer.amount.currency == balances.currency

    positions = cents(balances)
    for member_id, position in positions.items():
        received = sum(
            t.amount.cents for t in plan.transfers if t.to_member_id == member_id
        )
        paid = sum(
            t.amount.cents for t in plan.transfers if t.from_member_id == member_id
        )
        assert position + paid - received == 0
        if position == 0:
            assert paid == 0 and received == 0

    assert_within_bounds(balances, plan)
    assert_provenance_holds(balances, plan)


def random_ledger(rng: random.Random, size: int) -> list[LedgerEvent]:
    """A ledger of ``size`` entries mixing expenses with settlements in every state.

    Ids are unique by construction, timestamps ascend, and every amount is a whole
    number of cents, so the only thing that varies is the shape of the ledger. A
    settlement is sized to reach past the debt it clears often enough that the
    pair-flipping case task 4 documents shows up here too.
    """
    events: list[LedgerEvent] = []
    for index in range(size):
        minute = index + 1
        if rng.choice((True, True, False)):
            participants = rng.sample(ROSTER, rng.randint(1, len(ROSTER)))
            shares = {member_id: rng.randint(0, 500) for member_id in participants}
            if sum(shares.values()) == 0:
                shares[participants[0]] = 1
            events.append(
                expense(
                    f"e{index}",
                    payer=rng.choice(ROSTER),
                    total=sum(shares.values()),
                    shares=shares,
                    minute=minute,
                )
            )
            continue

        payer, receiver = rng.sample(ROSTER, 2)
        settlement = SettlementEvent(
            id=SettlementId(f"s{index}"),
            group_id=GROUP,
            currency=AUD,
            from_member_id=payer,
            to_member_id=receiver,
            amount_cents=rng.randint(1, 1200),
            created_at=at(minute),
            created_by=payer,
        )
        events.append(settlement)
        outcome = rng.choice(
            (None, SettlementState.CONFIRMED, SettlementState.REJECTED)
        )
        if outcome is not None:
            events.append(
                SettlementDecisionEvent(
                    id=f"d{index}",
                    settlement_id=SettlementId(f"s{index}"),
                    decision=outcome,
                    decided_by=receiver,
                    created_at=at(minute),
                )
            )
    return events


def test_every_random_ledger_produces_a_plan_holding_every_invariant() -> None:
    rng = random.Random(SEED)
    for _ in range(200):
        balances = fold(random_ledger(rng, rng.randint(0, 20)))
        assert_plan_holds(balances, simplify_debts(balances))


def test_every_random_plan_settles_the_group_through_the_real_fold() -> None:
    rng = random.Random(SEED + 1)
    for _ in range(100):
        events = random_ledger(rng, rng.randint(0, 20))
        plan = simplify_debts(fold(events))
        assert set(cents(fold(paying_off(events, plan))).values()) <= {0}


def test_every_random_ledger_simplifies_to_nothing_once_it_is_paid_off() -> None:
    rng = random.Random(SEED + 2)
    for _ in range(50):
        events = random_ledger(rng, rng.randint(0, 20))
        settled = fold(paying_off(events, simplify_debts(fold(events))))
        assert simplify_debts(settled).transfers == ()


# --- Exhaustive where the domain is small enough ----------------------------


def expense_pool() -> list[ExpenseEvent]:
    """Six hand-written expenses over four members, covering the shapes that matter."""
    return [
        expense("p0", payer=ALI, total=900, shares={ALI: 300, BO: 300, CASS: 300},
                minute=0),
        expense("p1", payer=BO, total=400, shares={ALI: 400}, minute=1),
        expense("p2", payer=CASS, total=1000, shares={BO: 500, DEE: 500}, minute=2),
        expense("p3", payer=DEE, total=250, shares={ALI: 100, CASS: 150}, minute=3),
        expense("p4", payer=ALI, total=7, shares={BO: 3, CASS: 3, DEE: 1}, minute=4),
        expense("p5", payer=BO, total=1200, shares={BO: 600, DEE: 600}, minute=5),
    ]


def test_every_ledger_of_up_to_three_of_six_expenses_holds_every_invariant() -> None:
    """42 ledgers: one empty, six of one expense, fifteen of two, twenty of three."""
    pool = expense_pool()
    ledgers = [
        list(chosen)
        for size in range(4)
        for chosen in itertools.combinations(pool, size)
    ]
    assert len(ledgers) == 42

    for events in ledgers:
        balances = fold(events)
        plan = simplify_debts(balances)
        assert_plan_holds(balances, plan)
        assert set(cents(fold(paying_off(events, plan))).values()) <= {0}


# --- Determinism ------------------------------------------------------------


def test_shuffling_the_log_never_changes_the_plan() -> None:
    rng = random.Random(SEED + 3)
    for _ in range(50):
        events = random_ledger(rng, rng.randint(1, 20))
        ordered = sorted(events, key=lambda event: (event.created_at, event.id))
        expected = simplify_debts(fold(ordered))
        for _ in range(3):
            shuffled = list(events)
            rng.shuffle(shuffled)
            assert simplify_debts(fold(shuffled)) == expected


def test_two_calls_on_one_balances_do_not_drift() -> None:
    balances = from_debts(NOT_MINIMAL)
    first = simplify_debts(balances)
    second = simplify_debts(balances)
    assert first == second
    assert moves(first) == moves(second)
    assert [rows(t.payer_debts) for t in first.transfers] == [
        rows(t.payer_debts) for t in second.transfers
    ]


def test_the_plan_is_the_same_in_a_process_with_a_different_string_hash() -> None:
    """String hashing is salted per process, so two readers would otherwise differ."""
    script = (
        "from splitwise_lite import derive_balances, simplify_debts;"
        "import sys; sys.path.insert(0, 'tests');"
        "from test_simplify import NOT_MINIMAL, from_debts, moves;"
        "print(moves(simplify_debts(from_debts(NOT_MINIMAL))))"
    )
    answers = set()
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode == 0, result.stderr
        answers.add(result.stdout.strip())
    assert len(answers) == 1


# --- Arithmetic: integer cents, and no division at all ----------------------


def _module_tree(module) -> ast.Module:
    return ast.parse(Path(inspect.getfile(module)).read_text(encoding="utf-8"))


def _names(tree: ast.Module) -> set[str]:
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return names | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }


@pytest.mark.parametrize("forbidden", ["float", "round", "Decimal", "divmod"])
def test_the_module_never_names_a_rounding_tool(forbidden: str) -> None:
    assert forbidden not in _names(_module_tree(simplify_module))


def test_the_module_holds_no_float_literal() -> None:
    """The name check above would miss ``0.5``; this catches the literal itself."""
    tree = _module_tree(simplify_module)
    literals = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    ]
    assert literals == []


@pytest.mark.parametrize(
    "operator",
    [ast.Div, ast.FloorDiv, ast.Mod],
    ids=["true division", "floor division", "modulo"],
)
def test_the_module_never_divides(operator: type[ast.operator]) -> None:
    """Only comparison, addition and subtraction, so no remainder can arise."""
    tree = _module_tree(simplify_module)
    divisions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.BinOp, ast.AugAssign))
        and isinstance(node.op, operator)
    ]
    assert divisions == []


@pytest.mark.parametrize("forbidden", ["hash", "random", "time", "uuid", "datetime"])
def test_the_module_is_a_pure_function_of_its_input(forbidden: str) -> None:
    """No clock, no randomness, and nothing salted per process deciding an answer."""
    assert forbidden not in _names(_module_tree(simplify_module))


def test_the_module_keeps_no_mutable_state_to_memoise_into() -> None:
    mutable = {
        name: value
        for name, value in vars(simplify_module).items()
        if not name.startswith("__")
        and isinstance(value, (dict, list, set, bytearray))
    }
    assert mutable == {}


def test_no_stored_amount_bound_is_applied_to_a_derived_plan() -> None:
    """A plan is derived and never stored, so there is no column to overflow."""
    huge = MAX_CENTS + MAX_CENTS
    balances = from_debts({(BO, ALI): huge, (ALI, CASS): huge})
    plan = simplify_debts(balances)
    assert moves(plan) == [(BO, CASS, huge)]
    assert rows(plan.transfers[0].payer_debts) == [((BO, ALI), huge, huge)]
    assert_plan_holds(balances, plan)


# --- Dependency direction ---------------------------------------------------


def _imported(tree: ast.Module) -> set[str]:
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    return imported


def test_simplify_imports_only_money_events_and_balances() -> None:
    """Nothing here divides a total and nothing here touches a database."""
    imported = _imported(_module_tree(simplify_module))
    assert {
        name
        for name in imported
        if name in {"money", "events", "balances", "split", "store"}
    } == {"money", "events", "balances"}
    assert not any("splitwise_lite" in name for name in imported)


@pytest.mark.parametrize(
    "module",
    [money_module, events_module, split_module, balances_module, store_module],
    ids=["money", "events", "split", "balances", "store"],
)
def test_no_earlier_module_learns_that_this_one_exists(module) -> None:
    assert "simplify" not in _imported(_module_tree(module))


def test_only_public_names_are_imported_from_the_modules_below() -> None:
    """The underscore-prefixed helpers in ``balances.py`` are not its contract."""
    tree = _module_tree(simplify_module)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not any(name.startswith("_") for name in imported)


def test_the_public_names_are_re_exported_from_the_package_root() -> None:
    assert splitwise_lite.simplify_debts is simplify_debts
    assert splitwise_lite.AbsorbedDebt is AbsorbedDebt
    assert splitwise_lite.Transfer is Transfer
    assert splitwise_lite.TransferPlan is TransferPlan
    assert splitwise_lite.InvalidBalances is InvalidBalances
    assert set(simplify_module.__all__) <= set(splitwise_lite.__all__)


def test_the_package_version_is_untouched() -> None:
    """``tests/test_smoke.py`` asserts it, so adding a module must not move it."""
    assert splitwise_lite.__version__ == "0.1.0"


def test_everything_public_carries_a_docstring() -> None:
    for name in simplify_module.__all__:
        assert getattr(simplify_module, name).__doc__
    assert simplify_module.__doc__
    assert AbsorbedDebt.pair.__doc__


def test_nothing_public_is_defined_beyond_the_five_names() -> None:
    """Everything else in the module is private, underscore prefixed."""
    tree = _module_tree(simplify_module)
    defined = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined |= {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
    public = {name for name in defined if not name.startswith("_")}
    assert public == set(simplify_module.__all__)
