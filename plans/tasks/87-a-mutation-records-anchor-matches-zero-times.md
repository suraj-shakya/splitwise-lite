# Task 87: a mutation record's anchor matches zero times

GitHub issue **#87**, "A mutation record's anchor matches zero times, and nothing reports
it". `plans/backlog.md` has no entry for it and this task adds none: the issue is the
backlog entry and this file is the implementable version, following
`plans/tasks/70-substring-assertions-on-exception-messages.md` and
`plans/tasks/82-the-unreachability-claim.md`.

**Depends on:** nothing unlanded. Two landed pieces are load-bearing and are assumed to
exist, because this task reads both: PR #84's carried-baseline mechanism in
`tests/test_suite_integrity.py` (`CARRIED_UNANCHORED_BLOCKS`, `CARRIED_TOTAL`,
`carried_entry_literal`, `carried_baseline_message`), and PR #86's
`plans/mutations/82-the-unreachability-claim.md`, which is one of the eight record files
the new check sweeps.

---

## How the numbers here were obtained

**No Bash, no `gh`, no `pytest`, no `python` and no MCP GitHub server were available to
the author of this document.** The issue body was read from a file on disk. Every count
below is a run of the ripgrep-backed Grep tool or the Glob tool with the pattern quoted
beside it, or a read of the file at the path quoted beside it, all in the worktree
`splitwise-lite-task-87` on **2026-09-08**. Anything that needs a run is written as a
criterion for the implementer to run and record, never as a result.

| What | How | Result |
| --- | --- | --- |
| files under `plans/mutations/` | Glob `plans/mutations/*` | **9**: eight record files plus `README.md` |
| fenced records | Grep ``^```json`` over `plans/mutations/` | **33**: 32 in the eight record files, one in `README.md` |
| `##` sections | Grep `^## ` over the same | **31** in the eight record files (`README.md` has seven of its own) |
| records per file | Grep `^\s*"id": ` | `16` 7, `44` 3, `57` 1, `61` 5, `65` 7, `70a` 5, `72` 1, `82` 3 |

**So the population this check sweeps is 32 records in 31 sections across eight files.**
`record_files()` at `tests/test_suite_integrity.py:1546` already excludes `README.md`, so
its example block is not one of the 32.

### The issue's 31 is a count of sections, not of records

The issue says it "swept all **31** records in the repo: 30 anchors match exactly once,
and one matches **zero** times". Re-measured, **31 is the number of `##` sections** and
the number of records is **32**. The discrepancy is one file:
`plans/mutations/61-identifiers-in-4xx-bodies.md` has four sections and five records,
because `## 4 and 5. The check itself, in both directions` carries two JSON blocks,
`blind-the-identifier-search` and `make-the-identifier-search-total` (Grep
``^## |^```json`` over that file: headings at lines 45, 69, 95 and 124, blocks at 50, 75,
106, 137 and 194).

Use 32. And note what that off-by-one is an instance of: a correct count attached to a
subject one level away from the one it names, which is the family of defect this repo has
now recorded four times, most recently in the correction under criterion 10 of
`plans/tasks/70-substring-assertions-on-exception-messages.md` ("Two was the module count
and the claim was about blocks"). It is also the whole reason criterion 10 below keys the
baseline by **record id** rather than by section heading or by position in a file.

The issue's "30 matching once" moves for the same reason, and is not restated here as a
number, because it was not fully re-measured; see the next paragraph.

### What was verified by hand, and what was not

**Fourteen of the 32 anchors were opened**: all seven in `plans/mutations/65-message-pins.md`,
all five in `plans/mutations/70a-message-block-check.md`, and two of the three in
`plans/mutations/82-the-unreachability-claim.md`. For each, the record's `find` was read
out of the record and the target file was opened at the matching lines with the
indentation and the line breaks compared.

* **Thirteen match exactly once.** `g1-weights-sum-to-zero` at `src/splitwise_lite/split.py:210`;
  `g3`, `g4`, `g5`, `g6`, `g7` at `src/splitwise_lite/balances.py:660`, `:748`, `:763`,
  `:778` and `:688`; `m1`, `m3`, `m4`, `m5` at `tests/test_suite_integrity.py:786`, `:796`,
  `:1261` and `:1767`; `m2` at `tests/test_money.py:55`; `mark-a-row-a-request-reaches` at
  `tests/test_error_messages.py:786`; `record-nothing` at `tests/conftest.py:179`.
* **One matches zero times**, and it is the one the issue names. See the section below.
* **Eighteen were not opened**: the seven in `16-incompleteness-signal.md`, three in
  `44-the-empty-roster-message.md`, one in `57-fragment-flattening.md`, five in
  `61-identifiers-in-4xx-bodies.md`, one in `72-the-feed-swallows-its-own-errors.md`, and
  `reword-a-marked-reason` in `82-the-unreachability-claim.md`.

**The full population is therefore not stated in this document, deliberately.** The
instrument for measuring it is the check this task builds, and criterion 17 makes that
check print the literal to paste back. The one command that produces the number is:

```
uv run python -m pytest tests/test_suite_integrity.py -k stale_anchor -x -q
```

Whatever it prints is the number; criterion 44 has the PR state it. No number in the
shipped code is a hand count, which is `plans/tasks/70-...md`'s constraint and is kept
here unchanged.

### The instance, re-measured

`plans/mutations/65-message-pins.md:53`, record id `g2-repeated-member`, carries

```
"find": "        raise InvalidSplit(\n            f\"member_ids names a member more than once: {list(ordered)}\"\n        )"
```

and `src/splitwise_lite/split.py:343` now reads, on one line,

```
        raise InvalidSplit("member_ids names a member more than once")
```

with the comment above it saying the refusal names the payload key and not the ids. So
the anchor matches **zero** times, the cause is #61 removing `{list(ordered)}`, and the
issue's diagnosis is confirmed by opening both files.

Two further reads that bear on what to do about it:

* **The record's node ids are still live.** `tests/test_split.py:408` defines
  `test_split_equally_rejects_a_repeated_member` and `:403` defines
  `test_split_equally_rejects_an_empty_member_list`, which are the record's `kills` and
  `survives`. So the record's lists are intact and only its anchor has rotted.
* **The guard's message has changed, not just its layout.** The record quotes what the
  guard printed in 2026-09-07: `member_ids names a member more than once: ['ali', 'bo', 'ali']`.
  Today's guard cannot print that, because the ids are gone. That is what makes this a
  retirement rather than a repair; see the decision below.

### Two appliers, one precondition

* `plans/mutations/README.md`'s recipe asserts `source.count(record['find']) == 1` after
  reading the target with `pathlib.Path.read_text(encoding='utf-8')`.
* `tests/shell_harness.mjs:9118` computes `source.split(find).length - 1` and throws a
  harness error, exit status 2, when it "matched N times ... not exactly once".

So **exactly once is the precondition of both languages' appliers**, not a Python-side
nicety, and the check below is a check on that precondition and nothing else.

---

## The three decisions the issue left open, settled

### 1. A test, not something to remember

**The check is a pytest test in `tests/test_suite_integrity.py`**, in the existing
`# --- The mutation records (#60) ---` section, beside the three checks that already read
this population.

Not a script under `scripts/`: `plans/mutations/README.md` already refuses a mutation
applier there and `test_scripts_holds_exactly_the_promised_python_files` pins that
directory. Not a documented sweep somebody runs at review time either. **"A check somebody
has to remember to run" is open issue #75**, and a spec that creates a second one makes
that issue worse while claiming to close this one. The module is also the right home
mechanically: it imports the standard library and `pytest` only and nothing from
`splitwise_lite`, and this check reads `src/` files as **text**, never by importing them,
so it still runs on a checkout where the package will not import.

### 2. `g2-repeated-member` is retired, not repaired

**Decision: the record's seven keys are left exactly as they are, the section gains a
dated retirement note, and the baseline carries it. The `find` is not re-derived against
today's `split.py`, and the record is not deleted.**

The reason, stated so nobody re-argues it:

* **What a record preserves is a measurement, not a string.** `g2`'s value is "with this
  guard deleted, `test_split_equally_rejects_a_repeated_member` printed `DID NOT RAISE
  InvalidSplit`, and the message the live guard printed was
  `member_ids names a member more than once: ['ali', 'bo', 'ali']`". Editing `find` to
  today's one-line raise would leave every one of those sentences in place beside an
  anchor they were not measured against. That is a correct measurement attached to the
  wrong subject, which is the defect this repo keeps finding and the one the section above
  catches the issue itself in.
* **Re-deriving from source is the thing #65's discipline forbids.** That file's own
  intro says the quoted message is "captured from a run against the unmutated tree, and it
  is what each anchored pattern was derived from", and PR #62 is the proof that an anchor
  written by reading the guard settles nothing. Re-deriving `find` by reading `split.py`
  today, without a run, breaks that rule in the one file that states it.
* **Deleting the section is worse than either.** It is the only record of pin 2's
  coverage in the #65 audit, and deleting evidence to make a check green is the failure
  mode the whole family of checks in that module exists to refuse.
* **What repair would actually be, recorded so the next person can do it:** run the
  mutation again against today's tree, capture the message from that run, and write a
  **new** record with a new id, in a new file or in `plans/mutations/87-stale-anchor-check.md`.
  That is a fresh measurement and it is legitimate; it is simply not this task, and the
  dated note says so.

A consequence worth naming: this leaves the baseline with exactly one entry, which means
every direction of the new check has a **live** subject rather than a synthetic-only one.
Compare `m3-startswith-branch-deleted` in `plans/mutations/70a-message-block-check.md`,
which measured that the `.startswith` branch of #70's accepted set has no live subject
anywhere in the suite. Having one is better evidence, and it is a second reason not to
close the population to zero in this task.

### 3. The baseline shape: what is copied from PR #84 and what is not

**Copied, deliberately, so this is not a second dialect:**

* keyed by a **POSIX path** relative to the repo root, one entry per file;
* the value is a **frozenset of `(subject, integer)` pairs plus one reason string**;
* **never a line number and never an ordinal**, for #84's own two reasons: line numbers
  churn on every edit above them and an ordinal is bound to its subject only by position;
* **set equality per file in both directions**, so an undeclared stale anchor reds and a
  declared entry that has outlived its subject reds and names itself;
* **one declared integer** for the total, so growing the list is a one-line diff in a
  place a reviewer reads;
* **a reason per entry**, at the same `MINIMUM_REASON` floor of 20 characters that
  `# unanchored:` already carries;
* **the failure prints the exact literal to paste back**, following `carried_entry_literal`
  and `carried_baseline_message`, and labels which direction the paste-back is for;
* **one hatch, not two**: no new JSON key, no per-record marker comment, no decorator.
  `REQUIRED_KEYS` is an exact set and does not change.

**Not copied, each with its reason:**

* **The total is a count of records, not a sum of the integers.** #84's counts are block
  counts, so summing them is the population. Here the integer is a **match count**, which
  is 0 or 2 or more by construction, so summing them would produce 0 today while one
  record in the repo cannot be re-run. `CARRIED_STALE_TOTAL` is therefore the number of
  carried records.
* **The reason names the change that broke the anchor, not a retiring slice.** There is no
  audit programme here to commit anybody to, so `RETIRING_SLICE` has no analogue;
  `BREAKING_CHANGE` demands a `#NN` reference instead. That is available for every change
  that can break an anchor: the five most recent commit subjects on `master`, as reported
  in this session's environment, each carry one (`d987b64 (#86)`, `6c5e144 (#85)`,
  `be9c49b (#84)`, `a595330 (#83)`, `bea0da7 (#81)`).
* **"May only shrink" does not carry over, as a check or as a convention.** For #70 a new
  unanchored block is never legitimate, so the convention makes sense. Here a correct
  source change legitimately rots an anchor: **#61 was right**, and that is the issue's own
  central point. So this list is expected to grow, what the check refuses is an
  **undeclared** stale anchor, and no document written by this task may say the list only
  shrinks. Writing that sentence would put a rule reading broader than its mechanism into
  the rules file, which is the complaint issue #70 was filed about.
* **The check is not parametrised per file.** It iterates inside one test, like the two
  existing checks in that section, because `record_files()` asserts on an empty directory
  and an assertion evaluated at collection time is a collection error rather than a
  failing test. A module-level, assertion-free second glob of the same directory would be
  two sources of truth for one population.
* **The placeholder reason must not satisfy the reason check.** Measured: #84's
  `NO_REASON_YET` at `tests/test_suite_integrity.py:1124` reads
  `<why this module is carried, and which of 70b to 70h retires it>`, which is over 20
  characters and matches `RETIRING_SLICE` on `70b`, so pasting the printed literal
  unedited clears both of that baseline's reason checks. This task's placeholder carries
  no `#NN`, and criterion 14 is a test on exactly that.

---

## Goal

A committed mutation record whose anchor no longer matches its target file exactly once
is a failing test that names the file, the record id, the target and the match count, so
a record can stop being re-runnable only in the open. The one record this is already true
of, `g2-repeated-member`, is declared, dated and explained where a reader of that record
will see it, rather than silently repaired into something that measures a different guard.

What this task does **not** reach, stated here so a green suite is not misread: it does
not re-run any recorded mutation and does not verify any recorded `result`, so a record
whose anchor matches is proven **appliable**, not proven **correct**.

---

## Acceptance criteria

### Where the check lives

1. `tests/test_suite_integrity.py` gains one new subsection, at the end of the existing
   `# --- The mutation records (#60) ---` section and headed in the same `# --- ... ---`
   comment style the module's other section headers use, naming issue #87. **No new test module and no new file under
   `scripts/`**, so `test_scripts_holds_exactly_the_promised_python_files` stays green
   without being touched.
2. That module's imports do not grow beyond the standard library and `pytest`, and
   nothing from `splitwise_lite` is imported, so the claim in its docstring at lines 39 to
   41 stays true. No test enforces this, which is why it is written down: it is checked by
   reading the diff's import block.
3. The new code reuses `record_files`, `read`, `posix`, `JSON_BLOCK`, `record_sections`,
   `mutation_record_problems`, `MINIMUM_REASON`, `DATED_NOTE` and `blockquote_run`. It
   introduces **no second way of reading a file**: the diff contains no `open(`, no
   `read_bytes` and no `read_text` outside `read()`. `read()` translates newlines, which is
   what makes a CRLF checkout and an LF checkout produce the same match counts and both CI
   legs agree, and it is also byte-for-byte what the README's recipe does
   (`target.read_text(encoding='utf-8')`).

### What a stale anchor is, mechanically

4. **The anchor is the record's `find`.** The file it is matched against is the file named
   by that same record's `file` key, resolved as `REPO / record["file"]`. The match count
   is `text.count(find)` over the text `read()` returns for that path.
5. **The required count is exactly one.** Zero is a finding and two or more is a finding.
   The reason is not symmetry: it is that both appliers assert exactly this, the README
   recipe with `source.count(record['find']) == 1` and `tests/shell_harness.mjs:9119` with
   `hits !== 1`, so a green check is a statement that the recipe will run. For the same
   reason the check uses `str.count` and **not** a regex, a whitespace-normalised
   comparison or a fuzzy match: a looser operation would make green mean something the
   recipe does not promise.
6. `result` is not consulted. A `survived` or `killed-for-the-wrong-reason` record's
   anchor is checked on the same terms as a `killed` one.
7. Three unreadable-target cases are findings, and none of them is an uncaught exception
   escaping the test: the target does not exist, the target is a directory, and the target
   is not decodable as UTF-8. They are recorded with the sentinel match count
   `TARGET_UNREADABLE = -1`, so that they can be carried like any other finding. **A
   future refactor that deletes a module must not be blocked with no way to declare the
   records that pointed at it.** Red if broken: the self-test feeds a record naming a path
   that does not exist and asserts a finding rather than an exception.
8. A record that `mutation_record_problems` rejects is **skipped** by this check, so one
   malformed record produces one failure and not two, and
   `test_every_recorded_mutation_is_machine_readable` stays its owner. The self-test
   **proves the pairing rather than claiming it**: the same synthetic record is asserted to
   yield no stale-anchor finding *and* to yield a non-empty
   `mutation_record_problems(...)`. A criterion that only asserted the skip would be a
   claim about this check's silence with nothing establishing that anybody else speaks.
9. The check depends on ids being unique within a file, which
   `mutation_record_problems` enforces through its `seen` set. A comment says so, and says
   that this is why criterion 8 skips rather than guesses.
10. `plans/mutations/README.md` is not scanned. `record_files()` already excludes it, and a
    comment records why widening the sweep to it would be wrong: its single block is the
    format's illustration and its `file` is the deliberately fictional
    `src/splitwise_lite/example.py`, so the sweep would red on the document that defines
    the format. Somebody will read the exclusion as arbitrary and reach to widen it; the
    comment is what refuses that, in the manner the `SPECIFIES_THE_SCAN` comment already
    does at `tests/test_suite_integrity.py:1956`.
11. The check asserts that it examined **at least one usable record**, and the assertion
    text says that a green run over zero records is the shape of defect this module exists
    to refuse. Red if broken: change `JSON_BLOCK` to a pattern that matches nothing and
    this assertion fires instead of the suite going green.

### The carried baseline

12. `CARRIED_STALE_ANCHORS: dict[str, tuple[frozenset[tuple[str, int]], str]]` maps a
    record file's POSIX path to a frozenset of `(record id, match count)` pairs and one
    reason string. **Keyed by record id**, never by section heading, never by a `##`
    ordinal, never by a line number. The reason is measured, not stylistic: the issue's own
    31 was a section count and one section in this repo holds two records, so a section is
    not a subject an entry can be bound to.
13. `test_every_recorded_anchor_matches_once_or_is_carried` asserts **set equality per
    record file, in both directions**, and the failure names the offending entries in each
    direction: an anchor that is stale and not carried, and a carried entry that is no
    longer stale.
14. `CARRIED_STALE_TOTAL` is a declared integer, asserted by
    `test_the_carried_stale_total_is_the_number_of_carried_records` to equal the sum of the
    frozenset lengths, which is the number of carried records and **not** the sum of the
    match counts. Red if broken: add a second carried pair without bumping the integer.
15. `test_every_carried_stale_anchor_names_what_broke_it` asserts each reason is at least
    `MINIMUM_REASON` characters and matches `BREAKING_CHANGE = re.compile(r"#\d+")`, so an
    entry cannot be added with a reason that names no change.
16. The placeholder reason the paste-back prints for a file that has no entry yet contains
    no `#NN` and no digits at all, and
    `test_the_placeholder_reason_does_not_satisfy_the_reason_check` asserts
    `BREAKING_CHANGE.search(...) is None` over it and that it is at least `MINIMUM_REASON`
    characters. Red if broken: put an example issue number in the placeholder. This is the
    deliberate divergence from `NO_REASON_YET`, whose text matches its own
    `RETIRING_SLICE`.
17. The failure ends with the exact `CARRIED_STALE_ANCHORS` entry and the
    `CARRIED_STALE_TOTAL` line as they should now read, following `carried_baseline_message`
    and `stale_digest_message`, and **labels which direction the paste-back is for**. In the
    undeclared direction it says plainly that pasting carries the rot instead of reporting
    it, and gives the two real answers: re-run the mutation and write a fresh record, or
    declare it with a reason naming the change that broke it.
18. The message distinguishes two cases the check itself **cannot** tell apart, and says
    that it cannot: an anchor that matched once and has since rotted, which is what a
    declaration is for, and an anchor that **never** matched, which means the record was
    never run and the answer is to run it. Without this the cheapest way to green a
    fabricated record is to declare it, which is the "cheapest resolution is a lie" failure
    `stray_node_id_message` was rewritten to avoid.
19. In the stale direction the message says which of three things happened to the carried
    entry, because the fix differs: the anchor matches exactly once now, so delete the
    entry; no record with that id exists in that file any more, so delete the entry; or the
    match count has changed, so update the pair.
20. `test_every_carried_stale_anchor_carries_a_dated_note_in_its_record` asserts that the
    `##` section holding each carried record carries a dated note, recognised by
    `DATED_NOTE` inside a `blockquote_run`, reusing both helpers rather than re-deriving
    either. This is the criterion that puts the honesty where a reader of the record will
    see it, rather than only in a constant in a test file. Its live subject is
    `g2-repeated-member`; red if broken by deleting the note from that section.
21. **The baseline may legitimately become empty**, and nothing asserts it is non-empty.
    The self-tests cover the empty case, so the mechanism does not rot into a check that
    cannot fail on the day somebody repairs the last entry.
22. No document this task writes or edits says the baseline may only shrink, as a check or
    as a convention. What it says instead is that the list is expected to grow when a
    correct change breaks an anchor, that what is refused is an undeclared stale anchor,
    and that what holds the list honest is a reviewer reading a diff that includes a bump
    to a declared integer.

### `g2-repeated-member`

23. The `g2-repeated-member` JSON block in `plans/mutations/65-message-pins.md` is
    **unchanged**, all seven keys, byte for byte. Checked by reading the diff: that block
    appears in it only as context, if at all.
24. Its `##` section gains a dated note, in this repo's correction-note form, carrying all
    of: the `find` fragment that no longer occurs, `{list(ordered)}`; the change that
    removed it, **#61**; what `src/splitwise_lite/split.py` says today, quoted, with the
    path and the line; the tree the record was taken on, `7bf518c` on 2026-09-07, which the
    file's intro already records; and the statement that repair means re-running the
    mutation against today's tree and writing a **new** record with a new id, not editing
    this one.
25. `CARRIED_STALE_ANCHORS` carries exactly `("g2-repeated-member", 0)` under
    `plans/mutations/65-message-pins.md`, with a reason at or above the floor that names
    **#61**.
26. The intro of `plans/mutations/65-message-pins.md`, which says at lines 11 to 13 that
    "The suite deliberately does not re-verify these anchors", is corrected in place in the
    quote-and-retract form: the retired sentence is quoted inside a dated note rather than
    deleted, and the replacement says what is now checked. Leaving it would put a false
    statement about the suite in the very file that holds the one carried entry.
27. The record is **not** deleted and its `find` is **not** re-derived. If the
    implementer disagrees with the decision in section 2 above, that is a comment on this
    task rather than a licence to do the other thing: the reasons are recorded there and a
    different answer needs to retire them in writing first.

### The documents that currently claim the opposite

28. `plans/mutations/README.md`'s section `## The suite does not re-verify these anchors`
    is retired in place with a dated note that quotes the sentence being retired, and is
    replaced by a section stating **exactly** what the suite now does and does not do:
    that every record's `find` must match its target exactly once **or be declared stale
    with a reason**, that no record is re-run and no `result` is verified, that no repair
    is demanded, and that the anti-ossification argument is answered by the declaration
    route rather than abandoned. A reader of that file must not be able to finish it
    believing either the old claim or that the suite now proves records correct.
29. The recipe section of that README says that the assertion it already tells you not to
    skip is now also checked in the suite, and names the check.
30. Rule (e) of `.claude/rules/testing.md`, "A mutation is recorded as an anchor and a
    replacement, never as a sentence", keeps its existing scar sentence verbatim and gains:
    the exactly-once rule; the literal names
    `test_every_recorded_anchor_matches_once_or_is_carried`, `CARRIED_STALE_ANCHORS` and
    `CARRIED_STALE_TOTAL`; the declaration route with the honest statement required by
    criterion 22; and one sentence on the `g2` decision, that a rotted anchor is retired
    with a dated note rather than re-derived, because re-deriving changes what the record
    measured.
31. `THE_THREE_BULLETS` is kept **verbatim**, so
    `test_the_testing_rules_keep_the_three_they_had` stays green untouched.
32. `ENFORCING_SYMBOLS` gains those three names, so
    `test_the_testing_rules_name_the_mechanisms_that_enforce_them` covers them and
    `test_every_named_mechanism_resolves_to_something_that_exists` reds if a later rename
    leaves the rule naming something gone. Red if broken: add the tuple entries without
    writing the names into the rules file and the first of those goes red; rename the check
    and the tuple entry together and the second one does.
33. The module docstring of `tests/test_suite_integrity.py` is corrected where this task
    moves a count in it. Two places, both measured: line 3 says "**Four** failures in this
    repo reported success without exercising the thing they named" and enumerates "#67,
    #65, #70 and #60"; and lines 36 to 37 say "the **last two** checks here keep those
    records machine readable so the next person can re-run one instead of reconstructing it
    from a sentence". Both are wrong once this lands, and the second one is wrong in the
    load-bearing direction: it promises re-runnability, which is the promise issue #87 is
    about.
34. **`CLAUDE.md` and `README.md` do not change.** This task adds no capability, retires
    none and creates no directory, so neither document's claim list moves and neither the
    literal in `tests/test_web_shell.py` nor the parity between the two documents is
    touched, exactly as for task 70a. Measured, so the omission is a decision rather than
    an oversight: `CLAUDE.md`'s `tests/` bullet already names two of the four checks in
    that module, omitting the #70 block check and the #58 documents check, both of which
    landed without editing it. Under-claiming is the safe direction here; over-claiming is
    the defect.

### Proof that the check can fail

35. `test_the_stale_anchor_check_still_bites` is written in the shape of
    `test_the_pin_check_still_bites` and `test_the_node_id_check_still_bites`: synthetic
    records, one per shape, each labelled with the branch it is the positive control for.
    The shapes it must cover, at minimum:
    a. an anchor matching **exactly once** in a real file is not a finding;
    b. an anchor matching **zero** times is a finding naming the file, the id and the count;
    c. an anchor matching **twice** is a finding, and this is the case that distinguishes
       "exactly once" from "at least once";
    d. a record whose target **does not exist** is a finding with `TARGET_UNREADABLE`, not
       an exception;
    e. a record whose target is a **directory** is the same;
    f. a record `mutation_record_problems` rejects yields **no** stale-anchor finding, and
       the same synthetic yields a problem from that helper, per criterion 8;
    g. a carried pair equal to the found pair is not a failure, in either direction;
    h. a carried pair whose count no longer agrees is a failure, and the message says the
       count changed rather than that the anchor is fine;
    i. a file with **no** carried entry and no stale anchor is not a failure, which is the
       empty-baseline case of criterion 21.
    A case that holds **by construction** under any mutation of the implementation is
    labelled as such in a comment saying what it does guard against, in the manner of the
    `NOT_A_PIN_RE_MATCH` comment. A section of self-tests that cannot fail is the defect
    this module exists to refuse.
36. `test_the_stale_anchor_message_says_what_happened` asserts the message carries, given
    a synthetic path, id, target and count: the POSIX record path and the record id; the
    target path and the match count; that exactly once is the precondition of both
    appliers, naming the README recipe and the harness; the rotted-versus-never-run
    distinction of criterion 18; the two real answers of criterion 17; and the labelled
    paste-back ending in the `CARRIED_STALE_TOTAL` line.
37. `plans/mutations/87-stale-anchor-check.md` records **at least three** mutations, in the
    format of `plans/mutations/65-message-pins.md` as amended by criterion 13 of
    `plans/tasks/70-substring-assertions-on-exception-messages.md`, each with a **named
    surviving control**:
    a. **A healthy anchor broken deliberately.** Edit the `find` of a record that matches
       once, in a committed record file, so that it matches zero times. The record names
       the new check as what reds and names the file and the id it printed. Its `survives`
       must list `test_every_recorded_mutation_is_machine_readable`,
       `test_a_mutation_record_holds_no_prose_only_section` and
       `test_every_node_id_a_record_names_is_one_it_lists`, all three staying green. **That
       trio surviving is the measured form of the issue's central claim**, that nothing
       reported this, and it belongs in the record rather than in a PR body.
    b. **The undeclared direction.** Delete the `("g2-repeated-member", 0)` pair from
       `CARRIED_STALE_ANCHORS` and record what reds and what it names.
    c. **The stale direction.** Make `g2`'s anchor match once again, by editing that
       record's `find` to today's one-line raise, while the entry still declares it. The
       stale direction must red and name the entry. This is the proof that the second
       direction of criterion 13 is not decorative, and it is the analogue of criterion 22b
       of task 70.
    A fourth is welcome and cheap if the exactly-once decision is to be more than a claim:
    weaken the comparison from `== 1` to `>= 1` and record that case (c) of criterion 35
    reds.
38. **The anchor-into-a-record-file trap is recorded in that file**, because it will cost
    somebody an hour otherwise: a record file quotes its own message text in prose, so a
    plain sentence is not a unique anchor in it. Measured example: in
    `plans/mutations/65-message-pins.md` the text
    `weights sum to zero, so there is no share to divide the total into` occurs twice, at
    line 21 inside the JSON `find` and at line 35 in the "message the guard actually
    prints" quote. An anchor into a record file therefore includes enough of the JSON
    escaping, a `\"` or a `\n`, to sit only inside the block.
39. Every mutation run sets `PYTHONDONTWRITEBYTECODE=1` and reverts with
    `git checkout -- <file>` before the next one, per `.claude/rules/testing.md` and the
    README recipe, and the recipe's exactly-once assertion is not skipped.
40. The new record file passes the checks that already exist over that directory: seven
    keys and no others, no prose-only section, and criterion 13 of task 70's node-id rule,
    so a node id in prose is a claim listed in `kills` or `survives` and a citation is
    written bare.

### Not paying for this with somebody else's check

41. `CARRIED_TOTAL`, which reads **107** at `tests/test_suite_integrity.py:1118`, does not
    move, and `CARRIED_UNANCHORED_BLOCKS` gains no entry. Any new `pytest.raises` block in
    the new code that reads the exception's message is anchored one of the four accepted
    ways. #70's baseline shrinks only, and this task must not be what grows it.
42. No module-level name in `tests/test_suite_integrity.py` is defined twice, which
    `test_no_test_module_defines_a_name_twice` enforces with no allowlist.
43. This task's own edits must not rot an anchor. Measured, the risk on the known
    population is low: none of the five anchors in
    `plans/mutations/70a-message-block-check.md` quotes the module docstring or
    `ENFORCING_SYMBOLS`; `m4`'s anchor is the `def` line of
    `test_every_message_block_is_anchored_or_carried` at `:1261` and `m5`'s is
    `    module, _, bare = identifier.partition("::")` at `:1767`. So **prefer the edit that
    leaves an anchor intact**, for instance appending to `ENFORCING_SYMBOLS` rather than
    reformatting it. If a break is unavoidable, it is declared with a reason naming **#87**
    and its record's section gets a dated note, and the PR says which anchor this task
    broke and why the edit could not avoid it.

### Verification, and what the PR states

44. The PR states `CARRIED_STALE_TOTAL` as the **check** computed it, the number of records
    the check examined, and whether that number is 32. It notes that this is the first
    machine-produced sweep of this population, that the issue's sweep was by hand, and it
    reconciles with this document: 32 records in 31 sections, and the issue's 31 was a
    section count. If the examined count is not 32, the PR says what moved.
45. Every module the branch touches is run in full by name. The rest of the suite is run in
    chunks by module and the PR states the chunk boundaries and the summed counts.
    Collection counts come from `uv run python -m pytest --collect-only -q`. The command is
    `uv run python -m pytest`, never `uv run pytest`.
46. The whole-suite gate is CI: both legs of `.github/workflows/tests.yml` must be green,
    and a PR whose base has moved is brought up to date and re-run. That matters more than
    usual here, because a record's target is a file another PR may edit, so this check's
    result against an older `master` says nothing about the merge commit.
47. **No criterion in this task requires a browser.** Everything is text read by Python and
    pytest runs, nothing routes to issue #80, and no verdict may rest on an unrun manual
    check.

---

## Out of scope

* **Repairing `g2-repeated-member`**, by re-deriving its `find` or by re-running its
  mutation. Decided in section 2 above, with reasons, and criterion 27 makes it explicit.
* **Re-running any recorded mutation, or verifying any `result`.** That is ossification of
  exactly the kind `plans/mutations/README.md` warns about, it would put 32 mutation runs in
  CI, and it is not what the issue asks for. A green check means a record is **appliable**,
  not that its recorded verdict still holds, and criterion 28 makes the README say so.
* **Verifying that a record's `kills` and `survives` node ids still name live tests.** This
  is a second, real rot population and it is a different check. It is out for a reason
  rather than by omission: it needs a collected-test list, so it needs `--collect-only` or
  an `ast` walk of `tests/`, and the parametrised ids in
  `plans/mutations/82-the-unreachability-claim.md` make a purely textual comparison
  unreliable. Nobody measured that population; whoever files that issue can start with
  `uv run python -m pytest --collect-only -q` against the ids in the record files. For the
  one record #87 names, both node ids are live, measured at `tests/test_split.py:403` and
  `:408`.
* **The committed mutants**, `MUTANT_A` onwards in `tests/test_shell_behaviour.py`.
  `mutated()` already re-asserts those anchors on every run, which is the difference
  between a mutant that is re-run and a record that is re-runnable, and the README already
  states it.
* **Adding, removing or optionalising a JSON key.** `REQUIRED_KEYS` is an exact set and
  `mutation_record_problems` refuses extras, so a per-record "known stale" flag would be a
  format change for all 32 records and a self-exemption with no declared integer anybody
  reads. The baseline is the answer instead.
* **A mutation applier or any new file under `scripts/`.** Refused already by the README
  and pinned by `test_scripts_holds_exactly_the_promised_python_files`.
* **Issue #75**, the checks somebody has to remember to run. This task must not add to that
  population, which is criterion 1's reason for being a test, but it does not close it.
* **Issue #70's audit slices** and its baseline. Criterion 41 is the whole of the contact.
* **Any change under `src/`, `app/` or `scripts/`.** `git diff --stat` shows no path under
  any of the three, and therefore `SHELL_DIGEST` in `app/sw.js` does not move. In
  particular, an `app/` anchor found stale is declared, never fixed by editing `app/`.
* **Deleting, renaming, loosening, skipping or xfailing any test**, and deleting any
  mutation record or record section.
* **Line-ending unification.** `.gitattributes` pins `*.sh` to LF and nothing else. The
  check reads through `read()`, which normalises, exactly as the README recipe does; the
  harness reads `readFileSync(path, 'utf8')`, which does not, so on a CRLF checkout a
  multi-line anchor into `app/app.js` or `app/api.js` could satisfy this check and still
  refuse a harness run. That residual is recorded in a comment beside the counter and is
  not fixed here: reading bytes instead would make every multi-line anchor match zero times
  on a CRLF checkout and red the whole check on one CI leg.

---

## Constraints

* **Files this task may touch, and no others in either direction:**
  `tests/test_suite_integrity.py`, `.claude/rules/testing.md`,
  `plans/mutations/README.md`, `plans/mutations/65-message-pins.md`,
  `plans/mutations/87-stale-anchor-check.md` (new), and this file.
* `tests/test_suite_integrity.py` imports the standard library and `pytest` only and
  nothing from `splitwise_lite`. The check reads `src/` files as text and never imports
  them, which is what keeps that true.
* `DATED_NOTE` and `blockquote_run` are defined further down the module than the mutation
  section, at lines 1997 and 2000. Both are resolved when the function body runs, so
  nothing needs moving and no code is duplicated to avoid a forward reference.
* One hatch, not two. The declaration route is `CARRIED_STALE_ANCHORS` with a reason at
  `MINIMUM_REASON`; no marker comment, no per-file skip, no decorator, no JSON key.
* Each check over this directory states one guarantee and none restates another's:
  `test_every_recorded_mutation_is_machine_readable` owns "a record parses and is
  complete", `test_a_mutation_record_holds_no_prose_only_section` owns "a section records a
  mutation rather than describing one", `test_every_node_id_a_record_names_is_one_it_lists`
  owns "a node id in prose is one the record lists", and the new check owns "a complete
  record's anchor matches its target exactly once, or is declared". A record that fails the
  first is not reported by the new one.
* No number in the shipped code is a hand count. The check prints the literal to paste
  back, and that is the only sanctioned way the baseline is maintained.
* No entry is keyed by position. A record is named by its file and its id.
* Every mutation is recorded as an anchor and a replacement, never as a sentence, and every
  Python mutation run sets `PYTHONDONTWRITEBYTECODE=1`.
* A correction retires the wording it replaces by quoting it inside a dated note, in this
  repo's committed form. Criteria 26, 28 and 33 are corrections, not edit-aways.
* `uv run python -m pytest`, never `uv run pytest`.

---

## Size

One new subsection in one test module, one new constant pair, four self-tests plus a
message test, three document corrections and one record file with three mutations. It is
comparable to the #60 half of `plans/tasks/60-65-67-checks-that-could-not-fail.md`, and
smaller than 70a, which it borrows its shape from. The sweep it enables is what the issue
asked for; the eighteen anchors nobody has opened are measured by running it, not by hand.
