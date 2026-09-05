# Task 11: Expense feed

**Depends on:** 6 (complete, on `master`), 8 (complete, on `master`), 9 (complete, on
`master`), 9a (complete, on `master`)
**Consumed by:** 16 (incompleteness signal), 17 (expense correction)

Sharpened from `plans/backlog.md` task 11. The backlog entry stays as written; this file
is the implementable version.

Task 8 shipped `#screen-feed` as a placeholder card. Task 9a shipped `GET /api/expenses`
and `GET /api/members` and the one API client in `app/api.js`. This task fills the feed
screen from those two endpoints and stops. It is read-only: editing and voiding arrive in
task 17, and the staleness signal arrives in task 16.

## Two sibling branches are in flight

**Task 12 (the balances screen) edits the same three files: `app/index.html`,
`app/app.js` and `app/styles.css`.** A JavaScript test harness is also being proposed
separately, and its outcome is not guaranteed.

Every criterion below is written so this work is additive inside the feed screen's own
region. The Constraints section names the exact regions. Do not refactor shared code, do
not extract a shared helper, do not reorder anything you did not add, and do not wait for
either sibling. Two branches that each stay inside their own screen merge cleanly; two
branches that each tidy the router do not.

## Goal

Opening `#/feed` on a phone shows every expense the group has recorded, newest first, one
row each carrying the payer, the total, the description and who the cost was split
across. Tapping a row reveals that expense's allocation detail in place: every
participant's exact share, and the total those shares are shares of. A group that has
recorded nothing sees a plain statement that nothing has been recorded, which is never
dressed up as an error and never as a settled ledger.

## What a row shows

Three lines inside one tappable control, at 320 CSS px and up:

| Line | Left | Right |
|---|---|---|
| 1 | The description | The amount |
| 2 | `Paid by <payer>` | The local date |
| 3 | `Split across <names>` | |

**The description may be empty**, because task 2 made it optional so that entry can
happen in under ten seconds, and `GET /api/expenses` returns `"description": ""` for one.
An empty description renders as the fixed literal text **`No description`** in the muted
colour. It is not blank, because a blank first line makes the row look truncated or
broken. It is not invented from the other fields either: `Sam's expense`, `Milk run` and
any other generated summary is indistinguishable from a description a person typed, which
is the "authoritative while wrong" failure the spec names as the product's largest risk.

A description is capped at 500 characters by the store's `CHECK`, and it **wraps in full**
in the row. No line clamp: clamping needs either a measurement or a second copy of the
text in the detail, and a tall row for a long description is honest.

**The participant list is the expense's allocation members, in roster order**, which is
the order `GET /api/members` returns. Roster order rather than allocation order, so the
same set of people reads the same way on every row, and so the detail and the summary
agree. A display name is 1 to 100 characters, so six participants is up to 600 characters
on one line. The rule at 320 px:

* Three participants or fewer: name all of them, comma separated, with `and` before the
  last.
* Four or more: name the first two in roster order, then `and N others`, where `N` is the
  remaining count.
* The line wraps rather than scrolling, and sets `overflow-wrap: anywhere`, so a single
  unbroken 100 character display name breaks instead of pushing the layout wide.

Counting participants is not money arithmetic. No cent value is ever added, divided,
rounded or reformatted in JavaScript; the amounts are `format_amount` strings and they are
passed through untouched.

## Ordering and the date

**The screen renders `expenses` in the order the array arrived and does not sort,
reverse, compare or group it.** `web.py` owns the ordering rule, and it is already
written down there: `store.list_expenses` returns ascending `(created_at, id)` and
`_list_expenses` reverses it, giving newest first with ties broken by id descending. A
second ordering rule in JavaScript would be a second contract to keep in step with the
first, and the two would disagree the first time either changed.

**The date is the local calendar date of `created_at`, rendered absolutely.** For example
`5 Sep 2026`. The row's date sits in a `<time datetime="...">` element carrying the raw
`created_at` string, so the exact instant survives in the markup even though the visible
text is rounded to a day. The detail shows the local date and time together.

Local, not UTC, and not the first ten characters of the string. `created_at` is UTC, and a
flat in Australia entering the milk at 8am local on the 5th stores `2026-09-04T22:00:00Z`.
Printing the UTC date would tell them they logged it yesterday.

**No relative labels.** No `Today`, no `Yesterday`, no `3 days ago`, and no reading of the
client clock. Relative time is the vocabulary task 16 will use for the staleness signal,
and a feed that cheerfully says `Today` above a two week old ledger is the exact confident
wrongness that task 16 exists to prevent.

## The allocation detail: an inline expansion

**Decided here: an inline disclosure inside the row. Not a modal, not a separate view.**
The engineer implements this; they do not re-open it.

* **It cannot be a route.** `ROUTES` in `app/app.js` holds exactly `#/feed`, `#/add` and
  `#/balances`, and `tests/test_web_shell.py::test_the_gate_is_not_a_fourth_route` asserts
  those three keys. Task 9a already had this problem with the sign-in gate and solved it
  by showing a curtain in place of `<main>` rather than by routing to it.
* **A modal is real work done badly.** It needs a focus trap, an Escape handler, a scroll
  lock, an inert background and a return-focus rule. Half of that is an accessibility trap
  on a phone, and none of it is what this task is for.
* **A "separate view" that is not a route** would be a second screen-swapping mechanism
  sitting beside the router, which is what task 8's "the router owns the route-to-screen
  mapping" constraint is written to prevent.
* An inline disclosure pushes nothing onto the history stack, so Back still leaves the app
  from the feed, and task 8's history criteria survive untouched.

Shape: the row's summary is a `<button type="button">` carrying `aria-expanded` and
`aria-controls`; the detail is its sibling element, `hidden` when collapsed so neither a
screen reader nor find-in-page reaches it, with an id derived from the expense id.

Accepted trade-offs, recorded rather than hidden: an expansion is not deep-linkable and is
lost on any reload of the list, and expanding a row far down the feed moves the rows below
it.

## The empty state

A group with no expenses is the normal state on day one. `GET /api/expenses` answers
`{"currency": "AUD", "expenses": []}` with status 200. **It is not an error, and it must
not be rendered as one.**

It must also not read as a settled ledger. The spec's largest risk is that a half-filled
ledger "looks authoritative while being wrong", so the empty state says what is true,
which is that nothing has been recorded and that the app only knows what people enter. It
never says settled, square, balanced, complete, up to date, nothing owed or no debts.

Task 16 adds the staleness signal to this screen and to balances. Do not build any part of
it here: no "last expense N days ago", no "these members have logged nothing", no freshness
badge. Do not build anything it would have to contradict either, which is why there is no
relative date vocabulary and no claim anywhere on this screen that the ledger is current or
complete.

## Testing, and what a source-text test may not claim

There is no JavaScript test runner in this repo, and this task does not add one. A
separate proposal may add one concurrently; its outcome is not guaranteed, this task does
not depend on it, and if it lands first this task still does not use it.

The line, and it is not negotiable: **a test may assert that a token is absent from a
source file; a test may not read source text and claim it covers rendering behaviour.**
This project has rejected the second three times, most recently on PR #30, where a
reviewer showed such a test passing two mutants that reintroduced the bug it claimed to
cover. A ban ("`app.js` contains no `innerHTML`") is falsifiable by the file itself. A
claim ("the feed renders newest first, because the source contains the word `expenses`")
is not a test. Everything in that second category goes on the hand checklist below,
labelled as unverified by the suite.

## Acceptance criteria

**The document region**

- Every change to `app/index.html` is inside `<section class="screen screen--feed"
  id="screen-feed">`. No other element in the document is added, removed, reordered or
  edited.
- The `<h1 id="title-feed" tabindex="-1">` and the `<p class="lede">Every expense the
  group has recorded, newest first.</p>` are unchanged, byte for byte.
- The placeholder `<div class="card">` and its `<ul class="notes">` are removed from the
  feed screen only. The add and balances placeholders are untouched.
- The section gains exactly these six elements, each with the id given, and each present
  exactly once in the document: `feed-currency`, `feed-loading`, `feed-empty`,
  `feed-error`, `feed-retry` and `feed-list`.
- `feed-list` is a `<ul>` and is empty in the committed document. No `<li>`, no sample row,
  no template markup.
- `feed-currency`, `feed-loading`, `feed-empty` and `feed-error` each carry the `hidden`
  attribute in the committed document, so the first paint shows one state at most and never
  all four.
- `feed-retry` is a `<button type="button">` inside `feed-error`.
- `feed-empty` contains an `<a href="#/add">` so the first expense is one tap away. It is a
  plain anchor: routing is anchors plus `hashchange`, per task 8, and no click handler is
  registered on it. This anchor is what forced the second line of change in
  `tests/test_web_shell.py`; see the correction dated 2026-09-06 under "Automated tests,
  in Python".
- The committed feed markup contains no amount, no currency symbol, no member name, no date
  and no expense description.
  `tests/test_web_shell.py::test_no_screen_shows_invented_data` passes unchanged, which
  means the visible copy contains none of `$`, `£`, `€`, `%`, no text matching `\d+\.\d\d`,
  and none of the words `Loading`, `loading`, `skeleton` or `spinner`. That test inspects
  text nodes only, so the id `feed-loading` is fine while its copy is not allowed to use the
  word.
- `tests/test_web_shell.py::test_each_screen_is_a_section_with_a_focusable_heading`,
  `test_only_the_default_screen_starts_visible` and
  `test_every_element_the_router_reaches_for_exists_in_the_document` all pass unchanged.

**The copy**

- `feed-loading` reads exactly: `Fetching the group's expenses.`
- `feed-empty` reads exactly, across its two paragraphs and its link:
  `Nobody has recorded an expense in this group yet.`
  `The app only knows what people enter. Once someone adds a spend it appears here, newest
  first.`
  `Add the first expense`
- `feed-error` reads exactly: `The feed did not arrive. Nothing you have recorded is lost.`
  and its button reads `Try again`.
- The empty-state copy contains none of these, case-insensitively: `settled`, `square`,
  `balanced`, `complete`, `up to date`, `nothing owed`, `no debts`, `all clear`. A test
  asserts the list.
- The error copy claims nothing about the ledger's contents: it contains none of
  `no expenses`, `nothing recorded`, `nothing yet`, case-insensitively. A failed request
  must never read as an empty ledger.
- No copy anywhere on this screen claims the ledger is current, complete or up to date.

**Loading, empty and failed are three different things**

- On first arrival at `#/feed`, `feed-loading` is shown until both requests settle. A blank
  feed area while a request is in flight is indistinguishable from a group that has
  recorded nothing, which is precisely the spec's failure mode. One plain line, no
  animation, no skeleton rows and no spinner: a skeleton reads as broken and a phantom row
  on a money app reads as data.
- A 200 carrying `"expenses": []` shows `feed-empty` and hides the other three states.
- A 200 carrying one or more expenses shows `feed-list` and `feed-currency` and hides the
  other three states.
- A request that rejects, or a 200 whose body is not the documented shape, shows
  `feed-error` and hides the other three, and clears `feed-list`. No list is ever shown
  beside a failure notice, and a failure never shows `feed-empty`.
- Exactly one of the four states is visible at any moment. A test cannot check this, so it
  is on the hand checklist; the implementation makes it structural by routing every state
  change through one function that hides all four and then shows one.
- The retry button re-issues both requests and returns to the loading state while they are
  in flight.
- 401, 403 `member_not_linked`, a network failure and any 5xx are already claimed by
  `app/api.js`, which raises the gate or one of the two notices over the whole app frame.
  The feed adds no second message for any of them and does not inspect the status code: it
  shows `feed-error` behind the curtain, where nobody sees it. This is deliberate. There is
  exactly one place that decides what a 401 means, and it is not this screen.

**Data and requests**

- The screen reads `GET /api/expenses` and `GET /api/members` through
  `window.SplitwiseApi.expenses()` and `window.SplitwiseApi.members()` and through nothing
  else. `app/app.js` still contains no `fetch(`, no `XMLHttpRequest`, no `EventSource`, no
  `WebSocket` and no `/api`, so
  `tests/test_web_shell.py::test_only_the_api_client_calls_the_back_end` and
  `test_the_narrowed_rule_still_bites` pass unchanged.
- Both requests are issued together and the list renders only when both have resolved. If
  either fails, the screen shows `feed-error`.
- The feed loads when its route becomes current and when the app frame is shown after a
  successful session check, and at no other time. No polling, no timer, no interval, no
  `visibilitychange` handler, and no refetch on window focus.
- A load while a load is already in flight is skipped rather than queued, so repeated tab
  taps cannot stack requests.
- Each successful load replaces the whole list, so a reload never duplicates a row.
  Expansion state resets with it; that is accepted.
- Navigating away to `#/add` or `#/balances` and back to `#/feed` re-requests. A feed that
  loaded once and never again would show a stale list the moment task 10 adds an expense,
  which is the same "authoritative while wrong" failure in a different costume.
- Nothing is written to `localStorage`, `sessionStorage`, `indexedDB` or `document.cookie`,
  and no response is cached in a variable that outlives the render.

**Rendering one row**

- Rows appear in the exact order of the `expenses` array. `app/app.js` contains no `sort(`,
  no `reverse(`, and no comparison of two `created_at` values.
- Line 1 carries the description and the amount. The amount is the entry's `amount` field
  passed through as text: no symbol is prepended, no digits are reformatted, and no
  separator is changed. `format_amount` already produced `12.50`, `1,234.50` and `0.00`.
- An entry whose `description` is empty, or empty once trimmed, renders the literal text
  `No description` in the muted colour. It is not blank, not an invented summary, and not
  styled as an error.
- A 500 character description wraps and produces no horizontal scroll at 320 px.
- Line 2 reads `Paid by <display name>` using the payer's name from the roster, and carries
  the date in a `<time datetime="<created_at verbatim>">` element whose visible text is the
  local calendar date.
- Line 3 reads `Split across ` followed by the participant names by the three-or-fewer rule
  above.
- A member id that appears in an expense but not in the roster renders as the literal text
  `Unknown member`. It never renders as a blank, and it never renders as a raw id: a UUID
  on screen is noise that helps nobody. One unresolvable id must not stop the row, or any
  other row, from rendering.
- Two members of one group may share a display name, which `store.Member` explicitly
  allows. Both render the same text and the screen does not disambiguate them. Inventing
  `Sam (2)` would be the front end making up data, and showing an id would be worse.
- **Every piece of user data reaches the DOM as text, never as markup.** An expense
  described as `<img src=x onerror=alert(1)>` renders as those literal characters. A test
  asserts that `app/app.js` contains none of `innerHTML`, `outerHTML`,
  `insertAdjacentHTML`, `document.write`, `eval(` or `new Function`. The list is cleared
  with `replaceChildren()`.

**Rendering the detail**

- Each row's summary is a `<button type="button">` spanning the row, so the whole row is
  the tap target, with a hit area of at least 44 x 44 CSS px at 320 px.
- The button carries `aria-expanded="false"` when collapsed and `"true"` when open, and
  `aria-controls` naming the detail element's id, which is derived from the expense id and
  is therefore unique in the document.
- The detail element carries `hidden` when collapsed, so find-in-page and assistive
  technology do not reach a closed detail.
- Open and closed are distinguished by a visible indicator as well as by the presence of
  the detail, and never by colour alone. Any indicator glyph is `aria-hidden="true"`.
- More than one row may be open at once. Opening one does not close another: collapsing
  somebody else's row to open yours is surprising, and single-open would be a piece of
  state the next re-render has to preserve.
- Toggling a row does not scroll the page, does not change `window.location.hash`, adds no
  history entry, and re-renders no other row.
- The detail lists **every** allocation, one per line, in roster order: the member's
  display name and that member's `amount`, passed through as text.
- Beneath the share lines, separated by a rule, is a line labelled `Total` carrying the
  expense's `amount` field verbatim. **The screen never adds the shares up.**
  `ExpenseEvent` already enforces that they sum exactly to the total, and a second
  implementation of that sum in JavaScript is exactly the drift task 8's no-arithmetic rule
  exists to prevent. Showing the shares and then the total they are shares of is what the
  criterion "the shares sum to the total" means here.
- No text on the screen claims a computed relationship between the numbers. There is no
  "these add up to" sentence, because the front end is in no position to have checked.
- Share amounts are rendered with `font-variant-numeric: tabular-nums` so the column lines
  up.
- The detail shows the local date and time of `created_at`, in full.

**The three awkward expenses**

- **A payer who is not a participant.** Task 4 supports it and `ExpenseEvent` documents it:
  someone can pay for a meal they did not eat. Line 3 lists only the allocation members, so
  the payer does not appear there, and the detail carries one extra line,
  `<payer> paid and is not sharing this expense.` The screen must not silently add the payer
  to the participant list and must not imply a share they do not have.
- **A zero cent allocation.** Task 3 produces these: 2 cents across 3 people gives 1, 1, 0,
  and `Allocation` accepts zero deliberately. That member is a participant. They appear in
  line 3's list and in the detail with their share rendered as the API's own `0.00`. The row
  is never dropped, never blanked, never dashed out, and never excluded from the count that
  feeds `and N others`, because a participant list that disagrees with the detail is a bug
  the reader cannot see.
- **One participant.** The single share equals the total, and both render. When that single
  participant is also the payer, the expense creates no debt; the feed says nothing about
  debt either way, so nothing special happens and nothing must be added to make it look
  special.
- An expense where `created_by` differs from `payer_id` shows one extra line in the detail,
  `Recorded by <display name>.`, and shows nothing when they are the same.

**Layout**

- At 320 x 568, 360 x 640 and 390 x 844, and in landscape at 844 x 390:
  `document.documentElement.scrollWidth === document.documentElement.clientWidth`, with a
  feed containing a 500 character description, a 100 character display name and a six
  participant expense.
- Every new `min-height` in `app/styles.css` is at least 44px and every new `font-size` is
  at least 16px, so `test_no_rule_sets_a_hit_area_below_forty_four_pixels` and
  `test_no_rule_sets_a_font_size_below_sixteen_pixels` pass unchanged. There is no small
  muted date text: the date is 16px like everything else.
- Every new `env()` call, if any, carries a `, 0px` fallback, so
  `test_the_layout_survives_a_collapsing_url_bar_and_a_notch` passes unchanged.
- Rows use the feed screen's existing `--accent` custom property. No new colour is added to
  `:root`.
- Any transition on the disclosure is disabled under the existing
  `@media (prefers-reduced-motion: reduce)` block, which already covers every element.
- Body and muted text meet 4.5:1 contrast, as task 8 required.
- The last row is reachable above the fixed tab bar with a hundred expenses in the list.

**The currency line**

- `feed-currency` is filled from the response's `currency` field and reads
  `Amounts in <code>.`, for example `Amounts in AUD.`
- It appears only once a successful response has arrived, and is hidden in the loading,
  empty and error states.
- The code is never invented, never abbreviated and never turned into a symbol. `web.py`
  calls `format_amount` with `symbol=False` on purpose, and the front end does not get to
  overrule that.
- No per-row currency marker. The group has exactly one currency, fixed at creation, and
  repeating it on every line is noise.

**Automated tests, in Python**

- A new file `tests/test_feed_screen.py` holds every structural assertion about `app/`.
  It uses the standard library only, locates the repo from
  `Path(__file__).resolve().parents[1]`, imports nothing from `splitwise_lite`, and adds no
  dependency.
- It asserts: the six ids exist exactly once each and sit inside `#screen-feed`;
  `feed-list` is an empty `<ul>`; the four states carry `hidden`; `feed-retry` is a
  `<button type="button">`; `feed-empty` holds an `<a href="#/add">`; the exact copy strings
  above; the banned vocabulary lists for the empty and error copy; that the feed screen no
  longer contains the word `Placeholder`; and that the `<h1>` and the lede are unchanged.
- It asserts the token bans over `app/app.js`: no `innerHTML`, `outerHTML`,
  `insertAdjacentHTML`, `document.write`, `eval(`, `new Function`, `sort(`, `reverse(`,
  `Date.now(`, `new Date()`, `pushState` or an assignment to `location.hash`, and
  `replaceState` exactly once, on the router's own line. Each of those is a ban a reader
  can verify against the file; none of them is a claim that a feature works.
  **Corrected 2026-09-06, during implementation.** This criterion previously listed
  `replaceState` among the tokens banned outright from the whole file. That cannot hold.
  Task 8's router already contains one, at `app/app.js:76`,
  `window.history.replaceState(null, '', DEFAULT_ROUTE);`, inside `route()`, which this
  task is forbidden to touch by "Refactoring the router, the gate, the notices or anything
  else on `master`" in Out of scope and by "`ROUTES` and `DEFAULT_ROUTE` in `app/app.js`
  are unchanged" in Constraints. A whole-file ban on the token therefore fails against
  `master` before this task writes a line. The other twelve tokens really are absent and
  their bans stand exactly as written. `replaceState` becomes an exact count rather than an
  absence, so "the feed adds no second one" stays falsifiable instead of being dropped, and
  the one occurrence is pinned to the router's own line so a feed-local one cannot hide
  behind the count.
- `tests/test_web_shell.py` changes by **exactly two lines, in two different functions**.
  `test_every_screen_names_the_task_that_fills_it` drops its
  `"Placeholder. Task 11 fills this with the expense feed."` assertion. The task 10 and task
  12 assertions in that function are left alone, so a concurrent branch removing the task 12
  line touches a different line of the same function.
  `test_the_nav_names_itself_and_lists_the_three_screens_in_order` narrows its anchor sweep
  from every `<a href>` in the document to the tab bar's own, which is what its comment
  about thumb reach in the nav always meant. No sibling branch touches that function.
  **Corrected 2026-09-06, during implementation.** This criterion previously said the file
  changes by **exactly one line**, the placeholder assertion alone, and the criterion below
  said no other test in it changes. That cannot hold alongside "`feed-empty` contains an
  `<a href="#/add">`" under The document region.
  `test_the_nav_names_itself_and_lists_the_three_screens_in_order` reads every anchor in the
  document rather than the nav's, and asserts the complete ordered list:
  `hrefs = [attrs["href"] for attrs in doc.find("a") if attrs.get("href")]`, then
  `assert hrefs == ["#/feed", "#/add", "#/balances"]`. `#screen-feed` sits inside `<main>`,
  ahead of `<nav>`, so the required anchor makes that list
  `['#/add', '#/feed', '#/add', '#/balances']` and the test fails. Verified by writing the
  markup and running the suite, not by reading the test. There is no escape inside the
  criteria as written: the anchor's element, its `href` and its container are each named
  verbatim, and any `<a href>` anywhere in the document joins that list.
  Two resolutions were possible, and narrowing the test was taken rather than dropping the
  anchor. The test's own comment is about which tab gets the easiest thumb, so a
  document-wide sweep was never what it meant; and an empty state that says nobody has
  recorded an expense while offering no way to record one is a dead end on the screen a new
  flat sees first. The balances screen hits the identical wall the moment it links
  anywhere, so the test is fixed once rather than the feature amputated from two screens.
  Narrowing a rule costs the incidental guard it used to give, so it gains a companion the
  way tasks 7 and 9a gave theirs one: `tests/test_feed_screen.py` asserts that every
  `<a href>` in the whole document still names one of the three routes and never leaves the
  origin, which is the part of the old sweep worth keeping.
- No other test in `tests/test_web_shell.py` changes, and none is deleted or weakened.
  `test_app_holds_exactly_the_promised_files` and `test_the_worker_precaches_exactly_the_shell`
  pass untouched, because this task adds no file under `app/`.
- Four tests are added to `tests/test_web_api.py`, inserted immediately after
  `test_a_feed_entry_carries_its_allocations_and_no_display_names`, guarding the four
  payload facts this screen is built on. They are real behavioural tests through the Flask
  test client, not source reading:
  1. An expense saved with `"description": ""` comes back with `"description": ""`: the key
     is present, the value is the empty string, and it is not `null` and not absent.
  2. An expense whose `payer_id` is not among its allocation member ids comes back that way,
     with the payer absent from `allocations`.
  3. A total of `"0.02"` split equally across three members comes back with allocations
     `"0.01"`, `"0.01"` and `"0.00"`, and the zero share is present in the array rather than
     omitted.
  4. An expense split across one member comes back with exactly one allocation whose
     `amount` equals the entry's `amount`.
- Assertions are exact: exact strings, exact ordered lists, exact key sets. No approximate
  comparison and no substring guess at prose beyond the copy strings named above, per
  `.claude/rules/testing.md`.
- No test is skipped and none is marked xfail. If something here cannot be tested, raise it
  rather than skipping it.
- `uv run python -m pytest` passes. Plain `uv run pytest` fails on this machine with an
  access-denied spawn error.

**Verified by hand, because the suite cannot see a browser**

Everything in this list is browser behaviour. None of it may be claimed by a test that
reads `app/app.js`. Record each as passed, failed or unverified.

Getting expenses into the store first: task 10 is not built, so there is no entry form.
Sign in, open the DevTools console, and call
`SplitwiseApi.addExpense({description: "...", amount: "12.50", payer_id: "...", split: {...}})`
using ids from `SplitwiseApi.members()`. Do not add a seeding script and do not commit a
fixture: task 8 banned demo data and task 18 owns the end-to-end fixture.

- Rows appear newest first, and the order matches `GET /api/expenses` read in the Network
  panel.
- Three expenses seeded at the same timestamp keep the server's tie-break order and are not
  regrouped or re-sorted.
- An expense with no description shows `No description`, and the row still names the payer,
  the amount, the participants and the date.
- An expense entered at 8am local, whose UTC timestamp falls on the previous day, shows the
  local date, not the UTC one.
- Tapping a row opens its detail; `aria-expanded` flips in the Elements panel; tapping again
  closes it. Two rows can be open at once. The URL never changes and Back still leaves the
  app.
- With VoiceOver or NVDA, the row announces as a collapsed button and the detail is
  unreachable until it is opened.
- The detail lists every participant including a `0.00` share, and the `Total` line matches
  the row's amount exactly.
- An expense whose payer is not a participant shows the extra payer line and does not list
  the payer among the participants.
- An expense described as `<img src=x onerror=alert(1)>` renders as literal text, fires no
  alert and logs nothing to the console.
- A group with no expenses shows the empty state, not an error and not a spinner, and the
  install-time console is clean.
- With the Network panel set to block `/api/expenses`, the error state appears and the empty
  state does not.
- With Network set to Offline, the offline notice covers the frame and the sign-in gate does
  not appear.
- At 320 x 568, 360 x 640, 390 x 844 and landscape 844 x 390, with the pathological fixture
  above: no horizontal scroll, nothing clipped, nothing overlapping, the last row reachable.
- Navigating Feed, Add, Feed re-requests the list. Signing out and back in re-requests it.
- Console is clean on load, after expanding several rows, and after a retry.
- On iOS Safari where a device is available, `created_at`'s six fractional digits parse and
  the date renders. Where no device is available, record it as unverified rather than as
  passing.

## Out of scope

- **Editing, voiding or deleting an expense.** Task 17 owns corrections, as an appended
  event rather than a mutation. No edit control, no swipe-to-delete, no long-press menu, and
  no `POST`, `PUT`, `PATCH` or `DELETE` from this screen. This task issues `GET` and nothing
  else, so it never needs a CSRF token.
- **The staleness signal.** Task 16 owns "days since the last expense" and "who has logged
  nothing". No relative dates, no freshness badge, no "last updated" line.
- **Any change to `src/splitwise_lite/`**, `web.py` included. The endpoints, the payload
  shape, the ordering rule and the error contract are task 9a's and are sufficient. If
  something here appears to need a new field, stop and raise it; do not add one.
- **Any change to `app/api.js` or `app/sw.js`.** `api.js` is the one network chokepoint and
  the one place that decides what a 401 means. No file is added under `app/`, so the
  precache list does not change.
- **A fourth route, a modal, a lightbox, a bottom sheet or a second screen-swapping
  mechanism.**
- **Pagination, infinite scroll, virtualisation, lazy rendering, filtering, sorting
  controls, search, date grouping headers and category grouping.** Task 9a recorded the
  no-pagination decision with its reasoning: a flat logs a few hundred expenses a year.
- **A total, a subtotal, a monthly figure, a per-person figure or any other number derived
  from more than one expense.** It would be money arithmetic in JavaScript, which task 8
  bans, and a total over an incomplete ledger is the spec's headline risk rendered in bold.
- **Anything about balances, debts, who owes who, settlements or transfers.** Tasks 12 to 15
  own those. The feed shows what was spent, not what is owed.
- **Polling, auto-refresh, live updates, websockets and optimistic rendering.**
- **Offline reading of the feed.** The service worker caches the shell and never `/api`.
- **Receipt images, attachments, notes, comments, reactions and categories.** All cut by the
  spec.
- **A JavaScript test runner, browser automation, a linter, a formatter, a date library, a
  templating library and a `package.json`.** Each is a dependency decision and the decision
  is no.
- **A seeding script, demo data or a "try it" mode.** Fake amounts on a money app are
  indistinguishable from wrong real ones.
- **Refactoring the router, the gate, the notices or anything else on `master`.** Two
  branches are editing these files.

## Constraints

- Files to create: `tests/test_feed_screen.py`. Nothing else, in either language.
- Files to modify, and only in the regions named:
  - `app/index.html`: inside `<section id="screen-feed">` only.
  - `app/app.js`: one new contiguous block, headed with the comment
    `/* --- The expense feed ------------------------------------------------- */`,
    inserted between the router section (after `route(false);`) and
    `/* --- The gate ---- */`, **plus exactly one line inside `showApp()`** calling the
    feed's own load function. Nothing else in that function changes. Function declarations
    hoist, so the block's placement does not constrain where it is called from.
  - `app/styles.css`: one new contiguous block, headed with a comment naming the feed,
    inserted immediately before the `/* The gate and the two notices */` header. No existing
    rule is edited and no custom property is added to `:root`.
  - `tests/test_web_shell.py`: exactly two lines, in two functions, named in the
    criteria. **Corrected 2026-09-06**; this read "exactly one line", which could
    not hold alongside the `<a href="#/add">` criterion. The reasoning is recorded
    in full under Automated tests, in Python.
  - `tests/test_web_api.py`: four tests inserted after
    `test_a_feed_entry_carries_its_allocations_and_no_display_names`, and nothing else.
- **Every new CSS class name begins with `feed-` or `expense-`**, and every new element id
  begins with `feed-` or `expense-`, so the sibling branch's selectors and this branch's
  cannot collide.
- The insertion points above are chosen to sit away from the end of each file, which is
  where a concurrent branch will naturally append. Keeping to them is what makes the two
  merges mechanical.
- Nothing under `src/splitwise_lite/` changes. Not `web.py`, not `events.py`, not
  `money.py`, not `store.py`, not `groups.py`. If a criterion here appears to need a
  change to the API, **stop and raise it loudly rather than editing `web.py`**: the endpoint
  contract is shared with tasks 10 and 12 and is not a screen task's to widen.
- Nothing else changes either: not `scripts/`, `pyproject.toml`, `uv.lock`,
  `plans/backlog.md`, `plans/spec.md`, `CLAUDE.md`, `README.md`, `app/api.js`,
  `app/sw.js`, `app/manifest.json`, the icons, or anything under `.claude/`. No file is
  deleted.
- **This file must not be modified either, with one exception: a statement in it that is
  provably wrong may be corrected.** Sharpening a criterion, re-scoping one or softening
  one to suit an implementation is not covered and stays forbidden. The exception is only
  for a statement that cannot be satisfied as written or that contradicts another, and the
  correction is raised and accepted before it is made, never applied unilaterally. Every
  such correction carries a dated marker saying what the file used to say, what it says now
  and why, so the next reader inherits the reasoning instead of a choice between two
  contradictory lines. Two were made on 2026-09-06 during implementation, both raised
  before any screen code was written and both accepted before they were applied: the
  `tests/test_web_shell.py` one-line change, which contradicted the `<a href="#/add">`
  criterion; and the whole-file `replaceState` ban, which task 8's router already violates.
  **Added 2026-09-06.** This bullet did not exist: the list above named "this file" among
  the files that must not change, which forbade the two corrections this file now carries.
  Task 5 reached the same contradiction and resolved it the same way.
- **No new dependency of any kind, in either language.** No `package.json`, no
  `node_modules`, no bundler, no framework, no date library, no polyfill, and no addition to
  `pyproject.toml`. Per CLAUDE.md a dependency is declared then installed with `uv sync`,
  never ad hoc, and `.claude/hooks/guard-deps.hs.sh` blocks the ad hoc route. If something
  here genuinely cannot be built without a package, stop and raise it before writing code.
- JavaScript is plain, browser-native, classic (non-module) script, matching the file it is
  going into. No `import`, no `export`, no arrow-function-only syntax the rest of the file
  does not already use, no template literal HTML.
- `ROUTES` and `DEFAULT_ROUTE` in `app/app.js` are unchanged. The feed reacts to its own
  route becoming current by listening for `hashchange` and comparing against the literal
  `'#/feed'` inside its own block. That one literal is the accepted cost of not editing
  `render()`, which the sibling branch also needs; the route-to-screen mapping itself stays
  in `ROUTES`, so task 8's constraint holds.
- The feed's load function guards on three things before doing anything: the API client has
  loaded, the hash is `#/feed`, and no request is already in flight. `app.js` loads `api.js`
  asynchronously, so a `hashchange` can fire before `api` is assigned.
- Money is a `format_amount` string from the moment it leaves `web.py` to the moment it
  reaches the DOM. No cent value is parsed, added, divided, rounded or reformatted in
  JavaScript. `toFixed`, `parseFloat`, `Math.round`, `Math.floor` and `/ 100` are already
  banned across `app/` by
  `tests/test_web_shell.py::test_no_shell_file_does_money_or_split_arithmetic`, and that test
  passes unchanged.
- The client clock is never read. No `Date.now()`, no `new Date()` with no argument, no
  elapsed-time calculation. `new Date(created_at)` is used only to render the server's
  instant in the reader's timezone, and if it yields an invalid date the row falls back to
  the first ten characters of `created_at` rather than printing `Invalid Date` or `NaN`.
  `created_at` carries six fractional digits, which is more than the ECMAScript date-time
  grammar requires engines to accept.
- All user data reaches the DOM through `textContent` or `createTextNode`. `innerHTML` and
  its relatives are banned by test.
- Tests locate repo files from `Path(__file__).resolve().parents[1]`, never from the current
  working directory. `tests/test_feed_screen.py` may re-declare the small HTML parsing helper
  rather than importing it from `tests/test_web_shell.py`; a dozen duplicated lines is
  cheaper than a shared edit to a file two branches are already touching.
- Tests run with `uv run python -m pytest`. No test is skipped or xfailed and no test binds
  a socket.
- Every non-obvious choice made here (the inline disclosure over a modal, rendering the
  array order rather than sorting, the absolute date, the `No description` literal, the
  four-state rule, the local `'#/feed'` literal) gets a one-line comment in the file that
  implements it, so the next person does not undo it by tidying.

## What the API does not give you, stated plainly

None of these blocks the task. They are recorded so nobody spends an afternoon looking for
a field that is not there, and so nobody quietly adds one to `web.py`.

- **There is no endpoint that joins expenses to names.** `GET /api/expenses` carries ids
  only, deliberately: task 9a's `_expense_view` docstring says duplicating names into every
  expense is how two spellings of one member end up on one page. Two requests is the
  design, not an oversight.
- **Two screens will each fetch the roster.** There is no shared cache and this task must
  not invent one, because a cache is shared state that two concurrent branches would both
  have to design. Two small `no-store` GETs is the accepted cost.
- **There is no per-expense endpoint.** Allocations ride along in the list payload, which is
  what makes the tap-to-open detail free.
- **503 `no_group_configured` and `ambiguous_group` reach the user as the generic offline
  notice**, because `app/api.js` routes every status at or above 500 to `onOffline`, and its
  message says the server cannot be reached rather than that the server has no group
  configured. That is wrong copy for an operator, it belongs to `api.js` and therefore to
  task 9a, and this task must not paper over it with a feed-local special case. Raise it as
  its own issue.
- **There is no pagination**, so a multi-year ledger renders every row. Recorded and
  accepted by task 9a. Do not add client-side paging or virtualisation to compensate.
- **There is no correction, void or edited flag on an expense.** Task 17 adds the concept,
  and until it does, every row in the feed is a live expense.
