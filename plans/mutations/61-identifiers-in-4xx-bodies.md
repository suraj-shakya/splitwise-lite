# Issue #61: identifiers in 4xx bodies

Three mutations, one per source file this task edits, each restoring exactly the
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
