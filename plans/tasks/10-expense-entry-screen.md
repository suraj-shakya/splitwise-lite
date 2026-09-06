# Task 10: Expense entry screen

**Depends on:** 3 (complete, on `master`), 6 (complete), 8 (complete), 9 (complete),
9a (complete), 9b (the JavaScript harness, complete)
**Consumed by:** 11 (the feed renders what this screen writes), 16, 17, 18

Sharpened from `plans/backlog.md` task 10, GitHub issue #11. The backlog entry stays as
written; this file is the implementable version.

Task 8 shipped `#screen-add` as a placeholder card. Task 9a shipped `POST /api/expenses`,
`GET /api/members` and the one API client in `app/api.js`. Task 9b shipped
`tests/shell_harness.mjs`, which runs the real `app/` files under Node's `vm`. This task
fills the add screen from those endpoints, adds the first behavioural coverage this screen
will ever have, and bumps the service worker so a returning user is served the shell that
contains it.

**"Log a spend in under ten seconds" is the requirement, not a nice to have.** The spec
names adoption, not arithmetic, as the risk that kills this product: "a half-filled ledger
is worse than memory, because it looks authoritative while being wrong", and the mitigation
it commits to is "expense entry must take under ten seconds from lock screen". Every
decision below that looks like a small convenience is that requirement being paid for. The
manifest already carries a home screen shortcut straight to `#/add`, so a cold launch into
this screen is a real entry path and not a curiosity.

## Two sibling branches are in flight

**#14 (transfer drill-down) edits the same three files: `app/index.html`, `app/app.js` and
`app/styles.css`. #32 edits `app/api.js`, which this task does not touch at all.**

Every criterion below is written so this work is additive inside the add screen's own
region, at insertion points chosen to sit away from #14's. Do not refactor shared code, do
not extract a shared helper, do not reorder anything you did not add, and do not wait for
either sibling. Two branches that each stay inside their own screen merge cleanly; two
branches that each tidy the router do not.

## Goal

Opening `#/add` on a phone puts the cursor in the amount field with the keypad up. Typing an
amount and tapping Save records an expense split equally across everyone in the group, paid
by the person entering it, with no other control touched. The two exceptions, sharing across
some of the group and sharing by uneven amounts, are one tap away and cost the common case
nothing. Every refusal the server can make is shown on the screen in the server's own words,
and nothing the person typed is thrown away by a failure.

## Ten seconds, and what makes it ten seconds

Three things, and each is separately checkable.

**The amount field is focused the moment the screen opens**, before the roster has been
asked for, so the keypad is up and the first character can be typed while the request is
still in the air. The screen focuses the field on entry to `#/add` and when the app frame is
first shown on that route, which is the cold launch the manifest shortcut produces. It never
touches focus while the add screen is not the current screen.

This deliberately overrides the router's own focus move. `render()` focuses the screen's
`<h1>` on a route change so a screen reader announces the new view; this is the one screen
that then moves focus on to a control. The section keeps `aria-labelledby="title-add"`, so
what a screen reader announces is the field inside a named region rather than an orphan
input. The add screen's own `hashchange` listener is registered after the router's, so the
router runs first and this runs second, which is why no change to `render()` is needed.

**Equal across everyone is the default**, and it is the default in the committed markup:
`add-mode-equal` ships with the `checked` attribute. Nothing has to load, resolve or be
chosen for the common case to be correct. When the roster arrives, that mode's member list
is every member in the order `GET /api/members` returned.

**Saving is one tap from a filled form.** With the roster loaded, a complete expense is the
amount plus one tap on Save. The payer defaults to the acting member, the description is
optional and the split needs no input at all.

The honest cost, recorded rather than hidden: at 320 x 568 with the on-screen keyboard up,
the Save control sits below the fold and the person flicks once to reach it. The form is
ordered and sized to keep that to one short scroll, and the three mode options sit in one
wrapping row rather than three stacked rows for exactly that reason. No sticky or fixed
save bar: `position: fixed` under an iOS keyboard is the class of layout this suite cannot
see and a browser gets wrong in a way that reads as broken.

## The three split modes in one form

The backlog names three modes: equal across all, equal across a subset, and uneven. The API
takes three shapes: `equal` over a member list, `weight` over integer weights, and `exact`
over amount strings. They do not line up one to one, and `split.py` says so in its own
docstring: "equal across everyone, and equal across a subset, are both `split_equally` over
the member list the caller assembles".

**The screen's three modes, and what each sends:**

| On screen | Sends | When it is used |
|---|---|---|
| `Equally` (default) | `{"mode": "equal", "member_ids": [every member, roster order]}` | Almost always |
| `Some people` | `{"mode": "equal", "member_ids": [ticked members, roster order]}` | Someone was not there |
| `Uneven amounts` | `{"mode": "exact", "amounts": {member: typed string}}` | Different people owe different amounts |

**`weight` is not exposed by this screen.** Deliberate, and stated loudly so nobody reads it
as an oversight: a weight needs explaining before anyone can use one, "I had the $18 curry
and you had the $12 one" is expressed directly in `exact`, and `split_exact`'s refusal
carries both figures so a wrong entry can be corrected, where a weight typo silently
produces a wrong but valid split. `split_by_weight` stays in the domain layer and stays
reachable through the API; exposing it is a later task's decision if anyone asks for it.

Choosing `Some people` reveals one row per member, everyone ticked, so the usual case of
"everyone except one" is a single untick. Choosing `Uneven amounts` reveals one amount field
per member, all empty. A member whose field is left empty is left out of the request
entirely, which is what "not sharing this one" means; a member who is sharing zero is typed
as a zero.

## Amounts are strings, and nothing here does arithmetic

`money.parse_amount` is the only input edge in the system and `format_amount` the only
display edge. `web.py` refuses a JSON number where an amount belongs, by name: *"must be an
amount as a JSON string, such as "12.50"; amounts are strings, never numbers"*.

* The amount field is `<input type="text" inputmode="decimal">`. **Never `type="number"`.**
  A number input hands back a value the browser has normalised and localised, exposes
  `valueAsNumber` as a float, and on iOS adds a stepper to a field that has nothing to step.
  Every one of those is the string contract being broken by the platform.
* What the field accepts is whatever the person types. The screen judges none of it. The
  grammar `parse_amount` accepts, for reference only, is: optional surrounding whitespace, an
  optional leading `$`, digits or correctly grouped digits with commas, and an optional `.`
  with at most two digits.
* What the field sends is the characters typed with surrounding whitespace removed, and
  nothing else: no comma stripped, no symbol removed, no digit padded, no decimal point
  added.
* No cent value is parsed, added, divided, rounded, compared or reformatted in JavaScript,
  in this block or anywhere else. There is no running total of the uneven shares, no
  "remaining" figure and no "you are out by" indicator computed on this screen. The suite
  already bans `toFixed`, `parseFloat`, `parseInt`, `Number(`, `Math.round`, `Math.floor`,
  `/ 100`, `Intl`, `toLocaleString`, `NumberFormat` and even the literal `0.00` across
  `app/app.js`, and those bans pass unchanged.

## Every refusal the API can make on save, and where it appears

`app/api.js` claims three of them for the whole app and this screen must not add a second
opinion on any: a 401 raises the sign-in gate, a 403 `member_not_linked` raises the
not-linked notice, and a status at or above 500 or a request that got no answer raises the
offline notice. Everything else is rejected to the caller, and the caller is this screen.

| What happened | Status, code | Where the person sees it |
|---|---|---|
| Session expired or absent | 401 `not_authenticated`, `session_invalid` | The sign-in gate, `api.js`. This screen shows nothing and clears nothing. |
| Account linked to no member | 403 `member_not_linked` | The not-linked notice, `api.js` |
| No answer, or the server could not produce one | network, 500 | The offline notice, `api.js` |
| Group missing or ambiguous | 503 `no_group_configured`, `ambiguous_group` | The offline notice, because `api.js` routes every status at or above 500 there. Wrong copy for an operator, `api.js`'s to fix, not this screen's. |
| CSRF cookie missing, stale or rewritten | 403 `csrf_failed` | `#add-error-server`, verbatim |
| A key the endpoint does not accept, an amount sent as a number, a payer or split member who is not in this group, an unknown mode | 400 `malformed_request` | `#add-error-server`, verbatim |
| Amount unparseable, over two decimals, negative, or above the storable cap | 400 `invalid_amount` | `#add-error-server`, verbatim |
| Total of zero, nobody in the split, a member named twice, exact shares that do not add up | 400 `invalid_split` | `#add-error-server`, verbatim |
| A database constraint refused the row | 409 `constraint_violated` | `#add-error-server`, verbatim. Unreachable in practice: the description is capped at 500 in the markup and the store's `CHECK` is 500. |
| Body over 64 KiB | 413 `request_too_large` | `#add-error-server`, verbatim. Unreachable with a 500 character description. |
| A success whose body is not the documented shape | none | Treated as a success, because the status said so. See "After a successful save". |

**The server's message is shown verbatim, and never replaced or reworded.** `web.py` says
the messages "were written deliberately in this repo for a person to read", and a screen that
substitutes its own copy per error code is a second error contract that drifts from the first
the day either changes. The one JavaScript literal is the fallback for a refusal that
carried no message at all, which mirrors the gate's existing `'That did not work.'`.

The refusal that matters most is `invalid_split` from `split_exact`, whose message names both
figures so the person can see by how much they are out. `tests/test_web_api.py` pins it:
`"exact amounts sum to 950, not the total 1000"`.

**Read that message again: the figures are raw cents.** A person who typed `8.00` and `1.50`
against a total of `10.00` is shown `950` and `1000`. It is shown verbatim anyway, because
the only alternatives are inventing replacement copy for one code, which is the drift above,
or dividing by a hundred in JavaScript, which is the one thing this whole codebase is built
to prevent. **Raise it as its own issue against `src/splitwise_lite/split.py` before this
task is called done, and link it from the PR.** Do not fix it here: `split.py` is shared with
task 18 and its message is pinned by a committed test. The screen's standing hint under the
uneven fields, which says the shares must add up to the total exactly, is what stops the
refusal being a surprise.

## After a successful save

**Decided here: the screen stays on `#/add`.** The form is cleared back to its defaults,
focus returns to the amount field, and a confirmation appears carrying the amount and
description **as the server echoed them in the 201 body**, with a plain anchor reading
`See it in the feed`.

The feed is the obvious destination and it is not taken, for three reasons.

1. **The app cannot navigate itself without breaking a committed test or the router.**
   `tests/test_feed_screen.py::test_the_feed_adds_no_history_entry_and_no_second_replace_state`
   asserts, over the whole of `app/app.js`, that `pushState` is absent, that nothing assigns
   `location.hash`, and that the file's only `replaceState` is the router's own line.
   Routing in this app is anchors plus `hashchange` with no click handler anywhere, by task
   8's design. A programmatic navigation would be the first of its kind, and it would land
   in a file two branches are editing.
2. **Entering three receipts in a row is a real flow**, and bouncing to the feed after each
   one costs a tab tap and a re-request every time. A cleared form with the cursor back in
   the amount field is ten seconds again.
3. **The confirmation is evidence rather than a claim.** It renders the amount and
   description the server sent back, not the text that was typed, so it says the ledger
   holds this, not that the screen tried. Anyone who wants stronger proof taps one anchor
   and the feed re-requests on entry, which task 11 guarantees.

The confirmation carries no figure the screen worked out, no "your balance is now" line, and
no claim about who owes what. It is cleared at the start of the next save and on the next
entry to the route.

**Entering the route always starts a fresh entry.** Every visit re-reads the roster, rebuilds
the payer picker and the people list, returns the mode to `Equally`, and clears the amount
and the description. Nothing is kept between visits, which is what both sibling screens
already say of themselves. The cost, stated: a person who taps Feed halfway through loses
what they had typed. The alternative is a draft, which is state, which this app keeps
nowhere.

## The service worker has never been bumped

`app/sw.js` still reads `var VERSION = 'v2';`. It precaches `index.html`, `app.js`,
`api.js` and `styles.css`, answers every navigation from that cache, and never revalidates.
**A returning user with the v2 cache is therefore served the shell as it was two tasks ago:
no feed screen, no balances screen, and no entry form however carefully this task builds
one.** The file's own comment already states the rule, "to ship a changed asset, bump
VERSION and reload", and tasks 11 and 12 both changed precached assets without doing it.

This task bumps it to `'v3'` and adds one sentence to the header comment saying when to bump
it. That is a real shipping defect that has gone unowned for two tasks, and this is the task
that ships the file it breaks. No test in the repo pins the value today, so the bump is free;
a new test pins that the number never goes backwards.

## What is tested, and how

**This is the first screen that can be properly tested, and it is tested.** Tasks 11 and 12
both shipped with no behavioural coverage, and the task 9a reviewer proved what that is worth
by mutating the balances screen four ways with every committed test still green.

So the behaviour goes in `tests/shell_harness.mjs` as real scenarios that drive the shipped
files, and only inventory and containment rules go in Python. The line, unchanged from task
11 and not negotiable: **a test may assert that a token is absent from a source file; a test
may not read source text and claim it covers rendering behaviour.**

No existing scenario changes. Nothing in the harness reads `#/add` today, and this screen
requests nothing until its own route is current, so every scenario already declared keeps its
exact request list. That is the design working: a screen that read at boot would have made
every one of the twenty-nine existing scenarios fail with "no answer was registered", which
is what happened to task 9b when tasks 11 and 12 landed.

Three things the harness records but cannot honestly prove, per issue #37, and **no scenario
below depends on any of them**: `focus()` on a hidden element is recorded as a focus anyway,
so every focus assertion here is made while the add screen is the visible screen and is
paired with one that asserts focus moved elsewhere when it is not; the session cache is
otherwise only ever asserted null, so the acting-member default is asserted through the
request body the screen sends rather than through the cache; and `aria-current` is checked
for presence rather than value, which this screen never touches.

## Acceptance criteria

**The document region**

- Every change to `app/index.html` is inside
  `<section class="screen screen--add" id="screen-add" aria-labelledby="title-add" hidden>`.
  No other element in the document is added, removed, reordered or edited, and the section
  keeps its `hidden` attribute and its `aria-labelledby`.
- `<h1 class="screen-title" id="title-add" tabindex="-1">Add</h1>` and
  `<p class="lede">Record a new expense and choose how it is shared.</p>` are unchanged,
  byte for byte.
- The placeholder `<div class="card">`, its `<p class="marker">` and its `<ul class="notes">`
  are removed. The word `Placeholder` appears nowhere in the document.
- The section gains exactly these ids, each present exactly once in the whole document, and
  no others: `add-currency`, `add-currency-code`, `add-form`, `add-amount`,
  `add-description`, `add-payer`, `add-mode-equal`, `add-mode-some`, `add-mode-exact`,
  `add-hint-some`, `add-hint-exact`, `add-people`, `add-roster-busy`, `add-roster-error`,
  `add-roster-retry`, `add-empty-roster`, `add-submit`, `add-status`, `add-saving`,
  `add-saved`, `add-saved-amount`, `add-saved-description`, `add-error`, `add-error-amount`,
  `add-error-roster`, `add-error-server`.
- `add-form` is a `<form novalidate>`. `novalidate`, because every refusal this form can make
  is one the server owns, and a browser bubble in the browser's own words is a second error
  contract.
- `add-amount` is `<input type="text" inputmode="decimal">` with `autocomplete="off"`. The
  string `type="number"` appears nowhere in `app/index.html`.
- `add-description` is an `<input type="text">` carrying `maxlength="500"`, matching the
  store's `CHECK (length(description) <= 500)`, so that constraint is unreachable from this
  screen.
- `add-payer` is a `<select>` and is empty in the committed document: no `<option>`, no
  sample name.
- `add-mode-equal`, `add-mode-some` and `add-mode-exact` are three `<input type="radio">`
  sharing one `name`. `add-mode-equal` carries `checked` in the committed document and the
  other two do not.
- `add-people` is empty in the committed document. No row, no sample member, no template
  markup.
- Every field has a `<label>` bound to it, either by `for` or by wrapping it. The split
  radios sit in a `<fieldset>` with a `<legend>`.
- `add-currency`, `add-hint-some`, `add-hint-exact`, `add-roster-busy`, `add-roster-error`,
  `add-empty-roster`, `add-saving`, `add-saved`, `add-error`, `add-error-amount`,
  `add-error-roster` and `add-error-server` each carry the `hidden` attribute in the
  committed document, so the first paint shows one state at most.
- `add-status` carries `role="status"` and holds `add-saving` and `add-saved`. `add-error`
  carries `role="alert"` and holds the three error children.
- `add-roster-retry` is a `<button type="button">` inside `add-roster-error`.
  `add-submit` is a `<button type="submit">` inside `add-form`.
- `add-saved` contains exactly one `<a href="#/feed">`. It is a plain anchor: routing is
  anchors plus `hashchange` per task 8, and no click handler is registered on it.
- The committed add markup contains no amount, no currency symbol, no member name, no
  percentage and no example figure.
  `tests/test_web_shell.py::test_no_screen_shows_invented_data` passes unchanged, which means
  the document text contains none of `$`, `£`, `€`, `%`, nothing matching `\d+\.\d\d`, and
  none of the words `Loading`, `loading`, `skeleton` or `spinner`. A placeholder attribute of
  `0.00` on the amount field would fail that test and is banned anyway by the literal ban on
  `0.00` across `app/app.js`.
- `tests/test_web_shell.py::test_each_screen_is_a_section_with_a_focusable_heading`,
  `test_only_the_default_screen_starts_visible`,
  `test_every_element_the_router_reaches_for_exists_in_the_document`,
  `test_the_gate_is_not_a_fourth_route`, `test_the_router_loads_as_a_classic_script` and
  `test_every_nav_item_carries_a_text_label` all pass unchanged. No `<img>` is added.
- `tests/test_feed_screen.py::test_every_anchor_names_one_of_the_three_routes` passes
  unchanged: the one anchor added names `#/feed`, which `ROUTES` holds, and leaves no origin.

**The copy, exactly**

- Labels: `Amount`, `Description (optional)`, `Paid by`. Legend: `Split`. Radio labels:
  `Equally`, `Some people`, `Uneven amounts`. Submit: `Save`. Retry: `Try again`.
- `add-currency` reads `Amounts are in ` then `add-currency-code` then `.`
- `add-hint-some` reads exactly: `Untick anyone who is not sharing this expense.`
- `add-hint-exact` reads exactly: `These shares must add up to the total exactly. Leave
  someone blank to keep them off this expense.`
- `add-roster-busy` reads exactly: `Fetching the people in this group.`
- `add-roster-error` reads exactly: `The people in this group did not arrive. Nothing you
  have typed is lost.`
- `add-empty-roster` reads exactly: `This group has no members yet, so there is nothing to
  record.`
- `add-error-amount` reads exactly: `Type an amount before saving.`
- `add-error-roster` reads exactly: `The people in this group have not arrived yet, so this
  cannot be saved.`
- `add-saving` reads exactly: `Saving this expense.`
- `add-saved`'s line reads `Saved ` then `add-saved-amount` then `add-saved-description`, and
  its anchor reads `See it in the feed`.
- No copy on this screen claims anything about balances, debts or settlement. It contains
  none of these, case-insensitively: `settled`, `balanced`, `square`, `owes`, `owed`, `debt`,
  `up to date`, `all clear`. A test asserts the list.
- No copy promises the ledger is complete or current, and none says the expense is shared
  fairly, correctly or evenly beyond naming the mode.

**Opening the screen**

- Entering `#/add` focuses `add-amount`, and does so before `GET /api/members` is issued.
- The app frame being shown on `#/add` after a successful session check focuses `add-amount`
  too, which is the cold launch the manifest shortcut `./#/add` produces.
- The screen touches focus at no other time. Leaving `#/add` for another route leaves focus
  wherever the router put it.
- Entering the route clears `add-amount` and `add-description`, sets `add-mode-equal`'s
  `checked` to true and the other two radios' to false, hides `add-saved`, hides all three
  error children, and re-reads the roster.
- `ROUTES` and `DEFAULT_ROUTE` are unchanged. The block reacts to its own route by listening
  for `hashchange` and comparing against the literal `'#/add'` inside its own block.
- The block guards on three things before reading anything: the API client has loaded, the
  hash is `'#/add'`, and no roster read is already in flight.

**The roster**

- The roster is read through `window.SplitwiseApi.members()` and through nothing else.
  `app/app.js` still contains no `fetch`, no `/api`, no `XMLHttpRequest`, no `EventSource`
  and no `WebSocket`, so `test_only_the_api_client_calls_the_back_end` and
  `test_the_narrowed_rule_still_bites` pass unchanged. Comments count: neither the word
  `fetch` nor the string `/api` may appear in a comment either.
- While the request is in flight, `add-roster-busy` is shown and `add-payer` and `add-people`
  are empty. `add-amount` and `add-description` stay usable and focused throughout: typing
  while the roster loads is the whole point.
- On success with one or more members, `add-payer` gains one `<option>` per member, in the
  order the payload returned, with the display name as text and the member id as the value.
  Nothing is sorted, reversed, filtered or deduplicated.
- The acting member's option reads the display name followed by ` (you)`, matching the
  balances screen's suffix. The suffix is this block's own literal; no helper is shared
  across regions.
- The default payer is applied by assigning `add-payer`'s `value`, never by relying on a
  browser to select the first option and never by setting `selected` on an option. The
  default is the acting member from `window.SplitwiseApi.cachedSession()`, or the first
  member in roster order when the cache holds no member.
- On success with an empty `members` array, `add-empty-roster` is shown, the payer picker and
  the people list stay empty and Save sends nothing. This state is reachable through a
  half-finished `setup_group.py` run, which is why the balances screen has one too.
- On a rejected request, or a 200 whose body is not the documented shape,
  `add-roster-error` is shown with its retry button, and `add-amount` and `add-description`
  keep exactly what was typed. 401, 403 `member_not_linked`, a network failure and any 5xx
  are `api.js`'s and are already covering the whole frame; this screen does not inspect the
  status code and shows its own notice behind that curtain.
- `add-roster-retry` re-issues the read and returns to the in-flight state while it runs. A
  retry that succeeds fills the picker and the people list and still leaves the typed amount
  and description untouched.
- The roster is held in one variable for the life of the visit, because switching split modes
  rebuilds the people list from it and a second read would be a second request for data the
  screen already has. It is re-read on every entry to the route and reaches no browser
  storage. Nothing else from a response is kept: `test_the_feed_keeps_nothing_in_browser_storage`
  passes unchanged.

**The three split modes**

- The current mode is held in one variable, set by a `change` listener registered on each
  radio individually. The screen never scans the three radios to discover which is checked,
  and registers no listener on a container: nothing here relies on event bubbling.
- `Equally`: `add-people`, `add-hint-some` and `add-hint-exact` are all hidden. The request
  carries every member in the roster.
- `Some people`: `add-people` shows one row per member, each an `<input type="checkbox">`
  inside a `<label>` carrying the display name, every one ticked. `add-hint-some` is shown.
- `Uneven amounts`: `add-people` shows one row per member, each an `<input type="text"
  inputmode="decimal">` inside a `<label>` carrying the display name, every one empty.
  `add-hint-exact` is shown.
- Switching modes rebuilds `add-people` from the held roster. Ticks and typed shares do not
  survive a mode switch; that is accepted and is not worked around with kept state.
- Every member name reaches the DOM through `textContent` or `createTextNode`. A member
  called `<img src=x onerror=alert(1)>` renders as those literal characters.
- A member id the payload spelled `__proto__` cannot reach `Object.prototype`: any map keyed
  by member id is built with `Object.create(null)` or read with
  `Object.prototype.hasOwnProperty.call`.
- The screen never exposes `weight`. The string `weight` appears nowhere in `app/app.js`.

**Saving: the request**

- The expense is sent through `window.SplitwiseApi.addExpense()` and through nothing else.
- The body carries exactly four keys, in this order: `description`, `amount`, `payer_id`,
  `split`. It never names `currency`, `id`, `created_at`, `created_by` or `now`: `web.py`
  refuses an unrecognised key by name, and those five are the server's to decide.
- `description` is the field's value with surrounding whitespace removed, and is `""` when
  the field is empty. It is never omitted and never `null`.
- `amount` is the field's value with surrounding whitespace removed and nothing else changed.
- `payer_id` is the member id `add-payer` currently holds.
- `split` is one of the three shapes in the table above, with member ids in roster order and,
  for `exact`, one key per member whose field is non-empty after trimming.
- Two refusals the screen makes itself, both sending no request: an empty `add-amount` shows
  `add-error-amount` and returns focus to the field, and a save before the roster has arrived
  or with an empty roster shows `add-error-roster`. Both are checks on whether there is
  anything to send, not judgements of an amount.
- Everything else goes to the server. A split with nobody in it, a zero total, an amount with
  three decimals and a comma used as a decimal point are all sent as typed and refused there,
  because a rule implemented twice is a rule that drifts.
- While the save is in flight: `add-submit` is disabled, `add-saving` is shown, and the
  fields stay enabled and keep their values so the person can see what was sent. A second
  submit while one is in flight is refused by the screen's own in-flight flag and sends no
  second request. The disabled attribute is an affordance, not the guard.

**Saving: every refusal**

- Any rejected save shows `add-error-server` carrying `error.message` exactly as the server
  sent it, with no rewording, no truncation, no added punctuation and no per-code
  substitution. A refusal that carried no message shows the one JavaScript literal
  `That did not save.`
- `invalid_split` from `split_exact` is shown verbatim, including its raw cent figures. The
  wording of that message is raised as its own issue against `src/splitwise_lite/split.py`
  and linked from this task's PR. It is not fixed here and it is not reformatted here.
- A refused save changes nothing else: the amount, the description, the payer, the mode and
  every per-member value stay exactly as they were, `add-saved` stays hidden, the hash does
  not change, and `add-submit` is enabled again.
- At most one of `add-error-amount`, `add-error-roster` and `add-error-server` is ever
  visible, and all three are hidden at the start of every submit.
- 401, 403 `member_not_linked`, a 5xx and a request that got no answer are `api.js`'s three
  screens, reused unchanged. This block registers none of `onUnauthenticated`, `onNotLinked`
  or `onOffline`, and writes no message of its own for any of them. On a save that got no
  answer the form keeps everything typed, which is what makes the offline notice's standing
  promise, "nothing you have recorded is lost", true on this screen.

**Saving: success**

- A resolved save shows `add-saved`, clears `add-amount` and `add-description`, returns the
  mode to `Equally` with all three radios' `checked` set explicitly, rebuilds `add-people`,
  reapplies the default payer, hides every error child, and focuses `add-amount`.
- `add-saved-amount` carries `expense.amount` from the response and `add-saved-description`
  carries ` for ` followed by `expense.description` when that is a non-empty string, and is
  empty otherwise. No description is invented for an expense that has none.
- Nothing in the confirmation is taken from what was typed. The screen echoes the server, or
  it says nothing.
- The screen does not navigate. `window.location.hash` is unchanged, no history entry is
  added, and `app/app.js` still contains no `pushState`, no assignment to `location.hash`,
  and exactly one `replaceState`, the router's own line.
- A success whose body is not the documented shape is still a success: the status said the
  expense was recorded, so the form is cleared and the confirmation is shown with an empty
  figure rather than an error claiming it did not save.
- The roster is not re-read after a save, and no other request is issued.
- The confirmation is cleared at the start of the next submit and on the next entry to the
  route. It is never cleared on a timer: `setTimeout` and `setInterval` are banned across
  `app/app.js` and stay banned.

**The service worker**

- `app/sw.js` reads `var VERSION = 'v3';`.
- Its header comment gains one sentence: bump `VERSION` in the same commit as any change to a
  file in `SHELL`, because the shell is answered from the cache and never revalidated, so a
  returning user is served the old files until the cache name changes.
- `SHELL` is unchanged: this task adds no file under `app/`, so
  `test_the_worker_precaches_exactly_the_shell` and `test_every_precache_entry_resolves_to_a_file`
  pass unchanged, and so does `test_app_holds_exactly_the_promised_files`.
- Nothing else in `app/sw.js` changes: not the install, activate or fetch handler, and not
  the `/api` bypass.

**Layout**

- At 320 x 568, 360 x 640 and 390 x 844, and in landscape at 844 x 390, with a six member
  roster where one display name is 100 characters:
  `document.documentElement.scrollWidth === document.documentElement.clientWidth`.
- Every new `min-height` in `app/styles.css` is at least 44px and every new `font-size` is at
  least 16px, so `test_no_rule_sets_a_hit_area_below_forty_four_pixels` and
  `test_no_rule_sets_a_font_size_below_sixteen_pixels` pass unchanged. Every input, the
  select, every checkbox row and both buttons clear 44px.
- Every new `env()` call, if any, carries a `, 0px` fallback, so
  `test_the_layout_survives_a_collapsing_url_bar_and_a_notch` passes unchanged.
- A long display name wraps rather than being clipped or ellipsised: the people rows set
  `overflow-wrap: break-word` and no new rule sets `text-overflow` or `overflow: hidden`. The
  `<select>` is full width and never pushes the page wider than the viewport.
- The screen uses `.screen--add`'s existing `--accent`. No custom property is added to
  `:root` and no existing rule is edited.
- The block adds no `animation`, no `transition` and no `@keyframes`, so the reduced-motion
  block has nothing new to switch off.
- No new `$`, `£` or `€` in any of `app/index.html`, `app/styles.css` or `app/app.js`, in
  markup, copy, CSS `content` or JavaScript, so `test_no_shell_file_prints_a_currency_symbol`
  passes unchanged.
- Body and muted text meet 4.5:1 contrast, as task 8 required. The ticked and unticked states
  and the selected mode are told apart by more than colour.

**Automated tests: the harness**

- `tests/shell_harness.mjs` gains its fixtures and its scenarios, and **no existing scenario
  is edited, reordered or deleted.** New scenarios are appended as one contiguous block at
  the end of `SCENARIOS`.
- `element()` gains exactly two reflected properties, `checked` and `type`, each backed by its
  attribute the way `hidden` already is, with a comment saying why: the guarded proxy refuses
  a set of any property the stub does not define, and this screen creates checkboxes and text
  inputs at run time. A radio that ships with the `checked` attribute therefore reads as
  checked. No other change is made to the stub.
- A `created(payload)` response fixture is added beside `ok()`, answering status 201, because
  that is what `POST /api/expenses` returns.
- Fixtures: a three member roster (`mem-1` Sam, `mem-2` Ali, `mem-3` Jo), a one member
  roster, and one 201 body in `_expense_view` shape.
- Every new scenario declares its full ordered request list through `expectRequests`, with the
  exact body of every request that changes something, and declares no console output.
- Scenarios that start on the add screen call `startAt('#/add')` before booting, so their
  request list is `GET /api/session` then `GET /api/members` and no feed or balances read is
  involved.
- The scenarios, each named as a sentence, each added to `SCENARIOS` in
  `tests/test_shell_behaviour.py` under a new `# The add screen` comment appended at the end
  of that list:

  1. `opening_add_focuses_the_amount_field_and_reads_the_roster`: boot at `#/add`; an
     `onRequest` watcher records that `add-amount` was already the focused element and
     `add-roster-busy` was visible when `GET /api/members` went out; afterwards the busy line
     is hidden, `add-payer` holds three options in roster order carrying the display names
     with ` (you)` on the acting member, `add-people` is empty, `add-mode-equal` is checked
     and `add-currency-code` reads `AUD`.
  2. `the_add_screen_takes_focus_only_while_it_is_the_current_screen`: boot at `#/add`, then
     go to `#/feed`; the focused element is `title-feed`, not the amount field.
  3. `an_amount_and_one_tap_records_an_equal_split_across_everyone`: type `12.50`, submit,
     and the one POST body is exactly
     `{"description":"","amount":"12.50","payer_id":"mem-1","split":{"mode":"equal","member_ids":["mem-1","mem-2","mem-3"]}}`.
  4. `unticking_someone_sends_an_equal_split_over_the_rest`: switch to `Some people`, untick
     the second row, submit, and `member_ids` is `["mem-1","mem-3"]`.
  5. `uneven_amounts_are_sent_as_strings_and_the_blanks_are_left_out`: switch to
     `Uneven amounts`, type in the first and third rows only, submit, and `split` is
     `{"mode":"exact","amounts":{"mem-1":"8.00","mem-3":"2.00"}}`.
  6. `shares_that_do_not_add_up_show_the_resolvers_own_message_and_keep_the_draft`: a 400
     `invalid_split` carrying `exact amounts sum to 950, not the total 1000`;
     `add-error-server` reads exactly that, `add-saved` is hidden, the amount field and both
     typed shares are unchanged, and `add-submit` is enabled again.
  7. `saving_with_no_amount_typed_asks_for_one_and_sends_nothing`: submit an empty form;
     `add-error-amount` is visible, `add-error-server` is hidden, focus is on `add-amount`,
     and the request list holds no POST at all.
  8. `a_successful_save_clears_the_form_and_confirms_from_the_response`: a 201 whose echo
     differs from what was typed; `add-saved-amount` carries the server's string,
     `add-saved-description` carries the server's description, both fields are empty,
     `add-mode-equal` is checked and the other two are not, focus is on `add-amount`, the
     hash is still `#/add`, and `pushStates` and `replaceStates` are both empty.
  9. `a_stale_form_refused_by_the_server_says_so_on_the_screen`: a 403 `csrf_failed`, which
     `announce()` passes through; the screen shows its message verbatim and the gate and both
     notices stay hidden.
  10. `the_save_control_is_disabled_while_the_save_is_in_flight`: observed through an
      `onRequest` watcher, asserted after settling, with `add-saving` visible at that moment
      and hidden afterwards.
  11. `a_second_submit_while_the_first_is_in_flight_sends_one_request`: the `onRequest`
      watcher re-invokes the form's own submit listener synchronously through the stub's
      `listeners` map; the request list holds exactly one POST. This pins the screen's
      in-flight flag, not a disabled control refusing a click, which stays browser-only.
  12. `a_roster_that_does_not_arrive_offers_a_retry_and_keeps_what_was_typed`: a 404 on the
      first `GET /api/members`, an amount typed, `add-roster-error` visible, a submit that
      shows `add-error-roster` and sends no POST, then a retry that succeeds and leaves the
      typed amount in place with the picker filled.
  13. `a_group_with_one_member_still_records_an_expense`: the one member roster; the split
      carries `["mem-1"]` and no copy anywhere says anything special about it.
  14. `a_group_with_no_members_says_so_and_saves_nothing`: `{"members": []}`;
      `add-empty-roster` is visible, the picker and people list are empty, and a submit sends
      no POST.
  15. `a_save_that_gets_no_answer_never_says_it_saved`: `fetch` rejects; the offline notice is
      up, `add-saved` is hidden, `add-error-server` is hidden, and the amount and description
      still hold what was typed behind the curtain.

- `tests/test_shell_behaviour.py::test_the_harness_reports_exactly_the_declared_scenarios`
  passes with the new names appended, and `test_the_service_worker_registration_branch_is_never_entered`
  passes unchanged: this block registers a `hashchange` listener and no `load` listener.
- Both mutant tests still pass unchanged. Neither mutant's anchor is touched by this task.

**Automated tests: Python**

- A new file `tests/test_add_screen.py` holds every structural assertion. Standard library
  only, repo located from `Path(__file__).resolve().parents[1]`, imports nothing from
  `splitwise_lite`, adds no dependency, and may re-declare the small HTML parsing helper
  rather than importing it from another test file.
- It asserts: the exact id set inside `#screen-add`; that each of those ids appears exactly
  once in the whole document; which elements ship `hidden`; the radio group's shared `name`
  and that only `add-mode-equal` ships `checked`; that `add-payer` and `add-people` ship
  empty; `maxlength="500"` on the description; `inputmode="decimal"` on the amount and no
  `type="number"` in the document; the exact copy strings; the banned vocabulary list; that
  `add-saved` holds exactly one anchor and it names `#/feed`; that the heading and lede are
  unchanged; and that no `Placeholder`, `class="marker"` or `class="notes"` survives in the
  section.
- It asserts these bans over `app/app.js`, each falsifiable by opening the file: `weight`,
  `valueAsNumber`, `selectedIndex`, `defaultValue`. The existing bans in
  `tests/test_feed_screen.py` and `tests/test_web_shell.py` already cover `innerHTML` and its
  relatives, `sort(`, `reverse(`, `new Date()`, `Date.now(`, `pushState`, an assignment to
  `location.hash`, `setTimeout`, `setInterval`, `requestAnimationFrame`, browser storage, the
  money tokens and the literal `0.00`, and every one of them passes unchanged.
- It asserts over the add region of `app/app.js`, sliced from its banner comment to the gate's
  banner comment, that none of `onUnauthenticated`, `onNotLinked` or `onOffline` appears.
- It asserts `app/sw.js`'s `VERSION` matches `^v([0-9]+)$` with a number of at least 3, so the
  bump is pinned and a future bump needs no edit here.
- `tests/test_web_shell.py` changes by exactly one deletion:
  `test_every_screen_names_the_task_that_fills_it` is removed, function and comment, because
  its last remaining assertion is the task 10 placeholder this task deletes and a test with no
  assertions left is worse than no test. Tasks 11 and 12 each removed their line from it; this
  task removes the function. Nothing replaces it. No other test in that file changes and none
  is weakened.
- **No test in `tests/test_web_api.py` changes and none is added.** Everything this screen is
  built on is already pinned there: `test_the_created_expense_comes_back_in_the_same_shape_as_a_feed_entry`,
  `test_an_unusable_amount_carries_the_domain_layers_own_message`,
  `test_exact_amounts_that_do_not_add_up_report_both_figures`,
  `test_an_empty_split_is_refused_by_the_resolver`,
  `test_a_payer_who_is_not_a_member_is_refused_by_name`,
  `test_a_split_naming_someone_outside_the_group_is_refused_by_name` and the parametrized
  refusal of an amount sent as a JSON number.
- Assertions are exact: exact strings, exact ordered lists, exact key sets, exact request
  bodies. No approximate comparison and no substring guess at prose, per
  `.claude/rules/testing.md`.
- No test is skipped and none is marked xfail. If something here cannot be tested, raise it
  rather than skipping it.
- `uv run python -m pytest` passes. Plain `uv run pytest` fails on this machine with an
  access-denied spawn error.

**Verified by hand, because the suite cannot see a browser**

Record each as passed, failed or unverified.

- **The service worker bump, which is the point of it.** With the shipped `v2` worker
  installed and the app open, confirm the old shell is being served. Deploy this branch,
  reload twice, and confirm Cache Storage holds exactly one cache named
  `splitwise-lite-shell-v3`, that the entry form is on screen, and that the feed and balances
  screens appear for the first time on that device.
- Opening Add raises the keypad with a decimal separator, and the first character typed lands
  in the amount field. On iOS, programmatic focus may not raise the keyboard without a user
  gesture; record what actually happens rather than what should.
- From the home screen shortcut, a cold launch lands on Add with the amount field focused.
- Typing an amount and tapping Save records the expense, and the row appears at the top of the
  feed after tapping `See it in the feed`.
- At 320 x 568 with the keyboard up, Save is reached with one short scroll and nothing is
  clipped or overlapped.
- A 100 character display name renders in the payer picker and in the people rows without
  pushing the page into a horizontal scroll, at all four sizes.
- Uneven amounts that do not add up show the server's message; note in the record that its
  figures are in cents, and link the issue raised for it.
- A description of exactly 500 characters saves; the field refuses the 501st character.
- An expense described as `<img src=x onerror=alert(1)>` renders as literal text in the
  confirmation and in the feed, fires no alert and logs nothing.
- With the Network panel set to block `POST /api/expenses`, the offline notice covers the
  frame, the sign-in gate does not appear, and reloading returns to an empty form. Record the
  known hole: the offline notice has no way back, so a draft behind it is unreachable without
  a reload. That belongs to `api.js` and task 9a, not here.
- With VoiceOver or NVDA: entering Add announces the amount field inside the Add region, the
  mode radios announce as a group with a legend, and the confirmation is announced when it
  appears.
- Console is clean on load, after switching modes three times, after a refused save and after
  a successful one.

## Out of scope

- **Weight splits and percentage splits.** `split_by_weight` stays in the domain layer,
  unexposed. No percentage anywhere: the API has no percentage mode and inventing one in
  JavaScript is split maths in the browser.
- **Any running total, remaining figure, per-person preview or "what this does to the
  balances" line.** All four are money arithmetic in JavaScript, which task 8 bans and this
  file bans again.
- **Editing, correcting, voiding or deleting an expense.** Task 17 owns corrections as
  appended events. This screen only ever issues `POST /api/expenses`.
- **A date or time field.** `created_at` comes from the server's single clock read per
  request, and `_create_expense` refuses any key it does not name, so backdating is not
  possible and no control may pretend otherwise.
- **Adding, renaming or removing a member from this screen.** There is no endpoint, and task 9
  decided members come from an operator's list.
- **A draft, an autosave, an offline queue, an undo or a "keep entering" toggle.** Offline
  entry is cut from v1 by the spec.
- **Anything about balances, who owes who, settlements or transfers.**
- **A fourth route, a modal, a bottom sheet, a lightbox or a second screen-swapping
  mechanism.** The entry form fills the existing section, like the two screens before it.
- **Any change to `src/splitwise_lite/`.** The endpoint, the three split shapes, the string
  money contract and the error family are task 9a's and are sufficient. If a criterion here
  appears to need a new field or a new status, **stop and raise it loudly rather than editing
  `web.py`**.
- **Any change to `app/api.js`.** #32 is editing it concurrently, it is the one network
  chokepoint, and `addExpense` already exists and already does the right thing.
- **Refactoring the router, `ROUTES`, the gate, the notices, the feed region or the balances
  region.** Two branches are editing these files.
- **Fixing `split_exact`'s message, `api.js`'s 503 copy, or the offline notice's missing way
  back.** All three are raised as their own issues.
- **Receipt photos, attachments, categories, tags, notes, comments, recurring expenses and
  templates.** All cut by the spec.
- **A JavaScript test runner, a framework, a bundler, a date library, a form library, a
  validation library, browser automation and a `package.json`.** Each is a dependency decision
  and the decision is no.
- **A seeding script, demo data or a "try it" mode.** Fake amounts on a money app are
  indistinguishable from wrong real ones.

## Constraints

- Files to create: `tests/test_add_screen.py`. Nothing else, in either language.
- Files to modify, and only in the regions named:
  - `app/index.html`: inside `<section id="screen-add">` only.
  - `app/app.js`: **one new contiguous block, headed
    `/* --- The expense entry form ------------------------------------------- */`,
    inserted immediately before the `/* --- The gate ---- */` header**, plus **exactly one
    line appended to the end of `showApp()`** calling this block's own entry function.
    Nothing else in that function changes. Function declarations hoist, so the block's
    placement does not constrain where it is called from.
  - `app/styles.css`: **one new contiguous block, headed with a comment naming the add
    screen, inserted immediately before the `/* Bottom nav ---` header.** No existing rule is
    edited and nothing is added to `:root`.
  - `app/sw.js`: the `VERSION` line and one sentence in the header comment. Nothing else.
  - `tests/shell_harness.mjs`: fixtures and scenarios appended at the end of `SCENARIOS`, and
    two new reflected properties inside `element()`. No existing scenario is edited.
  - `tests/test_shell_behaviour.py`: the new scenario names appended to `SCENARIOS`.
  - `tests/test_web_shell.py`: the one deletion named in the criteria.
- **Neither the JavaScript block nor the CSS block may be appended at the end of its file, and
  this is not a style preference.** `tests/test_web_shell.py` defines `balances_region()` as
  `app/app.js` from `/* --- The balances screen ---` **to the end of the file**, and
  `balances_styles()` as `app/styles.css` from `/* Balances ---` **to the end of the file**.
  Anything appended after those banners is read as task 12's work and is held to task 12's
  bans, which include no `addEventListener('click'`, no `createElement('button')`, no
  `tabindex`, no `setAttribute('role'`, no `setTimeout`, and every CSS selector starting
  `.balances-`. An add screen appended at the end of either file fails seven committed tests
  for reasons that name the balances screen. The insertion points above sit before both
  banners, which also keeps them away from #14, whose changes are inside the balances region
  and at the end of the stylesheet.
- Every new element id and every new CSS class begins with `add-`, and every new JavaScript
  identifier in the block begins with `add`, so this branch's selectors and #14's cannot
  collide.
- Nothing under `src/splitwise_lite/` changes. Not `web.py`, not `split.py`, not `money.py`,
  not `events.py`, not `store.py`. **If a criterion here appears to need an API change, stop
  and raise it loudly rather than editing the API**: that contract is shared with tasks 11,
  12, 13 and 18 and is not a screen task's to widen.
- Nothing else changes either: not `app/api.js`, not `app/manifest.json`, not the icons, not
  `scripts/`, `pyproject.toml`, `uv.lock`, `plans/backlog.md`, `plans/spec.md`, `CLAUDE.md`,
  `README.md`, or anything under `.claude/`. No file is deleted.
- **No new dependency of any kind, in either language.** No `package.json`, no `node_modules`,
  no bundler, no polyfill, and no addition to `pyproject.toml`. Per CLAUDE.md a dependency is
  declared and then installed with `uv sync`, never ad hoc, and `.claude/hooks/guard-deps.hs.sh`
  blocks the ad hoc route. If something here genuinely cannot be built without a package, stop
  and raise it before writing code.
- JavaScript is plain, browser-native, classic (non-module) script, matching the file it goes
  into: no `import`, no `export`, no template literal markup, and no syntax the rest of the
  file does not already use.
- Neither the word `fetch` nor the string `/api` may appear anywhere in `app/app.js`,
  comments included: two committed tests ban both across the whole file, and a comment naming
  an endpoint path is the easy way to fail them.
- The literal `0.00` may not appear anywhere in `app/app.js` either, copy and comments
  included.
- Listeners are registered directly on the elements they react to. No delegation from a
  container: nothing here relies on bubbling, which is also what makes each control drivable
  from a harness scenario.
- All user data reaches the DOM through `textContent` or `createTextNode`.
- Money is a string from the moment it leaves the field to the moment it reaches `web.py`, and
  a `format_amount` string from the moment it leaves `web.py` to the moment it reaches the
  DOM. Nothing in between parses, adds, divides, rounds, pads or reformats it.
- The client clock is never read: no `Date.now()`, no `new Date()` with no argument, no
  elapsed time. This screen renders no date at all.
- Tests locate repo files from `Path(__file__).resolve().parents[1]`, never from the working
  directory, and run with `uv run python -m pytest`.
- The three now-unused shared rules `.card`, `.marker` and `.notes` in `app/styles.css` are
  deleted with the placeholder they were written for, since no markup references them once
  this task lands and no sibling branch touches those lines.
  `tests/test_web_shell.py::test_the_balances_placeholder_is_gone` already asserts two of
  those class names are gone from the balances section and keeps passing.
- Every non-obvious choice made here gets a one-line comment where it is implemented, so the
  next person does not undo it by tidying: focusing the field over the router's heading, the
  default payer coming from the cached session, `equal` covering two of the three screen
  modes, the empty uneven field meaning "not sharing", showing the server's message verbatim,
  staying on `#/add` after a save, and the local `'#/add'` literal.
- **This file must not be modified either, with one exception: a statement in it that is
  provably wrong may be corrected.** Sharpening a criterion, re-scoping one or softening one
  to suit an implementation is not covered and stays forbidden. The exception is only for a
  statement that cannot be satisfied as written or that contradicts another, and the
  correction is raised and accepted before it is made, never applied unilaterally. Every such
  correction carries a dated marker saying what the file used to say, what it says now and
  why, so the next reader inherits the reasoning instead of a choice between two contradictory
  lines. Tasks 5, 9, 9b and 11 all set this precedent.

## What the API does not give you, stated plainly

None of these blocks the task. **The API needs no change for this screen**, and these are
recorded so nobody spends an afternoon looking for a field that is not there, and so nobody
quietly adds one to `web.py`.

- **`POST /api/expenses` decides five things and refuses to be told them.** `id`,
  `created_at`, `created_by`, `currency` and the group are the server's, and naming any of
  them is a 400 by name. There is therefore no way to backdate an expense, and no control on
  this screen may imply one.
- **`GET /api/members` carries no currency.** The group's currency code comes from the session
  view the client already holds, which costs no extra request. If the cache holds none, the
  currency line stays hidden rather than guessing.
- **There is no roster cache shared between screens.** The feed, the balances screen and this
  one each read `GET /api/members` on entry. Three small `no-store` GETs is the accepted cost,
  recorded by task 11, and this task must not invent the shared cache: a cache is state that
  two concurrent branches would both have to design.
- **`split_exact`'s refusal reports raw cents**, `"exact amounts sum to 950, not the total
  1000"`, pinned by `tests/test_web_api.py::test_exact_amounts_that_do_not_add_up_report_both_figures`.
  A user who typed dollars is shown cents. Shown verbatim here and raised as its own issue;
  reformatting it in JavaScript is banned.
- **A zero total is refused by the resolver, not the parser**, so its message reads
  `total_cents must be strictly positive, got 0`, which names an internal field. That is
  shown verbatim too, and goes in the same issue as the message above.
- **503 `no_group_configured` and `ambiguous_group` reach the user as the generic offline
  notice**, because `api.js` routes every status at or above 500 to `onOffline`. Wrong copy
  for an operator, owned by `api.js` and therefore by task 9a, and not to be papered over with
  a screen-local special case.
- **The offline notice has no way back.** A save that gets no answer replaces the whole frame
  with a notice carrying no retry and no dismiss, leaving the typed draft in the DOM behind
  it, reachable only by a reload that discards it. Raise it; it belongs to `api.js` and the
  curtain, not to this screen.
- **There is no endpoint that validates an amount without saving one.** There is no
  "dry run" and none is to be invented: `parse_amount` at the input edge is the only judge,
  and asking it costs a save.
