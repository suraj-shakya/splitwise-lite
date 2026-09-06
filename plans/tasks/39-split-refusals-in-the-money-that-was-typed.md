# Task 39: the split resolver refuses in the money that was typed

**Depends on:** 2 (complete, on `master`), 3 (complete, on `master`), 9a (complete, on
`master`), 10 (complete, on `master`), 51 (complete, on `master`)
**Consumed by:** nothing blocks on it. Backlog 18, the end-to-end smoke test, calls the
resolver and will pick up the new argument; see "Notes for the queued tasks" at the end.

Closes GitHub issue #39. `plans/backlog.md` has no entry for this and this task does not
add one; the issue is the backlog entry and this file is the implementable version.

## Why this task exists

Two refusals raised by `src/splitwise_lite/split.py` are shown to a flatmate word for
word by the expense entry screen, and neither is written for them.

```
POST /api/expenses
{"description":"","amount":"10.00","payer_id":"<sam>",
 "split":{"mode":"exact","amounts":{"<sam>":"8.00","<ali>":"1.50"}}}

400 {"error": {"code": "invalid_split",
               "message": "exact amounts sum to 950, not the total 1000"}}
```

```
POST /api/expenses
{"description":"","amount":"0","payer_id":"<sam>",
 "split":{"mode":"equal","member_ids":["<sam>","<ali>"]}}

400 {"error": {"code": "invalid_split",
               "message": "total_cents must be strictly positive, got 0"}}
```

The person typed `8.00`, `1.50` and `10.00` and is shown `950` and `1000`. The person
typed an amount into a field labelled **Amount** and is shown `total_cents`, which is a
parameter name in `split.py`.

Both reach the screen because that is the contract, and the contract is right. `app/api.js`
classifies a 400 `invalid_split` as `refused`, `speaks()` returns true for it, so `say` is
`error.message` exactly; `addRefused` in `app/app.js` writes that string into
`#add-error-server` untouched. The two alternatives the screen could have taken are both
worse and both already rejected in writing: a per-code substitution table on the client is a
second error contract that drifts from `web.py` the day either changes, and dividing a cent
figure by a hundred in JavaScript is the single thing this codebase is built to prevent. So
the fix belongs where the sentence is written.

It also matters more than it looks. `plans/spec.md` names adoption, not arithmetic, as the
product's real risk: "a half-filled ledger is worse than memory, because it looks
authoritative while being wrong", and expense entry has to take under ten seconds. A refusal
that asks somebody to convert 950 into 9.50 in their head, mid-entry, on a phone, is a
reason to give up on the entry.

`CLAUDE.md` already states the rule this breaks: "Amounts are parsed to cents at the input
edge and formatted back only for display." These two messages are display. They skipped the
edge.

## The decision, and why

**The formatting happens in the domain layer. `split_equally`, `split_by_weight` and
`split_exact` each take a required keyword-only `currency`, and every refusal they make
about an amount renders it through `money.format_amount`.**

### Why the domain and not `web.py`

The alternative is to leave `split.py` alone, give `InvalidSplit` structured cent
attributes, and have `web.py` catch `split.InvalidSplit` and compose the sentence. Rejected,
for three reasons.

* **It puts two sentences behind one situation.** `split.py` would keep its raw-cent
  sentence for every caller that is not HTTP, and `web.py` would grow a second one. The
  header of `app/api.js` already names this failure mode in so many words: "two sentences for
  one situation drift the moment either one is edited". Putting the second author in
  `web.py` instead of in `app/api.js` does not make it not a second author.
* **`web.py` does not write domain prose today, and the reason is written down.** Its
  docstring says every status except 500 carries `str(error)`, because "those strings were
  written deliberately in this repo for a person to read". A `DomainError` whose message has
  to be rewritten on the way out is that claim failing.
* **The sentence should be available to any caller.** Backlog 18's smoke test, a future
  script, and anything else that resolves a split gets the fixed sentence for free if it
  lives in the resolver, and gets the broken one if it lives in the HTTP layer.

Nothing about formatting needs a framework. `money.format_amount` is standard library, lives
in `money.py`, and `split.py` already imports from `money.py`. The domain layer keeps
importing with Flask absent, and the test that asserts it is untouched.

### Why the resolver has to be handed a currency

`format_amount` takes `Money`, and `Money` cannot be built without a `Currency`. With
`symbol=False`, which is the default and stays the default, the currency code never appears
in the output, so the argument is doing nothing visible. That is the point, and it is not an
argument for avoiding it: you cannot format money without saying which money it is, and that
requirement is exactly what stops the next person reaching for `cents / 100`.

Two shortcuts are available and both are rejected by name, so nobody has to rediscover them:

* **A second formatting helper in `money.py` that takes bare cents.** That is a second
  display edge. `money.py`'s own docstring and `CLAUDE.md` both say `format_amount` is the
  only one. Refused.
* **A module-private placeholder `Currency` inside `split.py`, so the signatures do not
  change.** That is a lie in the type system to avoid a mechanical edit to a test file, and
  it would sit in the money path forever. Refused.

`currency` is keyword-only and has **no default**, following `_ApiRoute.access`,
`create_app(secure_cookies=...)` and `scripts/serve.py --store`: in this repo a thing that
matters is stated by every caller rather than defaulted. `plans/spec.md` fixes one currency
per group and freezes it once the first expense lands, so `web.py` always has exactly one
right value to pass, and it already holds it — `_resolve_split` takes `currency` today for
`_require_exact_amount`.

All three functions take it, not just `split_exact`. `_require_total` is one function shared
by all three and it is where the zero-total refusal lives; the reproduction in the issue for
that refusal uses `mode: "equal"`, which is `split_equally`.

### Whether these messages are safe to show at all

Issue #14 found that `_read_debt`'s 400 interpolates a member id, and the transfer drill-down
screen consequently shows no server sentence at all. That question has to be settled here
before rewording anything, because if any `invalid_split` message could carry an id, then
`app/api.js` would have to stop speaking for the whole code and this task would be pointless.

It is settled, in this task's favour. Enumerated against what the add screen can actually
send — it sends `mode: "equal"` for both **Equally** and **Some people**, `mode: "exact"` for
**Uneven amounts**, and never `mode: "weight"`, which the screen does not expose — exactly
three `InvalidSplit` messages are reachable:

| reachable message | worst-case content |
|---|---|
| `total_cents must be strictly positive, got 0` | one integer, the total the person typed |
| `exact amounts sum to 950, not the total 1000` | two integers, both derived from amounts the person typed |
| `a split needs at least one member` | nothing |

No member id, no event id, no user text, no path, no internal identifier of any kind, before
this change or after it. After it, the worst case is `format_amount` output of those same
integers. **The `_read_debt` hazard does not exist here**, `app/api.js` needs no change, and
the add screen keeps printing `invalid_split` sentences verbatim.

Two `InvalidSplit` messages elsewhere in the module *can* carry member ids —
`member_ids names a member more than once: [...]` and
`weight for 'mem-x' must be zero or positive, got -1` — and neither is reachable from any
screen the shell ships: the add screen builds `member_ids` one row per roster member, so it
cannot produce a duplicate, and it offers no weight mode. Both are reachable from a
hand-written request, whose author supplied those ids in the request body and therefore
already knows them. They are recorded in "What was found elsewhere and deliberately left"
below and are not this task's to fix.

## Goal

The two refusals `src/splitwise_lite/split.py` makes about an amount reach the person in the
money they typed and in the words on their screen, rather than in cents and in a parameter
name. The sentences are written once, in the domain layer, through `money.format_amount`, so
the same sentence is what any caller gets; `web.py` composes nothing and its error contract
does not move; nothing under `app/` changes.

## Acceptance criteria

Each is a yes or no a QA agent can reach by reading a file or running a command. `REPO` is
the worktree root and every path is relative to it. Where a criterion quotes a string it is
quoted exactly, including case and the absence of a trailing full stop.

### The two sentences

1. A `split_exact` call whose amounts do not sum to the total raises `InvalidSplit` whose
   `str()` is exactly this, built from this template:

   ```python
   f"the shares add up to {_formatted(allocated, currency)}, "
   f"but the total is {_formatted(total, currency)}"
   ```

   For the issue's reproduction, `split_exact(1000, {ali: 150, sam: 800}, currency=AUD)`
   raises with the message exactly:

   ```
   the shares add up to 9.50, but the total is 10.00
   ```

   Both figures stay, because naming both is what lets somebody see by how much they are
   out. `shares` and `total` are the words already on screen: `#add-hint-exact` reads "These
   shares must add up to the total exactly." The message does not compute or state the
   difference; that would be a third figure and a claim the shares' own sum does not make.
2. A total that is not strictly positive raises `InvalidSplit` whose `str()` is exactly this,
   from all three resolver functions, built from this template:

   ```python
   f"the amount must be more than zero, but it is {_formatted(total_cents, currency)}"
   ```

   For the issue's reproduction, `split_equally(0, [ali, sam], currency=AUD)` raises with
   the message exactly:

   ```
   the amount must be more than zero, but it is 0.00
   ```

   `amount` is the word on the screen: the field is labelled **Amount** in
   `app/index.html`. The string `total_cents` does not appear.
3. A total above `MAX_CENTS` raises `InvalidSplit` whose `str()` is exactly this:

   ```python
   f"the amount is too large to record: {_formatted(total_cents, currency)}"
   ```

   This third message is in scope even though `web.py` cannot reach it — `parse_amount`
   refuses anything above `MAX_CENTS` first, with `invalid_amount` — because it is the other
   half of `_require_total`, it has the same two defects, and leaving one branch of one
   function spelling cents while the branch above it spells money is a contradiction the
   next reader has to resolve. The currency is already in hand; it costs one line.
4. None of the three sentences ends with a full stop and none begins with a capital letter,
   matching every other message in `money.py`, `split.py` and `web.py`. `app/app.js` prints
   them with "no rewording, no truncation, no added punctuation", so the punctuation is the
   server's to get right.
5. `grep -n "total_cents" src/splitwise_lite/split.py` shows the name only as a parameter, in
   docstrings, and inside the two `TypeError` messages in `_require_total`. It appears in no
   `InvalidSplit` message. The `TypeError` messages keep it deliberately: a wrong Python type
   is a programming error, becomes a generic 500 with a logged traceback, and is read by a
   programmer.

### The resolver's signature

6. `split_equally`, `split_by_weight` and `split_exact` each take a third parameter,
   `currency: Currency`, that is **keyword-only and has no default value**. Calling any of
   the three positionally-as-before raises `TypeError`:
   `split_equally(1000, ["a", "b"])` raises `TypeError`.
7. Each of the three validates `currency` **before** anything else, and raises `TypeError`
   (not `InvalidSplit`) when it is not a `Currency`, in the module's existing style: a wrong
   Python type is a programming error, not rejected user input. A bad currency and a zero
   total together produce the `TypeError`, not the `InvalidSplit`.
8. `split.py` gains one module-private helper, whose docstring names it as going through
   `money.py`'s one display edge:

   ```python
   def _formatted(cents: int, currency: Currency) -> str:
   ```

   Every refusal in the module that names an amount goes through it. No other function in
   `split.py` interpolates a bare cent integer into an `InvalidSplit` message. The one
   remaining `InvalidSplit` in the module that interpolates a bare integer is
   `f"{field} for {member_id!r} must be zero or positive, got {value}"` in
   `_ordered_from_mapping`, whose integer is a weight rather than money; see criterion 27.
9. `_require_total` takes the currency and passes it to `_formatted`. `_allocate`,
   `_require_member_id`, `_ordered_from_iterable` and `_ordered_from_mapping` are unchanged
   in signature and in behaviour.
10. `split.py`'s imports from `.money` grow to `Currency`, `MAX_CENTS`, `Money`,
    `DomainError` and `format_amount`, and nothing else changes about its imports.
    `test_split_imports_only_money_and_events_from_the_package` passes unedited, and so do
    `test_the_split_module_never_names_float_or_round`,
    `test_the_split_module_never_uses_true_division` and
    `test_the_split_is_a_pure_function_of_its_inputs`.
11. `split.__all__` is byte-identical. `_formatted` is underscore-prefixed, so the package
    root re-exports nothing new and `test_the_resolver_is_re_exported_from_the_package_root`
    passes unedited. `src/splitwise_lite/__init__.py` is not edited.
12. `split.py`'s module docstring gains one short paragraph in the existing bold-lead style,
    opening `**A refusal names the money, not the cents.**` It states that every refusal this
    module makes about an amount is rendered by `money.format_amount`, that this is why the
    resolver is handed a currency it does not otherwise need, and that the currency has no
    default because a defaulted currency in the money path is a bug waiting for a second
    currency. The `split_exact` and `_require_total` docstrings are updated to describe the
    refusals as they now read.

### The one call site outside the tests

13. `src/splitwise_lite/web.py` changes in exactly one function, `_resolve_split`, and in
    exactly three lines: each of `split.split_equally`, `split.split_by_weight` and
    `split.split_exact` gains `currency=currency`. The parameter is already there.
14. Nothing else in `web.py` moves. `ERROR_STATUS`, `ERROR_CODE`, `_handle_error`,
    `_API_ROUTES`, `_Access`, `_audit_routes`, `__all__` and the module docstring are
    byte-identical. `split.InvalidSplit` is still 400 `invalid_split`, and `web.py` catches,
    wraps, rewrites or prefixes nothing.
    `test_the_module_imports_flask_and_the_standard_library_only` and
    `test_the_two_tables_are_keyed_the_same_way_and_hold_exactly_these_rows` pass unedited.

### The refusal reaching a person, end to end

15. **On the wire.** `tests/test_web_api.py::test_exact_amounts_that_do_not_add_up_report_both_figures`
    keeps its name, its request and its `assert expense_count(seeded) == 0`, and asserts:

    * `response.status_code == 400` and `body["error"]["code"] == "invalid_split"`,
      unchanged;
    * `body["error"]["message"]` equals
      `f"the shares add up to {fmt(950)}, but the total is {fmt(1000)}"`, where `fmt` is
      `lambda c: money.format_amount(money.Money(c, group_currency))` evaluated in the test
      against the seeded group's own currency — **not a typed literal**;
    * `"950" not in message` and `"1000" not in message`. The two raw cent spellings cannot
      occur inside `9.50` and `10.00`, which is why these figures are the ones to test with.

    This replaces an assertion that pinned the sentence by hand. It asserts strictly more:
    the same equality, plus the absence of the defect.
16. **On the wire, the zero total.** A new test in `tests/test_web_api.py` posts a `"0.00"`
    amount with `mode: "equal"` and asserts: status 400, code `invalid_split`,
    `money.format_amount(money.Money(0, group_currency))` is in the message,
    `"total_cents" not in message`, and `"cents" not in message`.
17. **On the wire, the existing table row.** In
    `test_an_unusable_amount_carries_the_domain_layers_own_message`, the row
    `("0.00", "invalid_split", "strictly positive")` becomes
    `("0.00", "invalid_split", "more than zero")`. The other three rows, the test body and
    the test's name are unchanged. It goes on doing its one job, which is proving the domain
    layer's own message reached the wire rather than being swallowed by a 500.
18. **In front of a person.** `tests/shell_harness.mjs`'s `ADD_SUM_REFUSED` constant is
    updated to `'the shares add up to 9.50, but the total is 10.00'` and its comment is
    rewritten: the sentence is no longer a raw-cent figure that the screen shows anyway, it
    is the resolver's sentence in the money the person typed. All three scenarios that use it
    — `shares_that_do_not_add_up_show_the_resolvers_own_message_and_keep_the_draft`,
    `a_refused_save_followed_by_a_good_one_leaves_no_stale_message` and
    `a_save_refused_while_the_roster_loads_stops_saying_so_once_it_arrives` — keep their
    names, their bodies and their assertions, and go on asserting that
    `#add-error-server`'s `textContent` equals that constant character for character. That
    is the new sentence rendered by the shipped `app/app.js` and `app/api.js` into the
    shipped `app/index.html`, under Node, with nothing in between reformatting it.
19. **The two halves are pinned to each other.** A new test in `tests/test_web_api.py` reads
    `tests/shell_harness.mjs`, extracts the `ADD_SUM_REFUSED` literal with a regex, and
    asserts it equals `body["error"]["message"]` from a live `POST /api/expenses` made in the
    same test with the same figures the harness scenario uses (`10.00` total, `8.00` and
    `1.50` shares). Standard library only. This is the criterion that makes the whole chain
    hold: the fixture the JavaScript half shows to a person cannot drift from the sentence
    the Python half actually sends, because one is checked against the other on every run.
20. QA additionally performs this by hand and records it in the QA note:
    `uv run python scripts/serve.py --store <a scratch ledger>`, open `http://localhost:8000`,
    sign in, go to **Add**, type `10.00`, choose **Uneven amounts**, type `8.00` and `1.50`
    against two people, press Save. The sentence under the form reads exactly
    `the shares add up to 9.50, but the total is 10.00`. Then clear the shares, type `0` in
    Amount, choose **Equally**, press Save; the sentence reads exactly
    `the amount must be more than zero, but it is 0.00`. Screenshot or transcribe both. If
    the browser shows the old sentences, the service worker is serving a cached shell — but
    note that no file under `app/` changed in this task, so this should not happen; see
    criterion 25.

### The resolver's own tests

21. `tests/test_split.py::test_split_exact_rejects_amounts_that_fall_short` keeps its name
    and asserts, in place of `"1000" in str(...)` and `"750" in str(...)`:
    `money.format_amount(money.Money(750, AUD))` is in the message,
    `money.format_amount(money.Money(1000, AUD))` is in the message, `"750"` is not, and
    `"1000"` is not. `AUD` is a `Currency` the test file defines once.
22. `test_split_exact_rejects_amounts_that_overshoot` keeps its name and changes the same
    way, for 1200 against 1000: `format_amount` of both is present, `"1200"` is absent.
23. New tests in `tests/test_split.py`, each parameterised over all three resolver functions
    where it applies:
    * calling any of the three without `currency` raises `TypeError` (criterion 6);
    * calling any of the three with a `currency` that is not a `Currency` — `"AUD"`, `None`,
      `1` — raises `TypeError`, and does so even when the total is also invalid
      (criterion 7);
    * a zero total from any of the three produces a message containing
      `format_amount(Money(0, AUD))` and not containing `"total_cents"`;
    * a negative total, which only a direct domain caller can produce because `parse_amount`
      rejects signs, produces `the amount must be more than zero, but it is -5.00`, so
      `format_amount`'s leading-minus rendering is what a negative refusal says;
    * `MAX_CENTS + 1` produces the criterion 3 message, with the figure carrying
      `format_amount`'s comma groups;
    * a large exact mismatch, `123450` against `123400`, produces a message containing
      `1,234.50` and `1,234.00`, so the comma groups are covered on the mismatch path too.
24. Every other call in `tests/test_split.py` gains `currency=AUD`. This is 52 call sites and
    the edit is mechanical. **No assertion is weakened, no test is renamed, deleted,
    reordered, marked skip or xfail, and no parameter list loses a case.** The property tests
    over the small and large domains, the rotation tests, the ordering tests and the AST
    tests keep their bodies apart from the added keyword.

### The suite and the shell

25. **`SHELL_DIGEST` does not move, and nobody should go looking.** No file under `app/` is
    read, edited, added or removed by this task. `git diff --stat` shows no path beginning
    `app/`, `VERSION` and `SHELL_DIGEST` in `app/sw.js` are unchanged, and
    `test_the_recorded_digest_matches_the_files_it_covers` passes unedited. The digest covers
    files under `app/` only; `tests/shell_harness.mjs` is a test fixture and is not in it.
26. `uv run python -m pytest` reports 0 failed, 0 skipped and 0 xfailed. The passed count is
    2223 plus the number of cases this task adds; the four rewritten tests are rewrites and
    add nothing. QA records the exact number. `node` 20 or later is on `PATH`, so the
    JavaScript half runs and is not skipped.
27. The files changed by this task are exactly six: `src/splitwise_lite/split.py`,
    `src/splitwise_lite/web.py`, `tests/test_split.py`, `tests/test_web_api.py`,
    `tests/shell_harness.mjs`, and this spec if it needs correcting. No file is created or
    deleted anywhere in `src/`, `tests/`, `app/`, `scripts/` or `plans/`.
28. `pyproject.toml` and `uv.lock` are byte-identical to `master`. No new dependency, in
    either language.

### What was found elsewhere and deliberately left

29. The PR description records the audit of the sibling modules, so the next person does not
    repeat it. Nothing in this list is changed by this task, and each entry says why:

    * **`split.py`, `_ordered_from_mapping`:**
      `{field} for {member_id!r} must be zero or positive, got {value}`. Names a member id
      and a bare integer, and reaches a person at 400. For `exact` the integer is cents, but
      the path is unreachable from `web.py` because `parse_amount` rejects every signed
      string before `split_exact` sees it. For `weight` it is reachable, but the integer is a
      weight rather than money, so `format_amount` does not apply, and the add screen exposes
      no weight mode. The live defect is the member id, which is issue #14's question, not
      this one's. **Raise as its own issue.**
    * **`split.py`, `_ordered_from_iterable:`**
      `member_ids names a member more than once: ['mem-a', 'mem-b', 'mem-a']`. Dumps a list
      of internal ids and a payload field name at 400. Unreachable from the shell, which
      builds one row per roster member. Same family as the entry above. **Raise with it.**
    * **`money.py`, `parse_amount`:** every `InvalidAmount` quotes the offending input with
      `!r`. That is the person's own typed text, which is the right thing to echo, and it is
      never cents. **Correct as it stands, leave alone.**
    * **`money.py`, `_to_cents`:** `amount is not a whole number of cents: {scaled}` would
      print a cent figure, but the regex has already capped the fractional part at
      `MINOR_UNITS` digits, so scaling by 100 is always integral and the branch is
      unreachable. **Leave; note that it is defensive.**
    * **`events.py`:** `InvalidAllocation` and `InvalidEvent` carry cents and member ids in
      several messages, including `expense allocations sum to {allocated}, not total_cents
      {total}`. Neither class appears in `ERROR_STATUS` or `ERROR_CODE`, so both fall through
      to 500, and a 500 answers `_GENERIC_500_MESSAGE` with the real exception in the log.
      **None of these reaches a person. Leave alone**, and do not add them to the error maps
      as part of this task.
    * **`balances.py`:** `InvalidLedger` is likewise unmapped and is a 500. Its
      `CurrencyMismatch`, which *is* mapped to 400, names an event id but no cents, and is
      only reachable if a group's currency changed under a stored expense, which
      `plans/spec.md` forbids. **Leave alone.**
    * **`simplify.py`:** `InvalidBalances` carries cents in three messages and is unmapped,
      so it is a 500. **Leave alone.**
    * **`store.py`:** `AmountTooLarge` is mapped to 400 and reads
      `total_cents is 9223372036854775808, above MAX_CENTS (...)`, which is both defects at
      once. It is unreachable from `POST /api/expenses` because `parse_amount` refuses above
      `MAX_CENTS` first, with `invalid_amount`. It is one to watch when backlog 14 and 15 add
      settlement writes. **Leave alone; name it in the PR so the settlement tasks see it.**

## Out of scope

* **Anything under `app/`.** No file in `app/` is read, edited, added or removed. `VERSION`
  is not bumped and `SHELL_DIGEST` is not recomputed, because the shell bytes do not change.
  In particular `app/api.js`'s six kinds, three handlers and two fields are untouched:
  `classify()`, `speaks()` and `announce()` all stay as they are, `invalid_split` stays in
  the 400 row, and `say` remains either exactly `error.message` or exactly `''`.
* **Any change to the error contract.** No new status, no new code, no new exception class,
  no new row in `ERROR_STATUS` or `ERROR_CODE`, no change to the one JSON body shape. A
  reworded message is not a contract change: `web.py` says so itself — "a client branches on
  the code, never on the message: the messages are written for a person to read and may be
  reworded".
* **Composing, prefixing, truncating or substituting a message in `web.py` or in
  `app/app.js`.** Both are the rejected alternative above. `_handle_error` keeps carrying
  `str(error)` for every non-500.
* **A running total, a remaining figure or a "you are out by" line, on the screen or in the
  message.** The screen doing it is money arithmetic in JavaScript, which
  `tests/test_web_shell.py` bans across `app/app.js`. The message doing it is a third figure
  and a third thing to keep true.
* **`money.py`.** No new formatting helper, no cents-only variant of `format_amount`, no
  change to `MINOR_UNITS`, `MAX_CENTS`, `parse_amount` or `format_amount`. `format_amount`
  stays the only display edge and its `symbol` argument stays keyword-only and off.
* **The refusals listed in criterion 29.** They are recorded, not fixed. Widening this task
  to the member-id messages would drag in issue #14's decision about whether a screen may
  show a sentence containing an internal id, which is a different question with a different
  blast radius.
* **`events.py`, `balances.py`, `simplify.py` and `store.py`.** Not edited. Their cent-bearing
  messages are 500s or unreachable, per criterion 29.
* **Adding a currency to anything other than the three resolver functions.** No currency
  parameter on `_allocate`, on `Allocation`, on any events type, or on
  `_ordered_from_iterable`. `Allocation` deliberately carries no currency and that stays true.
* **Multi-currency anything.** One currency per group, fixed at creation, per
  `plans/spec.md`.
* **Tidying `split.py`.** No renaming of existing helpers, no reordering of functions, no
  rewrite of the remainder rule or its docstring, no reformatting of untouched lines.
* **`plans/spec.md`, `plans/backlog.md`, `README.md` and `CLAUDE.md`.** Nothing about what
  the product is, or how it is run, installed or tested, changes. `CLAUDE.md`'s "Money"
  section already states the rule this task makes true; it does not need editing to say so
  again.
* **CI, workflows, hooks and static analysis.** None is added or edited.

## Constraints

* **Files edited: exactly six**, as listed in criterion 27. Nothing else, in either
  direction.
* **Money is integer cents everywhere.** No float, no `round`, no true division, anywhere in
  this diff. `Decimal` stays an implementation detail inside `money.py` and does not appear
  in `split.py`. The three AST tests in `tests/test_split.py` enforce the first three and
  must pass unedited.
* **`format_amount` at the display edge only.** Every amount in a refusal goes through
  `_formatted`, which is four lines and calls `format_amount(Money(cents, currency))`. It
  mirrors `web.py::_amount` deliberately: the two cannot share code, because `split.py` may
  not import `web.py`, and both go through the same one edge, which is what matters.
* **The domain layer stays framework free.** `split.py` imports from `.money` and `.events`
  and nothing else in the package. `test_importing_the_package_does_not_import_the_framework`
  and `test_no_module_in_the_package_imports_the_web_layer` pass untouched.
* **No new dependency of any kind.** Nothing new is imported in either language; the
  JavaScript harness still imports only `node:vm`, `node:fs`, `node:path` and `node:url`. Per
  `CLAUDE.md`, a dependency is declared in `pyproject.toml` and then installed with
  `uv sync`, never `pip install` or `uv pip install`. If something here genuinely cannot be
  built without a package, stop and get the user's approval first.
* **`currency` is keyword-only with no default**, on all three functions, and validated
  before anything else in each. A default would be the exact shape of mistake this repo has
  refused three times: `_ApiRoute.access`, `create_app(secure_cookies=...)` and
  `serve.py --store`.
* **Messages carry no identifier.** Neither new sentence may name a member id, an event id,
  a group id, a payload key or a Python parameter name. Criterion 5 is the check.
* **Punctuation matches the family:** lower-case opening, no trailing full stop. `app/app.js`
  adds none.
* **Existing tests are not loosened.** The only pre-existing tests that change are the four
  named in criteria 15, 17, 21 and 22, and all four assert strictly more than they did: each
  keeps its equality or fragment and gains an assertion that the raw cent spelling or the
  parameter name is absent. The 52 mechanical call-site edits in criterion 24 change no
  assertion. Nothing anywhere is removed, renamed, reordered, skipped or xfailed.
* Tests run with `uv run python -m pytest`. Plain `uv run pytest` fails on this machine with
  an access-denied spawn error. Assertions are exact, per `.claude/rules/testing.md`.
* No test binds a socket. The hand check in criterion 20 is run by QA and is not automated.
* **Python 3.12 target**, a docstring on the new helper, and a one-line comment where each
  non-obvious choice is implemented, so the next person does not undo it by tidying: why the
  resolver takes a currency it never prints, why the currency has no default, and why the
  formatting is here rather than in `web.py`.

## On pinning message text, and issue #42

Issue #42 exists because a test asserted the word "placeholder" appeared in the documents,
and went on requiring it long after the screens shipped: the premise lived outside the test,
expired silently, and the assertion ended up enforcing the thing it was written to prevent.
Every message assertion this task specifies is built so that cannot happen.

* **The expected value is computed, not typed.** Criteria 15, 16, 21 and 22 build the
  expected figures by calling `money.format_amount(money.Money(cents, currency))` in the
  test. The assertion is therefore "this message spells its figures the way the one display
  edge spells them", which is the property, not the wording. If `format_amount` ever changes
  how it renders, these tests move with it instead of fossilising an old rendering.
* **The cross-language fixture is pinned to its producer.** Criterion 19 compares the
  `ADD_SUM_REFUSED` literal in `tests/shell_harness.mjs` against a live 400 body in the same
  run. That literal cannot outlive the sentence it stands for: reword the message and this
  test goes red pointing at the fixture, which is exactly the failure #42's test never
  produced.
* **The negative assertions are properties whose premise is the goal.** `"950" not in
  message`, `"total_cents" not in message`, `"cents" not in message`. These can only start
  failing if somebody puts cents or a parameter name back into a message shown to a person,
  which is the thing this task exists to stop. A red test then is correct, not stale.
* **The one true phrase pin, and why it is safe.** Criterion 17 keeps a fragment,
  `"more than zero"`, in an existing parameterised table. Its job is not to police wording:
  it is to prove the row reached the wire carrying the *domain layer's* message rather than a
  500's generic string, and its three sibling rows do the same for `parse_amount`. It is a
  fragment rather than the sentence, so a reword that keeps the meaning stays green, and the
  property test in criterion 16 sits beside it as the assertion that actually enforces the
  fix.

The full sentences are quoted verbatim in criteria 1, 2 and 3 as the *specification* of what
to write, and in criterion 18 as a fixture that criterion 19 keeps honest. No test asserts a
literal sentence that nothing else re-derives.

## Size

Small. In `split.py`: one four-line helper, three signature lines, three message lines, one
docstring paragraph and two docstring updates — roughly twenty lines added and three
replaced. In `web.py`: three keywords. The bulk of the diff is the 52 mechanical call sites
in `tests/test_split.py`, which are one keyword each, plus about six new test functions and
four rewrites across `tests/test_split.py` and `tests/test_web_api.py`, plus one constant and
one comment in `tests/shell_harness.mjs`.

If this task grows a new module, a new exception class, a new error code, a second formatting
function, a change to `app/`, or a `try`/`except` around `split` in `web.py`, it has gone
wrong.

## Notes for the queued tasks

Any branch that calls `split_equally`, `split_by_weight` or `split_exact` will conflict, and
the resolution is mechanical in every case: add `currency=<the group's currency>` to the
call. In `web.py` the value is already in scope as `_resolve_split`'s `currency` parameter;
in a test it is whatever `Currency` that test already builds its `Money` with. There is no
new import for a caller that already has a currency, and no caller in this repo lacks one.
