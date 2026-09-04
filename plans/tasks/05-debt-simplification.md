# Task 5: Debt simplification with provenance

**Depends on:** 4 (complete, landed on `master`)
**Consumed by:** 12 (balances screen), 13 (transfer drill-down), 14 (mark as paid), 18
(end-to-end smoke test)

Sharpened from `plans/backlog.md` task 5. The backlog entry stays as written; this file
is the implementable version.

## Goal

One pure function turns a `Balances` value into a short list of suggested transfers that
settles the group, where every transfer carries references to the pairwise debts it
absorbed and every cent of every transfer is traceable to one of them. Task 12 can
render the list, task 13 can drill from a transfer back to real pairwise debts and on to
source expenses, and task 14 can turn a transfer into a settlement event.

Provenance is the deliverable, not a decoration. The spec's section "Netting and audit
trail pull in opposite directions" says netting discards exactly the information that
"show me how you got there" needs, and its resolution is that "every suggested transfer
keeps a pointer back to the pairwise debts it absorbed". Task 13 is impossible without
that pointer, so it is specified here down to the field.

## What this task consumes

`Balances` from `src/splitwise_lite/balances.py`, exactly as task 4 built it, and nothing
else. This module reads no events, opens no store and never recomputes a balance.

Two things from `Balances` matter, and they play different roles:

* `net: Mapping[MemberId, Money]` decides **who pays whom and how much**. Positive means
  the group owes that member, negative means they owe the group, and the cents sum to
  exactly zero.
* `pairwise: Mapping[tuple[MemberId, MemberId], Money]`, keyed `(debtor, creditor)` with
  a strictly positive value and only ever one direction of a pair, is the **vocabulary
  of provenance**. Task 4's file states it plainly: "This key is the stable identity of a
  pairwise debt, and it is what task 5's provenance points back at." Every provenance row
  produced here names one of those keys, unchanged.

The two are related by the identity this task leans on throughout: for any member `m`,
`net[m] == in(m) - out(m)`, where `in(m)` is the sum of pairwise debts owed **to** `m`
and `out(m)` is the sum of pairwise debts `m` **owes**.

## "Fewest transfers" is a greedy result with a stated bound, not a proven minimum

**Decision: a greedy largest-debtor-to-largest-creditor algorithm, bounded at `n - 1`
transfers for `n` members with a non-zero net. It is not a true minimum, and nothing in
this module, its docstrings or its tests may claim that it is.**

The reasoning, so nobody reopens it mid-build:

* Minimising the number of transfers exactly is NP-hard. The optimal plan corresponds to
  partitioning the members into as many zero-sum blocks as possible, which is subset-sum
  in disguise. A flat of five people would be fine; a correct general implementation
  would be a search, and an acceptance criterion that says "the result is minimal" would
  be a criterion the implementation cannot honour.
* The greedy bound is provable and easy to test. Each round settles at least one member
  completely and the final round settles two, so the plan never exceeds `n - 1`
  transfers.
* A matching lower bound is also easy to test. Every plan needs at least
  `max(debtors, creditors)` transfers, because each member with a non-zero net must
  appear in at least one of them.
* Where those two bounds meet, the greedy result **is** minimal, and the criteria below
  say so for the two cases that meet: one debtor with many creditors, and many debtors
  with one creditor. Those are the common shapes in a flat.

The honest statement, and the one the module docstring must carry: **this is the fewest
transfers this algorithm finds, at most `n - 1`, and at least `max(debtors, creditors)`.
It is not guaranteed to be the smallest plan that exists.** A fixture in the acceptance
criteria pins a case where the greedy takes four transfers and three are possible, so
that anyone tempted to write `assert len(transfers) == minimum` runs into it.

### The algorithm

1. Take every member whose `net` is non-zero. Negative nets are debtors, holding
   `-net[m]` cents outstanding; positive nets are creditors, holding `net[m]` cents
   outstanding. Zero-net members and members absent from `net` are not in the pools at
   all.
2. While both pools are non-empty: take the debtor with the largest outstanding amount
   and the creditor with the largest outstanding amount, emit a transfer of
   `min(debtor outstanding, creditor outstanding)` cents from that debtor to that
   creditor, subtract it from both, and drop either that reaches zero.
3. Both pools empty at the same moment, because `net` sums to zero.

## Determinism, and why this is not task 3's rotation

Two readers of the same ledger must see the same transfer list, so the result may not
depend on dict insertion order, on set iteration order, or on `hash()` of a string, which
is salted per process.

**Ties in the greedy are broken by ascending `member_id`, plainly, and there is no
rotation.** Task 3 faced a superficially similar choice with leftover cents and chose a
rotation, and that precedent is deliberately not followed here. The difference is what
the tie decides:

* In task 3 the tie-break decides **who pays an extra cent**. A plain sorted tie-break
  there means the same flatmate quietly pays one cent more on every expense forever,
  which is a real, cumulative unfairness, so the recipient has to move.
* Here the tie-break decides **who pays whom**, never how much anyone pays. Each member's
  total outlay is fixed by their `net` before any matching happens, so no member is a cent
  better or worse off under any tie-break. There is nothing to rotate away from.

Worse, a rotation here would actively hurt. The transfer list feeds task 14, where a payer
taps a transfer and records a settlement against it. A list that reshuffles who pays whom
between two page loads, for no change in the underlying debts, makes that action feel
unsafe and makes a bug report unreproducible. Stability is the requirement; a rotation is
the opposite of it.

Concretely, determinism means:

* the debtor and creditor pools are walked in `(-outstanding, member_id)` order, so the
  largest amount wins and the smaller id wins a tie
* transfers are returned sorted by `(from_member_id, to_member_id)`
* provenance rows within a transfer are sorted by `(debtor, creditor)`
* every iteration over a `set` or a `dict` that can reach the output goes through
  `sorted()`

## The provenance structure

Task 13 is written against these three types, so they are specified here rather than left
to the implementation.

```
AbsorbedDebt        frozen, slots
    debtor: MemberId          a Balances.pairwise key, first element
    creditor: MemberId        a Balances.pairwise key, second element
    amount: Money             the portion of that debt this transfer absorbs, > 0
    debt_total: Money         the whole pairwise debt, from Balances.pairwise
    pair -> tuple[MemberId, MemberId]     property: (debtor, creditor)

Transfer            frozen, slots
    from_member_id: MemberId
    to_member_id: MemberId
    amount: Money                             > 0
    payer_debts: tuple[AbsorbedDebt, ...]     debts the payer owes
    receiver_credits: tuple[AbsorbedDebt, ...] debts owed to the receiver

TransferPlan        frozen, slots
    group_id: GroupId
    currency: Currency
    transfers: tuple[Transfer, ...]
```

`AbsorbedDebt.pair` is exactly a `Balances.pairwise` key, so task 13 looks the debt up
directly and then expands it to source expenses through the store. Nothing is copied out
of the expense log here.

`Transfer` uses `from_member_id`, `to_member_id` and an `amount`, matching
`SettlementEvent`'s field names, so task 14 maps a tapped transfer onto a settlement
event without renaming anything.

**Provenance has two sides, and that is deliberate.** A transfer of 400 from Bo to Cass
has two questions attached, and one list answers only one of them:

* Bo asks "why am I paying at all, and why 400?" The answer is on the payer side: the
  debts Bo owes that this payment discharges.
* Bo and Cass both ask "why *Cass*, when I never bought anything with them?" That is the
  known failure mode task 13 exists to fix, and it can only be answered from the receiver
  side: the debts owed to Cass that this payment discharges.

So a transfer carries both, and each list independently accounts for the full transfer
amount. `payer_debts` sums to the transfer amount and every row names the payer as
debtor. `receiver_credits` sums to the same transfer amount and every row names the
receiver as creditor. **This is not double counting.** They are two views of one payment
from its two ends, and the criteria below keep each side's books separately.

Both attributions are always feasible, and the proof is one line each. A net debtor `d`
pays `-net[d] == out(d) - in(d)` in total, which is at most `out(d)`, so `d` always has
enough of their own outgoing debt to source every cent they pay. Symmetrically a net
creditor `c` receives `net[c] == in(c) - out(c)`, at most `in(c)`.

### How cents are attributed to debts

Run once for the payer side and once for the receiver side, over **separate** remaining
maps, both initialised from `Balances.pairwise`.

Payer side, with transfers taken in `(from_member_id, to_member_id)` order:

1. **Pass one, the direct debt.** For a transfer `d -> c`, if `(d, c)` is a pairwise key
   with remaining capacity, absorb `min(transfer amount, remaining)` of it first.
2. **Pass two, the rest.** While the transfer still has unattributed cents, take `d`'s
   outgoing key with the largest remaining capacity, ties broken by ascending creditor id,
   and absorb `min(still needed, remaining)`. Repeat.

Pass one cannot collide with pass two: if a transfer still needs cents after pass one,
its direct key was drained to zero, so pass two can never pick it again and a key can
never appear twice in one transfer's rows.

Receiver side is the mirror image: pass one takes the direct `(d, c)` key from the
receiver's own remaining map, pass two takes the receiver's incoming key with the largest
remaining capacity, ties broken by ascending debtor id.

Two consequences worth stating so nobody files them as bugs:

* Pass two can consume a debt that a later transfer would have preferred as its direct
  match, which costs a little readability and never costs honesty. Accepted.
* Cents left unattributed on a pairwise debt are exactly the cents that netting cancelled
  against something the payer was owed. That leftover is a fact about the group, not a
  gap, and the criteria below pin its size exactly.

## What a plan looks like

**A chain, where one debt splits across two transfers.** Bo owes Ali 1000 and Ali owes
Cass 400, so `net` is Ali +600, Bo -1000, Cass +400.

Transfers: `bo -> ali 600` and `bo -> cass 400`. Two transfers with one debtor, which is
the lower bound `max(1, 2)`, so this plan is provably minimal.

* `bo -> ali 600`: payer debts `[(bo, ali) 600 of 1000]`, receiver credits
  `[(bo, ali) 600 of 1000]`.
* `bo -> cass 400`: payer debts `[(bo, ali) 400 of 1000]`, receiver credits
  `[(ali, cass) 400 of 400]`.

The 1000 Bo owes Ali is split 600 and 400 across two transfers, each row carrying the
full 1000 as `debt_total` so the drill-down can say "400 of the 1000 you owe Ali". The
second transfer reads end to end: Bo pays Cass because Bo owes Ali, and Ali owes Cass.

**A transfer larger than any single debt it absorbs, with a zero-net bystander.** Bo owes
Ali 300, Bo owes Cass 300, Cass owes Ali 300. `net` is Ali +600, Bo -600, Cass 0.

One transfer, `bo -> ali 600`, with payer debts `[(bo, ali) 300 of 300, (bo, cass) 300 of
300]` and receiver credits `[(bo, ali) 300 of 300, (cass, ali) 300 of 300]`. The transfer
is twice the size of any debt on either list, which is the normal case and exactly what
the drill-down exists to explain. Cass pays and receives nothing, appears in no transfer,
and still shows up inside the provenance as a counterparty whose debts were netted
through.

**A pure cycle, which needs no transfers at all.** Ali owes Bo 500, Bo owes Cass 500,
Cass owes Ali 500. Every `net` is zero, so `transfers` is empty even though `pairwise`
holds three live debts, and every one of those debts is absorbed by nothing.

## Acceptance criteria

**Shape and contract**

- `simplify_debts(balances)` takes one positional `Balances` and returns a `TransferPlan`.
  There is no `group_id` or `currency` argument: `Balances` already carries both, and a
  second source for either would be a second thing to disagree.
- `plan.group_id == balances.group_id` and `plan.currency == balances.currency`.
- `AbsorbedDebt`, `Transfer` and `TransferPlan` are frozen slotted dataclasses holding
  exactly the fields listed above, in that order, and nothing else.
- All three compare by value and are hashable, tuples all the way down. This differs from
  `Balances`, which cannot be hashed because it holds mappings, and it lets a test compare
  plans with `==` and collect transfers into a set.
- `AbsorbedDebt.pair` returns `(debtor, creditor)` and is a key of `balances.pairwise`
  for every row in the plan.
- Every `Money` anywhere in the plan carries `balances.currency`.
- The function is pure. No clock, no I/O, no randomness, no module-level mutable state, no
  memoisation, no caching of a plan on the `Balances` it came from. Called twice on the
  same input it returns equal results, and it returns equal results in a fresh process.
- `simplify_debts` does not mutate its argument. A test compares `balances.net` and
  `balances.pairwise` before and after the call and asserts they are unchanged.
- Passing anything that is not a `Balances` raises `TypeError` naming the type received.

**Input validation**

- `InvalidBalances`, defined in this module and subclassing `DomainError` from `money.py`,
  is raised for a `Balances` that cannot be simplified. `Balances` is a public dataclass
  with no `__post_init__`, so a hand-built one can break invariants that `derive_balances`
  would never break, and silently producing a plan from it would be a money bug.
- The cents in `net` must sum to exactly zero, or `InvalidBalances` is raised naming the
  residue. The greedy's termination and the settle-to-zero guarantee both depend on it.
- Every `pairwise` value must be strictly positive, no pair may appear in both directions,
  and no self pair `(m, m)` may appear. Each violation raises `InvalidBalances` naming the
  offending pair.
- `net` and `pairwise` must agree: for every member, `net[m] == in(m) - out(m)`. A
  disagreement raises `InvalidBalances` naming the member and both figures. The provenance
  feasibility proof rests on this identity, so it is checked rather than assumed.
- A `Money` in `net` or `pairwise` whose currency differs from `balances.currency` raises
  `CurrencyMismatch` from `money.py`. No second name is invented for it.
- Validation is eager and total: it happens before any transfer is emitted, so a rejected
  input produces no partial plan.

**The transfer set**

- Every transfer amount is strictly positive, and `from_member_id != to_member_id`.
- `transfers` is sorted ascending by `(from_member_id, to_member_id)`.
- A `(from, to)` pair appears at most once in `transfers`, and `(to, from)` never appears
  alongside it. Each greedy round retires at least one participant, and no member is both
  a debtor and a creditor.
- The sum of transfer amounts equals the sum of the positive `net` values, which equals
  the negation of the sum of the negative ones.
- For every member `m`, `net[m] + received(m) - paid(m) == 0` in exact cents, where
  `paid` and `received` are sums over `transfers`. This is the backlog's "verify that
  simplified transfers settle the group to zero", checked directly on the plan.
- A member with `net[m] < 0` pays exactly `-net[m]` in total and receives nothing. A
  member with `net[m] > 0` receives exactly `net[m]` and pays nothing.
- A member with a `net` of zero appears in no transfer, as neither payer nor receiver. A
  member absent from `net` entirely likewise. Both may still appear inside provenance
  rows as a counterparty.

**The transfer count**

- With `d` debtors and `c` creditors, `max(d, c) <= len(transfers) <= max(0, d + c - 1)`.
  Both bounds are asserted on every generated case in the property tests, not only on
  hand-written fixtures.
- A group that is already settled produces `transfers == ()`. That covers an empty `net`,
  an all-zero `net`, and the pure cycle above where `pairwise` is non-empty and every
  `net` is zero. None of these is an error and none returns `None`.
- **One debtor, many creditors:** the debtor pays each creditor exactly that creditor's
  `net`, giving `c` transfers. Since `max(1, c) == c == 1 + c - 1`, the bounds meet and
  the plan is minimal. A test asserts the exact list and states that reason.
- **Many debtors, one creditor:** each debtor pays the creditor exactly `-net[debtor]`,
  giving `d` transfers, minimal by the same argument.
- **The greedy is not always minimal, and one fixture proves it.** For `net` of
  `ali -400, bo -200, cass +500, dee +400, eve -300`, `simplify_debts` returns exactly
  four transfers: `ali -> cass 400`, `bo -> cass 100`, `bo -> dee 100`, `eve -> dee 300`.
  Three transfers exist (`ali -> dee 400`, `bo -> cass 200`, `eve -> cass 300`) and the
  algorithm does not find them. The test asserts the four, names the three in a comment,
  and asserts nothing about optimality. This criterion exists to make a false optimality
  claim fail loudly.
- Ties are broken by ascending member id, and a fixture with two debtors holding equal
  amounts and two creditors holding equal amounts asserts the exact resulting list.

**Provenance: within one transfer**

- `sum(row.amount.cents for row in transfer.payer_debts) == transfer.amount.cents`
  exactly. No cent of a suggested payment is unexplained.
- `sum(row.amount.cents for row in transfer.receiver_credits) == transfer.amount.cents`
  exactly, by the same rule on the other side.
- Both lists are non-empty for every transfer, which follows from the two sums above and a
  strictly positive amount.
- Every row in `payer_debts` has `row.debtor == transfer.from_member_id`. Every row in
  `receiver_credits` has `row.creditor == transfer.to_member_id`.
- Every row's `pair` is a key of `balances.pairwise`, and `row.debt_total` equals
  `balances.pairwise[row.pair]` exactly. No row invents a debt or restates a wrong total.
- `0 < row.amount.cents <= row.debt_total.cents` for every row.
- A given `pair` appears at most once within `payer_debts` and at most once within
  `receiver_credits` of the same transfer. It may appear in both lists of the same
  transfer, which is the two-ended view and not a duplicate.
- Both lists are sorted ascending by `(debtor, creditor)`.
- **Direct debt first:** if `(from_member_id, to_member_id)` is a key of
  `balances.pairwise`, it appears in `payer_debts` with an amount of
  `min(transfer amount, that debt)`, and it appears in `receiver_credits` with the same
  amount. This is what makes the simple case read perfectly: one debt between two people
  produces one transfer whose provenance is that debt and nothing else.

**Provenance: across the whole plan**

- Payer side, per pairwise debt: for every key, the total absorbed across every
  transfer's `payer_debts` is at most `balances.pairwise[key]`. Never more.
- Receiver side, per pairwise debt: the same bound, computed independently across every
  transfer's `receiver_credits`.
- Payer side, per member: for every net debtor `d`, the total absorbed across all
  `payer_debts` rows where `row.debtor == d` equals `-net[d]` exactly, and the cents of
  `d`'s outgoing debts left unabsorbed equal `in(d)`, what `d` is owed. That leftover is
  the amount netting cancelled, and it is asserted as an exact figure rather than left
  implicit.
- Receiver side, per member: for every net creditor `c`, the total absorbed across all
  `receiver_credits` rows where `row.creditor == c` equals `net[c]` exactly, and the
  unabsorbed remainder of `c`'s incoming debts equals `out(c)`.
- No `payer_debts` row names a net creditor or a zero-net member as its debtor, and no
  `receiver_credits` row names a net debtor or a zero-net member as its creditor.
- **A debt may be split across two transfers.** The chain fixture above asserts exactly:
  `(bo, ali)` appears in the `payer_debts` of both transfers, for 600 and 400, with
  `debt_total` 1000 on both rows, and 600 + 400 equals the full 1000.
- **A debt may be absorbed by nothing.** In the pure cycle fixture no transfer exists, so
  all three debts are absorbed zero times. In the chain fixture `(ali, cass)` is absorbed
  zero times on the payer side and fully on the receiver side. Neither is an error, and
  no criterion requires every debt to be absorbed.
- **A transfer routinely exceeds every single debt it absorbs.** The three-member fixture
  above asserts a transfer of 600 whose four provenance rows are 300 each.

**Settling to zero, through task 4**

- Building one `SettlementEvent` per transfer with the transfer's payer, receiver and
  amount, appending each with a `CONFIRMED` decision event, and re-folding the whole log
  with `derive_balances` gives a `net` of exactly zero cents for every member. This is the
  closure property task 4's file said this task would lean on, and it is checked through
  the real fold rather than by re-implementing it.
- After that re-fold, `pairwise` is **not** required to be empty, and no test may assert
  that it is. Simplification converts a chain into a residual cycle: in the chain fixture
  the re-fold leaves `(bo, ali) 400`, `(ali, cass) 400` and `(cass, bo) 400`, three live
  debts that cancel to zero in `net`. This is the visible price of netting and it is
  correct.
- `simplify_debts` on the re-folded balances returns an empty plan. Zero net positions
  mean nothing left to suggest, which is what the balances screen shows the group.

**Arithmetic**

- Integer cents throughout. No `float()`, no `Decimal`, no `round()`.
- **No division of any kind appears in this module**, `/`, `//`, `%` and `divmod`
  included. The algorithm only compares, adds and subtracts, so no remainder can arise and
  no rounding rule may be invented here. Dividing a total across people is task 3's job
  and has already happened.
- Accumulate in plain `int` cents and wrap into `Money` once, when the result is built.
  `Money` has no `__radd__`, so `sum()` over `Money` values raises `TypeError`; that is a
  deliberate feature of task 2's type, not a gap to route around.
- No `MAX_CENTS` bound is applied. A plan is derived and never stored, following the same
  reasoning task 4 recorded for balances.

**Property tests**

- Over randomly generated ledgers from a seeded `random.Random`, folded through
  `derive_balances` so the two modules stay in step, every criterion above that is
  expressible as an invariant is asserted: the two transfer-count bounds, settle-to-zero
  on `net`, both per-transfer provenance sums, both per-debt bounds, both per-member
  totals, the sort orders, and the strictly positive amounts.
- Generated ledgers must include shapes that are easy to miss: an already settled group, a
  pure cycle, a single debtor against several creditors, several debtors against a single
  creditor, a member with a zero net sitting between two live debts, and a confirmed
  settlement larger than the debt it cleared, which task 4 documents as flipping a pair.
- Coverage is exhaustive where the domain is small enough to enumerate: every ledger
  formed by taking zero to three expenses from a fixed pool of six hand-written expenses
  over four members, asserting the same invariants on each.
- Determinism is tested, not assumed. Folding a shuffled event list and folding the sorted
  one give `Balances` values that produce `==` plans, and calling `simplify_debts` twice on
  one `Balances` gives `==` plans.
- Every assertion on cents is an exact integer comparison, never approximate.

**Suite**

- New tests live in `tests/test_simplify.py` and cover every criterion above, including
  each of the four worked fixtures by hand: the chain, the oversized transfer with a
  zero-net bystander, the pure cycle, and the five-member case where the greedy is not
  minimal.
- `uv run python -m pytest` passes, and all 939 tests already on `master` from tasks 1, 2,
  3, 4 and 6 keep passing unchanged.

## Out of scope

- **Minimising transfers exactly.** No subset-sum search, no branch and bound, no
  dynamic-programming partition, no "exact if the group is small enough" special case. The
  bound above is the contract. If a later task wants the true minimum for small groups, it
  can add it then, behind the same public shape, on its own merits.
- **An exact-match pre-pass** that cancels a debtor and a creditor holding equal amounts
  before running the greedy. It would shorten some plans, including the five-member fixture
  above, and it changes neither the worst case nor the stated bound. It also adds a second
  ordering rule to keep deterministic and a second code path to keep honest. One documented
  algorithm beats two, and the fixture that proves the greedy is not minimal is worth more
  than the transfers it would save.
- **Path provenance.** A transfer names the payer's own debts and the receiver's own
  credits. It does not reconstruct the chain of intermediate members between them, and it
  does not decompose the pairwise graph into paths. Two ends answer both questions the two
  humans involved actually ask; the middle of a four-hop chain is nobody's question.
- **Drilling from a pairwise debt to source expenses.** The `(debtor, creditor)` key is the
  handoff. Task 13 takes that key and queries the store for the expenses behind it. Do not
  put expense ids, descriptions or event references into `AbsorbedDebt`: that would guess
  at task 13's query shape and would drag the event log into a module that takes a single
  derived value.
- **Deriving balances.** This module takes a `Balances`. It does not accept events, does
  not call `derive_balances`, and does not know that settlement decisions exist. Tests may
  call `derive_balances` to build fixtures; the module may not.
- **Creating settlement events, marking as paid, or confirming.** Tasks 14 and 15. A
  `Transfer` is a suggestion with no id and no timestamp, and it must not grow either.
- **Partial settlement of a suggested transfer.** The spec cuts it explicitly: a suggested
  transfer is confirmed in full or not at all. Nothing here splits a transfer into
  instalments, and `AbsorbedDebt` is a record of what a transfer covers, not a schedule.
- **Storing, caching or memoising a plan**, including a lazy attribute on `TransferPlan` or
  on `Balances`. The spec's resolution to the netting-versus-audit-trail conflict is that
  everything is derived on read.
- **Rendering, display ordering, member names, and formatting.** Task 12 owns the balances
  screen and calls `format_amount` at the display edge. This module returns `Money`.
- **Convenience accessors** such as "the transfers this member pays", "the transfers this
  member receives", a plan total, or a per-member summary. Filtering a small tuple is one
  line in the caller, and every accessor added here is a shape task 12 has to live with.
- **Knowing the roster.** A member with no events is absent from `net` and absent from the
  plan. Tasks 9 and 12 own the member list, exactly as tasks 2 and 4 decided.
- **Validating that a member id names a real member of the group**, or that a payer is
  entitled to anything. Same reason.
- **Multi-currency, conversion, or a plan spanning two groups.** One `Balances` is one
  group in one currency, and a currency mismatch inside it is rejected rather than
  reconciled.
- **Corrections and voids.** Task 17 appends a new event type; it must be able to do so by
  extending task 4's fold, and this module must need no change when it does, because it
  reads only `Balances`.
- **Changing `Balances` or any task 2, 4 or 6 type.** If a criterion here seems to require
  a field added to `Balances`, a validator relaxed, or a private helper exported, stop and
  raise it.
- **Adding `hypothesis`, a type checker or a linter.** Tasks 3 and 4 already decided no, on
  the same reasoning.

## Constraints

- Files to create: `src/splitwise_lite/simplify.py` and `tests/test_simplify.py`.
  `src/splitwise_lite/__init__.py` may re-export the new public names, following the
  precedent tasks 2, 3, 4 and 6 set, but `__version__` must keep its current value because
  `tests/test_smoke.py` asserts it.
- **`src/splitwise_lite/balances.py`, `events.py`, `money.py`, `split.py` and `store.py`
  must not be modified.** Their types are consumed here, never reshaped. The same goes for
  `plans/backlog.md`, `plans/spec.md`, this file and `CLAUDE.md`.
- Public names: `AbsorbedDebt`, `Transfer`, `TransferPlan`, `InvalidBalances` and
  `simplify_debts`. Everything else in the module is private, underscore prefixed.
- Dependency direction stays one way. `simplify.py` imports `Balances` from `balances.py`,
  `GroupId` and `MemberId` from `events.py`, and `Currency`, `Money`, `CurrencyMismatch`
  and `DomainError` from `money.py`. None of those modules learns this one exists. Do
  **not** import `split.py` or `store.py`: nothing here divides a total and nothing here
  touches a database.
- Only public names are imported from the modules above. The underscore-prefixed helpers in
  `balances.py` are not part of its contract.
- **Standard library only, and no new dependency.** `dataclasses`, `collections.abc` and
  `typing` cover the module; `random`, `itertools` and `datetime` cover the tests. Per
  CLAUDE.md, any dependency would be declared in `pyproject.toml` and installed with
  `uv sync`, never `pip install` or `uv pip install`. If implementation genuinely needs a
  package, stop and get the user's approval before writing code.
- Python 3.12 target. `frozen=True, slots=True` on all three value types. Validation is
  eager, and there is no half-valid plan a later layer has to re-check.
- Integer cents everywhere and no float in this path, per the money rules in CLAUDE.md.
  Amounts are formatted only at the display edge, which is task 12, not here.
- No `hash()` of a string reaches any decision. String hashing is salted per process, so a
  plan that depended on it would differ between two readers of the same ledger. Sort every
  set and every dict view before iterating.
- The module docstring states, because tasks 12, 13 and 14 are written against it: the
  greedy algorithm and its `n - 1` bound, the explicit statement that the result is not a
  proven minimum, the ascending-id tie-break and why it is not task 3's rotation, the
  two-sided provenance contract with both sums, and the fact that a pairwise debt may be
  split across transfers or absorbed by none. Every public name gets a docstring naming the
  invariant it enforces.
- Tests use exact integer assertions, never approximate comparison, per
  `.claude/rules/testing.md`. No test is skipped or xfailed. Run them with
  `uv run python -m pytest`; plain `uv run pytest` fails on this machine with an
  access-denied spawn error.
