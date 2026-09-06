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
    DebtEffect,
    DebtEntry,
    DebtEntryKind,
    DebtSources,
    InvalidLedger,
    debt_sources,
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


def test_both_public_functions_refuse_a_log_that_double_counts_an_expense() -> None:
    """settlement_states ignores expenses for state, but not for the id check.

    The alternative would let a caller render settlement rows for a ledger whose
    balances ``derive_balances`` refuses to compute, which is the disagreement between
    two readers of one log that this module exists to rule out.
    """
    events = [
        expense("e1", payer=ALI, total=1000, shares={BO: 1000}),
        expense("e1", payer=ALI, total=1000, shares={BO: 1000}, minute=1),
        settlement("s1", payer=BO, receiver=ALI, amount=100, minute=2),
    ]
    with pytest.raises(InvalidLedger, match="e1"):
        derive_balances(events, group_id=GROUP, currency=AUD)
    with pytest.raises(InvalidLedger, match="e1"):
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
    """A documentation test rather than a discriminating one.

    ``ExpenseEvent`` enforces that the allocations sum to the total, so no input can
    tell the two readings apart and this assertion would hold either way. It is here to
    record which one the fold takes, because the fold deliberately re-checks none of
    task 2's construction invariants.
    """
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


def test_the_balance_module_holds_no_float_literal() -> None:
    """The name check above would miss ``0.5``; this catches the literal itself."""
    tree = _module_tree(balances_module)
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
    # Task 12a's walk and its four types, re-exported on the same terms as the fold
    # they are checked against.
    assert splitwise_lite.debt_sources is debt_sources
    assert splitwise_lite.DebtSources is DebtSources
    assert splitwise_lite.DebtEntry is DebtEntry
    assert splitwise_lite.DebtEntryKind is DebtEntryKind
    assert splitwise_lite.DebtEffect is DebtEffect
    assert {
        "Balances",
        "DebtEffect",
        "DebtEntry",
        "DebtEntryKind",
        "DebtSources",
        "InvalidLedger",
        "debt_sources",
        "derive_balances",
        "settlement_states",
    } <= set(splitwise_lite.__all__)


def test_the_package_version_is_untouched() -> None:
    assert splitwise_lite.__version__ == "0.1.0"


# --- Debt sources: shape and contract ---------------------------------------
#
# Task 12a of plans/backlog.md, sharpened in
# plans/tasks/12a-transfer-provenance-api.md. ``debt_sources`` answers "what is the
# debt from d to c made of", and its whole contract is that its entries sum to
# exactly what ``derive_balances`` derives for that pair. Every assertion below is on
# integer cents and is exact.

DEE = MemberId("dee")
"""A fourth member, so the exhaustive pool below holds a pair neither party of
another pair belongs to, and so a third-party payer has somebody to be third to."""

UNSEEN = MemberId("nobody-the-ledger-has-met")


def sources(
    events: list[LedgerEvent],
    *,
    debtor: MemberId = BO,
    creditor: MemberId = ALI,
    group_id: GroupId = GROUP,
    currency: Currency = AUD,
) -> DebtSources:
    """``debt_sources`` with the boilerplate filled in, defaulting to Bo owing Ali."""
    return debt_sources(
        events,
        debtor=debtor,
        creditor=creditor,
        group_id=group_id,
        currency=currency,
    )


def rows_of(found: DebtSources) -> list[tuple[str, str, str, int]]:
    """Each entry as ``(kind, effect, event_id, cents)``, for exact comparison."""
    return [
        (entry.kind.value, entry.effect.value, entry.event_id, entry.amount.cents)
        for entry in found.entries
    ]


def flipped(effect: DebtEffect) -> DebtEffect:
    """The other way round, which is what swapping the pair does to every entry."""
    return DebtEffect.REDUCES if effect is DebtEffect.ADDS else DebtEffect.ADDS


def signed_sum(found: DebtSources) -> int:
    """The entries added up the way the invariant states, in plain integer cents."""
    total = 0
    for entry in found.entries:
        if entry.effect is DebtEffect.ADDS:
            total += entry.amount.cents
        else:
            total -= entry.amount.cents
    return total


def ordering_key_of(entry: DebtEntry) -> tuple:
    """The entry's place in the ledger's one total order: ``(created_at, id)``."""
    return (entry.created_at, entry.event_id)


def test_the_four_new_types_and_the_function_are_public() -> None:
    assert {
        "DebtEffect",
        "DebtEntry",
        "DebtEntryKind",
        "DebtSources",
        "debt_sources",
    } <= set(balances_module.__all__)


def test_both_new_dataclasses_are_frozen_with_slots() -> None:
    for klass in (DebtSources, DebtEntry):
        assert dataclasses.is_dataclass(klass), klass
        assert klass.__dataclass_params__.frozen is True, klass
        assert hasattr(klass, "__slots__"), klass


def test_debt_sources_holds_exactly_six_fields_in_the_documented_order() -> None:
    assert [field.name for field in dataclasses.fields(DebtSources)] == [
        "group_id",
        "currency",
        "debtor",
        "creditor",
        "amount",
        "entries",
    ]


def test_a_debt_entry_holds_exactly_six_fields_in_the_documented_order() -> None:
    # No display name, no member id other than the pair's, no allocation list and no
    # expense total: each of those would be a second copy of something another
    # endpoint already answers, free to drift from it.
    assert [field.name for field in dataclasses.fields(DebtEntry)] == [
        "kind",
        "effect",
        "event_id",
        "description",
        "amount",
        "created_at",
    ]


def test_the_two_enums_hold_their_names_as_their_values() -> None:
    assert [(member.name, member.value) for member in DebtEntryKind] == [
        ("EXPENSE", "EXPENSE"),
        ("SETTLEMENT", "SETTLEMENT"),
    ]
    assert [(member.name, member.value) for member in DebtEffect] == [
        ("ADDS", "ADDS"),
        ("REDUCES", "REDUCES"),
    ]


def test_every_new_public_name_is_documented() -> None:
    for name in (
        "debt_sources",
        "DebtSources",
        "DebtEntry",
        "DebtEntryKind",
        "DebtEffect",
    ):
        assert (getattr(balances_module, name).__doc__ or "").strip(), name


def test_events_is_positional_and_the_other_four_are_keyword_only() -> None:
    parameters = inspect.signature(debt_sources).parameters
    assert parameters["events"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for name in ("debtor", "creditor", "group_id", "currency"):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameters[name].default is inspect.Parameter.empty, name


def test_an_empty_ledger_is_a_settled_pair_with_no_entries() -> None:
    found = sources([])
    assert found.group_id == GROUP
    assert found.currency == AUD
    assert found.debtor == BO
    assert found.creditor == ALI
    assert found.amount == Money(0, AUD)
    assert found.entries == ()


def test_a_member_the_ledger_has_never_seen_gets_an_empty_answer() -> None:
    # This module does not know what a group's members are, exactly as tasks 2, 4 and
    # 5 decided, so an unknown id is a settled pair rather than a refusal.
    ledger = [expense("e1", payer=ALI, total=3000, shares=THIRDS)]
    found = sources(ledger, debtor=UNSEEN, creditor=ALI)
    assert found.entries == ()
    assert found.amount == Money(0, AUD)


def test_every_money_in_the_result_carries_the_currency() -> None:
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        *confirmed("s1", payer=BO, receiver=ALI, amount=400, minute=2),
    ]
    found = sources(ledger)
    assert found.amount.currency == AUD
    assert [entry.amount.currency for entry in found.entries] == [AUD, AUD]


def test_every_entry_amount_is_strictly_positive() -> None:
    # The sign is carried by ``effect`` and by nothing else.
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        expense("e2", payer=BO, total=900, shares={ALI: 500, BO: 400}, minute=1),
        *confirmed("s1", payer=BO, receiver=ALI, amount=400, minute=2),
    ]
    found = sources(ledger)
    assert len(found.entries) == 3
    for entry in found.entries:
        assert entry.amount.cents > 0, entry


def test_the_amount_is_exactly_what_the_real_fold_derives_for_the_pair() -> None:
    # Through ``derive_balances`` rather than by re-deriving the figure here: the two
    # must agree by construction, and a test that recomputed it would prove nothing.
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        expense("e2", payer=BO, total=900, shares={ALI: 500, BO: 400}, minute=1),
        *confirmed("s1", payer=BO, receiver=ALI, amount=400, minute=2),
    ]
    derived = derive_balances(ledger, group_id=GROUP, currency=AUD)
    for debtor, creditor in itertools.permutations([ALI, BO, CASS], 2):
        found = sources(ledger, debtor=debtor, creditor=creditor)
        assert found.amount == derived.owed_between(debtor, creditor)
        assert signed_sum(found) == derived.owed_between(debtor, creditor).cents


def test_events_may_be_a_generator_and_is_consumed_exactly_once() -> None:
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        expense("e2", payer=BO, total=900, shares={ALI: 500, BO: 400}, minute=1),
    ]
    reads = 0

    def once():
        nonlocal reads
        for event in ledger:
            reads += 1
            yield event

    found = debt_sources(
        once(), debtor=BO, creditor=ALI, group_id=GROUP, currency=AUD
    )
    assert reads == len(ledger)
    assert len(found.entries) == 2


def test_the_callers_list_is_neither_mutated_nor_reordered_by_a_walk() -> None:
    ledger = [
        expense("e2", payer=BO, total=900, shares={ALI: 500, BO: 400}, minute=5),
        expense("e1", payer=ALI, total=3000, shares=THIRDS, minute=1),
    ]
    before = list(ledger)
    sources(ledger)
    assert ledger == before


def test_two_walks_of_the_same_events_and_of_a_shuffled_copy_are_equal() -> None:
    ledger = six_event_ledger()
    first = sources(ledger)
    assert sources(ledger) == first
    rng = random.Random(SEED)
    for _ in range(20):
        shuffled = list(ledger)
        rng.shuffle(shuffled)
        assert sources(shuffled) == first


def test_swapping_the_pair_flips_every_effect_and_negates_the_amount() -> None:
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        expense("e2", payer=BO, total=900, shares={ALI: 500, BO: 400}, minute=1),
        *confirmed("s1", payer=BO, receiver=ALI, amount=400, minute=2),
    ]
    forward = sources(ledger, debtor=BO, creditor=ALI)
    backward = sources(ledger, debtor=ALI, creditor=BO)
    assert [entry.event_id for entry in backward.entries] == [
        entry.event_id for entry in forward.entries
    ]
    assert [entry.amount for entry in backward.entries] == [
        entry.amount for entry in forward.entries
    ]
    assert [entry.effect for entry in backward.entries] == [
        flipped(entry.effect) for entry in forward.entries
    ]
    assert backward.amount.cents == -forward.amount.cents


def test_entries_ascend_by_the_ordering_key_events_py_defines() -> None:
    # The ledger's one total order: created_at ascending with ties broken by ascending
    # event id, never list position and never created_at alone.
    ledger = [
        expense("e-b", payer=ALI, total=100, shares={BO: 100}, minute=2),
        expense("e-a", payer=ALI, total=100, shares={BO: 100}, minute=2),
        expense("e-c", payer=ALI, total=100, shares={BO: 100}, minute=1),
    ]
    found = sources(ledger)
    assert [entry.event_id for entry in found.entries] == ["e-c", "e-a", "e-b"]
    assert [entry.created_at for entry in found.entries] == [at(1), at(2), at(2)]


def test_one_expense_yields_at_most_one_entry_and_event_ids_are_unique() -> None:
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        expense("e2", payer=ALI, total=3000, shares=THIRDS, minute=1),
        *confirmed("s1", payer=BO, receiver=ALI, amount=400, minute=2),
    ]
    found = sources(ledger)
    ids = [entry.event_id for entry in found.entries]
    assert ids == ["e1", "e2", "s1"]
    assert len(set(ids)) == len(ids)


def test_a_description_is_passed_through_verbatim_including_empty() -> None:
    ledger = [
        ExpenseEvent(
            id=ExpenseId("e1"),
            group_id=GROUP,
            currency=AUD,
            payer_id=ALI,
            total_cents=1000,
            allocations=(Allocation(BO, 1000),),
            description="Milk and bread",
            created_at=at(1),
            created_by=ALI,
        ),
        expense("e2", payer=ALI, total=500, shares={BO: 500}, minute=2),
    ]
    found = sources(ledger)
    assert [entry.description for entry in found.entries] == ["Milk and bread", ""]


def test_a_settlement_entry_carries_an_empty_description() -> None:
    # ``SettlementEvent`` has none, and substituting placeholder text here would put a
    # sentence this repo wrote into a list of what people actually recorded.
    found = sources(confirmed("s1", payer=BO, receiver=ALI, amount=400))
    assert [entry.description for entry in found.entries] == [""]


# --- Debt sources: refusals -------------------------------------------------


@pytest.mark.parametrize("field", ["debtor", "creditor"])
def test_a_member_id_that_is_not_a_str_raises_type_error_naming_the_type(
    field: str,
) -> None:
    arguments = {"debtor": BO, "creditor": ALI, field: 7}
    with pytest.raises(TypeError) as raised:
        debt_sources([], group_id=GROUP, currency=AUD, **arguments)
    assert field in str(raised.value)
    assert "int" in str(raised.value)


@pytest.mark.parametrize("field", ["debtor", "creditor"])
def test_an_empty_member_id_is_a_domain_error(field: str) -> None:
    arguments = {"debtor": BO, "creditor": ALI, field: ""}
    with pytest.raises(InvalidLedger):
        debt_sources([], group_id=GROUP, currency=AUD, **arguments)


def test_a_member_cannot_owe_themselves() -> None:
    # Answering with an empty list would present a meaningless question as a settled
    # pair, which is the one answer a reader would take at face value.
    with pytest.raises(InvalidLedger) as raised:
        sources([], debtor=BO, creditor=BO)
    assert "bo" in str(raised.value)


def test_a_group_id_that_is_not_a_str_raises_type_error_for_a_walk_too() -> None:
    with pytest.raises(TypeError):
        sources([], group_id=7)


def test_an_empty_group_id_is_a_domain_error_for_a_walk_too() -> None:
    with pytest.raises(InvalidLedger):
        sources([], group_id=GroupId(""))


def test_a_currency_that_is_not_a_currency_raises_type_error_for_a_walk_too() -> None:
    with pytest.raises(TypeError):
        sources([], currency="AUD")


def test_events_that_is_not_an_iterable_of_events_raises_type_error_for_a_walk() -> None:
    with pytest.raises(TypeError):
        sources(7)
    with pytest.raises(TypeError):
        sources(["not an event"])


def test_a_foreign_group_is_refused_on_the_same_terms_as_the_fold() -> None:
    # A caller must never be able to list entries for a ledger whose balances
    # ``derive_balances`` would refuse to compute.
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        expense(
            "e2",
            payer=ALI,
            total=600,
            shares={BO: 600},
            minute=1,
            group_id=OTHER_GROUP,
        ),
    ]
    with pytest.raises(InvalidLedger):
        derive_balances(ledger, group_id=GROUP, currency=AUD)
    with pytest.raises(InvalidLedger) as raised:
        sources(ledger)
    assert "e2" in str(raised.value)


def test_a_foreign_settlement_is_refused_for_a_walk_too() -> None:
    ledger = [
        settlement("s1", payer=BO, receiver=ALI, amount=400, group_id=OTHER_GROUP)
    ]
    with pytest.raises(InvalidLedger):
        sources(ledger)


def test_a_repeated_event_id_is_refused_for_a_walk_too() -> None:
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        expense("e1", payer=ALI, total=3000, shares=THIRDS, minute=1),
    ]
    with pytest.raises(InvalidLedger) as raised:
        sources(ledger)
    assert "e1" in str(raised.value)


def test_a_foreign_currency_raises_currency_mismatch_for_a_walk_too() -> None:
    ledger = [expense("e1", payer=ALI, total=600, shares={BO: 600}, currency=NZD)]
    with pytest.raises(CurrencyMismatch) as raised:
        sources(ledger)
    assert "NZD" in str(raised.value)
    assert "AUD" in str(raised.value)


def test_a_settlement_in_a_foreign_currency_raises_currency_mismatch_too() -> None:
    ledger = [settlement("s1", payer=BO, receiver=ALI, amount=400, currency=NZD)]
    with pytest.raises(CurrencyMismatch):
        sources(ledger)


def test_no_new_exception_class_is_added_to_the_module() -> None:
    # ``InvalidLedger`` and ``CurrencyMismatch`` cover every rejection this walk
    # makes, so web.py's two error tables and the DELIBERATELY_UNMAPPED set in
    # tests/test_web_api.py are all unchanged.
    defined = {
        name
        for name, value in vars(balances_module).items()
        if isinstance(value, type) and issubclass(value, DomainError)
    }
    assert defined == {"DomainError", "CurrencyMismatch", "InvalidLedger"}


def test_validation_is_eager_so_a_rejected_call_produces_no_partial_answer() -> None:
    # The foreign expense sorts last, so a walk that answered over the events it liked
    # would return one entry rather than raising.
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        expense(
            "e2",
            payer=ALI,
            total=600,
            shares={BO: 600},
            minute=9,
            group_id=OTHER_GROUP,
        ),
    ]
    with pytest.raises(InvalidLedger):
        sources(ledger)


# --- Debt sources: what is and is not an entry ------------------------------


def test_an_expense_paid_by_the_creditor_adds_the_debtors_allocation() -> None:
    # The debtor's allocation, never the expense total.
    ledger = [expense("e1", payer=ALI, total=3000, shares=THIRDS)]
    found = sources(ledger, debtor=BO, creditor=ALI)
    assert rows_of(found) == [("EXPENSE", "ADDS", "e1", 1000)]
    assert found.amount == Money(1000, AUD)


def test_an_expense_paid_by_the_debtor_reduces_the_creditors_allocation() -> None:
    ledger = [expense("e1", payer=BO, total=900, shares={ALI: 500, BO: 400})]
    found = sources(ledger, debtor=BO, creditor=ALI)
    assert rows_of(found) == [("EXPENSE", "REDUCES", "e1", 500)]
    assert found.amount == Money(-500, AUD)


def test_an_expense_paid_by_a_third_member_yields_no_entry() -> None:
    # Two people who split a third person's expense owe that third person, not each
    # other.
    ledger = [expense("e1", payer=CASS, total=1200, shares={ALI: 600, BO: 600})]
    found = sources(ledger, debtor=BO, creditor=ALI)
    assert found.entries == ()
    assert found.amount == Money(0, AUD)


def test_a_zero_cent_allocation_yields_no_entry() -> None:
    ledger = [expense("e1", payer=ALI, total=700, shares={ALI: 700, BO: 0})]
    found = sources(ledger, debtor=BO, creditor=ALI)
    assert found.entries == ()


def test_the_payers_own_allocation_yields_no_entry() -> None:
    # A member does not owe themselves, so Ali's own share of Ali's expense is absent
    # and the pair reads only Bo's share.
    ledger = [expense("e1", payer=ALI, total=3000, shares=THIRDS)]
    found = sources(ledger, debtor=BO, creditor=ALI)
    assert rows_of(found) == [("EXPENSE", "ADDS", "e1", 1000)]


def test_a_confirmed_settlement_from_the_creditor_adds_its_whole_amount() -> None:
    found = sources(confirmed("s1", payer=ALI, receiver=BO, amount=750))
    assert rows_of(found) == [("SETTLEMENT", "ADDS", "s1", 750)]


def test_a_confirmed_settlement_from_the_debtor_reduces_its_whole_amount() -> None:
    found = sources(confirmed("s1", payer=BO, receiver=ALI, amount=750))
    assert rows_of(found) == [("SETTLEMENT", "REDUCES", "s1", 750)]


def test_a_pending_settlement_yields_no_entry() -> None:
    # It moved no money. Putting a claimed payment in a list that explains a live
    # figure is the "two people see two versions of the truth" failure the spec's
    # third section exists to stop.
    ledger = [settlement("s1", payer=BO, receiver=ALI, amount=750)]
    found = sources(ledger)
    assert found.entries == ()
    assert found.amount == Money(0, AUD)


def test_a_rejected_settlement_yields_no_entry() -> None:
    ledger = [
        settlement("s1", payer=BO, receiver=ALI, amount=750),
        decision("d1", settlement_id="s1", state=SettlementState.REJECTED, minute=1),
    ]
    found = sources(ledger)
    assert found.entries == ()


def test_a_settlement_between_other_members_yields_no_entry() -> None:
    found = sources(confirmed("s1", payer=CASS, receiver=DEE, amount=750))
    assert found.entries == ()


def test_a_decision_is_never_an_entry_of_its_own() -> None:
    found = sources(confirmed("s1", payer=BO, receiver=ALI, amount=750))
    assert [entry.event_id for entry in found.entries] == ["s1"]


def test_the_earliest_decision_decides_whether_a_settlement_is_entered() -> None:
    # The same code path ``derive_balances`` reaches, so a rendered entry list and a
    # balance can never disagree about whether a settlement counted.
    rejected_first = [
        settlement("s1", payer=BO, receiver=ALI, amount=750),
        decision("d1", settlement_id="s1", state=SettlementState.REJECTED, minute=1),
        decision("d2", settlement_id="s1", state=SettlementState.CONFIRMED, minute=2),
    ]
    assert sources(rejected_first).entries == ()

    confirmed_first = [
        settlement("s1", payer=BO, receiver=ALI, amount=750),
        decision("d1", settlement_id="s1", state=SettlementState.CONFIRMED, minute=1),
        decision("d2", settlement_id="s1", state=SettlementState.REJECTED, minute=2),
    ]
    assert rows_of(sources(confirmed_first)) == [("SETTLEMENT", "REDUCES", "s1", 750)]


def test_a_decision_naming_a_settlement_absent_from_the_input_is_ignored() -> None:
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        decision(
            "d1",
            settlement_id="never-appended",
            state=SettlementState.CONFIRMED,
            minute=1,
        ),
    ]
    assert rows_of(sources(ledger)) == [("EXPENSE", "ADDS", "e1", 1000)]


def test_a_pair_pulling_both_ways_lists_both_effects() -> None:
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        expense("e2", payer=BO, total=900, shares={ALI: 500, BO: 400}, minute=1),
    ]
    found = sources(ledger)
    assert rows_of(found) == [
        ("EXPENSE", "ADDS", "e1", 1000),
        ("EXPENSE", "REDUCES", "e2", 500),
    ]
    assert found.amount == Money(500, AUD)


def test_a_settlement_that_cancels_a_debt_leaves_the_entries_behind_it() -> None:
    # ``amount`` is zero and ``entries`` is not, which is exactly why no reader may
    # add the list up and call the total the debt.
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        *confirmed("s1", payer=BO, receiver=ALI, amount=1000, minute=1),
    ]
    found = sources(ledger)
    assert found.amount == Money(0, AUD)
    assert rows_of(found) == [
        ("EXPENSE", "ADDS", "e1", 1000),
        ("SETTLEMENT", "REDUCES", "s1", 1000),
    ]


def test_a_settlement_larger_than_the_debt_flips_the_pair_in_a_walk() -> None:
    ledger = [
        expense("e1", payer=ALI, total=3000, shares=THIRDS),
        *confirmed("s1", payer=BO, receiver=ALI, amount=2500, minute=1),
    ]
    found = sources(ledger)
    assert found.amount == Money(-1500, AUD)
    assert derive_balances(ledger, group_id=GROUP, currency=AUD).owed_between(
        BO, ALI
    ) == Money(-1500, AUD)


# --- Debt sources: property and exhaustive coverage -------------------------


def debt_pool() -> list[LedgerEvent]:
    """A fixed pool of hand-written events over four members.

    Small enough that every ledger of zero to three of them can be enumerated, and
    chosen so those subsets hold every shape that is easy to get wrong: expenses
    running both ways for one pair, a confirmed settlement that cancels a debt to
    exactly zero, a confirmed settlement larger than the debt it cleared, a pending
    settlement and a rejected one in the same log, a decision naming a settlement
    absent from the input, an expense paid by a third member that both parties share,
    a zero-cent allocation, and members with no events at all.
    """
    return [
        expense(
            "p-e1",
            payer=ALI,
            total=3000,
            shares={ALI: 1000, BO: 1000, CASS: 1000},
            minute=1,
        ),
        expense("p-e2", payer=BO, total=900, shares={ALI: 500, BO: 400}, minute=2),
        expense("p-e3", payer=CASS, total=1200, shares={ALI: 600, BO: 600}, minute=3),
        expense("p-e4", payer=DEE, total=100, shares={DEE: 100}, minute=4),
        expense("p-e5", payer=ALI, total=700, shares={ALI: 700, BO: 0}, minute=5),
        settlement("p-s1", payer=BO, receiver=ALI, amount=1000, minute=6),
        decision(
            "p-d1",
            settlement_id="p-s1",
            state=SettlementState.CONFIRMED,
            minute=7,
            decided_by=ALI,
        ),
        settlement("p-s2", payer=BO, receiver=ALI, amount=2500, minute=8),
        decision(
            "p-d2",
            settlement_id="p-s2",
            state=SettlementState.CONFIRMED,
            minute=9,
            decided_by=ALI,
        ),
        settlement("p-s3", payer=CASS, receiver=DEE, amount=400, minute=10),
        decision(
            "p-d3",
            settlement_id="p-s3",
            state=SettlementState.REJECTED,
            minute=11,
            decided_by=DEE,
        ),
        decision(
            "p-d4",
            settlement_id="p-absent",
            state=SettlementState.CONFIRMED,
            minute=12,
            decided_by=ALI,
        ),
    ]


POOL_MEMBERS = [ALI, BO, CASS, DEE]


def assert_the_pair_holds_every_invariant(
    ledger: list[LedgerEvent],
    derived: Balances,
    debtor: MemberId,
    creditor: MemberId,
) -> None:
    """Every criterion that must hold for one pair of one ledger, all exact."""
    found = debt_sources(
        ledger, debtor=debtor, creditor=creditor, group_id=GROUP, currency=AUD
    )
    owed = derived.owed_between(debtor, creditor)
    assert signed_sum(found) == owed.cents, (debtor, creditor, rows_of(found))
    assert found.amount == owed
    assert found.amount.currency == AUD

    keys = [ordering_key_of(entry) for entry in found.entries]
    assert keys == sorted(keys), (debtor, creditor)
    ids = [entry.event_id for entry in found.entries]
    assert len(set(ids)) == len(ids), (debtor, creditor)
    for entry in found.entries:
        assert entry.amount.cents > 0, entry
        assert entry.amount.currency == AUD, entry

    backward = debt_sources(
        ledger, debtor=creditor, creditor=debtor, group_id=GROUP, currency=AUD
    )
    assert backward.amount.cents == -found.amount.cents
    assert [entry.event_id for entry in backward.entries] == ids
    assert [entry.amount for entry in backward.entries] == [
        entry.amount for entry in found.entries
    ]
    assert [entry.effect for entry in backward.entries] == [
        flipped(entry.effect) for entry in found.entries
    ]


def test_the_pool_holds_every_shape_that_is_easy_to_miss() -> None:
    """Named one by one, so a later edit that drops a shape fails here."""
    pool = {event.id: event for event in debt_pool()}

    both_ways = sources([pool["p-e1"], pool["p-e2"]])
    assert {entry.effect for entry in both_ways.entries} == {
        DebtEffect.ADDS,
        DebtEffect.REDUCES,
    }

    cancelled = sources([pool["p-e1"], pool["p-s1"], pool["p-d1"]])
    assert cancelled.amount == Money(0, AUD)
    assert len(cancelled.entries) == 2

    overshot = sources([pool["p-e1"], pool["p-s2"], pool["p-d2"]])
    assert overshot.amount == Money(-1500, AUD)

    states = settlement_states([pool["p-s1"], pool["p-s3"], pool["p-d3"]])
    assert states == {
        "p-s1": SettlementState.PENDING,
        "p-s3": SettlementState.REJECTED,
    }

    orphan = sources([pool["p-e1"], pool["p-d4"]])
    assert rows_of(orphan) == [("EXPENSE", "ADDS", "p-e1", 1000)]

    third_party = sources([pool["p-e3"]])
    assert third_party.entries == ()

    zero_share = sources([pool["p-e5"]])
    assert zero_share.entries == ()

    nobody = sources([pool["p-e1"]], debtor=DEE, creditor=ALI)
    assert nobody.entries == ()


def test_every_ledger_of_up_to_three_pool_events_sums_for_every_ordered_pair() -> None:
    """Exhaustive where the domain is small enough to enumerate, as task 5 did.

    Every subset of size zero to three, and for each of them every ordered pair of the
    four members: the signed sum of the entries equals ``owed_between`` exactly, as an
    integer comparison and never an approximate one.
    """
    pool = debt_pool()
    ledgers = 0
    for size in range(4):
        for chosen in itertools.combinations(pool, size):
            ledger = list(chosen)
            derived = derive_balances(ledger, group_id=GROUP, currency=AUD)
            ledgers += 1
            for debtor, creditor in itertools.permutations(POOL_MEMBERS, 2):
                assert_the_pair_holds_every_invariant(
                    ledger, derived, debtor, creditor
                )
    assert ledgers == 1 + 12 + 66 + 220


def random_debt_ledger(rng: random.Random, size: int) -> list[LedgerEvent]:
    """A random ledger, plus the two shapes ``random_ledger`` alone never produces.

    Task 4's generator already mixes expenses running both ways, zero-cent
    allocations, third-party payers and settlements in all three states. Added here: a
    decision naming a settlement that is not in the log, and a confirmed settlement
    for exactly one outstanding pairwise debt or for more than it, so a pair cancelled
    to zero and a pair a settlement flipped are both in the corpus.
    """
    events = random_ledger(rng, size)
    if rng.choice((True, False)):
        events.append(
            decision(
                f"orphan-{size}",
                settlement_id="never-appended",
                state=SettlementState.CONFIRMED,
                minute=size + 100,
            )
        )
    outstanding = derive_balances(events, group_id=GROUP, currency=AUD).pairwise
    pairs = sorted(outstanding)
    if pairs:
        debtor, creditor = pairs[rng.randrange(len(pairs))]
        owed = outstanding[(debtor, creditor)].cents
        amount = owed if rng.choice((True, False)) else owed + rng.randint(1, 500)
        events += confirmed(
            f"clear-{size}",
            payer=debtor,
            receiver=creditor,
            amount=amount,
            minute=size + 200,
        )
    return events


def test_every_random_ledger_sums_for_every_pair_it_names_and_one_it_does_not() -> None:
    """The property the whole function exists to hold, over generated ledgers.

    Every ordered pair of member ids in the ledger plus one the ledger has never seen,
    which is a pair a roster walk can legitimately ask about and the fold answers zero
    for.
    """
    rng = random.Random(SEED + 3)
    everyone = [*ROSTER, UNSEEN]
    for _ in range(60):
        ledger = random_debt_ledger(rng, rng.randint(0, 12))
        derived = derive_balances(ledger, group_id=GROUP, currency=AUD)
        for debtor, creditor in itertools.permutations(everyone, 2):
            assert_the_pair_holds_every_invariant(ledger, derived, debtor, creditor)


def test_shuffling_a_random_ledger_never_changes_a_walk() -> None:
    """Determinism is tested, not assumed."""
    rng = random.Random(SEED + 4)
    for _ in range(25):
        ledger = random_debt_ledger(rng, rng.randint(1, 12))
        expected = sources(ledger, debtor=ROSTER[0], creditor=ROSTER[1])
        for _ in range(3):
            shuffled = list(ledger)
            rng.shuffle(shuffled)
            assert sources(shuffled, debtor=ROSTER[0], creditor=ROSTER[1]) == expected
