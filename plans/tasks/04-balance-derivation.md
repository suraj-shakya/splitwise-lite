# Task 4: Balance derivation

**Depends on:** 2 (complete, landed on `master`)
**Consumed by:** 5 (debt simplification), 15 (receiver confirmation), and through 5,
12 (balances screen)

Sharpened from `plans/backlog.md` task 4. The backlog entry stays as written; this file
is the implementable version.

## Goal

One pure function folds a list of ledger events into pairwise balances and per-member
net positions, so the product can answer "who owes who" without ever storing a balance.
The same list of events always produces the same answer, in any order, in any process.
Task 5 can reduce the pairwise map to transfers, and task 15 can ask this module what
state a settlement is in.

## What the fold takes and returns

The backlog says "a list of expense and confirmed settlement events". Read that as the
whole log: the caller passes expenses, settlements **and** decision events, and this
module works out which settlements are confirmed. Task 2 deliberately gave
`SettlementEvent` no state field, so nobody upstream can pre-filter to "confirmed"
without duplicating the rules below.

Two public functions:

| Function | Answer |
|---|---|
| `derive_balances(events, *, group_id, currency)` | a `Balances` value |
| `settlement_states(events)` | `dict[SettlementId, SettlementState]` |

`Balances` is a frozen value holding `group_id`, `currency` and two read-only mappings:

* `net: Mapping[MemberId, Money]` — one entry per member the fold has seen. A positive
  value means the group owes them; a negative value means they owe the group. This is
  the per-member figure task 12 renders.
* `pairwise: Mapping[tuple[MemberId, MemberId], Money]` — the key is
  `(debtor, creditor)` and the value is always strictly positive. `(bo, ali): $10.00`
  reads as "Bo owes Ali ten dollars". A pair that nets to zero is not in the map, and
  only one direction of a pair is ever present. This key is the stable identity of a
  pairwise debt, and it is what task 5's provenance points back at.

`net` is a summary and can be recomputed from `pairwise`. `pairwise` cannot be
recomputed from `net` — that loss is exactly what debt simplification does, and it is
why the fold accumulates the pairwise map directly from each event rather than
distributing net positions afterwards.

Worked example. Ali pays 3000 for dinner, split equally across Ali, Bo and Cass:

* `net` = Ali +2000, Bo -1000, Cass -1000
* `pairwise` = `{(Bo, Ali): 1000, (Cass, Ali): 1000}`

Bo then settles 1000 to Ali and Ali confirms:

* `net` = Ali +1000, Bo 0, Cass -1000
* `pairwise` = `{(Cass, Ali): 1000}`

## The two settlement rules

Both are already written in the `events.py` module docstring. Task 4 is the first module
that enforces them, and every other consumer must get the same answer, so they are
implemented once here and imported, never re-derived.

1. **Earliest decision wins.** A settlement's state is decided by the earliest decision
   event referencing it, ordered by `ordering_key` (`(created_at, id)`). Later decisions
   for the same settlement are ignored, including a later `CONFIRMED` after an earlier
   `REJECTED`. A retry or a race can put two answers in the log; picking the first keeps
   every reader on the same answer.
2. **Only confirmed settlements move money.** `PENDING` and `REJECTED` settlements are
   inert: they change no net position, create no pairwise entry, and do not even put
   their two members into the `net` map. Until the receiver confirms, the claimed
   payment is a row on a screen, not money that has moved.

## How a decision event finds its group

`SettlementDecisionEvent` carries no `group_id`. That matches the field list in
`plans/tasks/02-domain-types-and-money-primitives.md` and contradicts the cross-cutting
rule in the same file that every event type carries one. The task 2 reviewer flagged it
for settling here. **Task 4 works with the types as they are and does not change them.**

The resolution:

* `group_id` is a required argument to `derive_balances`. The group is stated by the
  caller, not inferred from whichever event happens to sort first.
* Every `ExpenseEvent` and `SettlementEvent` in the input must carry that `group_id`.
  One that does not raises `InvalidLedger`. Task 2's stated reason for putting
  `group_id` on events is that folding two groups together should be a detectable
  mistake, and silently dropping the foreign events would make it undetectable.
* A decision event is bound to a group indirectly, through `settlement_id`. It applies
  to the settlement of that id in the same input.
* A decision whose `settlement_id` names no settlement in the input is **ignored, not
  an error**. Without a `group_id` of its own it cannot be attributed to anything: it
  may belong to another group's settlement, or to a settlement outside the window the
  caller loaded. Ignoring is the only rule that is total, and it is safe, because a
  decision never moves money by itself.

The consequence for task 6 is worth stating in the module docstring: a query layer must
load a group's settlements and their decisions together, because decisions cannot be
filtered by group on their own.

## Acceptance criteria

**Shape and contract**

- `derive_balances(events, *, group_id, currency)` returns a `Balances`. Both
  `group_id` and `currency` are keyword-only and both are required.
- `Balances` is a frozen dataclass with slots holding `group_id: GroupId`,
  `currency: Currency`, `net: Mapping[MemberId, Money]` and
  `pairwise: Mapping[tuple[MemberId, MemberId], Money]`.
- Both mappings are read-only views (`types.MappingProxyType`), so no consumer can
  mutate a derived balance in place. A derived figure is a value, not a cache to patch.
- `Balances` compares by value: two folds of the same events are `==`. It is not
  required to be hashable, and no `__hash__` is written for it.
- `Balances.net_for(member_id)` returns `Money(0, currency)` for a member the ledger has
  never seen, so task 12 can walk the roster without a `KeyError`. It never raises for
  an unknown member.
- `Balances.owed_between(debtor, creditor)` is signed and total: it returns the stored
  amount when that direction is present, the negative of the stored amount when the
  reverse direction is present, and `Money(0, currency)` when the pair has no debt.
- `events` accepts any iterable, a generator included, and is consumed exactly once. A
  caller's list is neither mutated nor reordered by the call: sort a copy.
- The function is pure. No clock, no I/O, no randomness, no module-level mutable state,
  no memoisation. Called twice on the same events in a fresh process it returns equal
  results.
- The result does not depend on the order of the input. Sorting is by `ordering_key`
  imported from `events.py`, never by list position and never by `created_at` alone.
- Iteration order is deterministic: `net` keys ascend by member id, `pairwise` keys
  ascend by `(debtor, creditor)`. Two readers of the same log see the same rows in the
  same order.

**Sign conventions**

- `net[m]` positive means the group owes `m`; negative means `m` owes the group. A
  member who paid 3000 and consumed 1000 has `net` of +2000.
- `sum(v.cents for v in net.values()) == 0` for every input. Money is only ever moved
  between members, never created.
- Every `pairwise` value is strictly positive. Zero is never stored as a debt.
- A pair appears in at most one direction: if `(d, c)` is present then `(c, d)` is
  absent.
- A self pair `(m, m)` never appears.
- `net` and `pairwise` agree: for every member,
  `net[m] == sum of pairwise entries where m is creditor - sum where m is debtor`.

**The expense fold**

- Every expense in scope is folded. The payer is credited `total_cents` and each
  allocation debits its member by that allocation's cents.
- The fold credits `total_cents`, not the sum of the allocations. `ExpenseEvent`
  guarantees they are equal, and the fold re-checks none of task 2's construction
  invariants.
- **Payer is a participant:** Ali pays 3000 split equally across Ali, Bo and Cass gives
  `net` Ali +2000, Bo -1000, Cass -1000 and `pairwise`
  `{(Bo, Ali): 1000, (Cass, Ali): 1000}`. The payer's own allocation creates no debt to
  themselves.
- **Payer is not a participant:** Ali pays 3000 split across Bo and Cass only gives
  `net` Ali +3000, Bo -1500, Cass -1500 and `pairwise`
  `{(Bo, Ali): 1500, (Cass, Ali): 1500}`. Ali holds a `net` entry despite being in no
  allocation.
- An expense where the payer is the only participant produces `net` of 0 for the payer,
  who still appears as a key, and an empty `pairwise`. Task 2 declared this legal, so it
  must not raise and must not be dropped.
- A zero-cent allocation creates no `pairwise` entry, because zero is not a debt, but
  its member still appears in `net` with zero. Task 3 emits zero allocations for small
  totals, so this arrives in real data.
- Two expenses between the same pair accumulate into one `pairwise` entry, and debts in
  opposite directions net: Ali pays 1000 for Bo, then Bo pays 400 for Ali, leaves
  `{(Bo, Ali): 600}`.

**The settlement fold**

- A confirmed settlement of `amount_cents` from A to B credits A and debits B: A has
  handed over real money, so A's position improves.
- **Full settlement back to zero:** after the three-person dinner above, Bo settling
  1000 to Ali and Cass settling 1000 to Ali, both confirmed, gives `net` of zero for all
  three, all three still present as keys, and an empty `pairwise`.
- A pending settlement moves nothing: identical `Balances` with and without it, and
  neither of its members gains a `net` key on its account alone.
- A rejected settlement moves nothing, by the same test.
- A confirmed settlement larger than the debt flips the pair: with `{(Bo, Ali): 1000}`,
  Bo settling 1500 leaves `{(Ali, Bo): 500}` and `net` Ali +500, Bo +500, Cass -1000.
  The fold records what the log says and never clamps a settlement to the debt it
  appears to clear.
- A confirmed settlement between two members with no expense between them creates a
  debt in the opposite direction: Bo paying Cass 750 with no expenses at all gives
  `{(Cass, Bo): 750}`. Handing someone money for nothing is recordable.
- The fold never validates a settlement's amount against any pairwise debt. "Confirm in
  full or not at all" is a service and UI rule in tasks 14 and 15, not an arithmetic one.

**Settlement state**

- `settlement_states(events)` returns one entry for every `SettlementEvent` in the
  input, keyed by settlement id, ascending, with `PENDING` for a settlement that has no
  decision.
- The earliest decision by `ordering_key` decides. A `CONFIRMED` at 10:00 followed by a
  `REJECTED` at 11:00 gives `CONFIRMED`; reverse the timestamps and it gives `REJECTED`.
- Two decisions sharing a `created_at` are broken by id, so the decision with the
  smaller id string wins, and the answer does not depend on list order.
- Shuffling the input changes nothing about the returned states.
- A decision referencing a settlement id not in the input is ignored and adds no key to
  the output.
- Expense events in the input are ignored rather than rejected, so the same whole-log
  list can be passed to both public functions.
- The function does not check that `decided_by` is the settlement's receiver. Task 2
  assigned that rule to task 15, which can load both records.
- `derive_balances` uses this same code path, so the balances and the rendered state of
  a settlement can never disagree.

**Group and currency**

- An `ExpenseEvent` or `SettlementEvent` whose `group_id` differs from the argument
  raises `InvalidLedger`, and the message names the event id, the group asked for and
  the group found.
- Events from two groups in one list raise even when one group's events would have
  folded cleanly on their own. There is no partial answer.
- Decision events are not group-checked, per the decision above, and an orphan decision
  is ignored rather than raising.
- An `ExpenseEvent` or `SettlementEvent` whose `currency` differs from the argument
  raises `CurrencyMismatch` from `money.py`, naming both codes. Adding NZD cents to AUD
  cents is exactly what that exception exists for, so no second name is invented.
- An empty event list returns a `Balances` with empty `net` and `pairwise` and the
  `group_id` and `currency` that were passed in. This is why `currency` is an argument
  rather than read off the first event: an empty ledger still has a currency, and no
  caller should have to handle a `None`.

**Rejections and types**

- `events` that is not iterable raises `TypeError`. An element that is not an
  `ExpenseEvent`, `SettlementEvent` or `SettlementDecisionEvent` raises `TypeError`
  naming the offending type.
- `group_id` that is not a `str` raises `TypeError`; an empty `group_id` raises
  `InvalidLedger`. `currency` that is not a `Currency` raises `TypeError`. This follows
  the convention tasks 2 and 3 set: rejected input is a domain error, a wrong Python
  type is a programming error.
- The same event id appearing twice within the same event type raises `InvalidLedger`,
  naming the id. Double-counting an expense is a money bug, and a caller who
  concatenates two overlapping queries would otherwise get a plausible wrong answer.
  Two distinct events with equal amounts and different ids are fine.
- `InvalidLedger` subclasses `DomainError`, so task 10 keeps mapping the whole domain
  family to one response.
- No `MAX_CENTS` bound is applied to a balance. Balances are derived and never stored,
  so there is no 64-bit column to overflow, and Python integers do not wrap. Task 3's
  bound belongs on stored amounts, not on a sum of them.

**Arithmetic**

- Integer cents throughout. No `float()`, no `round()`, no `Decimal`, no `/`.
- No division of any kind appears in this module, `//`, `%` and `divmod` included. The
  fold only adds and subtracts, so there is no remainder to assign and no rounding rule
  may be invented here. Splitting is task 3's job and has already happened.
- Public figures are `Money` carrying the group currency, so task 12 can call
  `format_amount` on them directly and a negative net renders as `-12.50`.

**Property tests**

- Over randomly generated ledgers from a seeded `random.Random`, mixing expenses with
  pending, confirmed and rejected settlements: `net` cents sum to exactly zero, every
  `pairwise` value is strictly positive, no pair appears in both directions, and `net`
  agrees with `pairwise` for every member.
- Order independence is exhaustive where it can be: every permutation of a hand-written
  six-event fixture that includes two conflicting decisions gives one identical
  `Balances` and one identical state map. Larger ledgers are covered by seeded shuffles.
- Settling every outstanding pairwise debt, one confirmed settlement per entry, drives
  every `net` to zero and leaves `pairwise` empty. This is the closure property task 5
  will lean on.
- Every assertion on cents is an exact integer comparison, never approximate.

**Suite**

- New tests live in `tests/test_balances.py` and cover every criterion above, including
  the three the backlog names by hand: payer-is-participant, payer-is-not-a-participant,
  and full settlement back to zero.
- `uv run python -m pytest` passes, and every test already on `master` from tasks 1, 2
  and 3 keeps passing unchanged.

## Out of scope

- Minimising transfers. Task 5 reduces the pairwise map; task 4 must not merge, net
  across pairs, or reorder debts to make the list shorter. A three-way cycle stays as
  three pairwise entries here.
- Provenance from a pairwise debt back to source expenses. The `(debtor, creditor)` key
  is the identity task 5 attaches provenance to, and task 13 drills from there. Adding
  event-id trails to `Balances` now would guess at task 5's shape before it exists.
- Storing, caching or memoising a balance anywhere, including a lazy attribute on
  `Balances`. The spec's resolution to the netting-versus-audit-trail conflict is that
  balances are derived on read, always.
- Knowing the roster. Members with no events do not appear in `net`; `net_for` returns
  zero for them. Tasks 9 and 12 own the member list, exactly as task 2 decided.
- Validating that a payer, participant or settlement counterparty is a member of the
  group. Same reason.
- Checking that a decision was made by the settlement's receiver, or that a settlement
  was raised by the debtor. Task 15.
- Rendering the "awaiting confirmation" row. Task 14 and task 15 own that screen and
  read `settlement_states` for it.
- Corrections and voids. Task 17 adds a new event type, and it must be able to do so by
  extending this fold rather than by reshaping `Balances`.
- Currency conversion, multi-currency groups, and enforcing that a group's currency
  never changes. Task 6 owns immutability across events.
- Any persistence, query, HTTP, CLI or UI surface. This module takes a list and returns
  a value.
- Changing task 2's types. Specifically, do not add `group_id` to
  `SettlementDecisionEvent`, do not add a state field to `SettlementEvent`, and do not
  relax any construction invariant. If a criterion here seems to require it, stop and
  raise it.
- Adding `hypothesis`, a type checker or a linter. Task 3 already decided no, on the
  same reasoning.

## Constraints

- Files to create: `src/splitwise_lite/balances.py` and `tests/test_balances.py`.
  `src/splitwise_lite/__init__.py` may re-export the new public names, following the
  precedent tasks 2 and 3 set, but `__version__` must keep its current value because
  `tests/test_smoke.py` asserts it.
- Do not modify `plans/backlog.md`, `plans/spec.md`, this file, or anything under
  `src/splitwise_lite/` other than the two files named above.
- Public names: `Balances`, `InvalidLedger`, `derive_balances`, `settlement_states`.
  Everything else in the module is private.
- Dependency direction stays one way. `balances.py` imports from `events.py` and
  `money.py`, and neither of them learns it exists. Do **not** import `split.py`: tasks
  3 and 4 are siblings, the backlog says they never touch each other's code, and nothing
  here divides a total.
- Standard library only, and no new dependency. `dataclasses`, `collections.abc`,
  `types` and `typing` cover the module; `random`, `itertools` and `datetime` cover the
  tests. Per CLAUDE.md, any dependency would be declared in `pyproject.toml` and
  installed with `uv sync`, never `pip install`.
- Python 3.12 target. `frozen=True, slots=True` on `Balances`, validation eager, no
  half-valid result a later layer has to re-check.
- Accumulate in plain `int` cents internally and wrap into `Money` once, when building
  the result. `Money` has no `__radd__`, so `sum()` over `Money` values raises
  `TypeError`; that is a deliberate feature of task 2's type, not a gap to work around
  by reaching for floats.
- Sort with `ordering_key` from `events.py`. Do not re-derive the `(created_at, id)`
  rule, and do not sort on `created_at` alone: identical timestamps are the case the
  tie-break exists for.
- Follow the money rules in CLAUDE.md: integer cents everywhere, formatting only at the
  display edge, and no float in the balance path.
- The module docstring states the sign convention, both settlement rules and the
  `group_id` decision above, because tasks 5, 12 and 15 are written against it. Every
  public name gets a docstring naming the invariant it enforces.
- Tests use exact integer assertions, never approximate comparison, per
  `.claude/rules/testing.md`. No test is skipped or xfailed. Run them with
  `uv run python -m pytest`; plain `uv run pytest` fails on this machine.
