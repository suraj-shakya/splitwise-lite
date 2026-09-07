# Task 16, the incompleteness signal: recorded mutations

GitHub issue #17. Every check this task adds has been made to go red, and this file is
where that is recorded as something the next person can re-run rather than as a
sentence they would have to reconstruct. `plans/mutations/README.md` states the format
and the recipe; every run below used it, from the record's own `find` and `replace`,
with `PYTHONDONTWRITEBYTECODE=1` set and `git checkout -- <file>` between runs.

**How to read the figures.** This is part of the preamble rather than a section of
its own, because `tests/test_suite_integrity.py` refuses a `##` section carrying no
fenced JSON block: a section here records a mutation or it is not a section. That
rule fired on the first draft of this file and it was right to.

Each figure below is a **whole-module, unfiltered** `N failed, M passed` line, quoted
as pytest printed it. Not a filtered count: a filtered count is reproducible only by
somebody who guesses the same `-k`, and the whole-module line is the one a later reader
can reproduce from this record alone.

**The quantity is named every time, and the two quantities are different.** "Killed 1 of
the 58 tests in `tests/test_staleness.py`" and "survived all 490 in
`tests/test_web_api.py`" are two measurements of one mutation, and each claim below says
which mutation it is about and which module it was measured in. A correct number
attached to the wrong mutation is the defect this discipline exists to prevent.

The two modules, on the branch with every mutation reverted:

* `tests/test_staleness.py`: **58 tests**, the domain checks this task adds.
* `tests/test_web_api.py`: **490 tests**, of which 15 are this task's endpoint checks.

**The standing finding, stated once here because it is true of four of the five
mutations below.** The endpoint module survives almost everything. That is not a gap in
it: `web.py` stamps `created_at` from its own single clock read and the endpoint tests
drive real requests, so a future timestamp is unreachable from there, and no endpoint
test sits on the exact threshold. The endpoint checks are evidence that the wire carries
the right shape at one instant, and the domain checks are the evidence that the figures
are right. Neither substitutes for the other, and this file is what says so with
measurements instead of confidence.

## Mutation 1: the clamp at zero deleted

A future `created_at` yields a negative day count. `web.py` should make this
unreachable, but `store.py` deliberately accepts timestamps that disagree, because
phone clocks disagree, and a hand-edited database or a future `setup_group.py` run
reaches it.

```json
{
  "id": "clamp-deleted",
  "file": "src/splitwise_lite/staleness.py",
  "find": "    days = elapsed if elapsed > 0 else 0",
  "replace": "    days = elapsed",
  "kills": ["tests/test_staleness.py::test_a_future_expense_reads_as_zero_days_and_never_as_a_negative"],
  "survives": ["tests/test_web_api.py::test_both_reads_send_the_identical_staleness_object_for_one_ledger"],
  "result": "killed"
}
```

Measured: `tests/test_staleness.py` reported **`1 failed, 57 passed`**, so mutation 1 is
killed by 1 of that module's 58 tests. `tests/test_web_api.py` reported **`490 passed`**:
mutation 1 survives every one of the 490 endpoint tests, for the reason in the standing
finding above.

**What actually killed it is worth recording, because it is not what the test asserts.**
The named test asserts the figure is `0`; what it met was
`TypeError: Staleness days_since_last_expense must be zero or positive, got -1`, raised
by the result type's own guard before the assertion was reached. So the clamp is
guarded twice, once in the arithmetic and once in the type, and this mutation removes
only the first. It is still `killed` rather than `killed-for-the-wrong-reason`: the
deleted clamp is the cause, and the test that names the clamp is the test that went red.

## Mutation 2: the threshold comparison weakened from `>=` to `>`

The boundary criterion says that at exactly `quiet_after_days` days and zero
microseconds the state is `STALE`. This makes it `FRESH`, so the signal appears a day
late.

```json
{
  "id": "threshold-weakened-to-strictly-greater",
  "file": "src/splitwise_lite/staleness.py",
  "find": "    state = StalenessState.STALE if days >= window else StalenessState.FRESH",
  "replace": "    state = StalenessState.STALE if days > window else StalenessState.FRESH",
  "kills": [
    "tests/test_staleness.py::test_exactly_the_threshold_elapsed_is_stale_and_a_microsecond_less_is_fresh",
    "tests/test_staleness.py::test_the_state_is_stale_at_or_above_the_threshold_and_fresh_below_it"
  ],
  "survives": ["tests/test_web_api.py::test_the_state_is_one_of_three_wire_words_and_never_the_enum_value"],
  "result": "killed"
}
```

Measured: `tests/test_staleness.py` reported **`2 failed, 56 passed`**, so mutation 2 is
killed by 2 of that module's 58 tests, and both of them are the boundary tests written
for it. `tests/test_web_api.py` reported **`490 passed`**: mutation 2 survives all 490,
because no endpoint test sits on the boundary. The boundary is a domain-level claim and
only the domain module measures it.

## Mutation 3: the member-age condition deleted

Every member with no recent entry is named as quiet, including one whose row was
created yesterday. This is issue #44's shape at the level of the list: an absence of
data reported as a finding.

```json
{
  "id": "member-age-condition-deleted",
  "file": "src/splitwise_lite/staleness.py",
  "find": "        and _elapsed_days(moment, created_at) >= window",
  "replace": "",
  "kills": [
    "tests/test_staleness.py::test_a_member_who_joined_inside_the_window_is_not_named",
    "tests/test_staleness.py::test_a_group_set_up_inside_the_window_names_nobody_at_all",
    "tests/test_staleness.py::test_a_member_created_exactly_the_window_ago_is_quiet_and_later_is_not",
    "tests/test_web_api.py::test_a_roster_younger_than_the_window_names_nobody_as_quiet"
  ],
  "survives": ["tests/test_staleness.py::test_a_ledger_with_no_expense_at_all_is_never_whatever_the_roster_holds"],
  "result": "killed"
}
```

Measured: `tests/test_staleness.py` reported **`3 failed, 55 passed`** and
`tests/test_web_api.py` reported **`1 failed, 489 passed`**. So mutation 3 is killed by
3 of the 58 domain tests **and** by 1 of the 490 endpoint tests, which makes it the only
mutation in this file that both modules catch. That is the one condition whose absence
is visible through a real request, because a group seeded and read inside the window is
an ordinary state of the product rather than a hand-made instant.

## Mutation 4: the quiet list computed from `payer_id` rather than `created_by`

The list stops being about who has entered anything and becomes about who has paid for
anything, which is a different question and answers a different risk. The spec's risk is
that nothing gets recorded.

```json
{
  "id": "quiet-by-payer-not-recorder",
  "file": "src/splitwise_lite/staleness.py",
  "find": "        expense.created_by",
  "replace": "        expense.payer_id",
  "kills": ["tests/test_staleness.py::test_a_member_who_paid_but_did_not_enter_it_is_still_listed_as_quiet"],
  "survives": ["tests/test_web_api.py::test_the_balances_read_names_who_has_entered_nothing_in_roster_order"],
  "result": "killed"
}
```

Measured: `tests/test_staleness.py` reported **`1 failed, 57 passed`**, so mutation 4 is
killed by exactly 1 of the 58 domain tests, and that one test is the only guard on this
distinction anywhere in the suite. `tests/test_web_api.py` reported **`490 passed`**:
mutation 4 survives all 490. The reason is worth stating, because it is a real gap
somebody could close later: every endpoint test that names a quiet member records its
expense through the API, where `created_by` and `payer_id` are the same member, so the
two fields are indistinguishable from there. The domain test is the only place they
differ, which is why it hands one expense a payer and a different recorder and then
asserts the payer is still listed.

## Mutation 5: the newest expense taken as the last element rather than by `ordering_key`

The ledger arrives in `ordering_key` order today, so this is invisible until a caller
hands over a list in another order, at which point the age is computed from the wrong
event.

```json
{
  "id": "newest-is-the-last-element",
  "file": "src/splitwise_lite/staleness.py",
  "find": "    newest = max(expenses, key=ordering_key)",
  "replace": "    newest = expenses[-1]",
  "kills": ["tests/test_staleness.py::test_the_newest_expense_is_the_maximal_one_and_not_the_last_in_the_list"],
  "survives": ["tests/test_staleness.py::test_the_newest_expense_is_chosen_with_the_ordering_key_events_py_defines"],
  "result": "killed"
}
```

Measured: `tests/test_staleness.py` reported **`1 failed, 57 passed`** and
`tests/test_web_api.py` reported **`490 passed`**. Mutation 5 is killed by 1 of the 58
domain tests and survives all 490 endpoint tests.

**Two things this measurement says that a prediction would have got wrong.** First, the
identity assertion `staleness.ordering_key is events.ordering_key` **survives this
mutation**, and it is named in `survives` above for that reason: the import is still
there and still resolves, it is simply no longer used. An identity check on an import is
not evidence that the import is used, and this is the mutation that proves it. Second,
the endpoint module cannot catch it because `store.list_events` and
`store.list_expenses` both return `ordering_key` order, so the last element really is the
newest through every real request. Only a hand-built out-of-order list reaches it.

## The committed mutant: `MUTANT_H`

Recorded here as well as committed, so this file lists every mutation this task claims.
It lives in `tests/test_shell_behaviour.py` beside `MUTANT_A` through `MUTANT_G` and the
suite re-runs it on every run; the four keys below are the same three the harness accepts
plus the result.

```json
{
  "id": "MUTANT_H-the-never-arm-removed",
  "file": "app/app.js",
  "find": "    if (state === 'stale') {",
  "replace": "    if (state !== 'fresh') {",
  "kills": ["a_group_with_nothing_recorded_says_so_beside_the_figures"],
  "survives": ["an_unknown_hash_is_replaced_not_pushed", "a_stale_balance_names_who_has_entered_nothing"],
  "result": "killed"
}
```

Measured through the harness, which reports per scenario rather than per test: of the
**158 scenarios**, exactly **1 fails**, and it is the `never` one. The failure names the
word `null` on screen, which is the whole point: a ledger known to hold nothing is
rendered with the words for a ledger of known age, and the number in that sentence is
`String(null)`. The two named survivors are the repo's standing control and this
feature's own stale case, so this is a working app with one sentence wrong rather than a
crater.

**The run cost it adds**, per `plans/mutations/README.md`'s cap: one further harness
process, which is one `node` run of all 158 scenarios. Timed at 0.73 seconds wall clock on this
machine, inside a `tests/test_shell_behaviour.py` run that takes about 12 seconds in
total, so the mutant adds about six per cent to that module and nothing measurable
to the suite.

**Why the anchor is one line**, recorded because it cost a run to find out. It was first
written as the three-line `if (state === 'never') { ... } else if (state === 'stale') {`,
and the harness refused it: `matched 0 times in app/app.js, not exactly once`, because
this working tree is CRLF and the anchor spelled `\n`. `MUTANT_F` already carries that
scar in its own comment. The two arms of the toggler in `app/app.js` are therefore
ordered stale-then-never, so that one line carries the whole mutation and the anchor
cannot rot on a checkout whose line endings differ.
