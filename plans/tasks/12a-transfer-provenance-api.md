# Task 12a: Transfer provenance on the wire, and the debts behind it

**Depends on:** 4 (complete, on `master`), 5 (complete, on `master`), 9a (complete, on
`master`), 12 (complete, on `master`), and **issue #32, which is rewriting `app/api.js`
right now**. See the sequencing note in Constraints before starting.

**Consumed by:** 13 (transfer drill-down, issue #14). That task is written, waiting, and
explicitly refuses to start until this one lands.

Added after the original numbering, when sharpening task 13 exposed that the data the
drill-down is built on never reaches the browser. The backlog entry for task 13 stays as
written; this file is the API half of it, split out so the money arithmetic and the
request layer are reviewed on their own merits rather than inside a screen task.

## Why this task exists

Task 5 built two-ended provenance and called it the deliverable, not a decoration: every
`Transfer` carries `payer_debts` and `receiver_credits`, each summing exactly to the
transfer amount, each row keyed to a real `Balances.pairwise` entry and carrying that
debt's whole total. The backlog says the drill-down is impossible without it.

`_read_balances` in `src/splitwise_lite/web.py` throws all of it away, building each
transfer as `from_member_id`, `to_member_id` and `amount`. Task 12 made that choice on
purpose and said so in the docstring that is still there:

> Transfer provenance is deliberately not here: task 13 owns the drill-down and adds
> `payer_debts` and `receiver_credits` there, which is a widening of one response object
> rather than a new endpoint.

Half of that sentence is now wrong, and this task corrects it: the widening is real, and
it is **not** the whole of the job, because no endpoint answers "which expenses are behind
the debt between these two people". The front end cannot derive that answer, for three
separate reasons, each fatal on its own:

* Deciding whether an expense contributes to the debt from `d` to `c` means asking whether
  an allocation is non-zero. Off the wire that is a formatted string, and `app/app.js` may
  not compare or parse an amount, or even contain the literal `0.00`.
* A pairwise debt is a **signed** fold. An expense where `d` paid and `c` shared *reduces*
  the debt from `d` to `c`. A list showing only the expenses pushing one way would not
  account for the figure it claims to explain.
* `derive_balances` moves a pairwise debt on every **confirmed settlement** between the
  two members, and nothing exposes settlements at all.

So the real work here is a pure function, in integer cents, with the same property-test
treatment tasks 3, 4 and 5 got. Task 5 refused to guess its shape:

> Do not put expense ids, descriptions or event references into `AbsorbedDebt`: that would
> guess at task 13's query shape.

This task defines that shape.

## Where the new function lives, and why it is not a new module

**It goes in `src/splitwise_lite/balances.py`, beside `derive_balances`.** The rejected
alternative was a new `debts.py` importing only public names.

The invariant this function has to hold is stated in terms of `Balances.pairwise`, and
every rule it must apply is already implemented once in `balances.py`: earliest decision
wins, only confirmed settlements move money, a foreign group is refused rather than
dropped, a repeated event id is refused, a decision naming no settlement in the input is
ignored. That module's own docstring says of the decision rule: *"This is the single
implementation of the rule; nothing else in the codebase re-derives it."* A sibling module
could reach the states through the public `settlement_states`, but it would still have to
restate the group check, the currency check and the duplicate-id check, and those three
drifting apart is exactly the money bug this arrangement exists to prevent.

The dependency direction is unchanged: `balances.py` still imports from `money.py` and
`events.py` only, and neither learns it exists.

## What is behind a pairwise debt

`derive_balances` moves the debt from `d` to `c` in exactly two ways, and this function
enumerates the same two. Nothing else in the fold touches a pairwise entry.

**An expense** contributes one entry to the pair `(d, c)` when its payer is one of the two
and the other holds a non-zero allocation:

| payer | non-zero allocation | effect on the debt `d -> c` | entry amount |
|---|---|---|---|
| `c` | `d` | `ADDS` | `d`'s allocation |
| `d` | `c` | `REDUCES` | `c`'s allocation |

An expense paid by anybody else contributes nothing, even when both `d` and `c` share it:
two people who split a third person's expense owe that third person, not each other. The
payer's own allocation never counts, because a member does not owe themselves, and a
zero-cent allocation never counts, because the fold excludes it. One expense has one
payer, so an expense yields **at most one** entry per pair.

**A confirmed settlement** contributes one entry:

| settlement | effect on the debt `d -> c` | entry amount |
|---|---|---|
| `c` paid `d` | `ADDS` | the settlement amount |
| `d` paid `c` | `REDUCES` | the settlement amount |

A `PENDING` or `REJECTED` settlement contributes nothing and is not listed at all. It moved
no money, and putting a claimed payment in a list that explains a live figure would be the
"two people see two versions of the truth" failure the spec's third section exists to stop.
Decision events are never entries in their own right.

**The invariant**, and the reason this is a money function rather than a query helper:

    sum(+e.amount if e.effect is ADDS else -e.amount for e in entries)
        == Balances.owed_between(debtor, creditor).cents

exactly, in integer cents, for **every** ordered pair of member ids, over any ledger the
fold accepts. It holds for pairs that pull both ways, for pairs a settlement cancelled to
zero, and for pairs with nothing between them at all.

## The sign lives in the domain and the wire carries a magnitude

`format_amount` renders a negative amount with a leading minus. `web.py` never sends one:
`_read_balances` already sends `abs(cents)` plus a server-computed `direction`, so the
screen never parses, compares or renders a sign.

This task keeps both halves of that. `DebtSources.amount` is **signed**, because
`owed_between` is signed and a domain value that hides which way a debt runs is a value
that cannot be checked against the fold. The endpoint sends the magnitude plus
`direction`, exactly as a net row does.

That matters because the endpoint takes two ids from a path and can legitimately be asked
about a pair whose debt runs the other way: a ledger changes between the balances read and
the drill-down request, and `simplify.AbsorbedDebt` only guarantees a positive pair at the
moment the plan was built.

## Where this differs from the contract task 13 was written against

`plans/tasks/13-transfer-drill-down.md` writes down the payload shapes and says a reviewer
must check the two files agree. They agree, with **one addition**:

* `GET /api/debts/...` carries a sixth top-level key, `direction`, spelled and valued
  exactly as `direction` on a net row: `owes` when the debtor owes the creditor, `owed`
  when it runs the other way, `settled` when the pair is square. Task 13's contract lists
  five keys and does not say what `amount` means when the debt runs backwards, which is a
  case it did not consider. Without `direction` the only two options are a lie (a magnitude
  presented as a debt in the direction asked about) or a minus sign on the wire (which task
  13 forbids by name).

Nothing task 13 renders changes: no criterion in that file reads the endpoint's top-level
`amount`, and none reads `direction`. **This branch does not edit that file** — it lives on
another branch. Whoever picks up issue #14 adds `direction` to its contract section under
that file's own dated-marker rule, before implementation starts.

Everything else matches byte for byte: the absorbed-debt row's five keys, the entry's six
keys, `covers_whole_debt` as a server-computed boolean, `effect` as `adds` or `reduces`,
`kind` as `expense` or `settlement`, `created_at` spelled the way `_expense_view` spells
it, `entries` newest first, and `api.debt(debtorId, creditorId)` in `app/api.js`.

## Goal

Every suggested transfer reaches the browser with both ends of its provenance, and one new
endpoint answers what a single pairwise debt is made of, backed by a pure function whose
entries provably sum to the debt the fold derives. When this is done, issue #14 can be
implemented against a real server with no change to anything under `src/splitwise_lite/`
and no second network call in `app/app.js`.

## Acceptance criteria

**The pure function: shape and contract**

- `src/splitwise_lite/balances.py` gains one public function,
  `debt_sources(events, *, debtor, creditor, group_id, currency) -> DebtSources`, with
  `events` positional and the other four keyword-only, matching `derive_balances`.
- It gains four public types, all in `__all__` and all documented:
  `DebtSources` and `DebtEntry`, frozen slotted dataclasses, and `DebtEntryKind` and
  `DebtEffect`, enums whose members are `EXPENSE`/`SETTLEMENT` and `ADDS`/`REDUCES` with
  values equal to their names, following `SettlementState`'s precedent.
- `DebtSources` holds exactly `group_id`, `currency`, `debtor`, `creditor`, `amount` and
  `entries`, in that order. `DebtEntry` holds exactly `kind`, `effect`, `event_id`,
  `description`, `amount` and `created_at`, in that order. Neither grows a display name, a
  member id other than the pair's, an allocation list or an expense total.
- `DebtSources.amount` is **signed** and equals
  `derive_balances(events, group_id=..., currency=...).owed_between(debtor, creditor)`
  exactly, for the same events. A test asserts that through the real fold rather than by
  re-deriving it.
- Every `Money` in the result carries `currency`. Every `DebtEntry.amount` is strictly
  positive: the sign is carried by `effect` and by nothing else.
- `entries` is sorted ascending by `events.ordering_key`, so `created_at` ascending with
  ties broken by ascending event id. The ledger's one total order, never list position and
  never `created_at` alone.
- At most one entry per event: one expense yields at most one entry for a pair and one
  settlement yields exactly one, so `event_id` is unique across `entries`.
- `DebtEntry.description` is the expense's own description, verbatim, empty string
  included. For a settlement it is `""`, because `SettlementEvent` has none. The function
  substitutes no placeholder text.
- The function is pure: no clock, no I/O, no randomness, no module-level mutable state, no
  caching. `events` may be any iterable, a generator included, and is consumed exactly
  once. The caller's list is neither mutated nor reordered.
- Called twice on the same input, and called on a shuffled copy of it, it returns `==`
  results.
- `debt_sources(events, debtor=c, creditor=d, ...)` returns the same entries in the same
  order with every `effect` flipped, the same `event_id`s and the same amounts, and an
  `amount` that is the exact negation.

**The pure function: refusals**

- A `debtor` or `creditor` that is not a `str` raises `TypeError` naming the type. So does
  a non-`str` `group_id`, a non-`Currency` `currency`, and an `events` that is not an
  iterable of ledger events. Those are programming errors, not rejected input.
- An empty `debtor` or `creditor` raises `InvalidLedger`, and so does `debtor == creditor`:
  a member cannot owe themselves, and answering with an empty list would present a
  meaningless question as a settled pair.
- Every refusal `derive_balances` makes on the same events is made here on the same terms:
  a foreign group or an empty `group_id` raises `InvalidLedger`, a repeated event id raises
  `InvalidLedger`, and an expense or settlement in another currency raises
  `CurrencyMismatch`. A caller must never be able to list entries for a ledger whose
  balances `derive_balances` would refuse to compute.
- **No new exception class is added anywhere in the package.** `InvalidLedger` and
  `CurrencyMismatch` cover every rejection, so `ERROR_STATUS`, `ERROR_CODE` and
  `DELIBERATELY_UNMAPPED` in `tests/test_web_api.py` are all unchanged.
- Validation is eager: a rejected call produces no partial answer.
- Neither `debtor` nor `creditor` is checked against a roster. This module does not know
  what a group's members are, exactly as tasks 2, 4 and 5 decided; a member the ledger has
  never seen gets an empty answer, which is what `net_for` already promises.

**The pure function: what is and is not an entry**

- An expense paid by `c` where `d` holds a non-zero allocation yields one `ADDS` entry for
  `d`'s allocation cents, never the expense total.
- An expense paid by `d` where `c` holds a non-zero allocation yields one `REDUCES` entry
  for `c`'s allocation cents.
- An expense paid by a third member yields no entry, even when both `d` and `c` hold
  allocations on it.
- A zero-cent allocation yields no entry, and the payer's own allocation yields no entry.
- A `CONFIRMED` settlement from `c` to `d` yields one `ADDS` entry; one from `d` to `c`
  yields one `REDUCES` entry; both for the settlement's whole amount.
- A `PENDING` or a `REJECTED` settlement yields no entry. So does a settlement between
  other members, and so does a decision event on its own.
- The earliest decision by `ordering_key` decides the state, through the same code path
  `derive_balances` uses, so a rendered entry list and a balance can never disagree about
  whether a settlement counted. A settlement carrying two conflicting decisions is entered
  or omitted according to the earlier one.
- A decision naming a settlement absent from the input is ignored, not rejected.

**The pure function: property tests**

- Over randomly generated ledgers from a seeded `random.Random`, folded through
  `derive_balances` so the two stay in step, for **every ordered pair of member ids in the
  ledger plus one member id the ledger has never seen**: the signed sum of the entries
  equals `owed_between(debtor, creditor).cents` exactly, as an integer comparison and never
  an approximate one.
- The same generated cases assert, on every pair: entry amounts strictly positive,
  `ordering_key` ascending, `event_id` unique within `entries`, the currency of every
  `Money`, and the reversal property above.
- Generated ledgers must include the shapes that are easy to miss: a pair with expenses
  running both ways, a debt a confirmed settlement cancels exactly to zero, a settlement
  larger than the debt it cleared so the pair flips, pending and rejected settlements in
  the same log, a decision whose settlement is absent, an expense paid by a third member
  that both parties share, a zero-cent allocation, and a member with no events at all.
- Coverage is exhaustive where the domain is small enough to enumerate, following task 5's
  precedent: every ledger formed by taking zero to three events from a fixed pool of
  hand-written expenses and settlements over four members, asserting the sum invariant for
  every ordered pair of those four.
- Determinism is tested, not assumed: folding a shuffled event list gives an `==` result.

**`GET /api/balances`: the widening**

- Each entry of `transfers` gains exactly two keys, `payer_debts` and
  `receiver_credits`, each a JSON array. `from_member_id`, `to_member_id` and `amount` keep
  their spelling and their values, `net` and `currency` are untouched, and no key is
  removed or reordered.
- Each element of both arrays holds exactly five keys: `debtor_id`, `creditor_id`,
  `amount`, `debt_total` and `covers_whole_debt`. No `pair`, no nested object, no member
  display name.
- `debtor_id` and `creditor_id` are `AbsorbedDebt.debtor` and `AbsorbedDebt.creditor`
  unchanged, so the two together are a `Balances.pairwise` key and are exactly what
  `api.debt` is called with.
- `amount` and `debt_total` are `format_amount` strings, produced through the existing
  `_amount` helper. Both are strictly positive, so neither ever carries a minus sign.
- `covers_whole_debt` is a JSON boolean the server computes as
  `row.amount.cents == row.debt_total.cents`. It is computed from cents and never from the
  two formatted strings, for the same reason `direction` exists on a net row.
- Both arrays preserve `simplify.py`'s order, ascending by `(debtor, creditor)`. Nothing is
  re-sorted, merged, filtered or deduplicated, and a pair appearing in both arrays of one
  transfer appears in both on the wire.
- A settled group still answers `"transfers": []`, and the two keys appear nowhere in that
  payload.
- Every transfer this server sends carries both keys as non-empty arrays, because task 5
  guarantees both lists are non-empty for a strictly positive transfer. Task 13's inert
  fallback is defence against an older server, not a state this one produces.
- `_read_balances`'s docstring is corrected: the sentence deferring provenance to task 13
  is replaced by one saying what the payload now carries and that `covers_whole_debt` is
  computed from cents.

**`GET /api/debts/<debtor_id>/<creditor_id>`**

- The route is registered as endpoint `read_debt`, `GET` only, and **is added to
  `_API_ENDPOINTS`**. Without that the `before_request` hook skips it and the endpoint gets
  no session check at all.
- It is in neither `_ANONYMOUS_ENDPOINTS` nor `_MEMBER_OPTIONAL_ENDPOINTS`, so it inherits
  the default: 401 for a caller with no session or a dead one, 403 `member_not_linked` for
  a signed-in user with no member row in the group. The handler writes no authentication
  code of its own.
- A successful response is 200 and holds exactly six keys: `currency`, `debtor_id`,
  `creditor_id`, `amount`, `direction` and `entries`.
- `debtor_id` and `creditor_id` echo the path segments. `currency` is the group's code.
- `amount` is the non-negative magnitude of `DebtSources.amount`, as a `format_amount`
  string, and never carries a minus sign. `direction` is `owes` when the debtor owes the
  creditor, `owed` when the creditor owes the debtor, and `settled` when the pair is
  square, computed by the same `_direction` helper the net rows use, read from the debtor's
  side.
- Each element of `entries` holds exactly six keys: `kind`, `effect`, `id`, `description`,
  `created_at` and `amount`.
- `kind` is `expense` or `settlement`; `effect` is `adds` or `reduces`. Both are lowercase
  wire strings produced by an explicit map in `web.py` from the domain enums, so renaming a
  domain enum member cannot silently rename a JSON value the front end branches on. The map
  is exhaustive over both enums, and a test asserts it is.
- `id` is the event id, `description` is passed through verbatim including empty, `amount`
  is a `format_amount` string of a strictly positive figure, and `created_at` is
  `isoformat(timespec="microseconds")`, byte for byte the spelling `_expense_view` uses.
- `entries` arrives **newest first**: the domain function returns `ordering_key` ascending
  and the handler reverses it, exactly as `_list_expenses` reverses the store's order. Ties
  therefore break by descending event id, the same rule as the feed.
- Both ids are checked against the group roster before anything else. An id that is not a
  member of the group is `MalformedRequest`, 400 `malformed_request`, naming the offending
  id and nothing else. A 404 was considered and rejected: the path names members, not a
  stored record, and `web.py` already refuses an out-of-group member id this way in
  `_create_expense`.
- `debtor_id == creditor_id` is refused the same way, 400, with a message saying a member
  cannot owe themselves. Together with the roster check this keeps `InvalidLedger`
  unreachable from any request, so its entry in `DELIBERATELY_UNMAPPED` stays true and
  `test_no_domain_error_becomes_a_five_hundred_without_this_test_seeing_it` passes
  untouched.
- The whole group's pairs are readable by any linked member. The endpoint does **not**
  require the acting member to be one of the two: the drill-down exists to explain a
  payment between two other people, and membership of the group is the only authorisation
  this product has.
- Nothing is stored, cached or memoised. Every figure is derived on read from the event
  log, and two requests against a ledger that changed in between may legitimately differ.
- No query parameter, no body, no pagination and no second method on the path.

**The awkward cases, each pinned by a test**

- **A debt with nothing behind it.** Two roster members with no shared history answer 200
  with `"entries": []`, `"amount": "0.00"` and `"direction": "settled"`. An empty list is a
  real answer, never a 404 and never an error.
- **A pair with expenses in both directions.** Both `adds` and `reduces` entries appear in
  one `entries` array, and the signed sum matches the pair's derived figure.
- **A debt fully cancelled by a confirmed settlement.** `entries` is non-empty, `amount` is
  `"0.00"` and `direction` is `settled`. This is why the front end may not add the list up
  and call the total the debt.
- **A settlement larger than the debt it cleared.** The pair flips: `direction` reads
  `owed` while the ids are unchanged, and the magnitude is the overshoot.
- **A member who appears in a transfer but shares no expense with the other party.** The
  case issue #14 exists to explain. In a ledger where Bo owes Ali and Ali owes Cass, the
  plan carries a transfer `bo -> cass`, `GET /api/debts/<bo>/<cass>` answers with an empty
  `entries`, and the transfer's `payer_debts` and `receiver_credits` name `(bo, ali)` and
  `(ali, cass)` instead. The test asserts all three together, because that is the whole
  claim the drill-down makes.
- **A debt split across two transfers.** Task 5's chain fixture: `(bo, ali)` appears in the
  `payer_debts` of both transfers with `covers_whole_debt` false on both and the same
  `debt_total` on both.
- **A transfer covering a whole single debt.** `covers_whole_debt` is true and
  `amount` equals `debt_total` on that row.
- **A pure cycle.** `transfers` is empty, no provenance appears anywhere in the payload,
  and the endpoint still answers 200 for each of the three live pairs with the entries
  behind them.
- **A pending settlement between the two members.** It appears in no `entries` array and
  moves no figure.
- **An id that needs percent-encoding.** `api.debt` encodes both ids, and a member id
  carrying a space or a percent sign round-trips to the right member. A member id
  containing `/` is unreachable through this path and answers the routing 404 in the one
  JSON body shape; that is recorded as a known limitation, not worked around, because ids
  come from `new_id()` and an operator roster.
- **An empty path segment.** `/api/debts//x` and `/api/debts/x/` match no route and are the
  routing 404 in the one JSON body shape.

**`app/api.js`**

- It gains exactly one function, `debt(debtorId, creditorId)`, hung off
  `window.SplitwiseApi` beside `balances`, which calls `call('GET', ...)` on
  `'/debts/' + encodeURIComponent(debtorId) + '/' + encodeURIComponent(creditorId)`.
- Both ids are encoded. An id with a space, a `%` or a `#` produces a path the server
  routes to the right pair.
- Nothing else in the file changes: no new failure classification, no cache, no header, no
  storage, no second `BASE`. `test_the_api_client_holds_no_state_of_its_own`,
  `test_the_client_names_its_three_failure_paths` and
  `test_only_the_api_client_calls_the_back_end` all pass untouched.
- No file under `app/` other than `api.js` is touched, so `app/app.js` still contains
  neither `fetch` nor `/api`, `test_app_holds_exactly_the_promised_files` and
  `test_the_worker_precaches_exactly_the_shell` pass unchanged, and no screen calls
  `api.debt` yet.

**Automated tests: Python**

- New domain tests are appended to `tests/test_balances.py`, covering every criterion under
  the three "pure function" headings, including each contribution rule and each refusal by
  name, plus the property and exhaustive tests.
- `tests/test_balances.py`'s existing tests all pass untouched, and
  `test_the_fold_is_re_exported_from_the_package_root` gains the four new names alongside
  the four it already lists.
- `src/splitwise_lite/__init__.py` re-exports `debt_sources`, `DebtSources`, `DebtEntry`,
  `DebtEntryKind` and `DebtEffect`, and `__version__` keeps its current value.
- `tests/test_web_api.py` gains a row for `("GET", "/api/debts/<id>/<id>", None, 401, 401)`
  in `ENDPOINT_ROWS` and a `403` row in `UNLINKED_ROWS`, so
  `test_the_endpoint_table_names_every_route_the_app_serves`,
  `test_every_endpoint_refuses_an_unauthenticated_caller` and
  `test_a_signed_in_user_with_no_member_row_may_not_read_the_ledger` cover the new
  endpoint. The table test compares against `app.url_map`, so a route added without a row
  fails.
- `test_a_transfer_carries_no_provenance` is **deleted**. It asserts the opposite of this
  task. It is not renamed, not kept alongside and not xfailed. A test asserting the exact
  provenance payload for the same fixture replaces it, named for what is now true.
- `test_balances_report_the_exact_figures_and_the_exact_transfer_list` is updated to the
  widened transfer object, with the exact `payer_debts` and `receiver_credits` for that
  fixture written out in full rather than loosened to a subset check.
- `test_no_amount_is_ever_a_json_number_and_no_payload_names_cents` gains the new path to
  its list, and its `every_amount_key` helper also collects `debt_total`, so both money
  fields are held to the two-decimal string rule. Widening the helper is deliberate; no
  assertion in it is weakened.
- Tests that need a confirmed settlement append it through `open_store` directly, with a
  `SettlementEvent` and a `CONFIRMED` `SettlementDecisionEvent`, because no endpoint
  creates one until task 14. That is stated in a comment where it is done.
- Every assertion on cents is an exact integer comparison and every assertion on a payload
  is an exact equality, not a subset or a substring, per `.claude/rules/testing.md`.
- No test is skipped or xfailed, no test binds a socket, and `uv run python -m pytest`
  passes. Plain `uv run pytest` fails on this machine with an access-denied spawn error.

**Automated tests: the JavaScript harness**

- `tests/shell_harness.mjs` gains exactly one scenario,
  `the_api_client_builds_a_debt_path_from_two_ids`, appended to the end of the scenario
  list, and the identical name is appended to `SCENARIOS` in
  `tests/test_shell_behaviour.py` so `test_the_harness_reports_exactly_the_declared_scenarios`
  passes.
- That scenario boots to the app, calls `window.SplitwiseApi.debt(...)` through
  `page.global` with two ids that need encoding, registers an answer for the encoded path,
  drains through an existing affordance that makes no request, and declares its whole
  ordered request list through `expectRequests` including the exact encoded path.
- **No widening of the DOM stub is needed or made.** `document.createTextNode` and an
  element `type` property are still absent, and they stay issue #14's to add, with the one
  line comment that file requires, since nothing here renders anything. If a widening turns
  out to be unavoidable, it carries a comment naming the shipped code that reaches for it,
  and the guarded proxy still refuses anything undefined.
- No existing scenario is weakened, renamed, reordered or deleted, and both mutant tests
  still exit 1 and still name `a_refused_sign_in_tells_the_person_why`.
- Running the harness with no substitutions passes every scenario and exits 0.

**Verified by hand**

Record each as checked, against a store seeded by `scripts/setup_group.py` and served with
`uv run python scripts/serve.py --store ledger.sqlite3`.

- `curl` `GET /api/balances` on a seeded chain ledger: every transfer carries both arrays,
  every amount is a two-decimal string, and no minus sign appears anywhere in the body.
- `curl` `GET /api/debts/<d>/<c>` for a pair with expenses both ways and one confirmed
  settlement: the entries add up by hand to the figure the balances payload implies.
- The same path with the two ids swapped: the same entries with the effects flipped, and
  `direction` reading the other way.
- `GET /api/debts/<d>/<d>` and a path naming a member of no group: 400, one JSON body
  shape, the offending id named, and nothing in the log.
- With no session cookie: 401. Signed in but unlinked: 403 `member_not_linked`.

## Out of scope

- **Any UI.** No drill-down, no transfer row change, no button, no `aria-expanded`, no
  detail region, no new sentence in `app/index.html` and no CSS. Every criterion under
  "The transfer row becomes a control", "What one open payment shows", "A debt row" and
  "Expanding a debt to its expenses" in task 13 belongs to issue #14 and stays there.
- **Anything under `app/` except `api.js`.** `app/app.js`, `app/index.html`,
  `app/styles.css`, `app/manifest.json` and everything under `app/icons/` are untouched,
  and no file is added to or removed from `app/`.
- **`app/sw.js`, including `VERSION`.** The precache list is unchanged because the file
  list is unchanged. A cached shell will serve the old `api.js` until somebody bumps it;
  whoever integrates these branches bumps it once, and until then hand checks need
  DevTools, Application, Service Workers, "Update on reload". Bumping it here would collide
  with issue #32 for no benefit.
- **Changing `simplify.py`.** `AbsorbedDebt` gains no expense id, no description and no
  event reference. Task 5's refusal stands: the `(debtor, creditor)` key is the handoff, and
  this task is the query that takes it.
- **Changing `events.py`, `money.py`, `split.py`, `store.py`, `groups.py` or
  `accounts.py`.** No new event type, no new store method, no new column, no new index. If
  a criterion appears to need one, stop and raise it.
- **Mark as paid, settlement creation, confirmation, rejection, or exposing a settlement
  state.** Tasks 14 and 15. A confirmed settlement appears in `entries` because it moved a
  pairwise debt; that is reading history, not offering an action, and no endpoint here
  writes anything.
- **Path provenance.** No chain, no intermediate member, no "via". Task 5 refused to
  compute it and this task does not reconstruct it from two ends.
- **A bulk endpoint** returning the sources of every pair, an endpoint per transfer, or
  folding `entries` into the balances payload. One pair per request, asked for only when
  somebody opens a row, is what task 13's laziness requirement is built on.
- **Filtering, sorting, searching, grouping, totalling or paginating** either the entries
  or the provenance arrays, and any query parameter on the new endpoint.
- **Narrowing who may read a pair.** No "only the two members involved" rule, no per-pair
  authorisation, no new error code.
- **Storing, caching or memoising** a breakdown, a plan or a balance, in the server, in the
  service worker or in the browser. Nothing here adds a `Cache-Control` value: `no-store`
  already covers every response.
- **Display names, an acting-member flag, or ` (you)` anywhere in a payload.** One roster
  call covers every screen, exactly as `_expense_view` decided.
- **Expense correction and voiding.** Task 17. When it lands it extends the fold, and
  `debt_sources` must keep working by reading the same events; nothing here may make that
  harder by copying an expense's fields into a stored shape.
- **The incompleteness signal**, staleness, "days since the last expense", and
  distinguishing a never-used ledger from a settled one. Task 16.
- **Any new dependency in either language**, runtime or dev, including `hypothesis`. Tasks
  3, 4 and 5 already decided property tests are a seeded `random.Random` here.
- **Docs.** `CLAUDE.md`, `README.md`, `plans/backlog.md` and `plans/spec.md` are unchanged:
  nothing about how the app is run, installed or tested changes here.
- **Editing `plans/tasks/13-transfer-drill-down.md`.** It is on another branch. The one
  divergence is recorded above and is applied there, by whoever picks up issue #14, before
  implementation starts.

## Constraints

- **Sequencing: this task must not be built until issue #32 lands.** That issue is
  rewriting `app/api.js` to reclassify every response. Two branches editing one small file
  for unrelated reasons is a merge conflict bought for nothing. Confirm #32 is on `master`
  before touching `api.js`; everything else here can be written first if that helps.
- Files to modify, and nothing else:
  - `src/splitwise_lite/balances.py`
  - `src/splitwise_lite/__init__.py`
  - `src/splitwise_lite/web.py`
  - `app/api.js`
  - `tests/test_balances.py`
  - `tests/test_web_api.py`
  - `tests/shell_harness.mjs`
  - `tests/test_shell_behaviour.py`
- No file is created and no file is deleted, in either `src/` or `app/`.
- **No new dependency of any kind, in either language.** Nothing is added to
  `pyproject.toml`, no `package.json` is created, and `.claude/hooks/guard-deps.hs.sh`
  blocks the ad hoc Python route anyway. Per CLAUDE.md a dependency is declared then
  installed with `uv sync`, never `pip install` or `uv pip install`. If something here
  genuinely cannot be built without a package, stop and get the user's approval first.
- **Integer cents throughout, and `format_amount` is the only display edge.** No float, no
  `Decimal`, no `round()`, and no division of any kind in the new domain code: the walk only
  adds and subtracts, so no remainder can arise and no rounding rule may be invented here.
  Amounts are accumulated in plain `int` and wrapped into `Money` once.
- Money crosses the wire only as a `format_amount` string, never as a number and never as
  cents, and no payload key is named `cents`. `covers_whole_debt`, `direction` and `effect`
  exist precisely so that no client ever compares two amount strings.
- `debt_sources` lives in `balances.py` and reuses that module's existing private helpers
  for partitioning, id-uniqueness, the group check, the currency check and the
  earliest-decision rule. It does not re-implement any of them, and no rule is copied into
  a second place.
- Dependency direction is unchanged: `balances.py` imports from `money.py` and `events.py`
  only, `web.py` stays the only module that knows Flask exists, and no module in the
  package imports the web layer. `test_balances_imports_only_money_and_events_from_the_package`,
  `test_the_earlier_modules_never_learn_about_the_fold` and
  `test_no_module_in_the_package_imports_the_web_layer` all pass untouched.
- Public names added: `debt_sources`, `DebtSources`, `DebtEntry`, `DebtEntryKind` and
  `DebtEffect` in `balances.py`. Everything else added there is underscore-prefixed.
  `web.py` gains **no** public name: the handler, the two view helpers and the enum-to-wire
  maps are all private, so `test_the_public_surface_is_exactly_the_named_names` and
  `test_everything_else_the_module_defines_is_underscored` pass unchanged.
- Python 3.12 target, `frozen=True, slots=True` on both new dataclasses, eager validation,
  and a docstring on every new public name stating the invariant it enforces.
- No `hash()` of a string reaches any decision, and every iteration over a `set` or a
  `dict` view that can reach a result goes through `sorted()`, so two readers of one ledger
  see one answer.
- Every authentication and CSRF decision stays task 9a's. The new endpoint is registered,
  named in `_API_ENDPOINTS`, and left out of both exemption tuples; the handler contains no
  cookie read, no session lookup and no membership check of its own beyond the roster test
  on the two path ids.
- The error contract is unchanged: one `DomainError` family, one JSON body shape, the
  existing `ERROR_STATUS` and `ERROR_CODE` tables with no new row, and no new status code
  used by this endpoint beyond 200, 400, 401, 403 and the routing 404.
- `app/api.js` gains one function and nothing else. JavaScript there stays plain,
  browser-native, classic (non-module) script in the existing style: an IIFE,
  `'use strict'`, `var`, named functions, single-quoted strings. No framework, no polyfill,
  no transpilation, no minification. Every URL stays relative.
- The front end does no arithmetic, no formatting, no comparison and no parsing of an
  amount, and this task adds nothing to `app/` that could start.
- New tests are appended at the end of their files. The only pre-existing tests that change
  are the four named in the criteria: one deletion, one replacement, and two widenings.
- Tests run with `uv run python -m pytest`. No test is skipped or xfailed and assertions
  are exact, per `.claude/rules/testing.md`.
- Every non-obvious choice made here gets a one line comment where it is implemented, so
  the next person does not undo it by tidying: why the entries walk lives beside the fold,
  why a pending settlement is absent, why an expense paid by a third member contributes
  nothing, why `DebtSources.amount` is signed while the wire is a magnitude, why
  `covers_whole_debt` and `effect` are computed on the server, why the wire vocabulary is a
  map rather than the enum values, and why `entries` is reversed at the handler.
- **This file must not be modified, with one exception: a statement in it that is provably
  wrong may be corrected**, following the precedent tasks 5, 9b, 11 and 13 set. Sharpening
  a criterion, re-scoping one or softening one to suit an implementation is not covered and
  stays forbidden. Every correction carries a dated marker saying what the file used to
  say, what it says now and why.
