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
  which is the unit the fix has, that population is **107**, computed by the check and not
  by anybody's grep.

  The blocks that were already loose when the check landed are carried in
  `CARRIED_UNANCHORED_BLOCKS`, keyed by test module, enclosing definition name and count,
  never by a line number or an ordinal, and totalled in one declared integer. **The
  baseline may only shrink.** It is checked in both directions, so a carried entry that is
  no longer unanchored is a failure naming it and an entry cannot outlive its subject, and
  the last of issue #70's audit slices deletes it. Carrying a block is not anchoring one:
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
