# Four record files still say the suite does not re-verify these anchors (issue #96)

GitHub issue #96. This is a follow-up to PR #93, which landed
`test_every_recorded_anchor_matches_once_or_is_carried` in
`tests/test_suite_integrity.py` and thereby falsified a sentence four committed mutation
record files carry. #93 corrected the two files its own task spec allowed it to touch and
left the other four, on the correct grounds that a scope breach to fix a sentence is the
worse trade.

This task is documentation only. It writes no code, adds no check and moves no figure.

## The population, measured on this tree

Measured 2026-09-09 on the worktree at master `0f6e8df`, with a grep for
`does not re-verify` across the repository. Eight hits, in four kinds:

| file:line | kind |
| --- | --- |
| `plans/mutations/57-fragment-flattening.md:24` | **live instance, to correct** |
| `plans/mutations/70a-message-block-check.md:11` | **live instance, to correct** |
| `plans/mutations/72-the-feed-swallows-its-own-errors.md:13` | **live instance, to correct** |
| `plans/mutations/88-the-sign-in-gate-discards-a-programming-error.md:52` | **live instance, to correct** |
| `plans/mutations/65-message-pins.md:19` | already retired, inside PR #93's dated blockquote. Do not touch |
| `plans/mutations/README.md:210` | already retired, inside PR #93's dated blockquote. Do not touch |
| `plans/tasks/87-a-mutation-records-anchor-matches-zero-times.md:389` | criterion 26, quoting the sentence as the thing to correct. Do not touch |
| `plans/tasks/87-a-mutation-records-anchor-matches-zero-times.md:400` | criterion 28, same. Do not touch |

All four live instances carry the sentence in identical words, differing only in where the
line wrap falls:

> The suite deliberately does not re-verify these anchors; see `README.md` in this
> directory for that reasoning, and for the format and the recipe.

In `57-`, `70a-` and `72-` it is the last sentence of the paragraph that records the tree
the file was measured on. In `88-` it is a standalone two-line paragraph at the end of a
long introduction, and the tree paragraph is nine lines above it. All four sit in the
file's introduction, above its first `##` heading, which are at `57-`:27, `70a-`:76,
`72-`:16 and `88-`:55.

### Three more places carry the same claim in paraphrase

Also measured on this tree, and **deliberately not edited in place** by this task, see Out
of scope. `plans/tasks/60-65-67-checks-that-could-not-fail.md` asserts the retired claim
three times in its own words, at lines 127 to 131, 414 to 417 and 431 to 434. Those are
quoted and retracted in this file instead, under "What this task supersedes, quoted", per
the precedent criterion 46 of `plans/tasks/79-two-unreachable-400s-carry-cents-and-an-event-id.md`
set for exactly this shape.

Recording them matters for one reason beyond honesty: they are why a mechanical guard on
the literal sentence would be a check that reports success without exercising what it
names. See criterion 30.

### Why the count was three and is four, which is not sloppiness

The sentence reached `88-the-sign-in-gate-discards-a-programming-error.md` in PR #91,
merged as `5bfc117`, which is the commit before #93's `0f6e8df`. It was **true when
written**: nothing counted an anchor until #93. PR #93 falsified it a short time later.

So the population of the retired sentence was **three** on a tree that did not yet hold
#91's record file, which is what #93's coordinator and both its verifiers measured and
was correct on the tree they measured, and **four** on any tree that holds both merges,
which is what #93's own final grep at `4be70ce` reports and what this worktree reports
today. Neither number was careless. The population is a function of which merges the tree
holds, and this document went stale by a merge.

That distinction is load-bearing for how the `88-` file's correction is worded, per
criterion 16, and it is the argument for giving the sentence a canonical home, per
criterion 26.

## Goal

The four mutation record files that still tell a reader the suite does not re-verify a
record's anchor say instead, in this repo's quote-and-retract form, exactly what
`test_every_recorded_anchor_matches_once_or_is_carried` does and exactly what it does not,
so that a reader of any record file learns the current rule from the file in front of them
rather than from a pointer they may not follow. No JSON block changes and no check changes.

## Acceptance criteria

### The corrected wording, and where it comes from

1. The replacement wording is **copied from `plans/mutations/65-message-pins.md:12` to
   `:15`**, which is the wording PR #93 landed and the model this task follows. It is not
   newly invented, and a reviewer can check that claim by diffing the new sentence against
   that file. The general form, which `70a-` and `88-` take because they hold five records
   each:

   > Every anchor below is swept by the suite, which counts each `find` in the file that
   > record's `file` key names and requires exactly one match or a declaration; see
   > `README.md` in this directory for what that check does and does not promise, and for
   > the format and the recipe.

2. `57-fragment-flattening.md` and `72-the-feed-swallows-its-own-errors.md` hold **one
   record each**, measured: one `` ```json `` fence in each. Their replacement is the same
   sentence with the number agreeing, and nothing else altered:

   > The anchor below is swept by the suite, which counts its `find` in the file this
   > record's `file` key names and requires exactly one match or a declaration; see
   > `README.md` in this directory for what that check does and does not promise, and for
   > the format and the recipe.

   A reader of either file must not be told "every anchor below" when there is one.

3. `70a-message-block-check.md`'s replacement carries **one extra clause**, because four
   of its five records target `tests/test_suite_integrity.py`, measured at lines 81, 250,
   296 and 342, and applying one of those now reds the sweep as well as whatever the
   mutation was aimed at. That is the standing collateral `plans/mutations/README.md:85`
   to `:107` documents, and `README.md:100` to `:106` already names
   `m4-a-named-check-renamed` **in this very file** as its worked example, so a reader of
   `70a-` who is not pointed at it will read a `kills` list that is one failure short of
   what their run prints. Its replacement reads:

   > Every anchor below is swept by the suite, which counts each `find` in the file that
   > record's `file` key names and requires exactly one match or a declaration; see
   > `README.md` in this directory for what that check does and does not promise, for the
   > standing collateral it adds to a run of the four records here that target
   > `tests/test_suite_integrity.py`, and for the format and the recipe.

4. `57-`, `72-` and `88-` do **not** get the collateral clause, and this is a decision
   rather than an omission. Measured: `57-`'s one record targets `tests/shell_harness.mjs`
   (line 32), `72-`'s one record targets `app/app.js` (line 21), and all five of `88-`'s
   records target `app/app.js` (lines 60, 206, 321, 386, 441). None of those is a file in
   `plans/mutations/` and none is `tests/test_suite_integrity.py`, so no collateral arises
   and a clause claiming it would be false.

5. In `57-`, `70a-` and `72-` the replacement sentence sits where the retired sentence sat,
   as the last sentence of that same paragraph. Every word of that paragraph before the
   retired sentence is **unchanged, character for character**, and the paragraph is not
   re-wrapped. So each file's diff shows the retired sentence leaving, the replacement and
   the note arriving, and nothing else.

6. In `88-` the replacement stands as its own paragraph at lines 52 to 53's position,
   which is where the retired paragraph stood, immediately above the `## A programming
   error on the gate's success path` heading and below the paragraph about two blocks
   sharing an anchor. The nine paragraphs above it are unchanged.

### The old sentence is retracted, not deleted

7. **The retired sentence is quoted, not removed from the repository.** Each of the four
   files gains a dated blockquote note immediately below the paragraph it corrects, in the
   form `plans/mutations/65-message-pins.md:17` to `:28` uses. This is the repo's standing
   convention and it is applied rather than argued with: a reader who remembers the old
   claim, or who arrives from a search engine, a PR body or
   `plans/tasks/60-65-67-checks-that-could-not-fail.md`, has to see it withdrawn rather
   than find it absent. Deleting it would also leave `65-` and `README.md` quoting a
   sentence that appears nowhere in the repository as it stood.

8. The span each note quotes is **character-identical to the span quoted at
   `plans/mutations/65-message-pins.md:19` to `:20`**, namely:

   > The suite deliberately does not re-verify these anchors; see `README.md` in this
   > directory for that reasoning

   The trailing clause "and for the format and the recipe" is **not** inside the quoted
   span, because it is not retired: it is still true and it survives into the replacement.
   Retracting more than went false is the same defect as retracting less.

9. Each note opens with a bold marker naming the date and the issue, then names this file,
   in the form `65-` uses:

   > **Corrected 2026-09-09 for issue #96**, per
   > `plans/tasks/96-record-files-still-say-the-suite-does-not-re-verify.md`.

   The date is the day the correction is written, in `YYYY-MM-DD` form. 2026-09-09 is the
   date this spec was measured; if the work lands later, the note carries the later date
   and this criterion is satisfied by the form and the `#96`, not by the calendar day.

10. Each note is a contiguous run of `>` lines with **no blank unquoted line inside it**,
    so `blockquote_run` in `tests/test_suite_integrity.py:2983` reads it as one run. This
    is not decoration: that helper and `DATED_NOTE` at line 2980 are what the repo's
    existing dated-note machinery recognises, and a note split by a bare blank line reads
    as two containers.

### What the note says is now true, and what it does not claim

11. Each note states what the landed check does, in these three parts and no more than
    these, because a correction that overclaims is the same defect in a new place:
    a. it counts every recorded `find` in the file that record's own `file` key names;
    b. it refuses anything other than exactly one match;
    c. unless the record is declared in `CARRIED_STALE_ANCHORS` with a reason naming the
       change that broke it.

12. Each note then states the boundary, in the words
    `plans/mutations/65-message-pins.md:26` to `:28` uses, so all five corrected files say
    it identically:

    > What is still true, and is what that sentence was protecting, is narrower: no
    > recorded mutation is re-run and no `result` is verified, so a matching anchor proves
    > a record **appliable** and not correct.

13. No note in any of the four files says or implies that the suite re-runs a mutation,
    verifies a `result`, proves a record correct, or checks that a record's recorded
    verdict still holds. Checkable by reading the four notes: the words "re-run", "result"
    and "correct" appear only inside the boundary sentence of criterion 12.

14. Each note names `test_every_recorded_anchor_matches_once_or_is_carried` and
    `tests/test_suite_integrity.py` in the **bare citation form**, as
    ``` `test_every_recorded_anchor_matches_once_or_is_carried` in
    `tests/test_suite_integrity.py` ```, and never as a `tests/test_suite_integrity.py::`
    node id. Two reasons, and the second is the load-bearing one. The convention is
    `70a-message-block-check.md:47` to `:50`, that a node id in a record's prose is read as
    a claim and a citation is written bare. And `test_every_node_id_a_record_names_is_one_it_lists`
    reads a record's prose for `.py::`, so writing the node-id form anywhere this task
    later moves into a `##` section would be read as a claim about that mutation.

15. Each note credits **PR #93** as what landed the check, by number, so a reader can find
    the change rather than only its consequence.

### The `88-` file's note differs, and only here

16. The `88-` note carries the same body as the other three, and **one extra sentence** the
    others do not, because its history differs and a reader who checks the dates will
    otherwise read it as carelessness. It says, in substance: this copy was written by PR
    #91 while the sentence was still true, PR #93 falsified it a short time later, so the
    file went stale by a merge rather than by anyone being careless; and the population of
    the sentence was three on a tree without #91 and four on a tree with it. It must name
    both PR numbers. It must **not** say that anybody miscounted, because nobody did.

17. The other three notes carry no history clause. `57-`, `70a-` and `72-` were written
    before the check existed or was contemplated, so for them the sentence simply aged out,
    and inventing a story for them would be prose nobody measured.

### What must not change

18. **The twelve JSON blocks in the four files are byte for byte identical**, all seven
    keys of each. Measured: five in `88-`, five in `70a-`, one in `57-`, one in `72-`,
    twelve `` ```json `` fences in total across the four. Checkable by reading the diff:
    no line inside a `` ```json `` fence appears in it, except as context.

19. **`CARRIED_STALE_TOTAL` stays `1`**, at `tests/test_suite_integrity.py:2068`, and
    `CARRIED_STALE_ANCHORS` at line 2049 keeps its single entry for
    `plans/mutations/65-message-pins.md` with `("g2-repeated-member", 0)`. None of the four
    files has a stale anchor, none is being declared, and a prose correction cannot rot an
    anchor. If the number moved, something was edited that should not have been.

20. **`tests/test_suite_integrity.py` is not edited at all.** Four of `70a-`'s five records
    quote fragments of that module as their `find`, so an edit to it would rot those
    anchors and red the sweep, which is the standing collateral described at
    `plans/mutations/README.md:85`. This constraint is therefore stronger here than the
    usual "do not touch the tests": editing that module would break the very records this
    task is correcting the prose of.

21. **No file under `app/`, `src/` or `scripts/` changes**, and `tests/` is untouched
    entirely, so `SHELL_DIGEST` in `app/sw.js` does not move and no scenario list changes.

22. **`CLAUDE.md`, `README.md`, `plans/spec.md` and `plans/backlog.md` are not edited.** No
    capability is added or retired, so neither pinned list in `tests/test_web_shell.py`
    moves and the parity between the two documents is untouched. Same reasoning as
    criterion 34 of `plans/tasks/87-a-mutation-records-anchor-matches-zero-times.md` and
    criterion 45 of `plans/tasks/79-two-unreachable-400s-carry-cents-and-an-event-id.md`.

23. **`.claude/rules/testing.md` is not edited.** Read and verified against this task: rule
    (e) at lines 125 to 157 already states the exactly-once rule, already names all three
    of `test_every_recorded_anchor_matches_once_or_is_carried`, `CARRIED_STALE_ANCHORS` and
    `CARRIED_STALE_TOTAL`, and already carries the boundary at lines 137 to 138. There is
    nothing there to correct, and touching it would move `ENFORCING_SYMBOLS`.

24. `plans/mutations/65-message-pins.md` and the dated blockquote at
    `plans/mutations/README.md:208` to `:227` are **not edited**. They are the corrections
    #93 landed and the model this task copies. Editing them would delete a retraction.

25. `plans/mutations/16-incompleteness-signal.md`, `44-the-empty-roster-message.md`,
    `61-identifiers-in-4xx-bodies.md`, `82-the-unreachability-claim.md`,
    `79-two-unreachable-400s.md` and `87-stale-anchor-check.md` are **not edited**. Read
    rather than grepped: none carries the claim in any wording, and
    `61-identifiers-in-4xx-bodies.md:16` carries a dated "Re-verification, 2026-09-07" note
    that is nearer the opposite of it. `87-stale-anchor-check.md:12` to `:15` already
    carries the corrected wording with the collateral clause, and is the second precedent
    for criterion 3.

### A canonical home for the sentence, which is the answer to recurrence

26. `plans/mutations/README.md` gains **one short labelled paragraph** at the end of its
    `## The record format` section, after line 40 and before the `## Why these three keys`
    heading at line 42, giving the intro sentence a home to be copied from. Issue #96's
    closing paragraph asks for exactly this consideration. It says, in substance:

    > **One sentence about the sweep, and one home for it.** A record file's introduction
    > carries the tree it was measured on and one sentence about this check, and that
    > sentence gets copied into the next record file, so it lives here and is copied from
    > here: *Every anchor below is swept by the suite, which counts each `find` in the file
    > that record's `file` key names and requires exactly one match or a declaration; see
    > `README.md` in this directory for what that check does and does not promise, and for
    > the format and the recipe.* Adjust the number for a file with a single record, and
    > add the standing collateral above to what this README is being cited for if any of
    > the file's records target a file in this directory or
    > `tests/test_suite_integrity.py`. Issue #96 is why this has a home: the sentence it
    > replaces was carried by four record files, the fourth copied in good faith by PR #91
    > while it was still true and falsified by PR #93 a short time later, so the population
    > grew by one merge rather than by anyone being careless.

27. That paragraph names the residual rather than overselling itself: a canonical home
    names the origin of a copy, and it does not remove the fan-out. If the check changes
    again, the record files that already carry the sentence still each need a correction,
    and this README paragraph is one more place to correct rather than one fewer.

28. Nothing else in `plans/mutations/README.md` changes. Its
    `## What the suite checks about these anchors, and what it does not` section at line 141
    onwards is already correct and is not restated.

### This task file, and what it retracts on the older documents' behalf

29. This file carries a `## What this task supersedes, quoted` section, following
    `plans/tasks/79-two-unreachable-400s-carry-cents-and-an-event-id.md:119` to `:124`,
    which quotes the three paraphrases in
    `plans/tasks/60-65-67-checks-that-could-not-fail.md` at lines 127 to 131, 414 to 417
    and 431 to 434, and retracts them here rather than editing that file. Written below, so
    this criterion is satisfied by this document as committed.

    > **Departed from 2026-09-09 for issue #96, by the coordinator's decision, and this is
    > a deliberate departure rather than a slip.** The three paraphrases in
    > `plans/tasks/60-65-67-checks-that-could-not-fail.md`, at `:127`, `:414` and `:431`,
    > are retracted **in place** as well: each gains a dated note in the same
    > quote-and-retract idiom the four record files get, with the criteria and the prose
    > around them left standing so a reader sees the original claim beside the withdrawal.
    > The reason, recorded here because the next reader of this file is who needs it: a
    > correction that lives in a different document has the same defect as one that lives
    > in a PR body, which is that the reader who needs it does not find it. The precedent
    > is the one this file's own Out of scope section already records, that PR #58
    > corrected eight older task specs in place. The section below stays exactly as it is,
    > because a reader who greps for the claim should still find the retraction in the same
    > result set; what changes is that the older document now carries one too. Two costs,
    > named rather than waved past: the diff is seven paths and not six, per the note on
    > criterion 34, and the distinction this file drew between a record file that instructs
    > and a task spec that a reader already reads as history is thereby not the line the
    > work follows.

### No mechanical guard, and why

30. **No check is added, in either language, and `tests/test_suite_integrity.py` gains
    nothing.** This was considered rather than skipped, and the verdict is that a guard here
    would be a check that reports success without exercising what it names, which is the
    defect that module exists to refuse. Four reasons, the third measured on this tree and
    decisive:

    a. **It is not a four-line fix.** The machinery does exist: `scanned_documents()` at
       line 2954 covers `plans/**/*.md` plus `README.md` and `CLAUDE.md`, and
       `blockquote_run` and `DATED_NOTE` already implement the dated-blockquote exemption.
       But this repo's own standard for a check in that module, visible in
       `test_the_pin_check_still_bites` at line 568, `test_the_node_id_check_still_bites`
       at line 1889 and `test_the_stale_anchor_check_still_bites` at line 2654, is a check
       plus a message function plus a test that the message says what to do plus
       per-branch positive controls plus a mutation record with a named surviving control.

    b. **The literal `test_no_document_asks_for_the_measurement_that_cannot_fail` refuses
       is not the analogous case it looks like.** That literal is a property name with one
       spelling, so a guard on it is complete over its subject. "The suite deliberately
       does not re-verify these anchors" is a sentence, and a sentence has unbounded
       spellings.

       > **Corrected 2026-09-09 during implementation, for issue #96.** This sub-criterion
       > opened "**`documentElement` is not the analogous case it looks like.** That
       > literal is an identifier with one spelling", and criterion 35 below read "No new
       > text this task writes contains the string `documentElement`". Both named that
       > literal in live criterion prose, and
       > `test_no_document_asks_for_the_measurement_that_cannot_fail` scans every
       > `plans/**/*.md` for it and exempts only a dated blockquote, so this spec reddened
       > that check from the moment it was written. Measured on this worktree before any
       > other edit: `1 failed, 2788 passed`, the failure naming this file's lines 327 and
       > 375 and nothing else. Criterion 35 is the second of those two lines, which is why
       > it could not be satisfied as written: the sentence promising that no new text
       > carries the literal was itself new text carrying it. The argument here is
       > unchanged and both criteria still ask for the same thing; the literal now appears
       > only inside this dated note, which is the exemption that check documents.

    c. **Measured: a literal guard would go green over three surviving false statements.**
       `plans/tasks/60-65-67-checks-that-could-not-fail.md` asserts the same claim in three
       places, in three different wordings, none of them containing the literal sentence and
       none inside a dated blockquote. A guard on the sentence would pass on this tree while
       the repository still tells a reader the anchor is deliberately not checked, and the
       green run would then be read as evidence that it does not.

    d. **The recurrence route this fix closes is the copy route, and it closes it
       completely.** The sentence spread because record intros are copied, and
       `70a-message-block-check.md:32` to `:33` says outright that seven audit slices will
       copy that file as their template. After this task, every record file in the
       directory carries the corrected sentence and `README.md` names where to copy it
       from, so the next copy is of the true sentence. That is the cheap mechanical answer,
       and it is complete in a way a literal guard is not.

31. The reasoning in criterion 30 is recorded in this file's Out of scope section, so the
    next person who has the same idea reads the measurement rather than repeating it. If
    somebody later wants the guard anyway, the honest version of it also edits
    `plans/tasks/60-65-67-checks-that-could-not-fail.md`, and that is a separate issue with
    a separate scope line, not an extension of this one.

    > **Corrected 2026-09-09 for issue #96**, per the coordinator's decision recorded under
    > criterion 29. The last sentence is overtaken in part: this task does edit that file,
    > so the retraction half of the "honest version" has landed and only the guard itself
    > would be the separate issue. Criterion 30(c)'s measurement is unaffected and still
    > holds, and that is worth saying rather than leaving to be re-measured: the three
    > paraphrases still stand outside a blockquote, in three wordings none of which holds
    > the literal sentence, so a literal guard would still go green over them. What each
    > now carries beside it is a dated retraction.

### Verification

32. `uv run python -m pytest` is green, with the same test count as before the change. No
    test is added, removed or renamed, so a differing count means something was edited that
    criteria 20 to 23 forbid.

33. A grep for `does not re-verify` across the repository returns **eight** hits before the
    change and **eight** after it, at different lines: the four live instances become four
    quotations inside dated blockquotes, and the four hits listed as "do not touch" in the
    population table are unchanged. Zero hits sit outside a dated blockquote in
    `plans/mutations/`. The number is stated so the check is a count and not an impression.

34. `git diff --name-status $(git merge-base master HEAD)..HEAD` reports exactly these
    **six** paths and nothing else:

    - `plans/mutations/57-fragment-flattening.md`
    - `plans/mutations/70a-message-block-check.md`
    - `plans/mutations/72-the-feed-swallows-its-own-errors.md`
    - `plans/mutations/88-the-sign-in-gate-discards-a-programming-error.md`
    - `plans/mutations/README.md`
    - `plans/tasks/96-record-files-still-say-the-suite-does-not-re-verify.md`

    > **Corrected 2026-09-09 for issue #96.** The diff is **seven** paths, not six: the
    > list above plus `plans/tasks/60-65-67-checks-that-could-not-fail.md`, which the
    > coordinator's decision recorded under criterion 29 has this task retract in place.
    > Nothing else moves, and nothing under `src/`, `app/`, `scripts/` or `tests/` is
    > touched.

35. No new text this task writes names the literal
    `test_no_document_asks_for_the_measurement_that_cannot_fail` refuses, outside a dated
    note, so that check is green over every file in this task's diff.

    > **Corrected 2026-09-09 during implementation, for issue #96.** This criterion used to
    > read "No new text this task writes contains the string `documentElement`, so
    > `test_no_document_asks_for_the_measurement_that_cannot_fail` is unaffected by the new
    > file under `plans/`", and it falsified itself: it is new text and it carries the
    > string, so it was one of the two lines that reddened that check on this file as
    > delivered. Criterion 30(b) was the other, and carries the same note with the
    > measurement.

36. The PR body states the population as **four live instances in four files**, names PR
    #91 and PR #93, and says that the count was three on a tree without #91. A PR body that
    repeats "three" against this tree is the same class of error the issue is about.

## Out of scope

* **Editing `plans/tasks/60-65-67-checks-that-could-not-fail.md`.** Its three paraphrases
  are quoted and retracted in this file instead. The precedent is criterion 46 of
  `plans/tasks/79-two-unreachable-400s-carry-cents-and-an-event-id.md`, which quoted and
  retracted three older task specs in the new task file rather than editing them. The
  precedent is genuinely mixed and that is worth saying rather than hiding: PR #58 did
  correct eight older task specs in place, at `08-mobile-web-shell.md:219`,
  `10-expense-entry-screen.md:536`, `11-expense-feed.md:346`, `12-balances-screen.md:377`
  and `13-transfer-drill-down.md:909` among them. The distinction drawn here is that a
  record file is a live instruction for re-running a mutation, where a false sentence
  misleads whoever is about to act, while a task spec is a dated statement of what one task
  asked for, which a reader already reads as history. If a reviewer disagrees, that is a
  follow-up issue and not a licence to widen this diff.

  > **Retracted 2026-09-09 for issue #96, by the coordinator's decision.** This bullet no
  > longer describes the work. That file is edited, and each of its three paraphrases
  > carries a dated retraction in place, with the paraphrase itself left standing. The
  > reasoning is under criterion 29, and it is that a correction living in a different
  > document has the same defect as one living in a PR body. What still stands in this
  > bullet is its own account of the precedent, which is the mixed one: PR #58 corrected
  > eight older task specs in place, and that is the half the decision rests on. The
  > record-file-versus-task-spec distinction drawn above is what is retired.
* **Adding a check that refuses the sentence in a new record file.** Argued and refused in
  criterion 30, on the measurement in 30(c).
* **Re-running any recorded mutation, or re-verifying any recorded `result`.** Nothing here
  re-measures anything. The suite does not do it either, which is the boundary the four
  corrections have to state and must not overstate.
* **Editing any `find`, `replace`, `kills`, `survives` or `result`.** No JSON block in the
  repository changes.
* **Declaring anything in `CARRIED_STALE_ANCHORS`, or moving `CARRIED_STALE_TOTAL`.** No
  anchor rots in this task.
* **Rewriting the four files' introductions beyond the one sentence.** In particular the
  tree each was measured on, the run-count paragraphs in `70a-` and the anchor-naming
  paragraphs in `88-` are correct as they stand and are not restated, tidied or re-wrapped.
* **Adding a `##` section to any record file.** Every edit lands in a file's introduction,
  above its first `##`. A new `##` section with no JSON block in it would red
  `test_a_mutation_record_holds_no_prose_only_section`.
* **Correcting `plans/mutations/65-message-pins.md` or `plans/mutations/README.md`'s dated
  blockquote.** Those are #93's corrections and this task's model.
* **Any product behaviour.** No screen, route, message or figure changes.

## Constraints

* **Files this task may change, and the only ones:** the four record files
  `plans/mutations/57-fragment-flattening.md`,
  `plans/mutations/70a-message-block-check.md`,
  `plans/mutations/72-the-feed-swallows-its-own-errors.md` and
  `plans/mutations/88-the-sign-in-gate-discards-a-programming-error.md`; plus
  `plans/mutations/README.md` for criterion 26; plus this file. Six paths, per criterion 34.

  > **Corrected 2026-09-09 for issue #96.** Seven paths, not six: add
  > `plans/tasks/60-65-67-checks-that-could-not-fail.md`, per the note on criterion 29 and
  > the note on criterion 34.
* **The quote-and-retract form is the repo's convention and is applied, not re-litigated.**
  Its worked examples are `plans/mutations/65-message-pins.md:17` to `:28`,
  `plans/mutations/README.md:208` to `:227`, and the same idiom in a Python comment at
  `tests/test_suite_integrity.py:1540` to `:1551`. Criterion 7 states the reason.
* **Every number in this spec was measured with a read or a grep on this worktree at master
  `0f6e8df`, on 2026-09-09**, and the implementer should re-measure
  rather than trust it, because a count copied forward is how this issue happened. The
  numbers relied on: four live instances; eight grep hits; twelve JSON blocks across the
  four files, being five, five, one and one; four of `70a-`'s five records targeting
  `tests/test_suite_integrity.py`; `CARRIED_STALE_TOTAL = 1`; three paraphrases in
  `plans/tasks/60-65-67-checks-that-could-not-fail.md`.
* **The corrected sentence is copied, not composed.** Its source is
  `plans/mutations/65-message-pins.md:12` to `:15`, with the collateral variant at
  `plans/mutations/87-stale-anchor-check.md:12` to `:15`. Composing a fifth wording of a
  sentence that already has two correct forms is how a directory ends up with four wordings
  of one claim, which is this issue.
* **Read `plans/mutations/README.md` in full before writing any note.** Its
  `## What the suite checks about these anchors, and what it does not` section is the
  authority on what may be claimed, and its closing paragraph at line 177 to 182 is the
  boundary criterion 12 restates. A note that goes further than that section has overclaimed.
* **The suite's one command is `uv run python -m pytest`**, per `CLAUDE.md`. `uv run pytest`
  fails on this machine with an access-denied spawn error.
* Both CI legs, `ubuntu-latest` and `windows-latest`, must be green, and a base that has
  moved has to be brought up to date and re-run. That rule is not incidental here: it is
  precisely how the count in this issue went from three to four.

## What this task supersedes, quoted

Three sentences in `plans/tasks/60-65-67-checks-that-could-not-fail.md` say the suite does
not re-verify a record's anchor. All three were true when written, in the task that created
`plans/mutations/`, and PR #93 is what falsified them. They are quoted here rather than
edited in place, per criterion 46 of
`plans/tasks/79-two-unreachable-400s-carry-cents-and-an-event-id.md`, so a reader who greps
for the claim finds the retraction in the same result set.

> **Corrected 2026-09-09 for issue #96, by the coordinator's decision.** "They are quoted
> here rather than edited in place" is no longer the whole of it: they are quoted here
> **and** retracted in place, each paraphrase keeping its wording with a dated note beside
> it. Everything below stands as written, because a reader who greps for the claim should
> find the retraction in the same result set from either end. The reasoning for the
> departure is under criterion 29.

From `plans/tasks/60-65-67-checks-that-could-not-fail.md:127` to `:131`:

> **The records are not re-verified against live source by the suite.** The suite checks
> that a record is machine readable and complete; it does not check that its anchor still
> matches. Re-verifying would put every past mutation in the path of every future refactor,
> which is the ossification #60 warns against. A committed mutant is re-run; a recorded one
> is re-runnable. That is the whole difference between the two, and it is why both exist.

From the same file, criterion 33(g), at `:414` to `:417`:

> that the suite does **not** re-verify a record's anchor against live source, and why:
> re-verifying would put every past mutation in the path of every future refactor, which is
> the ossification #60 warns against. A committed mutant is re-run; a recorded one is
> re-runnable.

And criterion 37, at `:431` to `:434`:

> `test_the_mutation_records_are_not_re_verified_against_source` is not written. Instead a
> comment beside the two tests above states that the anchor is deliberately not checked
> against the live file, giving the ossification reason, so the next reader does not
> "improve" the check into the thing #60 argued against.

**All three are retired as of PR #93.** `test_every_recorded_anchor_matches_once_or_is_carried`
in `tests/test_suite_integrity.py` counts every recorded `find` in the file that record's
own `file` key names and refuses anything but exactly one match, unless the record is
declared in `CARRIED_STALE_ANCHORS` with a reason naming the change that broke it. The
comment criterion 37 asked for was itself retired in place, and is quoted as retired at
`tests/test_suite_integrity.py:1540` to `:1551`.

**The ossification worry those sentences carried was right and is not retired.** It is
answered rather than abandoned: a rotted anchor is declared once, with a reason and a dated
note, and no repair is demanded of anybody. The baseline is expected to grow whenever a
correct change breaks an anchor, and what the check refuses is an **undeclared** stale
anchor rather than a stale one.

**What still stands, word for word, is the distinction.** A committed mutant is re-run; a
recorded one is re-runnable. What changed is only that the re-runnable half is now checked
instead of assumed. No recorded mutation is re-run and no `result` is verified, so a
matching anchor proves a record **appliable** and not correct.
