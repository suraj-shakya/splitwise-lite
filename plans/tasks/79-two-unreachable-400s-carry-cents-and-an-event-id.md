# Task 79: two unreachable 400s carry raw cents and an event id

GitHub issue **#79**, "Two unreachable 400s carry raw cents and an event id".
`plans/backlog.md` has no entry for it and this task does not add one: the issue is the
backlog entry and this file is the implementable version, on the precedent
`plans/tasks/61-no-4xx-body-carries-an-identifier.md` set.

**Depends on:** 39, 61 (issue #61, shipped as "No 4xx body carries an internal
identifier (#81)") and 82 (issue #82, shipped as "The unreachability claim gets checked,
and three of the fifty marks were false (#86)"). All three are on `master`. Assume every
one of them has landed: `tests/test_error_messages.py` holds `FOUR_HUNDRED_SITES` and
its two-way enumeration equality, `tests/conftest.py` holds the escape observer and the
per-test guard, and `tests/test_suite_integrity.py` holds
`CARRIED_UNANCHORED_BLOCKS` and `CARRIED_TOTAL`.

**Consumed by:** nothing. This closes the last two rows #61 declared rather than
reworded, so after it, no 4xx message in the package spells an amount as cents and none
names an event id.

---

## How the numbers in this file were obtained

**No Bash tool was available in the session that produced this spec.** Nothing below was
run under `pytest`, `uv`, `git` or a shell. Every count is a run of the ripgrep-backed
Grep tool with the pattern quoted beside it, or arithmetic over a file that was read, and
it is labelled which. Anything a run would be needed for is written as a criterion for
the implementer to run and record, never as a result.

Measured in the worktree `splitwise-lite-task-79` on 2026-09-08.

| What | How | Answer |
| --- | --- | --- |
| `raise AmountTooLarge(` in `src/` | Grep `raise AmountTooLarge\(` | 1, `store.py:352` |
| `raise CurrencyMismatch(` in `src/` | Grep `raise CurrencyMismatch\(` | 4: `money.py:154`, `balances.py:789`, `simplify.py:343`, `store.py:1231` |
| Marked rows of `FOUR_HUNDRED_SITES` | Grep `^    unreachable\(` over `tests/test_error_messages.py` | 47 |
| Driven rows | Grep `^    Site\(` over the same file | 59 |
| Rows in total | 47 + 59, arithmetic | 106 |
| `CARRIED_TOTAL` | read at `tests/test_suite_integrity.py:1118` | 107 |

The unanchored pattern `unreachable\(` reports **48** rather than 47, because it also
matches the helper's own `def unreachable(` line at `tests/test_error_messages.py:604`.
Measured here the same way, and it is the trap
`plans/tasks/82-the-unreachability-claim.md:36` records. The anchored patterns in the
table are the ones to measure with, and the first of them is the one
`tests/conftest.py:7` quotes in its own docstring.

**A cross-check of 107 by a second means, because this repo has shipped six wrong
counts.** Summing the per-module counts in `CARRIED_UNANCHORED_BLOCKS` by reading the
literal at `tests/test_suite_integrity.py:940` to `1114`: `test_accounts.py` 1,
`test_balances.py` 7, `test_groups.py` 27, `test_money.py` 2, `test_simplify.py` 8,
`test_split.py` 2, `test_store.py` 44, `test_suite_integrity.py` 1, `test_web_api.py` 13,
`test_web_shell.py` 2. That sums to 107 and agrees with the declared integer. Two
measurements by different means, one answer.

Other reads used below, each checkable by opening the line named:

- `src/splitwise_lite/store.py:340` defines `_require_storable_cents`; its `TypeError`
  is at `348` to `350` and its `AmountTooLarge` at `352` to `355`. Its three call sites
  are `1598` (`"allocation cents"`), `1599` (`"expense total_cents"`) and `1653`
  (`"settlement amount_cents"`).
- `src/splitwise_lite/store.py:218` defines `AmountTooLarge`, whose docstring summary
  line ends "naming both" and whose body says "this says the field and the bound".
- `src/splitwise_lite/balances.py:784` defines `_require_currency_match`; its raise is
  at `789` to `793`. It has four call sites and one raise: `221` and `224` in
  `derive_balances`, `463` and `466` in `debt_sources`, each passing `"expense"` or
  `"settlement"` as `label`.
- `src/splitwise_lite/money.py:45` sets `MAX_CENTS = 2**63 - 1`; `264` to `265` is
  `parse_amount`'s own `MAX_CENTS` refusal; `285` defines `format_amount`, which takes a
  `Money` and therefore a `Currency`; `140` to `150` is `Money.__post_init__`, which
  bounds nothing, so a `Money` above `MAX_CENTS` constructs.
- `src/splitwise_lite/web.py:464` maps `store.AmountTooLarge` to 400 and `510` maps it to
  `amount_too_large`. `money.CurrencyMismatch` is 400 `currency_mismatch`, pinned at
  `tests/test_web_api.py:1602`.
- `src/splitwise_lite/web.py:1674` and `2131` call `derive_balances` and `debt_sources`
  with `currency=group.currency`, the group row's own currency.
- `balances.InvalidLedger` is in neither error table: Grep `InvalidLedger` over
  `src/splitwise_lite/web.py` returns one hit, a docstring at `2103` saying it is
  unreachable from any request. So it is a 500 and `_GENERIC_500_MESSAGE` answers it.
- The two rows this task edits are at `tests/test_error_messages.py:836` to `843`
  (`balances.py`) and `1199` to `1206` (`store.py`).
- The five test blocks that read these two messages are
  `tests/test_store.py:655`, `674` and `1032`, and `tests/test_balances.py:351` and
  `1744`.

---

## The two messages, as they stand

**`store.AmountTooLarge`**, `src/splitwise_lite/store.py:352` to `355`:

```python
    if value > MAX_CENTS:
        raise AmountTooLarge(
            f"{field} is {value}, above MAX_CENTS ({MAX_CENTS}), the largest value the "
            f"cents column can hold"
        )
```

400 `amount_too_large`. Two figures, both integer cents: the offending value, and
`MAX_CENTS` itself, which renders as `9223372036854775807`.

**`balances.CurrencyMismatch`**, `src/splitwise_lite/balances.py:789` to `793`:

```python
    if event.currency != currency:
        raise CurrencyMismatch(
            f"cannot combine {event.currency.code} and {currency.code}: {label} "
            f"{event.id!r} is in {event.currency.code} and the ledger is in "
            f"{currency.code}"
        )
```

400 `currency_mismatch`. The class is `money.CurrencyMismatch`; `balances.py` imports it.
This is the one 4xx in the package that interpolates an event id.

---

## What this task supersedes, quoted

Two sentences in the committed tree say these messages stay as they are. Both were true
when written, and this task is what retracts them. They are quoted here rather than
edited in place, so a reader who greps for `AmountTooLarge` finds the retraction in the
same result set.

From `plans/tasks/61-no-4xx-body-carries-an-identifier.md:218` to `221`:

> `balances.CurrencyMismatch` names an event id at 400 and is unreachable because
> `spec.md` freezes a group's currency. `store.AmountTooLarge` names raw cents at 400 and
> is unreachable because `parse_amount` refuses above `MAX_CENTS` first; it is #39's
> recorded leftover and stays recorded.

and its Out of scope bullet:

> **`store.AmountTooLarge` and `balances.CurrencyMismatch`.** Criterion 44c. Declared
> with reasons, not edited.

From `plans/tasks/39-split-refusals-in-the-money-that-was-typed.md:467` to `471`:

> **`store.py`:** `AmountTooLarge` is mapped to 400 and reads
> `total_cents is 9223372036854775808, above MAX_CENTS (...)`, which is both defects at
> once. [...] **Leave alone; name it in the PR so the settlement tasks see it.**

Neither of those files is edited by this task. #61's sentence is a record of what #61
declined to do and stays true of #61; the live record of what these two messages say is
`FOUR_HUNDRED_SITES`, which this task updates, and `AmountTooLarge`'s own class
docstring, which this task updates.

**#39's "both defects at once" is half honoured and half declined, deliberately.** The
two defects it named are the cent figure and the Python attribute name `total_cents`.
This task removes the figures and keeps the field labels. The reason is that #61's own
resolution note, at `plans/tasks/61-no-4xx-body-carries-an-identifier.md:600` to `649`,
settled that lineage in favour of values over names: "where the name heuristic in this
criterion points at a key name rather than at a stored value, the heuristic is what is
wrong, and the enforcement mechanism defines the scope." A field label is a name; a cent
figure is a value. Renaming the three labels is recorded in Out of scope below with its
own argument, so nobody re-derives this as a fourth reading.

---

## Decision 1: `store.AmountTooLarge` drops both figures and formats neither

**The new message, exactly:**

```python
    if value > MAX_CENTS:
        raise AmountTooLarge(
            f"{field} is above MAX_CENTS, the largest value the cents column can hold"
        )
```

Rendered, exhaustively, since `field` has exactly three literal values at three call
sites:

- `expense total_cents is above MAX_CENTS, the largest value the cents column can hold`
- `allocation cents is above MAX_CENTS, the largest value the cents column can hold`
- `settlement amount_cents is above MAX_CENTS, the largest value the cents column can hold`

**Why not `format_amount`, which `money.py:288` calls "the only display edge" and which
`CLAUDE.md`'s Money section makes the only way an amount is spelled for a reader.**
`format_amount` takes a `Money`, and a `Money` takes a `Currency`.
`_require_storable_cents` receives an `int` and a `str` and has no currency, and the two
figures in the message are of two different kinds:

1. The offending value is an amount, and a currency for it does exist one frame up:
   `ExpenseEvent` and `SettlementEvent` both carry `currency`, so a `currency` keyword
   could be threaded through the three call sites. That is possible, and it is refused in
   the two paragraphs after this list.
2. `MAX_CENTS` is not an amount at all. It is a column bound, the same integer whatever
   currency the group is in, and `money.py:48` describes it as "the bound of a signed
   64-bit integer column". Rendering it through `format_amount` would attach a currency
   to a figure that has none, which is a false statement about the figure, and it renders
   as `92,233,720,368,547,758.07`, which helps no reader of any kind.

Formatting one figure and leaving the other as digits would leave raw cents in the
message, which is the defect. Formatting both means asserting that a column bound is an
amount in the group's currency. So the figure goes, which is exactly what #61 did to the
one integer left in `split._ordered_from_mapping`, and its Out of scope forbade both of
the alternatives being refused here again: "No `currency` on `_ordered_from_mapping`, no
second display helper in `split.py`, no cents-only variant of `format_amount`. The
integer is dropped, not rendered."

There is a second cost to threading a currency, worth stating because it is a layering
change rather than a line count: `store.py` imports `MAX_CENTS`, `Currency`,
`CurrencyMismatch` and `DomainError` from `money.py` today and imports neither `Money`
nor `format_amount`. Making the persistence layer a display edge, in order to render a
figure into a message no request can produce, is cost with no reader.

**Why `MAX_CENTS` stays in the message as a name.** It spells no digits, it is a public
name in `money.__all__` and is re-exported from the package root, and it is the one thing
that tells a reader where the bound is written down. The considered alternative,
`f"{field} is above the largest value the cents column can hold"`, drops it; it is
rejected because the sentence then names nothing a reader can look up, and the class
exists precisely so that a caller is not left with SQLite's `OverflowError`, which
"says nothing about which field was wrong".

**What is lost, stated.** The value distinguished two overflowing allocations from one
another; the field label cannot, because it is the same string for every allocation. That
loss is accepted on #61's grounds: a count is a third figure that has to stay true and an
ordinal is an ordering claim, and the only caller who can reach this holds the
allocations it passed in.

**The `TypeError` two lines above is untouched**, keeping `{field}`,
`{type(value).__name__}` and `{value!r}`. A wrong Python type is a programming error, it
becomes a generic 500 with a logged traceback, and its reader is a programmer reading
that traceback. That is #61's criterion 3 applied unchanged, and it is not being
re-litigated.

## Decision 2: `balances.CurrencyMismatch` drops the event id, and nothing replaces it

**The new message, exactly:**

```python
    if event.currency != currency:
        raise CurrencyMismatch(
            f"cannot combine {event.currency.code} and {currency.code}: one {label} "
            f"is in {event.currency.code} and the ledger is in {currency.code}"
        )
```

Rendered, for an NZD expense in an AUD ledger:

- `cannot combine NZD and AUD: one expense is in NZD and the ledger is in AUD`
- `cannot combine NZD and AUD: one settlement is in NZD and the ledger is in AUD`

**What identifies the offending event afterwards: nothing, and that is the answer.** The
`label` says which kind of event it was and the two codes say what the disagreement is.
Which of the events it was is no longer in the message. Four reasons that is acceptable
here, and the fourth is the one that decides it:

1. No request can produce this message, so no client is left unable to act. The
   currency the fold is given is `group.currency`, read from the group row
   (`web.py:1675` and `2136`), and every event stored in that group is forced into that
   currency twice over: `store._require_group_currency` refuses an event in any other
   one, and the schema makes an event's `(group_id, currency_code)` a composite foreign
   key into `groups (id, currency_code)`, so a raw `INSERT` is refused too
   (`store.py:1218` to `1224`).
2. The only caller who can produce it is inside the process, and it holds the event list
   it passed in. A pair of currency codes is a one-line filter over that list. This is
   #61's cardinality-many ruling, applied unchanged: "the caller holds both halves of
   the diff already".
3. A count or an ordinal is refused, for #61's reasons.
4. **A programmer who needs an event id in this module still gets one, from the guard
   next door, and this task must not touch it.** `balances._require_group`, at
   `balances.py:777` to `781`, interpolates `{event.id!r}` and raises `InvalidLedger`,
   which is in neither of `web.py`'s error tables and therefore becomes
   `_GENERIC_500_MESSAGE` with the real exception in the log. So `balances.py` keeps a
   refusal that names the event, in the one place where naming it costs nothing, and
   loses it in the one place where it is mapped to a 400.

**Why the "cannot combine X and Y" prefix stays**, redundant though it is with the second
half. Four sites in the package raise `money.CurrencyMismatch` and three of them open
with that clause (`money.py:155`, `balances.py:790`, `simplify.py:344`). The family reads
as a family, and `simplify._cents` is already id-free, so this edit makes the two
walk-level messages consistent rather than inventing a new shape.

**The considered alternative, `: {label} is in ...` without `one`**, matching
`simplify.py:344` exactly, is rejected on grammar: it renders "cannot combine NZD and
AUD: expense is in NZD". `one {label}` reads properly and is honest about cardinality,
which is the thing the id used to carry.

**The superstring hazard, which is live and is the way to get this wrong.**
`money.Money._require_same_currency` at `money.py:154` to `156` raises the same class
with the message `cannot combine NZD and AUD`, and that is a **prefix** of the new
balances message. So `match=r"^cannot combine NZD and AUD"` would be satisfied by either
guard, which is precisely the PR #62 collision `.claude/rules/testing.md` opens with. Any
pin on this wording spells the whole sentence. The criteria below require the `==` form.

## Decision 3: both stay unreachable, both stay in the package, neither is driven

The issue asks whether either is worth making reachable, "because an unreachable 400 is a
branch with no caller". **No to reachable, and no to deleting either branch.**

- Making `store.AmountTooLarge` reachable means weakening or bypassing
  `parse_amount`'s `MAX_CENTS` refusal, which is the one input edge every amount passes
  through. Making `balances.CurrencyMismatch` reachable means letting a group hold two
  currencies, which `plans/spec.md:25` locks ("One currency per group, fixed at
  creation"), `plans/spec.md:71` restates ("Group currency is immutable") and
  `plans/spec.md:119` cuts from v1. Neither is a change a rewording gets to make.
- Deleting either branch is worse than leaving it. `store._require_storable_cents` is the
  only thing between an in-process caller and an `OverflowError` from SQLite mid
  transaction, because `events.py` puts no upper bound on an amount; `AmountTooLarge`'s
  docstring says so. `balances._require_currency_match` is what makes folding two
  currencies a detected mistake rather than a silent addition of NZD cents to AUD cents,
  and `derive_balances`'s docstring promises "there is no partial answer over the events
  that happen to match". Both trade a named refusal for a wrong number.
- And the issue's worry is already answered by machinery that landed after it was filed.
  A 4xx raise with no caller is not invisible in this repo: it is a row of
  `FOUR_HUNDRED_SITES` carrying a written reason of at least `MIN_REASON` characters, and
  `tests/conftest.py` reds if a request is ever answered from it. A branch with no caller
  here is a recorded, policed branch rather than rot.

**So both rows stay `unreachable(...)`, and protecting that is a criterion rather than a
hope.** The enumeration equality at `tests/test_error_messages.py:2029` compares two sets
in both directions, so a reworded message with a stale row reds it. Two consequences an
engineer has to know:

1. The message edit and the row edit land in the same commit, or the suite is red.
2. **A stale row does not merely red one test; it also silently drops that row from the
   #86 guard's watch list.** `tests/conftest.py:269` builds its marked set from
   `table.MARKED`, keyed by `(module, function, skeleton)`, and `key_for_raise_site`
   returns the key the `ast` walk derives from the source. If the two skeletons disagree,
   the walked key is not in the marked set and the guard stops covering that raise. The
   enumeration equality is what stops that being silent, which is why it is not to be
   relaxed to make a diff smaller.

## Decision 4: what can be tested, and what any of it proves

Stated plainly, because a test that reaches past the request path is evidence about a
helper and not about any 4xx body a person will ever read.

**The wording is testable, and it does not need a contrived hook.** Both raises sit
behind public domain functions the suite already calls directly:

- `store.append_expense` and `store.append_settlement`, given an event built with
  `total_cents=MAX_CENTS + 1`, reach `_require_storable_cents`. `events.py` puts no upper
  bound on an amount and `Money` bounds nothing, so such an event constructs. Three tests
  do this today: `tests/test_store.py:655`, `674` and `1032`.
- `derive_balances` and `debt_sources`, given an event in another currency, reach
  `_require_currency_match`. Two tests do this today: `tests/test_balances.py:351` and
  `1744`.

So the new wording is pinned by five existing test blocks, upgraded from unanchored
substring assertions to whole-message equality. **What that proves and does not prove:**
it proves the sentence each helper composes. It proves nothing about any HTTP response,
because none of those five calls goes through Flask at all, `web._handle_error` never
sees them, and `tests/conftest.py` therefore records nothing for them. That is not a
weakness of the tests; it is the fact that makes the rows correct.

**The unreachability is not testable, and is checked in two directions rather than
argued.** The engineer writes no new prose argument and no new hand-rolled unreachability
test. The evidence is:

- **Negative direction, always on.** `tests/conftest.py`'s per-test guard
  (`no_marked_row_answers_a_request`, line `257`) reds when the exception raised at a
  marked row's site is the one `web._handle_error` turned into the response. It found
  three of the then fifty marks false on the run recorded in
  `plans/tasks/82-the-unreachability-claim.md:221` to `260`, and neither of these two rows
  was among the three (`store._require_name`, `web._signup` and
  `web._decide_settlement` were). So as of that run, over every request the suite makes,
  the guard says nothing about either of these rows. The engineer re-establishes that on
  this branch by running the chunks and recording the result, not by reading this
  paragraph.
- **Positive direction, for the store row only.** `FOUR_HUNDRED_SITES` already holds a
  **driven** row for `money.py::parse_amount`'s `"amount is too large to store: "`
  (`tests/test_error_messages.py:984` to `999`), whose driver is
  `POST /api/expenses` with `"amount": str(money.MAX_CENTS)` and whose expected code is
  `invalid_amount`. Together with
  `test_each_driven_row_answers_from_the_site_it_declares`
  (`tests/test_error_messages.py:2420`), that is a running check that an over-large amount
  on the expense route is answered from `parse_amount` and not from
  `store._require_storable_cents`. `tests/test_web_api.py:4755` is the same demonstration
  for the settlement route, at the response level.
- **No positive direction for the balances row, and that is not fixable here.** No
  request can build a two-currency ledger, so there is no request whose answer could show
  that something else refuses first. The mark is checked only in the negative. Say so;
  do not invent a test that appears to say more.

---

## Goal

Neither of the two 4xx messages #61 left declared rather than reworded spells an amount
as cents or names an event id: `store.AmountTooLarge` names the field and no figure, and
`balances.CurrencyMismatch` names the kind of event and the two currency codes and no id.
Both stay unreachable and both stay declared as such, with their rows in
`FOUR_HUNDRED_SITES` updated in the same commit so that the enumeration equality still
holds and the #86 guard still watches them; and the five test blocks that read those two
messages stop being unanchored substring assertions and become whole-message equalities,
which lowers `CARRIED_TOTAL` rather than raising it.

---

## Acceptance criteria

Each is a yes or no a QA agent can reach by reading a named file or running a named
command. `REPO` is the worktree root and every path is relative to it. A quoted string is
quoted exactly, including case, spacing and the absence of a trailing full stop.

### A. The two messages

1. `src/splitwise_lite/store.py`'s `_require_storable_cents` raises `AmountTooLarge` whose
   message is exactly
   `f"{field} is above MAX_CENTS, the largest value the cents column can hold"`.
   The digits `9223372036854775807` appear nowhere in the message, `{value}` is not
   interpolated into it, and `MAX_CENTS` is not interpolated into it: the name `MAX_CENTS`
   appears in the message as literal text only.
2. The three sentences that raise actually produces are, verbatim:
   * `expense total_cents is above MAX_CENTS, the largest value the cents column can hold`
   * `allocation cents is above MAX_CENTS, the largest value the cents column can hold`
   * `settlement amount_cents is above MAX_CENTS, the largest value the cents column can hold`
3. `_require_storable_cents`'s signature is unchanged: `def _require_storable_cents(value:
   object, field: str) -> int:`. It takes no `currency`. `src/splitwise_lite/store.py`
   imports neither `Money` nor `format_amount`, and Grep `format_amount` over
   `src/splitwise_lite/store.py` returns nothing.

   > **Resolution, 2026-09-08.** This criterion's last clause, "Grep `format_amount`
   > over `src/splitwise_lite/store.py` returns nothing", contradicts criterion 5 of
   > this same spec, which prescribes `AmountTooLarge`'s docstring verbatim, requires
   > that paragraph to name "`format_amount` as the only display edge", and labels the
   > text it gives with "This text satisfies it". That prescribed text contains
   > `format_amount`. There is no reading in which both criteria hold. The contradiction
   > is recorded here rather than in a PR body, on the precedent
   > `plans/tasks/61-no-4xx-body-carries-an-identifier.md:600`, which put its own
   > resolution in the spec "because it was re-derived once already, in the PR body for
   > #81, and a PR body is not what the next reader of this spec finds". It was recorded
   > in the PR body for this task first, which is exactly the mistake that note warns
   > about.
   >
   > **It is resolved in favour of criterion 5, and this criterion's substance is
   > unharmed.** The enforceable property is the clause immediately before the grep,
   > "imports neither `Money` nor `format_amount`", and that is how Out of scope states
   > the rule: "no `Money` or `format_amount` import in `store.py`". The grep is a
   > mis-stated proxy for it, because a docstring can name a function the module never
   > calls. Measured on the shipped tree: `src/splitwise_lite/store.py:76` reads
   > `from .money import MAX_CENTS, Currency, CurrencyMismatch, DomainError`,
   > byte-identical to `master`; no call to `format_amount` exists anywhere in the
   > module; and `grep -n format_amount src/splitwise_lite/store.py` returns **1** hit,
   > at line `229`, inside criterion 5's own prescribed prose. The comment beside the
   > raise was worded so as not to add a second occurrence. So read as a ban on the word
   > the clause is false on arrival; read as the import-and-call ban its neighbour
   > states, it holds.
4. The `TypeError` at `store.py:348` to `350` is byte-identical to `master`, keeping
   `{field}`, `{type(value).__name__}` and `{value!r}`. The three call sites at
   `store.py:1598`, `1599` and `1653` are byte-identical, so the three `field` labels and
   the order of the two checks in `append_expense` are unchanged.
5. `AmountTooLarge`'s class docstring no longer claims the message carries two figures.
   The phrase `naming both` and the phrase `this says the field and the bound` both appear
   nowhere in `src/splitwise_lite/store.py`, and the docstring carries one paragraph
   saying why no figure is spelled, naming `format_amount` as the only display edge and
   the absence of a currency at that point. This text satisfies it, and the summary line
   may be reflowed to fit the module's 88 column habit:

   ```python
   class AmountTooLarge(StoreError):
       """Raised when a cent value will not fit the signed 64-bit column, naming the field.

       ``events.py`` puts no upper bound on an amount, and ``parse_amount`` only guards the
       values that arrive as text, so an event built from cents directly can carry more
       than ``MAX_CENTS``. SQLite answers that with ``OverflowError``, which says nothing
       about which field was wrong; this says which field, and the append that raised it
       leaves no rows behind.

       It spells no figure. The offending value and ``MAX_CENTS`` are both integer cents,
       this module has no currency at the point the check runs, so there is no ``Money``
       to hand ``format_amount``, and ``MAX_CENTS`` is a column bound rather than an
       amount in anybody's currency. Issue #79 dropped both figures rather than inventing
       a second formatter, on the precedent ``split._ordered_from_mapping`` set for #61.
       The only caller who can reach this holds the value it passed in.
       """
   ```

   > **Resolution, 2026-09-08.** This criterion's clause "The phrase `naming both` and
   > the phrase `this says the field and the bound` both appear nowhere in
   > `src/splitwise_lite/store.py`" is half false in the commit that adds this file, and
   > the false half could not have been made true. Measured on the shipped tree,
   > `naming both` appears **3** times in that module, at lines `1232`, `1370` and
   > `1840`. An `ast` walk puts them in `_require_group_currency`, whose docstring says a
   > caller gets `CurrencyMismatch` "naming both codes"; `set_member_user`, about
   > `DuplicateRecord` naming both members; and `get_member_for_user`, about
   > `RecordNotFound` naming both ids. All three are true statements about other
   > exceptions and not one of them describes `AmountTooLarge`.
   >
   > **It is not merely unsatisfiable, it is compelled, and that is the decisive
   > point.** The occurrence at `store.py:1232` sits inside `_require_group_currency`,
   > which **criterion 11 of this spec requires to be byte-identical**, and Out of scope
   > says "This task edits exactly one of `store.py`'s rows". Satisfying this clause
   > literally would therefore breach criterion 11. Two criteria of one spec cannot both
   > hold, and the one naming a line range wins over the one generalising a grep.
   >
   > **Where the wrong claim came from, which is worth more than the symptom.** The
   > occurrence this spec had actually read is the one at what was then `store.py:218`,
   > quoted at line `63` above as a docstring summary "ending 'naming both'". The
   > criterion generalised that single read into a file-wide claim nobody ran. That is
   > this repo's counts-and-names-come-from-measurement scar one level up: a criterion
   > written in the shape of a grep result, without the grep.
   >
   > **The rest of the clause is implemented in full.** The prescribed docstring is
   > present verbatim, so the phrase is gone from the one place where it described this
   > message, and `grep -c "this says the field and the bound"
   > src/splitwise_lite/store.py` returns **0**, which is the other half of the clause
   > and is satisfied outright.
6. `src/splitwise_lite/balances.py`'s `_require_currency_match` raises `CurrencyMismatch`
   whose message is exactly
   `f"cannot combine {event.currency.code} and {currency.code}: one {label} is in {event.currency.code} and the ledger is in {currency.code}"`,
   however it is wrapped across lines. `event.id` is not interpolated into it. Grep
   `event\.id` over `src/splitwise_lite/balances.py` reports **5** hits on `master`, at
   lines `687`, `689`, `691`, `779` and `791`, and **4** after this task: the one at `791`
   is gone and the other four, which are the duplicate-id guard and `_require_group`, are
   untouched.
7. The two sentences that raise actually produces, for an NZD event in an AUD ledger, are
   verbatim:
   * `cannot combine NZD and AUD: one expense is in NZD and the ledger is in AUD`
   * `cannot combine NZD and AUD: one settlement is in NZD and the ledger is in AUD`
8. `_require_currency_match`'s signature is unchanged, its four call sites at
   `balances.py:221`, `224`, `463` and `466` are byte-identical, and its docstring or a
   comment beside the raise says in one line why no event id is named, pointing at #61's
   rule so the next person does not restore it while tidying.
9. Both messages open lower case and carry no trailing full stop, matching every other
   message in `money.py`, `split.py`, `store.py`, `balances.py`, `web.py` and `groups.py`.

### B. The five sibling refusals that must not move

10. `balances._require_group` at `balances.py:777` to `781` is byte-identical, still
    interpolating `{event.id!r}` and both group ids, and so is the duplicate-id guard at
    `balances.py:687` to `691`. Both are `InvalidLedger`, which is in neither error table,
    so both are 500s whose body is `_GENERIC_500_MESSAGE` and whose real message is
    logged. A "consistent tidy" that strips the id from either one removes the diagnostic
    a programmer has and changes no 4xx body.
11. `money.Money._require_same_currency` at `money.py:152` to `156`,
    `simplify._cents` at `simplify.py:342` to `346`, and
    `store._require_group_currency` at `store.py:1230` to `1234` are all byte-identical.
    The third of those names a **group id** at 400 and is one of `store.py`'s marked rows;
    it is not this issue's and is not edited.
12. `src/splitwise_lite/money.py`, `src/splitwise_lite/simplify.py`,
    `src/splitwise_lite/events.py`, `src/splitwise_lite/split.py`,
    `src/splitwise_lite/web.py`, `src/splitwise_lite/groups.py` and
    `src/splitwise_lite/accounts.py` are not edited. `git diff --name-only` names exactly
    two paths under `src/`: `store.py` and `balances.py`.
13. No row of `web.ERROR_STATUS` or `web.ERROR_CODE` changes, no exception class is added
    or removed, and the one JSON body shape is untouched. A reworded message is not a
    contract change; `web.py` says so itself. `test_web_api.py`'s error-table tests pass
    unedited, including the rows at `tests/test_web_api.py:1602` and `1605`.

### C. The table, and the enumeration equality that protects it

14. The `store.py` row of `FOUR_HUNDRED_SITES` (`tests/test_error_messages.py:1199` to
    `1206`) keeps `unreachable(`, keeps `"store.py"` and `"_require_storable_cents"`, and
    its skeleton becomes exactly:

    ```
    " is above MAX_CENTS, the largest value the cents column can hold"
    ```

    One leading space, no trailing space.
15. That row's `reason` is rewritten, because the sentence "a 400 naming raw cents,
    unreachable and left recorded rather than reworded" is false after this task. The new
    reason is at least `MIN_REASON` characters, says what would have to be true for a
    request to be answered from it, and makes no claim that the message still spells
    cents. This text satisfies it:

    ```
    "money.parse_amount refuses anything above MAX_CENTS at the input edge, so a request "
    "is answered from invalid_amount long before the column's own bound is consulted; "
    "reaching this needs a caller inside the process building an event from cents "
    "directly, which is what events.py puts no upper bound on"
    ```
16. The `balances.py` row (`tests/test_error_messages.py:836` to `843`) keeps
    `unreachable(`, keeps `"balances.py"` and `"_require_currency_match"`, keeps its
    existing `reason` unchanged, because that reason is still true, and its skeleton
    becomes exactly:

    ```
    "cannot combine  and : one  is in  and the ledger is in "
    ```

    Read that spacing off the source rather than by eye: two spaces after `combine`, one
    before and after the colon, two after `one`, two after `is in`, and one trailing
    space. It is the concatenation of the literal fragments with the interpolations
    removed, which is what `message_skeleton` produces, and it is invariant under where
    the f-string is wrapped.
17. `test_every_four_hundred_raise_site_is_declared` passes unedited. If it fails, the
    walk is the authority and its failure message prints both sides: the skeletons above
    are pasted, not retyped.
18. `test_every_site_no_request_reaches_says_what_would_have_to_be_true` passes unedited,
    which is what puts the `MIN_REASON` floor under criterion 15.
19. The anchored counts are unchanged: Grep `^    unreachable\(` over
    `tests/test_error_messages.py` still reports **47**, Grep `^    Site\(` still reports
    **59**, and the table still holds **106** rows with 106 distinct keys. No row moves
    between marked and driven, in either direction, and no row is added or deleted. This
    is the property the issue asks to be protected rather than relaxed: either message
    becoming reachable is a change to these counts and to
    `plans/tasks/82-the-unreachability-claim.md`'s figures, and it is not what this task
    does.
20. The only lines that change in `tests/test_error_messages.py` are those two rows' two
    skeletons and the one reason of criterion 15. `git diff` over that module shows no new
    test, no new helper, no new row, no deleted row and no docstring rewrite.

### D. The five test blocks, anchored rather than loosened

21. `tests/test_store.py::test_a_total_above_the_bound_is_rejected_naming_the_field` keeps
    its name, keeps `assert count(store, "expense_events") == 0` and
    `assert count(store, "expense_allocations") == 0`, and its message assertions become:

    ```python
    assert str(caught.value) == (
        "expense total_cents is above MAX_CENTS, the largest value the cents column "
        "can hold"
    )
    assert str(MAX_CENTS) not in str(caught.value)
    ```

    The `==` is the pin; the negative is documentation of the defect that was removed. The
    old `assert str(MAX_CENTS) in str(caught.value)` is gone, because it is now false.

    > **Resolution, 2026-09-08.** This criterion gives the block's message assertions as
    > exactly two, which drops the pre-existing
    > `assert "total_cents" in str(caught.value)`, an assertion the new wording leaves
    > true. Criterion 26 says of the same five blocks that they "each keep every
    > assertion that is still true". Read literally the two cannot both hold for the
    > three `tests/test_store.py` blocks.
    >
    > **It is resolved in favour of this criterion, which supplies literal code, and
    > nothing is weaker for it.** The whole-message `==` contains the dropped substring
    > and so implies it. That was checked against the sentences the helper actually
    > produces rather than inferred: `total_cents` is a substring of the expense
    > sentence, `cents` of the allocation sentence and `amount_cents` of the settlement
    > sentence, so each dropped assertion is entailed by the pin that replaced it.
    > `.claude/rules/testing.md` settles the general case the same way: "Once one anchor
    > has established which guard raised, every fragment assertion beside it stops being
    > a pin and becomes documentation, and none of them has to change." Criterion 32's
    > own account of these three blocks names only the `str(MAX_CENTS) in` assertion,
    > which is consistent with this reading.
    >
    > **The inconsistency is this spec's, not the diff's, and it is left visible rather
    > than tidied.** This criterion drops the still-true fragment from the three store
    > blocks, while criteria 23 and 24 explicitly keep the still-true `"AUD"` and `"NZD"`
    > fragments in the two balances blocks. Both shapes are anchored by their `==` and
    > neither is weaker, so the shipped diff follows each criterion as written and the
    > two read differently. Do not tidy one to match the other on the strength of the
    > diff alone. One thing to know while reading them: the negative this criterion puts
    > in place of the dropped positive, `str(MAX_CENTS) not in`, is what
    > `.claude/rules/testing.md` calls "weaker still rather than safer", because any
    > message lacking the string satisfies it. With the `==` as the block's anchor both
    > are documentation and that costs nothing; without one it would matter.
22. `tests/test_store.py::test_an_allocation_above_the_bound_is_rejected_naming_the_field`
    and `tests/test_store.py::test_a_settlement_amount_above_the_bound_is_rejected` take
    the same shape, keep their names and their `count(...) == 0` assertions, and pin
    `allocation cents is above MAX_CENTS, the largest value the cents column can hold`
    and
    `settlement amount_cents is above MAX_CENTS, the largest value the cents column can hold`
    respectively. Both keep `str(MAX_CENTS) not in str(caught.value)`.
23. `tests/test_balances.py::test_a_foreign_currency_raises_currency_mismatch_naming_both_codes`
    keeps its name, keeps `assert "AUD" in message` and `assert "NZD" in message`, and
    gains, above them:

    ```python
    assert message == (
        "cannot combine NZD and AUD: one expense is in NZD and the ledger is in AUD"
    )
    assert "e1" not in message
    ```

    `message = str(raised.value)` already binds the local, and
    `tests/test_suite_integrity.py`'s `region_is_anchored` follows one level of local
    binding (`message_locals`, line `735`), so this form anchors the block.
24. `tests/test_balances.py::test_a_foreign_currency_raises_currency_mismatch_for_a_walk_too`
    takes the same shape against the same sentence, keeps its name and its two `in`
    assertions, and gains the same `==` and `"e1" not in` pair. It exercises
    `debt_sources` through the module's `sources()` helper at `tests/test_balances.py:1366`
    rather than `derive_balances`, and it keeps doing so: the two tests differ in which
    call site reaches the one raise, and that is why there are two.
25. **No pin in this diff is a prefix another live guard can satisfy.** Every message
    assertion this task adds is either a whole-message `==` or a negative beside one. In
    particular no `match=` and no `startswith` pattern stops at
    `cannot combine NZD and AUD`, which `money.Money._require_same_currency` produces in
    full. Grep the diff for `match=` and confirm it adds none.
26. No test in the suite is renamed, deleted, reordered, skipped or xfailed, and no
    parameter list loses a case. Nothing in this task's diff makes an existing assertion
    weaker: the five blocks each keep every assertion that is still true and gain a
    stronger one.

### E. The carried baseline shrinks, and by exactly five

27. `tests/test_suite_integrity.py`'s `CARRIED_UNANCHORED_BLOCKS` entry for
    `tests/test_store.py` loses exactly these three pairs, each count 1:
    `("test_a_settlement_amount_above_the_bound_is_rejected", 1)`,
    `("test_a_total_above_the_bound_is_rejected_naming_the_field", 1)`,
    `("test_an_allocation_above_the_bound_is_rejected_naming_the_field", 1)`.
    The entry keeps its reason and keeps every other pair.
28. The entry for `tests/test_balances.py` loses exactly these two pairs, each count 1:
    `("test_a_foreign_currency_raises_currency_mismatch_for_a_walk_too", 1)`,
    `("test_a_foreign_currency_raises_currency_mismatch_naming_both_codes", 1)`.
    The entry keeps its reason and keeps its other five pairs.
29. `CARRIED_TOTAL` is set to whatever `test_every_message_block_is_anchored_or_carried`
    prints in its paste-back, and to nothing else. It is **lower** than the 107 it reads
    today at `tests/test_suite_integrity.py:1118`. **Predicted 102**, and that figure is
    arithmetic over the five pairs named above rather than a measurement, so it is
    reconciled against the check's own output and the check wins. It is never higher: the
    baseline only ever shrinks, and this is the diff a reviewer reads to confirm that.
30. `test_the_carried_total_is_the_sum_of_the_baseline`,
    `test_every_carried_module_names_the_slice_that_retires_it` and
    `test_every_message_block_is_anchored_or_carried` all pass, unedited. Both entries
    still hold blocks, so neither entry is deleted and both reasons still name their
    retiring slice.
31. Nothing else in `tests/test_suite_integrity.py` changes. In particular the two
    literals `108` and `106` at lines `1242`, `1251`, `1253` and `1257` are arguments
    passed into `carried_baseline_message` by its own self-test and are independent of
    `CARRIED_TOTAL`, so they are left alone.
32. **The three blocks in `tests/test_store.py` had to change and the two in
    `tests/test_balances.py` did not, and the diff says which.** The three assert
    `str(MAX_CENTS) in str(caught.value)`, which the new wording falsifies; the two assert
    only `"AUD"` and `"NZD"`, which the new wording keeps, so they would have stayed green
    unedited. They are anchored anyway, because this task's subject is that exact wording
    and an unanchored block is not a pin on it. The PR body states this distinction, so
    nobody reads the balances edits as forced.

### F. What the #86 guard says about these two rows, run and recorded

33. Every module under `tests/` is run, in chunks, with `tests/conftest.py`'s guard in
    place and unmodified, so the guard sees every request the suite makes. The command per
    chunk is `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest <module> -q`. The PR body
    records the module, the command and the pass, fail, skip and xfail figures for each of
    these six, which are the chunks that make requests or read the table:
    `tests/test_error_messages.py`, `tests/test_web_api.py`, `tests/test_store.py`,
    `tests/test_balances.py`, `tests/test_suite_integrity.py`, `tests/test_end_to_end.py`.
34. The guard reports neither of these two rows in any chunk. That is recorded as exactly
    what it is: **no request this suite makes is answered from either raise.** It is not
    recorded as proof of unreachability, and no sentence in the diff or the PR body calls
    it one. `tests/conftest.py:57` to `62` already states that limit, including that a
    partial run can produce a false pass and never a false failure, and this task does not
    restate it anywhere.
35. **The engineer writes no new unreachability argument.** The two rows' `reason` fields
    are the only place either claim is made in prose, criterion 15 is the only reason
    text that changes, and no new test, comment or docstring in this diff asserts that a
    request cannot reach either site. Where the check can say it, the check says it.
36. `test_each_driven_row_answers_from_the_site_it_declares` passes unedited, which is
    the positive-direction evidence for the store row: the `POST /api/expenses` driver
    carrying `str(money.MAX_CENTS)` is still answered from `money.py::parse_amount`.
    `tests/test_web_api.py:4755`'s test and its comment naming the store's bound "an
    unreachable backstop on this path" pass and stay true, unedited.
37. The PR body states plainly that the balances row has no positive-direction check and
    why: no request can build a two-currency ledger, so there is no request whose answer
    could show something refusing first.

### G. The positive control, run and recorded

38. `plans/mutations/79-two-unreachable-400s.md` exists and holds records in the
    seven-key JSON format `plans/mutations/README.md` specifies, so
    `tests/test_suite_integrity.py`'s machine-readability checks pass over it.
39. One record restores the two interpolations in `store.py`'s message, so that its
    `replace` is exactly what `master` reads:

    ```python
            f"{field} is {value}, above MAX_CENTS ({MAX_CENTS}), the largest value the "
            f"cents column can hold"
    ```

    Its `kills` list holds all four of these node ids and `result` is `"killed"`:
    * `tests/test_store.py::test_a_total_above_the_bound_is_rejected_naming_the_field`
    * `tests/test_store.py::test_an_allocation_above_the_bound_is_rejected_naming_the_field`
    * `tests/test_store.py::test_a_settlement_amount_above_the_bound_is_rejected`
    * `tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared`
40. One record restores `{event.id!r}` in `balances.py`'s message. Its `kills` list holds
    all three of these and `result` is `"killed"`:
    * `tests/test_balances.py::test_a_foreign_currency_raises_currency_mismatch_naming_both_codes`
    * `tests/test_balances.py::test_a_foreign_currency_raises_currency_mismatch_for_a_walk_too`
    * `tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared`
41. One record is a named control that must **survive**, so the new pins are shown not to
    red at everything: reword the `store.py` row's `reason` text, keeping it at or above
    `MIN_REASON` characters, which changes no behaviour, no message and no skeleton, and
    so must red nothing. Its `result` is `"survived"`, its `kills` is
    empty, and its `survives` names the five anchored node ids of criteria 39 and 40 plus
    `test_every_four_hundred_raise_site_is_declared`. One test does read the `reason`,
    `test_every_site_no_request_reaches_says_what_would_have_to_be_true`, but only its
    length, which is why the reword stays above `MIN_REASON`. A `"killed"` here would mean
    something pins a reason's wording, and that would be its own finding to report.
42. `kills` and `survives` hold pytest node ids, never `name: count`. Every `find` string
    is verified to match **exactly once** before the run, using the assertion in the
    recipe at `plans/mutations/README.md:56` to `65`. Every run sets
    `PYTHONDONTWRITEBYTECODE=1`. The working tree is committed before any mutation is
    applied, and reverting is `git checkout --` against the one named file.
43. **Without criteria 39 and 40 there is no evidence the five new pins bite**, because
    every one of them replaces an assertion that was already green. That is why the
    mutation records are criteria and not a suggestion.

### H. Nothing else moves

44. No file under `app/` is read for editing, edited, added or removed. `VERSION` and
    `SHELL_DIGEST` in `app/sw.js` are unchanged and
    `test_the_recorded_digest_matches_the_files_it_covers` passes unedited. No server
    sentence this task rewords reaches any screen: the add screen prints
    `error.message` for the codes it can receive, and neither `amount_too_large` nor
    `currency_mismatch` can arrive.
45. `CLAUDE.md`, `README.md`, `plans/spec.md`, `plans/backlog.md` and
    `.claude/rules/testing.md` are not edited. No capability is added or removed, so no
    bullet in either pinned list in `tests/test_web_shell.py` moves.
46. `plans/tasks/39-split-refusals-in-the-money-that-was-typed.md`,
    `plans/tasks/61-no-4xx-body-carries-an-identifier.md` and
    `plans/tasks/82-the-unreachability-claim.md` are not edited. What they say about these
    two messages is quoted and retracted in this file, which is the committed record.
47. `pyproject.toml` and `uv.lock` are byte-identical. No dependency is added to either
    group, in either language. `tests/shell_harness.mjs` is untouched and
    `tests/test_shell_behaviour.py`'s `SCENARIOS` gains nothing.
48. The paths this task may create or change are exactly these **eight**, and
    `git diff --name-status $(git merge-base master HEAD)..HEAD` reports these eight and
    nothing else:
    `src/splitwise_lite/store.py`, `src/splitwise_lite/balances.py`,
    `tests/test_store.py`, `tests/test_balances.py`,
    `tests/test_error_messages.py`, `tests/test_suite_integrity.py`,
    `plans/mutations/79-two-unreachable-400s.md`, and this file. **Two are created**, the
    mutation record and this spec, because this spec arrives in the working tree untracked
    and the commit that carries it records it as `A`. None is deleted, so the report is
    2 `A`, 6 `M`, 0 `D`. The created count is stated here rather than left implicit
    because criterion 46 of `plans/tasks/61-no-4xx-body-carries-an-identifier.md` got
    exactly this wrong by forgetting its own spec file.
49. **The collected count does not move.** No test function is added or removed and no
    test file is created, so `tests/test_suite_integrity.py`'s `TEST_SOURCES`, derived
    from the filesystem at line `72`, is unchanged and the two checks parametrised over it
    gain no case. The engineer records the count from
    `uv run python -m pytest --collect-only -q` before and after and states that it is
    identical. No number for it is written in this spec, because none was measured here.
50. Across the chunked runs plus CI: **0 failed, 0 skipped, 0 xfailed.** Both CI legs,
    `ubuntu-latest` and `windows-latest`, are green on a branch brought up to date with
    `master`, and the PR body links that run.

### I. Browser

51. No criterion in this task needs a browser. Both messages are unreachable from the
    shipped shell, every criterion above is decidable from a Python run or from reading a
    named file, and there is nothing to click. If review adds a criterion that needs one,
    it is marked **NOT RUN**, no verdict depends on it, and recording an unrun check as
    "pass" is a FAIL.

---

## Out of scope

* **Making either message reachable.** Refused above, on three grounds. It would mean
  weakening `parse_amount`'s input edge or letting a group hold two currencies, which
  `plans/spec.md` locks in three places.
* **Deleting either raise.** Refused above. Both are the last thing between an in-process
  caller and either an `OverflowError` mid transaction or a silent addition of two
  currencies' cents.
* **Driving either row.** No row of `FOUR_HUNDRED_SITES` moves from `unreachable(...)` to
  a `Drive`, in either direction, and the anchored counts stay at 47 and 59. A driver
  would have to be a request, and there is none.
* **Formatting either figure.** No `currency` parameter on `_require_storable_cents`, no
  `Money` or `format_amount` import in `store.py`, no second display helper and no
  cents-only variant of `format_amount`. The figures are dropped, not rendered. This is
  #61's ruling on `split._ordered_from_mapping`, applied unchanged.
* **A count, an ordinal or a "which one" figure** in either message. A count is a third
  figure that has to stay true and an ordinal into an event list is an ordering claim the
  caller did not make.
* **Renaming the three `field` labels** `"allocation cents"`, `"expense total_cents"` and
  `"settlement amount_cents"` to public wire words. This is the half of #39's "both
  defects at once" that this task declines, and it is recorded here rather than left to a
  fourth reading. Three reasons. #61's resolution note settled this lineage in favour of
  values over names, and a field label is a name. The label feeds both the `AmountTooLarge`
  message and the `TypeError` two lines above it, whose reader really is a programmer
  reading a traceback and for whom the attribute name is the diagnostic, so renaming it
  makes the 500 worse to serve a 400 nobody can receive; giving the helper two labels
  instead is a second vocabulary to keep in step for one unreachable sentence. And the
  message would then name `MAX_CENTS`, a Python constant, next to public words, which is
  a half-measure rather than a rule. If somebody wants it, it is a naming task of its own
  and the PR body is where to record the ask.
* **`balances._require_group`, `money.Money._require_same_currency`, `simplify._cents`
  and `store._require_group_currency`.** Named in criteria 10 and 11 as byte-identical.
  The first is a 500 and keeps its event id; the last names a group id at 400 and is one
  of `store.py`'s marked rows, declared by #61 and not reopened here.
* **`store.py`'s other 4xx messages.** `RecordNotFound`, `DuplicateRecord` and
  `_require_group_currency`'s `CurrencyMismatch` all name ids and are all declared with
  reasons. This task edits exactly one of `store.py`'s rows.
  `plans/tasks/82-the-unreachability-claim.md:54` to `58` puts `store.py`'s marked rows at
  28 as re-measured on 2026-09-08; that figure is quoted from there and was not measured
  in this session, and it is not a criterion. Confirm it, if it matters, by importing
  `FOUR_HUNDRED_SITES` and counting `MARKED` by module.
* **Anything under `app/`.** No file edited, no `VERSION` bump, no `SHELL_DIGEST`
  recompute. Neither code this task touches can reach a screen.
* **Any change to the error contract.** No new status, no new code, no new exception
  class, no row moved in `ERROR_STATUS` or `ERROR_CODE`, no change to the one JSON body
  shape.
* **The rest of issue #70's audit.** This task anchors five of the 107 carried blocks and
  lowers `CARRIED_TOTAL` by five. It does not anchor any other block, does not touch
  `.claude/rules/testing.md`, and does not do slices 70b to 70h's work: slices 70c, 70g
  and 70h simply inherit five fewer blocks. Their reasons in
  `CARRIED_UNANCHORED_BLOCKS` are unchanged.
* **Extending `tests/conftest.py`'s guard.** It already covers these two rows and its
  reach is already stated where the predicate is. Nothing in this task changes the
  observer, the predicate or what either claims.
* **A static scan for cents or for identifiers over `src/`.** Refused by #61 for reasons
  that have not changed: it cannot tell a field name from a value, and a denylist is a
  premise living outside the check.
* **`_require_storable_cents`'s missing lower bound.** It refuses `value > MAX_CENTS` and
  nothing below zero, and a large negative int still fits the column. Not this issue's,
  and not fixed here.
* **Multi-currency, partial settlements, member departure** and everything else
  `plans/spec.md` cuts from v1.

---

## Constraints

* **Paths changed: exactly eight**, per criterion 48, two of them created. Nothing else,
  in either direction.
* **The domain layer stays framework free.** Neither `store.py` nor `balances.py` gains
  an import of any kind, `store.py` in particular gaining neither `Money` nor
  `format_amount`. `test_importing_the_package_does_not_import_the_framework`,
  `test_no_module_in_the_package_imports_the_web_layer` and
  `test_only_the_web_module_imports_the_framework` pass unedited.
* **Money is integer cents; `format_amount` is the only display edge.** No float, no
  `round`, no true division, no `Decimal` in this diff.
  `test_the_module_does_no_floating_point_arithmetic` over `store.py` passes unedited.
  Both figures are dropped rather than divided, formatted or rendered anywhere.
* **The message edit and its table row land in the same commit.** A reworded message with
  a stale skeleton reds the enumeration equality and, worse, silently drops that row from
  the #86 guard's watch list. Do not split them across commits and do not push the first
  half to see what CI says.
* **Whole-message equality, never a prefix.** `pytest.raises(match=)` is an `re.search`
  and `assert "x" in str(exc.value)` is the same operation.
  `money.Money._require_same_currency` produces `cannot combine NZD and AUD` in full,
  which is a prefix of the new balances sentence, so a pin that stops there is satisfied
  by the wrong guard. Every pin this task adds is `==` against the whole message. Read
  `.claude/rules/testing.md`'s first rule before writing one.
* **The carried baseline is pasted, not calculated.** `CARRIED_TOTAL` and both entries
  come from what `test_every_message_block_is_anchored_or_carried` prints. The 102 in
  criterion 29 is a prediction to reconcile against that output, and if the two disagree
  the check is right.
* **`CARRIED_UNANCHORED_BLOCKS`'s two entries are contended.** Issue #70's slices 70c,
  70g and 70h are declared, in those same entries, as the work that retires them, and
  other worktrees may be in flight against the same literal. Bring the branch up to date
  with `master` and re-run the check before the PR goes up, per `CLAUDE.md`: a paste-back
  computed against an older `master` says nothing about the merge commit. If a slice has
  already anchored one of the five blocks, that block's baseline pair is already gone and
  only its message assertion changes here.
* **A mutation claimed as evidence is recorded as an anchor and a replacement**, in
  `plans/mutations/79-two-unreachable-400s.md`, in the README's seven-key format, never as
  a sentence. Commit first, then mutate: a revert discards uncommitted work. Every run
  sets `PYTHONDONTWRITEBYTECODE=1`.
* **Do not run the whole suite in one command.** Chunk by module, per criterion 33, and
  let `.github/workflows/tests.yml` be the one place a full green run is claimed. The test
  command is `uv run python -m pytest`; plain `uv run pytest` fails on this machine with
  an access-denied spawn error. Collected counts come from `--collect-only -q`.
* **No `skip` and no `xfail`,** anywhere, under any condition.
* **Check names before using them.** Every test name in this diff already exists, because
  no test is added or renamed; confirm that with a Grep before the PR goes up, and run
  `tests/test_suite_integrity.py` over `tests/` to catch a duplicate definition.
* **Every number in the PR body is one somebody ran**, with the command beside it. This
  project has shipped six wrong counts, every one from an eyeballed measurement.
* **Python 3.12 target.** A one-line comment where a non-obvious choice is implemented, so
  the next person does not undo it by tidying: why the two figures are dropped rather than
  formatted, and why `_require_currency_match` names no event id while `_require_group`,
  the function immediately above it in the same file, does.
* **Punctuation matches the family:** lower-case opening, no trailing full stop.

---

## Size

An estimate, and labelled as one.

Small in `src/`: two message edits removing three interpolations between them,
`{value}` and `{MAX_CENTS}` from one and `{event.id!r}` from the other, plus one class
docstring paragraph and one comment. Perhaps fifteen lines replaced across two files, no
function added, no signature changed.

Most of the diff is five test blocks, two table skeletons, one reason string, five pairs
out of one baseline literal, one declared integer, and one mutation record with three
entries.

If this task grows a new exception class, a new error code, a `currency` parameter, a
second formatter, an import in `store.py`, a new test module, an edit under `app/`, a new
row in `FOUR_HUNDRED_SITES`, or a `CARRIED_TOTAL` higher than 107, it has gone wrong.
