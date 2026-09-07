# Task 57: the feed render path runs under test

**GitHub issue:** #57. The issue is the backlog entry; `plans/backlog.md` gains no entry and is
not edited.

**Depends on:** 9b (the harness), 11 (the expense feed), 12, 13, 14 and 15 (which widened the
same DOM stub and added the balances row scenarios). All are on `master`; this task assumes
them and re-establishes none of them.

**Touches two files:** `tests/shell_harness.mjs` and `tests/test_shell_behaviour.py`. Nothing
under `app/`, `src/`, `scripts/` or the documents.

## Why this task exists

`app/app.js:569`, three lines into `feedRender`:

```js
var rows = document.createDocumentFragment();
```

`tests/shell_harness.mjs` does not fake `createDocumentFragment` on its `document` stub, and
the stub's guarded proxy refuses any property it does not define, so **that call throws every
time a scenario renders a feed row**.

`feedRender` is called at `app/app.js:622`, inside the `onFulfilled` arm of a
`.then(onFulfilled, onRejected)`. A throw inside `onFulfilled` is not caught by that same
call's `onRejected`, so it travels on as a rejection, and `loadFeed` ends `.then(done, done)`,
where `done` clears `feedBusy` and returns. The rejection is handled, the chain settles, and
nothing anywhere records that a screen died. A broken render and a refused request reach the
same place and look identical from outside.

**And no scenario asserts feed row content**, so nothing observes it: grepping the harness for
`feed-list`, `feedRow` and `feed-row` returns nothing. The whole of the feed's render path has
therefore never executed under test: `feedNames`, `feedRosterOrder`, `feedParticipants`,
`feedRow`, `feedDetail`, `feedDate`, `feedDateAndTime`, the share breakdown, the escaping and
the currency line. Every guarantee about what the feed *shows* rests on
`tests/test_feed_screen.py`, which reads the static committed document, and on nothing else.

It is not a shipping bug. Browsers implement `createDocumentFragment` and the feed works when
the app is opened. It is a hole in the evidence, which is the harder kind to notice, and a
later task documented it rather than closing it: the harness carries a comment at roughly line
7324 saying `feedRender calls document.createDocumentFragment`, "which this stub does not
fake, so no scenario in this repo has ever rendered a feed row". The comment is accurate and
the hole is unchanged.

## What was established before this file was written

Seven findings. Each is a fact about the code as it stands on `master`, checked rather than
assumed, and each one decides something below.

**1. The fragment is the only gap in the feed's DOM surface.** Every other member the render
path reaches for is already faked: `document.createElement`, and on an element `className`,
`textContent`, `id`, `hidden`, `type`, `setAttribute`, `getAttribute`, `appendChild`,
`replaceChildren`, `firstChild` and `addEventListener`. `createElement('time')` needs nothing
special. So one member closes it, and criterion 7 says so as a claim the engineer can falsify
by running.

**2. The stub's `replaceChildren` does not flatten, so the obvious fix is silently wrong.**
`replaceChildren(...nodes)` is `own.childNodes = nodes.slice()`, and `appendChild(child)` is a
push. A fragment handed to either one would become **one child node** rather than its
children, where a browser inserts the children and empties the fragment. The consequences are
all quiet: `descendants()` skips nothing but walks into the fragment as if it were an element,
the `textContent` getter reads a node with no `tagName` as `node.text` and yields `undefined`,
and `.expense-row` would be found under a phantom element. A stub that accepts a fragment
without flattening it produces a wrong tree and no error, which is the one behaviour a stub
must never have. Hence criteria 2, 3, 4 and 5.

**3. The empty case never reaches `feedRender`.** `loadFeed` sends a zero-length list to
`feedState('empty')` at `app/app.js:620` and returns; only the `else` arm renders. Every
scenario on `master` that reaches the app frame is answered with `EMPTY_FEED`
(`{currency: 'AUD', expenses: []}`) through `screensLoad`, which is exactly why 140-odd green
scenarios never touched the broken line. **The empty-case scenario the issue asks for is
therefore not the scenario that pins the fix**, and criterion 17 turns that into evidence
rather than leaving it as a footnote.

**4. The balances render path is not in the same position, and it never was.** Established,
not assumed:

* `balancesRender` builds no fragment. It appends each row straight to `#balances-net` and
  `#balances-transfers` through `balancesFill`, and composes text with
  `document.createTextNode`, which the stub has faked since #14 (`tests/shell_harness.mjs:637`).
* Balances rows **do** render under test today. `a_group_with_no_member_rows_shows_no_hint`,
  the drill-down family and the mark-as-paid family boot straight onto `#/balances` with a
  non-empty `net` and `transfers`, and the harness asserts rendered content: three net rows,
  transfer row tag names, row `childNodes` counts, `aria-expanded` flips and figure texts.
* Its handler shape protects it anyway. `balancesLoad` ends at
  `.then(onFulfilled, onRejected)` with **nothing after it**, so a throw inside
  `balancesRender` rejects a promise nobody handles, and the harness's `unhandledRejection`
  hook records it against the running scenario (`tests/shell_harness.mjs:7721-7737`). Had it
  ever thrown, the scenario that was running would have said so.
* `EMPTY_BALANCES` being `net: []` does short-circuit `balancesRender` into
  `balancesMessage('empty-roster')`, which is the same shape of blind spot as finding 3. It
  stopped mattering once #13 and #14 added scenarios with real figures.

So the balances half of the issue's last bullet is answered: no defect there, nothing to fix,
and no new balances scenario in this task beyond the invariant in criterion 12.

**5. The two screens differ by one token, and that token is the whole reason one hole stayed
invisible.** `.then(done, done)` is a hand-rolled `finally` that also swallows a throw from
`onFulfilled`. `.finally(done)` would clear `feedBusy` on both paths and re-raise, which is
what `balancesLoad`'s missing trailing handler achieves implicitly. That is a one-token change
to `app/app.js`, and it is **out of scope here**: see the decision below.

**6. The comment at line 7324 hopes for an oracle that does not exist.** It says the feed's own
spelling of an instant "would be the independent check". It would not: the drill-down rows call
`feedDate` directly (`app/app.js:1898`, `:2200`, `:2425`), the same function the feed row calls
at `:526`. Comparing one to the other compares `f(x)` to `f(x)`. #14's `spelledDate`, a second
copy of the rule, is a weaker oracle than an independent one and a **stronger** one than a
tautology, so it stays. The comment is corrected rather than acted on: criterion 32.

**7. #37's six survivors in the task 11 render path are void, not surviving.** #37 records ten
mutations surviving the harness, six of them "in the task 11 and 12 render paths". A mutation
to code that never executes cannot be killed, so the feed half of that number was measured
against a screen that was not running and says nothing about the scenarios. The task 12 half
stands, per finding 4. **Re-measuring is #37's, not this task's**, and this task's only
contribution to it is one mutant (criterion 18) proving the new scenarios kill something in
code that was dead until now.

## Goal

The feed's render path executes under the harness, and what a feed row shows is asserted rather
than assumed: the stub fakes `createDocumentFragment`, eleven appended scenarios pin the row,
the detail, the ordering, the escaping and the empty case, and a missing stub member can never
again be swallowed by a screen's own error handling.

## The four decisions

### The stub method

`document.createDocumentFragment` returns a node built by the existing `element()` factory
under the reserved tag name `#document-fragment`, following the precedent already in the file:
the parse root is `element('#document', {}, sink)`. That gets the fragment every member an
element has, the same guarded proxy, and correct `childNodes`, `firstChild` and `textContent`
for free, and it costs one line plus the insertion helper.

**Insertion flattens.** One helper expands a fragment into its children and empties it, and
both `appendChild` and `replaceChildren` route every node they are given through it, because
finding 2 says the alternative is a wrong tree and no error. `head.appendChild`, which is
replaced separately so it can load `api.js`, is left alone: nothing appends a fragment to
`<head>`, and a comment says so.

A `#`-prefixed tag name cannot collide with the selector support: `select()` reads `#x` as an
id and its bare-tag pattern is `^[a-z][a-z0-9]*$`, so no selector can name the fragment. And
after flattening, no fragment is ever in the tree to be named.

### Whether `.then(done, done)` keeps absorbing programming errors

**It keeps it, and this task does not touch `app/app.js`.** Three reasons, in order:

1. `git diff master -- app/` must be empty here, which also means `SHELL_DIGEST` does not move.
   That constraint comes from task 9b and #37 repeats it.
2. This task exists to make existing behaviour observable. Changing the subject and its test in
   one commit is how a test ends up asserting whatever the code happens to do, which 9b
   forbade by name.
3. The change is a real product decision with a real blast radius: it turns a class of
   currently-silent failure into an unhandled rejection in a browser, it moves `SHELL_DIGEST`
   and retires a cache, and it deserves its own issue with its own scenario. **Recommended
   follow-up issue: `loadFeed` should end `.finally(done)`, not `.then(done, done)`**, quoting
   finding 5 and this task's mutant G as the evidence that the shape hid a dead render for two
   tasks.

What makes leaving it safe **now** is that the harness stops depending on the app to surface a
stub gap:

* **Criterion 9** records a refused property against the running scenario at the moment the
  guard refuses it, whatever the app then does with the exception. That kills the class:
  `.then(done, done)`, a bare `catch`, or a rejection handler cannot hide a member the stub
  does not fake.
* **Criterion 12** fails any scenario left with a screen in its in-flight state after settle.
  A throw out of `feedRender` leaves `#feed-loading` up forever, because `feedState('list')` is
  the last line of the function, so a dead render is loud even in a scenario that asserts
  nothing about rows.
* **The eleven scenarios** assert what the feed draws, so a dead render is red on content too.

Honest residual: an exception thrown inside `feedRender` for a reason that is *not* a stub gap,
a genuine `TypeError` introduced by a future edit, is still absorbed by `.then(done, done)`.
What catches that is criterion 12 and the content assertions, not the promise chain. Closing
the residual is the follow-up issue's business.

### Which scenarios to add

Eleven, appended. Each pins one guarantee that has never executed, and each is a guarantee
about what a person reads on a money screen:

| Scenario | What it pins |
|---|---|
| `a_feed_row_names_the_payer_the_amount_and_what_it_was_for` | The row: description, amount, `Paid by`, the split line, the currency line, the four states |
| `a_feed_with_nothing_recorded_says_so_and_draws_no_row` | The empty answer is not dressed as a list, and does not reach `feedRender` |
| `the_rows_stay_in_the_order_the_server_sent_them` | Nothing here sorts, reverses or regroups, ties included |
| `an_expense_described_in_markup_reaches_the_screen_as_text` | The escaping claim, currently resting on a source-text ban |
| `an_expense_with_no_description_still_names_everything_else` | The `No description` literal, and that the rest of the row survives it |
| `opening_a_row_shows_every_share_and_the_total_they_are_shares_of` | `feedDetail`: every share including `0.00`, the total, `Recorded by`, the disclosure both ways |
| `a_payer_who_is_not_sharing_is_said_so_rather_than_added_to_the_split` | Paying for a meal you did not eat, stated rather than invented |
| `a_member_the_roster_does_not_know_reads_as_words_not_as_an_id` | `Unknown member`, and no UUID on screen |
| `four_people_sharing_one_expense_read_as_two_names_and_a_count` | The only place this screen composes prose about people |
| `leaving_the_feed_and_coming_back_draws_each_row_once` | Each load replaces the whole list, and expansion resets |
| `a_created_at_that_is_not_a_date_never_reads_as_nan` | The fallback branch, so a money screen never shows `NaN` |

**What is deliberately left to a later task:** the local-rather-than-UTC date guarantee, and any
independent date oracle. Finding 6 shows there is no independent spelling of an instant inside
the sandbox, and inventing one would mean reimplementing `feedDate` in the harness, which is
what `spelledDate` already is. The row scenario pins the two machine-independent halves, that
`datetime` carries the raw instant byte for byte and that the visible text is neither empty nor
`NaN`, and the rest stays on task 11's hand checklist where #14 left it.

### Whether the harness should refuse a screen that renders nothing

**Not as a rule about scenarios. Yes as an invariant about screens.**

Rejected: "a scenario that registers a non-empty payload must assert something about what
appeared." It is not mechanically checkable in any useful sense, since the harness cannot tell
an assertion about the screen from `page.is(1, 1, 'x')`, so the rule is satisfiable with a
token and a rule satisfiable with a token is worse than no rule. And it is wrong for a family
of scenarios that already exists: `a_route_change_behind_the_gate_asks_for_nothing_and_leaves_the_gate_alone`,
`marking_a_payment_paid_behind_a_curtain_asks_for_nothing` and their neighbours register real
payloads precisely to prove nothing was drawn. A check that fires on correct scenarios trains
people to defeat it.

Accepted instead, and it catches this defect in every scenario rather than in the ones that
thought to look: **after settle, no screen is left in the state it shows while a read is in
flight.** `#feed-loading` is hidden and `#balances-busy` is hidden, checked in `finish()`
beside the `#notice` invariant that is already there. Every answer in this harness resolves or
rejects immediately and `settle()` drains both queues, so a screen still mid-flight when a
scenario ends is a screen whose render died. That is criterion 12, and criterion 16 proves it
fires on the original defect.

## Acceptance criteria

**The stub gains a fragment**

1. `tests/shell_harness.mjs`'s `document` stub defines `createDocumentFragment`, returning a
   node built by the existing `element()` factory under the reserved tag name
   `#document-fragment`, so it carries the members every element carries and the same guarded
   proxy. `rows.appendChild(feedRow(...))` works, and a property nobody faked on it is still
   refused with a message naming it.
2. One helper expands a fragment on insertion, and **both** `appendChild` and
   `replaceChildren` route every node they are given through it: the fragment's children are
   inserted in order in its place, and the fragment is left empty, as a browser leaves it. A
   fragment node never becomes a child of anything.
3. After a render of three expenses, `page.el('feed-list').childNodes` is three nodes, each
   with `tagName === 'LI'` and `className === 'expense-row'`, in payload order; `firstChild` is
   the first of them; and `#feed-list`'s `textContent` contains no `undefined`.
4. `.expense-row`, `.expense-description`, `.expense-payer`, `.expense-figure`,
   `.expense-split`, `.expense-share` and `.expense-share-name` are all reachable through
   `page.query` after a render. The fragment does not sit between `#feed-list` and the rows.
5. No node in a rendered document has `tagName === '#DOCUMENT-FRAGMENT'`. A criterion because
   finding 2 makes a leftover fragment a wrong tree with no error attached.
6. `head.appendChild`, replaced separately so it can load `api.js`, is unchanged and carries a
   one-line comment saying nothing appends a fragment to `<head>`.
7. `createDocumentFragment` is the only member this task adds to the `document` stub, and no
   element member is added at all. If implementation finds a second gap, it is added with a
   comment naming the shipped line that uses it, and the PR says which line and why, because a
   second gap is a finding this task did not predict.
8. The addition carries a comment saying what it fakes, that insertion flattens, and why
   flattening is not optional.

**A refused property can no longer be swallowed**

9. `guarded()` records the refusal against the running scenario as well as throwing it: at the
   moment a get or a set is refused, the message goes into that scenario's failure list through
   the same `running` handle `escaped()` uses. Messages are deduplicated, so a gap tripped once
   per row produces one line and not a thousand.
10. A refusal with no scenario running goes to stderr and exits 2, which is what `escaped()`
    already does for an escaped rejection.
11. The guard still throws, unchanged, and recording is in addition to throwing and never
    instead of it. The shipped file's own error path must run exactly as it ran before.
12. `finish()` gains one invariant beside the `#notice` one: after settle, `#feed-loading` is
    hidden and `#balances-busy` is hidden, in every scenario, and a scenario where either is up
    fails with a message naming the element and saying that a screen was left mid-flight.
13. Every scenario on `master` still passes with 9 and 12 in place. If one goes red it is
    reported, never softened: a guard trip inside shipped code is another gap of this same
    class and gets the same one-member fix with a comment, and the in-flight invariant firing
    means a screen really is left mid-flight. The one case that is **not** implementable here
    is a deliberate feature probe in shipped code, a `typeof` or `in` test against a guarded
    stub; there is none today (`app/app.js:1498` probes `navigator`, which is a plain object),
    and if one appears, stop and raise it rather than weakening criterion 9.

**The fix is shown to catch the original defect**

14. The harness accepts one new configuration key, `hideDocumentMembers`: a list of names
    deleted from the `document` stub before the run, so the defect can be reproduced without
    editing the harness or committing a second copy of it. Precedent: `provokeRunawayTimer`
    exists for exactly this purpose. The module docstring gains a line for it.
15. A name in `hideDocumentMembers` that the stub does not define is a harness error, exit 2,
    with a message naming it, and the docstring's exit-2 list says so. A pytest test proves it,
    so a typo can never produce a vacuous green.
16. One pytest test runs `{"hideDocumentMembers": ["createDocumentFragment"]}` and asserts all
    five of:
    * the harness exits **1**, not 2, so a broken configuration cannot be mistaken for a
      caught defect;
    * `a_feed_row_names_the_payer_the_amount_and_what_it_was_for` is among the failed
      scenarios;
    * one of its failure messages names `createDocumentFragment`, which is criterion 9 proving
      the throw `.then(done, done)` swallows is now visible;
    * another names `#feed-loading`, which is criterion 12 proving a dead render is visible
      even without a content assertion;
    * `boot_with_no_session_shows_the_gate` still passed, so the record shows a working app
      with one screen broken rather than a crater.
17. That same test asserts `a_feed_with_nothing_recorded_says_so_and_draws_no_row` **still
    passes** with the member hidden. This is finding 3 written down where it cannot be
    forgotten: the empty case never reaches `feedRender`, so the empty-case scenario could not
    have caught this on its own, and neither can it prove the fix.
18. One new mutant, `MUTANT_G` in `tests/test_shell_behaviour.py`, expressed as an anchored
    substitution in `app/app.js` and never as a committed copy:

        find:     'Paid by ' + feedNameFor(names, entry.payer_id)
        replace:  'Paid by ' + feedNameFor(names, entry.created_by)

    The anchor matches exactly once, which `mutated()` already asserts. Its pytest test asserts
    exit 1, that the row scenario is among the failed, that a failure message names the payer
    text, and that a named unrelated scenario still passed. The row fixture therefore has
    `payer_id !== created_by`. Why this mutant: on a shared ledger the payer is who is owed
    money, `tests/test_feed_screen.py` cannot see it because it reads the static document, and
    before this task nothing in the repo could.

**The eleven scenarios**

19. Every one of the eleven exists in `tests/shell_harness.mjs`, passes against the shipped
    files, declares its exact ordered request list through `expectRequests`, and registers an
    answer for every call it makes. A scenario that changes something declares the exact body,
    per `finish()`.
20. `a_feed_row_names_the_payer_the_amount_and_what_it_was_for`: one expense whose payer is
    neither the acting member nor the first member of the roster, and whose `created_by`
    differs from its `payer_id`. It asserts exactly one `.expense-row`; the description text;
    the summary's amount as the payload spelled it, character for character; `Paid by` plus the
    payer's display name; the split line; `#feed-currency` reading `Amounts in ` plus the
    payload's currency and a full stop; `#feed-list` and `#feed-currency` visible with
    `#feed-loading`, `#feed-empty` and `#feed-error` hidden; the summary's `aria-expanded` as
    `false`, its indicator as `+`, and the region its `aria-controls` names existing exactly
    once and hidden; and the `<time>` element's `datetime` attribute equal to the payload's
    `created_at` byte for byte while its visible text is neither empty nor contains `NaN`.
21. `a_feed_with_nothing_recorded_says_so_and_draws_no_row`: a valid payload with no expenses
    and a non-empty roster. `#feed-empty` visible, the other three states hidden,
    `#feed-list.childNodes` empty. It carries a comment saying it does not reach `feedRender`
    and naming criterion 17.
22. `the_rows_stay_in_the_order_the_server_sent_them`: three expenses, two of them sharing one
    `created_at`. The ordered list of description texts equals the payload order exactly, ties
    included, and nothing in the scenario sorts, reverses or groups.
23. `an_expense_described_in_markup_reaches_the_screen_as_text`: a description of
    `<img src=x onerror=alert(1)>` renders as that literal string in `.expense-description`,
    the row contains no `IMG` node, and the scenario declares no console output, so any
    console line fails it.
24. `an_expense_with_no_description_still_names_everything_else`: an empty description renders
    the fixed literal `No description` on an element carrying both
    `expense-description` and `expense-description--none`, and the amount, the payer, the split
    line and the date are all still present.
25. `opening_a_row_shows_every_share_and_the_total_they_are_shares_of`: an expense with three
    allocations, one of them `0.00`, and `created_by` different from `payer_id`. Dispatching
    `click` on `.expense-summary` flips `aria-expanded` to `true`, unhides the region named by
    `aria-controls`, and the region lists every share name in roster order with its amount
    exactly as the payload spelled it, the zero included and none dropped, blanked or dashed;
    the total line reads the label `Total` and the payload's `amount`; the notes are exactly
    the one `Recorded by` sentence; the indicator reads `-`. A second click closes it: back to
    `false`, hidden, `+`. The hash is unchanged and `pushState` was never called.
26. `a_payer_who_is_not_sharing_is_said_so_rather_than_added_to_the_split`: a payer absent from
    the allocations. The detail carries exactly the one sentence naming that payer, the share
    names are exactly the participants, and the payer's name is not among them.
27. `a_member_the_roster_does_not_know_reads_as_words_not_as_an_id`: an allocation and a payer
    naming an id the roster has no row for. `Unknown member` appears in both the payer line and
    the share list, the unknown allocation keeps its place at the end of the shares, the known
    rows still render, and the raw id appears nowhere in the row's `textContent`.
28. `four_people_sharing_one_expense_read_as_two_names_and_a_count`: four allocations produce
    the first two names, then ` and 2 others`, asserted as the whole split line.
29. `leaving_the_feed_and_coming_back_draws_each_row_once`: open a row, navigate to
    `#/balances`, navigate back. The feed reads again; the row count is what it was and not
    doubled; the region id derived from the expense id exists exactly once in the document; and
    the rebuilt row's `aria-expanded` is `false` with its region hidden. The declared request
    list includes the balances screen's own two reads, because the route change enters that
    screen.
30. `a_created_at_that_is_not_a_date_never_reads_as_nan`: a `created_at` that is a string but
    not a date, longer than ten characters. Both the row's `<time>` text and the detail's
    `.expense-when` read exactly its first ten characters, `NaN` and `Invalid Date` appear
    nowhere in the row's `textContent`, and the `datetime` attribute still carries the whole
    raw value.
31. The eleven names are appended to `SCENARIOS` in `tests/test_shell_behaviour.py` at the end
    of the list, under one new comment header, in the order the harness runs them. Nothing
    above them moves, and
    `test_the_harness_reports_exactly_the_declared_scenarios` passes.

**One comment is corrected**

32. The comment above `SPELLED_MONTHS` in `tests/shell_harness.mjs` is corrected in place: the
    stub now fakes `createDocumentFragment` and feed rows do render, and the feed's own
    spelling of an instant is `feedDate`, the same function the drill-down rows call, so it is
    not an independent oracle and `spelledDate` stays. It names the four call sites. No
    scenario that uses `spelledDate` changes, and no assertion is switched to a feed-derived
    date.

**The suite**

33. `uv run python -m pytest` passes. Plain `uv run pytest` fails on this machine with an
    access-denied spawn error.
34. The count goes from **2431** to **2445**: eleven new `test_scenario` results, plus three
    new tests (criterion 15, criterion 16 and mutant G). A different total means something
    unplanned happened, and the engineer finds out what before proceeding.
35. Nothing is skipped, xfailed or made conditional on the environment, and a grep for
    `skipif`, `pytest.skip` and `xfail` in `tests/` finds nothing new.
36. `git diff master -- app/` is empty. `SHELL_DIGEST` and `VERSION` in `app/sw.js` are
    unchanged, and nobody goes looking for a digest to recompute, because no shell byte moves.
37. `tests/test_feed_screen.py` is unchanged and still passes, including its docstring's claim
    that nothing in it reads `app/app.js` and asserts a rendering behaviour.
38. Two runs of the same configuration are still byte-identical on stdout, and no new
    assertion depends on the machine's timezone, locale or clock.
39. The harness still imports `node:vm`, `node:fs`, `node:path` and `node:url` and nothing
    else.

## Out of scope

- **Anything under `app/`.** Not `app.js`, not `index.html`, not `styles.css`, not `sw.js`. The
  shipped code is correct; this task tests it.
- **Changing `.then(done, done)` to `.finally(done)`**, however right that change is. It is an
  `app/` edit, it moves `SHELL_DIGEST`, and it belongs to the follow-up issue this task's
  findings recommend.
- **Re-measuring #37's ten survivors.** This task voids the six that sit in the task 11 render
  path, because they were measured against code that never ran, and it makes re-measuring
  possible. #37 owns doing it. Mutant G is one mutant proving the new scenarios kill something,
  not a mutation campaign, and no mutation tool or framework is added, per task 9b.
- **The balances render path.** Finding 4 established that it already runs and does not throw.
  No new balances scenario, no change to any existing one, beyond `#balances-busy` appearing in
  criterion 12's invariant.
- **The local-rather-than-UTC date guarantee, and any independent date oracle.** Finding 6 says
  there is not one to be had inside the sandbox. It stays on task 11's hand checklist.
- **A rule requiring a scenario to assert something about the DOM.** Rejected above, with the
  reason.
- **Widening the stub beyond criterion 7**: no element member nothing uses, no new selector
  shape, no `innerHTML`, no `insertBefore`, no `classList` object, no event bubbling, no radio
  group semantics.
- **jsdom, happy-dom, linkedom, cheerio, npm, `package.json`, `node_modules`, a JavaScript test
  framework including `node:test`, a linter, a formatter, a bundler, coverage in either
  language.**
- **`app/sw.js` semantics, service workers, Cache Storage, installability, layout,
  accessibility trees and real cookie enforcement.** The browser-only list in the harness's
  docstring stands unchanged, and no new scenario is named as if it covered any of it.
- **CLAUDE.md, README.md, `plans/spec.md`, `plans/backlog.md`, `src/`, `scripts/`,
  `pyproject.toml`, `uv.lock`, `.claude/`.** The docs already describe the harness accurately,
  and `test_the_no_build_step_claim_carries_its_caveat_where_it_is_made` fails on a second
  paragraph.
- **Restructuring, renaming, reordering, weakening or deleting any existing scenario.** If a
  new scenario cannot be kept honest, stop and raise it.
- **Relative dates, staleness, editing and correction.** Tasks 16 and 17.

## Constraints

- Files to modify: `tests/shell_harness.mjs` and `tests/test_shell_behaviour.py`. No other
  file in the repository is created, modified or deleted.
- **Append; do not restructure.** New scenario objects go at the end of the `SCENARIOS` array
  in the harness. New fixtures and helpers go at the end of the file, under a header naming
  issue #57, the way the task 13, 14, 15 and 43 blocks did; module-level function declarations
  hoist, so a scenario body can call a helper defined below it. The four edits inside existing
  code are the stub member, the insertion helper, the `guarded()` recorder, the `finish()`
  invariant and the corrected comment, and nothing else moves.
- **The concurrent `task-hygiene` branch adds a duplicate-definition check and an
  anchored-pin check over every module in `tests/`.** Check every new name is free in both
  languages before using it, in the harness and in the Python file: scenario names, fixture
  constants, helper functions and pytest test function names. Any `pytest.raises` written here
  carries an anchored `match=`, spelled `^...$`, from the start.
- New helpers worth having, if the names are free: an `onFeed(page, expenses, roster)` mirroring
  the existing `onBalances`, and a `FEED_ENTRY` constant mirroring `BALANCES_ENTRY` for the
  three reads entering the feed route costs. `regionFor(page, button)` already exists and
  reaches a region app.js built at run time through the `aria-controls` its button names; reuse
  it rather than writing a second one.
- Assertions are exact: exact strings, exact element states, exact ordered request lists, exact
  exit statuses, per `.claude/rules/testing.md`. No substring guess at prose the shipped files
  did not write, and no approximate comparison.
- **Money stays money.** No scenario parses, adds, divides, rounds or reformats a cent value.
  Every amount is compared as the string the payload carried, and the fixtures spell those
  strings out rather than deriving them.
- Fixtures are spelled out rather than rebuilt from the code that renders them: a value
  asserted against a copy of its own producer asserts nothing.
- `node:vm`, `node:fs`, `node:path` and `node:url` only. Any further import, built-in or not,
  needs a one-line comment saying why, and no package from any registry is added in either
  language. `.claude/hooks/guard-deps.hs.sh` blocks the Python route; the JavaScript side has
  no guard and the discipline is the rule.
- The test command is exactly `uv run python -m pytest`. `node tests/shell_harness.mjs` stays a
  debugging convenience and never a second documented command.
- Files are located from `import.meta.url` in the harness and from
  `Path(__file__).resolve().parents[1]` in Python, never from the working directory.
- Every non-obvious choice gets a one-line comment where it is implemented: why the fragment
  reuses `element()` with a `#`-prefixed tag, why insertion flattens and empties, why a refused
  property is recorded as well as thrown, why the in-flight invariant lives in `finish()`, and
  why `hideDocumentMembers` refuses a name the stub does not define.
- **This file may be corrected only for a statement that is provably wrong**, following the
  precedent tasks 5, 9, 9b and 11 set: it is created by this PR and nothing on `master` depends
  on it. Sharpening a criterion, re-scoping one or softening one to suit an implementation is
  not covered and stays forbidden. Every correction carries a dated marker saying what the file
  used to say, what it says now, and why.
