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

from splitwise_lite import money as money_module
from splitwise_lite.events import (
    Allocation,
    ExpenseEvent,
    ExpenseId,
    GroupId,
    InvalidAllocation,
    InvalidEvent,
    MemberId,
    SettlementId,
    new_id,
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
