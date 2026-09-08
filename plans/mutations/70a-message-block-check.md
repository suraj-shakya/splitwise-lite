# Mutations behind the block-anchor check (issue #70, task 70a)

Four mutations, all run and all killed, against the checks this task adds: that a
`pytest.raises` block which reads the exception's message carries an anchor, and that the
blocks which were already loose are carried in a baseline the suite checks in both
directions.

Taken against `bdca309` on 2026-09-08, on branch `task-70`, and re-taken there after merging `a595330`, which grew this module. A record quotes a
measurement, so it carries the tree it was measured on: if an anchor below no longer
matches exactly once, that is the tree to diff against rather than a defect in the
record. The suite deliberately does not re-verify these anchors; see `README.md` in this
directory for that reasoning, and for the format and the recipe.

**What each run was, named as a quantity rather than left to be inferred.** Every run
below was the whole of `tests/test_suite_integrity.py`, unfiltered, which collects **89
tests** at this revision, and the figures quoted are that module's failed and passed
counts. Nothing was selected with `-k`, so a claim that a mutation is caught by one test
is a claim about the other eighty-eight staying green, not about a filtered subset. The
second record also ran the whole of `tests/test_money.py`, **181 tests**. Every run set
`PYTHONDONTWRITEBYTECODE=1` and reverted with `git checkout -- <file>` before the next
one.

**What `survives` holds, and how to tell an observed green from an inferred one.** A
`survives` entry may name a test that was **not** among those 86, because a mutation's
useful controls are not always in the module the run covers. Every entry in every
`survives` in this file was observed green **in a named run**, and each record says which
run that was: the 86-test module run, or a second run of named node ids under the same
mutant, quoted with its own count. Nothing here is green by inference from the mutation's
shape. Where a future record cannot run an entry, it says so in prose beside that entry
rather than leaving a reader to assume, because `REQUIRED_KEYS` is an exact set and this
distinction cannot be carried by a new JSON key. Written down rather than left implicit
because seven audit slices will copy this file as their template, and a distinction the
format cannot express would otherwise be lost seven times.

**On the anchors and this tree's line endings.** The working tree is CRLF on disk, and
the first anchor below spans three lines. It still matched exactly once, because the
recipe reads the file through `read_text`, which translates newlines, and writes back
through `write_text`, which restores them. That was verified before the record was
written rather than assumed, because a three-line anchor matching zero times while the
run still reports a result is the failure `README.md` warns about.

**No entry here is numbered by position, and a claim about which tests a mutation touched
enumerates node ids rather than counting them.**
`test_every_node_id_a_record_names_is_one_it_lists` then holds those ids to the `kills`
and `survives` beside them.

**A node id in prose is a claim; a citation is written bare.** If you name another test as
a precedent, an example or a cross-reference, and are claiming nothing about it under the
mutation, write it as `test_some_name` in `tests/test_module.py` rather than as
`tests/test_module.py::test_some_name`. The `::` form is what the check reads as a claim,
and a claim has to appear in that section's `kills` or `survives`. Do not satisfy the
check by adding a citation to `survives`: `survives` means you ran it under the mutant and
watched it stay green, and an entry you did not run is an observation nobody made.

> **Found 2026-09-08, by the check reddening on a record that had already merged.** The
> convention above is not a preference somebody had; it is the answer to a real failure,
> and this is the third time this mechanism has caught something unplanned. Merging
> `a595330` into `task-70` reddened
> `test_every_node_id_a_record_names_is_one_it_lists` against Mutation 5 of
> `plans/mutations/16-incompleteness-signal.md`, which names in `::` form the precedent it
> was copied from. The citation was legitimate; reading it as a claim was not. Criterion 13
> of `plans/tasks/70-substring-assertions-on-exception-messages.md` says every node id in
> prose must be listed, and that criterion is too broad; it carries a dated correction
> saying so. The record's citation was reworded to the bare form in the same pull request,
> because a check landing red on `master` is the failure #49 exists to prevent, and
> `stray_node_id_message` now teaches this convention at the moment it fires so the
> cheapest fix stops being a false `survives` entry.

> **Corrected 2026-09-08, after QA failed PR #84.** This paragraph previously said "Every
> claim names its pytest node id", which was not true of this file when it was written:
> the `m1` record counted five blocks as two and named one of them without a `::`. The
> check cannot see a claim that names no node id, so the sentence above is now about the
> **format** the file follows and not about a guarantee the suite gives. The full
> reasoning is in the correction under the first record.

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
    "tests/test_suite_integrity.py::test_the_carried_total_is_the_sum_of_the_baseline",
    "tests/test_accounts.py::test_authenticate_refuses_a_token_it_does_not_hold",
    "tests/test_split.py::test_a_large_exact_mismatch_carries_the_formatters_comma_groups",
    "tests/test_split.py::test_a_negative_total_is_refused_with_a_leading_minus",
    "tests/test_split.py::test_a_total_above_the_maximum_is_refused_in_the_money",
    "tests/test_split.py::test_a_zero_total_is_refused_in_the_money_and_not_in_cents"
  ],
  "result": "killed"
}
```

**What the run printed:** `3 failed, 86 passed`.

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
reddened too, naming real blocks that this branch, and nothing else, was anchoring.

**How many real blocks: five, enumerated rather than counted.** In two modules.
`computed_carried_total()` moves from 107 to **112** under this mutation. Each of these
node ids names a test whose block loses its only anchor when the branch goes, and each
of them stays green under the mutant, which is why all five are in `survives` above:

- `tests/test_accounts.py::test_authenticate_refuses_a_token_it_does_not_hold`
- `tests/test_split.py::test_a_large_exact_mismatch_carries_the_formatters_comma_groups`
- `tests/test_split.py::test_a_negative_total_is_refused_with_a_leading_minus`
- `tests/test_split.py::test_a_total_above_the_maximum_is_refused_in_the_money`
- `tests/test_split.py::test_a_zero_total_is_refused_in_the_money_and_not_in_cents`

**Which run each `survives` entry here was observed in**, since this record's `survives`
draws on two. The two `tests/test_suite_integrity.py` entries are among the 86 of the
module run above, so their green is part of the `3 failed, 83 passed` already quoted. The
five listed immediately above are in other modules and so were **not** in that run; they
were run separately under the same mutant, selected by those five node ids, and printed
**15 passed**. Fifteen and not five because those five ids collect fifteen cases between
them, the ids being selectors rather than cases. Both groups are observations. No entry
in this record is green by inference.

> **Corrected 2026-09-08, after QA failed PR #84 on this paragraph.** It previously read
> "two live blocks in the suite are anchored by an equality and nothing else", and then
> named exactly one of the five, as `test_authenticate_refuses_a_token_it_does_not_hold:
> 1` rather than as a node id. **Two was the module count, not the block count**, and the
> unit of this whole task is the block. Measured two ways that agree: applying this
> mutation and running `tests/test_suite_integrity.py` unfiltered prints
> `CARRIED_TOTAL = 112`, and `computed_carried_total()` returns 112 against 107 on the
> unmutated tree.
>
> **Why the check added this week did not catch it, which is the part worth keeping.**
> `test_every_node_id_a_record_names_is_one_it_lists` polices node ids in prose. A claim
> phrased as `name: count`, or as a bare number with no name at all, holds no `::`, so
> the checker cannot see it. The record stayed green while carrying a count attached to
> the wrong subject. Prose form was the escape route around the mechanism, and it was
> sitting inside a note telling the next reader not to re-measure.
>
> **So yes: a claim of this kind has to name node ids, and this record now does.** That
> is not a style preference. Naming them puts them under the existing check, which then
> forces each id into `kills` or `survives`, which forces the writer to say of each
> whether it reddened or stayed green. That classification is what would have exposed
> the substitution, because five ids cannot be written down as two. An enumeration is
> the checkable form of a count.
>
> **The residual, stated because it is real.** Nothing forces a claim to be *phrased*
> with node ids in the first place. A later record can still write "two live blocks" and
> stay green, because no check can tell a prose number from a correct one. What has
> changed is that the format says to enumerate and that an enumeration is self-checking
> where a count is not. That is a convention which a check polices once it is followed,
> not a mechanism that forces it to be followed, and it must not be described as the
> second.
>
> **Observed 2026-09-08, unplanned, and worth more than the synthetic beside it.** While
> PR #84 was being verified, a QA probe deleted
> `tests/test_split.py::test_a_negative_total_is_refused_with_a_leading_minus` from this
> record's `survives` in a shared working tree, and then reverted it with
> `git checkout --`, which is why it read as an unexplained edit to everyone else looking
> at the tree. While it was applied,
> `test_every_node_id_a_record_names_is_one_it_lists` reddened at once and named both the
> section and that id, because the prose above enumerates five while the lists then held
> four. So this defect class has now been caught on a real drift and not only on a
> synthetic, and the enumeration is what made it catchable: the same drift against the
> `name: count` phrasing this note retracts would have been silent.

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

**What the run printed:** `1 failed, 88 passed` over
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

**What the run printed:** `1 failed, 88 passed`.

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

## Renaming a check the rules file names

```json
{
  "id": "m4-a-named-check-renamed",
  "file": "tests/test_suite_integrity.py",
  "find": "def test_every_message_block_is_anchored_or_carried(path: Path) -> None:",
  "replace": "def test_every_message_block_is_anchored_or_carried_after_a_rename(path: Path) -> None:",
  "kills": [
    "tests/test_suite_integrity.py::test_every_named_mechanism_resolves_to_something_that_exists"
  ],
  "survives": [
    "tests/test_suite_integrity.py::test_the_testing_rules_name_the_mechanisms_that_enforce_them",
    "tests/test_suite_integrity.py::test_the_mechanism_resolution_check_still_bites"
  ],
  "result": "killed"
}
```

**What the run printed:** `1 failed, 88 passed`.

**Which finding this is evidence for.** The reviewer's second blocking finding on PR #84:
that the comment beside `ENFORCING_MECHANISMS` claimed renaming a named check "would
leave the rule naming something gone", while the only check reading that tuple was
`assert mechanism in read(RULES)`, a substring assertion on markdown. This mutation is
the reviewer's scenario run rather than argued.

**The measurement, which is the point of the record.**
`tests/test_suite_integrity.py::test_the_testing_rules_name_the_mechanisms_that_enforce_them`
**stayed green** under this rename. That is the gap, measured: the rule goes on naming a
function that no longer exists and the substring check cannot tell. It is listed in
`survives` for that reason and not as a bystander, so the record's own lists carry the
finding.
`tests/test_suite_integrity.py::test_every_named_mechanism_resolves_to_something_that_exists`
is what reddened, which is the gap closed.

**The other named surviving control.**
`tests/test_suite_integrity.py::test_the_mechanism_resolution_check_still_bites` stayed
green, which says the resolution helper still refuses a synthetic name that resolves to
nothing while it is refusing this real one. Without it, a helper that had started
returning a finding for everything would look identical from this run.

**Verdict.** Killed. The comment that made the claim now points at this mutation, and the
four entries that resolve to nothing but themselves are named as such rather than left
under a claim that was true of none of them.
