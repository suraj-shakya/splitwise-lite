# Mutations behind the reason-naming controls (issue #97)

Six mutations against the controls this task adds to the `#87` subsection of
`tests/test_suite_integrity.py`: that the one reason a record file carries names every
record in its entry, that the printed paste-back tells a reader which reason to extend,
and that the two arms of the failure message nothing reached are reached. Five are
killed by a named control. The sixth is not, and it is here for that reason: it is the
measurement behind the decision to leave `computed_stale_total` uncontrolled and marked
as documentation rather than restructured.

Taken against `af52a1e` on 2026-09-09, on branch `task-97`, at master `0f6e8df`, with
this file's own six records committed, so every run below covers the population that
ships. Nothing changed in the tree after the runs except the figures below being written
into this file. A record quotes a measurement, so it carries the tree it was measured on:
if an anchor below no longer matches exactly once, that is the tree to diff against rather
than a defect in the record. Every anchor below is itself swept by
`test_every_recorded_anchor_matches_once_or_is_carried`; see `README.md` in this directory
for what that check does and does not promise, and for the format and the recipe.

**What each run was, named as a quantity rather than left to be inferred.** Every run
below was the whole of `tests/test_suite_integrity.py`, unfiltered, which collects
**102 tests** at this revision, and the figures quoted are that module's failed and
passed counts. Nothing was selected with `-k`, so a claim that a mutation is caught by
one test is a claim about the other hundred-and-one staying green rather than about a
filtered subset. Every `survives` entry below was observed green in that named run.

**Which population the sweep covered.** At this revision the check examines **53**
records in **12** record files, the six in this one included, and finds exactly one stale
anchor, `g2-repeated-member`, which is declared. That was measured with the shipped
helpers rather than counted.

**Standing collateral, and it applies to every mutation in this file.** All six mutate
`tests/test_suite_integrity.py`, and each `find` here is a piece of the file its own
mutation edits, so applying any of them rots that record's own anchor and the sweep then
reds naming the record just applied. That is collateral rather than evidence: it says
nothing about the guard under test and it appears whatever the mutation does. Following
the idiom `44-the-empty-roster-message.md` uses for the two whole-harness checks and
`87-stale-anchor-check.md` uses for the same collateral, it is named in `kills` where it
fires rather than omitted, because a record that quietly dropped one of its failures
would not reproduce. Where that check is in `kills` for a substantive reason instead, the
section says so; `r6` is the only section where it is the *whole* of what reddened.

Every mutation was applied with the recipe in `README.md`, whose exactly-once assertion
was **not** skipped and which refused nothing, with `PYTHONDONTWRITEBYTECODE=1` set on
every run, and each was reverted with `git checkout -- tests/test_suite_integrity.py`
before the next one. All six edit one Python file minutes apart, so the bytecode rule is
load-bearing rather than ceremonial here: without that variable a cached `.pyc`
invalidated on `(mtime, size)` can make a later run report an earlier one's result, which
is what happened on PR #62 and looked exactly like a genuine finding.

**A node id in prose is a claim; a citation is written bare.** Where a test is named
below as a precedent or a cross-reference, with no claim about what a mutation did to it,
it is written as `test_some_name` in `tests/test_module.py` rather than in `::` form,
which is the convention `87-stale-anchor-check.md` states and
`test_every_node_id_a_record_names_is_one_it_lists` reads.

## The reason-naming helper gutted

```json
{
  "id": "r1-the-reason-naming-helper-gutted",
  "file": "tests/test_suite_integrity.py",
  "find": "    return sorted(\n        identifier\n        for identifier, _ in carried\n        if not re.search(rf\"(?<![-\\w]){re.escape(identifier)}(?![-\\w])\", reason)\n    )",
  "replace": "    return []",
  "kills": [
    "tests/test_suite_integrity.py::test_the_reason_check_still_bites",
    "tests/test_suite_integrity.py::test_the_stale_anchor_paste_back_says_which_reason_to_extend",
    "tests/test_suite_integrity.py::test_the_placeholder_reason_does_not_satisfy_the_reason_check",
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_names_what_broke_it"
  ],
  "result": "killed"
}
```

**What the run printed:** `4 failed, 98 passed`.

**Which criterion this is evidence for.** Criterion 22a. It is the diagnostic issue #97
names, applied to the helper the issue is about: `unnamed_records` replaced with its
passing value, so it computes nothing and answers the empty list over every entry it is
handed.

**The survivor is the point of this record, and it is issue #97's claim measured rather
than argued.**
`tests/test_suite_integrity.py::test_every_carried_stale_anchor_names_what_broke_it`
stays green under this mutant. That check is the live requirement that a record file's
one reason names every record in its entry, and under a helper that has stopped
computing anything it reports success: the baseline carries one entry holding one record
whose reason opens with that record's id, so the correct answer over the live population
is the empty list and so is the degenerate one. That is the whole of the issue, and it
belongs here rather than in a pull request body, because a sentence about a mutation is
what this directory exists to replace.

**What reddened, and what each one named.**
`tests/test_suite_integrity.py::test_the_reason_check_still_bites` at its case (d), the
two-record entry whose reason names one of them, which is the assertion the issue is
about:

    assert len(partial) == 1
    AssertionError: assert 0 == 1

`tests/test_suite_integrity.py::test_the_stale_anchor_paste_back_says_which_reason_to_extend`
at its case (a), because with nothing unnamed the printed entry carries no
`EXTEND THIS REASON` comment and a reader pasting it is told nothing about why their
paste stayed red. And
`tests/test_suite_integrity.py::test_the_placeholder_reason_does_not_satisfy_the_reason_check`
at its fourth assertion, the one added for criterion 16, which routes
`NO_BREAKING_CHANGE_YET` through the check that consumes it: the placeholder is refused
on one count instead of two, because under the mutant it no longer fails to name a
record. The three die independently of one another, which is what makes them three
controls and not one restated three times.
`tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried` is
the standing collateral described above, naming `r1-the-reason-naming-helper-gutted`
itself.

## The paste-back marker suppressed

```json
{
  "id": "r2-the-paste-back-marker-suppressed",
  "file": "tests/test_suite_integrity.py",
  "find": "    missing = unnamed_records(frozenset(pairs), reason)",
  "replace": "    missing = []",
  "kills": [
    "tests/test_suite_integrity.py::test_the_stale_anchor_paste_back_says_which_reason_to_extend",
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_the_reason_check_still_bites",
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_names_what_broke_it",
    "tests/test_suite_integrity.py::test_the_placeholder_reason_does_not_satisfy_the_reason_check"
  ],
  "result": "killed"
}
```

**What the run printed:** `2 failed, 100 passed`.

**Which criterion this is evidence for.** Criterion 22b. It leaves `unnamed_records`
alone and cuts the paste-back off from it, which is the state a reader hits when the
printed entry stops telling them which reason to extend. Before issue #97 nothing read
that marker: `EXTEND THIS REASON` occurred once in the repo, in the producer.

**What reddened, and what it named.**
`tests/test_suite_integrity.py::test_the_stale_anchor_paste_back_says_which_reason_to_extend`
at the assertion that exactly one line of the printed entry carries the marker:

    marker = [line for line in unnamed.splitlines() if "EXTEND THIS REASON" in line]
    assert len(marker) == 1
    AssertionError: assert 0 == 1

**The survivor is what shows the two new controls are independent.**
`tests/test_suite_integrity.py::test_the_reason_check_still_bites` stays green under this
mutant, because it drives `reason_problems` and not the producer. So neither of the two
is standing in for the other: the reason check holds the requirement and this holds the
message that tells a reader how to satisfy it, and gutting one leaves the other reporting
its own subject.
`tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried` is
the standing collateral.

## The delete-this-entry arm never taken

```json
{
  "id": "r3-the-delete-this-entry-arm-never-taken",
  "file": "tests/test_suite_integrity.py",
  "find": "    if not pairs:\n        return (",
  "replace": "    if pairs and not pairs:\n        return (",
  "kills": [
    "tests/test_suite_integrity.py::test_the_stale_anchor_paste_back_says_which_reason_to_extend",
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_the_stale_anchor_message_says_what_happened",
    "tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites",
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_names_what_broke_it"
  ],
  "result": "killed"
}
```

**What the run printed:** `2 failed, 100 passed`.

**Which criterion this is evidence for.** Criterion 22c. The condition is made
unsatisfiable rather than deleted, so the arm stays in the source and stops being taken,
which is the shape of a refactor that keeps a branch nobody reaches. The retirement
direction of the check then prints an entry holding an empty `frozenset` where it used to
print the sentence telling the reader to delete the entry.

**What reddened, and what it named.**
`tests/test_suite_integrity.py::test_the_stale_anchor_paste_back_says_which_reason_to_extend`
at its case (c):

    assert f'delete the "{where}" entry' in gone
    AssertionError: assert 'delete the "plans/mutations/synthetic.md" entry' in '    "plans/mutations/synthetic.md": (\n        frozenset(\n            {\n\n            }\n        ),\n        "#97 left nothing stale in this file to declare",\n    ),'

**Why the two survivors matter here.**
`tests/test_suite_integrity.py::test_the_stale_anchor_message_says_what_happened` passes
a hand-written literal for that slot, so it never calls the producer, and
`tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites` drives
`stale_anchor_failure` and asserts nothing about the paste-back. Both of them are checks
that could have controlled this arm and do not, which is the finding criterion 22c is
evidence against.
`tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried` is
the standing collateral.

## Delimited naming weakened back to a substring

```json
{
  "id": "r4-delimited-naming-weakened-to-a-substring",
  "file": "tests/test_suite_integrity.py",
  "find": "        if not re.search(rf\"(?<![-\\w]){re.escape(identifier)}(?![-\\w])\", reason)",
  "replace": "        if identifier not in reason",
  "kills": [
    "tests/test_suite_integrity.py::test_the_reason_check_still_bites",
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_the_stale_anchor_paste_back_says_which_reason_to_extend",
    "tests/test_suite_integrity.py::test_the_placeholder_reason_does_not_satisfy_the_reason_check",
    "tests/test_suite_integrity.py::test_every_carried_stale_anchor_names_what_broke_it"
  ],
  "result": "killed"
}
```

**What the run printed:** `2 failed, 100 passed`.

**Which criterion this is evidence for.** Criterion 22d, which is what makes criterion 7
a decision rather than a preference. It puts back the plain `in` test the helper shipped
with on PR #93, so an id counts as named wherever it is spelled, including inside a
longer id.

**What reddened, and what it named.**
`tests/test_suite_integrity.py::test_the_reason_check_still_bites` at its case (f), the
entry holding two ids where one is a substring of the other and the reason names only
the longer:

    assert len(substring) == 1
    AssertionError: assert 0 == 1

**Nothing else substantive reds, and that is the honest reading of criterion 7.** A
substring standing in for a naming is the exact defect `unnamed_records` was added to
fix, one level down, but it is a latent hole rather than a live failure: measured over
the 53 recorded ids, no id is a substring of another id in the same record file, so the
live entry and the paste-back both answer the same thing under this mutant. The one case
that separates the two operations is the synthetic, which is why it exists.

`tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried` is
the standing collateral, and here it names **two** records rather than one, which is
worth stating because the introduction above says "the record just applied". This
record's `find` is a substring of `r1-the-reason-naming-helper-gutted`'s: both quote the
same return statement, r1 the whole of it and this one its last line. So applying this
one rots both anchors and the sweep reported:

    r1-the-reason-naming-helper-gutted: its find occurs 0 times in tests/test_suite_integrity.py
    r4-delimited-naming-weakened-to-a-substring: its find occurs 0 times in tests/test_suite_integrity.py

One failing test, two findings, and neither is evidence about the guard under test.

## The unreadable-target line deleted

```json
{
  "id": "r5-the-unreadable-target-line-deleted",
  "file": "tests/test_suite_integrity.py",
  "find": "        if count == TARGET_UNREADABLE:\n            lines.append(\n                f\"    {identifier}: {target} could not be read at all, so the anchor \"\n                \"cannot be counted\"\n            )\n        else:\n            lines.append(f\"    {identifier}: its find occurs {count} times in {target}\")",
  "replace": "        lines.append(f\"    {identifier}: its find occurs {count} times in {target}\")",
  "kills": [
    "tests/test_suite_integrity.py::test_the_stale_anchor_message_says_what_happened",
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites",
    "tests/test_suite_integrity.py::test_the_reason_check_still_bites",
    "tests/test_suite_integrity.py::test_the_stale_anchor_paste_back_says_which_reason_to_extend"
  ],
  "result": "killed"
}
```

**What the run printed:** `2 failed, 100 passed`.

**Which criterion this is evidence for.** Criterion 22e, for criterion 11a. Before it,
that arm was a promise with nothing holding it: the message test passed a count of `0`
only, so a target that could not be read at all would have been reported as
`occurs -1 times`, printing the sentinel as though it were a number of occurrences.

**What reddened, and what it named.**
`tests/test_suite_integrity.py::test_the_stale_anchor_message_says_what_happened` at the
first of the two assertions criterion 11 adds:

    assert "s-unreadable: app/icons/icon-192.png could not be read at all" in unreadable
    AssertionError

and the assertion beside it, that `occurs -1 times` does not appear, reds on the same
run under the same test.
`tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites` stays green,
which is the honest boundary between the two: that check reads `stale_pairs` and gets
`TARGET_UNREADABLE` back as a count in three cases, and never renders it, so the sentinel
reaching a reader as prose is this test's subject alone.

## The total builder gutted

```json
{
  "id": "r6-the-total-builder-gutted",
  "file": "tests/test_suite_integrity.py",
  "find": "    return sum(\n        len(stale_pairs(sweep_anchors(read(path)).counts)) for path in record_files()\n    )",
  "replace": "    return 0",
  "kills": [
    "tests/test_suite_integrity.py::test_every_recorded_anchor_matches_once_or_is_carried"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites",
    "tests/test_suite_integrity.py::test_the_stale_anchor_message_says_what_happened",
    "tests/test_suite_integrity.py::test_the_carried_stale_total_is_the_number_of_carried_records",
    "tests/test_suite_integrity.py::test_the_reason_check_still_bites",
    "tests/test_suite_integrity.py::test_the_stale_anchor_paste_back_says_which_reason_to_extend"
  ],
  "result": "killed-for-the-wrong-reason"
}
```

**What the run printed:** `1 failed, 101 passed`.

**Which criterion this is evidence for.** Criterion 22f, and it is the measurement behind
criterion 13. `computed_stale_total` is replaced with its passing value and **no
substantive control reds.** The one failure is the standing collateral, this record's own
`find` being the statement it replaces, which is why the `result` here is
`killed-for-the-wrong-reason` rather than `killed`: a mutant that reds a test for a reason
unrelated to the mutation is not a pass, and calling it one is the defect this repo keeps
finding.

**And the wrong number was printed, in that very failure, with nothing objecting.** Under
this mutant two anchors do not match exactly once, this record's own and
`g2-repeated-member`'s, so the paste-back at the end of the collateral failure should
have read `CARRIED_STALE_TOTAL = 2`. It read `CARRIED_STALE_TOTAL = 0`. That is the
defect this mutation is the measurement of, observed rather than described: the producer
answered nothing and the only thing that noticed was a reader.

**What the survivors say, enumerated, because a decision to leave something uncontrolled
is only auditable if the measurement is written down.** The value is read on one path,
into the paste-back at the end of a failing run, so
`tests/test_suite_integrity.py::test_the_stale_anchor_check_still_bites` drives
`stale_anchor_failure` in both directions and asserts nothing about the total;
`tests/test_suite_integrity.py::test_the_stale_anchor_message_says_what_happened` passes
its own hand-written total and asserts on that;
`tests/test_suite_integrity.py::test_the_carried_stale_total_is_the_number_of_carried_records`
reads the declared constant and never the producer; and neither of the two controls this
task adds,
`tests/test_suite_integrity.py::test_the_reason_check_still_bites` and
`tests/test_suite_integrity.py::test_the_stale_anchor_paste_back_says_which_reason_to_extend`,
touches it.

**What the downstream owner catches instead, which is why this is documentation and not a
hole.** A wrong number here is printed into a failure, for a reader to paste into
`CARRIED_STALE_TOTAL`. That constant's subject is the entries themselves, checked by
`tests/test_suite_integrity.py::test_the_carried_stale_total_is_the_number_of_carried_records`,
and `s2-the-declaration-deleted` in `87-stale-anchor-check.md` is the recorded proof that
that check bites. So a wrong value cannot be pasted into a green tree; it costs the reader
one round trip through a failing test. The comment above the function in the module says
the same thing, and says what the two alternatives were and why both are worse: taking the
population as an argument buys a control over arithmetic nobody has got wrong, and
comparing the value with `CARRIED_STALE_TOTAL` is `0 == 0` on the day the baseline
empties, which is a check that would rot into this task's own subject.
