# Issue #44, the empty roster message: recorded mutations

GitHub issue #44, sharpened in `plans/tasks/44-the-empty-roster-message.md`. Every check
this task adds has been made to go red, and this file is where that is recorded as
something the next person re-runs rather than as a sentence they would have to
reconstruct. `plans/mutations/README.md` states the format and the recipe; every run
below used that recipe, from the record's own `find` and `replace`, with
`PYTHONDONTWRITEBYTECODE=1` set and `git checkout -- <file>` between runs, on a tree
whose only uncommitted file was the task specification.

**How to read the figures.** Each is a **whole-module, unfiltered** `N failed, M passed`
line, quoted as pytest printed it, and each names the quantity it is a count of. A
filtered count is reproducible only by somebody who guesses the same `-k`; the
whole-module line is the one a later reader reproduces from this record alone.

The two modules, on the branch with every mutation reverted:

* `tests/test_add_screen.py`: **28 tests**, of which 1 is this task's new ban. It holds
  facts about committed markup and bans over source text, and nothing else: its own
  docstring forbids it to claim a rendering behaviour.
* `tests/test_shell_behaviour.py`: **188 tests**, of which 2 are this task's, one new
  scenario and one new mutant test. It drives the shipped files through
  `tests/shell_harness.mjs`, so it is the only module here that can see behaviour.

**The standing collateral, stated once because it is true of all three mutations
below.** `tests/test_shell_behaviour.py` holds two whole-harness exit-code checks,
`test_the_harness_exits_zero_against_the_shipped_files` (`:486`) and
`test_the_harness_finds_app_from_its_own_location` (`:1032`). Both run every scenario
and assert the process exited 0, so **any** red scenario reds both of them as well. They
are listed under `kills` where they went red, because a record that quietly omitted two
of the three failures would not reproduce, but they are collateral rather than evidence:
neither names the defect and neither would tell a reader what broke.

**The one demonstration that is not in this file, and why.** Criterion 4's ban can never
fire *alone* under a single-file mutation, because any edit to the sentence also reds the
exact-text pin beside it. Showing it fire alone needs the sentence and the pin changed
**together**, in two files, and this format admits exactly one `file` per record. That
run is therefore written into the pull request's Findings, quoting both edits and the
output, with criterion 17d named as the reason it is not a section here. It is disclosed
rather than dressed up as a normal mutation.

## Mutation 1: the retracted sentence put back

The sentence exactly as it shipped before this task, which is the defect as issue #44
reported it: an empty roster answered with the words for a roster that had not arrived,
directly beneath a note saying it had arrived and held nobody.

```json
{
  "id": "the-retracted-sentence-put-back",
  "file": "app/index.html",
  "find": "<p class=\"add-error-text\" id=\"add-error-roster\" hidden>The app has nobody to\n        record this expense against, so it cannot be saved.</p>",
  "replace": "<p class=\"add-error-text\" id=\"add-error-roster\" hidden>The people in this group\n        have not arrived yet, so this cannot be saved.</p>",
  "kills": [
    "tests/test_add_screen.py::test_the_screens_own_two_refusals_read_exactly_as_promised",
    "tests/test_add_screen.py::test_the_roster_refusal_names_none_of_the_three_reasons_it_covers",
    "tests/test_shell_behaviour.py::test_scenario[a_save_refused_while_the_roster_loads_still_reads_true_when_the_roster_is_empty]",
    "tests/test_shell_behaviour.py::test_the_harness_exits_zero_against_the_shipped_files",
    "tests/test_shell_behaviour.py::test_the_harness_finds_app_from_its_own_location"
  ],
  "survives": [
    "tests/test_add_screen.py::test_the_three_roster_states_read_exactly_as_promised",
    "tests/test_shell_behaviour.py::test_mutant_i_an_empty_roster_withdrawing_a_refusal_that_is_still_true_is_killed"
  ],
  "result": "killed"
}
```

Measured: `tests/test_add_screen.py` reported **`2 failed, 26 passed`**, so mutation 1 is
killed by 2 of that module's 28 tests, the exact-text pin and the new ban.
`tests/test_shell_behaviour.py` reported **`3 failed, 185 passed`**, so it is killed by 3
of that module's 188, of which one is the new scenario's text assertion and two are the
collateral exit-code checks named in the preamble.

The order the checks went red, which criterion 17a asks for: the pin
(`test_the_screens_own_two_refusals_read_exactly_as_promised`) and the ban
(`test_the_roster_refusal_names_none_of_the_three_reasons_it_covers`) both in
`tests/test_add_screen.py`, then the scenario's `#add-error-roster text` assertion in the
harness. The ban failed on `arriv`, the first of its four substrings that the retracted
sentence contains; it also contains `yet`, which the ban would have caught had `arriv`
not come first.

Three of the other four sentences on this screen are untouched, which is why
`test_the_three_roster_states_read_exactly_as_promised` is named as a survivor: a
mutation of the refusal must not be mistaken for a mutation of the roster panel.

## Mutation 2: a different cause-naming sentence, not the retracted one

The point of this record is that the pin and the ban are two checks and not two names for
one comparison against one string. This sentence has never shipped, so nothing can match
it by memory, and it names a different cause from the retracted one: the empty roster
rather than the roster in flight. It is also false in the state it does not name, which
is the whole defect one wording over.

```json
{
  "id": "a-different-cause-naming-sentence",
  "file": "app/index.html",
  "find": "<p class=\"add-error-text\" id=\"add-error-roster\" hidden>The app has nobody to\n        record this expense against, so it cannot be saved.</p>",
  "replace": "<p class=\"add-error-text\" id=\"add-error-roster\" hidden>The group is empty, so\n        this cannot be saved.</p>",
  "kills": [
    "tests/test_add_screen.py::test_the_screens_own_two_refusals_read_exactly_as_promised",
    "tests/test_add_screen.py::test_the_roster_refusal_names_none_of_the_three_reasons_it_covers",
    "tests/test_shell_behaviour.py::test_scenario[a_save_refused_while_the_roster_loads_still_reads_true_when_the_roster_is_empty]",
    "tests/test_shell_behaviour.py::test_the_harness_exits_zero_against_the_shipped_files",
    "tests/test_shell_behaviour.py::test_the_harness_finds_app_from_its_own_location"
  ],
  "survives": [
    "tests/test_add_screen.py::test_the_committed_add_markup_invents_no_data",
    "tests/test_add_screen.py::test_no_copy_on_this_screen_says_anything_about_balances"
  ],
  "result": "killed"
}
```

Measured: `tests/test_add_screen.py` reported **`2 failed, 26 passed`** and
`tests/test_shell_behaviour.py` reported **`3 failed, 185 passed`**, the same two counts
as mutation 1 out of the same 28 and 188.

What the counts do not show, and what this record exists for: the ban failed on a
**different substring**. Under mutation 1 it was `arriv`; here pytest printed

```
E           AssertionError: empty
E             'empty' is contained here:
E               the group is empty, so this cannot be saved.
```

so the ban is reading the sentence rather than comparing it to one remembered string, and
the two add-screen failures are two checks with two different reasons.

## Mutation 3: the empty path withdraws the refusal

`MUTANT_I`, recorded here as well as committed, because a committed mutant and a recorded
one are read by different people: the suite re-runs the first and a person re-runs the
second. It is the fix issue #44 analysed and rejected — `addRosterArrived()` called before
`addRosterState('empty')`, so the Save is answered and the empty roster that lands a
moment later silently un-answers it.

```json
{
  "id": "the-empty-path-withdraws-the-refusal",
  "file": "app/app.js",
  "find": "          addRosterState('empty');",
  "replace": "          addRosterArrived();\n          addRosterState('empty');",
  "kills": [
    "tests/test_shell_behaviour.py::test_scenario[a_save_refused_while_the_roster_loads_still_reads_true_when_the_roster_is_empty]",
    "tests/test_shell_behaviour.py::test_the_harness_exits_zero_against_the_shipped_files",
    "tests/test_shell_behaviour.py::test_the_harness_finds_app_from_its_own_location"
  ],
  "survives": [
    "tests/test_add_screen.py::test_the_screens_own_two_refusals_read_exactly_as_promised",
    "tests/test_add_screen.py::test_the_roster_refusal_names_none_of_the_three_reasons_it_covers",
    "tests/test_shell_behaviour.py::test_scenario[a_group_with_no_members_says_so_and_saves_nothing]",
    "tests/test_shell_behaviour.py::test_scenario[an_unknown_hash_is_replaced_not_pushed]"
  ],
  "result": "killed"
}
```

Measured: `tests/test_shell_behaviour.py` reported **`3 failed, 185 passed`**, so mutation
3 is killed by 3 of that module's 188, one of them the new scenario and two of them the
collateral exit-code checks. `tests/test_add_screen.py` reported **`28 passed`**: mutation
3 survives **every one** of that module's 28 tests, and that is the finding rather than a
gap. Nothing in `app/index.html` moves under it, so a module confined to facts about
committed markup cannot see it — which is the constraint that put criteria 8 and 15 in the
harness and not in the add-screen module. A check about a module that never opens that
module is not a check about that module, and this is the measurement that says so.

The failing assertion is the one criterion 15d exists for, quoted from the run:

```
the three error children once the empty roster landed: expected [false,true,false], got [false,false,false]
```

`a_group_with_no_members_says_so_and_saves_nothing` is named as a survivor and measured as
one: it taps Save **after** the roster has already landed, so nothing on its path
withdraws anything and it stays green. That is what makes this a defect on the in-flight
path rather than a refusal that stopped working, and it is the "working app with one
behaviour broken" that `plans/mutations/README.md`'s third test asks for.
`an_unknown_hash_is_replaced_not_pushed` is the named control every other mutant test in
this repository uses, and it survives too.

The anchor is a single line, deliberately. The harness substitutes into raw source text
at run time, so a multi-line anchor rots on a CRLF checkout and this working tree is CRLF;
`MUTANT_F` and `MUTANT_H` both carry that scar. Mutations 1 and 2 above do span two lines
and are safe anyway, because the recipe in `plans/mutations/README.md` applies them
through `Path.read_text`, whose universal-newline translation makes `\n` in a record match
`\r\n` on disk. The two mechanisms differ, and that difference is the reason the committed
mutant is written the stricter way.
