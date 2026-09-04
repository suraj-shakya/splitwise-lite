# Task 2: Domain types and money primitives

**Depends on:** 1 (complete)
**Consumed by:** 3 (split resolver), 4 (balance derivation), 6 (persistence)

Sharpened from `plans/backlog.md` task 2. The backlog entry stays as written; this file
is the implementable version.

## Goal

The repo has one shared vocabulary for money and ledger events: integer cents with a
currency tag, an allocation, an immutable expense event, and an append-only settlement
event with a pending and a confirmed state. Tasks 3, 4 and 6 can all be built against
these types without reshaping them.

## Acceptance criteria

**Money**

- `Money` is a frozen value type holding `cents: int` and `currency: Currency`, and it is
  hashable.
- `Money` may be negative or zero. Balances in task 4 are signed, so the primitive has to
  carry a sign.
- Constructing `Money` with a `float` raises `TypeError`, including both `Money(12.5, aud)`
  and `Money(1250.0, aud)`. A `bool` is rejected too, even though it is an `int` subclass.
- Adding, subtracting or comparing two `Money` values with different currencies raises
  `CurrencyMismatch`. Same-currency operations return `Money`.
- Multiplying `Money` by an `int` is supported. Division is not exposed at all, so no
  caller can produce a fractional cent. Splitting is task 3's job.
- No `float` appears anywhere in the money path: no `float()` call, no `/` true division
  on cents, no `round()` on a float. Integer `//` and `divmod` only.
- `Decimal` is used inside parsing and formatting and nowhere else. It never appears in a
  public field, return type or constructor argument.

**Currency**

- `Currency` is a frozen value type holding an ISO 4217 alpha-3 `code`, validated as
  exactly three characters in `A-Z`. Lowercase input is rejected rather than coerced, so
  persisted codes have exactly one canonical form.
- Minor units are fixed at 2 for every currency in v1, exposed as one named module
  constant that parsing and formatting both read. Zero-decimal currencies such as JPY are
  a documented v1 limitation, not a silent bug.

**Amount parsing (input edge)**

- `parse_amount` takes a `str` and a `Currency` and returns `Money`. Passing an `int`,
  `float` or `Decimal` raises `TypeError`.
- `"12.5"` parses to 1250 cents, `"12.50"` to 1250, `"12"` to 1200.
- `".5"` parses to 50 cents. A missing integer part is allowed, a missing fractional part
  is allowed, a string with neither is rejected.
- `"12.345"` is rejected. More fractional digits than the currency's minor units is always
  an error, and it stays an error when the extra digits are zeros, so `"12.500"` is
  rejected too. The parser never rounds a user's amount.
- `"1,234.50"` parses to 123450 cents. Commas are accepted only as thousands separators in
  correct three-digit groups left of the decimal point.
- `"12,5"` is rejected rather than read as either 12.5 or 125. The app is single-locale
  with a dot decimal separator, and comma-decimal input must fail loudly.
- `"1,23,456.00"`, `"1234,567.00"` and `",123.00"` are rejected as malformed grouping.
- An optional leading `$` and surrounding whitespace are accepted, so `" $12.50 "` parses
  to 1250. No other symbol and no currency code is accepted inside the string.
- `"1e3"`, `"NaN"`, `"nan"`, `"Infinity"`, `"-Infinity"` and `"+12"` are all rejected.
  `Decimal` happily accepts every one of these, so the string must be validated against an
  explicit pattern before any `Decimal` is constructed.
- Non-ASCII digits are rejected, for example the Arabic-Indic digits U+0661 U+0662.
  Python's `\d` matches those and `Decimal` accepts them, so the pattern must use `[0-9]`
  explicitly and the check must not be delegated to `Decimal`.
- `""`, `"   "`, `"."`, `"$"`, `"abc"`, `"12 34"` and `"1.2.3"` are rejected.
- Negative input is rejected at the parse edge, including `"-5.00"`. Users never type a
  negative amount in this product; negative `Money` is constructed from cents by the
  balance layer instead.
- `"0"` and `"0.00"` parse successfully to zero cents. Rejecting a zero-value expense is
  the expense type's job, not the parser's.
- An amount whose cent value would exceed `2**63 - 1` is rejected, so every value fits a
  64-bit integer column in task 6.
- Every rejection raises one named exception type carrying the offending input in its
  message, so task 10 can surface it directly.

**Amount formatting (display edge)**

- `format_amount(money)` returns exactly two decimal places with thousands separators:
  1250 gives `"12.50"`, 123450 gives `"1,234.50"`, 0 gives `"0.00"`, 5 gives `"0.05"`.
- Negative values render with a leading minus, so -1250 gives `"-12.50"`. No parentheses
  and no currency-specific placement.
- A keyword-only symbol option prefixes `$`, giving `"$1,234.50"`. It is off by default, so
  no symbol is ever concatenated into stored text by accident.
- Round trip holds: for any non-negative `Money`,
  `parse_amount(format_amount(m), m.currency) == m`. This is the test that keeps the
  parser's and the formatter's comma rules in step.

**Identity**

- `MemberId`, `GroupId`, `ExpenseId` and `SettlementId` are distinct declared id types
  over `str`, so a member id is not interchangeable with an expense id when read.
- New ids are minted by a factory returning a UUID4 string. Ids are never derived from
  names, emails or sequence numbers.
- Every event validates that each id field is a non-empty `str` at construction.
- No type checker is configured in this repo, so the distinctness is documentation and
  future-proofing. The runtime guarantee comes from the constructor validation above.

**Allocation**

- `Allocation` is a frozen value type holding `member_id: MemberId` and `cents: int`.
- Allocation cents must be zero or positive. Zero is legal and must not be rejected: 2
  cents split across 3 people gives `1, 1, 0`, and task 3 has to be able to express that.
  Negative allocation cents are rejected.
- `Allocation` carries no currency. The enclosing event carries one currency covering all
  of its amounts, which is what makes a mixed-currency event unrepresentable.

**Expense event**

- `ExpenseEvent` is frozen with slots and holds: `id`, `group_id`, `currency`, `payer_id`,
  `total_cents`, `allocations`, `description`, `created_at`, `created_by`.
- `allocations` is a `tuple`, not a `list`, so the frozen dataclass is genuinely immutable
  and the event stays hashable.
- `sum(a.cents for a in allocations) == total_cents` exactly, validated at construction.
  This is the invariant task 3 is written to satisfy and task 4 relies on.
- `total_cents` must be strictly positive. Zero is a data-entry error, negative is a
  refund, and v1 has neither.
- An empty `allocations` tuple is rejected.
- A member id appearing twice in `allocations` is rejected. The task 4 fold and the task 13
  drill-down both break quietly on duplicates, so it has to fail at construction.
- The payer is not required to appear in `allocations`. Task 4 explicitly tests the
  payer-is-not-a-participant case, so no constraint may link the two.
- An expense where the payer is the only participant is legal and produces no debt.
- `created_at` is a timezone-aware `datetime`, stored in UTC. A naive `datetime` is
  rejected.
- `description` is a `str`, stripped of surrounding whitespace, and may be empty. Entry
  speed is a product requirement, so a description is never mandatory. No length cap is
  imposed here; task 6 picks a storage width.
- The event exposes no mutating method. Correcting an expense is task 17 and happens by
  appending a new event.

**Settlement events**

- A settlement is modelled as two append-only pieces rather than one mutable row: a
  `SettlementEvent` recording the proposed payment, plus a `SettlementDecisionEvent` that
  references it by id.
- `SettlementEvent` holds: `id`, `group_id`, `currency`, `from_member_id` (the payer),
  `to_member_id` (the receiver), `amount_cents`, `created_at`, `created_by`. It is born
  pending and carries no state field, because a mutable state field on an immutable event
  is a contradiction.
- `SettlementDecisionEvent` holds: `id`, `settlement_id`, `decision`, `decided_by`,
  `created_at`. It never restates the amount, so a decision cannot disagree with the
  settlement it decides.
- `SettlementState` is an enum with exactly `PENDING`, `CONFIRMED` and `REJECTED`. Task 15
  needs a rejected settlement to stay visible with its state changed, so rejection is a
  state and not a deletion.
- `amount_cents` must be strictly positive.
- `from_member_id != to_member_id`. A self-settlement is rejected.
- The module docstring states the rule that resolves a conflicting log: the earliest
  decision for a given settlement id wins, and later decisions for the same settlement are
  ignored. Tasks 4, 6 and 15 must all agree on this, so it is written down here even though
  it is enforced there.
- The docstring also states that only `CONFIRMED` settlements enter the balance fold, and
  that a pending settlement moves no balance.

**Cross-cutting**

- All domain exceptions subclass a single base error, so task 10 can map the whole family
  to one HTTP response without catching bare `Exception`.
- Every event type carries `group_id`, so folding events from two groups together is a
  detectable mistake rather than a silent one, with one deliberate exception:
  `SettlementDecisionEvent` carries only `settlement_id` and inherits its group from the
  settlement it decides, so the field list above is correct as written. The rule and its
  cost live in "A settlement decision has no `group_id` of its own" under Modelling notes
  in `plans/spec.md`; read that before adding the field or restating this rule elsewhere.
- A documented ordering key of `(created_at, id)` gives events a total order even when two
  timestamps are identical. Tasks 4, 11 and 16 all read events in order.
- Constructing any invalid value raises. There is no "valid-ish" object that a later layer
  has to re-check.
- New tests live in `tests/`, cover every criterion above, and `uv run python -m pytest`
  passes from a clean clone. The existing `tests/test_smoke.py` keeps passing unchanged.

## Out of scope

- Splitting a total across people. Task 3 owns the resolver and the remainder rule; task 2
  only supplies the `Allocation` type it emits and the sum invariant it must satisfy.
- Folding events into balances, and deriving a settlement's current state from its decision
  events. Both belong to task 4.
- Any database, schema, migration, ORM or serialisation format. Task 6 mirrors these types
  into a schema; task 2 must not import a storage library or name a table.
- `Group`, `Member` and `User` aggregate types. Those are owned by tasks 6, 7 and 9. Task 2
  refers to members and groups by id only.
- Validating that a payer or participant is actually a member of the group. Task 2 has no
  membership roster in scope. That check belongs to the service layer in tasks 9 and 10.
- Enforcing that group currency is immutable once the first expense lands. The type layer
  makes a mixed-currency event unrepresentable; immutability across events is enforced by
  task 6.
- Enforcing that the confirming member is the settlement's receiver. A decision event
  cannot see the settlement it references, so that rule belongs to task 15.
- Correction and void events. Task 17 adds them, and it must be able to do so by adding a
  new event type rather than by changing `ExpenseEvent`.
- Exchange rates, currency conversion, and zero-decimal or three-decimal currency support.
  One group, one currency, two minor units.
- Partial settlements and instalments. The spec cuts them from v1.
- Any HTTP, CLI or UI surface.
- Adding a type checker, a linter, or `hypothesis`. If task 3 wants property testing, that
  is task 3's dependency decision to make.

## Constraints

- Files to create: `src/splitwise_lite/money.py` (currency, money, parsing, formatting, the
  exception base) and `src/splitwise_lite/events.py` (id types, allocation, expense event,
  settlement event, decision event, state enum). Tests go in `tests/test_money.py` and
  `tests/test_events.py`.
- `src/splitwise_lite/__init__.py` may re-export the public names, but `__version__` must
  keep its current value because `tests/test_smoke.py` asserts it.
- Do not modify `plans/backlog.md`, `plans/spec.md`, or this file.
- Standard library only. `decimal`, `dataclasses`, `enum`, `uuid`, `datetime`, `re` and
  `typing` cover everything described here. Do not add `pydantic`, `attrs`, `moneyed`,
  `babel` or any other third-party package. If implementation reveals a genuine need for
  one, stop and raise it rather than adding it, and follow CLAUDE.md: declare it in
  `pyproject.toml` and run `uv sync`, never `pip install`.
- Python 3.12 target. Use `frozen=True, slots=True` dataclasses for every value and event
  type, and validate in `__post_init__`.
- Parsing validates the string against an explicit `[0-9]`-based pattern before
  constructing a `Decimal`, then converts to cents with integer arithmetic on the digit
  strings, or with `Decimal` scaling followed by `int()` on an exactly integral value. It
  must never call `float()` and never round.
- Follow the money rules in CLAUDE.md: integer cents everywhere, parse at the input edge,
  format only for display.
- Every public type and function gets a docstring stating the invariant it enforces,
  because tasks 3, 4 and 6 are written against these docstrings.
- Dependency direction is one way: `events.py` imports from `money.py`, and `money.py`
  imports nothing from the package.
