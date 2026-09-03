# Task 3: Split resolver

**Depends on:** 2 (complete, landed on `master`)
**Consumed by:** 10 (expense entry screen)

Sharpened from `plans/backlog.md` task 3. The backlog entry stays as written; this file
is the implementable version.

## Goal

One module turns any of the three split modes into an explicit tuple of `Allocation`
that sums exactly to the total, with leftover cents assigned by a stated rule rather
than by whoever happens to sort first. Task 10 can resolve a filled-in expense form to
allocations with one call, and the result drops straight into `ExpenseEvent`.

## Mode mapping

The backlog names three modes. They resolve to three functions:

| Backlog mode | Function |
|---|---|
| Equal across all | `split_equally(total_cents, member_ids)` with every member |
| Equal across a subset | `split_equally(total_cents, member_ids)` with the subset |
| Uneven by weight | `split_by_weight(total_cents, weights)` |
| Uneven by exact amount | `split_exact(total_cents, amounts)` |

"Equal across all" and "equal across a subset" are the same computation over a
different member list. The resolver has no membership roster (task 2 kept one out of
the domain layer, and tasks 9 and 10 own it), so "all" is a list the caller assembles.
There is deliberately no fourth function and no mode enum.

## The remainder rule

Stated once here because it is the point of the task, and both fair-share modes share
one implementation of it.

Every mode is computed by the largest-remainder method on integer arithmetic. For a
total `T`, weights `w_i` and `W = sum(w_i)`:

* each member's floor share is `(T * w_i) // W`, and their remainder is `(T * w_i) % W`
* the leftover cents, `T - sum(floor shares)`, are handed out one each to the members
  with the largest remainder

An equal split is the same computation with every weight equal to 1, so there is one
remainder engine and not two.

Under an equal split every remainder is identical, so the tie-break is what actually
decides who absorbs the extra cent. It is a **rotation**: members are placed in
ascending `member_id` order, and the walk starts at index `(T // n) % n` where `n` is
the number of participants, wrapping around.

The rotation is what the backlog is asking for. A plain sorted tie-break would hand the
extra cent to the same member on every expense, which is the "whoever sorts first"
outcome the backlog and the spec both reject. Offsetting by the base share makes the
recipient move as the total moves, so over a series of expenses the extra cent lands on
everyone. Offsetting by `T % n` instead would not work: `T % n` *is* the leftover count,
so a one-cent remainder would always land on the same index.

## Acceptance criteria

**Shape and contract**

- Each of the three functions returns a `tuple[Allocation, ...]`, so the result is
  immutable and can be handed to `ExpenseEvent.allocations` unchanged.
- Allocations are returned in ascending `member_id` order for all three modes. The
  order the caller supplied members in is never echoed back, so two callers who name
  the same people in a different order get an identical result.
- `sum(a.cents for a in result) == total_cents` exactly, for every mode and every
  accepted input. This is the invariant `ExpenseEvent` validates and task 4 folds on.
- Every returned allocation is a real `Allocation`, so its own invariants
  (non-empty member id, non-negative cents) are enforced at construction.
- No `float` anywhere: no `float()`, no `/` true division, no `round()`. Integer `//`,
  `%` and `divmod` only.

**Equal split**

- `split_equally(1000, [a, b, c])` gives 334, 333, 333: every member is within one cent
  of the base share, and the total is exact.
- With `n` members and a leftover of `r` cents, exactly `r` members get `base + 1` and
  the rest get `base`. No member is ever two cents off another.
- A single member takes the whole total: `split_equally(1000, [a])` gives 1000.
- A total smaller than the head count still resolves: `split_equally(2, [a, b, c])`
  gives allocations of 1, 1 and 0. A zero allocation is legal and must not be dropped
  from the result or rejected, because task 2 designed `Allocation` for exactly this.
- `split_equally(1, [a, b, c])` gives a single cent to one member and zero to the other
  two, and the result still has three allocations.
- Shuffling the input list does not change the result. Tested by resolving every
  permutation of a member list and asserting one identical answer.
- The extra cent rotates: across a run of consecutive totals for a fixed member list,
  every member receives the extra cent at least once. This is the criterion that fails
  if the tie-break is ever reduced to plain sorted order.
- The recipient is a pure function of the total and the member set, so resolving the
  same expense twice gives the same answer in a fresh process. No clock, no randomness,
  no `hash()` of a `str` (which is salted per process and would break this).

**Weighted split**

- `split_by_weight` takes a mapping of member id to an integer weight and allocates in
  proportion: `split_by_weight(1000, {a: 1, b: 2, c: 1})` gives 250, 500, 250.
- Where the proportion does not divide evenly, the largest remainder wins:
  `split_by_weight(10, {a: 1, b: 2})` gives 3 and 7, not 4 and 6.
- A member with double another's weight receives double their cents, within the one
  cent the rounding can move.
- A weight of zero is accepted and allocates zero cents. It says "this person is on the
  expense and owes nothing", which is expressible and must not be rejected.
- A negative weight is rejected.
- All weights zero is rejected rather than dividing by zero, and the error says the
  weights sum to zero.
- A `float` weight raises `TypeError`, including a whole-valued one like `2.0`. Shares
  of one and a half are expressed as weights 3 and 2. A `bool` weight is rejected too,
  even though `bool` is an `int` subclass.
- An empty mapping is rejected.
- Equal weights agree with the equal split exactly: for the same total and members,
  `split_by_weight` with every weight 1 returns what `split_equally` returns, including
  which member absorbs the extra cent.

**Exact split**

- `split_exact` takes a mapping of member id to an exact cent amount and returns those
  amounts unchanged, in member id order.
- Amounts that do not sum to the total are rejected, and the error message carries both
  the total and what the amounts summed to, so task 10 can tell the user by how much
  they are out.
- Being over the total and being under it are both rejected. The resolver never absorbs
  the difference into somebody's share, and it never adjusts the total to fit.
- A zero amount is accepted. A negative amount is rejected.
- An empty mapping is rejected.
- A `float` amount raises `TypeError`, including `12.0`. Amounts reach this function as
  cents, already through `parse_amount`.

**Rejections common to every mode**

- `total_cents` must be a strictly positive `int`. Zero and negative are rejected, which
  matches `ExpenseEvent.total_cents` so the resolver cannot produce allocations for an
  expense that will not construct.
- A `float` or `bool` `total_cents` raises `TypeError`, including `1000.0`.
- `total_cents` above `MAX_CENTS` is rejected, so every allocation fits the signed
  64-bit column task 6 will write to.
- An empty member list or mapping is rejected. There is no expense with nobody on it.
- A member id repeated in the `split_equally` list is rejected. `ExpenseEvent` rejects
  duplicate allocations, so the resolver must not manufacture them. Mappings cannot
  carry a duplicate key, so this applies to the list form only.
- A member id that is not a non-empty `str` is rejected.
- Passing something that is not a sequence of ids, or not a mapping, raises `TypeError`.
- Every value rejection raises one named exception, `InvalidSplit`, which subclasses
  `DomainError` so task 10 maps the whole domain family to one response. Wrong Python
  types raise `TypeError`, matching the convention task 2 set: bad input is a domain
  error, a wrong type is a programming error.

**Property tests**

- The sum invariant is property-tested: for every mode, allocations sum to the total
  across a wide range of generated inputs.
- Coverage is exhaustive where the domain is small enough to enumerate: every total from
  1 to 400 cents crossed with every head count from 1 to 8, asserting the exact sum, the
  within-one-cent fairness bound and the allocation count on each.
- Coverage is randomised where it is not, seeded from a fixed constant so a failure is
  reproducible from the test alone. Random totals reach into the millions of cents and
  random weights cover zero, one and large values.
- The rotation is property-tested: over any window of `n` consecutive totals for `n`
  members, the extra cent is not always the same member.

**Suite**

- New tests live in `tests/test_split.py` and cover every criterion above.
- `uv run python -m pytest` passes. The 281 tests already on `master` keep passing
  unchanged.

## Out of scope

- Deciding who is in the group or validating that a member id names a real member.
  Tasks 9 and 10 own the roster; the resolver takes ids on trust, exactly as task 2's
  events do.
- Constructing an `ExpenseEvent`. The resolver returns allocations; the caller builds
  the event.
- A mode enum, a dispatcher, or a form model that carries a mode and its arguments
  together. Task 10 collects the mode from the UI and calls the matching function.
  Three functions with three different argument types beat one function with three
  optional arguments.
- Parsing amounts from text. `parse_amount` is the input edge and already exists; the
  resolver works in cents.
- Percentage splits. The spec names equal, subset and uneven only, and a percentage is a
  weight with an implied denominator of 100, so it needs no separate mode.
- Balances, debt simplification and settlement. Tasks 4 and 5.
- Persistence and serialisation. Task 6.
- Adding `hypothesis`, a type checker or a linter. See the constraint below.
- Re-splitting or correcting an expense. Task 17 appends a correction event, which
  resolves its own allocations through this same module.

## Constraints

- Files to create: `src/splitwise_lite/split.py` and `tests/test_split.py`.
  `src/splitwise_lite/__init__.py` may re-export the new public names, following the
  precedent task 2 set, but `__version__` must keep its current value because
  `tests/test_smoke.py` asserts it.
- Do not modify `plans/backlog.md`, `plans/spec.md`, this file, or anything under
  `src/splitwise_lite/` other than the two files named above. Task 2's types are
  consumed, never reshaped: if a criterion here seems to need `Allocation`, `Money` or
  `ExpenseEvent` changed, stop and raise it.
- **No new dependency, and specifically not `hypothesis`.** Task 2 left this decision to
  task 3, and the decision is no. The invariant under test is a sum over a small integer
  domain, so enumerating every total from 1 to 400 against every head count from 1 to 8
  is a stronger check than sampling that space randomly, and a seeded `random.Random`
  covers the large domain reproducibly. Both are standard library. If a later task wants
  shrinking or stateful testing, it can declare `hypothesis` in the `dev` group then, on
  its own merits. Per CLAUDE.md, any dependency is declared in `pyproject.toml` and
  installed with `uv sync`, never ad hoc.
- Standard library only: `dataclasses` is not even needed here. `collections.abc`,
  `typing` and, in the tests, `itertools` and `random` cover everything.
- Python 3.12 target. Validate eagerly and raise: there is no partly-valid allocation
  set that a later layer has to re-check.
- Dependency direction stays one way. `split.py` imports `Allocation` and `MemberId`
  from `events.py` and `DomainError` and `MAX_CENTS` from `money.py`, and neither of
  those modules learns about `split.py`.
- Both fair-share modes go through one internal allocator. Do not write the remainder
  rule twice: an equal split is a weighted split with every weight 1, and a second copy
  of the rule is a second place for it to drift.
- Every public function gets a docstring stating the invariant it enforces and naming
  the remainder rule, because task 10 is written against these docstrings.
- Follow the money rules in CLAUDE.md: integer cents throughout, and never a float in
  the split path.
- Tests use exact integer assertions, never approximate comparison, per
  `.claude/rules/testing.md`. No test is skipped or xfailed.
