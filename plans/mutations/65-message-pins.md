# Mutations behind the message-pin audit (issue #65)

Seven guard deletions covering all thirteen unanchored pins. Every run set
`PYTHONDONTWRITEBYTECODE=1`, ran the killed tests alone by node id, and reverted with
`git checkout -- <file>` before the next deletion. The message quoted in each section
is what the guard really prints, captured from a run against the unmutated tree, and
it is what each anchored pattern was derived from.

See `README.md` in this directory for the format and the recipe.

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

