# Mutations behind the stale-anchor check (issue #87)

Four mutations, all run and all killed, against the check this task adds: that a
complete record's `find` occurs exactly once in the file its own `file` key names, or
that record is declared in `CARRIED_STALE_ANCHORS` with a reason naming the change that
broke it.

Taken against `2fbfc68` on 2026-09-08, on branch `task-87`. A record quotes a
measurement, so it carries the tree it was measured on: if an anchor below no longer
matches exactly once, that is the tree to diff against rather than a defect in the
record. Every anchor below is now swept by the suite; see `README.md` in this directory
for what that check does and does not promise, and for the format and the recipe.

**What each run was, named as a quantity rather than left to be inferred.** Every run
below was the whole of `tests/test_suite_integrity.py`, unfiltered, which collects **99
tests** at this revision, and the figures quoted are that module's failed and passed
counts. Nothing was selected with `-k`, so a claim that a mutation is caught by one test
is a claim about the other ninety-eight staying green rather than about a filtered
subset. Every `survives` entry below was observed green in that named run.

**Which population the sweep covered during these runs, since this file changes it.**
The four runs were taken before this file was committed, so the check swept the **32**
records the directory then held, in eight record files. This file adds four, so a re-run
against the tip of this branch sweeps **36** in nine. Neither figure changes any result
below: no anchor in either population matches twice, and the two record-file mutations
red on `plans/mutations/65-message-pins.md` either way.

Every mutation was applied with the recipe in `README.md`, whose exactly-once assertion
was **not** skipped and which refused nothing, with `PYTHONDONTWRITEBYTECODE=1` set on
every run, and each was reverted with `git checkout -- <file>` before the next one. Two
of the four mutate `tests/test_suite_integrity.py` itself and two mutate a record file,
so the bytecode rule is load-bearing rather than ceremonial here: `s2` and `s4` are
edits to one Python file minutes apart, and without that variable a cached `.pyc`
invalidated on `(mtime, size)` can make the second run report the first one's result,
which is what happened on PR #62 and looked exactly like a genuine finding.

**The anchor-into-a-record-file trap, because it will cost somebody an hour otherwise.**
Half of these mutations target a record file, and a record file quotes its own message
text in prose, so a plain sentence is **not** a unique anchor in one. Measured in
`plans/mutations/65-message-pins.md` on 2026-09-08: the text
`weights sum to zero, so there is no share to divide the total into` occurs **twice**,
at line 36 inside the JSON `find` of `g1-weights-sum-to-zero` and at line 50 in the
"message the guard actually prints" quote below it. The recipe would refuse that anchor,
correctly, and a looser applier would mutate the prose as well as the record. So an
anchor into a record file carries enough of the JSON escaping, a `\"` or a `\n`, to sit
only inside the block: `s1` below anchors on `{event.id!r}\"` and `s3` on a whole
escaped `"find":` line for exactly that reason. That twice-occurring sentence is also
the target of case (c) of the self-test, which is how the two-or-more branch gets a real
subject rather than a synthetic one.

**A node id in prose is a claim; a citation is written bare.** If a test is named below
as a precedent or a cross-reference, with no claim about what a mutation did to it, it is
written as `test_some_name` in `tests/test_module.py` rather than in `::` form. The `::`
form is what `test_every_node_id_a_record_names_is_one_it_lists` reads as a claim, and a
claim has to appear in that section's `kills` or `survives`. Do not satisfy that check by
adding a citation to `survives`: `survives` means it was run under the mutant and watched
to stay green, and an entry nobody ran is an observation nobody made.

## A healthy anchor broken deliberately

```json
{
  "id": "s1-a-healthy-anchor-broken",
  "file": "plans/mutations/65-message-pins.md",
  "find": "appears twice in the ledger: {event.id!r}\\\"",
  "replace": "appears twice in the ledger: {event.id!r} and again\\\"",
  "kills": [
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_every_recorded_mutation_is_machine_readable",
    "tests/test_suite_integrity.py::test_a_mutation_record_holds_no_prose_only_section",
    "tests/test_suite_integrity.py::test_every_node_id_a_record_names_is_one_it_lists"
  ],
  "result": "killed"
}
```

**What the run printed:** `1 failed, 98 passed`.

**Which criterion this is evidence for.** Criterion 37a. It edits the `find` of
`g7-repeated-id`, a record that matched its target exactly once, so that it matches zero
times, and it edits it inside the committed record file rather than in a synthetic.

**What reddened, and what it named.**
`tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried`,
with:

    These anchors do not match their target exactly once, and nothing declares them:
        g7-repeated-id: its find occurs 0 times in src/splitwise_lite/balances.py

The mutated record's JSON stays valid, so the failure is this check's and nobody
else's, and the paste-back at the end of that message printed the file's entry with
both `g2-repeated-member` and `g7-repeated-id` in it and `CARRIED_STALE_TOTAL = 2`.

**The three survivors are the point of this record.** Before this task, the three checks
over `plans/mutations/` were the whole of what read that directory, and all three stay
green with a committed anchor pointing at nothing:
`tests/test_suite_integrity.py::test_every_recorded_mutation_is_machine_readable`,
`tests/test_suite_integrity.py::test_a_mutation_record_holds_no_prose_only_section` and
`tests/test_suite_integrity.py::test_every_node_id_a_record_names_is_one_it_lists`. That
trio surviving **is the measured form of issue #87's central claim**, that a record's
anchor matched zero times and nothing reported it. It is recorded here rather than
asserted in a pull request body, because a sentence about a mutation is the thing this
directory exists to replace.

## The undeclared direction, with the declaration deleted

```json
{
  "id": "s2-the-declaration-deleted",
  "file": "tests/test_suite_integrity.py",
  "find": "\n                (\"g2-repeated-member\", 0),",
  "replace": "",
  "kills": [
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried",
    "tests/test_suite_integrity.py::test_the_carried_stale_total_is_the_number_of_carried_records"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_names_what_broke_it",
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_carries_a_dated_note_in_its_record",
    "tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites"
  ],
  "result": "killed"
}
```

**What the run printed:** `2 failed, 97 passed`.

**Which criterion this is evidence for.** Criterion 37b. The one pair in the baseline is
deleted while the rot it declares is still there, which is the undeclared direction over
a live subject rather than a synthetic one.

**What reddened, and what each one named.**
`tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried`
named the record and its target:

    These anchors do not match their target exactly once, and nothing declares them:
        g2-repeated-member: its find occurs 0 times in src/splitwise_lite/split.py

and `tests/test_suite_integrity.py::test_the_carried_stale_total_is_the_number_of_carried_records`
named the arithmetic:

    CARRIED_STALE_TOTAL says 1 and the entries hold 0 records. The entries are the
    subject; set CARRIED_STALE_TOTAL to how many records they hold.

**Two reds for one edit, which is worth stating rather than reading as noise.** The
declared integer is a second, independent statement about the same list, so deleting a
pair without lowering the integer cannot be quiet. What the mutation leaves behind is the
file's key with an empty `frozenset` and its reason intact, which is why
`tests/test_suite_integrity.py::test_every_carried_stale_anchor_names_what_broke_it` and
`tests/test_suite_integrity.py::test_every_carried_stale_anchor_carries_a_dated_note_in_its_record`
both stay green: they iterate the carried records, and under this mutant there are none.
`tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites` stays green too,
because it drives the sweep against synthetic baselines it passes in itself and never
reads the module's own.

## The stale direction, with the anchor repaired underneath the declaration

```json
{
  "id": "s3-the-declaration-outlives-its-subject",
  "file": "plans/mutations/65-message-pins.md",
  "find": "\"find\": \"        raise InvalidSplit(\\n            f\\\"member_ids names a member more than once: {list(ordered)}\\\"\\n        )\",",
  "replace": "\"find\": \"        raise InvalidSplit(\\\"member_ids names a member more than once\\\")\",",
  "kills": [
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_the_carried_stale_total_is_the_number_of_carried_records",
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_carries_a_dated_note_in_its_record",
    "tests/test_suite_integrity.py::test_every_recorded_mutation_is_machine_readable"
  ],
  "result": "killed"
}
```

**What the run printed:** `1 failed, 98 passed`.

**Which criterion this is evidence for.** Criterion 37c, and it is the analogue of
criterion 22b of `plans/tasks/70-substring-assertions-on-exception-messages.md`. It does
the thing the retirement note in `plans/mutations/65-message-pins.md` refuses to do: it
re-derives `g2-repeated-member`'s `find` against today's one-line raise, so the anchor
matches exactly once again while the entry still declares it stale.

**What reddened, and what it named.**
`tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried`,
in its other direction:

    These are declared stale and this file no longer agrees, so the entry has outlived
    its subject:
        g2-repeated-member: its anchor matches exactly once now, so delete the entry

and the paste-back was labelled `Paste this in place of this file's entry in
CARRIED_STALE_ANCHORS:` rather than as the anti-instruction, because in this direction
pasting is the answer.

**This is the proof that the second direction is not decorative.** A baseline checked in
one direction only becomes an allowlist nobody retires, and the entry would sit there
after the rot it names had been repaired. The mutant also shows why the message says
*which* of three things happened rather than only that the two disagree: here the anchor
matches once, so the fix is to delete the entry, whereas a moved count wants the pair
updated and a deleted record wants the entry gone for a different reason. And
`tests/test_suite_integrity.py::test_every_carried_stale_anchor_carries_a_dated_note_in_its_record`
stays green under it, which is the honest reading of that check: it asks whether the
record carries a dated note, not whether the note is still true.

## Exactly once weakened to at least once

```json
{
  "id": "s4-exactly-once-weakened-to-at-least-once",
  "file": "tests/test_suite_integrity.py",
  "find": "for identifier, count in counts.items() if count != 1",
  "replace": "for identifier, count in counts.items() if count < 1",
  "kills": [
    "tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried",
    "tests/test_suite_integrity.py::test_the_stale_anchor_message_says_what_happened",
    "tests/test_suite_integrity.py::test_the_carried_stale_total_is_the_number_of_carried_records"
  ],
  "result": "killed"
}
```

**What the run printed:** `1 failed, 98 passed`.

**Which criterion this is evidence for.** The fourth mutation criterion 37 invites: the
exactly-once decision is a claim until something reds when it is weakened. This weakens
the comparison in `stale_pairs` from "not exactly one" to "fewer than one", which is
`>= 1` accepted as healthy.

**What reddened, and what it named.**
`tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites` at its case (c),
the assertion labelled in the source as the positive control for the two-or-more branch:

    assert stale_pairs(twice.counts) == {("s-twice", 2)}
    AssertionError: assert set() == {('s-twice', 2)}

**The survivor that carries the argument is
`tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried`.**
It stays green under this mutant, over all 32 records the directory held at that
revision, because no anchor in this repo matches twice today. So the sweep over the real population cannot be
the positive control for that branch and the synthetic case is the only thing standing
between "exactly once" and "at least once". That is the measured reason case (c) exists
and the reason its target is the sentence measured to occur twice in a record file rather
than a made-up string: a self-test section that cannot fail is the defect this module
exists to refuse.
