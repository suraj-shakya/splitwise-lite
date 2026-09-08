# Issue #79: two unreachable 400s carry raw cents and an event id

Three mutations. The first two are the positive control this task's criteria 39, 40 and
43 ask for: every one of the five message pins in the diff replaces an assertion that
was already green, so without a mutation there is no evidence at all that the new pins
bite. The third is the named control that has to survive, so the new pins are shown not
to red at everything.

Every run set `PYTHONDONTWRITEBYTECODE=1`, applied its own `find` and `replace` with the
recipe in `README.md` after asserting the anchor matched exactly once, and reverted with
`git checkout -- <file>` against the single named file before the next one. The working
tree was committed first, at `f74ad47`.

Each run is reported twice: the node ids the record lists, run alone, and then the whole
of each affected module, unfiltered, so the figures are the complete outcome inside
those modules rather than a confirmation of what was expected. Unmutated, and measured
on this branch, those modules report **452 passed** for `tests/test_store.py`, **152
passed** for `tests/test_balances.py` and **133 passed** for
`tests/test_error_messages.py`. Every figure quoted counts pytest test outcomes.

The three `tests/test_store.py` node ids below are parametrised, over `memory` and
`file`, so a filtered run reports two cases for each of them. The balances ones and
`test_every_four_hundred_raise_site_is_declared` are not parametrised.

## 1. Put the two cent figures back

Restores `master`'s message exactly, so the mutant is the defect this task removed
rather than one invented to be killed: the offending value and `MAX_CENTS` both spelled
as digits in a 400 body.

Measured, the five node ids run alone: **7 failed, 2 passed**. The seven are the three
store pins, two parametrised cases each, plus the enumeration equality; the two passes
are the named survivor, which stores `MAX_CENTS` exactly and reads no message.

Whole modules: `tests/test_store.py` **6 failed, 446 passed**, and
`tests/test_error_messages.py` **1 failed, 132 passed**.

The enumeration equality is in `kills` for a reason worth reading. Restoring the two
interpolations changes the skeleton the `ast` walk derives, so the walked key stops
matching the row's declared key and the two-way set equality reds. That is the mechanism
this task's constraints turn on: a reworded message with a stale row does not merely red
one test, it also drops that row from the #86 guard's watch list, because the guard keys
its marked set on the same skeleton.

```json
{
  "id": "restore-the-two-cent-figures",
  "file": "src/splitwise_lite/store.py",
  "find": "            f\"{field} is above MAX_CENTS, the largest value the cents column can hold\"",
  "replace": "            f\"{field} is {value}, above MAX_CENTS ({MAX_CENTS}), the largest value the \"\n            f\"cents column can hold\"",
  "kills": [
    "tests/test_store.py::test_a_total_above_the_bound_is_rejected_naming_the_field",
    "tests/test_store.py::test_an_allocation_above_the_bound_is_rejected_naming_the_field",
    "tests/test_store.py::test_a_settlement_amount_above_the_bound_is_rejected",
    "tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared"
  ],
  "survives": [
    "tests/test_store.py::test_the_largest_storable_amount_round_trips_exactly"
  ],
  "result": "killed"
}
```

## 2. Put the event id back

Restores `master`'s message exactly, so the mutant is again the shipped defect: an event
id interpolated into a 400 body.

Measured, the four node ids run alone: **3 failed, 1 passed**. The three are the two
balances pins and the enumeration equality; the pass is the named survivor, a settlement
in a foreign currency, which asserts the type and reads no message.

Whole modules: `tests/test_balances.py` **2 failed, 150 passed**, and
`tests/test_error_messages.py` **1 failed, 132 passed**.

Worth reading off this one: both balances pins fail on the `==`, and both would have
stayed green unedited, because each block's surviving assertions are `"NZD"` and `"AUD"`
and the mutant keeps both codes. The `"e1" not in` negative is what the id restores, and
it is documentation of the removed defect rather than the anchor. The anchor is the `==`.

```json
{
  "id": "restore-the-event-id",
  "file": "src/splitwise_lite/balances.py",
  "find": "            f\"cannot combine {event.currency.code} and {currency.code}: one {label} \"\n            f\"is in {event.currency.code} and the ledger is in {currency.code}\"",
  "replace": "            f\"cannot combine {event.currency.code} and {currency.code}: {label} \"\n            f\"{event.id!r} is in {event.currency.code} and the ledger is in \"\n            f\"{currency.code}\"",
  "kills": [
    "tests/test_balances.py::test_a_foreign_currency_raises_currency_mismatch_naming_both_codes",
    "tests/test_balances.py::test_a_foreign_currency_raises_currency_mismatch_for_a_walk_too",
    "tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared"
  ],
  "survives": [
    "tests/test_balances.py::test_a_settlement_in_a_foreign_currency_raises_currency_mismatch"
  ],
  "result": "killed"
}
```

## 3. Reword the store row's reason, which must survive

The named control. It rewords the `reason` text of the `store.py` row this task edits,
keeping it well above `MIN_REASON` characters. That changes no behaviour, no message and
no skeleton, so nothing may red. One test does read a reason,
`test_every_site_no_request_reaches_says_what_would_have_to_be_true`, but only its
length.

Measured, the six node ids run alone: **9 passed, 0 failed**, nine because three of the
six are parametrised over `memory` and `file`. The reason-length test, run alone,
passed. Whole modules: `tests/test_store.py` and `tests/test_balances.py` together
**604 passed**, `tests/test_error_messages.py` **133 passed**, and
`tests/test_suite_integrity.py` **92 passed**.

A `killed` here would have meant something in the suite pins a reason's wording rather
than its length, which would have been its own finding to report. Nothing does.

```json
{
  "id": "reword-the-store-rows-reason",
  "file": "tests/test_error_messages.py",
  "find": "        \"money.parse_amount refuses anything above MAX_CENTS at the input edge, so a \"\n        \"request is answered from invalid_amount long before the column's own bound \"\n        \"is consulted; reaching this needs a caller inside the process building an \"\n        \"event from cents directly, which is what events.py puts no upper bound on\",",
  "replace": "        \"the input edge refuses anything above MAX_CENTS before the column's own \"\n        \"bound is ever consulted, so reaching this needs an in-process caller that \"\n        \"builds an event from cents directly\",",
  "kills": [],
  "survives": [
    "tests/test_store.py::test_a_total_above_the_bound_is_rejected_naming_the_field",
    "tests/test_store.py::test_an_allocation_above_the_bound_is_rejected_naming_the_field",
    "tests/test_store.py::test_a_settlement_amount_above_the_bound_is_rejected",
    "tests/test_balances.py::test_a_foreign_currency_raises_currency_mismatch_naming_both_codes",
    "tests/test_balances.py::test_a_foreign_currency_raises_currency_mismatch_for_a_walk_too",
    "tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared"
  ],
  "result": "survived"
}
```
