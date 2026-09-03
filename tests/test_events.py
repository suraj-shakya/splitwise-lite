"""Tests for the ledger event types: allocations, expenses and settlements.

Task 2 of plans/backlog.md, sharpened in
plans/tasks/02-domain-types-and-money-primitives.md.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import uuid
from pathlib import Path

import pytest

from splitwise_lite import money as money_module
from splitwise_lite.events import (
    Allocation,
    ExpenseId,
    GroupId,
    InvalidAllocation,
    MemberId,
    SettlementId,
    new_id,
)
from splitwise_lite.money import DomainError

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
