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

* `tests/test_staleness.py`: **64 tests** today, of which 15 are this task's own new
  checks beyond the plain domain figures. It has moved twice while this file was being
  written, and every figure below is quoted as it was taken rather than restated:
  **58** when mutations 1 to 4 were measured, **59** after the positive control added
  with the repair under mutation 5, and **64** after the control repair recorded in the
  last section, which turned one test into five parametrised cases and added one more.
* `tests/test_web_api.py`: **493 tests**, of which 15 are this task's endpoint checks.
  The figures quoted against it under mutations 1 to 5 were taken when it held **490**,
  before this branch merged `bea0da7`, which brought three. The same disclosure the
  domain module gets, for the same reason: the counts moved for a reason unrelated to
  any mutation, and a reader re-running this file today gets 493 and should not have to
  wonder why. QA re-ran all five against 493 and every verdict was unchanged.

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
  "kills": [
    "tests/test_staleness.py::test_the_newest_expense_is_the_maximal_one_and_not_the_last_in_the_list",
    "tests/test_staleness.py::test_the_newest_expense_is_chosen_with_the_ordering_key_events_py_defines"
  ],
  "survives": ["tests/test_staleness.py::test_the_runtime_name_check_can_tell_a_used_import_from_an_unused_one"],
  "result": "killed"
}
```

**This mutation found a check that could not fail, and the record keeps both
measurements, because a survivor that became a killer is the most useful thing this
file can hold.**

**Before, measured on `7d5af55`:** `tests/test_staleness.py` reported
**`1 failed, 57 passed`** of 58. The one that failed was the behavioural test. The test
named for this very rule,
`test_the_newest_expense_is_chosen_with_the_ordering_key_events_py_defines`, **passed
under the mutation**. It held one assertion,
`staleness.ordering_key is events.ordering_key`, and that assertion cannot fail here:
the import is still there and still resolves, and the module simply stops calling what
it imported. An identity check on an import says two names are the same object and says
nothing about whether either is used.

The cause was narrow and worth naming, because it is a copying error anybody could
repeat: the precedent it was modelled on,
`tests/test_balances.py::test_the_fold_sorts_with_the_ordering_key_events_py_defines`,
carries **two** assertions, and only the second was copied. The first,
`"ordering_key" in _runtime_names(_module_tree(balances_module))`, is the half that
bites.

**After, measured on the repair:** `tests/test_staleness.py` reports
**`2 failed, 57 passed`** of 59, and the second failure is that test. It now asserts, in
the order they bite: the behaviour, over a list whose newest expense is neither first nor
last and over every rotation of it; the name being reached at run time, off the module's
own syntax tree; and then the identity criterion 11 asks for. Pytest stops at the first
failing assertion, so what is seen in the run is the behavioural one, `assert 30 == 2`.

**The structural half was measured separately rather than assumed**, because a repair
with the same defect as the bug has happened in this repo before. Against the mutated
source: `runtime_names(...)` reports `ordering_key` reached at run time = **False**,
while a plain text search for `ordering_key` in the same file reports **True**. So the
syntax-tree check kills the mutant and the text search that a hastier repair would have
used does not. `ast.alias` is not an `ast.Name`, which is exactly why an import
contributes nothing and only a use does.

`tests/test_web_api.py` reported **`490 passed`** both before and after: mutation 5
survives all 490 endpoint tests either way, because `store.list_events` and
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
**159 scenarios**, exactly **1 fails**, and it is the `never` one. That figure was
**158** when first taken, before this branch merged `bea0da7`, which added one scenario
of its own through PR #81; the count of failures is unchanged at exactly one, and QA
re-measured it live at 159. The failure names the
word `null` on screen, which is the whole point: a ledger known to hold nothing is
rendered with the words for a ledger of known age, and the number in that sentence is
`String(null)`. The two named survivors are the repo's standing control and this
feature's own stale case, so this is a working app with one sentence wrong rather than a
crater.

**The run cost it adds**, per `plans/mutations/README.md`'s cap: one further harness
process, which is one `node` run of all **159** scenarios. That figure was 158 when the timing
below was taken, before this branch merged `bea0da7`; the timing is quoted as it was measured
and the scenario count is current. Timed at 0.73 seconds wall clock on this
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


## The control on the clock ban: the second survivor that became a killer

Not a mutation of `src/` but of a guard, and it belongs here for the same reason
mutation 5 does: a check was shown incapable of failing, repaired, and shown to fail.
QA found this one; I found mutation 5. **They are the same copying error, one test
apart**, and that is the useful thing about the pair. Both copied a two-part precedent
from `tests/test_balances.py` in name and kept only the half that cannot bite:
mutation 5 kept the identity assertion and dropped the runtime-name check, and this one
kept the shape of a positive control and dropped the part that reads the module.

The mutation is the deletion QA measured, expressed so it can be re-run:

```json
{
  "id": "clock-ban-loses-a-spelling",
  "file": "tests/test_staleness.py",
  "find": "CLOCK_READS = (\"now(\", \"utcnow(\", \"today(\", \"time.time\", \"monotonic\")",
  "replace": "CLOCK_READS = (\"now(\", \"today(\", \"time.time\", \"monotonic\")",
  "kills": ["tests/test_staleness.py::test_every_spelling_in_the_ban_is_measured_for_what_it_alone_catches"],
  "survives": ["tests/test_staleness.py::test_the_module_never_reads_the_clock"],
  "result": "killed"
}
```

**Before, measured by QA on `24e39b2`:** deleting `"utcnow("` from the real ban left
`tests/test_staleness.py` at **`6 passed, 52 deselected`** under their filter, green.
The old control never called `source()`, so it never read `staleness.py`, and it
carried its own second copy of the ban list, so it asserted five hardcoded strings
against five other hardcoded strings. The only effect of the deletion was one
parametrised case silently vanishing, which is how this repository once lost four tests
unnoticed.

**After, measured here, whole module and unfiltered, deleting each spelling in turn:**

| spelling deleted | `tests/test_staleness.py` (64) | what fails |
|---|---|---|
| `"now("` | `2 failed, 61 passed` | the smuggled `datetime.now(` case, and the coverage test |
| `"utcnow("` | `1 failed, 62 passed` | the coverage test |
| `"today("` | `2 failed, 61 passed` | the smuggled `date.today()` case, and the coverage test |
| `"time.time"` | `2 failed, 61 passed` | the smuggled `time.time()` case, and the coverage test |
| `"monotonic"` | `2 failed, 61 passed` | the smuggled `perf.monotonic()` case, and the coverage test |

Every deletion now fails. It could not before.

**One row of that table is not what was expected, and the reason is a real finding
about the ban rather than about the control.** `"utcnow("` kills only the coverage
test, and its smuggled case still passes. Measured: **every string containing
`utcnow(` also contains `now(`**, so `now(` catches `_Instant.utcnow()` on its own and
`"utcnow("` is strictly redundant. Deleting it costs no coverage at all, which is
exactly why a *correct* control cannot fail on that particular deletion by catching an
escaped read: there is no escaped read to catch. The only way to make it fail that way
would be to pin the list against a copy of itself, which is the defect being removed.

So the redundancy is measured and stated instead, by
`test_every_spelling_in_the_ban_is_measured_for_what_it_alone_catches`, which asserts
which four spellings are load-bearing and that `"utcnow("` alone catches nothing, and
then refuses its removal with a message saying that criterion 8 names all five and
taking one out is a decision to record rather than a tidy. That is what keeps the
deletion loud without duplicating the list. The same redundancy sits in
`tests/test_store.py`'s list, which this one was modelled on, and is not this task's to
fix.
