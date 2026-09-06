# Task 13: Transfer drill-down

**Depends on:** 5 (complete, on `master`), 9b (complete, on `master`), 12 (complete, on
`master`), **12a / issue #38 (complete, on `master` as of 2026-09-06)**. Everything this
task reads now exists and is quoted from the shipped source below.

**Consumed by:** nothing. Task 14 hangs "mark as paid" off the same row and must be able to
add a third child to the transfer `<li>` without unpicking anything here.

Sharpened from `plans/backlog.md` task 13, GitHub issue #14. The backlog entry stays as
written; this file is the implementable version.

---

## 2026-09-06: what changed in this file, and why

This file was written **before the API it depends on existed**, so its contract section was
a set of predictions. Task 12a (#38) landed that API on 2026-09-06, and task 32 (#43) moved
the front end underneath it. Everything below was re-read against the shipped source
(`src/splitwise_lite/web.py`, `src/splitwise_lite/balances.py`, `app/api.js`, `app/app.js`,
`app/sw.js`, `tests/shell_harness.mjs`, `tests/test_web_shell.py`) and corrected. This is
the record of what moved, under this file's own dated-marker rule. Nothing here sharpens,
re-scopes or softens a criterion; every entry is a statement that was provably wrong.

1. **"The data is not on the wire" was the largest section in this file. It is now false in
   every particular, and it is deleted.** `_read_balances` sends `payer_debts` and
   `receiver_credits` on every transfer; `GET /api/debts/<debtor_id>/<creditor_id>` exists
   and is registered in `_API_ENDPOINTS`; `app/api.js` exposes `api.debt`. The section is
   replaced by "The contract, as shipped", which quotes the source rather than predicting
   it. The instruction "**this task cannot start**" is spent and is gone with it.

2. **The debt endpoint returns six top-level keys, not five. The added one is `direction`.**
   `web.py:1422` sets it, from `_direction(-found.amount.cents)`. `amount` is the
   non-negative magnitude and `direction` carries the sign, spelled and valued exactly like
   `direction` on a net row. This was recorded as a contract correction in issue #14's
   comments and is applied here. It changes no criterion: nothing on this screen reads the
   endpoint's top-level `amount` or its `direction`, and "The screen renders neither, and
   why" below now says so on purpose rather than by omission.

3. **The endpoint refuses two inputs this file never mentioned, and both are reachable from
   this screen.** `_read_debt` raises `MalformedRequest` (400, `malformed_request`) when
   either path id is not in the group's roster, and again when the two ids are equal. A
   drill-down row whose member is missing from the roster is therefore not only a
   `Unknown member` label: expanding it gets a refusal. Criteria 29 and 43 cover it.

4. **The failure sentence is fixed prose and is never `error.say`.** This file predated
   `announce()`'s six kinds. The one kind that carries a server sentence here is `refused`,
   and the sentence `_read_debt` composes for its own 400 contains a **member id**, which
   this screen may never render as visible text. So the row prints its own sentence for
   every kind. Criterion 43.

5. **`ledgerIsUp()` did not exist when this file was written.** It landed with #43 and every
   screen-entry path calls it. This task's disclosure handlers call it too, and add no
   fourth copy of the question. Criterion 47.

6. **`app/sw.js` is now edited by this task, for exactly one line.** This file said sw.js
   was untouched and `VERSION` unbumped. `VERSION` still is not bumped, but the cache name
   now carries `SHELL_DIGEST`, a digest over the nine precached files, and `app/app.js`,
   `app/index.html` and `app/styles.css` are three of them. Editing them turns
   `test_the_recorded_digest_matches_the_files_it_covers` red. Criterion 79.

7. **Half of the predicted harness widening is already done.** Elements gained a `type`
   property with the add screen (`shell_harness.mjs:166-171`). `document.createTextNode` is
   still absent, and so is an element `id` property, which this file did not predict and
   which `feedDetail`'s `detail.id = ...` pattern needs. Criterion 75.

8. **`test_the_balances_section_carries_every_id_the_screen_toggles` cannot pass untouched.**
   This file listed it among the tests that do, while also adding an id to that section. The
   test pins the id set exactly, so `BALANCES_IDS` gains `balances-drill-hint`. Criterion 69.

9. **The mutant criterion named two mutants. There are six**, A to F, and D, E and F name
   add-screen scenarios. Criterion 78.

10. **Two "exact words" corrections, both forced by ` (you)`.** The second line of an
    expense entry read `<Creditor> paid, <Debtor>'s share`. Every name on this screen goes
    through `balancesName`, which appends ` (you)` for the acting member, so that sentence
    renders as `Sam (you)'s share`. The possessive is dropped: `<Creditor> paid, and
    <Debtor> shared`. Nothing else about the entry lines moves.

11. **The `covers_whole_debt` fallback is inverted.** This file said a value that is neither
    `true` nor `false` renders the row *without* the "of" clause. That is the reading that
    claims the payment clears the whole debt, which is the claim a garbled flag has not
    earned. The rule is now a single strict equality: `=== true` drops the clause, and
    anything else keeps it, because the clause states two figures the server sent and makes
    no claim of its own. Criterion 25.

12. **"Two other branches are editing these files" named task 10 (#11) and issue #32. Both
    have landed.** The merge-hygiene rules they motivated are kept as written, because other
    branches are still in flight and the rules cost nothing: append at the end, prefix every
    selector, touch one region.

Anything not listed here stood up to the shipped source and is unchanged.

---

## Goal

Tapping a suggested payment on the balances screen opens it, and shows the pairwise debts
that payment absorbed, from both ends: the debts the payer owes and the debts owed to the
receiver. Each of those debts opens in turn and lists the expenses and confirmed settlements
behind it. A flatmate looking at "Jo pays Sam 10.50" for a person they have never bought
anything with can get from that row to real, named expenses without asking anybody.

That question is the whole reason this task exists. The backlog calls it "the known failure
mode of debt simplification", and the spec's resolution of "netting and audit trail pull in
opposite directions" is that "every suggested transfer keeps a pointer back to the pairwise
debts it absorbed, so any figure can be traced to real expenses". Task 5 built that pointer,
task 12a put it on the wire, and this task is the only thing that ever reads it.

## The contract, as shipped

Read against `src/splitwise_lite/web.py` and `src/splitwise_lite/balances.py` on 2026-09-06.
Verify it again before starting: if the source and this section disagree, the source wins
and this section is corrected before implementation, never reinterpreted during it.

### `GET /api/balances`

`_read_balances` (`web.py:1306`) sends `currency`, `net` and `transfers`. Each entry of
`transfers` carries five keys:

    {"from_member_id": "...", "to_member_id": "...", "amount": "10.50",
     "payer_debts":      [ <absorbed debt>, ... ],
     "receiver_credits": [ <absorbed debt>, ... ]}

An absorbed debt is `_absorbed_view` (`web.py:926`), exactly five keys:

    {"debtor_id": "...", "creditor_id": "...", "amount": "4.00",
     "debt_total": "10.00", "covers_whole_debt": false}

`covers_whole_debt` is `row.amount.cents == row.debt_total.cents`, computed on the server
from cents, for the same reason `direction` exists on a net row: the screen must never
compare two amount strings to decide what a row says. `amount` and `debt_total` are
`format_amount` strings, as every amount on this wire already is, and carry no minus sign.

What `simplify.py` guarantees about those two lists, and this screen relies on:

* every row of `payer_debts` names `from_member_id` as its debtor, and the rows sum to
  exactly the transfer amount;
* every row of `receiver_credits` names `to_member_id` as its creditor, and those rows sum
  to exactly the transfer amount too;
* both lists are non-empty, both ascend by `(debtor, creditor)`, and a pair appears at most
  once **within** each list. The same pair may appear in **both**, and that is the
  two-ended view rather than a duplicate.

Nothing is re-sorted, merged, filtered or deduplicated in `web.py`, and nothing is here.

### `GET /api/debts/<debtor_id>/<creditor_id>`

`_read_debt` (`web.py:1363`) sends **six** top-level keys:

    {"currency": "AUD",
     "debtor_id": "...", "creditor_id": "...",
     "amount": "10.00", "direction": "owes",
     "entries": [ <entry>, ... ]}

An entry is `_debt_entry_view` (`web.py:964`), six keys in this order:

    {"kind": "expense", "effect": "adds", "id": "...", "description": "Milk run",
     "created_at": "2026-09-04T08:00:00.000000+00:00", "amount": "4.00"}

* `kind` is `expense` or `settlement`, from `_ENTRY_KIND_WIRE`, an explicit map over
  `DebtEntryKind`, exhaustive and tested.
* `effect` is `adds` or `reduces`, from `_ENTRY_EFFECT_WIRE` over `DebtEffect`. It is the
  server saying which way this entry moves the debt that was asked about. `amount` is always
  strictly positive; the sign lives in `effect` and nowhere else.
* `description` is the expense's own description, verbatim, empty included. **A settlement
  always carries `""`**, because `SettlementEvent` has none and `balances.py` refuses to mix
  a sentence this repo wrote into a list of what people actually recorded. Naming a
  settlement is this screen's job.
* `created_at` is spelled exactly as `_expense_view` spells it, so the feed's `feedDate`
  reads it with no second parser.
* `entries` arrives **newest first**: `web.py:1427` reverses `debt_sources`' ascending
  ordering key, the same way `_list_expenses` reverses the store's order. The screen
  preserves that order exactly.

What `debt_sources` puts in the list, from `balances.py:399`, because the wording of an
entry line depends on it:

* an expense **paid by the creditor** where the debtor holds a non-zero allocation `adds`
  the debtor's allocation;
* an expense **paid by the debtor** where the creditor holds a non-zero allocation `reduces`
  the creditor's allocation;
* a **confirmed** settlement from the creditor to the debtor `adds` its whole amount, and
  one from the debtor to the creditor `reduces` it. A pending or rejected settlement is not
  listed at all.

Two refusals this endpoint makes, both reachable from this screen and both a 400
`malformed_request`: **either path id that is not in the group's roster**, and **a
self-pair**. See criterion 43.

### The screen renders the endpoint's `amount` and `direction` nowhere, and why

A debt row's text is composed entirely from the transfer payload: `debtor_id`,
`creditor_id`, `amount`, `debt_total`, `covers_whole_debt`. The entry lines are composed
entirely from `entries`. The endpoint's top-level `amount` and `direction` are read by
nothing.

That is deliberate. The two payloads are two reads of a ledger that may have moved in
between, and `_read_debt`'s own docstring says two requests against a changed ledger may
legitimately differ. Splicing a fresher pair total into a row built from an older balances
read would make one row disagree with itself, and the screen is in no position to say which
half is right. The entry list stays coherent with the row's wording either way, because
`effect` is relative to the pair the row asked about, which is the pair the row names.

The screen therefore makes no claim that the entries sum to the row's figure. Task 11 set
that precedent for the feed's shares and its total: state the two things, claim no
relationship between them, because the front end is in no position to have checked one.

### The client

`app/api.js` exposes `api.debt(debtorId, creditorId)`, which `encodeURIComponent`s both ids
into the path. **`app/app.js` contains no URL**: `test_the_narrowed_rule_still_bites`
forbids it the byte sequences `fetch` and `/api` outright, in code and in comments alike, so
not even a comment in the balances region may spell `/api/debts`.

## What an open payment shows, and why one list is not enough

A transfer of 10.50 from Jo to Sam has two questions attached to it, and they have different
answers:

* Jo asks "why am I paying at all, and why 10.50?" That is answered by `payer_debts`: the
  debts Jo owes that this payment discharges.
* Jo and Sam both ask "why *Sam*, when I have never bought anything with them?" That can
  only be answered by `receiver_credits`: the debts owed to Sam that this payment
  discharges.

Task 5's file states this plainly and warns that one list answers only one of them. **A
drill-down that renders `payer_debts` and stops is a wrong implementation of this task**, and
it is wrong in exactly the case the backlog says the task exists for.

Both lists are shown, each under a label naming whose end it is. Each list independently
accounts for the whole transfer amount, which is the one thing a reader can badly misread:
seeing 10.50 of debts under one label and 10.50 under the other, a person can conclude they
owe 21.00. So an open payment carries a fixed sentence saying they are one payment seen from
two ends. The screen states that; it does not compute it. The front end adds nothing up, and
per task 11's precedent it makes no claim about a sum it is in no position to have checked.

## The three shapes a payment takes, and how each reads

Which shape a transfer is in is decided by the ids alone. **No amount is ever compared to
decide what a row says.**

**Direct.** `payer_debts` and `receiver_credits` are each one row naming the same pair. This
happens exactly when the transfer discharges one debt straight between the two people, which
is the simple case task 5's "direct debt first" rule guarantees. Two labelled lists holding
the same single row reads as a bug, so this shape shows **one** list, under one sentence
saying the payment settles that debt directly.

**Passing through.** No row of `payer_debts` names the receiver as its creditor, so the two
have no debt between them at all. This is the case the whole task exists for. It shows both
lists plus a fixed sentence saying the two have not shared an expense, and the two lists are
why the payment still settles the group.

**Mixed.** A direct row plus others. Task 5's worked fixture is exactly this: Bo owes Ali
300, Bo owes Cass 300, Cass owes Ali 300, one transfer `bo -> ali 600` whose payer debts are
`(bo, ali) 300` and `(bo, cass) 300` and whose receiver credits are `(bo, ali) 300` and
`(cass, ali) 300`. Both lists, no passing-through sentence, and the direct debt appears in
both lists, which is the two-ended view and not a duplicate.

**A transfer is routinely larger than every single debt it absorbs.** That fixture is a 600
payment made of four 300 debts. Nothing on this screen may present that as odd: no row is
highlighted as the main one, nothing is sorted by size, and no list is truncated to the
biggest few. Every absorbed debt is listed, because a debt left off the list is a cent of a
real payment left unexplained.

**A debt can be split across two transfers, and both halves look wrong alone.** Task 5's
chain fixture: Bo owes Ali 1000, Ali owes Cass 400, giving `bo -> ali 600` and
`bo -> cass 400`, where `(bo, ali)` appears in both, for 600 and for 400, with `debt_total`
1000 on both rows. Open both payments and a reader sees the same debt twice. What stops them
concluding they owe Ali 1600 is the whole total on the row: `Bo owes Ali 6.00 of 10.00` and
`Bo owes Ali 4.00 of 10.00`. That is why `debt_total` and `covers_whole_debt` are on the
wire, and why a row that covers a whole debt drops the "of" clause rather than saying "of"
the same number twice.

**A debt may be absorbed by nothing at all.** In a pure cycle there are no transfers and
every debt is absorbed zero times. Such a debt appears in no drill-down anywhere, and the
screen never claims these lists cover every debt in the group. No summary, no total, no
"and 3 more debts" line.

## Expanding a debt to its expenses

Each absorbed debt row opens in turn, and that is where the second request happens.

**When.** The first time that debt row is expanded, and never before. Not on entering the
route, not when the payment above it opens, not speculatively for the other rows. The
balances screen already makes two requests on every entry; adding one request per debt in
every transfer, for rows nobody opened, would multiply that by the size of the plan to
answer a question nobody asked.

**What.** `api.debt(debtorId, creditorId)` for that row's pair, once. Expanding, collapsing
and expanding the same row again does not ask a second time: the answer is already in that
row's own DOM. That is not a cache. The whole transfer list is rebuilt from scratch on every
entry to the route, so nothing survives a navigation, nothing is held in a module variable
between visits, and nothing reaches `localStorage`, `sessionStorage` or `indexedDB`.

**A pair can move both ways.** The entries include expenses that reduce the debt as well as
expenses that add to it, and confirmed settlements between the two people. Each entry says
in words which way it moves the debt, taken from `effect`. Nothing on this screen infers a
direction from an amount, and no entry's meaning is carried by a sign, a colour or a minus
that is not there: `format_amount` produces no minus sign, and `web.py` sends magnitudes.

## Making an inert row interactive without breaking task 12

Task 12 built this row deliberately inert and left the seams for this task: each transfer
`<li>` carries `data-from` and `data-to`, holds its sentence inside exactly one child
element, is already 44 px tall so nothing shifts, and is built by one named function,
`balancesTransferRow`, which is the function this task changes.

The pattern is already in this codebase and shipped: the expense feed's inline disclosure,
`feedRow` in `app/app.js` (lines 478 to 564). Follow it rather than inventing a second one.

* The row's one child `<span class="balances-line">` becomes a real `<button type="button">`
  carrying the same sentence, with `aria-expanded` and `aria-controls`, and the detail region
  is appended to the `<li>` as its sibling. The `<li>` keeps `data-from` and `data-to`, so
  task 14 can still find the transfer a row belongs to.
* A real `<button>`, so Enter and Space work with no key handler, focus order is right with
  no `tabindex`, and no `role="button"` is needed. Not an `<a>`, which would put an entry in
  the history; not `<details>`, whose open state and styling differ across the browsers this
  ships to.
* **No fourth route.** `ROUTES` keeps exactly `#/feed`, `#/add` and `#/balances`, the router
  keeps owning the route-to-screen mapping, opening a row changes no hash, pushes no history
  entry and scrolls nothing.
* **Nothing looks tappable before the data is there.** A transfer whose payload carries no
  usable provenance renders exactly as task 12 rendered it: an inert `<span>`, no button, no
  chevron, no pointer cursor. That is the honest fallback against an older server and a
  partial payload.
* Hit areas stay at 44 px. The button carries the row's padding and its own `min-height`, so
  the whole row is the target with no dead strip, and the nested debt button clears the same
  floor. Every `min-height` in `app/styles.css` is asserted to be at least 44 px across the
  whole file, and every `font-size` at least 16 px, so there is no small print here: the
  effect line and the date are 16 px or larger like everything else.
* More than one payment may be open at once, and more than one debt inside one payment. The
  feed made the same decision for the same reason: collapsing somebody else's row to open
  yours is surprising.
* **Both detail regions are built eagerly, hidden, when the row is built**, exactly as
  `feedDetail` is built inside `feedRow`. Opening toggles `hidden` and nothing else. Only the
  *request* behind a debt is lazy. Building the DOM eagerly costs no request, keeps the
  toggle a two-line handler, and puts every `role="status"` line in the document before it is
  ever revealed, which is what a live region needs.

## Opening, closing, focus and the keyboard

Accessibility is not decoration on this screen: the row is a tap target that opens a detail
view, so it needs a keyboard route and it needs to say what it did.

**The keyboard route** is a real `<button type="button">` and nothing else. Enter and Space
activate it natively, it is in the tab order with no `tabindex`, and it needs no `role`. Any
key, pointer or touch listener appearing here would mean somebody rebuilt a button badly,
which is why they stay banned by name.

**The announcement of state** is `aria-expanded`, `"false"` closed and `"true"` open, on
both levels of button, plus `aria-controls` naming the region and the `hidden` attribute on
the region itself, so neither a screen reader nor find-in-page reaches a closed one. The
visible indicator is `aria-hidden="true"`, because `aria-expanded` already says the same
thing and twice is noise. The feed's `+` and `-` are the precedent.

**The announcement of the request** is a one-line message element inside each debt's region,
carrying `role="status"`, holding the waiting sentence, the failure sentence or the
nothing-recorded sentence and never anything else. The entry list is that element's sibling,
not its child, so arriving entries are not read out in full. The region carries
`aria-busy="true"` while its request is in flight and loses the attribute when it settles.

**The ordering that makes the live region work.** On the first expand, in this order: flip
`aria-expanded`, unhide the region, set `aria-busy`, write the waiting sentence into the
status line, and only then send the request. A `role="status"` element whose text changed
while it was hidden announces nothing in several screen readers, so the reveal comes first.
This is checkable: `page.onRequest` runs a watcher at the moment the request goes out, and a
scenario asserts the region was already visible and already reading the waiting sentence.

**Focus does not move, in either direction.** The button that was activated keeps focus when
the region opens and keeps it when the region closes. Nothing in this task calls `focus()`,
and `app/app.js`'s balances region contains no `.focus(` at all. Two reasons: the feed set
the precedent, and issue #37 records that the harness counts `focus()` on a hidden element as
a focus, so a scenario asserting focus movement would report a pass it has not earned.

**Closing cannot orphan focus.** The only control that closes a region is that region's own
button, which sits outside the region and takes focus when it is activated, by mouse, by
touch and by keyboard alike. So focus is never inside a region at the moment it becomes
hidden, and the browser never has to move it to `<body>`. Nothing else in this task is
focusable: the regions contain buttons, list items, spans and paragraphs, no links and no
fields.

## What it shows while it waits, and what it shows when it fails

`app/api.js` classifies every failed request into one of six kinds before any handler runs,
and it is the only file that may decide what a status means. This screen asks about session
state through `ledgerIsUp()` and asks about nothing else. It reads no status, no code, and
does not branch on `error.kind` either.

**Before the request.** The disclosure handler calls `ledgerIsUp()` first. If a curtain is
up, or no session is held, or the app frame is not what is showing, the handler returns
having changed nothing: no toggle, no request, no message. That is the same answer the feed
and add retries give behind a curtain, and it uses the same shared helper rather than a
fourth copy of the question.

**While it waits.** The status line reads `Looking up the expenses behind this.` The button
stays usable. No spinner, no animation, no skeleton row, no timer, no debounce: `setTimeout`,
`setInterval` and `requestAnimationFrame` stay banned in this region by an existing test.

**When it fails.** The row's status line reads `Those expenses could not be listed just now.`
and the region drops `aria-busy`. That is the answer for **all six kinds**, and the six kinds
divide only in what happens *elsewhere*, which is `api.js`'s doing and not this screen's:

| kind | what `announce()` does | what this screen does |
|---|---|---|
| `offline` | `onOffline`, the offline curtain | the row's fixed sentence |
| `unavailable` | `onOffline`, the problem curtain | the row's fixed sentence |
| `sign-in-not-kept` | `onOffline`, the problem curtain | the row's fixed sentence |
| `signed-out` | `onUnauthenticated`, the gate | the row's fixed sentence |
| `not-linked` | `onNotLinked`, the not-linked notice | the row's fixed sentence |
| `refused` | nothing; the caller reports it | the row's fixed sentence |

The screen registers none of the three global handlers, so five of those six put a curtain
over the frame that this row is under. Writing the sentence into a row nobody can see is
harmless and keeps the code one path; signing back in rebuilds the whole list anyway.

**Why the sentence is fixed and is never `error.say`.** Only `refused` carries a server
sentence at all, and the sentence `_read_debt` composes for its own 400 is
`a debt path names a member id that is not a member of this group: 'mem-9'`. It names a
**member id**, and this screen may never render a member id as visible text: task 12 decided
a UUID on screen is noise that helps nobody, and it holds one level down as well. The other
sentences the route can produce, `record_not_found` and `too_many_attempts` among them, are
written for whoever made the request rather than for a flatmate reading a debt. One sentence,
composed here, for every way this can fail.

**`balances-error` is not shown.** A drill-down that failed is one row's failure, not the
screen's. The transfer above it stays open, its debt rows stay listed, the net list is
untouched, and the four fixed messages in `#balances-status` are exactly as task 12 left
them.

**A failure keeps nothing.** Collapsing and re-expanding a row whose request failed asks
again, because nothing was kept. A row that answered keeps its entries in its own DOM and
asks nothing further.

## The empty cases, and the single-entry case

* **A debt with nothing behind it.** `entries: []` is a valid answer, not a failure: the
  status line reads `Nothing is recorded behind this debt.` and no list is rendered. An
  empty region is never shown. This is reachable even though a debt row only exists because
  a transfer absorbed a non-zero debt, because the ledger can move between the balances read
  and this request.
* **A debt with one entry** renders exactly like a debt with nine: one entry, no count, no
  "1 expense", no special case.
* **A transfer with no usable provenance** renders inert, per criterion 12. That is a
  payload problem rather than an empty answer, and the row says nothing about it.
* **An empty transfer list** is task 12's `No payments needed. Every net position is zero.`
  unchanged, and the drill-down hint stays hidden.
* **A response that is not the documented shape** is a failure, not an empty debt.

## Where the fixed prose lives

Task 12 put every sentence it could show into `app/index.html`, because there was no
JavaScript test runner and prose in markup was prose a Python test could pin. Task 9b landed
the harness, so that reason is gone for prose that repeats per row, and a per-row sentence
cannot live in markup anyway.

The rule for this task:

* A sentence shown **at most once on the screen** goes in `app/index.html`, hidden, and the
  code only toggles `hidden`. This task adds exactly one: the hint that rows can be opened.
* A sentence that belongs **to a row** is composed in `app/app.js`, exactly as `feedRow`
  composes "paid and is not sharing this expense", and is pinned by a harness scenario
  asserting the rendered text. That is a stronger check than a substring in a source file,
  and PR #30's rule still stands: no Python test asserts a string is present in `app.js` in
  order to claim a rendering behaviour is covered.

## The exact words

These are the contract. Reword one and the harness scenarios go red, which is the point.
Raise a change; do not make it quietly.

Transfer row, unchanged from task 12: `Jo pays Sam 10.50`.

An open payment, direct shape:

    This payment settles what Jo owes Sam directly.
    [one debt list, from payer_debts]

An open payment, passing-through shape:

    Jo and Sam have not shared an expense. These are the debts on each side of this
    payment.
    What Jo owes
    [payer_debts]
    What Sam is owed
    [receiver_credits]
    The same payment seen from each end. These are not two payments.

An open payment, mixed shape: the same as passing through, without the first sentence.

A debt row, with `covers_whole_debt` true, then anything else:

    Jo owes Ali 4.00
    Jo owes Ali 4.00 of 10.00

An open debt, one entry per line pair, then the date, in the feed's spelling:

    Milk run                                        4.00
    Adds to this debt: Sam paid, and Jo shared
    4 Sep 2026

    A settlement                                    5.00
    Takes off this debt: Jo paid Sam
    2 Sep 2026

The four second lines in full, `<Debtor>` and `<Creditor>` being the row's own two people
through `balancesName`:

| `kind` | `effect` | second line |
|---|---|---|
| `expense` | `adds` | `Adds to this debt: <Creditor> paid, and <Debtor> shared` |
| `expense` | `reduces` | `Takes off this debt: <Debtor> paid, and <Creditor> shared` |
| `settlement` | `reduces` | `Takes off this debt: <Debtor> paid <Creditor>` |
| `settlement` | `adds` | `Adds to this debt: <Creditor> paid <Debtor>` |

An open debt that is waiting, that failed, and that came back with nothing:

    Looking up the expenses behind this.
    Those expenses could not be listed just now.
    Nothing is recorded behind this debt.

The one sentence added to `app/index.html`, shipped hidden, shown only when at least one
transfer row can actually be opened:

    Open a payment to see the debts behind it.

Names carry ` (you)` for the acting member and `Unknown member` for an id the roster does
not know, everywhere they appear, through the existing `balancesName`. An expense whose
description is empty or whitespace only renders as `No description`, the same literal the
feed uses. A settlement's description is always `""` on the wire and always renders as the
literal `A settlement`; `kind` decides that before the description is looked at.

## The names this task adds

Every id and class is prefixed `balances-`, so a concurrent branch cannot collide with it.

Ids: `balances-drill-hint` in the markup, and `balances-detail-N` for every detail region,
where `N` comes from a module-level counter in the balances region that increases for every
region built and is never reset. Derived from a sequence number and never from the member
ids: task 12 decided the renderer does not assume a pair appears at most once, and two rows
for one pair must not produce two elements with one id.

Classes: `balances-transfer` (on the transfer `<li>`, beside `balances-row`),
`balances-transfer-button`, `balances-transfer-detail`, `balances-shape-note`,
`balances-debt-label`, `balances-debt-list`, `balances-debt` (the debt `<li>`),
`balances-debt-button`, `balances-debt-detail`, `balances-entry-status`,
`balances-entries`, `balances-entry`, `balances-entry-line`, `balances-entry-description`,
`balances-entry-effect`, `balances-entry-date`, `balances-indicator`. Any further class is
also `balances-` prefixed.

## How it is tested

Three layers, and each is only allowed to claim what it can actually see.

**Python, `tests/test_web_shell.py`:** markup and bans only. It pins the one new paragraph
and its exact sentence, and it keeps the bans that are still true now that the row is a real
control. Three task 12 tests state the opposite of what this task builds and are dealt with
explicitly below rather than left to fail.

**The JavaScript harness, `tests/shell_harness.mjs` plus `tests/test_shell_behaviour.py`:**
everything the screen actually renders. This is where the two-ended lists, the three shapes,
the split debt, the second request and every failure path are asserted, against the real
shipped files.

**The stub widening is this task's, and it is deliberate.** No scenario in this repo has ever
rendered a balances row or a feed row, so `document.createTextNode` has never been reached
and no element has ever had an `id` assigned to it. The 12a scenario says so in its own
comment and leaves both to this task. Widen them, each with a one line comment naming the
shipped code that reaches for it; do not route around the stub by writing the app
differently. The guarded proxy keeps refusing everything else.

**What the harness cannot claim, and what no scenario here pretends.** The stub never parses
markup, so a scenario asserting that a name containing `<` renders as text would be asserting
nothing: escaping is covered by the `innerHTML` ban in Python and by the browser checklist.
Focus movement, a cached session view and an `aria-current` value are issue #37's recorded
gaps and no scenario here rests on one. Whether a screen reader speaks a `role="status"` line
is browser-only and stays on the hand checklist.

**By hand, in a browser:** layout at three widths with a deep nesting, screen reader
announcement of the expanded state and of the status lines, and console cleanliness. Listed
at the end.

---

## Acceptance criteria

Numbered so each can be ticked yes or no by reading the result. Behavioural criteria name
the harness scenario that proves them; a criterion with no scenario named is checkable by
reading a file or running the suite.

### Before anything: the dependency

1. `src/splitwise_lite/web.py` is read and confirmed to match "The contract, as shipped"
   above: `_absorbed_view` sends the five keys named, `_read_balances` sends `payer_debts`
   and `receiver_credits` on every transfer, and `_read_debt` sends the six top-level keys
   named, `direction` included. If any of it differs, this file is corrected before code is
   written.
2. `app/api.js` exposes `api.debt(debtorId, creditorId)` and is **not modified by this
   task**: `git diff` shows no change to it.
3. Nothing under `src/splitwise_lite/` is modified by this task: `git diff` shows no change
   to any file under it. If a criterion below appears to need a new field, a widened payload
   or a new endpoint, stop and raise it rather than editing `web.py`.

### The transfer row becomes a control

4. `balancesTransferRow` is still the one named function that takes one transfer and returns
   one `<li>`, and `balancesFill` still calls it once per entry of `transfers`, in the order
   the array arrived.
5. The `<li>` still carries `data-from` and `data-to`, holding the payload's
   `from_member_id` and `to_member_id`, still as attributes only and never rendered as text.
   (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)
6. When the transfer carries usable provenance, the `<li>` holds exactly two children: a
   `<button type="button">` carrying the row's sentence, and a detail region that is its
   sibling. Task 14 can append a third child without touching either.
   (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)
7. The button carries `aria-expanded`, `"false"` when closed and `"true"` when open, and
   `aria-controls` naming the detail region's id. The detail region carries the `hidden`
   attribute when closed and loses it when open.
   (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)
8. Every detail region's id is `balances-detail-N` from a module-level counter that is never
   reset, is unique within the document, and is derived from no member id. Two transfer rows
   naming one pair produce two regions with two ids.
   (scenario: `a_debt_split_across_two_payments_shows_each_share_of_the_whole`)
9. A visible open or closed indicator sits inside each button, told apart by a character and
   not by colour alone, and carries `aria-hidden="true"`.
   (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)
10. Opening or closing a row changes no hash, calls no `pushState` and no `replaceState`,
    scrolls nothing, re-renders no other row and closes no other row.
    (scenarios: `opening_a_payment_changes_no_route_and_no_history`,
    `a_second_payment_opens_without_closing_the_first`)
11. The row's sentence is byte for byte what task 12 rendered: `Jo pays Sam 10.50`, payer
    first, the amount inserted exactly as received, inside its own `.balances-figure` span.
    (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)
12. **A transfer with no usable provenance renders inert**, exactly as task 12 rendered it:
    one `<span class="balances-line">` child, no `<button>`, no `aria-expanded`, no detail
    region, no indicator and no pointer cursor. "Usable provenance" is exactly this
    predicate, and nothing looser: `payer_debts` and `receiver_credits` are both arrays,
    both non-empty, and every element of both is an object whose `debtor_id`, `creditor_id`,
    `amount` and `debt_total` are all strings and which has a `covers_whole_debt` property.
    (scenario: `a_transfer_row_without_provenance_is_not_tappable`)
13. One malformed transfer renders inert without throwing and without affecting any other
    row: the net list, the currency line and the other transfer rows all still render, and
    the other rows are still buttons.
    (scenario: `a_transfer_row_without_provenance_is_not_tappable`)
14. `#balances-drill-hint` is shown only when at least one rendered transfer row is a
    button, and is hidden in every other state: the busy state, the failure state, the
    empty-roster state, an empty transfer list and an all-inert list included.
    (scenarios: `opening_a_suggested_payment_shows_both_ends_of_it`,
    `a_transfer_row_without_provenance_is_not_tappable`)
15. Two payments can be open at once, and two debts inside one payment: opening the second
    leaves the first open, with its `aria-expanded` still `"true"` and its region still
    visible.
    (scenario: `a_second_payment_opens_without_closing_the_first`)

### What one open payment shows

16. An open payment shows the debts from **both** ends: `payer_debts` under a label naming
    the payer, `receiver_credits` under a label naming the receiver, both in the order the
    arrays arrived, nothing sorted, filtered, merged or deduplicated.
    (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)
17. The shape is chosen from ids alone: **direct** when both arrays hold exactly one row and
    the two rows name the same pair; **passing through** when no row of `payer_debts` has a
    `creditor_id` equal to `to_member_id`; **mixed** otherwise. No amount string is compared,
    measured, parsed or converted to make this choice.
    (scenarios: all three shape scenarios)
18. The direct shape shows exactly one debt list, built from `payer_debts`, under
    `This payment settles what Jo owes Sam directly.`, with no label above it, and never
    shows the same debt row twice under two labels.
    (scenario: `a_payment_that_settles_one_debt_directly_shows_it_once`)
19. The passing-through shape shows `Jo and Sam have not shared an expense. These are the
    debts on each side of this payment.` above both lists, and the mixed shape shows no such
    sentence.
    (scenarios: `a_payment_to_someone_you_never_shared_an_expense_with_says_why`,
    `opening_a_suggested_payment_shows_both_ends_of_it`)
20. The passing-through and mixed shapes both close with `The same payment seen from each
    end. These are not two payments.` The direct shape does not.
    (scenarios: `opening_a_suggested_payment_shows_both_ends_of_it`,
    `a_payment_that_settles_one_debt_directly_shows_it_once`)
21. **No path is drawn.** Nothing renders a chain, an arrow between three members, an
    intermediate member or a "via" clause. In the passing-through scenario, the rendered text
    of the open payment names no member other than the ones its two lists name.
    (scenario: `a_payment_to_someone_you_never_shared_an_expense_with_says_why`)
22. Every absorbed debt in both arrays is rendered. No list is truncated, capped, collapsed
    behind a "show more", or reduced to the largest few.
    (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)
23. The screen shows no total of either list, no count of debts, and no sentence claiming a
    list adds up to the transfer amount.
24. The two labels read `What <payer> owes` and `What <receiver> is owed`, both names through
    `balancesName`, so ` (you)` and `Unknown member` apply to them as everywhere else.
    (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)

### A debt row

25. A debt row reads `<Debtor> owes <Creditor> <amount>` when `covers_whole_debt === true`,
    and `<Debtor> owes <Creditor> <amount> of <debt_total>` for every other value, `false`
    and an unexpected type alike. The clause is chosen by that one strict equality and by
    nothing else, and the fallback is the reading that states both figures and claims
    nothing.
    (scenarios: `a_payment_that_covers_a_whole_debt_does_not_say_of_itself`,
    `opening_a_suggested_payment_shows_both_ends_of_it`)
26. Both amount strings are inserted exactly as received: nothing rounded, no separator added
    or removed, no symbol prepended, no minus sign anywhere, each in its own
    `.balances-figure` span.
    (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)
27. The same pair appearing in two different open payments renders in both, each with its own
    portion and the same whole. Nothing is deduplicated across rows and nothing is added up
    across rows.
    (scenario: `a_debt_split_across_two_payments_shows_each_share_of_the_whole`)
28. The same pair appearing in both lists of one payment renders in both.
    (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)
29. A `debtor_id` or `creditor_id` with no roster entry renders as `Unknown member` and the
    row is still shown. No member id is ever rendered as visible text, at any level, in any
    state, the failure state included.
    (scenario: `a_member_missing_from_the_roster_still_shows_the_debt`)
30. The acting member's name carries ` (you)` inside a drill-down exactly as it does in the
    two outer lists, through the same `balancesName`.
    (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)
31. Debt rows render in the order their array arrived, at both levels.
    (scenario: `opening_a_suggested_payment_shows_both_ends_of_it`)

### Expanding a debt to its expenses

32. Each debt row holds a `<button type="button">` with `aria-expanded` and `aria-controls`,
    and a sibling region carrying `hidden` when closed, built by the same pattern as the
    transfer row.
    (scenario: `opening_a_debt_lists_the_expenses_behind_it`)
33. The first expansion of a debt row calls `api.debt(debtorId, creditorId)` exactly once
    with that row's two ids, and the recorded request path is
    `GET /api/debts/<encoded debtor>/<encoded creditor>`. Nothing requests entries on
    entering the route, on opening the payment above, or for a row that was never opened.
    (scenario: `opening_a_debt_lists_the_expenses_behind_it`)
34. Collapsing and re-expanding a row that already has its entries makes no second request.
    Collapsing and re-expanding a row whose request **failed** makes a fresh one.
    (scenarios: `the_expenses_behind_a_debt_are_asked_for_once`,
    `a_debt_whose_expenses_do_not_arrive_says_so_and_can_be_asked_again`)
35. At the moment the request goes out, the region is already unhidden, already carries
    `aria-busy="true"`, and its `role="status"` line already reads `Looking up the expenses
    behind this.` The button is not disabled. When the request settles, `aria-busy` is
    removed.
    (scenario: `the_waiting_line_is_on_screen_before_the_request_goes_out`)
36. One entry renders as three parts in this order: a first line holding the description and
    the amount; a second line holding the effect sentence; and the date, spelled by the
    feed's `feedDate` so one ledger has one date spelling. The date element carries a
    `datetime` attribute holding `created_at` unchanged.
    (scenario: `opening_a_debt_lists_the_expenses_behind_it`)
37. The second line is exactly one of the four rows of the table in "The exact words",
    chosen from `kind` and `effect` and from nothing else.
    (scenario: `opening_a_debt_lists_the_expenses_behind_it`)
38. An entry whose `kind` is `settlement` renders the literal `A settlement` as its
    description, whatever its `description` field holds, and never `No description`.
    (scenario: `opening_a_debt_lists_the_expenses_behind_it`)
39. An entry with an unrecognised `kind` or an unrecognised `effect` still renders its first
    line and its date, omits the second line, and does not throw or blank the list. Its
    description is treated as an expense's.
    (scenario: `opening_a_debt_lists_the_expenses_behind_it`)
40. An expense entry whose description is empty or whitespace only renders as
    `No description`.
    (scenario: `opening_a_debt_lists_the_expenses_behind_it`)
41. `entries` renders in the order it arrived, newest first as the server sent it.
    `app/app.js` still contains no `.sort(` and no `.reverse(`.
    (scenario: `opening_a_debt_lists_the_expenses_behind_it`)
42. An `entries` array that is empty shows `Nothing is recorded behind this debt.` in the
    status line, renders no list, and is not treated as a failure. An empty region is never
    shown.
    (scenario: `a_debt_with_nothing_behind_it_says_so_rather_than_failing`)
43. A failed request shows `Those expenses could not be listed just now.` in that row's
    status line and nowhere else. The same sentence for every one of the six kinds; the
    screen never reads `error.status`, `error.code`, `error.kind` or `error.say`, and never
    renders a server sentence here, because the one this route composes for its own 400
    names a member id. The transfer above stays open, its debt rows stay listed, the net list
    is untouched and `#balances-error` stays hidden.
    (scenario: `a_debt_whose_expenses_do_not_arrive_says_so_and_can_be_asked_again`)
44. A 200 that is not the documented shape takes the failure path, not the empty path.
    `entries` missing, `entries` not an array, or any element that is not an object carrying
    string `id`, `kind`, `effect`, `description`, `created_at` and `amount` all make the
    whole response a failure.
    (scenario: `a_debt_that_answers_with_the_wrong_shape_is_a_failure_not_an_empty_debt`)
45. The screen registers no handler with `api.onUnauthenticated`, `api.onNotLinked` or
    `api.onOffline` for this request either: the balances region still contains none of those
    three names.
46. An answer that arrives after the transfer list has been rebuilt is written only into the
    row that asked for it, which is no longer in the document, and never into the new list.
    (scenario: `leaving_the_balances_screen_and_returning_closes_every_drill_down`)
47. Both disclosure handlers call `ledgerIsUp()` before doing anything, and return having
    changed nothing when it is false: no toggle, no request, no message. `ledgerIsUp` is
    called, never reimplemented, and the region contains no second copy of the question.
    (scenario: `a_drill_down_behind_a_curtain_asks_for_nothing`)
48. A 401 answering a drill-down request is the gate, exactly as task 9a built it, and the
    balances screen adds nothing to it: `#balances-error` stays hidden and no second sentence
    appears anywhere outside the row.
    (scenario: `a_401_on_a_drill_down_is_the_gate_and_not_this_screens_message`)

### Keyboard, focus and announcement

49. Both controls are real `<button type="button">` elements. The balances region contains no
    `createElement('a')`, `createElement('details')`, `createElement('summary')`,
    `tabindex`, `onclick`, and no `keydown`, `keyup`, `keypress`, `pointerdown` or
    `touchstart` listener. Every `setAttribute` in the region names its attribute with a
    single-quoted literal, every `setAttribute('role', X)` has `X` equal to `'status'`, and
    the region assigns no `.role` property.

    > **Amended 2026-09-06, after the first review of PR #56.** The list above used to hold
    > `setAttribute('role'` as a twelfth banned byte sequence, alongside the others. That
    > contradicted criterion 51 of this same file, which requires a `role="status"` live
    > region inside every debt region: markup cannot ship a region built at run time, so the
    > shipped code has to set that role, and the ban forbade the only way to do it.
    >
    > The first fix was an indirection, `var LIVE_REGION = 'role';`, which satisfied the
    > letter of the ban and was the wrong answer. It made the ban weaker, not stronger:
    > `setAttribute(LIVE_REGION, 'button')` passed it, so anyone rebuilding a button out of a
    > div had a sanctioned, documented way through. The ban was porous before that anyway,
    > blind to `setAttribute("role"` with double quotes, to a template literal and to
    > `el.role = 'button'`. And it bought nothing, because what criterion 49 actually means is
    > asserted behaviourally and is unaffected: `button.tagName === 'BUTTON'`,
    > `button.type === 'button'`, and a transfer region's children each reporting a `role` of
    > `null`.
    >
    > So the ban moves to what it always meant. Forbidding a hand-set interactive role is kept
    > and widened, permitting the one role criterion 51 requires is added, and the word `role`
    > stays in `app/app.js` where a reader and a grep can both find it. The literal-attribute
    > rule is what closes the indirection for good. Criterion 70 carries the same change.
50. The balances region contains no `.focus(`. Focus is never moved by this task, in either
    direction, and no scenario asserts focus movement.
51. Each debt region holds exactly one `role="status"` element, holding only the waiting,
    failure or nothing-recorded sentence, with the entry list as its sibling rather than its
    child. A transfer region holds no `role="status"` element and no `aria-busy`.
    (scenario: `opening_a_debt_lists_the_expenses_behind_it`)
52. Both button classes carry a `:focus-visible` rule with a visible outline, so a keyboard
    user can see which control they are on.

### Refreshing, leaving and failing

53. Entering the balances route still makes exactly two requests, `GET /api/members` and
    `GET /api/balances`, and no drill-down request. The count of requests on entry does not
    grow with the size of the plan.
    (scenario: `opening_a_payment_changes_no_route_and_no_history`)
54. Leaving the route and returning rebuilds every row closed, with no detail region open, no
    entries kept and no drill-down request replayed.
    (scenario: `leaving_the_balances_screen_and_returning_closes_every_drill_down`)
55. The busy state and the failure state clear both lists exactly as task 12 built them, and
    `balancesClear()` also hides `#balances-drill-hint`, so no open drill-down and no hint can
    survive a refresh or sit beside a failure message.
56. There is still no polling, no timer, no interval and no automatic retry anywhere in the
    region: the existing ban on `setTimeout`, `setInterval`, `requestAnimationFrame`,
    `localStorage`, `sessionStorage` and `indexedDB` in the balances region still passes.

### Names, escaping and money

57. Every server-provided string reaches the DOM through `textContent` or `createTextNode`,
    at every level. `app/app.js` still contains no `innerHTML`, `outerHTML`,
    `insertAdjacentHTML` or `document.write`.
58. `app/app.js` still contains none of `toFixed`, `parseFloat`, `parseInt`, `Number(`,
    `Math.round`, `Math.floor`, `/ 100`, `Intl`, `toLocaleString`, `NumberFormat`, or the
    literal `0.00`. The screen does no arithmetic on an amount and no comparison of two
    amounts, anywhere, at any level.
59. `app/app.js` still contains none of `fetch`, `fetch(` or `/api`, in code or in a comment,
    so `test_the_narrowed_rule_still_bites` passes unchanged.
60. No file under `app/` gains money formatting, cent arithmetic, rounding, a currency symbol
    or a locale-aware number call. `app/index.html`, `app/styles.css` and `app/app.js`
    contain no `$`, `£` or `€`, and no CSS rule inserts a glyph through `content`.
61. Every dynamic node is reached through a closure, never through
    `document.querySelector('.some-new-class')`: every `getElementById('...')` and
    `querySelector('.…')` literal in `app/app.js` still names something present in
    `app/index.html`, so `test_every_element_the_router_reaches_for_exists_in_the_document`
    passes unchanged.

### Layout

62. All new CSS is appended at the end of `app/styles.css`, inside the existing
    `/* Balances --- */` block, every selector prefixed `.balances-`, with no existing rule
    modified. `.balances-row`'s `display: flex` is overridden for transfer rows through a new
    class on the `<li>` and a new rule, never by editing the old one.
63. Every `min-height` in `app/styles.css` is at least 44 px and every `font-size` is at least
    16 px, so `test_no_rule_sets_a_hit_area_below_forty_four_pixels`,
    `test_every_transfer_row_clears_the_hit_area_floor` and
    `test_no_rule_sets_a_font_size_below_sixteen_pixels` pass unchanged. Both disclosure
    buttons carry their own `min-height` of at least 44 px and full-width padding, so the
    whole row is the target with no dead strip.
64. `.balances-figure` stays the only selector in the balances block carrying
    `white-space: nowrap`, so `test_a_long_display_name_wraps_rather_than_being_cut_off`
    passes unchanged, and no new rule adds `text-overflow` or `overflow: hidden`.
65. `cursor: pointer` appears only on `.balances-transfer-button` and `.balances-debt-button`,
    and `pointer` is the only `cursor` value in the block.
66. No `animation`, `transition` or `@keyframes` is added, so the reduced-motion block at the
    end of the file still has nothing on this screen to switch off, and opening a row is
    instant.
67. No `row-reverse`, no `column-reverse`, no `order` property and no absolute positioning:
    visual order matches DOM order at every level, and an amount is never read before the name
    it belongs to.
68. At 320, 360 and 390 CSS px, with a 40 character display name and a payment open with a
    debt open inside it, the `.content` element's `scrollWidth` equals its `clientWidth`, and
    so does every element inside the balances region that a name is interpolated into.
    Nesting is shown with indentation small enough that the third level still fits, or with a
    rule and no indentation at all. (browser check)

    > **Corrected 2026-09-06, after the first review of PR #56.** This criterion used to
    > measure `document.documentElement.scrollWidth` against its `clientWidth`. On this shell
    > that comparison is blind to the failure it was written to catch: `app/styles.css` sets
    > `body { overflow: hidden; }` and the element that scrolls is `.content`, which has
    > `overflow-y: auto` and therefore a computed `overflow-x: auto`. Overflow inside
    > `.content` is contained there and clipped at `body`, so the document element's
    > scrollWidth equals its clientWidth whether or not a name is running out of its box.
    > Running the old check in a browser would have gone green and meant nothing, which is
    > why three name-carrying classes shipped without `overflow-wrap: break-word` and no
    > check on this branch could see it. The measurement moves to the element that actually
    > scrolls, and to the boxes the text is in. The general case, that any future task
    > inheriting this line inherits the blind spot, is filed as issue #58 and is not fixed
    > here.

### Automated tests: Python

69. `tests/test_web_shell.py` gains a test that `#balances-drill-hint` sits inside
    `<section id="screen-balances">`, between the `Suggested payments` heading and
    `#balances-transfers`, outside `#balances-status`, ships with the `hidden` attribute, and
    holds exactly `Open a payment to see the debts behind it.` `BALANCES_IDS` gains
    `balances-drill-hint` so `test_the_balances_section_carries_every_id_the_screen_toggles`
    passes.
70. `test_no_transfer_row_pretends_to_be_tappable` is **replaced** by a test whose name says
    what is now true, carrying exactly criterion 49 as amended: the ten remaining bans, the
    literal-attribute rule, the `role` value rule and the `.role` property rule. Three of task
    12's bans are dropped: `createElement('button')`, `aria-expanded` and
    `addEventListener('click'`. Its comment records that the row is now a disclosure, why the
    list shrank, and why `role` is reasoned about rather than forbidden.

    > **Amended 2026-09-06, after the first review of PR #56.** This line used to read
    > "keeping exactly the bans of criterion 49 and dropping exactly three". Criterion 49 no
    > longer bans `setAttribute('role'` outright, for the reasons recorded under it, so this
    > one changes with it: the same test, one absence swapped for three rules that say what
    > that absence was for. The three dropped bans are unchanged, and no other ban moves.
71. `test_nothing_asks_for_provenance_that_is_not_in_the_payload` is **deleted**. It asserts
    the opposite of this task. It is not renamed, not kept alongside and not xfailed.
72. `test_the_balances_block_offers_no_affordance_that_does_nothing` is **replaced** by a test
    that still forbids a `content:` declaration anywhere in the block, and that asserts every
    rule carrying `cursor` names one of the two disclosure button classes and sets it to
    `pointer`.
73. Every other task 12 test in `tests/test_web_shell.py` passes untouched, by name:
    `test_the_status_region_announces_and_ships_every_message_hidden`,
    `test_the_two_lists_ship_empty_under_headings_in_the_stated_order`,
    `test_the_balances_screen_reimplements_no_money_handling`,
    `test_the_shell_builds_rows_without_parsing_markup`,
    `test_the_shell_never_reorders_what_the_server_sent`,
    `test_the_balances_screen_keeps_no_copy_of_a_derived_figure`,
    `test_the_balances_screen_registers_none_of_the_three_global_handlers`,
    `test_every_balances_selector_is_namespaced_to_this_screen`,
    `test_the_balances_block_never_moves_a_row_out_of_document_order`,
    `test_every_transfer_row_clears_the_hit_area_floor`,
    `test_a_long_display_name_wraps_rather_than_being_cut_off`,
    `test_no_row_carries_its_meaning_in_colour_alone`,
    `test_no_shell_file_prints_a_currency_symbol`,
    `test_the_balances_block_adds_no_animation`, `test_no_screen_shows_invented_data`,
    `test_every_element_the_router_reaches_for_exists_in_the_document`,
    `test_only_the_api_client_calls_the_back_end`, `test_the_narrowed_rule_still_bites`,
    `test_app_holds_exactly_the_promised_files` and
    `test_the_worker_precaches_exactly_the_shell`.
74. **No new test asserts that a string is present in `app/app.js` in order to claim a
    rendering behaviour is covered.** Bans are permitted, because a ban is falsified by one
    occurrence. No test in `tests/test_web_api.py` or `tests/test_balances.py` is added or
    changed.

### Automated tests: the JavaScript harness

75. `tests/shell_harness.mjs` gains exactly two things in its DOM stub, each with a one line
    comment naming the shipped code that reaches for it: `document.createTextNode`, returning
    a node of the `{ text: ... }` shape the existing `textContent` getter already understands,
    and an element `id` property reflected off the `id` attribute the way `hidden` and `type`
    already are. Nothing else about the stub is loosened, and the guarded proxy keeps refusing
    anything undefined. (`type` is already present and needs nothing.)
76. Scenarios locate a dynamic region through its button's `aria-controls` and
    `page.query('#' + id)`, never through `page.el(...)`, which only knows the ids parsed out
    of `app/index.html` and throws a harness error for anything else.
77. Every new scenario declares its exact ordered request list through `expectRequests` and
    registers an answer for every call it makes. New scenarios, each named as a sentence, each
    appended to the harness list and to `SCENARIOS` in `tests/test_shell_behaviour.py` so the
    two stay exactly equal, in this order:
    - `opening_a_suggested_payment_shows_both_ends_of_it` (the mixed fixture)
    - `a_payment_to_someone_you_never_shared_an_expense_with_says_why`
    - `a_payment_that_settles_one_debt_directly_shows_it_once`
    - `a_debt_split_across_two_payments_shows_each_share_of_the_whole` (task 5's chain)
    - `a_payment_that_covers_a_whole_debt_does_not_say_of_itself`
    - `a_transfer_row_without_provenance_is_not_tappable`
    - `a_second_payment_opens_without_closing_the_first`
    - `opening_a_debt_lists_the_expenses_behind_it`
    - `the_waiting_line_is_on_screen_before_the_request_goes_out`
    - `the_expenses_behind_a_debt_are_asked_for_once`
    - `a_debt_whose_expenses_do_not_arrive_says_so_and_can_be_asked_again`
    - `a_debt_with_nothing_behind_it_says_so_rather_than_failing`
    - `a_debt_that_answers_with_the_wrong_shape_is_a_failure_not_an_empty_debt`
    - `a_member_missing_from_the_roster_still_shows_the_debt`
    - `a_drill_down_behind_a_curtain_asks_for_nothing`
    - `a_401_on_a_drill_down_is_the_gate_and_not_this_screens_message`
    - `opening_a_payment_changes_no_route_and_no_history`
    - `leaving_the_balances_screen_and_returning_closes_every_drill_down`
78. No existing scenario is weakened, renamed, deleted or turned into a source-text assertion,
    and no new scenario asserts focus movement, a cached session view, an `aria-current` value
    or the escaping of markup. Running the harness with no substitutions passes every scenario
    and exits 0, and all six mutant tests still pass unchanged, still exiting 1 and still
    naming the scenarios they name today.

### The service worker

79. `app/sw.js` is edited on exactly one line: `SHELL_DIGEST` is set to the twelve hex
    characters `test_the_recorded_digest_matches_the_files_it_covers` prints when it fails,
    pasted verbatim. `VERSION` is **not** bumped, `SHELL` is unchanged, and nothing else in
    the file moves. That test is never skipped, loosened, xfailed or deleted, and no file is
    added to or removed from `app/`.

### The suite

80. `uv run python -m pytest` passes, with nothing skipped and nothing xfailed, and the pass
    count is master's 2172 plus exactly the tests this task adds. Plain `uv run pytest` fails
    on this machine with an access-denied spawn error and is not the command.

---

## Verified by hand

Browser only. Record each as checked, against a store seeded by `scripts/setup_group.py` and
served with `uv run python scripts/serve.py --store ledger.sqlite3`. Tick "Update on reload"
in DevTools, Application, Service Workers first, or the cached shell serves the old `app.js`.

- Seed a ledger that produces a payment between two people who have never shared an expense.
  Open it and read it aloud: it explains itself without anybody asking a question.
- Seed task 5's chain, open both payments, and confirm the split debt reads as one debt in
  two parts rather than as two debts.
- A payment covering a whole single debt reads simply and does not say "of" the same figure
  twice.
- Open a debt, collapse it, open it again: the Network panel shows one request, not two.
- Stop the server, open a debt, and confirm the failure message appears inside that row with
  the rest of the screen intact. Restart it, collapse, and re-expand: the entries arrive.
- With VoiceOver or NVDA: the payment button announces collapsed and expanded, the debt button
  does too, the waiting line and the failure line are spoken when they appear, and a closed
  region is reachable by neither the screen reader nor find-in-page.
- Tab through an open payment: focus lands on the payment button, then on each debt button, in
  visual order, Enter and Space both toggle, and the focus ring is visible on both.
- A display name containing `<`, `&` and a quote renders as those characters at every level.
- At 320x568, 360x640, 390x844 and landscape 844x390, with a 40 character display name and a
  payment open with a debt open inside it: no horizontal scroll, nothing clipped, the amounts
  whole, and the deepest row reachable above the nav.
- Console is clean on entry, on opening and closing rows, after a failed drill-down request,
  and after signing back in.

## Out of scope

- **Any change to `src/splitwise_lite/`, including `web.py`.** Task 12a shipped everything
  this task reads. If something is missing, it is raised, not added from here.
- **Any change to `app/api.js`.** `api.debt` exists and is enough. A screen task inventing a
  second client function beside it is a merge conflict for work that has nothing to do with a
  drill-down.
- **Registering a route, or anything endpoint-adjacent.** Issue #14 records that
  `_API_ENDPOINTS` in `web.py` is a hand-written literal set and that `_before_request`
  returns early for anything absent from it, so a route registered without a matching entry is
  served with no session check at all. That is a real trap and it belongs to whoever adds the
  next endpoint. This task adds none.
- **Deriving anything in the front end.** No computing which expenses lie behind a pair from
  `GET /api/expenses`, no summing a provenance list, no comparing two amount strings, no
  checking that a list adds up to a transfer.
- **Path provenance.** No chain, no intermediate member, no "Jo owes Ali who owes Sam". Task 5
  refused to compute it and this task does not draw it from two ends and pretend.
- **Mark as paid, settlement creation, pending or awaiting-confirmation rows.** Tasks 14 and
  15. A confirmed settlement appears inside a debt's entries because it moved the debt; that
  is reading history, not offering an action.
- **The incompleteness signal.** Task 16. This screen keeps the one honest sentence task 12
  gave it.
- **Distinguishing a never-used ledger from a settled one.** Still a known gap with a named
  cause, still task 16's.
- **A fourth route, a modal, a bottom sheet, a full-screen detail view or any navigation
  change.** `ROUTES` keeps exactly three entries. A modal on a phone needs a focus trap, an
  escape handler, a scroll lock and an inert background, and the feed already decided an
  inline disclosure instead.
- **An Escape handler, a close button, a "collapse all" control, or single-open behaviour.**
- **Deep linking to an open drill-down**, remembering which rows were open across a
  navigation, or restoring scroll position.
- **Sorting, filtering, searching, grouping or totalling anything in a drill-down.**
- **Showing a debt that no transfer absorbed**, a per-member debt browser, or a "see all
  debts" view.
- **Rendering the debt endpoint's top-level `amount` or `direction`**, or reconciling them
  against the row that opened the request. Two reads of a moving ledger may differ, and the
  screen is in no position to say which is right.
- **Editing, voiding or correcting an expense from a drill-down.** Task 17.
- **Linking a drill-down entry to the feed screen.** It needs a route with an expense id in
  it, which is a navigation change.
- **Currency symbols, locale formatting, relative dates, "3 days ago", or a second date
  spelling.** `feedDate` is the one spelling.
- **Bumping `VERSION` in `app/sw.js`, or touching anything in it but `SHELL_DIGEST`.**
- **A JavaScript test runner, a bundler, a framework, ES modules, a linter or a formatter.**
- **Any new dependency in either language**, runtime or dev.
- **Docs.** `CLAUDE.md` and `README.md` are unchanged: nothing about how the app is run,
  installed or tested changes here.

## Constraints

- Files to modify: `app/index.html`, `app/app.js`, `app/styles.css`, `app/sw.js` (one line),
  `tests/test_web_shell.py`, `tests/shell_harness.mjs` and `tests/test_shell_behaviour.py`.
  **Nothing else.**
- No file is created and no file is deleted. Nothing is added to or removed from `app/`, so
  `test_app_holds_exactly_the_promised_files` and `test_the_worker_precaches_exactly_the_shell`
  pass unchanged.
- **Nothing under `src/splitwise_lite/` is modified, and neither is `app/api.js`.** If a
  criterion appears to need a field, a widened payload or a new endpoint, **stop and raise it
  loudly**.
- `app/manifest.json`, everything under `app/icons/`, everything under `scripts/`,
  `tests/test_web_api.py`, `tests/test_balances.py`, `tests/test_dev_server.py`, every other
  test file, `pyproject.toml`, `uv.lock`, `CLAUDE.md`, `README.md`, `plans/backlog.md`,
  `plans/spec.md` and everything under `.claude/` are not modified.
- **No new dependency of any kind, in either language.** Nothing is added to `pyproject.toml`,
  no `package.json` is created, and `.claude/hooks/guard-deps.hs.sh` blocks the ad hoc Python
  route anyway. Per CLAUDE.md a dependency is declared then installed with `uv sync`, never
  `pip install` or `uv pip install`. If something here genuinely cannot be built without a
  package, stop and get the user's approval first.
- **Every change in `app/` stays inside the balances screen's transfer list.** In
  `app/index.html`, one paragraph added inside `<section id="screen-balances">`; the head,
  header, gate, notice, feed and add sections, the nav and the script tag are untouched. In
  `app/app.js`, edits only inside the balances region, from the
  `/* --- The balances screen ---` banner to the end of the file, with no function above it
  edited, `showApp()` included. In `app/styles.css`, rules appended at the end of the file in
  one block. The net list, the currency line, the status region and the four fixed messages
  are untouched.
- The region may **call** three things defined above it and must modify none of them:
  `ledgerIsUp`, `feedDate` and `feedInstant`. It defines its own small element builder beside
  `balancesFigure` rather than calling `feedText`: a date spelling is a product rule that must
  not be duplicated, a three line element builder is not, and the region boundary is what
  keeps these merges trivial.
- Every element id and class this task adds is prefixed `balances-`.
- JavaScript is plain, browser-native, classic (non-module) script, in the style already in
  `app/app.js`: an IIFE, `'use strict'`, `var`, named functions, single-quoted strings. No
  framework, no polyfill, no transpilation, no minification. The committed file is the file
  the browser runs.
- Element lookups stay `document.getElementById('literal-id')` and
  `document.querySelector('.literal-class')`, single quoted, and name only things present in
  `app/index.html`. Dynamic nodes are reached through closures.
- Every URL and asset reference stays relative. No absolute `http://` or `https://` anywhere
  under `app/`.
- Money is a string from the server and is passed straight through. The front end does no
  arithmetic, no formatting, no comparison and no parsing of an amount, ever. Every decision
  that depends on a comparison of cents arrives as a field: `direction`, `covers_whole_debt`
  and `effect`.
- All ordering is the server's, at every level: `net`, `transfers`, `payer_debts`,
  `receiver_credits` and `entries`.
- New tests are appended at the end of `tests/test_web_shell.py`. The only pre-existing tests
  that change are the three named in criteria 70 to 72: one deletion and two replacements, plus
  the one-line addition to `BALANCES_IDS`.
- New scenarios are appended to the scenario list in `tests/shell_harness.mjs` and to
  `SCENARIOS` in `tests/test_shell_behaviour.py`, and the two stay exactly equal. Scenario
  fixtures are locals inside their scenario rather than module constants threaded into the
  fixtures above, following the 12a scenario's own note: one appended block conflicts with
  less on a file other branches are editing.
- Tests run with `uv run python -m pytest`. No test is skipped or xfailed, no test binds a
  socket, and assertions are exact, per `.claude/rules/testing.md`.
- Every non-obvious choice made here gets a one line comment where it is implemented, so the
  next person does not undo it by tidying: why both provenance lists are shown, why the direct
  shape collapses to one, why the shape is chosen from ids and never from amounts, why
  `debt_total` is on the row, why the second request is lazy and per row, why a re-expansion
  after a failure asks again, why the detail id comes from a sequence number, why the region is
  revealed before the waiting sentence is written, why the failure sentence is fixed rather
  than the server's, why the endpoint's own `amount` and `direction` are ignored, and why a
  transfer without provenance renders inert.
- **This file must not be modified, with one exception: a statement in it that is provably
  wrong may be corrected**, following the precedent tasks 5, 9b and 11 set. Sharpening a
  criterion, re-scoping one or softening one to suit an implementation is not covered and stays
  forbidden. Every correction carries a dated marker saying what the file used to say, what it
  says now and why, as the 2026-09-06 section at the top does.
