---
paths:
  - "tests/**"
  - "**/test_*.py"
  - "plans/mutations/**"
  - "plans/tasks/**"
  - "plans/*.md"
---

- Tests are pytest, run with `uv run python -m pytest` (plain `uv run pytest` fails on
  Windows with an access-denied spawn error)
- Test settle-up with exact integer assertions, never approximate
- Never mark a test skipped or xfail to make the suite green

## Seven rules, each with the defect that produced it

A rule without its scar is one nobody believes, so each of these carries the failure it
was learned from. All seven are about one thing: a check that reported success without
exercising what it named.

- **Message pins are anchored.** `pytest.raises(match=)` is an `re.search`, not a full
  match. Lead with `^` and spell enough of the message that no other exception the same
  call can raise would match it. Scar: on PR #62 a test written to prove the currency is
  validated before the total stayed green with the guard deleted, and the first proposed
  repair, `match="currency must be a Currency"`, had the same defect. Measured on
  `7bf518c` (2026-09-07), `money.py:148` said `Money currency must be a Currency, ...`,
  which contained the shorter sentence from index 6, so the loose pattern was satisfied
  by `Money`'s refusal rather than by the guard under test. If that wording has since
  changed the collision is a different one, and the rule is unchanged, because `match=`
  is still an `re.search`. A deliberate substring pin carries `# unanchored: <why>`, and
  `tests/test_suite_integrity.py` refuses one without a reason. The anchored form looks
  like `match=r"^currency must be a Currency"`.

  > **Corrected 2026-09-08 for issue #70**, per
  > `plans/tasks/70-substring-assertions-on-exception-messages.md`. This rule used to stop
  > there, and a reader finished it believing that anchoring a `match=` was the whole of
  > it. Measured on `bea0da7`: the suite holds **16** real `match=` pins, every one of
  > them anchored, against **101 occurrences** of `assert <needle> in str(<name>.value)`,
  > on 100 lines across seven modules, plus everything asserted through the 27 lines that
  > bind the message to a local first. The count is of occurrences and not of lines,
  > because one line in `tests/test_simplify.py` carries two. So the rule as written
  > covered the rarer form and read as covering the commoner one, which is a document
  > reporting coverage it does not have: the same defect as a check reporting success
  > without exercising what it names, one level up.

  `assert "x" in str(exc.value)` is the same defect and not a milder one. For a pattern
  with no metacharacters an `re.search` **is** a substring test, so that assertion and
  `match="x"` are the same operation and the PR #62 collision applies to it unchanged.
  Measured on `bea0da7` (2026-09-08), `money.py:246` raises `currency must be a Currency,
  got ...` and `money.py:148` raises `Money currency must be a Currency, got ...`, so one
  such assertion is satisfied by either of two live guards. A negative, `assert x not in
  str(exc.value)`, is weaker still rather than safer: any message lacking the string
  satisfies it, including one from an entirely different guard.

  **The anchor goes on the block, not on each assertion.** A block routinely asserts
  several fragments about one message and at most one of them can start it, so there is no
  per-assertion form of this fix. Once one anchor has established which guard raised,
  every fragment assertion beside it stops being a pin and becomes documentation, and none
  of them has to change. Any one of these four anchors a block and they are the whole
  accepted set: `match=r"^..."` on the `raises` call; `==` against the whole message;
  `.startswith` on it; or `# unanchored: <why>` on the `with` statement, at the same
  twenty-character floor. That is what `test_every_message_block_is_anchored_or_carried`
  in `tests/test_suite_integrity.py` enforces, and it is the converse of the check above
  rather than a second copy of it: `test_every_message_pin_is_anchored_or_says_why`
  guarantees that any `match=` which exists is anchored, and this one guarantees that a
  `match=` exists wherever a message is read. Counted as blocks rather than as assertions,
  which is the unit the fix has, that population was **107** measured on `109d7e9`
  (2026-09-08), computed by the check and not by anybody's grep. Every audit slice from
  70b on lowers it, so read that number off `CARRIED_TOTAL` rather than off this sentence.

  The blocks that were already loose when the check landed are carried in
  `CARRIED_UNANCHORED_BLOCKS`, keyed by test module, enclosing definition name and count,
  never by a line number or an ordinal, and totalled in one declared integer.

  What the suite actually enforces about that baseline, stated exactly, because this rule
  sits in the document issue #70 was filed about and a rule reading broader than its
  mechanism is the whole complaint: set equality per module in **both** directions, so a
  carried entry that is no longer unanchored is a failure naming it and an entry cannot
  outlive its subject; `CARRIED_TOTAL` equal to the sum of the counts; and a reason of at
  least twenty characters naming one of slices 70b to 70h.

  **That the baseline only ever shrinks is a convention, not a check.** Nothing refuses a
  new entry. Adding a loose block, adding its `(name, count)` pair and bumping
  `CARRIED_TOTAL` passes all three of those, because a set equality is satisfied by the
  new pair and a sum equality by the bump. It is a claim about history and the suite reads
  one tree, so enforcing it would mean reading git from a test, which is not worth it.
  What holds the baseline down is a reviewer reading a three-place diff that includes a
  bump to a declared integer. That is weaker than the `# unanchored:` hatch, which demands
  twenty characters of written reason for every block it exempts, so do not describe the
  two as equals; it is a visibility cost rather than a written justification, and it is
  enough while the audit is in flight. The last of issue #70's audit slices deletes the
  baseline outright, which is the only thing that ends it. Carrying a block is not
  anchoring one:
  nothing in that baseline can fail for the reason its assertions name until its slice has
  deleted the guard behind it and run.
- **A test function defined twice in one module deletes the first one.** Python rebinds
  silently and pytest collects only what the module ends up holding. Scar: on PR #64
  four parametrised cases stopped running with the suite green, found only because
  somebody reconciled a pass count arithmetically. `tests/test_suite_integrity.py`
  refuses it now, with no allowlist and no marker, because a duplicate module-level
  definition is always a bug and an exemption is how a check stops being one.

  Do not read that scar as saying arithmetic is a reliable backstop. Reconciling a test
  count catches a duplicate that shadows a **parametrised** test, because the case count
  moves. It does not catch one that shadows a single test, because one collected test is
  removed and one is added. Only the check catches that. So the PR #64 collision was only
  ever caught because the shadowed test happened to be parametrised. Had those four cases
  been one, nobody would have noticed, the suite would have been green, and the test would
  simply have stopped existing. Both halves of that were measured, and the counts are
  quoted in the dated marker on criterion 44c of
  `plans/tasks/60-65-67-checks-that-could-not-fail.md`, which is where a measurement
  belongs; this rule states the property, which does not go stale when a test file grows.
- **If a test's name mentions concurrency, staleness or a guard, its body has a second
  actor.** Scar: a 409 described as a race guard whose test only ever ran the sequential
  case, so it could not have failed for the reason its name gave.
- **A fixture that is both the stubbed response and the expected value cannot detect its
  own drift.** Scar: a harness constant set to nonsense while all three scenarios stayed
  green; only a cross-language pin against a live response caught it.
- **A mutation is recorded as an anchor and a replacement, never as a sentence.** Scar:
  reconstructing "choose the shape from something other than ids" from a PR body
  produced a different mutation and a different result, killing one scenario where QA
  had recorded two. Records go in `plans/mutations/`; `plans/mutations/README.md` says
  when one earns a committed mutant instead.

  **An anchor matches its target exactly once, and that is now checked rather than
  assumed.** Exactly once is the precondition of both appliers: the README's recipe
  asserts `source.count(record['find']) == 1`, and `tests/shell_harness.mjs` throws a
  harness error when an anchor matched anything else. Zero matches mutates nothing while
  the run still reports a result, and two matches mutates two places, so both are
  refused. `test_every_recorded_anchor_matches_once_or_is_carried` in
  `tests/test_suite_integrity.py` counts every recorded `find` in the file that
  record's own `file` key names. Second scar, issue #87: `g2-repeated-member` in
  `plans/mutations/65-message-pins.md` had matched **zero** times ever since #61 took
  `{list(ordered)}` out of `split.py`, and nothing anywhere reported it, so a record
  that read as re-runnable was not one.

  A green run of that check means a record is **appliable**, not that its verdict still
  holds: no recorded mutation is re-run and no `result` is verified. The anchors that do
  not match are declared in `CARRIED_STALE_ANCHORS`, keyed by record file and record id
  and never by a section heading, an ordinal or a line number, totalled in the declared
  integer `CARRIED_STALE_TOTAL`, and checked as a set equality in **both** directions.
  There is **one reason string per record file**, not one per anchor, so it has to be at
  least twenty characters, carry a `#NN`, and **name every record id in that entry**;
  without the last of those a second declaration inherits the first one's reason and is
  explained by a change that had nothing to do with it, which is what happened when the
  printed literal was pasted unedited in review. Each carried record also gets a dated
  note in its own section, naming the record and the change, so a reader of the record
  sees the retirement and not only a reader of the test module. A date alone is not
  enough there either: a bare dated line satisfied an earlier version of that check.

  **That list is expected to grow, and saying so exactly matters in this file.** A
  correct change to `src/` legitimately rots an anchor, and #61 was right to make one,
  so refusing growth would be refusing the change. What the check refuses is an **undeclared** stale
  anchor. What holds the list honest is a reviewer reading a diff that includes a bump
  to a declared integer, plus the dated note in the record itself; the suite reads one
  tree and cannot tell an anchor that rotted from one that never matched, and its
  failure message says so rather than implying a declaration is proof of anything.

  **A rotted anchor is retired, not re-derived.** Editing `find` until it matches
  today's source leaves the recorded message, the result and the node ids standing
  beside an anchor they were never measured against, which is a correct measurement
  attached to the wrong subject. Repair is re-running the mutation against today's tree
  and writing a **new** record with a new id.
- **A Python mutation run sets `PYTHONDONTWRITEBYTECODE=1`.** CPython invalidates
  bytecode on `(mtime, size)`, so two same-size mutations of one file within one second
  run stale bytecode and the run reports the previous mutation's result. Scar: a false
  mutation result on PR #62 that looked exactly like a genuine finding. The JavaScript
  harness is immune, because it substitutes into source text at run time and caches
  nothing.
- **A manual check names the element it measures, and comes with a way to make it
  fail.** "No horizontal scroll" is not a check; `el.scrollWidth > el.clientWidth` over
  a named element is. And a sweep that cannot be made to fail on demand is not
  evidence, so write its positive control down beside it. Scar: `app/styles.css` sets
  `overflow: hidden` on `body` and the element that scrolls is `.content`, so the root
  element's scrollable area can never grow and
  `document.documentElement.scrollWidth === clientWidth` is constant rather than weak.
  Four task specs asked for exactly that comparison, in a browser, as the test for
  horizontal overflow. The PR #56 branch then shipped three name-bearing classes with
  no break rule at all, and every one of those criteria would have gone green on it,
  which is the same defect as an unanchored pin one level up: the check reported
  success in precisely the case it was written to catch. `tests/test_suite_integrity.py`
  refuses `documentElement` in any document under `plans/`, in `README.md` or in
  `CLAUDE.md` unless it sits inside a blockquote carrying a **date**, so a dated
  correction note may quote the old wording and a new criterion cannot be written with
  it. The date is the exemption, and that is the second scar on this rule: the first
  version of that check accepted any line starting with `>`, which is one character a
  criterion can write next to itself, so the check had a hole where its own comment
  claimed a hatch. The exemption now costs placing your criterion inside somebody's
  dated note, where it reads as part of that note. That is weaker than the reason
  `# unanchored:` demands, and unlike that hatch it enforces no minimum prose, so do not
  describe the two as equals; it is a placement cost rather than a written
  justification, and it is enough. The positive control for the corrected sweep is
  `document.body.style.overflowWrap = 'normal'` in the console: re-run the sweep and it
  must find something.
