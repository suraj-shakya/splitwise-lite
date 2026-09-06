"""Tests for the split resolver: a total and a mode become explicit allocations.

Task 3 of plans/backlog.md, sharpened in plans/tasks/03-split-resolver.md.

Property coverage is standard library rather than hypothesis, which is the dependency
decision task 2 deferred to this task. The sum invariant lives over a small integer
domain, so totals from 1 to 400 crossed with head counts from 1 to 8 are enumerated
exhaustively, and the large domain is covered by a generator seeded from a fixed
constant so any failure reproduces from the test alone.
"""

from __future__ import annotations

import ast
import inspect
import itertools
import random
from decimal import Decimal
from pathlib import Path

import pytest

from splitwise_lite import events as events_module
from splitwise_lite import money as money_module
from splitwise_lite import split as split_module
from splitwise_lite.events import Allocation, MemberId
from splitwise_lite.money import MAX_CENTS, Currency, DomainError, Money, format_amount
from splitwise_lite.split import (
    InvalidSplit,
    split_by_weight,
    split_equally,
    split_exact,
)

ALI = MemberId("ali")
BO = MemberId("bo")
CY = MemberId("cy")
THREE = [ALI, BO, CY]

AUD = Currency("AUD")
"""The one currency every call here resolves in.

The resolver takes it because it renders its refusals through ``format_amount``, which
takes ``Money``, which cannot be built without a currency. Nothing in this file asserts
on the code itself: with ``symbol=False``, which is the default, it never reaches the
message. Every expected figure below is built by calling ``format_amount`` rather than
typed as a literal, so these tests move with the one display edge instead of pinning a
rendering it might change."""

SEED = 20260903


def members(count: int) -> list[MemberId]:
    """A canonical member list of ``count`` ids, already in ascending order."""
    return [MemberId(f"m{index}") for index in range(count)]


def cents_of(allocations: tuple[Allocation, ...]) -> dict[str, int]:
    return {allocation.member_id: allocation.cents for allocation in allocations}


# --- Shape and contract -----------------------------------------------------


def test_invalid_split_is_a_domain_error() -> None:
    assert issubclass(InvalidSplit, DomainError)


def test_the_resolver_is_re_exported_from_the_package_root() -> None:
    import splitwise_lite

    assert splitwise_lite.split_equally is split_equally
    assert splitwise_lite.split_by_weight is split_by_weight
    assert splitwise_lite.split_exact is split_exact
    assert splitwise_lite.InvalidSplit is InvalidSplit


@pytest.mark.parametrize(
    "resolve",
    [
        lambda: split_equally(1000, THREE, currency=AUD),
        lambda: split_by_weight(1000, {ALI: 1, BO: 2, CY: 1}, currency=AUD),
        lambda: split_exact(1000, {ALI: 250, BO: 500, CY: 250}, currency=AUD),
    ],
    ids=["equally", "by_weight", "exact"],
)
def test_every_mode_returns_a_tuple_of_allocations(resolve) -> None:
    result = resolve()
    assert isinstance(result, tuple)
    assert all(isinstance(allocation, Allocation) for allocation in result)


@pytest.mark.parametrize(
    "resolve",
    [
        lambda: split_equally(1000, [CY, ALI, BO], currency=AUD),
        lambda: split_by_weight(1000, {CY: 1, ALI: 1, BO: 2}, currency=AUD),
        lambda: split_exact(1000, {CY: 250, ALI: 250, BO: 500}, currency=AUD),
    ],
    ids=["equally", "by_weight", "exact"],
)
def test_every_mode_returns_allocations_in_ascending_member_id_order(resolve) -> None:
    result = resolve()
    assert [allocation.member_id for allocation in result] == [ALI, BO, CY]


@pytest.mark.parametrize(
    "resolve",
    [
        lambda: split_equally(1000, THREE, currency=AUD),
        lambda: split_by_weight(1000, {ALI: 1, BO: 2, CY: 1}, currency=AUD),
        lambda: split_exact(1000, {ALI: 250, BO: 500, CY: 250}, currency=AUD),
    ],
    ids=["equally", "by_weight", "exact"],
)
def test_every_mode_sums_exactly_to_the_total(resolve) -> None:
    assert sum(allocation.cents for allocation in resolve()) == 1000


def test_allocations_drop_straight_into_an_expense_event() -> None:
    from datetime import datetime, timezone

    from splitwise_lite.events import ExpenseEvent, ExpenseId, GroupId
    from splitwise_lite.money import Currency

    event = ExpenseEvent(
        id=ExpenseId("expense-1"),
        group_id=GroupId("group-flat"),
        currency=Currency("AUD"),
        payer_id=ALI,
        total_cents=1000,
        allocations=split_equally(1000, THREE, currency=AUD),
        description="groceries",
        created_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        created_by=ALI,
    )
    assert sum(a.cents for a in event.allocations) == event.total_cents


# --- Equal split ------------------------------------------------------------


@pytest.mark.parametrize(
    ("total", "member_ids", "expected"),
    [
        (1000, THREE, {ALI: 334, BO: 333, CY: 333}),
        (999, THREE, {ALI: 333, BO: 333, CY: 333}),
        (1000, [ALI], {ALI: 1000}),
        (2, THREE, {ALI: 1, BO: 1, CY: 0}),
        (1, THREE, {ALI: 1, BO: 0, CY: 0}),
        (1003, THREE, {ALI: 334, BO: 335, CY: 334}),
        (1004, THREE, {ALI: 334, BO: 335, CY: 335}),
        (1007, THREE, {ALI: 336, BO: 335, CY: 336}),
        (1, [ALI, BO], {ALI: 1, BO: 0}),
    ],
)
def test_split_equally_resolves_known_totals(
    total: int, member_ids: list[MemberId], expected: dict[str, int]
) -> None:
    assert cents_of(split_equally(total, member_ids, currency=AUD)) == expected


def test_split_equally_keeps_a_zero_share_in_the_result() -> None:
    result = split_equally(2, THREE, currency=AUD)
    assert len(result) == 3
    assert sorted(allocation.cents for allocation in result) == [0, 1, 1]


def test_split_equally_is_indifferent_to_the_order_it_is_given() -> None:
    expected = split_equally(1000, THREE, currency=AUD)
    for permutation in itertools.permutations(THREE):
        assert split_equally(1000, list(permutation), currency=AUD) == expected


def test_split_equally_repeats_itself_exactly() -> None:
    assert split_equally(1007, THREE, currency=AUD) == split_equally(
        1007, THREE, currency=AUD
    )


@pytest.mark.parametrize("count", range(2, 9))
def test_the_extra_cent_rotates_across_every_member(count: int) -> None:
    """No member absorbs the leftover on every expense.

    A single leftover cent lands on the member at index ``(total // n) % n``, so the
    recipient advances by one every ``n`` cents. Over ``n * n`` consecutive totals the
    walk therefore visits every member, and this fails the moment the tie-break is
    reduced to plain sorted order.
    """
    member_ids = members(count)
    recipients = set()
    for total in range(1, count * count + count + 1):
        base = total // count
        recipients |= {
            allocation.member_id
            for allocation in split_equally(total, member_ids, currency=AUD)
            if allocation.cents == base + 1
        }
    assert recipients == set(member_ids)


def test_the_single_extra_cent_is_not_always_the_same_member() -> None:
    """The "whoever sorts first" outcome the backlog and the spec both reject."""
    recipients = []
    for total in range(1000, 1031):
        base, leftover = divmod(total, 3)
        if leftover != 1:
            continue
        recipients.extend(
            allocation.member_id
            for allocation in split_equally(total, THREE, currency=AUD)
            if allocation.cents == base + 1
        )
    assert set(recipients) == {ALI, BO, CY}


# --- Weighted split ---------------------------------------------------------


@pytest.mark.parametrize(
    ("total", "weights", "expected"),
    [
        (1000, {ALI: 1, BO: 2, CY: 1}, {ALI: 250, BO: 500, CY: 250}),
        (10, {ALI: 1, BO: 2}, {ALI: 3, BO: 7}),
        (999, {ALI: 1, BO: 2}, {ALI: 333, BO: 666}),
        (1000, {ALI: 0, BO: 1}, {ALI: 0, BO: 1000}),
        (100, {ALI: 3, BO: 2}, {ALI: 60, BO: 40}),
        (1000, {ALI: 1}, {ALI: 1000}),
    ],
)
def test_split_by_weight_allocates_in_proportion(
    total: int, weights: dict[str, int], expected: dict[str, int]
) -> None:
    assert cents_of(split_by_weight(total, weights, currency=AUD)) == expected


def test_split_by_weight_gives_the_leftover_to_the_largest_remainder() -> None:
    # The exact quotas are 3.33 and 6.67, so the leftover cent goes to bo, not to the
    # member who happens to sort first.
    assert cents_of(split_by_weight(10, {ALI: 1, BO: 2}, currency=AUD)) == {
        ALI: 3,
        BO: 7,
    }


def test_double_the_weight_is_double_the_cents() -> None:
    result = cents_of(split_by_weight(3000, {ALI: 1, BO: 2}, currency=AUD))
    assert result[BO] == result[ALI] * 2


def test_split_by_weight_accepts_a_zero_weight() -> None:
    assert cents_of(split_by_weight(500, {ALI: 0, BO: 1, CY: 1}, currency=AUD)) == {
        ALI: 0,
        BO: 250,
        CY: 250,
    }


def test_split_by_weight_rejects_a_negative_weight() -> None:
    with pytest.raises(InvalidSplit):
        split_by_weight(1000, {ALI: -1, BO: 2}, currency=AUD)


def test_split_by_weight_rejects_weights_that_all_sum_to_zero() -> None:
    with pytest.raises(InvalidSplit, match="zero"):
        split_by_weight(1000, {ALI: 0, BO: 0}, currency=AUD)


@pytest.mark.parametrize("weight", [2.0, 1.5, True, Decimal("2"), "2", None])
def test_split_by_weight_rejects_a_weight_that_is_not_an_int(weight: object) -> None:
    with pytest.raises(TypeError):
        split_by_weight(1000, {ALI: 1, BO: weight}, currency=AUD)


def test_split_by_weight_rejects_an_empty_mapping() -> None:
    with pytest.raises(InvalidSplit):
        split_by_weight(1000, {}, currency=AUD)


@pytest.mark.parametrize("weights", [[1, 2], (1, 2), "ali", None, 1])
def test_split_by_weight_rejects_weights_that_are_not_a_mapping(
    weights: object,
) -> None:
    with pytest.raises(TypeError):
        split_by_weight(1000, weights, currency=AUD)


@pytest.mark.parametrize("count", range(1, 6))
def test_equal_weights_agree_with_the_equal_split(count: int) -> None:
    """One remainder engine, so the two fair-share modes cannot drift apart."""
    member_ids = members(count)
    weights = {member_id: 1 for member_id in member_ids}
    for total in range(1, 200):
        assert split_by_weight(total, weights, currency=AUD) == split_equally(
            total, member_ids, currency=AUD
        )


# --- Exact split ------------------------------------------------------------


def test_split_exact_returns_the_amounts_it_was_given() -> None:
    amounts = {ALI: 250, BO: 500, CY: 250}
    assert cents_of(split_exact(1000, amounts, currency=AUD)) == amounts


def test_split_exact_accepts_a_zero_amount() -> None:
    assert cents_of(split_exact(1000, {ALI: 0, BO: 1000}, currency=AUD)) == {
        ALI: 0,
        BO: 1000,
    }


def test_split_exact_rejects_amounts_that_fall_short() -> None:
    with pytest.raises(InvalidSplit) as raised:
        split_exact(1000, {ALI: 250, BO: 500}, currency=AUD)
    message = str(raised.value)
    assert format_amount(Money(750, AUD)) in message
    assert format_amount(Money(1000, AUD)) in message
    assert "750" not in message
    assert "1000" not in message


def test_split_exact_rejects_amounts_that_overshoot() -> None:
    with pytest.raises(InvalidSplit) as raised:
        split_exact(1000, {ALI: 600, BO: 600}, currency=AUD)
    message = str(raised.value)
    assert format_amount(Money(1200, AUD)) in message
    assert format_amount(Money(1000, AUD)) in message
    assert "1200" not in message


def test_split_exact_rejects_a_negative_amount() -> None:
    with pytest.raises(InvalidSplit):
        split_exact(1000, {ALI: -100, BO: 1100}, currency=AUD)


def test_split_exact_rejects_an_empty_mapping() -> None:
    with pytest.raises(InvalidSplit):
        split_exact(1000, {}, currency=AUD)


@pytest.mark.parametrize("amount", [12.0, 12.5, True, Decimal("12"), "12", None])
def test_split_exact_rejects_an_amount_that_is_not_an_int(amount: object) -> None:
    with pytest.raises(TypeError):
        split_exact(1000, {ALI: amount, BO: 988}, currency=AUD)


@pytest.mark.parametrize("amounts", [[250, 750], "ali", None, 1])
def test_split_exact_rejects_amounts_that_are_not_a_mapping(amounts: object) -> None:
    with pytest.raises(TypeError):
        split_exact(1000, amounts, currency=AUD)


# --- Rejections common to every mode ----------------------------------------

MODES = [
    pytest.param(lambda total: split_equally(total, THREE, currency=AUD), id="equally"),
    pytest.param(
        lambda total: split_by_weight(total, {ALI: 1, BO: 2}, currency=AUD),
        id="by_weight",
    ),
    pytest.param(
        lambda total: split_exact(total, {ALI: 1, BO: 2}, currency=AUD), id="exact"
    ),
]


@pytest.mark.parametrize("resolve", MODES)
@pytest.mark.parametrize("total", [0, -1, -1000])
def test_every_mode_rejects_a_total_that_is_not_strictly_positive(
    resolve, total: int
) -> None:
    with pytest.raises(InvalidSplit):
        resolve(total)


@pytest.mark.parametrize("resolve", MODES)
def test_every_mode_rejects_a_total_above_the_storable_maximum(resolve) -> None:
    with pytest.raises(InvalidSplit):
        resolve(MAX_CENTS + 1)


def test_a_total_at_the_storable_maximum_still_resolves() -> None:
    assert cents_of(split_equally(MAX_CENTS, [ALI], currency=AUD)) == {ALI: MAX_CENTS}


@pytest.mark.parametrize("resolve", MODES)
@pytest.mark.parametrize("total", [1000.0, 12.5, True, Decimal("1000"), "1000", None])
def test_every_mode_rejects_a_total_that_is_not_an_int(resolve, total: object) -> None:
    with pytest.raises(TypeError):
        resolve(total)


def test_split_equally_rejects_an_empty_member_list() -> None:
    with pytest.raises(InvalidSplit):
        split_equally(1000, [], currency=AUD)


def test_split_equally_rejects_a_repeated_member() -> None:
    with pytest.raises(InvalidSplit, match="more than once"):
        split_equally(1000, [ALI, BO, ALI], currency=AUD)


def test_split_equally_rejects_an_empty_member_id() -> None:
    with pytest.raises(InvalidSplit):
        split_equally(1000, [ALI, ""], currency=AUD)


@pytest.mark.parametrize("member_id", [1, None, b"ali", 2.0])
def test_split_equally_rejects_a_member_id_that_is_not_a_str(
    member_id: object,
) -> None:
    with pytest.raises(TypeError):
        split_equally(1000, [ALI, member_id], currency=AUD)


@pytest.mark.parametrize("member_ids", ["ali", b"ali", {ALI: 1}, 1, None])
def test_split_equally_rejects_member_ids_that_are_not_a_list_of_ids(
    member_ids: object,
) -> None:
    with pytest.raises(TypeError):
        split_equally(1000, member_ids, currency=AUD)


@pytest.mark.parametrize(
    "resolve",
    [
        lambda key: split_by_weight(1000, {key: 1}, currency=AUD),
        lambda key: split_exact(1000, {key: 1000}, currency=AUD),
    ],
    ids=["by_weight", "exact"],
)
def test_the_mapping_modes_reject_an_empty_member_id(resolve) -> None:
    with pytest.raises(InvalidSplit):
        resolve("")


@pytest.mark.parametrize(
    "resolve",
    [
        lambda key: split_by_weight(1000, {key: 1}, currency=AUD),
        lambda key: split_exact(1000, {key: 1000}, currency=AUD),
    ],
    ids=["by_weight", "exact"],
)
@pytest.mark.parametrize("key", [1, None, b"ali"])
def test_the_mapping_modes_reject_a_member_id_that_is_not_a_str(
    resolve, key: object
) -> None:
    with pytest.raises(TypeError):
        resolve(key)


# --- A refusal names the money, not the cents -------------------------------

WITHOUT_CURRENCY = [
    pytest.param(lambda: split_equally(1000, THREE), id="equally"),
    pytest.param(lambda: split_by_weight(1000, {ALI: 1, BO: 2}), id="by_weight"),
    pytest.param(lambda: split_exact(1000, {ALI: 400, BO: 600}), id="exact"),
]

WITH_A_CURRENCY = [
    pytest.param(
        lambda total, currency: split_equally(total, THREE, currency=currency),
        id="equally",
    ),
    pytest.param(
        lambda total, currency: split_by_weight(
            total, {ALI: 1, BO: 2}, currency=currency
        ),
        id="by_weight",
    ),
    pytest.param(
        lambda total, currency: split_exact(total, {ALI: 1, BO: 2}, currency=currency),
        id="exact",
    ),
]


@pytest.mark.parametrize("resolve", WITHOUT_CURRENCY)
def test_every_mode_refuses_to_resolve_without_a_currency(resolve) -> None:
    """``currency`` is keyword-only with no default, so every caller has to state it.

    A defaulted currency in the money path is a bug waiting for a second currency, and
    a positional third argument would silently swallow the mapping a caller meant to
    pass. These calls are the pre-task spelling of every one of them.
    """
    with pytest.raises(TypeError):
        resolve()


@pytest.mark.parametrize("resolve", WITH_A_CURRENCY)
@pytest.mark.parametrize("currency", ["AUD", None, 1])
def test_every_mode_rejects_a_currency_that_is_not_a_currency(
    resolve, currency: object
) -> None:
    with pytest.raises(TypeError):
        resolve(1000, currency)


@pytest.mark.parametrize("resolve", WITH_A_CURRENCY)
@pytest.mark.parametrize("currency", ["AUD", None, 1])
def test_a_bad_currency_is_a_type_error_even_when_the_total_is_refusable(
    resolve, currency: object
) -> None:
    """The currency is checked before anything else, so a programming error never
    arrives at the screen dressed as rejected user input.

    The message is pinned, and anchored, because without both this test cannot fail
    for the reason its name gives. Delete the resolver's own guard and a refusable
    total still reaches ``_formatted``, where ``Money`` rejects the same currency, so
    a bare ``pytest.raises(TypeError)`` goes green on somebody else's refusal and the
    ordering this test exists for is asserted nowhere. ``match`` is an ``re.search``,
    and ``Money`` says ``Money currency must be a Currency, ...``, which *contains*
    the resolver's sentence: the leading ``^`` is the whole of what tells the two
    apart. This is also the one test that pins the guard's wording in every mode.
    """
    with pytest.raises(TypeError, match=r"^currency must be a Currency"):
        resolve(0, currency)


@pytest.mark.parametrize("resolve", MODES)
def test_a_zero_total_is_refused_in_the_money_and_not_in_cents(resolve) -> None:
    with pytest.raises(InvalidSplit) as raised:
        resolve(0)
    message = str(raised.value)
    assert message == (
        f"the amount must be more than zero, but it is {format_amount(Money(0, AUD))}"
    )
    assert "total_cents" not in message
    assert "cents" not in message


@pytest.mark.parametrize("resolve", MODES)
def test_a_negative_total_is_refused_with_a_leading_minus(resolve) -> None:
    """Only a domain caller reaches this: ``parse_amount`` rejects a signed string."""
    with pytest.raises(InvalidSplit) as raised:
        resolve(-500)
    figure = format_amount(Money(-500, AUD))
    assert figure.startswith("-")
    assert str(raised.value) == (
        f"the amount must be more than zero, but it is {figure}"
    )


@pytest.mark.parametrize("resolve", MODES)
def test_a_total_above_the_maximum_is_refused_in_the_money(resolve) -> None:
    with pytest.raises(InvalidSplit) as raised:
        resolve(MAX_CENTS + 1)
    figure = format_amount(Money(MAX_CENTS + 1, AUD))
    assert "," in figure
    assert str(raised.value) == f"the amount is too large to record: {figure}"
    assert str(MAX_CENTS + 1) not in str(raised.value)


def test_a_large_exact_mismatch_carries_the_formatters_comma_groups() -> None:
    with pytest.raises(InvalidSplit) as raised:
        split_exact(123400, {ALI: 123450}, currency=AUD)
    message = str(raised.value)
    allocated = format_amount(Money(123450, AUD))
    total = format_amount(Money(123400, AUD))
    assert "," in allocated
    assert "," in total
    assert message == f"the shares add up to {allocated}, but the total is {total}"
    assert "123450" not in message
    assert "123400" not in message


# --- No float, no clock, no per-process randomness --------------------------


def _module_tree(module) -> ast.Module:
    return ast.parse(Path(inspect.getfile(module)).read_text(encoding="utf-8"))


def _names(tree: ast.Module) -> set[str]:
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return names | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }


@pytest.mark.parametrize("forbidden", ["float", "round"])
def test_the_split_module_never_names_float_or_round(forbidden: str) -> None:
    assert forbidden not in _names(_module_tree(split_module))


def test_the_split_module_never_uses_true_division() -> None:
    tree = _module_tree(split_module)
    divisions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(node.op, ast.Div)
    ]
    assert divisions == []


@pytest.mark.parametrize("forbidden", ["hash", "random", "time", "uuid", "datetime"])
def test_the_split_is_a_pure_function_of_its_inputs(forbidden: str) -> None:
    """No clock, no randomness, and no salted ``hash`` deciding who pays the cent."""
    assert forbidden not in _names(_module_tree(split_module))


# --- Dependency direction ---------------------------------------------------


def _imported(tree: ast.Module) -> set[str]:
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    return imported


def test_split_imports_only_money_and_events_from_the_package() -> None:
    imported = _imported(_module_tree(split_module))
    assert {name for name in imported if name in {"money", "events"}} == {
        "money",
        "events",
    }
    assert not any("splitwise_lite" in name for name in imported)


@pytest.mark.parametrize(
    "module", [money_module, events_module], ids=["money", "events"]
)
def test_the_task_2_modules_never_learn_about_the_resolver(module) -> None:
    assert "split" not in _imported(_module_tree(module))


# --- Property: allocations always sum to the total --------------------------


@pytest.mark.parametrize("count", range(1, 9))
def test_equal_split_holds_for_every_small_total(count: int) -> None:
    """Exhaustive over the small domain: totals 1 to 400 against 1 to 8 people."""
    member_ids = members(count)
    for total in range(1, 401):
        result = split_equally(total, member_ids, currency=AUD)
        allocated = [allocation.cents for allocation in result]
        base, leftover = divmod(total, count)
        assert sum(allocated) == total
        assert len(result) == count
        assert min(allocated) >= 0
        assert max(allocated) - min(allocated) <= 1
        assert allocated.count(base + 1) == leftover
        assert allocated.count(base) == count - leftover


def test_equal_split_holds_across_random_large_totals() -> None:
    generator = random.Random(SEED)
    for _ in range(2000):
        count = generator.randint(1, 12)
        total = generator.randint(1, 10_000_000)
        member_ids = members(count)
        result = split_equally(total, member_ids, currency=AUD)
        allocated = [allocation.cents for allocation in result]
        assert sum(allocated) == total
        assert len(result) == count
        assert max(allocated) - min(allocated) <= 1


def test_weighted_split_holds_across_random_weights() -> None:
    generator = random.Random(SEED)
    for _ in range(2000):
        count = generator.randint(1, 10)
        member_ids = members(count)
        weights = {
            member_id: generator.choice([0, 1, 1, 2, 3, 7, 1000])
            for member_id in member_ids
        }
        if sum(weights.values()) == 0:
            weights[member_ids[0]] = 1
        total = generator.randint(1, 10_000_000)
        result = split_by_weight(total, weights, currency=AUD)
        assert sum(allocation.cents for allocation in result) == total
        assert len(result) == count
        # Every share sits within one cent of its exact quota, asserted in integers:
        # abs(cents * weight_total - total * weight) < weight_total.
        weight_total = sum(weights.values())
        for allocation in result:
            quota_error = abs(
                allocation.cents * weight_total
                - total * weights[allocation.member_id]
            )
            assert quota_error < weight_total


def test_exact_split_holds_across_random_partitions() -> None:
    generator = random.Random(SEED)
    for _ in range(2000):
        count = generator.randint(1, 10)
        member_ids = members(count)
        amounts = {member_id: generator.randint(0, 100_000) for member_id in member_ids}
        total = sum(amounts.values())
        if total == 0:
            continue
        result = split_exact(total, amounts, currency=AUD)
        assert sum(allocation.cents for allocation in result) == total
        assert cents_of(result) == amounts
