"""Tests for the money primitives: currency, integer-cent money.

Task 2 of plans/backlog.md, sharpened in
plans/tasks/02-domain-types-and-money-primitives.md.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import operator
import typing
from decimal import Decimal
from pathlib import Path

import pytest

from splitwise_lite import money as money_module
from splitwise_lite.money import (
    MINOR_UNITS,
    Currency,
    CurrencyMismatch,
    DomainError,
    InvalidCurrency,
    Money,
)

AUD = Currency("AUD")
USD = Currency("USD")


# --- Currency ---------------------------------------------------------------


def test_currency_holds_an_uppercase_alpha3_code() -> None:
    assert AUD.code == "AUD"


def test_currency_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        AUD.code = "USD"


def test_currency_is_hashable_and_compares_by_value() -> None:
    assert Currency("AUD") == AUD
    assert Currency("AUD") != USD
    assert len({Currency("AUD"), AUD, USD}) == 2


def test_currency_rejects_lowercase_rather_than_coercing() -> None:
    with pytest.raises(InvalidCurrency) as excinfo:
        Currency("aud")
    assert "aud" in str(excinfo.value)


@pytest.mark.parametrize("code", ["", "AU", "AUDD", "AU1", "A$D", "AU ", " AUD", "AuD"])
def test_currency_rejects_codes_that_are_not_three_uppercase_letters(code: str) -> None:
    with pytest.raises(InvalidCurrency):
        Currency(code)


@pytest.mark.parametrize("code", [123, None, b"AUD", ["A", "U", "D"]])
def test_currency_rejects_non_string_codes(code: object) -> None:
    with pytest.raises(TypeError):
        Currency(code)


def test_invalid_currency_is_a_domain_error() -> None:
    assert issubclass(InvalidCurrency, DomainError)


def test_minor_units_is_two_for_every_currency_in_v1() -> None:
    assert MINOR_UNITS == 2


# --- Money construction -----------------------------------------------------


def test_money_holds_cents_and_a_currency() -> None:
    amount = Money(1250, AUD)
    assert amount.cents == 1250
    assert amount.currency == AUD


def test_money_is_frozen() -> None:
    amount = Money(1250, AUD)
    with pytest.raises(dataclasses.FrozenInstanceError):
        amount.cents = 1


def test_money_is_hashable_and_compares_by_value() -> None:
    assert Money(1250, AUD) == Money(1250, AUD)
    assert len({Money(1250, AUD), Money(1250, AUD), Money(1251, AUD)}) == 2


@pytest.mark.parametrize("cents", [-1250, -1, 0, 1, 2**63 - 1])
def test_money_may_be_negative_or_zero(cents: int) -> None:
    assert Money(cents, AUD).cents == cents


@pytest.mark.parametrize("cents", [12.5, 1250.0, 0.0, -1.0])
def test_money_rejects_float_cents(cents: object) -> None:
    with pytest.raises(TypeError):
        Money(cents, AUD)


@pytest.mark.parametrize("cents", [True, False])
def test_money_rejects_bool_cents_even_though_bool_is_an_int(cents: object) -> None:
    with pytest.raises(TypeError):
        Money(cents, AUD)


@pytest.mark.parametrize("cents", [Decimal("12.50"), "1250", None])
def test_money_rejects_other_non_int_cents(cents: object) -> None:
    with pytest.raises(TypeError):
        Money(cents, AUD)


@pytest.mark.parametrize("currency", ["AUD", None, 1])
def test_money_rejects_a_currency_that_is_not_a_currency(currency: object) -> None:
    with pytest.raises(TypeError):
        Money(1250, currency)


# --- Money arithmetic -------------------------------------------------------


def test_addition_of_same_currency_returns_money() -> None:
    assert Money(1250, AUD) + Money(250, AUD) == Money(1500, AUD)


def test_subtraction_of_same_currency_returns_money_and_may_go_negative() -> None:
    assert Money(250, AUD) - Money(1250, AUD) == Money(-1000, AUD)


def test_currency_mismatch_is_a_domain_error() -> None:
    assert issubclass(CurrencyMismatch, DomainError)


def test_addition_across_currencies_raises_currency_mismatch() -> None:
    with pytest.raises(CurrencyMismatch):
        Money(1250, AUD) + Money(250, USD)


def test_subtraction_across_currencies_raises_currency_mismatch() -> None:
    with pytest.raises(CurrencyMismatch):
        Money(1250, AUD) - Money(250, USD)


@pytest.mark.parametrize(
    "compare", [operator.lt, operator.le, operator.gt, operator.ge]
)
def test_ordering_across_currencies_raises_currency_mismatch(compare) -> None:
    with pytest.raises(CurrencyMismatch):
        compare(Money(1250, AUD), Money(250, USD))


def test_ordering_within_one_currency_works() -> None:
    assert Money(250, AUD) < Money(1250, AUD)
    assert Money(250, AUD) <= Money(250, AUD)
    assert Money(1250, AUD) > Money(-250, AUD)
    assert Money(1250, AUD) >= Money(1250, AUD)


def test_equality_across_currencies_is_false_rather_than_an_error() -> None:
    assert Money(1250, AUD) != Money(1250, USD)


def test_arithmetic_with_a_non_money_operand_raises_type_error() -> None:
    with pytest.raises(TypeError):
        Money(1250, AUD) + 250
    with pytest.raises(TypeError):
        Money(1250, AUD) - 250


def test_multiplication_by_an_int_is_supported_both_ways() -> None:
    assert Money(1250, AUD) * 3 == Money(3750, AUD)
    assert 3 * Money(1250, AUD) == Money(3750, AUD)
    assert Money(1250, AUD) * 0 == Money(0, AUD)
    assert Money(1250, AUD) * -1 == Money(-1250, AUD)


@pytest.mark.parametrize("factor", [1.5, 2.0, True, Decimal("2"), "2"])
def test_multiplication_by_a_non_int_raises_type_error(factor: object) -> None:
    with pytest.raises(TypeError):
        Money(1250, AUD) * factor


def test_money_by_money_multiplication_raises_type_error() -> None:
    with pytest.raises(TypeError):
        Money(1250, AUD) * Money(2, AUD)


@pytest.mark.parametrize("name", ["__truediv__", "__floordiv__", "__mod__"])
def test_division_is_not_exposed_at_all(name: str) -> None:
    assert not hasattr(Money, name)


def test_dividing_money_raises_type_error() -> None:
    with pytest.raises(TypeError):
        Money(1250, AUD) / 2
    with pytest.raises(TypeError):
        Money(1250, AUD) // 2


# --- No float anywhere in the money path ------------------------------------


def _module_tree(module) -> ast.Module:
    return ast.parse(Path(inspect.getfile(module)).read_text(encoding="utf-8"))


def test_money_module_never_names_float_or_round() -> None:
    tree = _module_tree(money_module)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "float" not in names
    assert "round" not in names


def test_money_module_never_uses_true_division() -> None:
    tree = _module_tree(money_module)
    divisions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(node.op, ast.Div)
    ]
    assert divisions == []


def test_decimal_never_appears_in_the_public_money_api() -> None:
    for name in money_module.__all__:
        obj = getattr(money_module, name)
        if not (dataclasses.is_dataclass(obj) or inspect.isfunction(obj)):
            continue
        hints = typing.get_type_hints(obj)
        assert Decimal not in hints.values(), name
