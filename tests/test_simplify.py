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
import random
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
    plan = simplify_debts(from_debts({(BO, ALI): 300, (BO, CASS): 300, (CASS, ALI): 300}, currency=NZD))
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
