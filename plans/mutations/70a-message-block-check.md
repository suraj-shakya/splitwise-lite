# Mutations behind the block-anchor check (issue #70, task 70a)

Three mutations, all run and all killed, against the check this task adds: that a
`pytest.raises` block which reads the exception's message carries an anchor, and that the
blocks which were already loose are carried in a baseline the suite checks in both
directions.

Taken against `0f30663` on 2026-09-08, on branch `task-70`. A record quotes a
measurement, so it carries the tree it was measured on: if an anchor below no longer
matches exactly once, that is the tree to diff against rather than a defect in the
record. The suite deliberately does not re-verify these anchors; see `README.md` in this
directory for that reasoning, and for the format and the recipe.

**What each run was, named as a quantity rather than left to be inferred.** Every run
below was the whole of `tests/test_suite_integrity.py`, unfiltered, which collects **82
tests** at this revision, and the figures quoted are that module's failed and passed
counts. Nothing was selected with `-k`, so a claim that a mutation is caught by one test
is a claim about the other eighty-one staying green, not about a filtered subset. The
second record also ran the whole of `tests/test_money.py`, **181 tests**. Every run set
`PYTHONDONTWRITEBYTECODE=1` and reverted with `git checkout -- <file>` before the next
one.

**On the anchors and this tree's line endings.** The working tree is CRLF on disk, and
the first anchor below spans three lines. It still matched exactly once, because the
recipe reads the file through `read_text`, which translates newlines, and writes back
through `write_text`, which restores them. That was verified before the record was
written rather than assumed, because a three-line anchor matching zero times while the
run still reports a result is the failure `README.md` warns about.

**No entry here is numbered by position.** Every claim names its pytest node id, and
`test_every_node_id_a_record_names_is_one_it_lists` holds the prose below to the `kills`
and `survives` beside it.

## Deleting the equality branch of the accepted set

```json
{
  "id": "m1-equality-branch-deleted",
  "file": "tests/test_suite_integrity.py",
  "find": "            if isinstance(node, ast.Compare) and any(\n                isinstance(op, ast.Eq) for op in node.ops\n            ):",
  "replace": "            if False:",
  "kills": [
    "tests/test_suite_integrity.py::test_the_message_block_check_still_bites",
    "tests/test_suite_integrity.py::test_every_message_block_is_anchored_or_carried[tests/test_accounts.py]",
    "tests/test_suite_integrity.py::test_every_message_block_is_anchored_or_carried[tests/test_split.py]"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_the_pin_check_still_bites",
    "tests/test_suite_integrity.py::test_the_carried_total_is_the_sum_of_the_baseline"
  ],
  "result": "killed"
}
```

**What the run printed:** `3 failed, 79 passed`.

**Which criterion this is evidence for.** Criterion 22a: a branch of the accepted set is
deleted and the self-test that covers it reds. The branch is 10b, an `==` against the
whole message.

**What reddened, and the part worth having.** The synthetic self-test
`tests/test_suite_integrity.py::test_the_message_block_check_still_bites` reds at its
case (c), which is the assertion labelled in the source as the positive control for this
branch. That much was designed in. The part that was not designed in is that
`tests/test_suite_integrity.py::test_every_message_block_is_anchored_or_carried[tests/test_accounts.py]`
and
`tests/test_suite_integrity.py::test_every_message_block_is_anchored_or_carried[tests/test_split.py]`
reddened too, naming real blocks: two live blocks in the suite are anchored by an
equality and nothing else, so deleting the branch makes them findings the baseline does
not carry. The failure named
`test_authenticate_refuses_a_token_it_does_not_hold: 1` under "These are unanchored and
not carried, so they are new".

**The named surviving control.**
`tests/test_suite_integrity.py::test_the_pin_check_still_bites` stayed green. That is the
control that matters here rather than an arbitrary passing test: it is the sibling
check's own self-test, and its survival is the evidence that the two checks are
independent, that neither restates the other's guarantee, and that this mutation reached
only the new one.

**Verdict.** Killed, for the reason the mutation names. The branch has live subjects as
well as a synthetic one.

## Anchoring a real carried block without updating the baseline

```json
{
  "id": "m2-a-carried-block-anchored",
  "file": "tests/test_money.py",
  "find": "with pytest.raises(InvalidCurrency) as excinfo:",
  "replace": "with pytest.raises(\n        InvalidCurrency,\n        match=r\"^currency code must be three uppercase A-Z letters\",\n    ) as excinfo:",
  "kills": [
    "tests/test_suite_integrity.py::test_every_message_block_is_anchored_or_carried[tests/test_money.py]"
  ],
  "survives": [
    "tests/test_money.py::test_currency_rejects_lowercase_rather_than_coercing",
    "tests/test_suite_integrity.py::test_every_message_pin_is_anchored_or_says_why[tests/test_money.py]",
    "tests/test_suite_integrity.py::test_the_message_block_check_still_bites"
  ],
  "result": "killed"
}
```

**The message the guard actually prints**, captured from a run against the unmutated
tree rather than read out of the guard's source:

    currency code must be three uppercase A-Z letters: 'aud'

**What the run printed:** `1 failed, 81 passed` over
`tests/test_suite_integrity.py`, and `181 passed` over `tests/test_money.py`.

**Which criterion this is evidence for.** Criterion 22b: the **stale** direction of the
baseline, which is the direction that stops it becoming an allowlist nobody retires. The
mutation does what an audit slice does, anchors one carried block, and then omits the
one thing a slice must also do, take the block out of the baseline.

**What reddened, and the entry it named.**
`tests/test_suite_integrity.py::test_every_message_block_is_anchored_or_carried[tests/test_money.py]`
reddened, and named the entry:

    These are carried but are no longer unanchored, so the entry has outlived its subject:
        test_currency_rejects_lowercase_rather_than_coercing: 1

It then printed the corrected entry to paste back and the line `CARRIED_TOTAL = 106`,
which is 107 less the one block that had just been anchored. No number in that failure is
a hand count, and the paste-back is the only sanctioned way the baseline is maintained.

**The named surviving controls.**
`tests/test_money.py::test_currency_rejects_lowercase_rather_than_coercing` stayed green
under the anchor, so the pattern is a real one derived from the captured message and not
a pattern that happens to make the check quiet. And
`tests/test_suite_integrity.py::test_every_message_pin_is_anchored_or_says_why[tests/test_money.py]`
stayed green, because the pattern leads with `^`; had it not, the sibling check would
have caught it, which is the division of labour between the two.

**Verdict.** Killed. The second direction of the baseline is not decorative: it fires on
a real file, names the real function, and prints the real replacement.

## Deleting the startswith branch of the accepted set

```json
{
  "id": "m3-startswith-branch-deleted",
  "file": "tests/test_suite_integrity.py",
  "find": "                and node.func.attr == \"startswith\"",
  "replace": "                and node.func.attr == \"startswith_which_no_call_has\"",
  "kills": [
    "tests/test_suite_integrity.py::test_the_message_block_check_still_bites"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_the_carried_total_is_the_sum_of_the_baseline",
    "tests/test_suite_integrity.py::test_every_message_block_is_anchored_or_carried[tests/test_accounts.py]"
  ],
  "result": "killed"
}
```

**What the run printed:** `1 failed, 81 passed`.

**Which criterion this is evidence for.** Criterion 21, that each accepted case in the
self-tests is one that goes red if the branch accepting it is removed. This is the third
branch, 10c.

**What this one establishes that the first does not, stated as a finding rather than as a
pass.** Only the synthetic self-test
`tests/test_suite_integrity.py::test_the_message_block_check_still_bites` reddened. Every
one of the nineteen parametrised cases of the baseline check stayed green, and
`tests/test_suite_integrity.py::test_every_message_block_is_anchored_or_carried[tests/test_accounts.py]`
is named here as the representative survivor. So `.startswith` is in the accepted set
with **no live subject anywhere in the suite today**: not one block in `tests/` is
anchored that way. That is a real asymmetry with the equality branch above, and it is
recorded rather than smoothed over, because it means the self-test is the whole of what
guards this branch. Deleting the branch would be a behaviour change nothing but that one
assertion would notice.

**The named surviving control.**
`tests/test_suite_integrity.py::test_the_carried_total_is_the_sum_of_the_baseline` stayed
green, which is what says the mutation touched the walk and not the arithmetic over the
baseline.

**Verdict.** Killed, and a finding beside it: the branch is currently synthetic-only, so
it is the audit slices 70b to 70h, if any of them chooses `.startswith` over `match=`,
that will give it a live subject.
