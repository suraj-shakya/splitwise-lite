---
paths:
  - "tests/**"
  - "**/test_*.py"
  - "plans/mutations/**"
---

- Tests are pytest, run with `uv run python -m pytest` (plain `uv run pytest` fails on
  Windows with an access-denied spawn error)
- Test settle-up with exact integer assertions, never approximate
- Never mark a test skipped or xfail to make the suite green

## Six rules, each with the defect that produced it

A rule without its scar is one nobody believes, so each of these carries the failure it
was learned from. All six are about one thing: a check that reported success without
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
