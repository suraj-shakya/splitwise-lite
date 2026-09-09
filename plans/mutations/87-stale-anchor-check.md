# Mutations behind the stale-anchor check (issue #87)

Seven mutations, all run and all killed, against the checks this task adds: that a
complete record's `find` occurs exactly once in the file its own `file` key names, or
that record is declared in `CARRIED_STALE_ANCHORS` with a reason naming the change that
broke it, and that the declaration carries a dated note in the record itself.

Taken against `a0e48eb` on 2026-09-09, on branch `task-87`, which is this branch merged
up to master `5bfc117`. A record quotes a measurement, so it carries the tree it was
measured on: if an anchor below no longer matches exactly once, that is the tree to diff
against rather than a defect in the record. Every anchor below is itself swept by the
check this file is about; see `README.md` in this directory for what that check does and
does not promise, for the standing collateral it adds to every run here, and for the
format and the recipe.

**What each run was, named as a quantity rather than left to be inferred.** Every run
below was the whole of `tests/test_suite_integrity.py`, unfiltered, which collects **100
tests** at this revision, and the figures quoted are that module's failed and passed
counts. Nothing was selected with `-k`, so a claim that a mutation is caught by one test
is a claim about the other ninety-nine staying green rather than about a filtered
subset. Every `survives` entry below was observed green in that named run.

**Which population the sweep covered.** At `a0e48eb` the check examines **44** records in
**11** record files, including the seven in this one, and finds exactly one stale anchor,
`g2-repeated-member`. That was measured with the shipped helpers rather than counted.

> **Corrected 2026-09-09 for the review of this pull request.** This paragraph used to
> say that the runs were taken at `2fbfc68` over 32 records, and then: "Neither figure
> changes any result below: no anchor in either population matches twice, and the two
> record-file mutations red on `plans/mutations/65-message-pins.md` either way." The
> clause after the colon was true; **the sentence before it was false for `s4`**. Both
> the reviewer and QA of this pull request measured it independently: at `2fbfc68`, `s4`
> gave `1 failed, 98 passed` exactly as recorded, and at the branch tip it gave
> `2 failed, 97 passed`, the second failure being the sweep, which that record listed
> under `survives`. The cause is the standing collateral described below, and it is why
> every run in this file has now been re-taken at `a0e48eb` with this file in the swept
> population. The old figures are not restated as current anywhere.

**Standing collateral, and it applies to every mutation in this file.** Each `find` here
is a piece of the file its own mutation edits, so applying any of them rots that record's
own anchor, and the sweep then reds naming the record just applied. That is collateral
rather than evidence: it says nothing about the guard under test and it appears whatever
the mutation does. Following the two whole-harness checks that
`44-the-empty-roster-message.md` lists for the same reason, it is named in `kills` where
it fires rather than omitted, because a record that quietly dropped one of its failures
would not reproduce. Where the sweep is in `kills` for a substantive reason, the section
says which of the two it is.

Every mutation was applied with the recipe in `README.md`, whose exactly-once assertion
was **not** skipped and which refused nothing, with `PYTHONDONTWRITEBYTECODE=1` set on
every run, and each was reverted with `git checkout -- <file>` before the next one. Four
of the seven mutate `tests/test_suite_integrity.py` itself and three mutate a record
file, so the bytecode rule is load-bearing rather than ceremonial here: `s2`, `s4`, `s5`
and `s7` are edits to one Python file minutes apart, and without that variable a cached
`.pyc` invalidated on `(mtime, size)` can make a later run report an earlier one's
result, which is what happened on PR #62 and looked exactly like a genuine finding.

**The anchor-into-a-record-file trap, because it will cost somebody an hour otherwise.**
Three of these mutations target a record file, and a record file quotes its own message
text in prose, so a plain sentence is **not** a unique anchor in one. Measured in
`plans/mutations/65-message-pins.md` at `a0e48eb`: the text
`weights sum to zero, so there is no share to divide the total into` occurs **twice**,
once inside the JSON `find` of `g1-weights-sum-to-zero` and once below it in the
"message the guard actually prints" quote. Sites here are named by their anchor text
rather than by a line number, following the introduction of
`88-the-sign-in-gate-discards-a-programming-error.md`, whose own line numbers went stale
three times on one branch; at `a0e48eb` those two occurrences are at lines 36 and 50, and
that is the only place a number for them appears. The recipe would refuse that anchor,
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

**What the run printed:** `1 failed, 99 passed`.

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
both `g2-repeated-member` and `g7-repeated-id` in it and a bumped `CARRIED_STALE_TOTAL`.
That one failing test carries a second finding as well, naming `s1-a-healthy-anchor-broken`
itself, which is the standing collateral described above: this record's `find` is a piece
of the file this mutation edits. One failing test, two findings.

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

**What the run printed:** `2 failed, 98 passed`.

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
reads the module's own. The sweep's failure carries a second finding naming
`s2-the-declaration-deleted`, the standing collateral: this record's `find` is the pair
line it deletes.

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

**What the run printed:** `1 failed, 99 passed`.

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
    "tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites",
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_the_stale_anchor_message_says_what_happened",
    "tests/test_suite_integrity.py::test_the_carried_stale_total_is_the_number_of_carried_records",
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_carries_a_dated_note_in_its_record"
  ],
  "result": "killed"
}
```

**What the run printed:** `2 failed, 98 passed`.

**Which criterion this is evidence for.** The fourth mutation criterion 37 invites: the
exactly-once decision is a claim until something reds when it is weakened. This weakens
the comparison in `stale_pairs` from "not exactly one" to "fewer than one", which is
`>= 1` accepted as healthy.

**What reddened, and what it named.**
`tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites` at its case (c),
the assertion labelled in the source as the positive control for the two-or-more branch:

    assert stale_pairs(twice.counts) == {("s-twice", 2)}
    AssertionError: assert set() == {('s-twice', 2)}

**The second failure is standing collateral and not the check catching the weakening.**
`tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried`
reds because this record's own `find` is the line this mutation replaces, so applying it
leaves `s4-exactly-once-weakened-to-at-least-once` with an anchor that matches zero
times. Zero is still a finding under `< 1`, so the sweep reds for its own anchor and not
for anything the weakening let through. Do not read it as evidence.

> **Corrected 2026-09-09 for the review of this pull request.** This record used to list
> that sweep under `survives`, and to argue from its staying green. It did stay green at
> `2fbfc68`, where the run was taken and where this file was not yet in the swept
> population; both the reviewer and QA re-ran it at the branch tip and got
> `2 failed, 97 passed`. The measurement was sound and the claim about the other tree was
> not. It is moved to `kills` in the idiom `44-the-empty-roster-message.md` uses for
> collateral, and the argument it used to carry is restated below as a measurement of the
> population rather than as a survivor.

**What actually carries the exactly-once argument is the population, measured directly.**
At `a0e48eb` every one of the 44 recorded anchors counts exactly 1 in its target except
`g2-repeated-member`, which counts 0. **No anchor in this repo matches twice.** So the
sweep over the real population could not be the positive control for the two-or-more
branch whatever it did, and the synthetic case (c) is the only thing standing between
"exactly once" and "at least once". That is the measured reason case (c) exists, and the
reason its target is a sentence measured to occur twice in a real committed file rather
than an invented string: a self-test section that cannot fail is the defect this module
exists to refuse.

## The undecodable target, uncaught

```json
{
  "id": "s5-the-undecodable-target-uncaught",
  "file": "tests/test_suite_integrity.py",
  "find": "    except (OSError, UnicodeDecodeError):",
  "replace": "    except OSError:",
  "kills": [
    "tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites",
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_the_stale_anchor_message_says_what_happened",
    "tests/test_suite_integrity.py::test_the_carried_stale_total_is_the_number_of_carried_records",
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_carries_a_dated_note_in_its_record"
  ],
  "result": "killed"
}
```

**What the run printed:** `2 failed, 98 passed`.

**Which finding this is evidence for.** QA of this pull request dropped
`UnicodeDecodeError` from that `except` clause and the module stayed at `99 passed`, so
criterion 7's third unreadable-target case, a target that exists and is not UTF-8, had
nothing holding it: the missing-file and directory cases both raise `OSError` and shared
the other half of the clause. A control was added, and this is the mutation that shows it
bites.

**What reddened, and what it named.**
`tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites` at the assertion
that sweeps a record pointing at `app/icons/icon-192.png`, a committed 2106-byte PNG:

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0x89 in position 0

That is the exception escaping the test rather than becoming a finding, which is exactly
what criterion 7 forbids. The second failure is standing collateral: this record's `find`
is the clause it edits.

## The retirement note stops naming its record

```json
{
  "id": "s6-the-note-stops-naming-its-record",
  "file": "plans/mutations/65-message-pins.md",
  "find": "So the pair `(\"g2-repeated-member\", 0)` is declared in",
  "replace": "So that pair is declared in",
  "kills": [
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_carries_a_dated_note_in_its_record",
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_names_what_broke_it",
    "tests/test_suite_integrity.py::test_the_carried_stale_total_is_the_number_of_carried_records",
    "tests/test_suite_integrity.py::test_the_dated_note_check_reads_the_note_and_not_only_its_shape"
  ],
  "result": "killed"
}
```

**What the run printed:** `2 failed, 98 passed`.

**Which finding this is evidence for.** QA of this pull request replaced the whole of
`g2-repeated-member`'s retirement note with `> Note, 2026-09-08. Nothing in particular.`
and the module stayed at `99 passed`, because a date inside a blockquote was all the
check asked for. The five things criterion 24 requires of that note were held by review
alone. The note now has to name the record it retires and a change with a `#NN`, and this
mutation removes the record's name from it while leaving everything else in place.

**What reddened, and what it named.**
`tests/test_suite_integrity.py::test_every_carried_stale_anchor_carries_a_dated_note_in_its_record`:

    plans/mutations/65-message-pins.md section '## The repeated-member refusal in
    split.py' holds g2-repeated-member, whose anchor is declared stale, and its
    retirement note is not usable:
        its dated note does not name g2-repeated-member

**The one that matters here is the survivor.**
`tests/test_suite_integrity.py::test_the_dated_note_check_reads_the_note_and_not_only_its_shape`
stays green, which is the point: the synthetic controls and the live subject fail
independently, so neither is standing in for the other. The second failure is standing
collateral, this record's `find` being a sentence inside the note it edits.

## The one reason stops naming its record

```json
{
  "id": "s7-the-reason-stops-naming-its-record",
  "file": "tests/test_suite_integrity.py",
  "find": "\"g2-repeated-member rotted when #61 took {list(ordered)} out of split.py's \"",
  "replace": "\"#61 took {list(ordered)} out of split.py's \"",
  "kills": [
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_names_what_broke_it",
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_carries_a_dated_note_in_its_record",
    "tests/test_suite_integrity.py::test_the_carried_stale_total_is_the_number_of_carried_records",
    "tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites"
  ],
  "result": "killed"
}
```

**What the run printed:** `2 failed, 98 passed`.

**Which finding this is evidence for.** The reviewer of this pull request rotted
`g3-not-a-ledger-event`'s target by hand, pasted the printed literal unedited into the
existing entry, bumped the integer and added a bare dated line, and got `99 passed`, with
#61's reason left standing as the explanation for a rot #61 had nothing to do with. There
is one reason string per record file, so the check now requires it to name every record
id in its entry. This mutation takes the record's name back out of it while leaving the
`#NN` and the length intact, which is precisely the state a blind paste would leave.

**What reddened, and what it named.**
`tests/test_suite_integrity.py::test_every_carried_stale_anchor_names_what_broke_it`:

    plans/mutations/65-message-pins.md: this file's entry carries one reason for every
    record in it, and that reason does not name g2-repeated-member.

The two older assertions in that test stay satisfied under the mutant, the reason still
being over twenty characters and still carrying `#61`, so this is the new requirement
failing alone rather than one of the old two catching it. The second failure is standing
collateral, this record's `find` being the reason line it edits.
