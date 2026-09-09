# Mutations behind the message-pin audit (issue #65)

Seven guard deletions covering all thirteen unanchored pins. Every run set
`PYTHONDONTWRITEBYTECODE=1`, ran the killed tests alone by node id, and reverted with
`git checkout -- <file>` before the next deletion. The message quoted in each section
is what the guard really prints, captured from a run against the unmutated tree, and
it is what each anchored pattern was derived from.

Taken against `7bf518c` on 2026-09-07, on branch `task-hygiene`. A record quotes a
measurement, so it carries the tree it was measured on: if an anchor below no longer
matches exactly once, that is the tree to diff against rather than a defect in the
record. Every anchor below is swept by the suite, which counts each `find` in the file
that record's `file` key names and requires exactly one match or a declaration; see
`README.md` in this directory for what that check does and does not promise, and for
the format and the recipe.

> **Corrected 2026-09-08 for issue #87**, per
> `plans/tasks/87-a-mutation-records-anchor-matches-zero-times.md`. This paragraph used
> to end: "The suite deliberately does not re-verify these anchors; see `README.md` in
> this directory for that reasoning". That is no longer true of this repo.
> `test_every_recorded_anchor_matches_once_or_is_carried` in
> `tests/test_suite_integrity.py` counts every recorded `find` in its target and refuses
> anything but exactly one match, unless the record is declared in
> `CARRIED_STALE_ANCHORS` with a reason naming the change that broke it. Leaving the
> retired sentence in place would have put a false statement about the suite in the one
> file that holds the one declared entry. What is still true, and is what that sentence
> was protecting, is narrower: no recorded mutation is re-run and no `result` is
> verified, so a matching anchor proves a record **appliable** and not correct.

## The weights-sum-to-zero refusal in split.py

```json
{
  "id": "g1-weights-sum-to-zero",
  "file": "src/splitwise_lite/split.py",
  "find": "        raise InvalidSplit(\n            \"weights sum to zero, so there is no share to divide the total into\"\n        )",
  "replace": "        pass",
  "kills": [
    "tests/test_split.py::test_split_by_weight_rejects_weights_that_all_sum_to_zero"
  ],
  "survives": [
    "tests/test_split.py::test_split_by_weight_rejects_a_negative_weight"
  ],
  "result": "killed"
}
```

**The message the guard actually prints**, from a run against the unmutated tree:

    weights sum to zero, so there is no share to divide the total into

**What the run printed with the guard deleted:**

    ZeroDivisionError: integer division or modulo by zero

**Pins this guard covers:**

- 1. `test_split_by_weight_rejects_weights_that_all_sum_to_zero`, pattern `"zero"`

**Verdict.** Rung 1. With the refusal gone the call reaches `divmod(..., 0)` and dies, so the guard is real and fires first; the pin was merely loose, and `"zero"` would also have matched the word in any other sentence this call could produce.

## The repeated-member refusal in split.py

```json
{
  "id": "g2-repeated-member",
  "file": "src/splitwise_lite/split.py",
  "find": "        raise InvalidSplit(\n            f\"member_ids names a member more than once: {list(ordered)}\"\n        )",
  "replace": "        pass",
  "kills": [
    "tests/test_split.py::test_split_equally_rejects_a_repeated_member"
  ],
  "survives": [
    "tests/test_split.py::test_split_equally_rejects_an_empty_member_list"
  ],
  "result": "killed"
}
```

**The message the guard actually prints**, from a run against the unmutated tree:

    member_ids names a member more than once: ['ali', 'bo', 'ali']

**What the run printed with the guard deleted:**

    Failed: DID NOT RAISE InvalidSplit

**Pins this guard covers:**

- 2. `test_split_equally_rejects_a_repeated_member`, pattern `"more than once"`

**Verdict.** Rung 1. Nothing else refuses a repeated member, so the deletion leaves the call returning a split that silently double-counts somebody.

> **Retired 2026-09-08 for issue #87**, per
> `plans/tasks/87-a-mutation-records-anchor-matches-zero-times.md`. **This record's
> anchor no longer matches its target, and the record is kept exactly as it stands
> rather than repaired.** The `find` above quotes the fragment `{list(ordered)}`, which
> **#61** removed when it took member ids out of 4xx bodies. `src/splitwise_lite/split.py:343`
> now reads, on one line, `raise InvalidSplit("member_ids names a member more than once")`,
> with a comment above it saying the refusal names the payload key and not the ids. So
> the `find` above occurs **zero** times in that file and the recipe in `README.md`
> refuses to apply it. The message quoted in this section is what the guard printed on
> `7bf518c` on 2026-09-07, the tree this file's intro records, and today's guard cannot
> print it at all: the ids are gone.
>
> **Nothing above this note is edited, and that is the decision rather than an
> oversight.** What a record preserves is a measurement, not a string. Re-deriving
> `find` against today's source would leave every sentence in this section standing
> beside an anchor they were never measured against, the printed message and the
> deletion's own output included, which is a correct measurement attached to the wrong
> subject and the defect this directory exists to refuse. Deleting the section would
> delete the only record of pin 2's coverage in the #65 audit in order to make a check
> green. So the pair `("g2-repeated-member", 0)` is declared in `CARRIED_STALE_ANCHORS`
> in `tests/test_suite_integrity.py` with a reason naming #61, and this note is that
> same fact where a reader of the record will see it.
>
> **What repair would be, for whoever wants it:** run this mutation again against
> today's tree, capture what that run prints, and write a **new** record with a new id,
> in a new file or in `plans/mutations/87-stale-anchor-check.md`. That is a fresh
> measurement and it is legitimate. Editing this record is not, and neither is deriving
> an anchor by reading the guard, which is what this file's intro says every pattern
> here was not.
>
> Both node ids this record lists are still live, measured on 2026-09-08:
> `test_split_equally_rejects_a_repeated_member` and
> `test_split_equally_rejects_an_empty_member_list` in `tests/test_split.py`, at lines
> 408 and 403. Only the anchor has rotted.

## The not-a-ledger-event refusal in balances.py

```json
{
  "id": "g3-not-a-ledger-event",
  "file": "src/splitwise_lite/balances.py",
  "find": "            raise TypeError(\n                f\"events may only contain ledger events, got \"\n                f\"{type(event).__name__}: {event!r}\"\n            )",
  "replace": "            pass",
  "kills": [
    "tests/test_balances.py::test_an_element_that_is_not_a_ledger_event_raises_type_error_naming_it"
  ],
  "survives": [
    "tests/test_balances.py::test_events_that_is_not_iterable_raises_type_error"
  ],
  "result": "killed"
}
```

**The message the guard actually prints**, from a run against the unmutated tree:

    events may only contain ledger events, got dict: {'total': 1000}
    events may only contain ledger events, got NoneType: None

**What the run printed with the guard deleted:**

    Failed: DID NOT RAISE TypeError

**Pins this guard covers:**

- 3. `test_an_element_that_is_not_a_ledger_event_raises_type_error_naming_it`, first block, pattern `"dict"`
- 4. the same test, second block, pattern `"NoneType"`

**Verdict.** Rung 1 for both. The node-id run reds at the first block, which masks the second, so the second was audited by calling `settlement_states([None])` directly under the same deletion: it raised nothing at all. One guard, both pins.

## The group-id type refusal in balances.py

```json
{
  "id": "g4-group-id-not-a-str",
  "file": "src/splitwise_lite/balances.py",
  "find": "        raise TypeError(\n            f\"group_id must be a str, got {type(value).__name__}: {value!r}\"\n        )",
  "replace": "        pass",
  "kills": [
    "tests/test_balances.py::test_a_group_id_that_is_not_a_str_raises_type_error"
  ],
  "survives": [
    "tests/test_balances.py::test_an_empty_group_id_is_a_domain_error"
  ],
  "result": "killed"
}
```

**The message the guard actually prints**, from a run against the unmutated tree:

    group_id must be a str, got int: 7

**What the run printed with the guard deleted:**

    Failed: DID NOT RAISE TypeError

**Pins this guard covers:**

- 5. `test_a_group_id_that_is_not_a_str_raises_type_error`, pattern `"int"`

**Verdict.** Rung 1. The empty-string refusal below it survives the deletion, which is why the control still passes.

## The currency type refusal in balances.py

```json
{
  "id": "g5-currency-not-a-currency",
  "file": "src/splitwise_lite/balances.py",
  "find": "        raise TypeError(\n            f\"currency must be a Currency, got {type(value).__name__}: {value!r}\"\n        )",
  "replace": "        pass",
  "kills": [
    "tests/test_balances.py::test_a_currency_that_is_not_a_currency_raises_type_error"
  ],
  "survives": [
    "tests/test_balances.py::test_a_foreign_currency_raises_currency_mismatch_naming_both_codes"
  ],
  "result": "killed"
}
```

**The message the guard actually prints**, from a run against the unmutated tree:

    currency must be a Currency, got str: 'AUD'

**What the run printed with the guard deleted:**

    Failed: DID NOT RAISE TypeError

**Pins this guard covers:**

- 6. `test_a_currency_that_is_not_a_currency_raises_type_error`, pattern `"str"`

**Verdict.** Rung 1, and this is the pin criterion 26 flagged as highest suspicion. It is NOT the PR #62 shape: the arrangement passes an empty event list, so nothing downstream ever constructs a `Money` with the bad currency, and with the guard deleted the call raises nothing rather than raising `Money`'s superstring. The pattern was still weak and is now anchored.

## The foreign-group refusal in balances.py

```json
{
  "id": "g6-foreign-group",
  "file": "src/splitwise_lite/balances.py",
  "find": "        raise InvalidLedger(\n            f\"{label} {event.id!r} belongs to group {event.group_id!r}, not the group \"\n            f\"asked for, {group_id!r}\"\n        )",
  "replace": "        pass",
  "kills": [
    "tests/test_balances.py::test_a_foreign_settlement_is_rejected_too"
  ],
  "survives": [
    "tests/test_balances.py::test_a_foreign_currency_raises_currency_mismatch_naming_both_codes"
  ],
  "result": "killed"
}
```

**The message the guard actually prints**, from a run against the unmutated tree:

    settlement 's-foreign' belongs to group 'group-holiday', not the group asked for, 'group-dinner'

**What the run printed with the guard deleted:**

    Failed: DID NOT RAISE InvalidLedger

**Pins this guard covers:**

- 7. `test_a_foreign_settlement_is_rejected_too`, pattern `"s-foreign"`

**Verdict.** Rung 1. The currency-mismatch guard beside it is untouched, so the control still refuses a foreign currency in the same group.

## The repeated-id refusal in _sorted_unique

```json
{
  "id": "g7-repeated-id",
  "file": "src/splitwise_lite/balances.py",
  "find": "            raise InvalidLedger(\n                f\"the same {label} id appears twice in the ledger: {event.id!r}\"\n            )",
  "replace": "            pass",
  "kills": [
    "tests/test_balances.py::test_a_repeated_expense_id_is_a_domain_error_naming_the_id",
    "tests/test_balances.py::test_a_repeated_settlement_id_is_a_domain_error_naming_the_id",
    "tests/test_balances.py::test_a_repeated_decision_id_is_a_domain_error_naming_the_id",
    "tests/test_balances.py::test_both_public_functions_refuse_a_log_that_double_counts_an_expense"
  ],
  "survives": [
    "tests/test_balances.py::test_two_distinct_events_with_equal_amounts_are_fine"
  ],
  "result": "killed"
}
```

**The message the guard actually prints**, from a run against the unmutated tree:

    the same expense id appears twice in the ledger: 'e1'
    the same settlement id appears twice in the ledger: 's1'
    the same settlement decision id appears twice in the ledger: 'd1'

**What the run printed with the guard deleted:**

    Failed: DID NOT RAISE InvalidLedger  (all four tests)

**Pins this guard covers:**

- 8. `test_a_repeated_expense_id_is_a_domain_error_naming_the_id`, pattern `"e1"`
- 9. `test_a_repeated_settlement_id_is_a_domain_error_naming_the_id`, pattern `"s1"`
- 10. the same test, `settlement_states` block, pattern `"s1"`
- 11. `test_a_repeated_decision_id_is_a_domain_error_naming_the_id`, pattern `"d1"`
- 12. `test_both_public_functions_refuse_a_log_that_double_counts_an_expense`, pattern `"e1"`
- 13. the same test, `settlement_states` block, pattern `"e1"`

**Verdict.** Rung 1 for all six. One guard covers six pins. Pin 13 is criterion 26's second flagged suspicion, and it holds: with the guard deleted `settlement_states` on that ledger raises nothing at all, so no other message naming `e1` was standing in for it. The anchored patterns now name the label as well as the id, so an expense collision can no longer be satisfied by a settlement one.

