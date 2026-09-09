# Task 97: the reason-naming check has no control

GitHub issue **#97**, "The reason-naming check has no control, and gutting its helper
stays green". `plans/backlog.md` holds twenty numbered product entries, 1 to 18 plus
9a and 12a, and no entry for this, and this task adds none: the issue is the backlog entry
and this file is the implementable version, following
`plans/tasks/87-a-mutation-records-anchor-matches-zero-times.md`, which is the task that
landed the checks this one is about.

**Depends on:** nothing unlanded. One landed piece is load-bearing and is assumed to
exist, because every criterion below reads it: PR #93's `# --- The stale-anchor check
(#87) ---` subsection of `tests/test_suite_integrity.py`, with `CARRIED_STALE_ANCHORS`,
`CARRIED_STALE_TOTAL`, `unnamed_records`, `stale_anchor_entry_literal`,
`computed_stale_total`, `spelled_stale`, `dated_note_problems` and the eight tests that
sit in it, plus `plans/mutations/87-stale-anchor-check.md` and the amended
`plans/mutations/README.md`.

---

## How the numbers here were obtained

**No Bash, no `gh`, no `pytest`, no `python` and no MCP GitHub server were available to
the author of this document.** The issue body was read from a file on disk. Every count
below is a run of the ripgrep-backed Grep tool or the Glob tool with the pattern quoted
beside it, or a read of the file at the path quoted beside it, all in the worktree
`splitwise-lite-task-97` at master `0f6e8df` on **2026-09-09**. Anything that needs a run
is written as a criterion for the implementer to run and record, never as a result.

Line numbers below are measured at `0f6e8df` and every one of them is given with the
anchor text at that line, because line numbers in this module have gone stale three times
on one branch and this task adds tests above and below other people's code.

| What | How | Result |
| --- | --- | --- |
| record files swept | Glob `plans/mutations/*` | **11** record files plus `README.md` |
| recorded records | Grep `^\s*"id": ` over `plans/mutations/` | **47** in the 11 files, one more in `README.md`'s illustration |
| record ids that are a substring of another id **in the same file** | read of all 48 matched lines | **none** |
| records anchored into `tests/test_suite_integrity.py` | Grep `"file": "tests/test_suite_integrity\.py"` | **8**: `s2`, `s4`, `s5`, `s7` in `87-stale-anchor-check.md` and `m1`, `m3`, `m4`, `m5` in `70a-message-block-check.md` |
| tests in the `#87` subsection | read of lines 1955 to 2923 | **8** |
| occurrences of `EXTEND THIS REASON` in the repo | Grep | **1**, the producer at `:2235`; no test reads it |
| call sites of `stale_anchor_entry_literal` | Grep | **1**, `:2383` |
| call sites of `computed_stale_total` | Grep | **1**, `:2384` |
| call sites of `unnamed_records` | Grep | **2**, `:2233` and `:2899` |

The one number nobody can get without running something is this module's test count. The
issue reports `100 passed` at `0f6e8df` and `plans/mutations/87-stale-anchor-check.md`
records `100` collected at `df507b3`. This task adds tests, so that number moves;
criterion 30 has the implementer measure it with
`uv run python -m pytest tests/test_suite_integrity.py --collect-only -q` and record it.

### The measurement this task is built on, done by reading rather than by running

The diagnostic is the one in the issue: replace a helper's body with its passing value
and see whether anything reds. It is decidable by reading when a helper has one call site
and every assertion over the value that call site produces can be enumerated. That is
what the table below is. **Every row is still written as something the implementer runs
and records**, because a read is weaker evidence than a run and this task is about
exactly that difference.

| helper | gutted to | what reds today | verdict |
| --- | --- | --- | --- |
| `anchor_match_count` (`:2090`) | `return 1` | cases (b) to (e) of `test_the_stale_anchor_check_still_bites` | controlled |
| `sweep_anchors` (`:2115`) | an empty `AnchorSweep` | case (a), `once.counts == {"s-once": 1}` | controlled |
| `stale_pairs` (`:2144`) | `return set()` | cases (b) to (e); and `s4` records the weakening | controlled |
| `unnamed_records` (`:2151`) | `return []` | **nothing** | **uncontrolled** |
| `spelled_stale` (`:2170`) | `return ""` | `"occurs 0 times in pyproject.toml"` in case (b) | controlled, **except two branches**: the `TARGET_UNREADABLE` arm at `:2175` to `:2179` and the `targets.get(..., "the file its record names")` fallback at `:2174`, neither of which any assertion reaches |
| `spelled_resolved` (`:2185`) | `return ""` | three assertions in `test_the_stale_anchor_message_says_what_happened` | controlled, all three arms |
| `stale_anchor_entry_literal` (`:2212`) | `return ""` | **nothing** | **uncontrolled, the whole function**, including the marker at `:2234`, the pair listing at `:2229` and the `if not pairs` arm at `:2224` |
| `computed_stale_total` (`:2253`) | `return 0` | **nothing** | **uncontrolled** |
| `stale_anchor_message` (`:2260`) | `return ""` | `test_the_stale_anchor_message_says_what_happened` | controlled |
| `stale_anchor_failure` (`:2360`) | `return None` | cases (b) and (h) | controlled |
| `section_holding_record` (`:2416`) | `return None` | case (a) of the note test, and the live note check | controlled |
| `dated_note` (`:2429`) | `return []` | case (a) of the note test | controlled |
| `dated_note_problems` (`:2445`) | `return []` | cases (b) to (e) of the note test | controlled |

Why `unnamed_records` gutted reds nothing, in full, because a fix that does not understand
this reintroduces it. It has two call sites. At `:2899` the value is bound to `missing` and
`assert not missing` follows, and `CARRIED_STALE_ANCHORS` holds one entry carrying one
record, `("g2-repeated-member", 0)`, whose reason opens with that record's id, so the
correct answer over the live population is `[]` and so is the degenerate one. At `:2233`
the value decides whether the paste-back prints its `# EXTEND THIS REASON` comment, and
that string occurs once in the repo, in the producer. So both call sites agree with a
helper that has stopped computing anything.

### The checks that read an uncontrolled helper, enumerated

1. **`test_every_carried_stale_anchor_names_what_broke_it`** (`:2884`), third assertion.
   The issue's subject. It reads `unnamed_records` and is satisfied by `not []`.
2. **`test_every_recorded_anchor_matches_once_or_is_carried`** (`:2388`). The only live
   caller of `stale_anchor_failure`, so the only live caller of
   `stale_anchor_entry_literal` and `computed_stale_total`. Both are read only in a
   failing run, and this check does not fail on a green tree, so neither producer is
   exercised by it at all.
3. **`test_the_stale_anchor_check_still_bites`** (`:2654`). Drives `stale_anchor_failure`
   over synthetics in both directions and asserts nothing about the paste-back or the
   total, so it is the check that could have controlled the two producers and does not.
4. **`test_the_stale_anchor_message_says_what_happened`** (`:2736`). Passes a hand-written
   literal and a hand-written total, so it exercises the assembly in
   `stale_anchor_message` and never the two producers; and it passes count `0` only, never
   `TARGET_UNREADABLE`, and a full `targets` mapping, so both of `spelled_stale`'s
   uncontrolled branches stay unreached.
5. **`test_the_placeholder_reason_does_not_satisfy_the_reason_check`** (`:2912`). Asserts
   three properties of `NO_BREAKING_CHANGE_YET`, a constant defined 900 lines above it in
   the same module. Its docstring claims something larger, that "pasting the printed
   literal unedited does not clear the reason check", and nothing in it connects the
   constant to either half of that check.

### The issue's count of four, corrected

The issue body on disk states two edits, both of which reproduce by construction above.
The figure of **four** vacuous assertions belongs to the re-review that raised it and
counts four sites found on PR #93 by four different passes: QA found the undecodable-UTF-8
target and the retirement note's content, the re-review found `unnamed_records`, and the
same call found the `EXTEND THIS REASON` marker.

**Two of those four were closed before PR #93 merged and are controlled at `0f6e8df`**,
read rather than assumed: `ANCHOR_INTO_A_FILE_THAT_IS_NOT_TEXT` at `:2618` and the
assertion at `:2700` hold the undecodable case, and `dated_note_problems` at `:2445` with
`test_the_dated_note_check_reads_the_note_and_not_only_its_shape` at `:2835` hold the
note's content in five synthetic cases.

**So four is the count of the finding's history and not of the work left.** What is left
at `0f6e8df` is **three whole helpers with no control**, `unnamed_records`,
`stale_anchor_entry_literal` and `computed_stale_total`, and **two uncontrolled branches**
inside a helper that is otherwise controlled, both in `spelled_stale`. The issue names one
of the three and one arm of another. Use five sites, and note which of the five this task
closes and which it deliberately leaves as documentation: criteria 3 to 12 close four of
them and criterion 13 leaves `computed_stale_total` as documentation with its own recorded
measurement.

---

## The four decisions the issue left open, settled

### 1. Both a self-test and a mutation record, and they are not alternatives

**The enforcement is self-tests in `tests/test_suite_integrity.py`. The demonstration that
each of them can fail is `plans/mutations/97-the-reason-naming-check.md`.** Neither alone
is the fix, and the reason is written in the issue: a recorded mutation is re-runnable and
is not re-run, so `s7-the-reason-stops-naming-its-record` attests the guard through a
document somebody has to remember to open, which is issue #75's subject. A self-test with
no recorded proof that it bites is this task's own subject one level up. So both, in the
shape `.claude/rules/testing.md` states: an anchor and a replacement, never a sentence,
each with a named surviving control.

### 2. What a control looks like when the subject is a literal beside the check

This is where a careless fix reintroduces the defect, so it is settled here rather than
left to taste. Three shapes, and only the first two count as controls.

* **Drive the helper with a population it does not read from the module.** This is the
  module's own answer and it is already used twice in the region: `stale_anchor_failure`
  takes its baseline as a **parameter** so the self-tests can pass a synthetic one, and
  its docstring at `:2369` says exactly why, "instead of asserting about set arithmetic
  they performed themselves"; and `dated_note_problems` is a pure function over a section
  string, which is what let five synthetic notes close QA's finding. Copy that. The reason
  check becomes a pure `reason_problems(where, carried, reason)` over arguments, the live
  test keeps its name and calls it over `CARRIED_STALE_ANCHORS`, and a new
  `test_the_reason_check_still_bites` calls it over synthetics.
* **Round-trip a produced artefact rather than comparing it with itself.** For the
  paste-back the honest control is not "the string contains the string I wrote beside it";
  it is that the entry it produces is **valid Python that names the pairs it was given**,
  proved by parsing it, plus that the marker appears when and only when a carried id is
  unnamed. Criterion 9 spells that out.
* **Asserting properties of a constant defined in the same module is not a control.** It
  is a claim about that constant, and the only thing it detects is somebody editing the
  constant. It is not banned, and
  `test_the_placeholder_reason_does_not_satisfy_the_reason_check` is not deleted; it is
  routed through the helper that consumes the constant so that it also detects the
  consumer stopping to care, which is the failure its docstring already claims to cover.

**And every criterion below that adds a control names the edit that must make it fail, and
criterion 22 requires the implementer to make that edit and record what happened.** A
criterion that only asserted an assertion exists would be the same defect a third time.

### 3. Which mutations, with what anchors

Six, listed in criterion 22, each with a named surviving control. Two of them matter most:
`r1` guts `unnamed_records` and the record must show
`test_every_carried_stale_anchor_names_what_broke_it` **surviving** beside the new control
dying, because that survivor is the measured form of issue #97's central claim and belongs
in the record rather than in a pull request body; and `r6` guts `computed_stale_total` and
records that nothing substantive reds, which is how a decision to leave something as
documentation becomes auditable instead of a sentence.

Anchors are quoted **from the shipped branch**, not from this document, because two of the
lines a mutation targets are lines this task edits. Every anchor must occur exactly once
in `tests/test_suite_integrity.py`, which the recipe's own assertion enforces and which
`test_every_recorded_anchor_matches_once_or_is_carried` then enforces on every run.

### 4. What stays documentation, said plainly

**`computed_stale_total` is left uncontrolled on purpose**, and criterion 13 turns that
into a comment stating the measurement and the reason rather than a silent hole. The
reason is a mechanism and not a hope: the value is read only when the check is already
failing, and it is read into a paste-back whose destination constant is owned by
`test_the_carried_stale_total_is_the_number_of_carried_records`, which has a live subject
and a recorded mutation, `s2-the-declaration-deleted`, showing it bites. So a wrong number
cannot survive in a green tree; it costs the reader one round trip. A synthetic control
would mean either restructuring the function to take its population as an argument, which
buys a control over arithmetic nobody has got wrong, or comparing it with
`CARRIED_STALE_TOTAL`, which is `0 == 0` on the day the baseline empties and so is a check
that will rot into this task's own subject.

**Case (e) of `test_the_stale_anchor_check_still_bites`, the directory target, also stays
exactly as it is.** Its comment at `:2685` to `:2690` already says it cannot fail while
(d) passes under any mutation of the implementation as it stands, and says what it does
guard against instead. That is the marking this repo asks for and it is the model criterion
13 follows. Do not "strengthen" it, and do not delete it.

`spelled_stale`'s `targets.get` fallback is the one place where documentation is the wrong
answer even though the branch is unreachable today: deleting it in favour of
`targets[identifier]` would turn a failing check into a `KeyError` out of the test, so it
stays and criterion 11 gives it the one assertion it needs.

---

## Goal

The requirement that a carried stale anchor's reason names every record its entry covers
is held by the suite rather than by a document: gutting `unnamed_records` to its passing
value, or suppressing the paste-back comment that tells a reader why their paste stayed
red, fails a named test instead of leaving the module green. The three other uncontrolled
producers in that subsection are either given a control or marked as documentation with the
measurement that says why, so the next person to refactor these helpers is told what they
broke.

What this task does **not** reach, stated here so a green suite is not misread: nothing it
adds detects the *next* uncontrolled helper. The diagnostic stays a review step, written
down in `.claude/rules/testing.md` by criterion 19, and no check anywhere can tell an
assertion that passes because it is right from one that passes because its population is
the single case that satisfies it.

---

## Acceptance criteria

### Where the work lives

1. Every code change is inside the `# --- The stale-anchor check (#87) ---` subsection of
   `tests/test_suite_integrity.py`, which runs from that header at `:1955` down to the line
   before `# --- The measurement that could not fail, refused in the documents (#58) ---`
   at `:2925`, with exactly three exceptions, each named in its own criterion: one sentence
   in the module docstring (criterion 18), two appended entries in `ENFORCING_SYMBOLS`
   (criterion 20), and no other. **No new test module, no new file under `scripts/`, no
   change under `src/`, `app/` or `scripts/`.**
2. That module's imports do not grow beyond the standard library and `pytest`, and nothing
   from `splitwise_lite` is imported, so the claim in its docstring at lines 48 to 49 stays
   true. `ast` is already imported at `:54` and criterion 9 uses it. No test enforces this,
   which is why it is written down: it is checked by reading the diff's import block.

### The reason check gets a population it can be driven with

3. A pure helper `reason_problems(where, carried, reason) -> list[str]` returns everything
   wrong with one record file's entry: a reason under `MINIMUM_REASON` characters, a reason
   that `BREAKING_CHANGE` does not match, and every carried record id the reason does not
   name. It reads nothing from the module: `CARRIED_STALE_ANCHORS` is not consulted inside
   it. It mirrors `dated_note_problems` at `:2445`, which is the shape that let five
   synthetic notes close the equivalent finding on PR #93.
4. `test_every_carried_stale_anchor_names_what_broke_it` **keeps its name**, iterates
   `CARRIED_STALE_ANCHORS` as it does today, collects `reason_problems` over every entry
   and asserts once at the end, so one bad entry no longer hides another. Its name is kept
   because `s7-the-reason-stops-naming-its-record` names it in `kills` and
   `s2-the-declaration-deleted` names it in `survives`.
5. **The three finding texts move without being rewritten.** In particular the string
   `this file's entry carries one reason for every record in it, and that reason does not
   name ` survives verbatim, prefixed by `{where}: ` as it is today, because
   `plans/mutations/87-stale-anchor-check.md` quotes the rendered form of that sentence as
   `s7`'s recorded output and a record whose quoted output no longer occurs is a
   measurement attached to a subject that has moved. Checked by reading the diff: those
   string literals appear in it as moved lines and not as edited ones.
6. `unnamed_records` keeps its name, its signature and its call site at `:2233`. It is
   called by `reason_problems` rather than duplicated, so one definition answers both
   callers and `r1` in criterion 22 kills every control at once.
7. **Naming a record is a delimited match, not a substring.** `unnamed_records` treats a
   carried id as named only where it occurs in the reason with no `-` and no word character
   immediately before or after it, so a reason naming `g2-repeated-member` does **not**
   name a carried `g2-repeated`. The match stays exact and case-sensitive, and the
   docstring says so, so a reason that capitalises an id at the start of a sentence is a
   finding whose fix is to write the id as it is. Measured, so this is a latent hole and not
   a live failure: of the 47 recorded ids, no id is a substring of another id in the same
   record file, so the live entry stays green. The reason it is closed anyway is that a
   substring standing in for a naming is the exact defect `unnamed_records` was added to
   fix, one level down.
8. `test_the_reason_check_still_bites` is a new test, named in the module's idiom for
   positive controls over synthetics, sitting directly below
   `test_every_carried_stale_anchor_names_what_broke_it`. It calls `reason_problems` with
   synthetic entries only, never the module's baseline, and covers at minimum:
   a. a reason of adequate length, carrying a `#NN`, naming the entry's one record: no
      findings, which is what stops (b) to (g) passing because the helper always answers
      something;
   b. a reason under `MINIMUM_REASON` characters: a finding, and the message says it is not
      a reason;
   c. a reason long enough and carrying no digit at all: a finding, and the message says it
      names no change;
   d. a two-record entry whose reason names one of them: a finding naming **the other one
      and only the other one**, which is the assertion the whole issue is about;
   e. a two-record entry whose reason names both: no finding;
   f. a two-record entry where one id is a substring of the other and the reason names only
      the longer: a finding naming the shorter, per criterion 7;
   g. an entry whose frozenset is **empty** with a usable reason: no finding, because that
      is the state `s2-the-declaration-deleted` leaves behind and that record lists this
      test under `survives`;
   h. findings come back in a deterministic order, so a failure list does not churn between
      runs.
   Each case carries a one-line comment saying which branch it is the positive control for,
   in the manner of the existing cases at `:2661` onward.

### The paste-back gets a control, and two message branches get theirs

9. `test_the_stale_anchor_paste_back_says_which_reason_to_extend` is a new test calling
   `stale_anchor_entry_literal` directly, with synthetic arguments, and covers its three
   arms:
   a. pairs plus a reason that names none of them: the returned text carries a
      `("id", count),` line for every pair, in sorted order, and the `EXTEND THIS REASON`
      comment naming exactly the unnamed ids;
   b. pairs plus a reason that names all of them: the same pair lines and **no** marker;
   c. no pairs: the delete-this-entry sentence, naming the record file.
   For (a) and (b) the returned text is **parsed** rather than only searched: wrapping it in
   a dict literal and running `ast.parse` over the result must not raise, so the check is
   that a reader can paste it, not that it contains a string this test also spells. State in
   a comment that (c) is prose rather than a dict entry and is therefore asserted as prose.
10. That test also asserts that the marker names the unnamed id and does **not** name an id
    the reason already names, so a marker that always lists every pair does not satisfy it.
11. `test_the_stale_anchor_message_says_what_happened` gains two assertions, and no new test
    is created for them:
    a. a `TARGET_UNREADABLE` count renders as `could not be read at all`, rather than as
       `occurs -1 times`, which is what `spelled_stale`'s uncontrolled arm at `:2175`
       currently promises with nothing holding it;
    b. an id absent from the `targets` mapping renders with the
       `the file its record names` fallback at `:2174`, so the one branch that exists to stop
       a failing check raising `KeyError` is reached at least once.
12. No existing assertion in that test or in `test_the_stale_anchor_check_still_bites` is
    deleted, loosened or reordered. Both grow only.

### What is left as documentation, and says so

13. `computed_stale_total` is unchanged, and the comment above it records: that it has no
    control, measured by the gut in criterion 22's `r6` rather than argued; that it is read
    only in a failing run; and that a wrong value cannot survive in a green tree because
    `test_the_carried_stale_total_is_the_number_of_carried_records` owns the constant it
    feeds and `s2-the-declaration-deleted` is the recorded proof that check bites. The
    comment follows the marking at `:2685` to `:2690`, which is this module's established
    form for a case that holds by construction: say what it does not cover, and say what it
    guards against instead.
14. That comment names no number that was not measured, and in particular does not claim
    the two totals agree. `computed_stale_total` counts stale anchors found and
    `CARRIED_STALE_TOTAL` counts carried records; they coincide only while every stale
    anchor is declared.
15. Case (e) of `test_the_stale_anchor_check_still_bites`, the directory target at `:2691`,
    and its comment, are untouched.

### The constant the paste-back prints

16. `test_the_placeholder_reason_does_not_satisfy_the_reason_check` keeps its name and its
    three existing assertions, and gains one that routes `NO_BREAKING_CHANGE_YET` through
    `reason_problems` with a synthetic carried pair, asserting that the placeholder is
    **refused by the check** on both counts: it names no change and it names no record. Its
    docstring stops claiming more than it holds, or holds what it claims.
17. `NO_BREAKING_CHANGE_YET` itself is unchanged, so `stale_anchor_failure`'s default at
    `:2374` and the comment at `:2006` to `:2011` stay true.

### The documents

18. The module docstring's issue #87 paragraph, lines 34 to 46, gains one sentence: that
    the reason requirement now has a positive control over synthetics, naming
    `test_the_reason_check_still_bites`. **The count in line 3 does not move**, and that is
    a decision rather than an oversight: "Five failures ... #67, #65, #70, #60 and #87"
    counts the issues that produced this module's sections, this task produces no section,
    and adding a sixth number would send a reader looking for a section that does not
    exist. The sentence about the five checks that read `plans/mutations/` as data at line
    36 also stays true and untouched, measured: the five are
    `test_every_recorded_mutation_is_machine_readable`,
    `test_a_mutation_record_holds_no_prose_only_section`,
    `test_every_node_id_a_record_names_is_one_it_lists`,
    `test_every_recorded_anchor_matches_once_or_is_carried` and
    `test_every_carried_stale_anchor_carries_a_dated_note_in_its_record`, and everything
    this task adds reads synthetics.
19. `.claude/rules/testing.md` gains one rule with its scar, and the heading at line 15
    becomes "Eight rules, each with the defect that produced it". The rule states the
    property, that a guard added to close a review finding is usually written against the
    one population that already satisfies it, so its assertion is real, correct and unable
    to fail; the diagnostic, that you replace the helper's body with its passing value and
    re-run before approving; and the scar, that four such sites were found in one module on
    one pull request, #93 for issue #87, two by QA before it merged and two in re-review,
    the last of them being #97. It also says plainly that **this is a review step and not a
    check**, because nothing in the suite can detect a vacuous assertion, so the rule does
    not read broader than its mechanism. `THE_THREE_BULLETS` is kept **verbatim**, so
    `test_the_testing_rules_keep_the_three_they_had` stays green untouched.
20. `ENFORCING_SYMBOLS` gains `reason_problems` and `test_the_reason_check_still_bites`, and
    both names are written into the rules text, so
    `test_the_testing_rules_name_the_mechanisms_that_enforce_them` covers them and
    `test_every_named_mechanism_resolves_to_something_that_exists` reds if a later rename
    leaves the rule naming something gone. Appended to the tuple rather than reformatted, so
    no anchor into it can rot. Red if broken: add the entries without writing the names into
    the rules file and the first of those reds; rename either definition and the tuple entry
    together and the second one does.
21. `plans/mutations/README.md`, `plans/mutations/65-message-pins.md` and
    `plans/mutations/87-stale-anchor-check.md` are **not edited**, and the reason is
    measured rather than assumed. The README's "One reason per record file" paragraph at
    lines 168 to 175 describes the mechanism accurately and claims no control for it. The
    `87` file's figures are each anchored to a named tree, `df507b3`, including "collects
    **100 tests** at this revision" and "examines **47** records in **11** record files", so
    adding tests and a twelfth record file makes none of its sentences false, and editing
    those figures without re-running the seven mutations would be fabricating a measurement.

### Proof that each new control can fail

22. `plans/mutations/97-the-reason-naming-check.md` records **six** mutations, in the format
    of `plans/mutations/87-stale-anchor-check.md`, each with a **named surviving control**,
    each anchor quoted from the shipped branch and asserted by the recipe to match exactly
    once:
    a. **`r1`, the reason-naming helper gutted.** Anchor: the shipped return statement of
       `unnamed_records`. Replacement: `    return []`. Must kill
       `test_the_reason_check_still_bites`,
       `test_the_stale_anchor_paste_back_says_which_reason_to_extend` and
       `test_the_placeholder_reason_does_not_satisfy_the_reason_check`. **Must record
       `test_every_carried_stale_anchor_names_what_broke_it` under `survives`, and the
       section must say that this survivor is the measured form of issue #97's claim**, that
       the live check reports success while the helper it calls has stopped computing.
    b. **`r2`, the paste-back marker suppressed.** Anchor: `    missing =
       unnamed_records(frozenset(pairs), reason)`. Replacement: `    missing = []`. Must kill
       `test_the_stale_anchor_paste_back_says_which_reason_to_extend` and must leave
       `test_the_reason_check_still_bites` green, which is what shows the two controls are
       independent rather than one standing in for the other.
    c. **`r3`, the delete-this-entry arm never taken.** Anchor: the `if not pairs:` line of
       `stale_anchor_entry_literal`, with enough context to occur exactly once in the module.
       Must kill case (c) of criterion 9.
    d. **`r4`, delimited naming weakened back to a substring.** Replaces the delimited match
       of criterion 7 with the plain `in` test. Must kill case (f) of criterion 8 and nothing
       else substantive, which is what makes criterion 7 a decision rather than a preference.
    e. **`r5`, the unreadable-target line deleted.** Anchor: the `if count ==
       TARGET_UNREADABLE:` arm of `spelled_stale`. Must kill criterion 11a.
    f. **`r6`, the total builder gutted.** Anchor: the shipped return statement of
       `computed_stale_total`. Replacement: `    return 0`. Its `result` is
       **`killed-for-the-wrong-reason`**, with `test_every_recorded_anchor_matches_once_or_is_carried`
       in `kills` as the standing collateral described in `plans/mutations/README.md` at lines
       83 to 97, and the section says that **no substantive control reds**, that this is the
       measurement behind criterion 13, and what the downstream owner catches instead.
23. Every one of the six is applied with the recipe in `plans/mutations/README.md`, whose
    exactly-once assertion is **not** skipped, with `PYTHONDONTWRITEBYTECODE=1` set on every
    run, reverted with `git checkout -- <file>` before the next, and each `What the run
    printed` figure is that module's own failed and passed counts from an unfiltered run of
    `tests/test_suite_integrity.py`. Six of the six mutate that one Python file, minutes
    apart, so the bytecode variable is load-bearing here rather than ceremonial.
24. The new record file names the tree it was taken on and the module's collected count at
    that tree, states the standing collateral once in its introduction rather than per
    record, and records the anchor-into-a-record-file trap only if one of its mutations
    targets a record file, which none of the six does.
25. It passes the checks that already read that directory: seven keys and no others, no
    prose-only `##` section, and a node id in prose is one that section lists in `kills` or
    `survives` while a citation is written bare, as
    `plans/mutations/87-stale-anchor-check.md` states at lines 77 to 83.
26. **No new synthetic in the test module reproduces an anchor another record points at.**
    Eight records anchor into `tests/test_suite_integrity.py`, and a synthetic that
    accidentally spells one of them a second time makes that anchor match twice and reds the
    sweep. The four in the `#87` subsection are the pair line
    `\n                ("g2-repeated-member", 0),` for `s2`, the comprehension line `for
    identifier, count in counts.items() if count != 1` for `s4`, `    except (OSError,
    UnicodeDecodeError):` for `s5`, and the first line of the live reason string for `s7`. So
    the new synthetics use `s-` prefixed invented ids in the manner of `ANCHOR_MATCHING_ONCE`
    at `:2526`, not `g2-repeated-member`, and no new pair literal is indented to sixteen
    spaces.
27. No module-level name in `tests/test_suite_integrity.py` is defined twice, which
    `test_no_test_module_defines_a_name_twice` enforces with no allowlist and which matters
    here because this task adds several synthetic constants to a module that already holds
    forty-odd.
28. The new tests use no `pytest.raises`, so `CARRIED_UNANCHORED_BLOCKS` gains no entry and
    `CARRIED_TOTAL`, which reads **102** at `:1122`, does not move. If a block turns out to
    be needed, it is anchored one of the four accepted ways rather than carried. #70's
    baseline shrinks only and this task must not be what grows it.

### Verification, and what the pull request states

29. `s7-the-reason-stops-naming-its-record` is re-run against the shipped branch, because
    criterion 4 restructures the check that record claims to kill. If its recorded failure
    sentence no longer occurs in the output, the fix is the wording under criterion 5 and not
    an edit to the record. The pull request states that it was re-run and what it printed.
30. The module's collected count is measured before and after with `uv run python -m pytest
    tests/test_suite_integrity.py --collect-only -q`, and the pull request states both
    numbers and the number of tests added. Every module the branch touches is run in full by
    name; the rest of the suite is run in chunks by module with the chunk boundaries and the
    summed counts stated. The command is `uv run python -m pytest`, never `uv run pytest`.
31. The pull request states the swept population as the check reports it after the new record
    file lands: 47 records in 11 files today, plus the six this task adds in a twelfth, and
    whether the sweep stays green.
32. The pull request lists, for each of the five sites in the table above, which of the three
    outcomes it got: controlled by a new test, marked as documentation with a recorded
    measurement, or left alone. A site that quietly disappeared from that list is the defect
    this task is about.
33. The whole-suite gate is CI: both legs of `.github/workflows/tests.yml` must be green, and
    a pull request whose base has moved is brought up to date and re-run. That matters more
    than usual here: two other branches are in flight against this same module, so a result
    computed against an older `master` says nothing about the merge commit. If a merge lands
    somebody else's edit to a constant this task does not own, the value is **not** restored
    to what this document measured; the dated-note practice in criterion 41 of
    `plans/tasks/87-a-mutation-records-anchor-matches-zero-times.md` is followed instead.
34. **No criterion in this task requires a browser.** Everything is text read by Python and
    pytest runs, nothing routes to issue #80, and no verdict rests on an unrun manual check.

---

## Out of scope

* **The #70 region of the same module**, lines 642 to 1530. Measured, and it has the same
  defect: `carried_entry_literal` at `:1139` and `computed_carried_total` at `:1158` each
  have one call site, at `:1277` and `:1278`, and
  `test_the_carried_baseline_message_says_which_direction_it_is_for` passes its own literal
  and its own total, so gutting either leaves the module green, exactly as the issue says.
  It is out because that baseline is mid-audit under slices 70b to 70h and because a task
  that edits both regions cannot be reviewed as one change. Whoever picks it up starts from
  this paragraph; nothing in this task file may be read as saying that region is fine.
* **Anything that would make the suite detect the next vacuous assertion.** No check can,
  the diagnostic is a review step, and criterion 19 puts it where the next author reads it.
* **Re-running any recorded mutation other than `s7`**, and verifying any recorded `result`.
  A green sweep still means a record is appliable, never that its verdict holds.
* **Repairing or re-deriving `g2-repeated-member`**, editing its retirement note, or touching
  `CARRIED_STALE_ANCHORS`, its reason string or `CARRIED_STALE_TOTAL`. The live entry is the
  population that hides the defect and it is also the only live subject three other checks
  have. It stays byte for byte.
* **`stale_pairs`, `anchor_match_count`, `sweep_anchors`, `AnchorSweep` and the
  `except (OSError, UnicodeDecodeError)` clause.** All controlled, and `s4` and `s5` anchor
  into two of them.
* **Restructuring `computed_stale_total` to take its population as an argument.** Decided in
  section 4 above, with reasons.
* **`CLAUDE.md` and `README.md`.** This task adds no capability, retires none and creates no
  directory, so neither document's claim list moves, the literal in `tests/test_web_shell.py`
  is untouched and the parity between the two documents is untouched. Under-claiming is the
  safe direction here; over-claiming is the defect. `plans/backlog.md` gains nothing, for the
  reason task 87 gives: the issue is the backlog entry.
* **Any change under `src/`, `app/` or `scripts/`.** `git diff --stat` shows no path under
  any of the three, so `SHELL_DIGEST` in `app/sw.js` does not move.
* **Deleting, renaming, loosening, skipping or xfailing any test**, and deleting any mutation
  record or record section.
* **Issue #75**, the checks somebody has to remember to run. This task moves one guard out of
  that population and does not close the issue.

---

## Constraints

* **Files this task may touch, and no others in either direction:**
  `tests/test_suite_integrity.py`, `.claude/rules/testing.md`,
  `plans/mutations/97-the-reason-naming-check.md` (new), and this file.
* **Regions of `tests/test_suite_integrity.py` this task touches:** lines 1955 to 2923, the
  `#87` subsection; one sentence inside the docstring paragraph at lines 34 to 46; and the
  `ENFORCING_SYMBOLS` tuple at lines 3154 to 3162. Everything else is another task's
  subject, including the `#67` region at 130 to 386, the `#65` region at 386 to 641, the
  `#70` region at 642 to 1530, the first three `#60` checks at 1532 to 1953, the `#58` region
  at 2925 to 3136 and the rules tests at 3206 to 3274.
* `tests/test_suite_integrity.py` imports the standard library and `pytest` only and nothing
  from `splitwise_lite`.
* **One hatch, not two.** The declaration route stays `CARRIED_STALE_ANCHORS` with a reason at
  `MINIMUM_REASON`; no marker comment, no per-file skip, no decorator, no JSON key. This task
  adds no exemption of any kind.
* Each check over that directory states one guarantee and none restates another's. The new
  tests are self-tests over synthetics and state none of those guarantees; they state that the
  helpers behind them compute something.
* **A control is a run, not a sentence.** Every criterion above that adds an assertion has a
  matching mutation in criterion 22, and the record carries what the run printed rather than
  what it was expected to print.
* Every mutation is recorded as an anchor and a replacement, never as a sentence; every Python
  mutation run sets `PYTHONDONTWRITEBYTECODE=1`; and each anchor occurs exactly once in its
  target, which the recipe asserts and the sweep then re-checks.
* No number in the shipped code is a hand count. The paste-back prints the literal to paste
  back, and that stays the only sanctioned way the baseline is maintained.
* A correction retires the wording it replaces by quoting it inside a dated note, in this
  repo's committed form. Criterion 19's heading change is the only count this task moves, and
  it moves it because the count is of bullets in the file being edited.
* `uv run python -m pytest`, never `uv run pytest`.

---

## Size

One pure helper extracted, two new tests, three assertions added to two existing tests, one
comment that states a measurement, one rule bullet, two tuple entries and one record file with
six mutations. Smaller than task 87, whose subsection it repairs, and comparable to the note
half of that task, which closed the same defect for `dated_note_problems` with five
synthetics and one recorded mutation.
