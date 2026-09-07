# Issue #61: identifiers in 4xx bodies

Five mutations. Three, one per source file this task edits, each restoring exactly the
interpolation the task removed. Each was applied with the recipe in `README.md`,
`PYTHONDONTWRITEBYTECODE=1` set on every run, the node ids in `kills` run alone, and
`git checkout -- <file>` before the next.

Every one of the three kills two different kinds of test, which is the point of the
pair of checks: the driven row in `tests/test_error_messages.py` goes red because an id
the store holds is back in the body, and
`test_every_four_hundred_raise_site_is_declared` goes red because restoring an
interpolation changes the message skeleton, so the walked key no longer equals the
declared one. Either check alone would catch a restored leak here; both catch it, and
the enumeration would also catch a *new* site nobody had thought about.

> **Re-verification, 2026-09-07.** All five records were re-applied from their own `find`
> and `replace`, one at a time, each anchor asserted to match exactly once, each reverted
> with `git checkout -- <file>` before the next, `PYTHONDONTWRITEBYTECODE=1` on every
> run. Rather than run each `kills` node id alone, each mutation was measured by running
> whole modules, which yields the complete kill set inside them instead of only
> confirming the ids already listed. Four records measured exactly as recorded. The
> fifth, `make-the-identifier-search-total`, did not, and carries its own correction.
>
> | record | modules run | measured | against the record |
> |---|---|---|---|
> | `restore-the-payer-id` | `test_error_messages.py test_web_api.py` | 3 failed, 539 passed | exactly the 3 listed kills, both listed survivors green |
> | `restore-the-member-id-and-the-figure` | `test_error_messages.py test_split.py` | 4 failed, 240 passed | exactly the 4 listed kills, both listed survivors green |
> | `restore-the-group-and-user-ids` | `test_error_messages.py test_groups.py` | 2 failed, 263 passed | exactly the 2 listed kills, both listed survivors green |
> | `blind-the-identifier-search` | `test_error_messages.py` | 3 failed, 61 passed | exactly the 3 listed kills, both listed survivors green |
> | `make-the-identifier-search-total` | `test_error_messages.py` | 58 failed, 6 passed | **understated**, see the correction below |
>
> Two prose claims above were re-measured with the same runs and both hold. The claim
> that each of the three source mutations kills two kinds of test at once is true of all
> three: every one of them reds its driven row and
> `test_every_four_hundred_raise_site_is_declared`. And the claim under mutations 4 and 5
> that blinding the search passes all 56 driven rows was re-run as
> `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_error_messages.py -q -k
> "no_four_hundred_body_names_an_identifier"`, which reports `56 passed, 8 deselected`.
>
> One further claim was measured as a side effect, and it holds. Record 3 says no test in
> `tests/test_groups.py` asserts that message's text, so the driven row is the only thing
> holding it. Under that mutation the whole of `tests/test_groups.py` stayed green, which
> is that claim measured rather than read.

## 1. The payer, in `web.py`

The site the spec numbers 3, and the one criterion 35 names. `{payer_id!r}` is a member
id of the group the caller is a member of.

```json
{
  "id": "restore-the-payer-id",
  "file": "src/splitwise_lite/web.py",
  "find": "        raise MalformedRequest(\n            f\"{what} names a payer_id that is not a member of this group\"\n        )",
  "replace": "        raise MalformedRequest(\n            f\"{what} names a payer_id that is not a member of this group: \"\n            f\"{payer_id!r}\"\n        )",
  "kills": [
    "tests/test_error_messages.py::test_no_four_hundred_body_names_an_identifier[web.py::_create_expense::names_a_payer_id_that_is_not_a_member_of_this_gr]",
    "tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared",
    "tests/test_web_api.py::test_a_payer_who_is_not_a_member_is_refused_without_naming_them"
  ],
  "survives": [
    "tests/test_error_messages.py::test_identifiers_in_finds_nothing_in_an_id_free_message",
    "tests/test_web_api.py::test_a_split_naming_a_member_twice_is_refused_by_the_resolver"
  ],
  "result": "killed"
}
```

## 2. The negative weight or amount, in `split.py`

The site the spec numbers 2. It carried a member id and a bare integer that was a
weight for one caller and raw cents for the other, which is the `CLAUDE.md` money-rule
half of this task.

```json
{
  "id": "restore-the-member-id-and-the-figure",
  "file": "src/splitwise_lite/split.py",
  "find": "            raise InvalidSplit(f\"every {field} must be zero or positive\")",
  "replace": "            raise InvalidSplit(\n                f\"{field} for {member_id!r} must be zero or positive, got {value}\"\n            )",
  "kills": [
    "tests/test_error_messages.py::test_no_four_hundred_body_names_an_identifier[split.py::_ordered_from_mapping::every_must_be_zero_or_positive]",
    "tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared",
    "tests/test_split.py::test_split_by_weight_rejects_a_negative_weight",
    "tests/test_split.py::test_split_exact_rejects_a_negative_amount"
  ],
  "survives": [
    "tests/test_split.py::test_split_by_weight_rejects_weights_that_all_sum_to_zero",
    "tests/test_split.py::test_split_equally_rejects_a_repeated_member"
  ],
  "result": "killed"
}
```

## 3. The group and the user, in `groups.py`

The site the spec numbers 12, and the only one of the twelve whose sentence reaches no
screen today: `app/api.js` classifies 403 `member_not_linked` as `not-linked` and
`speaks()` returns false for that kind, so `say` is `''`. It reaches the wire and the
browser's network panel, which is why the check has to cover it and the screen cannot.

No test in `tests/test_groups.py` asserts this message's text, before this task or
after it, so the driven row below is the only thing that holds it. That is why it is
recorded here: the mutation is the evidence that the row bites.

```json
{
  "id": "restore-the-group-and-user-ids",
  "file": "src/splitwise_lite/groups.py",
  "find": "        raise MemberNotLinked(\n            \"no member of this group is linked to your account; an operator links a \"\n            \"member with 'setup_group.py link'\"\n        ) from error",
  "replace": "        raise MemberNotLinked(\n            f\"no member of group {group_id!r} is linked to user {user_id!r}; an \"\n            f\"operator links a member with 'setup_group.py link'\"\n        ) from error",
  "kills": [
    "tests/test_error_messages.py::test_no_four_hundred_body_names_an_identifier[groups.py::acting_member::no_member_of_this_group_is_linked_to_your_accoun]",
    "tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared"
  ],
  "survives": [
    "tests/test_groups.py::test_an_unlinked_user_and_an_unknown_group_are_told_apart_by_type",
    "tests/test_error_messages.py::test_every_site_no_request_reaches_says_what_would_have_to_be_true"
  ],
  "result": "killed"
}
```

## 4 and 5. The check itself, in both directions

The three above mutate the code under test. These two mutate the **check**, because
criterion 30 claims the four `identifiers_in` unit tests are what prove the property
half bites, and that claim is worth measuring rather than asserting.

**Blinding it passes all 56 driven rows vacuously.** That was measured, not reasoned:
under mutation 4, `uv run python -m pytest tests/test_error_messages.py -k
"no_four_hundred_body_names_an_identifier"` reports **56 passed**. So the driven
parametrisation cannot police its own instrument, and the four unit tests are the only
thing standing between a green suite and a check that inspects nothing. That is exactly
the shape of defect `.claude/rules/testing.md` rule (d) is about, one level up.

```json
{
  "id": "blind-the-identifier-search",
  "file": "tests/test_error_messages.py",
  "find": "    return [found for found in identifiers if found in message]",
  "replace": "    return []",
  "kills": [
    "tests/test_error_messages.py::test_identifiers_in_finds_an_identifier_that_is_present",
    "tests/test_error_messages.py::test_identifiers_in_finds_an_identifier_wrapped_in_punctuation",
    "tests/test_error_messages.py::test_identifiers_in_reports_both_identifiers_when_two_are_present"
  ],
  "survives": [
    "tests/test_error_messages.py::test_identifiers_in_finds_nothing_in_an_id_free_message",
    "tests/test_error_messages.py::test_no_four_hundred_body_names_an_identifier[web.py::_create_expense::names_a_payer_id_that_is_not_a_member_of_this_gr]"
  ],
  "result": "killed"
}
```

The other direction, so the four tests pin the function from both sides rather than
only rewarding a search that finds things.

> **Correction, 2026-09-07.** This section used to close: "The id-free case is the
> control, and it is **the only one of the four** that this mutation kills." That is
> wrong, and it understates the mutation in both halves.
>
> Re-measured by applying this record's own `find` and `replace` through the recipe in
> `README.md`, which reported the anchor matching exactly once, and then running
> `PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_error_messages.py -q`:
> **58 failed, 6 passed**. Of the four `identifiers_in` unit tests this mutation kills
> **two**, not one: `test_identifiers_in_finds_nothing_in_an_id_free_message`, which is
> the control, and `test_identifiers_in_reports_both_identifiers_when_two_are_present`,
> which reds because a total function also reports the third identifier the message does
> not contain. It also kills **all 56 driven rows** of
> `test_no_four_hundred_body_names_an_identifier`, which the retracted sentence implies
> stay green. The six survivors, listed from the same run under `-v`, are the other two
> unit tests plus `test_every_four_hundred_raise_site_is_declared`,
> `test_the_skeleton_of_a_message_drops_its_interpolations`,
> `test_stored_identifiers_gathers_every_id_the_store_holds` and
> `test_every_site_no_request_reaches_says_what_would_have_to_be_true`.
>
> The block below was extended in the same pass, from one entry in each list to three.
> `kills` gained `test_identifiers_in_reports_both_identifiers_when_two_are_present` and
> one driven row, the `_create_expense` payer row, standing for all 56. `survives` gained
> `test_identifiers_in_finds_an_identifier_wrapped_in_punctuation` and
> `test_every_four_hundred_raise_site_is_declared`. Neither list is exhaustive even now,
> since writing out all 56 driven rows would bury the shape; the run above is the
> exhaustive record. `result` is unchanged: the mutation was killed either way, and the
> block was legal before, because the format does not require a list to be exhaustive.
> What was wrong was the sentence claiming that it was.
>
> The asymmetry this section was reaching for is real, but it runs the other way.
> Blinding the search is caught **only** by the unit tests, because all 56 driven rows
> pass vacuously under mutation 4. Making it total is caught by the control **and** by
> all 56 rows. So it is mutation 4, not mutation 5, that those unit tests are the sole
> guard against, which is the claim criterion 30 rests on and which mutation 4 measures.

```json
{
  "id": "make-the-identifier-search-total",
  "file": "tests/test_error_messages.py",
  "find": "    return [found for found in identifiers if found in message]",
  "replace": "    return list(identifiers)",
  "kills": [
    "tests/test_error_messages.py::test_identifiers_in_finds_nothing_in_an_id_free_message",
    "tests/test_error_messages.py::test_identifiers_in_reports_both_identifiers_when_two_are_present",
    "tests/test_error_messages.py::test_no_four_hundred_body_names_an_identifier[web.py::_create_expense::names_a_payer_id_that_is_not_a_member_of_this_gr]"
  ],
  "survives": [
    "tests/test_error_messages.py::test_identifiers_in_finds_an_identifier_that_is_present",
    "tests/test_error_messages.py::test_identifiers_in_finds_an_identifier_wrapped_in_punctuation",
    "tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared"
  ],
  "result": "killed"
}
```
