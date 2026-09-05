# Task 12: Balances screen

**Depends on:** 5 (complete, on `master`), 8 (complete, on `master`), 9a (complete, on
`master`)
**Consumed by:** 13 (transfer drill-down), 14 (mark as paid), 16 (incompleteness signal),
18 (end-to-end smoke test)

Sharpened from `plans/backlog.md` task 12. The backlog entry stays as written; this file
is the implementable version.

The backlog calls this "the screen the whole product exists to render", and the spec's
resolution of "netting and audit trail pull in opposite directions" is the reason it is
built the way it is: balances are never stored, they are folded out of the event log on
every read, and simplification is a display layer on top. This task renders that, and
stores nothing itself.

Everything it needs already exists. Task 5 produced the transfer plan, task 9a exposed it
at `GET /api/balances` with amounts already formatted as strings, and task 8 plus task 9a
built the shell, the router, the API client, the sign-in gate and the offline message.
**This task fills one screen section. It is not allowed to reach past it.**

## Goal

Opening `#/balances` in the shell shows every member's net position and the list of
suggested payments that would settle the group, both read from `GET /api/balances` each
time the screen is entered, and both rendered from strings the server formatted. A group
that has never spent anything and a group that is fully settled each read as a working
screen rather than a broken one, and nothing on the screen suggests the figures were
stored anywhere.

## What it says, exactly

Two lists, in this order, under the existing `<h1>Balances</h1>`.

**Net positions.** One row per entry in the payload's `net` array, in the order the array
arrives, which is roster order. The row names the member first, then the verb, then the
amount:

| `direction` | The row reads |
|---|---|
| `owes` | `Jo owes 10.50` |
| `owed` | `Sam is owed 10.50` |
| `settled` | `Ali is settled up` |

The verb is chosen from `direction` and from nothing else. **The screen never inspects
the amount string to decide what a row means**: no comparison against `"0.00"`, no length
check, no conversion to a number. `direction` is the sign, carried separately for exactly
this reason, and `amount` is always the non-negative magnitude.

A settled row shows **no amount at all**. `"0.00"` next to a name is a figure a reader
has to interpret; "is settled up" is the answer they came for. The payload still says
`"0.00"`, and the screen still ignores it.

**Suggested payments.** One row per entry in `transfers`, in the order the array arrives.
The row names the payer first, because the payer is the person who acts on it and task 14
will hang "mark as paid" off exactly this row:

    Jo pays Sam 10.50

**The currency appears once**, above the net list, as "Amounts are in AUD", with the code
taken from the payload's `currency` field. It is not repeated per row: at 320 px a code on
every line is noise. No currency symbol appears anywhere on this screen, in markup, in CSS
or in JavaScript. `format_amount` produces `"12.50"` and `"1,234.50"` without one, and the
front end does not get to add one.

**The acting member is marked** by appending ` (you)` to their display name wherever it
appears, in both lists, matched on `member_id` against the session view the API client
already holds. Names are never replaced by "You": two flatmates read this list off one
phone, and a list where the same row means different things depending on who is holding it
is worse than a list of names. If the session view or its member is missing, no name is
marked and everything else still renders.

**Names come from `GET /api/members`.** The balances payload carries ids only. A member id
is an opaque `new_id()` string and means nothing to a flatmate, so **no member id is ever
displayed**. A `member_id` with no roster entry renders as `Unknown member` and the row is
still shown: hiding money because a name is missing is the worse failure.

## The empty group and the settled group

Both are legitimate 200 responses and neither is an error.

**The net list is never empty when the group has members.** `Balances.net_for` is total by
design, so a group that has recorded nothing returns one entry per member, every one of
them `"0.00"` and `settled`. The screen renders all of them. That is what stops a fresh
flat from opening this screen and seeing a blank page: they see their roster, each person
settled up, which is both true and obviously working.

**An empty `transfers` array is a stated answer, not an absence.** The suggested payments
heading stays, the list is empty, and one sentence takes its place:

    No payments needed. Every net position is zero.

That sentence is true for a group that has never spent anything and true for a group that
has spent and settled, which matters, because as explained below the screen cannot tell
those two apart. Nothing celebratory, nothing that claims the ledger is complete.

**A group with no members at all** renders neither list and shows:

    This group has no members yet, so there is nothing to work out.

That is reachable through a half-finished `scripts/setup_group.py` run, and a screen that
renders two empty lists in that state reads as a bug.

**Every fixed sentence the screen can show lives in `app/index.html`, hidden, and the code
only toggles `hidden`.** There is no JavaScript test runner in this repo, so prose that
sits in markup is prose a Python test can pin exactly and prose that a reviewer can read in
a diff. The only text the code composes is a row: a name, a verb and an amount.

## The one thing the API cannot answer, stated loudly

**`GET /api/balances` cannot distinguish a group that has recorded nothing from a group
that has recorded plenty and settled all of it.** Both produce every member at `"0.00"`
and `settled` with an empty `transfers` array, byte for byte. There is no expense count, no
"last expense at" and no event count in the payload, and the roster call does not carry one
either.

This task does **not** fix that, and it does not change `src/splitwise_lite/web.py` to
add a count. Two reasons:

* Task 16 owns the incompleteness signal and is specified to surface days since the last
  expense and which members have logged nothing recently. That is the real answer, it is
  bigger than a count, and inventing half of it here would be work task 16 then has to
  unpick.
* Fetching `GET /api/expenses` from this screen purely to count rows would pull the whole
  feed payload on every visit to duplicate the request task 11 already makes, to decide one
  sentence.

So the screen deliberately does not distinguish them, and the wording above is chosen to be
honest in both cases. The always-visible note under the heading carries the rest of the
weight:

    These figures are worked out from the recorded expenses each time this screen opens,
    and are never stored. An expense nobody recorded is not in them.

**If the product decides before task 16 that the two states must read differently, that is
a change to `GET /api/balances` (an expense count or a last-expense timestamp), and it
belongs to whoever owns `web.py` next. Raise it; do not add it inside this task.**

## The states the API can return, and which are already handled

Task 9a built one network chokepoint and three failure screens. **This task reuses all of
them and reinvents none.**

| State | Response | Who handles it | What this task does |
|---|---|---|---|
| Not signed in | 401 | `api.js` fires `onUnauthenticated`, `app.js` shows the sign-in gate | nothing |
| Signed in, not linked to a member | 403 `member_not_linked` | `api.js` fires `onNotLinked`, `app.js` shows "nobody has linked you" | nothing |
| No group configured | 503 `no_group_configured` | `api.js` treats any status at or above 500 as no answer and fires `onOffline` | nothing |
| Two groups configured | 503 `ambiguous_group` | same | nothing |
| Network failure | rejected fetch | `api.js` fires `onOffline`, `app.js` shows the offline message and never the gate | nothing |
| Anything else (a 404, a 4xx nobody expected, a body that will not parse) | rejected promise, no global handler fires | **this screen** | clears both lists and shows its own one-line failure message |

The screen registers no handler with `api.onUnauthenticated`, `api.onNotLinked` or
`api.onOffline`, adds no retry, no redirect and no polling, and shows no sign-in prompt of
its own.

Two consequences worth writing down rather than discovering:

* A 503 from a server nobody has run `setup_group.py` against renders as the offline
  message, which names the wrong cause. That is task 9a's classification, it is on
  `master`, and changing it would change the answer for all three screens at once. It is
  recorded here as a known rough edge and is **out of scope**.
* Because the three global handlers replace the whole app frame, the screen's own failure
  path may run while the screen is hidden. That is fine and is why the rule below is
  unconditional: on any failure, clear the figures and show the failure message. Re-entering
  the app re-runs the fetch and overwrites it.

## Structured for task 13, but no drill-down here

Task 13 makes each suggested payment expand into the pairwise debts it absorbed. It must be
able to do that by changing the one function that builds a transfer row, not by
restructuring the list. So:

* The transfer list is a `<ul>`, one `<li>` per transfer, built by one named function that
  takes one transfer and returns one `<li>`. Not a `<table>`, not a run of `<p>` elements,
  not text lines.
* Each `<li>` carries `data-from` and `data-to` holding the two member ids from the payload,
  so a later handler can find the transfer a row belongs to without parsing its text. The
  ids are attributes only and are never rendered as text.
* The row's sentence sits inside a **single child element** of the `<li>`, so task 13 can
  replace that child with a button and append a detail region as its sibling without
  touching the code that builds the list.
* The row is already at least 44 px tall, so nothing about the layout shifts when task 13
  makes it tappable.
* The renderer does not assume a pair appears at most once. `simplify_debts` sorts by
  `(from_member_id, to_member_id)` and does not emit a pair twice today, but the screen
  keys nothing on the pair and renders the array as it arrives.

And, equally: **no drill-down is built.** No click handler, no `<details>`, no `<summary>`,
no `aria-expanded`, no chevron or disclosure glyph, no `cursor: pointer`, no hidden detail
region and no request for provenance. An affordance that does nothing is worse than none,
and `payer_debts` and `receiver_credits` are not in the payload yet by design.

## Two other branches are editing these three files

Task 11 (the expense feed, issue #12) is being built at the same time and edits
`app/index.html`, `app/app.js` and `app/styles.css`, the same three files as this task. A
JavaScript test harness (issue #31) is also in flight and may or may not land. **Write this
work so the two branches merge with a trivial resolution, and do not coordinate beyond
that.**

The rules that achieve it, all of them enforceable by reading the diff:

* In `app/index.html`, the only edit is **inside `<section id="screen-balances">`**. The
  head, the header, the gate, the notice, the feed and add sections, the nav and the script
  tag are untouched.
* In `app/app.js`, the only edits are **one new contiguous region appended at the end of the
  existing IIFE**, marked with a banner comment, plus **exactly one added line inside
  `showApp()`**. Nothing else in the file changes. That one line is the only shared edit in
  the task; if the feed branch adds its own beside it, the merge resolution is to keep both
  lines.
* In `app/styles.css`, the only edit is **one block appended at the end of the file**. No
  existing rule is modified. **Every selector it adds is prefixed `.balances-`**, so it
  cannot collide with the feed branch's names or restyle a shared component.
* Every element id this task adds is prefixed `balances-`.
* In `tests/test_web_shell.py`, new tests are **appended at the end of the file**, not
  interleaved with the existing ones, and the single pre-existing assertion this task must
  change is changed by deleting exactly one line.
* `app/sw.js` is not touched. See the note about `VERSION` in Out of scope.

## How it is tested, and what only a person can check

There is no JavaScript test runner in this repo. Issue #31 is adding one concurrently and
its outcome is not guaranteed, so **this task must pass, and be reviewable, with no runner
at all**, and must add none itself.

What that leaves is a hard line, and this repo has drawn it three times, most recently on
PR #30 where a reviewer demonstrated that a test asserting the presence of a string in a
JavaScript file passed against two mutants that reintroduced the bug it claimed to cover:

* **A test may ban an identifier** in a shell file. `test_only_the_api_client_calls_the_back_end`
  and `test_no_shell_file_does_money_or_split_arithmetic` are both of this shape and are on
  `master`: the property is "this text does not appear anywhere", and a ban is falsified by
  a single occurrence.
* **A test may not assert that a string is present in `app/app.js` in order to claim a
  rendering behaviour is covered.** "`'is owed'` appears in app.js" is not evidence that a
  creditor's row says "is owed", it is evidence that seven characters exist. Do not write
  one. If a behaviour cannot be checked in Python, it goes on the hand checklist below and
  is recorded as checked by hand.

Structure that a Python test *can* pin, and therefore must: the markup of the balances
section, the ids and roles it carries, the exact fixed sentences (which is why they live in
markup), that the two lists ship empty, that the placeholder is gone, and the bans. The API
side is already pinned by task 9a's tests, named in the criteria, and this task adds none.

## Acceptance criteria

**The markup**

- `app/index.html`'s `<section id="screen-balances">` keeps its existing `class`, `id`,
  `aria-labelledby` and `hidden` attributes and its `<h1 id="title-balances" tabindex="-1">`
  with `Balances` as its text. The router's focus handling is untouched.
- Its `<p class="lede">` reads `Who owes who, in the fewest payments.`
- It carries one always-visible note, `id="balances-derived"`, reading exactly: `These
  figures are worked out from the recorded expenses each time this screen opens, and are
  never stored. An expense nobody recorded is not in them.`
- It carries a status region `<div id="balances-status" role="status">` holding four
  paragraphs, each with the `hidden` attribute in the committed markup and each with the
  exact text: `balances-busy` = `Working these out.`; `balances-error` = `These figures
  could not be worked out just now.`; `balances-none` = `No payments needed. Every net
  position is zero.`; `balances-empty-roster` = `This group has no members yet, so there is
  nothing to work out.`
- It carries two `<h2>` headings, in document order, `Net positions` then `Suggested
  payments`, and no heading level is skipped.
- It carries `<p id="balances-currency" hidden>Amounts are in <span
  id="balances-currency-code"></span>.</p>`, with the span empty in the committed markup.
- It carries `<ul id="balances-net">` and `<ul id="balances-transfers">`, both empty in the
  committed markup.
- The `Placeholder. Task 12 fills this with balances and settle up.` marker and its two
  bullet notes are removed, and the section contains no other placeholder text.
- The section contains no amount, no currency symbol, no member name, no date and no
  `Loading`, `skeleton` or `spinner`, so `test_no_screen_shows_invented_data` passes
  unchanged.
- Every id and class the new code looks up is spelled in `app.js` as
  `document.getElementById('...')` or `document.querySelector('.…')` with single quotes and
  a literal name, so `test_every_element_the_router_reaches_for_exists_in_the_document`
  keeps covering it. A lookup written any other way silently escapes that guard.

**What renders**

- Entering `#/balances` requests `GET /api/members` and `GET /api/balances` together
  through `api.members()` and `api.balances()`, and renders only when both resolve.
- The net list renders one `<li>` per entry of `net`, **in the order the array arrives**,
  which is roster order. The screen sorts nothing, reverses nothing and filters nothing out.
- A row's text is the member's display name, then the verb chosen from `direction`, then the
  amount string: `owes` gives `Jo owes 10.50`, `owed` gives `Sam is owed 10.50`, `settled`
  gives `Ali is settled up` with no amount rendered.
- The verb is chosen from `direction` alone. The screen never compares an amount string to
  `"0.00"`, never measures it and never converts it.
- A `direction` value that is none of the three renders the name and the amount with no
  verb, and does not throw. One unexpected row must not blank the screen.
- Amount strings are inserted exactly as received. No rounding, no padding, no thousands
  separator inserted or removed, no symbol prepended.
- The transfer list renders one `<li>` per entry of `transfers`, in the order the array
  arrives, each reading `Jo pays Sam 10.50` with the payer named first.
- `Amounts are in <code>` is shown once above the net list, with the code taken from the
  payload's `currency` field and inserted as text. The code is not hard-coded anywhere, and
  the element is hidden whenever there is nothing to show.
- The acting member's display name is followed by ` (you)` in both lists, matched on
  `member_id` against `api.cachedSession().member.id`. A null session view, or one with a
  null member, marks nothing and breaks nothing.
- A `member_id` in `net` or in a transfer with no entry in the roster response renders as
  `Unknown member`, and the row is still rendered.
- No member id is ever rendered as visible text, in either list, in any state.
- Every server-provided string reaches the DOM through `textContent` or `createTextNode`. A
  display name containing `<`, `&` or a quote renders as those characters and is never
  parsed as markup.
- A member the ledger has never seen appears in the net list as settled, because
  `Balances.net_for` is total; the screen does nothing special for them.
- A member who both owes somebody and is owed by somebody else appears once, with their
  single netted position. The screen shows no pairwise breakdown: that is task 13.
- The same member appearing in several transfer rows renders several rows. Nothing is
  merged, grouped or deduplicated.

**The settled and empty states**

- `transfers: []` with a non-empty `net` shows the `Suggested payments` heading, an empty
  list and `balances-none`, and the net list still renders every member. The screen must not
  read as broken or blank.
- A group that has recorded nothing renders exactly the same as a fully settled group, by
  decision, with every member settled and `balances-none` shown. Neither is an error and
  neither shows the failure message.
- `net: []` shows `balances-empty-roster`, both lists empty and hidden, and the currency
  line hidden.
- `balances-none` is hidden again as soon as a render produces at least one transfer row, and
  the currency line is shown whenever the net list has at least one row.
- At most one of `balances-busy`, `balances-error`, `balances-none` and
  `balances-empty-roster` is visible at any moment.

**Fetching, failing and refreshing**

- The fetch runs when the balances route is entered, and when the app frame is shown while
  the current hash is already `#/balances` (signing in on the balances screen must not leave
  it blank). It does not run for any other route.
- The figures are re-fetched on every entry to the route. Nothing is cached across
  navigations, kept in a module variable between visits, or stored in `localStorage`,
  `sessionStorage` or `indexedDB`. A derived figure held over from a previous visit is the
  spec's "authoritative while being wrong" failure in miniature.
- There is no polling, no timer, no interval and no automatic retry.
- While a request is in flight, both lists are cleared, the currency line is hidden and
  `balances-busy` is shown. No spinner, no animation, no greyed skeleton rows.
- Only the most recent request may render. If the user leaves and re-enters the route, an
  earlier response that arrives late is discarded, never rendered over the newer one.
- If either request fails for any reason, both lists are cleared, the currency line is
  hidden and `balances-error` is shown. Stale figures are never left on screen after a
  failed refresh.
- The screen registers no handler with `api.onUnauthenticated`, `api.onNotLinked` or
  `api.onOffline`, and shows no sign-in prompt, no "not linked" message and no offline
  message of its own. Those three screens are task 9a's and are reused unchanged.
- `app/api.js` is not modified. No new API function, no changed error classification.

**Ready for task 13, with no drill-down**

- Each transfer `<li>` carries `data-from` and `data-to` holding the payload's
  `from_member_id` and `to_member_id`.
- Each transfer `<li>` holds its sentence inside exactly one child element, so a later task
  can swap that child and append a sibling.
- One named function builds one transfer row from one transfer object, and the list builder
  calls it. Task 13 changes that function.
- Each transfer row is at least 44 px tall at 320 px, including when its text wraps to two
  lines.
- No transfer row is an `<a>`, a `<button>`, a `<details>` or a `<summary>`; carries
  `aria-expanded`, `role="button"` or `tabindex`; has a click, key or pointer handler; or
  shows a chevron, arrow or `cursor: pointer`.
- Nothing requests, reads or renders `payer_debts` or `receiver_credits`. They are not in
  the payload.

**Layout**

- All new CSS is appended to `app/styles.css` in one block, every selector prefixed
  `.balances-`, and no existing rule is edited.
- At 320, 360 and 390 CSS px wide, with a 40-character display name in the roster, there is
  no horizontal scroll: `document.documentElement.scrollWidth` equals `clientWidth`.
- A long display name wraps onto another line. It is never clipped, never ellipsised and
  never overlapped by the amount.
- An amount never breaks across lines and never wraps mid-number.
- Visual order matches DOM order in both lists. No `flex-direction: row-reverse`, no
  `order` property, no absolute positioning that moves the amount ahead of the name.
- Rows are separated by something other than colour alone, and no row's meaning is carried
  by colour alone: "owes" and "is owed" are distinguished by the words, first.
- Body and row text stay at 16 px or above, so `test_no_rule_sets_a_font_size_below_sixteen_pixels`
  passes unchanged.
- The screen scrolls to its last row inside the existing `.content` area, with the bottom
  nav never covering the final row, at every tested width. A 12-member roster is enough to
  prove it.
- No animation or transition is added. If one is, it is disabled under
  `@media (prefers-reduced-motion: reduce)` like everything else in the file.

**Not reimplementing money**

- No file under `app/` gains money formatting, cent arithmetic, rounding, a currency symbol
  or a locale-aware number call. `format_amount` in `src/splitwise_lite/money.py` stays the
  only display edge.
- `app/app.js` contains none of `toFixed`, `parseFloat`, `parseInt`, `Number(`,
  `Math.round`, `Math.floor`, `/ 100`, `Intl`, `toLocaleString`, `NumberFormat`, or the
  literal `0.00`.
- `app/index.html` and `app/styles.css` contain no `$`, `£` or `€`, and no CSS rule inserts
  a currency symbol through `content`.
- `app/app.js` contains no `innerHTML`, `outerHTML`, `insertAdjacentHTML` or
  `document.write`.
- `app/app.js` contains no `.sort(` and no `.reverse(`. Ordering is the server's, in both
  lists.
- `app/app.js` still contains no `fetch` and no `/api`, so `test_the_narrowed_rule_still_bites`
  passes unchanged. Every request goes through `window.SplitwiseApi`.

**Automated tests**

- `tests/test_web_shell.py` gains new tests appended at the end of the file, covering: every
  id above exists in the balances section; `balances-status` carries `role="status"`; the
  four message paragraphs carry `hidden` in the committed markup and hold their exact
  sentences; `balances-derived` holds its exact sentence and is not hidden; both `<ul>`
  elements are empty; `balances-currency-code` is empty; the two `<h2>` headings appear in
  the stated order; and each ban listed above.
- `test_every_screen_names_the_task_that_fills_it` changes by **deleting exactly the one
  line** asserting the task 12 placeholder. The lines for tasks 10 and 11 stay byte
  identical, so a merge with the feed branch resolves by keeping both deletions.
- No other pre-existing test in `tests/test_web_shell.py` is edited, and
  `test_no_screen_shows_invented_data`, `test_only_the_default_screen_starts_visible`,
  `test_every_element_the_router_reaches_for_exists_in_the_document`,
  `test_no_shell_file_does_money_or_split_arithmetic`,
  `test_only_the_api_client_calls_the_back_end`, `test_the_narrowed_rule_still_bites`,
  `test_no_rule_sets_a_font_size_below_sixteen_pixels` and
  `test_the_worker_precaches_exactly_the_shell` all pass untouched.
- **No test asserts that a string is present in `app/app.js` in order to claim a rendering
  behaviour is covered.** Bans are permitted, because a ban is falsified by one occurrence;
  presence assertions about behaviour are not, and PR #30 is the record of why.
- No test in `tests/test_web_api.py` is added or changed. The five API facts this screen is
  built on are already pinned there and are named for the reviewer:
  `test_a_settled_group_is_every_member_at_zero_and_no_transfers`,
  `test_balances_report_the_exact_figures_and_the_exact_transfer_list`,
  `test_a_member_the_ledger_has_never_seen_is_settled_at_zero`,
  `test_a_transfer_carries_no_provenance`, and the parametrized authentication tables that
  cover `GET /api/balances` at 401 and 403. If one of them turns out not to hold, **stop**:
  that is a contract problem, not a screen problem.
- No JavaScript test runner, no `package.json`, no `node_modules`, no browser automation and
  no headless browser is added, whatever issue #31 does. This task must be green on its own.
- No test is skipped or marked xfail, per `.claude/rules/testing.md`.
- `uv run python -m pytest` passes. Plain `uv run pytest` fails on this machine with an
  access-denied spawn error.

**Verified by hand**

Everything below is browser-only. Record each as checked, against a store seeded by
`scripts/setup_group.py` and served with
`uv run python scripts/serve.py --store ledger.sqlite3`. Because `app/sw.js` is not touched
and its `VERSION` is unchanged, tick "Update on reload" in DevTools, Application, Service
Workers, or unregister the worker, before checking anything, or the cached shell will serve
the old `app.js`.

- With three expenses seeded across all three split modes: the net rows name the right
  people with the right verbs and the right amounts, and the transfer rows read
  `<payer> pays <receiver> <amount>` in the order the API returned them.
- A member with no expenses at all shows as settled up, with no amount.
- A member who owes one person and is owed by another shows one netted row.
- The acting member's name carries ` (you)` in both lists; nobody else's does.
- `Amounts are in AUD` appears once, above the net list, and no `$` appears anywhere on the
  screen.
- A brand new group with no expenses: every member settled up, `No payments needed. Every
  net position is zero.`, and the screen reads as working rather than empty or broken.
- The same group after settling everything looks identical. Confirm deliberately, because it
  is a decision and not an accident.
- Leaving `#/balances` and returning re-fetches: the Network panel shows a fresh
  `/api/balances` and `/api/members` pair on each entry, and none while another screen is
  showing.
- Tapping Balances while already on Balances does nothing, per task 8's no-op rule.
- Signing out on `#/balances` shows the gate, and signing back in re-renders the figures
  without a reload.
- DevTools set to Offline, then entering `#/balances`: the offline message shows, not the
  sign-in gate, and no figures are left on screen.
- Stopping the server and entering `#/balances`: same. Restarting it and re-entering
  renders again.
- Against a store with no group at all: the offline message shows. Confirm it is the known
  rough edge above and not a new failure.
- Signed in as a user nobody has linked: the "nobody has linked you" notice, no ledger data.
- With a 40-character display name in the roster, at 320x568, 360x640, 390x844 and landscape
  844x390: no horizontal scroll, the name wraps, the amount stays whole, nothing overlaps,
  and the last row is reachable above the nav.
- With VoiceOver or NVDA: entering the route announces the Balances heading, and the arrival
  of the figures or of a message is announced from the status region.
- Console is clean on entry, on re-entry, after a failure and after signing back in.

## Out of scope

- **Any drill-down.** Tapping a transfer does nothing. `payer_debts` and
  `receiver_credits` are task 13's, along with the payload change that carries them.
- **Mark as paid, settlement, pending or awaiting-confirmation rows.** Tasks 14 and 15. No
  settlement event is created, read or rendered, and no row shows a settlement state.
- **The incompleteness signal.** Days since the last expense, who has logged nothing, any
  staleness badge: task 16. This screen ships one honest sentence about derivation and stops
  there.
- **Distinguishing a never-used ledger from a settled one.** Recorded above as a real gap
  with a named cause. Not solved here, and not solved by adding a field to `web.py`.
- **Any change to `src/splitwise_lite/`.** Task 9a already exposes everything this screen
  needs. No new endpoint, no widened payload, no new field, no reordering, no provenance.
- **Any change to `app/api.js`.** No new client function, no changed status handling, no
  caching layer.
- **Any change to `app/sw.js`, including its `VERSION`.** The precache list is unchanged
  because no file is added, and three concurrent branches bumping one constant is three
  conflicts on one line for one effective bump. **Whoever integrates this branch with task
  11's bumps `VERSION` once, at that point.** Until then, hand checks need the DevTools step
  named above. This is a release step, and it is named here so it is not forgotten.
- **A fourth route, a settings screen, a group switcher or any navigation change.** `ROUTES`
  keeps exactly `#/feed`, `#/add` and `#/balances`, and the router keeps owning the
  route-to-screen mapping.
- **The feed screen and the add screen.** Task 11 and task 10 own those sections, and this
  task does not edit them even to tidy them.
- **Sorting, filtering, searching or grouping either list**, and any per-member drill-in,
  chart, total, history or "since when" figure. The app answers who owes who.
- **Disambiguating two members who share a display name.** The roster is a manual list in
  v1; if it holds two people called Sam, both rows read Sam. Fixing that means showing an id
  or inventing a suffix, and neither is worth it here.
- **Currency symbols, locale formatting, per-row currency codes and multi-currency
  anything.** One group, one currency, fixed at creation.
- **Offline rendering of balances, a cached last-known position, or any local copy.** The
  spec cuts offline; a stored balance is the one thing the spec forbids outright.
- **A JavaScript test runner, a bundler, a framework, ES modules, a linter or a formatter.**
  Task 8's decision stands and issue #31 is its own task. If something here seems to need
  one, stop and raise it.
- **Any new dependency in either language**, runtime or dev.
- **Docs.** The run command, CLAUDE.md and README.md are unchanged: nothing about how the
  app is run or installed changes here.

## Constraints

- Files to modify: `app/index.html`, `app/app.js`, `app/styles.css` and
  `tests/test_web_shell.py`. **Nothing else.**
- No file is created and no file is deleted.
- **Nothing under `src/splitwise_lite/` changes.** Task 9a already exposes what this screen
  needs. If a criterion here appears to need a new field, a widened payload or a new
  endpoint, **stop and raise it loudly rather than editing `web.py`**; the one place this
  task already knows the API falls short is written up above and is deliberately left alone.
- `app/api.js`, `app/sw.js`, `app/manifest.json`, everything under `app/icons/`, everything
  under `scripts/`, `tests/test_web_api.py`, `tests/test_dev_server.py`, every other test
  file, `pyproject.toml`, `uv.lock`, `CLAUDE.md`, `README.md`, `plans/backlog.md`,
  `plans/spec.md`, this file and everything under `.claude/` are not modified.
- **No new dependency of any kind, in either language.** Nothing is added to
  `pyproject.toml`, no `package.json` is created, and `.claude/hooks/guard-deps.hs.sh`
  blocks the ad hoc route anyway. Per CLAUDE.md a dependency is declared then installed with
  `uv sync`, never `pip install` or `uv pip install`. If something here genuinely cannot be
  built without a package, stop and raise it.
- The edit to `app/index.html` is confined to the contents of
  `<section id="screen-balances">`.
- The edit to `app/app.js` is one contiguous region appended at the end of the existing
  IIFE, opened with a banner comment in the style of `/* --- The gate --- */`, plus exactly
  one added line inside `showApp()`. No existing function is rewritten, and `ROUTES`,
  `render`, `route`, `known`, `show`, `showGate`, `showNotice`, `setMode`, `refresh`,
  `submitted`, `wire` and the service worker registration are all left as they are.
- The edit to `app/styles.css` is one block appended at the end, every selector prefixed
  `.balances-`, with no existing rule modified.
- New tests are appended at the end of `tests/test_web_shell.py`. The only pre-existing
  assertion that changes is the one deleted line in
  `test_every_screen_names_the_task_that_fills_it`.
- JavaScript is plain, browser-native, classic (non-module) script, in the style already in
  `app/app.js`: an IIFE, `'use strict'`, `var`, named functions, single-quoted strings. No
  framework, no polyfill, no transpilation, no minification. The committed file is the file
  the browser runs.
- Every URL and every asset reference stays relative. No absolute `http://` or `https://`
  URL appears anywhere under `app/`.
- Money is a string from the server and is passed straight through. The front end does no
  arithmetic, no formatting, no comparison and no parsing of an amount, ever.
- All ordering is the server's. `net` is roster order and `transfers` is
  `(from_member_id, to_member_id)` order, both fixed in the domain layer, and the screen
  preserves them exactly.
- Every fixed sentence lives in `app/index.html`; the code toggles `hidden` and composes
  only row text.
- Element lookups are written as `document.getElementById('literal-id')` and
  `document.querySelector('.literal-class')`, single-quoted, so the existing
  document-versus-router guard keeps covering them.
- Every non-obvious choice made here (the settled row showing no amount, `direction` being
  the only thing the verb is chosen from, the two lists preserving server order, the
  `data-from` and `data-to` attributes existing for task 13, the fixed sentences living in
  markup) gets a one-line comment in the file that implements it, so the next person does
  not undo it by tidying.
- Tests run with `uv run python -m pytest`. No test is skipped or xfailed, no test binds a
  socket, and assertions are exact, per `.claude/rules/testing.md`.
