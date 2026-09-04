"""Tests for the balance fold: events become pairwise debts and net positions.

Task 4 of plans/backlog.md, sharpened in plans/tasks/04-balance-derivation.md.

Property coverage is standard library rather than hypothesis, matching the dependency
decision task 3 made. Order independence is proved exhaustively over every permutation
of a small hand-written fixture, and the larger ledgers are shuffled by a generator
seeded from a fixed constant so any failure reproduces from the test alone.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import itertools
import random
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import splitwise_lite
from splitwise_lite import balances as balances_module
from splitwise_lite import events as events_module
from splitwise_lite import money as money_module
from splitwise_lite import split as split_module
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
    format_amount,
)

AUD = Currency("AUD")
NZD = Currency("NZD")

GROUP = GroupId("group-dinner")
OTHER_GROUP = GroupId("group-holiday")

ALI = MemberId("ali")
BO = MemberId("bo")
CASS = MemberId("cass")

THIRDS = {ALI: 1000, BO: 1000, CASS: 1000}

SEED = 20260904


EPOCH = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


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
        result.net[CASS] = Money(1, AUD)
    with pytest.raises(TypeError):
        result.pairwise[(CASS, ALI)] = Money(1, AUD)


def test_two_folds_of_the_same_events_compare_equal() -> None:
    events = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
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
        derive_balances([], GROUP, AUD)
    with pytest.raises(TypeError):
        derive_balances([], group_id=GROUP)
    with pytest.raises(TypeError):
        derive_balances([], currency=AUD)


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
        derive_balances(7, group_id=GROUP, currency=AUD)
    with pytest.raises(TypeError):
        settlement_states(7)


def test_an_element_that_is_not_a_ledger_event_raises_type_error_naming_it() -> None:
    not_an_event = {"total": 1000}
    with pytest.raises(TypeError, match="dict"):
        derive_balances([not_an_event], group_id=GROUP, currency=AUD)
    with pytest.raises(TypeError, match="NoneType"):
        settlement_states([None])


def test_a_group_id_that_is_not_a_str_raises_type_error() -> None:
    with pytest.raises(TypeError, match="int"):
        derive_balances([], group_id=7, currency=AUD)


def test_an_empty_group_id_is_a_domain_error() -> None:
    with pytest.raises(InvalidLedger):
        derive_balances([], group_id=GroupId(""), currency=AUD)


def test_a_currency_that_is_not_a_currency_raises_type_error() -> None:
    with pytest.raises(TypeError, match="str"):
        derive_balances([], group_id=GROUP, currency="AUD")


def test_a_foreign_group_names_the_event_and_both_groups() -> None:
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


# --- Sign conventions -------------------------------------------------------


def assert_consistent(balances: Balances) -> None:
    """Assert the invariants that must hold for every fold, whatever the input.

    Exact integer comparison throughout: a balance that is one cent out is wrong, and an
    approximate assertion would not notice.
    """
    net = cents_of(balances)
    debts = debts_of(balances)

    assert sum(net.values()) == 0
    assert all(amount > 0 for amount in debts.values())
    for debtor, creditor in debts:
        assert debtor != creditor
        assert (creditor, debtor) not in debts

    for member_id, position in net.items():
        owed_to_them = sum(
            amount for (_, creditor), amount in debts.items() if creditor == member_id
        )
        they_owe = sum(
            amount for (debtor, _), amount in debts.items() if debtor == member_id
        )
        assert position == owed_to_them - they_owe

    assert list(balances.net) == sorted(balances.net)
    assert list(balances.pairwise) == sorted(balances.pairwise)


def test_a_positive_net_means_the_group_owes_the_member() -> None:
    result = derive_balances(
        [expense("e1", payer=ALI, total=3000, shares=THIRDS)],
        group_id=GROUP,
        currency=AUD,
    )
    assert result.net_for(ALI) == Money(2000, AUD)
    assert result.net_for(BO) == Money(-1000, AUD)
    assert_consistent(result)


def test_owed_between_is_signed_and_total() -> None:
    result = derive_balances(
        [expense("e1", payer=ALI, total=1000, shares={BO: 1000})],
        group_id=GROUP,
        currency=AUD,
    )
    assert result.owed_between(BO, ALI) == Money(1000, AUD)
    assert result.owed_between(ALI, BO) == Money(-1000, AUD)
    assert result.owed_between(ALI, CASS) == Money(0, AUD)
    assert result.owed_between(CASS, CASS) == Money(0, AUD)


def test_iteration_ascends_by_member_and_by_pair() -> None:
    result = derive_balances(
        [
            expense(
                "e1",
                payer=CASS,
                total=300,
                shares={CASS: 100, BO: 100, ALI: 100},
            )
        ],
        group_id=GROUP,
        currency=AUD,
    )
    assert list(result.net) == [ALI, BO, CASS]
    assert list(result.pairwise) == [(ALI, CASS), (BO, CASS)]


# --- The expense fold -------------------------------------------------------


def test_payer_is_a_participant() -> None:
    """Ali pays 3000 for a dinner she also ate: her own share is no debt to herself."""
    result = derive_balances(
        [expense("e1", payer=ALI, total=3000, shares=THIRDS)],
        group_id=GROUP,
        currency=AUD,
    )
    assert cents_of(result) == {ALI: 2000, BO: -1000, CASS: -1000}
    assert debts_of(result) == {(BO, ALI): 1000, (CASS, ALI): 1000}
    assert_consistent(result)


def test_payer_is_not_a_participant() -> None:
    """Ali pays for a meal she did not eat, and holds a net entry all the same."""
    result = derive_balances(
        [expense("e1", payer=ALI, total=3000, shares={BO: 1500, CASS: 1500})],
        group_id=GROUP,
        currency=AUD,
    )
    assert cents_of(result) == {ALI: 3000, BO: -1500, CASS: -1500}
    assert debts_of(result) == {(BO, ALI): 1500, (CASS, ALI): 1500}
    assert_consistent(result)


def test_the_payer_as_the_only_participant_owes_nobody_and_still_appears() -> None:
    result = derive_balances(
        [expense("e1", payer=ALI, total=1000, shares={ALI: 1000})],
        group_id=GROUP,
        currency=AUD,
    )
    assert cents_of(result) == {ALI: 0}
    assert debts_of(result) == {}
    assert_consistent(result)


def test_a_zero_cent_allocation_is_no_debt_but_keeps_its_member_in_net() -> None:
    """Task 3 emits a zero share when a total is smaller than the head count."""
    result = derive_balances(
        [expense("e1", payer=ALI, total=2, shares={ALI: 1, BO: 1, CASS: 0})],
        group_id=GROUP,
        currency=AUD,
    )
    assert cents_of(result) == {ALI: 1, BO: -1, CASS: 0}
    assert debts_of(result) == {(BO, ALI): 1}
    assert_consistent(result)


def test_two_expenses_between_the_same_pair_accumulate_into_one_entry() -> None:
    result = derive_balances(
        [
            expense("e1", payer=ALI, total=1000, shares={BO: 1000}),
            expense("e2", payer=ALI, total=500, shares={BO: 500}, minute=1),
        ],
        group_id=GROUP,
        currency=AUD,
    )
    assert debts_of(result) == {(BO, ALI): 1500}
    assert cents_of(result) == {ALI: 1500, BO: -1500}
    assert_consistent(result)


def test_debts_in_opposite_directions_net_to_one_entry() -> None:
    result = derive_balances(
        [
            expense("e1", payer=ALI, total=1000, shares={BO: 1000}),
            expense("e2", payer=BO, total=400, shares={ALI: 400}, minute=1),
        ],
        group_id=GROUP,
        currency=AUD,
    )
    assert debts_of(result) == {(BO, ALI): 600}
    assert cents_of(result) == {ALI: 600, BO: -600}
    assert_consistent(result)


def test_debts_that_cancel_exactly_leave_no_entry() -> None:
    result = derive_balances(
        [
            expense("e1", payer=ALI, total=1000, shares={BO: 1000}),
            expense("e2", payer=BO, total=1000, shares={ALI: 1000}, minute=1),
        ],
        group_id=GROUP,
        currency=AUD,
    )
    assert debts_of(result) == {}
    assert cents_of(result) == {ALI: 0, BO: 0}
    assert_consistent(result)


def test_the_fold_credits_the_total_not_the_sum_of_the_allocations() -> None:
    """The two are equal by construction, so the payer's credit is the whole total."""
    result = derive_balances(
        [expense("e1", payer=ALI, total=999, shares={ALI: 333, BO: 333, CASS: 333})],
        group_id=GROUP,
        currency=AUD,
    )
    assert result.net_for(ALI) == Money(666, AUD)
    assert_consistent(result)


def test_a_three_way_cycle_stays_three_pairwise_entries() -> None:
    """Task 4 never merges debts to shorten the list; that is task 5's job."""
    result = derive_balances(
        [
            expense("e1", payer=ALI, total=1000, shares={BO: 1000}),
            expense("e2", payer=BO, total=1000, shares={CASS: 1000}, minute=1),
            expense("e3", payer=CASS, total=1000, shares={ALI: 1000}, minute=2),
        ],
        group_id=GROUP,
        currency=AUD,
    )
    assert cents_of(result) == {ALI: 0, BO: 0, CASS: 0}
    assert debts_of(result) == {
        (ALI, CASS): 1000,
        (BO, ALI): 1000,
        (CASS, BO): 1000,
    }
    assert_consistent(result)


# --- The settlement fold ----------------------------------------------------


def confirmed(
    event_id: str,
    *,
    payer: MemberId,
    receiver: MemberId,
    amount: int,
    minute: int = 1,
) -> list[LedgerEvent]:
    """A settlement and the receiver's confirmation of it, as two events."""
    return [
        settlement(
            event_id, payer=payer, receiver=receiver, amount=amount, minute=minute
        ),
        decision(
            f"d-{event_id}",
            settlement_id=event_id,
            state=SettlementState.CONFIRMED,
            minute=minute,
            decided_by=receiver,
        ),
    ]


def test_a_confirmed_settlement_credits_the_payer_and_debits_the_receiver() -> None:
    """Bo has handed over real money, so his position improves by what he paid."""
    result = derive_balances(
        confirmed("s1", payer=BO, receiver=ALI, amount=400),
        group_id=GROUP,
        currency=AUD,
    )
    assert cents_of(result) == {ALI: -400, BO: 400}
    assert_consistent(result)


def test_full_settlement_back_to_zero() -> None:
    """The three-person dinner, settled by both debtors and confirmed by the payer."""
    events: list[LedgerEvent] = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
    ]
    events += confirmed("s1", payer=BO, receiver=ALI, amount=1000, minute=1)
    events += confirmed("s2", payer=CASS, receiver=ALI, amount=1000, minute=2)

    result = derive_balances(events, group_id=GROUP, currency=AUD)
    assert cents_of(result) == {ALI: 0, BO: 0, CASS: 0}
    assert debts_of(result) == {}
    assert_consistent(result)


def test_a_partial_confirmed_settlement_reduces_the_debt() -> None:
    events: list[LedgerEvent] = [expense("e1", payer=ALI, total=3000, shares=THIRDS)]
    events += confirmed("s1", payer=BO, receiver=ALI, amount=600, minute=1)

    result = derive_balances(events, group_id=GROUP, currency=AUD)
    assert debts_of(result) == {(BO, ALI): 400, (CASS, ALI): 1000}
    assert cents_of(result) == {ALI: 1400, BO: -400, CASS: -1000}
    assert_consistent(result)


def test_a_pending_settlement_moves_nothing() -> None:
    without: list[LedgerEvent] = [
        expense("e1", payer=ALI, total=1000, shares={BO: 1000})
    ]
    with_pending = without + [
        settlement("s1", payer=CASS, receiver=ALI, amount=500, minute=1)
    ]

    result = derive_balances(with_pending, group_id=GROUP, currency=AUD)
    assert result == derive_balances(without, group_id=GROUP, currency=AUD)
    assert CASS not in result.net
    assert settlement_states(with_pending) == {"s1": SettlementState.PENDING}


def test_a_rejected_settlement_moves_nothing() -> None:
    without: list[LedgerEvent] = [
        expense("e1", payer=ALI, total=1000, shares={BO: 1000})
    ]
    with_rejected = without + [
        settlement("s1", payer=CASS, receiver=ALI, amount=500, minute=1),
        decision("d1", settlement_id="s1", state=SettlementState.REJECTED, minute=2),
    ]

    result = derive_balances(with_rejected, group_id=GROUP, currency=AUD)
    assert result == derive_balances(without, group_id=GROUP, currency=AUD)
    assert CASS not in result.net
    assert settlement_states(with_rejected) == {"s1": SettlementState.REJECTED}


def test_a_settlement_larger_than_the_debt_flips_the_pair() -> None:
    """The fold records what the log says and never clamps a settlement to a debt."""
    events: list[LedgerEvent] = [expense("e1", payer=ALI, total=3000, shares=THIRDS)]
    events += confirmed("s1", payer=BO, receiver=ALI, amount=1500, minute=1)

    result = derive_balances(events, group_id=GROUP, currency=AUD)
    assert debts_of(result) == {(ALI, BO): 500, (CASS, ALI): 1000}
    assert cents_of(result) == {ALI: 500, BO: 500, CASS: -1000}
    assert_consistent(result)


def test_a_settlement_with_no_expense_behind_it_creates_the_opposite_debt() -> None:
    """Handing someone money for nothing is recordable, and leaves them owing it."""
    result = derive_balances(
        confirmed("s1", payer=BO, receiver=CASS, amount=750),
        group_id=GROUP,
        currency=AUD,
    )
    assert debts_of(result) == {(CASS, BO): 750}
    assert cents_of(result) == {BO: 750, CASS: -750}
    assert_consistent(result)


# --- Settlement state -------------------------------------------------------


def test_a_settlement_with_no_decision_is_pending() -> None:
    events = [settlement("s1", payer=BO, receiver=ALI, amount=100)]
    assert settlement_states(events) == {"s1": SettlementState.PENDING}


def test_every_settlement_gets_one_entry_keyed_ascending() -> None:
    events = [
        settlement("s-c", payer=BO, receiver=ALI, amount=100, minute=1),
        settlement("s-a", payer=BO, receiver=ALI, amount=100, minute=2),
        settlement("s-b", payer=CASS, receiver=ALI, amount=100, minute=3),
        decision("d1", settlement_id="s-b", state=SettlementState.CONFIRMED, minute=4),
    ]
    states = settlement_states(events)
    assert list(states) == ["s-a", "s-b", "s-c"]
    assert states == {
        "s-a": SettlementState.PENDING,
        "s-b": SettlementState.CONFIRMED,
        "s-c": SettlementState.PENDING,
    }


def test_a_confirmation_at_ten_beats_a_rejection_at_eleven() -> None:
    events = [
        settlement("s1", payer=BO, receiver=ALI, amount=100),
        decision("d1", settlement_id="s1", state=SettlementState.CONFIRMED, minute=10),
        decision("d2", settlement_id="s1", state=SettlementState.REJECTED, minute=11),
    ]
    assert settlement_states(events) == {"s1": SettlementState.CONFIRMED}


def test_a_rejection_at_ten_beats_a_confirmation_at_eleven() -> None:
    """A later CONFIRMED after an earlier REJECTED is ignored, like any late answer."""
    events = [
        settlement("s1", payer=BO, receiver=ALI, amount=100),
        decision("d1", settlement_id="s1", state=SettlementState.REJECTED, minute=10),
        decision("d2", settlement_id="s1", state=SettlementState.CONFIRMED, minute=11),
    ]
    assert settlement_states(events) == {"s1": SettlementState.REJECTED}


def test_two_decisions_on_one_timestamp_are_broken_by_the_smaller_id() -> None:
    base = [settlement("s1", payer=BO, receiver=ALI, amount=100)]
    smaller_confirms = base + [
        decision("d-a", settlement_id="s1", state=SettlementState.CONFIRMED, minute=5),
        decision("d-b", settlement_id="s1", state=SettlementState.REJECTED, minute=5),
    ]
    smaller_rejects = base + [
        decision("d-a", settlement_id="s1", state=SettlementState.REJECTED, minute=5),
        decision("d-b", settlement_id="s1", state=SettlementState.CONFIRMED, minute=5),
    ]
    assert settlement_states(smaller_confirms) == {"s1": SettlementState.CONFIRMED}
    assert settlement_states(smaller_rejects) == {"s1": SettlementState.REJECTED}
    assert settlement_states(list(reversed(smaller_confirms))) == {
        "s1": SettlementState.CONFIRMED
    }
    assert settlement_states(list(reversed(smaller_rejects))) == {
        "s1": SettlementState.REJECTED
    }


def test_a_decision_naming_no_settlement_in_the_input_is_ignored() -> None:
    events = [
        settlement("s1", payer=BO, receiver=ALI, amount=100),
        decision("d1", settlement_id="s-elsewhere", state=SettlementState.CONFIRMED),
    ]
    assert settlement_states(events) == {"s1": SettlementState.PENDING}
    assert derive_balances(events, group_id=GROUP, currency=AUD) == derive_balances(
        [events[0]], group_id=GROUP, currency=AUD
    )


def test_an_orphan_decision_alone_is_ignored_rather_than_rejected() -> None:
    orphan = [
        decision("d1", settlement_id="s-elsewhere", state=SettlementState.CONFIRMED)
    ]
    assert settlement_states(orphan) == {}
    assert derive_balances(orphan, group_id=GROUP, currency=AUD) == derive_balances(
        [], group_id=GROUP, currency=AUD
    )


def test_decisions_are_not_group_checked() -> None:
    """A decision carries no group, so it can only be bound through its settlement."""
    events: list[LedgerEvent] = [
        settlement("s1", payer=BO, receiver=ALI, amount=400),
        decision("d1", settlement_id="s1", state=SettlementState.CONFIRMED, minute=1),
    ]
    result = derive_balances(events, group_id=GROUP, currency=AUD)
    assert cents_of(result) == {ALI: -400, BO: 400}


def test_expense_events_are_ignored_rather_than_rejected_by_the_state_map() -> None:
    """The same whole-log list goes to both public functions."""
    events: list[LedgerEvent] = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        settlement("s1", payer=BO, receiver=ALI, amount=1000, minute=1),
    ]
    assert settlement_states(events) == {"s1": SettlementState.PENDING}


def test_the_decider_is_not_checked_against_the_receiver() -> None:
    """Task 15 owns that rule; it needs both records loaded, and this does not."""
    events = [
        settlement("s1", payer=BO, receiver=ALI, amount=400),
        decision(
            "d1",
            settlement_id="s1",
            state=SettlementState.CONFIRMED,
            minute=1,
            decided_by=CASS,
        ),
    ]
    assert settlement_states(events) == {"s1": SettlementState.CONFIRMED}
    assert cents_of(derive_balances(events, group_id=GROUP, currency=AUD)) == {
        ALI: -400,
        BO: 400,
    }


def test_the_balances_and_the_rendered_state_can_never_disagree() -> None:
    events: list[LedgerEvent] = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        settlement("s1", payer=BO, receiver=ALI, amount=1000, minute=1),
        settlement("s2", payer=CASS, receiver=ALI, amount=1000, minute=2),
        decision("d1", settlement_id="s1", state=SettlementState.CONFIRMED, minute=3),
        decision("d2", settlement_id="s2", state=SettlementState.REJECTED, minute=4),
        decision("d3", settlement_id="s2", state=SettlementState.CONFIRMED, minute=5),
    ]
    states = settlement_states(events)
    result = derive_balances(events, group_id=GROUP, currency=AUD)

    assert states == {
        "s1": SettlementState.CONFIRMED,
        "s2": SettlementState.REJECTED,
    }
    # Only s1 moved money: Bo is square and Cass still owes the whole third.
    assert cents_of(result) == {ALI: 1000, BO: 0, CASS: -1000}
    assert debts_of(result) == {(CASS, ALI): 1000}
    assert_consistent(result)


# --- Display edge -----------------------------------------------------------


def test_every_public_figure_is_money_in_the_group_currency() -> None:
    result = derive_balances(
        [expense("e1", payer=ALI, total=1250, shares={BO: 1250})],
        group_id=GROUP,
        currency=AUD,
    )
    assert all(money.currency == AUD for money in result.net.values())
    assert all(money.currency == AUD for money in result.pairwise.values())
    assert result.net_for(CASS).currency == AUD
    assert result.owed_between(ALI, CASS).currency == AUD


def test_a_negative_net_renders_straight_through_format_amount() -> None:
    result = derive_balances(
        [expense("e1", payer=ALI, total=1250, shares={BO: 1250})],
        group_id=GROUP,
        currency=AUD,
    )
    assert format_amount(result.net_for(BO)) == "-12.50"
    assert format_amount(result.net_for(ALI)) == "12.50"


# --- Order independence -----------------------------------------------------


def six_event_ledger() -> list[LedgerEvent]:
    """One expense, two settlements, and two decisions that conflict over one of them.

    Six events, so every one of the 720 orderings can be folded in the test below.
    """
    return [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        settlement("s1", payer=BO, receiver=ALI, amount=1000, minute=1),
        settlement("s2", payer=CASS, receiver=ALI, amount=1000, minute=2),
        decision("d1", settlement_id="s1", state=SettlementState.CONFIRMED, minute=3),
        decision("d2", settlement_id="s2", state=SettlementState.REJECTED, minute=4),
        decision("d3", settlement_id="s2", state=SettlementState.CONFIRMED, minute=5),
    ]


def test_every_permutation_of_six_events_folds_to_one_identical_answer() -> None:
    """Exhaustive where it can be: 720 orderings, one balance and one state map."""
    ledger = six_event_ledger()
    expected = derive_balances(ledger, group_id=GROUP, currency=AUD)
    expected_states = settlement_states(ledger)

    for ordering in itertools.permutations(ledger):
        shuffled = list(ordering)
        assert derive_balances(shuffled, group_id=GROUP, currency=AUD) == expected
        assert settlement_states(shuffled) == expected_states


def test_every_permutation_agrees_on_iteration_order_too() -> None:
    """Equality ignores order, so the rendered rows are compared as lists as well."""
    ledger = six_event_ledger()
    expected = derive_balances(ledger, group_id=GROUP, currency=AUD)

    for ordering in itertools.permutations(ledger):
        result = derive_balances(list(ordering), group_id=GROUP, currency=AUD)
        assert list(result.net.items()) == list(expected.net.items())
        assert list(result.pairwise.items()) == list(expected.pairwise.items())
        assert list(settlement_states(list(ordering))) == ["s1", "s2"]


# --- Property: randomly generated ledgers -----------------------------------


ROSTER = [MemberId(f"m{index}") for index in range(5)]


def random_ledger(rng: random.Random, size: int) -> list[LedgerEvent]:
    """A ledger of ``size`` entries mixing expenses with settlements in every state.

    Ids are unique by construction, timestamps ascend, and every amount is a whole
    number of cents, so the only thing that varies is the shape of the ledger.
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
        events.append(
            settlement(
                f"s{index}",
                payer=payer,
                receiver=receiver,
                amount=rng.randint(1, 1000),
                minute=minute,
            )
        )
        outcome = rng.choice(
            (None, SettlementState.CONFIRMED, SettlementState.REJECTED)
        )
        if outcome is not None:
            events.append(
                decision(
                    f"d{index}",
                    settlement_id=f"s{index}",
                    state=outcome,
                    minute=minute,
                )
            )
    return events


def test_every_random_ledger_holds_every_invariant() -> None:
    """Net sums to zero, debts are positive and one-directional, and the two agree."""
    rng = random.Random(SEED)
    for _ in range(200):
        events = random_ledger(rng, rng.randint(0, 20))
        assert_consistent(derive_balances(events, group_id=GROUP, currency=AUD))


def test_shuffling_a_random_ledger_never_changes_the_answer() -> None:
    rng = random.Random(SEED + 1)
    for _ in range(100):
        events = random_ledger(rng, rng.randint(1, 20))
        expected = derive_balances(events, group_id=GROUP, currency=AUD)
        expected_states = settlement_states(events)
        for _ in range(3):
            shuffled = list(events)
            rng.shuffle(shuffled)
            assert derive_balances(shuffled, group_id=GROUP, currency=AUD) == expected
            assert settlement_states(shuffled) == expected_states


def test_settling_every_outstanding_debt_closes_the_group() -> None:
    """The closure property task 5 leans on: one confirmed settlement per debt."""
    rng = random.Random(SEED + 2)
    for _ in range(50):
        events = random_ledger(rng, rng.randint(1, 20))
        outstanding = derive_balances(events, group_id=GROUP, currency=AUD).pairwise

        closing = list(events)
        for index, (pair, owed) in enumerate(outstanding.items()):
            debtor, creditor = pair
            closing += confirmed(
                f"close-{index}",
                payer=debtor,
                receiver=creditor,
                amount=owed.cents,
                minute=1000 + index,
            )

        settled = derive_balances(closing, group_id=GROUP, currency=AUD)
        assert dict(settled.pairwise) == {}
        assert set(cents_of(settled).values()) <= {0}


# --- Arithmetic: integer cents, and no division at all ----------------------


def _module_tree(module) -> ast.Module:
    return ast.parse(Path(inspect.getfile(module)).read_text(encoding="utf-8"))


def _names(tree: ast.Module) -> set[str]:
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return names | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }


@pytest.mark.parametrize("forbidden", ["float", "round", "Decimal", "divmod"])
def test_the_balance_module_never_names_a_rounding_tool(forbidden: str) -> None:
    assert forbidden not in _names(_module_tree(balances_module))


@pytest.mark.parametrize(
    "operator",
    [ast.Div, ast.FloorDiv, ast.Mod],
    ids=["true division", "floor division", "modulo"],
)
def test_the_balance_module_never_divides(operator: type[ast.operator]) -> None:
    """The fold only adds and subtracts, so no remainder can arise to be assigned."""
    tree = _module_tree(balances_module)
    divisions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.BinOp, ast.AugAssign))
        and isinstance(node.op, operator)
    ]
    assert divisions == []


def test_the_fold_sorts_with_the_ordering_key_events_py_defines() -> None:
    """Not re-derived here: one tie-break rule, shared by every consumer of the log."""
    assert "ordering_key" in _names(_module_tree(balances_module))
    assert balances_module.ordering_key is events_module.ordering_key


def test_no_stored_amount_bound_is_applied_to_a_derived_balance() -> None:
    """Balances are derived and never stored, so there is no column to overflow."""
    events = [
        expense("e1", payer=ALI, total=MAX_CENTS, shares={BO: MAX_CENTS}),
        expense("e2", payer=ALI, total=MAX_CENTS, shares={BO: MAX_CENTS}, minute=1),
    ]
    result = derive_balances(events, group_id=GROUP, currency=AUD)
    assert result.net_for(ALI) == Money(MAX_CENTS + MAX_CENTS, AUD)
    assert result.owed_between(BO, ALI) == Money(MAX_CENTS + MAX_CENTS, AUD)
    assert_consistent(result)


@pytest.mark.parametrize("forbidden", ["hash", "random", "time", "uuid", "datetime"])
def test_the_fold_is_a_pure_function_of_its_inputs(forbidden: str) -> None:
    """No clock, no randomness, and nothing salted per process deciding an answer."""
    assert forbidden not in _names(_module_tree(balances_module))


def test_the_module_keeps_no_mutable_state_to_memoise_into() -> None:
    mutable = {
        name: value
        for name, value in vars(balances_module).items()
        if not name.startswith("__")
        and isinstance(value, (dict, list, set, bytearray))
    }
    assert mutable == {}


def test_two_folds_in_a_row_do_not_drift() -> None:
    events = six_event_ledger()
    first = derive_balances(events, group_id=GROUP, currency=AUD)
    second = derive_balances(events, group_id=GROUP, currency=AUD)
    assert first == second
    assert list(first.net.items()) == list(second.net.items())
    assert list(first.pairwise.items()) == list(second.pairwise.items())


# --- Dependency direction ---------------------------------------------------


def _imported(tree: ast.Module) -> set[str]:
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    return imported


def test_balances_imports_only_money_and_events_from_the_package() -> None:
    imported = _imported(_module_tree(balances_module))
    assert {name for name in imported if name in {"money", "events", "split"}} == {
        "money",
        "events",
    }
    assert not any("splitwise_lite" in name for name in imported)


@pytest.mark.parametrize(
    "module",
    [money_module, events_module, split_module],
    ids=["money", "events", "split"],
)
def test_the_earlier_modules_never_learn_about_the_fold(module) -> None:
    assert "balances" not in _imported(_module_tree(module))


def test_the_fold_is_re_exported_from_the_package_root() -> None:
    assert splitwise_lite.derive_balances is derive_balances
    assert splitwise_lite.settlement_states is settlement_states
    assert splitwise_lite.Balances is Balances
    assert splitwise_lite.InvalidLedger is InvalidLedger
    assert {
        "Balances",
        "InvalidLedger",
        "derive_balances",
        "settlement_states",
    } <= set(splitwise_lite.__all__)


def test_the_package_version_is_untouched() -> None:
    assert splitwise_lite.__version__ == "0.1.0"
