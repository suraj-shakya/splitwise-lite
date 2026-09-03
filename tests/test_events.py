"""Tests for the ledger event types: allocations, expenses and settlements.

Task 2 of plans/backlog.md, sharpened in
plans/tasks/02-domain-types-and-money-primitives.md.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from splitwise_lite import events as events_module
from splitwise_lite import money as money_module
from splitwise_lite.events import (
    Allocation,
    ExpenseEvent,
    ExpenseId,
    GroupId,
    InvalidAllocation,
    InvalidEvent,
    MemberId,
    SettlementDecisionEvent,
    SettlementEvent,
    SettlementId,
    SettlementState,
    new_id,
    ordering_key,
)
from splitwise_lite.money import Currency, DomainError

ALICE = MemberId("member-alice")


# --- Identity ---------------------------------------------------------------


def test_the_four_id_types_are_distinct_declared_types() -> None:
    id_types = [MemberId, GroupId, ExpenseId, SettlementId]
    assert len({id(t) for t in id_types}) == 4
    assert {t.__name__ for t in id_types} == {
        "MemberId",
        "GroupId",
        "ExpenseId",
        "SettlementId",
    }


def test_every_id_type_is_declared_over_str() -> None:
    for id_type in (MemberId, GroupId, ExpenseId, SettlementId):
        assert id_type.__supertype__ is str
        assert id_type("x") == "x"


def test_new_id_mints_a_uuid4_string() -> None:
    minted = new_id()
    assert isinstance(minted, str)
    assert uuid.UUID(minted).version == 4


def test_new_id_is_not_derived_from_anything_and_does_not_repeat() -> None:
    assert len({new_id() for _ in range(100)}) == 100


# --- Allocation -------------------------------------------------------------


def test_invalid_allocation_is_a_domain_error() -> None:
    assert issubclass(InvalidAllocation, DomainError)


def test_allocation_holds_a_member_and_cents() -> None:
    allocation = Allocation(ALICE, 1250)
    assert allocation.member_id == ALICE
    assert allocation.cents == 1250


def test_allocation_carries_no_currency() -> None:
    field_names = {f.name for f in dataclasses.fields(Allocation)}
    assert field_names == {"member_id", "cents"}


def test_allocation_is_frozen_and_hashable() -> None:
    allocation = Allocation(ALICE, 1250)
    with pytest.raises(dataclasses.FrozenInstanceError):
        allocation.cents = 1
    assert len({Allocation(ALICE, 1250), Allocation(ALICE, 1250)}) == 1


def test_allocation_of_zero_cents_is_legal() -> None:
    assert Allocation(ALICE, 0).cents == 0


@pytest.mark.parametrize("cents", [-1, -1250])
def test_allocation_rejects_negative_cents(cents: int) -> None:
    with pytest.raises(InvalidAllocation):
        Allocation(ALICE, cents)


@pytest.mark.parametrize("cents", [12.5, 1250.0, True, "1250", None])
def test_allocation_rejects_cents_that_are_not_an_int(cents: object) -> None:
    with pytest.raises(TypeError):
        Allocation(ALICE, cents)


def test_allocation_rejects_an_empty_member_id() -> None:
    with pytest.raises(InvalidAllocation):
        Allocation(MemberId(""), 1250)


@pytest.mark.parametrize("member_id", [None, 1, b"alice"])
def test_allocation_rejects_a_member_id_that_is_not_a_str(member_id: object) -> None:
    with pytest.raises(TypeError):
        Allocation(member_id, 1250)


# --- Dependency direction ---------------------------------------------------


def test_money_imports_nothing_from_the_package() -> None:
    tree = ast.parse(Path(inspect.getfile(money_module)).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            if node.level:
                imported.add("relative import")
    assert not any("splitwise_lite" in name for name in imported)
    assert "relative import" not in imported


# --- ExpenseEvent -----------------------------------------------------------

BOB = MemberId("member-bob")
CARA = MemberId("member-cara")
GROUP = GroupId("group-flat")
AUD = Currency("AUD")
WHEN = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def make_expense(**overrides) -> ExpenseEvent:
    fields = {
        "id": ExpenseId("expense-1"),
        "group_id": GROUP,
        "currency": AUD,
        "payer_id": ALICE,
        "total_cents": 1200,
        "allocations": (Allocation(ALICE, 600), Allocation(BOB, 600)),
        "description": "milk",
        "created_at": WHEN,
        "created_by": ALICE,
    }
    fields.update(overrides)
    return ExpenseEvent(**fields)


def test_invalid_event_is_a_domain_error() -> None:
    assert issubclass(InvalidEvent, DomainError)


def test_expense_event_holds_the_documented_fields() -> None:
    assert [f.name for f in dataclasses.fields(ExpenseEvent)] == [
        "id",
        "group_id",
        "currency",
        "payer_id",
        "total_cents",
        "allocations",
        "description",
        "created_at",
        "created_by",
    ]


def test_expense_event_is_frozen_slotted_and_hashable() -> None:
    expense = make_expense()
    with pytest.raises(dataclasses.FrozenInstanceError):
        expense.total_cents = 1
    assert not hasattr(expense, "__dict__")
    assert len({make_expense(), make_expense()}) == 1


def test_expense_event_exposes_no_mutating_method() -> None:
    public = {name for name in vars(ExpenseEvent) if not name.startswith("_")}
    assert public == {f.name for f in dataclasses.fields(ExpenseEvent)}


def test_allocations_must_be_a_tuple_not_a_list() -> None:
    with pytest.raises(TypeError):
        make_expense(allocations=[Allocation(ALICE, 600), Allocation(BOB, 600)])


def test_allocations_must_contain_allocations() -> None:
    with pytest.raises(TypeError):
        make_expense(allocations=((ALICE, 600), (BOB, 600)))


def test_allocations_must_sum_exactly_to_the_total() -> None:
    with pytest.raises(InvalidEvent):
        make_expense(allocations=(Allocation(ALICE, 600), Allocation(BOB, 599)))
    with pytest.raises(InvalidEvent):
        make_expense(allocations=(Allocation(ALICE, 600), Allocation(BOB, 601)))


def test_an_allocation_of_zero_still_counts_towards_the_sum() -> None:
    expense = make_expense(
        total_cents=2,
        allocations=(Allocation(ALICE, 1), Allocation(BOB, 1), Allocation(CARA, 0)),
    )
    assert sum(a.cents for a in expense.allocations) == expense.total_cents


@pytest.mark.parametrize("total_cents", [0, -1, -1200])
def test_total_cents_must_be_strictly_positive(total_cents: int) -> None:
    with pytest.raises(InvalidEvent):
        make_expense(total_cents=total_cents, allocations=(Allocation(ALICE, 0),))


@pytest.mark.parametrize("total_cents", [12.0, "1200", True, None])
def test_total_cents_must_be_an_int(total_cents: object) -> None:
    with pytest.raises(TypeError):
        make_expense(total_cents=total_cents)


def test_empty_allocations_are_rejected() -> None:
    with pytest.raises(InvalidEvent):
        make_expense(total_cents=1200, allocations=())


def test_a_member_appearing_twice_in_allocations_is_rejected() -> None:
    with pytest.raises(InvalidEvent):
        make_expense(
            total_cents=1200,
            allocations=(Allocation(ALICE, 600), Allocation(ALICE, 600)),
        )


def test_the_payer_need_not_be_a_participant() -> None:
    expense = make_expense(
        payer_id=CARA,
        allocations=(Allocation(ALICE, 600), Allocation(BOB, 600)),
    )
    assert expense.payer_id not in {a.member_id for a in expense.allocations}


def test_an_expense_where_the_payer_is_the_only_participant_is_legal() -> None:
    expense = make_expense(
        payer_id=ALICE, total_cents=1200, allocations=(Allocation(ALICE, 1200),)
    )
    assert expense.allocations == (Allocation(ALICE, 1200),)


def test_created_at_must_be_timezone_aware() -> None:
    with pytest.raises(InvalidEvent):
        make_expense(created_at=datetime(2026, 9, 3, 12, 0))


@pytest.mark.parametrize("created_at", ["2026-09-03", 1757000000, None])
def test_created_at_must_be_a_datetime(created_at: object) -> None:
    with pytest.raises(TypeError):
        make_expense(created_at=created_at)


def test_created_at_is_stored_in_utc() -> None:
    sydney = timezone(timedelta(hours=10))
    expense = make_expense(created_at=datetime(2026, 9, 3, 22, 0, tzinfo=sydney))
    assert expense.created_at.utcoffset() == timedelta(0)
    assert expense.created_at == WHEN


def test_description_is_stripped_and_may_be_empty() -> None:
    assert make_expense(description="  milk run  ").description == "milk run"
    assert make_expense(description="").description == ""
    assert make_expense(description="   ").description == ""


def test_description_has_no_length_cap_here() -> None:
    long_description = "x" * 5000
    assert make_expense(description=long_description).description == long_description


@pytest.mark.parametrize("description", [None, 12, b"milk"])
def test_description_must_be_a_str(description: object) -> None:
    with pytest.raises(TypeError):
        make_expense(description=description)


@pytest.mark.parametrize("field", ["id", "group_id", "payer_id", "created_by"])
def test_every_id_field_must_be_a_non_empty_str(field: str) -> None:
    with pytest.raises(InvalidEvent):
        make_expense(**{field: ""})
    with pytest.raises(TypeError):
        make_expense(**{field: None})


@pytest.mark.parametrize("currency", ["AUD", None, 1])
def test_expense_currency_must_be_a_currency(currency: object) -> None:
    with pytest.raises(TypeError):
        make_expense(currency=currency)


# --- Settlement events ------------------------------------------------------


def make_settlement(**overrides) -> SettlementEvent:
    fields = {
        "id": SettlementId("settlement-1"),
        "group_id": GROUP,
        "currency": AUD,
        "from_member_id": BOB,
        "to_member_id": ALICE,
        "amount_cents": 600,
        "created_at": WHEN,
        "created_by": BOB,
    }
    fields.update(overrides)
    return SettlementEvent(**fields)


def make_decision(**overrides) -> SettlementDecisionEvent:
    fields = {
        "id": new_id(),
        "settlement_id": SettlementId("settlement-1"),
        "decision": SettlementState.CONFIRMED,
        "decided_by": ALICE,
        "created_at": WHEN,
    }
    fields.update(overrides)
    return SettlementDecisionEvent(**fields)


def test_settlement_state_has_exactly_three_members() -> None:
    assert [state.name for state in SettlementState] == [
        "PENDING",
        "CONFIRMED",
        "REJECTED",
    ]


def test_rejection_is_a_state_not_a_deletion() -> None:
    assert SettlementState.REJECTED in set(SettlementState)


def test_settlement_event_holds_the_documented_fields() -> None:
    assert [f.name for f in dataclasses.fields(SettlementEvent)] == [
        "id",
        "group_id",
        "currency",
        "from_member_id",
        "to_member_id",
        "amount_cents",
        "created_at",
        "created_by",
    ]


def test_settlement_event_is_born_pending_and_carries_no_state_field() -> None:
    settlement = make_settlement()
    assert not hasattr(settlement, "state")
    assert "state" not in {f.name for f in dataclasses.fields(SettlementEvent)}


def test_settlement_event_is_frozen_slotted_and_hashable() -> None:
    settlement = make_settlement()
    with pytest.raises(dataclasses.FrozenInstanceError):
        settlement.amount_cents = 1
    assert not hasattr(settlement, "__dict__")
    assert len({make_settlement(), make_settlement()}) == 1


@pytest.mark.parametrize("amount_cents", [0, -1, -600])
def test_settlement_amount_must_be_strictly_positive(amount_cents: int) -> None:
    with pytest.raises(InvalidEvent):
        make_settlement(amount_cents=amount_cents)


@pytest.mark.parametrize("amount_cents", [6.0, "600", True, None])
def test_settlement_amount_must_be_an_int(amount_cents: object) -> None:
    with pytest.raises(TypeError):
        make_settlement(amount_cents=amount_cents)


def test_a_self_settlement_is_rejected() -> None:
    with pytest.raises(InvalidEvent):
        make_settlement(from_member_id=ALICE, to_member_id=ALICE)


@pytest.mark.parametrize(
    "field", ["id", "group_id", "from_member_id", "to_member_id", "created_by"]
)
def test_settlement_id_fields_must_be_non_empty_strs(field: str) -> None:
    with pytest.raises(InvalidEvent):
        make_settlement(**{field: ""})
    with pytest.raises(TypeError):
        make_settlement(**{field: None})


@pytest.mark.parametrize("currency", ["AUD", None, 1])
def test_settlement_currency_must_be_a_currency(currency: object) -> None:
    with pytest.raises(TypeError):
        make_settlement(currency=currency)


def test_settlement_created_at_must_be_aware_and_is_stored_in_utc() -> None:
    with pytest.raises(InvalidEvent):
        make_settlement(created_at=datetime(2026, 9, 3, 12, 0))
    sydney = timezone(timedelta(hours=10))
    settlement = make_settlement(created_at=datetime(2026, 9, 3, 22, 0, tzinfo=sydney))
    assert settlement.created_at.utcoffset() == timedelta(0)


# --- Settlement decision events ---------------------------------------------


def test_decision_event_holds_the_documented_fields() -> None:
    assert [f.name for f in dataclasses.fields(SettlementDecisionEvent)] == [
        "id",
        "settlement_id",
        "decision",
        "decided_by",
        "created_at",
    ]


def test_a_decision_never_restates_the_amount() -> None:
    names = " ".join(f.name for f in dataclasses.fields(SettlementDecisionEvent))
    assert "amount" not in names
    assert "cents" not in names


def test_a_decision_may_confirm_or_reject() -> None:
    confirmed = make_decision(decision=SettlementState.CONFIRMED)
    rejected = make_decision(decision=SettlementState.REJECTED)
    assert confirmed.decision is SettlementState.CONFIRMED
    assert rejected.decision is SettlementState.REJECTED


def test_a_decision_of_pending_is_not_a_decision() -> None:
    with pytest.raises(InvalidEvent):
        make_decision(decision=SettlementState.PENDING)


@pytest.mark.parametrize("decision", ["CONFIRMED", "confirmed", 1, None])
def test_a_decision_must_be_a_settlement_state(decision: object) -> None:
    with pytest.raises(TypeError):
        make_decision(decision=decision)


def test_decision_event_is_frozen_slotted_and_hashable() -> None:
    decision = make_decision(id="decision-1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.decided_by = BOB
    assert not hasattr(decision, "__dict__")
    assert len({make_decision(id="decision-1"), make_decision(id="decision-1")}) == 1


@pytest.mark.parametrize("field", ["id", "settlement_id", "decided_by"])
def test_decision_id_fields_must_be_non_empty_strs(field: str) -> None:
    with pytest.raises(InvalidEvent):
        make_decision(**{field: ""})
    with pytest.raises(TypeError):
        make_decision(**{field: None})


def test_decision_created_at_must_be_aware_and_is_stored_in_utc() -> None:
    with pytest.raises(InvalidEvent):
        make_decision(created_at=datetime(2026, 9, 3, 12, 0))
    sydney = timezone(timedelta(hours=10))
    decision = make_decision(created_at=datetime(2026, 9, 3, 22, 0, tzinfo=sydney))
    assert decision.created_at.utcoffset() == timedelta(0)


# --- Ordering and the documented conflict rule ------------------------------


def test_ordering_key_is_created_at_then_id() -> None:
    expense = make_expense()
    assert ordering_key(expense) == (expense.created_at, expense.id)
    settlement = make_settlement()
    assert ordering_key(settlement) == (settlement.created_at, settlement.id)
    decision = make_decision(id="decision-1")
    assert ordering_key(decision) == (decision.created_at, decision.id)


def test_ordering_key_breaks_a_timestamp_tie_by_id() -> None:
    later = make_expense(id=ExpenseId("expense-b"))
    earlier = make_expense(id=ExpenseId("expense-a"))
    assert sorted([later, earlier], key=ordering_key) == [earlier, later]


def test_ordering_key_sorts_by_time_first() -> None:
    first = make_expense(id=ExpenseId("expense-z"), created_at=WHEN)
    second = make_expense(
        id=ExpenseId("expense-a"), created_at=WHEN + timedelta(seconds=1)
    )
    assert sorted([second, first], key=ordering_key) == [first, second]


def test_the_module_documents_the_conflicting_decision_rule() -> None:
    doc = (events_module.__doc__ or "").lower()
    assert "earliest decision" in doc
    assert "later decisions" in doc


def test_the_module_documents_which_settlements_move_a_balance() -> None:
    doc = (events_module.__doc__ or "").lower()
    assert "only confirmed settlements" in doc
    assert "pending settlement moves no balance" in doc
