"""Tests for the balance fold: events become pairwise debts and net positions.

Task 4 of plans/backlog.md, sharpened in plans/tasks/04-balance-derivation.md.

Property coverage is standard library rather than hypothesis, matching the dependency
decision task 3 made. Order independence is proved exhaustively over every permutation
of a small hand-written fixture, and the larger ledgers are shuffled by a generator
seeded from a fixed constant so any failure reproduces from the test alone.
"""

from __future__ import annotations

import dataclasses
import types
from datetime import datetime, timezone

import pytest

from splitwise_lite.balances import (
    Balances,
    InvalidLedger,
    derive_balances,
    settlement_states,
)
from splitwise_lite.events import (
    Allocation,
    ExpenseEvent,
    ExpenseId,
    GroupId,
    MemberId,
    SettlementDecisionEvent,
    SettlementEvent,
    SettlementId,
    SettlementState,
)
from splitwise_lite.money import Currency, CurrencyMismatch, DomainError, Money

AUD = Currency("AUD")
NZD = Currency("NZD")

GROUP = GroupId("group-dinner")
OTHER_GROUP = GroupId("group-holiday")

ALI = MemberId("ali")
BO = MemberId("bo")
CASS = MemberId("cass")

SEED = 20260904


def at(minute: int) -> datetime:
    """A UTC timestamp ``minute`` minutes into a fixed hour.

    Fixed rather than ``now()`` so the ordering key of every fixture is written down in
    the test rather than depending on when the suite runs.
    """
    return datetime(2026, 1, 1, 12, minute, tzinfo=timezone.utc)


def expense(
    event_id: str,
    *,
    payer: MemberId,
    total: int,
    shares: dict[MemberId, int],
    minute: int = 0,
    group_id: GroupId = GROUP,
    currency: Currency = AUD,
) -> ExpenseEvent:
    """An expense event, with the boilerplate task 4 does not care about filled in."""
    return ExpenseEvent(
        id=ExpenseId(event_id),
        group_id=group_id,
        currency=currency,
        payer_id=payer,
        total_cents=total,
        allocations=tuple(
            Allocation(member_id, cents) for member_id, cents in shares.items()
        ),
        description="",
        created_at=at(minute),
        created_by=payer,
    )


def settlement(
    event_id: str,
    *,
    payer: MemberId,
    receiver: MemberId,
    amount: int,
    minute: int = 0,
    group_id: GroupId = GROUP,
    currency: Currency = AUD,
) -> SettlementEvent:
    """A claimed payment from ``payer`` to ``receiver``, born pending."""
    return SettlementEvent(
        id=SettlementId(event_id),
        group_id=group_id,
        currency=currency,
        from_member_id=payer,
        to_member_id=receiver,
        amount_cents=amount,
        created_at=at(minute),
        created_by=payer,
    )


def decision(
    event_id: str,
    *,
    settlement_id: str,
    state: SettlementState,
    minute: int = 0,
    decided_by: MemberId = ALI,
) -> SettlementDecisionEvent:
    """The receiver's answer to one settlement."""
    return SettlementDecisionEvent(
        id=event_id,
        settlement_id=SettlementId(settlement_id),
        decision=state,
        decided_by=decided_by,
        created_at=at(minute),
    )


def cents_of(balances: Balances) -> dict[str, int]:
    """The net map as plain cents, for exact integer comparison."""
    return {member_id: money.cents for member_id, money in balances.net.items()}


def debts_of(balances: Balances) -> dict[tuple[str, str], int]:
    """The pairwise map as plain cents, for exact integer comparison."""
    return {pair: money.cents for pair, money in balances.pairwise.items()}


# --- Shape and contract -----------------------------------------------------


def test_invalid_ledger_is_a_domain_error() -> None:
    assert issubclass(InvalidLedger, DomainError)


def test_balances_is_a_frozen_dataclass_with_slots() -> None:
    assert dataclasses.is_dataclass(Balances)
    assert Balances.__dataclass_params__.frozen is True
    assert "__slots__" in vars(Balances)


def test_balances_holds_the_group_the_currency_and_two_mappings() -> None:
    result = derive_balances([], group_id=GROUP, currency=AUD)
    assert [field.name for field in dataclasses.fields(Balances)] == [
        "group_id",
        "currency",
        "net",
        "pairwise",
    ]
    assert result.group_id == GROUP
    assert result.currency == AUD


def test_both_mappings_are_read_only_views() -> None:
    result = derive_balances(
        [expense("e1", payer=ALI, total=1000, shares={BO: 1000})],
        group_id=GROUP,
        currency=AUD,
    )
    assert isinstance(result.net, types.MappingProxyType)
    assert isinstance(result.pairwise, types.MappingProxyType)
    with pytest.raises(TypeError):
        result.net[CASS] = Money(1, AUD)  # type: ignore[index]
    with pytest.raises(TypeError):
        result.pairwise[(CASS, ALI)] = Money(1, AUD)  # type: ignore[index]


def test_two_folds_of_the_same_events_compare_equal() -> None:
    events = [
        expense("e1", payer=ALI, total=3000, shares={ALI: 1000, BO: 1000, CASS: 1000}),
        settlement("s1", payer=BO, receiver=ALI, amount=1000, minute=1),
        decision("d1", settlement_id="s1", state=SettlementState.CONFIRMED, minute=2),
    ]
    assert derive_balances(events, group_id=GROUP, currency=AUD) == derive_balances(
        events, group_id=GROUP, currency=AUD
    )


def test_balances_of_different_ledgers_are_not_equal() -> None:
    one = derive_balances(
        [expense("e1", payer=ALI, total=1000, shares={BO: 1000})],
        group_id=GROUP,
        currency=AUD,
    )
    other = derive_balances(
        [expense("e1", payer=ALI, total=2000, shares={BO: 2000})],
        group_id=GROUP,
        currency=AUD,
    )
    assert one != other


def test_group_id_and_currency_are_keyword_only_and_required() -> None:
    with pytest.raises(TypeError):
        derive_balances([], GROUP, AUD)  # type: ignore[misc]
    with pytest.raises(TypeError):
        derive_balances([], group_id=GROUP)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        derive_balances([], currency=AUD)  # type: ignore[call-arg]


def test_an_empty_ledger_keeps_the_group_and_currency_it_was_given() -> None:
    result = derive_balances([], group_id=GROUP, currency=AUD)
    assert dict(result.net) == {}
    assert dict(result.pairwise) == {}
    assert result.group_id == GROUP
    assert result.currency == AUD


def test_net_for_returns_zero_for_a_member_the_ledger_has_never_seen() -> None:
    result = derive_balances([], group_id=GROUP, currency=AUD)
    assert result.net_for(ALI) == Money(0, AUD)
    assert result.net_for(MemberId("nobody")) == Money(0, AUD)


def test_events_may_be_a_generator_and_is_consumed_exactly_once() -> None:
    only = expense("e1", payer=ALI, total=1000, shares={BO: 1000})
    reads: list[str] = []

    def stream():
        for event in (only,):
            reads.append(event.id)
            yield event

    result = derive_balances(stream(), group_id=GROUP, currency=AUD)
    assert reads == ["e1"]
    assert cents_of(result) == {ALI: 1000, BO: -1000}


def test_the_callers_list_is_neither_mutated_nor_reordered() -> None:
    events = [
        expense("e2", payer=BO, total=400, shares={ALI: 400}, minute=5),
        expense("e1", payer=ALI, total=1000, shares={BO: 1000}, minute=1),
    ]
    before = list(events)
    derive_balances(events, group_id=GROUP, currency=AUD)
    settlement_states(events)
    assert events == before
    assert [event.id for event in events] == ["e2", "e1"]


# --- Rejections and types ---------------------------------------------------


def test_events_that_is_not_iterable_raises_type_error() -> None:
    with pytest.raises(TypeError):
        derive_balances(7, group_id=GROUP, currency=AUD)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        settlement_states(7)  # type: ignore[arg-type]


def test_an_element_that_is_not_a_ledger_event_raises_type_error_naming_it() -> None:
    with pytest.raises(TypeError, match="dict"):
        derive_balances([{"total": 1000}], group_id=GROUP, currency=AUD)  # type: ignore[list-item]
    with pytest.raises(TypeError, match="NoneType"):
        settlement_states([None])  # type: ignore[list-item]


def test_a_group_id_that_is_not_a_str_raises_type_error() -> None:
    with pytest.raises(TypeError, match="int"):
        derive_balances([], group_id=7, currency=AUD)  # type: ignore[arg-type]


def test_an_empty_group_id_is_a_domain_error() -> None:
    with pytest.raises(InvalidLedger):
        derive_balances([], group_id=GroupId(""), currency=AUD)


def test_a_currency_that_is_not_a_currency_raises_type_error() -> None:
    with pytest.raises(TypeError, match="str"):
        derive_balances([], group_id=GROUP, currency="AUD")  # type: ignore[arg-type]


def test_a_foreign_group_names_the_event_the_group_asked_for_and_the_one_found(
) -> None:
    foreign = expense(
        "e-foreign", payer=ALI, total=1000, shares={BO: 1000}, group_id=OTHER_GROUP
    )
    with pytest.raises(InvalidLedger) as raised:
        derive_balances([foreign], group_id=GROUP, currency=AUD)
    message = str(raised.value)
    assert "e-foreign" in message
    assert GROUP in message
    assert OTHER_GROUP in message


def test_a_foreign_settlement_is_rejected_too() -> None:
    foreign = settlement(
        "s-foreign",
        payer=BO,
        receiver=ALI,
        amount=1000,
        group_id=OTHER_GROUP,
    )
    with pytest.raises(InvalidLedger, match="s-foreign"):
        derive_balances([foreign], group_id=GROUP, currency=AUD)


def test_two_groups_raise_even_though_one_would_fold_cleanly() -> None:
    events = [
        expense("e1", payer=ALI, total=1000, shares={BO: 1000}),
        expense(
            "e2",
            payer=ALI,
            total=1000,
            shares={CASS: 1000},
            minute=1,
            group_id=OTHER_GROUP,
        ),
    ]
    with pytest.raises(InvalidLedger):
        derive_balances(events, group_id=GROUP, currency=AUD)


def test_a_foreign_currency_raises_currency_mismatch_naming_both_codes() -> None:
    foreign = expense(
        "e1", payer=ALI, total=1000, shares={BO: 1000}, currency=NZD
    )
    with pytest.raises(CurrencyMismatch) as raised:
        derive_balances([foreign], group_id=GROUP, currency=AUD)
    message = str(raised.value)
    assert "AUD" in message
    assert "NZD" in message


def test_a_settlement_in_a_foreign_currency_raises_currency_mismatch() -> None:
    foreign = settlement(
        "s1", payer=BO, receiver=ALI, amount=1000, currency=NZD
    )
    with pytest.raises(CurrencyMismatch):
        derive_balances([foreign], group_id=GROUP, currency=AUD)


def test_a_repeated_expense_id_is_a_domain_error_naming_the_id() -> None:
    events = [
        expense("e1", payer=ALI, total=1000, shares={BO: 1000}),
        expense("e1", payer=ALI, total=1000, shares={BO: 1000}, minute=1),
    ]
    with pytest.raises(InvalidLedger, match="e1"):
        derive_balances(events, group_id=GROUP, currency=AUD)


def test_a_repeated_settlement_id_is_a_domain_error_naming_the_id() -> None:
    events = [
        settlement("s1", payer=BO, receiver=ALI, amount=1000),
        settlement("s1", payer=BO, receiver=ALI, amount=1000, minute=1),
    ]
    with pytest.raises(InvalidLedger, match="s1"):
        derive_balances(events, group_id=GROUP, currency=AUD)
    with pytest.raises(InvalidLedger, match="s1"):
        settlement_states(events)


def test_a_repeated_decision_id_is_a_domain_error_naming_the_id() -> None:
    events = [
        settlement("s1", payer=BO, receiver=ALI, amount=1000),
        decision("d1", settlement_id="s1", state=SettlementState.CONFIRMED, minute=1),
        decision("d1", settlement_id="s1", state=SettlementState.REJECTED, minute=2),
    ]
    with pytest.raises(InvalidLedger, match="d1"):
        settlement_states(events)


def test_two_distinct_events_with_equal_amounts_are_fine() -> None:
    events = [
        expense("e1", payer=ALI, total=1000, shares={BO: 1000}),
        expense("e2", payer=ALI, total=1000, shares={BO: 1000}, minute=1),
    ]
    result = derive_balances(events, group_id=GROUP, currency=AUD)
    assert cents_of(result) == {ALI: 2000, BO: -2000}


def test_an_expense_id_equal_to_a_settlement_id_is_not_a_duplicate() -> None:
    """Ids collide across types only in a test; the check is per event type."""
    events = [
        expense("x1", payer=ALI, total=1000, shares={BO: 1000}),
        settlement("x1", payer=BO, receiver=ALI, amount=1000, minute=1),
        decision("x1", settlement_id="x1", state=SettlementState.CONFIRMED, minute=2),
    ]
    result = derive_balances(events, group_id=GROUP, currency=AUD)
    assert cents_of(result) == {ALI: 0, BO: 0}
