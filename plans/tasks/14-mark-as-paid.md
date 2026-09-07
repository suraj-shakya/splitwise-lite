# Task 14: Mark as paid

**Depends on:** 6 (complete, on `master`), 12 (complete, on `master`), and in practice also
9a, 9b, 12a and 13, all complete on `master`. Everything this task reads exists today and is
quoted from the shipped source below.

**Consumed by:** task 15 / issue #16 (receiver confirmation), and transitively task 18 /
issue #19 (the end-to-end smoke test). "What #16 needs from this" at the end of this file is
part of the deliverable, not a note.

Sharpened from `plans/backlog.md` task 14, GitHub issue #15. The backlog entry stays as
written; this file is the implementable version.

---

## Goal

The payer of a suggested payment can record that they really transferred the money, and that
record changes no balance. The claim appears, in the same words, on every member's phone as a
payment awaiting confirmation, and the suggested payment it answers stays exactly where it
was, because until the receiver confirms, nothing has moved.

## Why this task is easy to get wrong

The spec names the hazard directly, in "Receiver-confirms introduces an undefined state":

> When Sam marks a $40 payment and Ali has not confirmed it, the group balance is ambiguous.
> Resolution: the balance does not move until the receiver confirms. Pending payments render
> as a separate "awaiting Ali" row. Without this, two people see two different versions of
> the truth.

Two failures follow from getting it wrong, and they are opposites:

* **A balance that moved.** A pending settlement that reaches `derive_balances` clears a debt
  nobody has agreed was paid. Criterion 20 exists to make that fail loudly.
* **A payment that vanished.** A screen that quietly drops the suggested transfer once
  somebody claims to have paid it shows a cleared debt that is not cleared. Criterion 45
  exists for that one.

The design below refuses both by keeping them in different places: the ledger fold is
untouched, and the claim is rendered as its own thing beside the plan rather than folded into
it.

## The vocabulary already exists

Nothing here is invented. `src/splitwise_lite/events.py` shipped with task 2 and says:

* `SettlementEvent` is "a proposed payment from one member to another, recorded when it is
  claimed", carrying `id`, `group_id`, `currency`, `from_member_id`, `to_member_id`,
  `amount_cents`, `created_at` and `created_by`. It "is born pending and carries no state
  field, because a mutable state field on an immutable event is a contradiction."
* `SettlementState` is `PENDING`, `CONFIRMED`, `REJECTED`. `PENDING` "is the state of a
  settlement with no decision yet."
* `SettlementDecisionEvent` is the receiver's answer. **This task appends none.** A settlement
  with no decision is pending by definition, so marking a payment as paid is one append and
  nothing else.
* The module docstring already states the rule this task must not break: "only confirmed
  settlements enter the balance fold. A pending settlement moves no balance, and neither does
  a rejected one."

`src/splitwise_lite/balances.py` already implements it, at line 247:

    for settlement in settlements:
        if states[settlement.id] is not SettlementState.CONFIRMED:
            continue

and `balances.settlement_states(events)` returns one entry per `SettlementEvent`, `PENDING`
for a settlement no decision references, reaching the same code path `derive_balances` does,
"so a rendered state and a balance can never disagree about whether a settlement counted."

`store.EventStore.append_settlement` already exists and already refuses the wrong group, the
wrong currency, a duplicate id and an over-large amount.

**So the domain layer needs no change at all.** This task is an HTTP endpoint, a widened
balances payload, and a screen. If an implementer finds themselves editing `events.py`,
`balances.py`, `simplify.py` or `store.py`, they have taken a wrong turn: stop and raise it.

## Who may mark a payment as paid, and how the server enforces it

**The acting member is the payer, always, and the payer is never named in the body.**
`from_member_id` and `created_by` both come from `flask.g.member.id`, exactly as
`_create_expense` takes `created_by` from there today. `_require_keys` already refuses an
unrecognised key, so a body that names `from_member_id`, `created_by`, `created_at`, `id`,
`currency` or `group_id` is a 400 `malformed_request` with no special code written for it.

This is a structural rule, not a check that could be forgotten: **there is no code path by
which one member can record a payment as coming from another.**

Why it must be this way, and not `_create_expense`'s rule that "`payer_id` may be any member
of the group": an expense is settled by two people agreeing that it happened, and the balance
it produces is derived from a fact both can see. A settlement is settled by exactly one
person, the receiver, in task 15. If either end could create a settlement, then the receiver
could create one **and** confirm it, and a debt would clear with the payer never having
touched the app. Payer-creates plus receiver-confirms is what makes a settlement need two
people. One rule without the other is worth nothing.

Consequences to state plainly rather than discover later:

* A member whose account nobody has linked cannot mark anything as paid. They get a 403
  `member_not_linked` from `_Access.MEMBER`, and the screen never offers them a button,
  because `balancesActingId()` returns `null` for them.
* A payment whose payer is an unlinked member cannot be recorded by anybody. That is a real
  gap of this design and it is accepted: the alternative is letting somebody else claim a
  payment on their behalf, which is exactly the hole above.
* A request from a member who is not the payer of anything is not refused by a rule about
  payers, because it cannot express the idea. It records **their own** payment to whoever
  they named. That is a legitimate act: a member may pay somebody outside the current
  simplified plan.

**The endpoint does not check the request against the simplify plan.** It does not require
that a transfer from the acting member to `to_member_id` exists, and it does not require the
amount to equal one. `balances.py` already states why, at the settlement fold:

> The amount is never validated against the pairwise debt it appears to clear. A settlement
> larger than the debt flips the pair, and "confirm in full or not at all" is a service and
> UI rule, not an arithmetic one.

The person is recording something that happened in the world. The ledger records what they
say happened; the receiver is the check. Validating against a plan that may have moved since
the screen was drawn would refuse real payments for a reason nobody could act on.

## The endpoint

    POST /api/settlements

registered as one row appended to `_API_ROUTES` in `src/splitwise_lite/web.py`:

    _ApiRoute(
        "/api/settlements", "create_settlement", _create_settlement, ("POST",),
        _Access.MEMBER,
    )

**Adding an endpoint is now one edit, and the access is not optional.** `_ApiRoute` gives
`access` no default, so a row that does not state what it requires is a `TypeError` at
import; `_audit_routes` refuses to build an app that serves a rule no row declares; and
`_before_request` refuses one at request time as a second line. The three sets of endpoint
names that used to have to be kept in step are gone. There is nothing else to register, and
nothing to add to a second literal.

CSRF, the session check and the member check all follow from that one row:
`_before_request` runs `_check_csrf()` for every state-changing method under `/api` with no
per-endpoint exemption, then `_authenticate()`, then `_acting_group()` and `_acting_member()`
for `_Access.MEMBER`. `app/api.js` already sends the `X-CSRF-Token` header on every unsafe
method. No new gate is written.

### The request body

    {"to_member_id": "...", "amount": "12.50"}

Exactly those two keys. `amount` is an amount **as a JSON string**, through
`_require_amount_str`, because "a number is something a client could have done arithmetic
on". It is parsed once with `money.parse_amount(text, group.currency)`, the one input edge.

The refusals, all before anything is written, all `MalformedRequest` (400,
`malformed_request`) unless named otherwise:

| what | answer |
|---|---|
| a missing, extra or misspelled key | 400 `malformed_request` |
| `to_member_id` not a JSON string | 400 `malformed_request` |
| `amount` not a JSON string (a number included) | 400 `malformed_request` |
| `amount` not parseable | 400 `invalid_amount`, from `money.parse_amount` |
| `to_member_id` not in this group's roster | 400 `malformed_request`, naming the id |
| `to_member_id` equal to the acting member | 400 `malformed_request` |
| a zero amount | 400 `malformed_request` |
| a negative amount | 400 `invalid_amount`, from `money.parse_amount` |
| an amount above `MAX_CENTS` | 400 `invalid_amount`, from `money.parse_amount` |
| a second pending settlement to the same receiver | 409 `settlement_already_pending` |

> **Correction, 2026-09-07.** Two rows of that table were wrong about which refusal a
> client actually gets, and both were checked against the shipped code before being
> changed. The file used to hold one row reading "a zero or negative amount | 400
> `malformed_request`" and one reading "an amount above `store.MAX_CENTS` | 400
> `amount_too_large`, from the store". Neither describes what happens.
>
> `money.parse_amount`'s grammar takes no sign at all, so a negative amount never
> reaches the view's own `cents <= 0` check: it is refused one step earlier, at the one
> input edge, as `InvalidAmount`, which is 400 `invalid_amount`. And `store.MAX_CENTS`
> **is** `money.MAX_CENTS` — `store.py` imports it from `money.py` — and `parse_amount`
> already refuses anything above it, so `store.AmountTooLarge` is unreachable from this
> endpoint and is an unreachable backstop rather than an answer a client can provoke.
>
> The status is 400 in every one of these cases either way, and the substance of
> criterion 8, that a zero and a self-pair are 400 and never the 500 an escaped
> `InvalidEvent` would produce, is unchanged and is tested. Only the codes are
> corrected, to the codes the endpoint really returns.

**Two of those rows are traps, and both are why the view checks rather than letting the
constructor do it.** `SettlementEvent.__post_init__` raises `InvalidEvent` for a non-positive
amount and for `from_member_id == to_member_id`, and `InvalidEvent` is **not** in
`ERROR_STATUS`, so it would reach the client as a generic 500 with the real reason in the log
only. So `_create_settlement` refuses both itself, with a sentence, before constructing the
event. The constructor stays as the backstop it is.

### At most one pending settlement per ordered pair

A second `POST` from the acting member to a receiver who already has a pending settlement
from them is refused with **409 `settlement_already_pending`**.

The endpoint therefore reads the ledger before it writes: `_store().list_events(group.id)`,
`balances.settlement_states(ledger)`, and a scan for a `SettlementEvent` whose
`from_member_id` is the acting member, whose `to_member_id` is the named receiver and whose
state is `PENDING`.

Why refuse rather than allow, and why an ordered pair:

* Allowing two admits a double count that only the receiver could catch. Task 15 confirms a
  settlement; two pending claims for one payment become two confirmations and the debt clears
  twice. That is the same class of failure as a balance moving early, and worse, because it
  reads as settled.
* The pair is **ordered**, not unordered: Jo claiming a payment to Sam and Sam claiming one
  to Jo are two different claims about two different transfers of money, and both may be
  true.
* The amount is not part of the rule. Two claims for different amounts between the same two
  people, in the same direction, is still the ambiguity this refuses.

The accepted cost, stated so nobody has to discover it: **a pending settlement blocks that
ordered pair until the receiver answers it**, and v1 gives the payer no way to withdraw a
claim. A `SettlementDecisionEvent` is `CONFIRMED` or `REJECTED` and task 15 makes it the
receiver's alone, so an unanswered claim stays. In a flat of three to five people who see
each other daily, chasing the receiver is the recourse. "Let the payer withdraw a claim" is a
real backlog candidate and is **not** built here.

### The response

`201`, body `{"settlement": <settlement view>}`, mirroring `_create_expense`'s
`{"expense": ...}` exactly.

A settlement view is `_settlement_view(settlement, state)`, and it is the **same** shape the
balances payload sends, so the screen has one builder and not two:

    {"id": "...",
     "from_member_id": "...", "to_member_id": "...",
     "amount": "12.50",
     "created_at": "2026-09-07T08:00:00.000000+00:00",
     "created_by": "...",
     "state": "pending"}

* `amount` is `format_amount` of the magnitude, no minus sign, like every amount on this
  wire.
* `created_at` is `isoformat(timespec="microseconds")`, spelled exactly as `_expense_view`
  and `_debt_entry_view` spell it, so `feedDate` reads it with no second parser.
* `created_by` is carried for the same reason `_expense_view` carries it. Today it always
  equals `from_member_id`; the screen renders it nowhere.
* `state` comes from `_SETTLEMENT_STATE_WIRE`, an explicit map over `SettlementState`,
  exhaustive and tested, exactly like `_ENTRY_KIND_WIRE` and `_ENTRY_EFFECT_WIRE`: renaming a
  domain member must not silently rename a JSON value a client branches on. Only `"pending"`
  is reachable in this task, and the map covers all three so task 15 adds values rather than
  adding a field.

## What the balances payload gains

`GET /api/balances` grows two things and nothing else. It stays one request, on one read of
one ledger, and that is the point: the transfers and the pending claims come from the same
`list_events` call at the same instant, so they cannot disagree with each other the way two
separate requests against a moving ledger legitimately can. A `GET /api/settlements` is not
added.

**1. A top-level `pending` array.** Every settlement in the group whose derived state is
`PENDING`, as `_settlement_view`, in ascending `ordering_key` order, oldest first.

    "pending": [ {<settlement view>}, ... ]

Oldest first, and not reversed the way `_list_expenses` reverses: the claim that has been
waiting longest is the one that needs chasing, and it belongs at the top. It also means the
screen may append a freshly created settlement to the end of the list and be exactly right.

The settlements are filtered out of the `ledger` list `_read_balances` has already read,
never re-fetched with `list_settlements`, so the pending rows and the transfers come from one
snapshot.

**2. `awaiting_confirmation` on every transfer.** A boolean, `true` when at least one pending
settlement runs from that transfer's `from_member_id` to its `to_member_id`.

    {"from_member_id": "...", "to_member_id": "...", "amount": "10.50",
     "payer_debts": [...], "receiver_credits": [...],
     "awaiting_confirmation": false}

Computed on the server, from ids, for the same reason `covers_whole_debt` and `direction`
are computed there: the rule for what counts as a match is a product rule, task 15 will
refine it when rejected settlements join the list, and it must live in one place. The screen
reads `awaiting_confirmation === true` and compares nothing.

**The amount is deliberately not part of the match.** A pending claim of 5.00 marks the
"Jo pays Sam 9.00" row as awaiting, and the row's wording is chosen so that is not a lie: it
says a payment is marked and unconfirmed, and never that this figure has been paid. The exact
claimed figure is in the pending block, where it can be read against the suggestion.

A pending settlement whose pair matches no transfer at all marks nothing and appears only in
the pending block. A pending settlement running the opposite way to a transfer marks nothing
either. Both are correct: they are different claims about different money.

## Balances do not move, and how that is proved

`derive_balances` is not touched. `simplify_debts` is not touched. `debt_sources` is not
touched, so a pending settlement appears in no drill-down entry list either: `balances.py`
already lists confirmed settlements only, and a pending one "is not listed at all".

The check that matters is criterion 20, and it is written to fail if this ever stops being
true, over ledgers nobody hand-picked:

* build a ledger with `random.Random(SEED)`, in the style `tests/test_balances.py` already
  uses for `random_ledger`;
* snapshot `derive_balances(store.list_events(group_id), ...)` and `GET /api/balances`;
* `POST /api/settlements`;
* assert the new `Balances` compares `==` to the snapshot, that `net` and `pairwise` are
  each equal item by item, and that the payload's `currency`, `net` and every transfer with
  `awaiting_confirmation` removed are unchanged.

`Balances` has value equality and covers `net` and `pairwise` both, so one `==` is the whole
claim. The mutation that must turn it red is named in the criterion, and the QA of this task
runs it.

## What each of the three readers sees

One ledger, read off any phone, says the same thing. Task 12 fixed that rule when it decided
the acting member is marked with ` (you)` and never renamed to "You", "because two flatmates
read this list off one phone, and a row that means different things depending on who is
holding the phone is worse than a list of names."

So the **pending row is identical for everybody**, differing only where ` (you)` falls:

| who is holding the phone | the pending row reads |
|---|---|
| the payer, Sam | `Sam (you) marked 600.00 as paid to Ali.` |
| the receiver, Ali | `Sam marked 600.00 as paid to Ali (you).` |
| a third member, Cass | `Sam marked 600.00 as paid to Ali.` |

and the date underneath, through `feedDate`, is the same for all three.

The **suggested payment row** is identical for everybody too: while a pending settlement
matches its pair, every phone shows `Marked as paid, and not confirmed yet.` under the row.

The only thing that differs by reader is **the offer of the action**, which is an offer and
not information: the `Mark as paid` button appears only on a transfer row whose
`from_member_id` is the acting member. Nobody else sees a control they could not use.

The receiver sees no control in this task. Confirming is task 15, and it hangs off the same
pending row.

## Where it goes on the screen, and the exact words

### The markup this task adds

One block, inside `<section id="screen-balances">`, **between `<ul id="balances-net">` and
the `Suggested payments` heading**, shipped hidden:

    <div id="balances-pending-block" hidden>
      <h2 class="balances-heading">Awaiting confirmation</h2>
      <p class="balances-note">These are marked as paid and not confirmed yet. They are not
        counted in the figures above, and they stay in the suggested payments below, until
        the person receiving the money confirms.</p>
      <ul class="balances-list" id="balances-pending"></ul>
    </div>

* **One wrapper with one `hidden` flag**, so the heading, the note and the list cannot be
  half-shown. A bare "Awaiting confirmation" heading over an empty list on an ordinary day is
  noise.
* **Above the suggested payments**, so the sentence that explains why a payment is still
  suggested is read before the suggestion, and so "the figures above" and "the list below"
  both point at something the reader has in front of them.
* The list ships empty, like the other two: every row comes from the API or there is no row.

### The exact words

These are the contract. Reword one and a scenario goes red, which is the point. Raise a
change; do not make it quietly.

Fixed prose, in `app/index.html`, shown at most once on the screen:

    Awaiting confirmation
    These are marked as paid and not confirmed yet. They are not counted in the figures
    above, and they stay in the suggested payments below, until the person receiving the
    money confirms.

Composed per row, in `app/app.js`, because a per-row sentence cannot live in markup:

    <Payer> marked <amount> as paid to <Receiver>.        (the pending row, then the date)
    Mark as paid                                          (the button's visible label)
    Mark as paid: <Payer> pays <Receiver> <amount>        (the button's aria-label)
    Recording this payment.                               (while the request is in flight)
    Marked as paid. It is not counted until <Receiver> confirms.   (after a 201)
    That was not recorded.                                (after any failure)
    Marked as paid, and not confirmed yet.                (a transfer row already claimed)

Every `<Payer>` and `<Receiver>` goes through the existing `balancesName`, so ` (you)` and
`Unknown member` apply here as everywhere else. `<amount>` is the string the server sent,
inserted exactly as received, inside its own `.balances-figure` span.

The `aria-label` begins with the visible label and then names the payment, so a screen reader
user listing the buttons on a screen with three payments hears three different names, and the
visible label is contained in the accessible name. The receiver in the recorded sentence is
never the acting member, because the button is only offered to the payer, so that sentence
never has to read `until Ali (you) confirms`.

**Why the failure sentence is fixed and is never `error.say`.** Every 400 this endpoint can
produce names a member id or describes a body the person did not type; the 409 describes a
claim they cannot see from here; the rest are api.js's curtains. There is no refusal on this
path whose words help a flatmate, and a member id may never be rendered as visible text on
this screen. One sentence, composed here, for every one of api.js's six kinds. The balances
region still reads no `error.status`, no `error.code`, no `error.kind` and no `error.say`.

The accepted imprecision, stated rather than hidden: when the 409 is the true answer, because
another device already recorded this claim, the screen still says `That was not recorded.`
That is imprecise and never wrong in the dangerous direction: it never claims something was
recorded that was not. Leaving the screen and returning shows the truth, because the second
read carries the pending row. Making it precise would mean branching on a code, which
`app/api.js`'s contract forbids a screen to do.

## The transfer row: a third child, and nothing else moved

Task 13 built the seam and said so: an openable transfer `<li>` holds "exactly two children,
the region a sibling of the button rather than its child, so task 14 can append a third
without unpicking either."

This task **appends a third child** and does not reorder the first two. `childNodes[0]` is
still the disclosure button and `childNodes[1]` is still the detail region. Appending rather
than inserting keeps every existing scenario's indexing correct, keeps visual order equal to
DOM order, and puts the control that records money after the explanation of the payment
rather than before it.

The third child is a `<div class="balances-action">`, and it is present in exactly two cases:

* **`awaiting_confirmation === true`**, whoever is acting: it holds one line,
  `Marked as paid, and not confirmed yet.`, and **no button**. This is also the up-front
  guard against a second claim, and it is why the 409 is a race guard rather than the normal
  path.
* **otherwise, when `from_member_id` equals the acting member id**: it holds the
  `Mark as paid` button and a `role="status"` line, shipped empty.

If neither holds, there is no third child at all, and the row is byte for byte what task 13
rendered. That is what keeps every existing balances scenario green except the one named in
criterion 72.

**An inert transfer row gets no third child, ever.** A transfer whose payload carries no
usable provenance renders exactly as task 13's criterion 12 pins it: one
`<span class="balances-line">`, no button, no region, no indicator. No `Mark as paid`, and no
awaiting line, even when the acting member is its payer and even when `awaiting_confirmation`
is true. Two reasons: a screen that cannot explain a payment has no business offering to
record it, and task 13's criterion 12 is not provably wrong, so it is not amended.

The information is not lost in that case. The pending block above still lists the claim in
full, because it is built from `pending` and not from the transfer rows.

## What happens when the button is pressed

In this order, and the order is load-bearing:

1. `ledgerIsUp()`. If it is false, return having changed nothing: no request, no message, no
   disabled button. The same shared helper the feed retry, the add retry and both of task
   13's disclosure handlers call, and not a fourth copy of the question.
2. If this row's own `asking` or `recorded` closure flag is set, return. **The flag is the
   real guard, not the `disabled` attribute**: the harness dispatches straight to listeners
   and never consults `disabled`, so a guard that lived only in the attribute would be
   asserted nowhere. `disabled` is set as well, for the browser.
3. `button.disabled = true`, `asking = true`, capture `var attempt = balancesAttempt`.
4. Set `aria-busy="true"` on the action region and write `Recording this payment.` into its
   `role="status"` line. The region is already in the document and was never hidden, so the
   live region announces. This happens **before** the request goes out, and criterion 48
   proves it with `page.onRequest`.
5. `api.addSettlement(toMemberId, amount)`.

On the answer:

* **201.** `aria-busy` removed; `recorded = true`; the button stays in the DOM,
  `disabled = true`; the status line reads `Marked as paid. It is not counted until Ali
  confirms.`; and if `attempt === balancesAttempt` and the returned view validates, one
  pending row is appended to `#balances-pending` and `#balances-pending-block` is unhidden.
* **Any failure.** `aria-busy` removed; `asking = false`; `button.disabled = false`, so it
  can be tried again; the status line reads `That was not recorded.` Nothing else on the
  screen changes: `#balances-error` stays hidden, the net list is untouched, an open
  drill-down stays open, and no curtain is raised by this screen. Five of api.js's six kinds
  raise a curtain over the frame anyway, which is api.js's doing and not this screen's.

**The button is not removed and the row is not re-rendered.** Removing or disabling the
element that has focus moves focus to `<body>`, and this task calls `focus()` nowhere: the
balances region still contains no `.focus(`. Disabling is unavoidable, because a live-looking
control that records nothing is worse; removing on top of it buys nothing.

**Nothing is re-read.** A successful mark does not call `balancesLoad()` and does not fire a
second `GET /api/balances`. Re-reading would snap every open drill-down shut and destroy the
live region mid-announcement, and the one row the read would add is the row that was just
appended.

**The `attempt` guard.** `balancesAttempt` is task 12's sequence number, bumped on every
read. Without capturing it, an answer arriving after the user left and came back would append
a pending row to a list the second read has already filled from the server, duplicating it.
The status line write needs no guard: it goes into the row's own detached DOM.

Recorded gap, in the repo's habit of naming them rather than leaving them to be found: **no
scenario proves the `attempt` guard**, because the harness settles a request before a
navigation can be driven against it. The guard is held by criterion 55, which is read off the
source, and by the hand check.

## Idempotence and double submission, in one place

| what happens | what the person gets |
|---|---|
| taps twice before the first answer | one `POST`; the second tap returns on `asking` |
| taps again after a 201 | nothing; `recorded` is set and the button is disabled |
| taps again after a failure | a fresh `POST`; nothing was kept |
| the row already shows a pending claim from the read | no button was ever drawn |
| a second device got there first | 409 `settlement_already_pending`, one settlement stored |
| leaves and comes back | the whole screen is rebuilt from the server's answer |

The server-side guarantee is the 409 and nothing else: the endpoint is not idempotent by key,
there is no client-supplied request id, and a retry is never automatic because `app/api.js`
"retries, re-sends, redirects or loops" nowhere.

## What happens to the suggestion

Nothing. The transfer stays in `transfers`, with the same amount and the same provenance,
because `simplify_debts` runs on balances that did not move. Removing it, greying it out,
striking it through or sorting it to the bottom would be the screen claiming a debt cleared.

What the screen adds is the sentence that stops the standing suggestion reading as a bug:
`Marked as paid, and not confirmed yet.` under the row, and the block above that says these
claims "stay in the suggested payments below, until the person receiving the money confirms."

## The empty and awkward cases

* **Nothing pending.** `pending` is `[]`, `#balances-pending-block` stays hidden, and the
  screen is exactly what task 13 left.
* **A pending claim with no payments left to make.** `transfers` is `[]`, so
  `No payments needed. Every net position is zero.` is showing, **and** the pending block is
  showing. Both are true: nothing is needed, and somebody has claimed something that has not
  been confirmed. The pending block is rendered independently of the transfer list and is not
  suppressed by the four fixed messages. Confirming that claim would move the group away from
  zero, and that is task 15's problem, correctly.
* **A pending claim whose pair matches no transfer.** It appears in the block; no transfer row
  is marked.
* **A pending row the screen cannot read.** A row that is not an object, or whose `id`,
  `from_member_id`, `to_member_id`, `amount`, `created_at` or `state` is not a string, or
  whose `state` is not exactly `'pending'`, is left out. The rest of the list still renders.
  One unreadable row does not hide a real claim, and the strict `state` equality is what lets
  task 15 widen this list without this screen mislabelling a rejected settlement as awaiting.
* **`pending` absent, or not an array.** Treated as empty. An older server is a screen without
  the block, not a broken one.
* **A member missing from the roster.** `Unknown member`, at both ends, and the row still
  shows. The button is still offered when the acting member is the payer, and tapping it gets
  the fixed failure sentence, which is exactly the answer task 13's criterion 29 and 43 pair
  gives for the same situation one level down.
* **An unlinked account.** `balancesActingId()` is `null`, so no row matches and no button is
  drawn anywhere. The pending block still renders, because it is information.
* **The busy and failure states.** `balancesClear()` empties the pending list and hides the
  block, so no claim from a previous visit sits beside `These figures could not be worked out
  just now.`
* **The empty roster state.** `net.length === 0` returns before any list is filled, so the
  pending block stays hidden there too.

## How it is tested

Four layers, each allowed to claim only what it can see.

**Python, `tests/test_web_api.py`:** the endpoint, its refusals, its gates, the widened
payload, and the generated-ledger proof that nothing moved. This is where criterion 20 lives.

**Python, `tests/test_web_shell.py`:** markup, ids, prose in markup, and the bans. Three
existing tests change and are named in criteria 60 to 62. No new test asserts a string is
present in `app/app.js` in order to claim a rendering behaviour is covered; PR #30's rule
stands. Bans are permitted, because a ban is falsified by one occurrence.

**The JavaScript harness, `tests/shell_harness.mjs` plus `tests/test_shell_behaviour.py`:**
everything the screen renders, against the real shipped files. Scenarios are appended; the
harness is not restructured. **The DOM stub is not widened**: `createElement`,
`createTextNode`, `setAttribute`, `removeAttribute`, `appendChild`, `className`,
`textContent`, `hidden`, `id`, `type`, `disabled`, `addEventListener` and `querySelectorAll`
are all present already, and criterion 70 pins that nothing is added.

**By hand, in a browser:** listed at the end.

---

## Acceptance criteria

Numbered so each can be ticked yes or no by reading the result or running one command.
Behavioural criteria name the harness scenario that proves them; a criterion with no scenario
named is checkable by reading a file or running the suite.

### The endpoint

1. `src/splitwise_lite/web.py` gains exactly one row in `_API_ROUTES`:
   `_ApiRoute("/api/settlements", "create_settlement", _create_settlement, ("POST",),
   _Access.MEMBER)`. No second literal, set or list of endpoint names is added or edited,
   and `_SHELL_ROUTES` is unchanged.
2. Deleting that row and leaving `_create_settlement` registered by any other means fails at
   `create_app` with `_RouteNotDeclared`, and changing `_Access.MEMBER` to a missing argument
   fails at import with `TypeError`. Demonstrate both once, by hand or in a test, and record
   the result.
3. `POST /api/settlements` with a valid body from a linked member returns `201` and a body of
   exactly `{"settlement": {...}}`, whose value holds exactly the seven keys `id`,
   `from_member_id`, `to_member_id`, `amount`, `created_at`, `created_by`, `state`.
4. `from_member_id` and `created_by` in the answer both equal the acting member's id, for
   every request, and neither can be influenced by the body: a body carrying
   `from_member_id`, `created_by`, `id`, `created_at`, `currency` or `group_id` is a `400`
   `malformed_request` naming the unrecognised key.
5. `state` is the string `"pending"`, and it comes from `_SETTLEMENT_STATE_WIRE`, a map over
   `SettlementState` with an entry for every one of its three members. A test asserts that
   map is exhaustive, in the way the existing tests assert `_ENTRY_KIND_WIRE` and
   `_ENTRY_EFFECT_WIRE` are.
6. `amount` in the answer is `format_amount` of the parsed amount, carries no minus sign, and
   round-trips: posting `"12.50"` answers `"12.50"`.
7. `created_at` is `isoformat(timespec="microseconds")`, byte-identical in spelling to what
   `_expense_view` produces, and comes from `_now()`. No endpoint accepts a client-supplied
   time, so `test_no_endpoint_accepts_a_client_supplied_time` and
   `test_the_clock_is_read_once_and_only_in_one_place` pass unchanged.
8. Each row of the refusal table in "The request body" above is a test, asserting the exact
   status **and** the exact `error.code`. The zero-amount and self-pair rows assert `400`
   and never `500`, which is what would happen if `InvalidEvent` were allowed to escape.
9. A refused request writes nothing: after each refusal in criterion 8,
   `store.list_settlements(group_id)` is unchanged.
10. `POST /api/settlements` is gated by its `_Access.MEMBER` row: no session is `401`
    `not_authenticated`; a signed-in account with no member row is `403` `member_not_linked`;
    a request with no `X-CSRF-Token` header is `403` `csrf_failed`; and a `PUT`,
    `PATCH` or `DELETE` on the same path is `405` `method_not_allowed`, while a `GET` is
    the shell catch-all's `404` `not_found`.

    > **Correction, 2026-09-07.** This criterion used to read "and a `GET`, `PUT`,
    > `PATCH` or `DELETE` on the same path is `405` `method_not_allowed`". A `GET` is
    > not a 405 and cannot be made one without changing a route this task may not
    > touch. `_SHELL_ROUTES` registers `/<path:filename>` for `GET`, so a `GET` that no
    > API row claims matches the shell catch-all, which finds no such file and answers
    > `404` `not_found` — exactly what `GET /api/nope` already answers, and what
    > `_before_request`'s own comment records the catch-all doing to paths under
    > `/api`. `PUT`, `PATCH` and `DELETE` match no rule at all and are the `405` the
    > criterion describes. Both halves are tested.
11. A second `POST` to a receiver who already has a pending settlement from the acting member
    is `409` with code `settlement_already_pending`, and `store.list_settlements` holds one
    settlement, not two.
12. That refusal is scoped to the ordered pair and to the pending state: a settlement in the
    other direction between the same two people is accepted; a settlement to a third member
    is accepted; and once a `SettlementDecisionEvent` confirming or rejecting the first is
    appended directly through the store, a second `POST` to that same receiver is accepted.
13. `SettlementAlreadyPending` is a `WebError` subclass with a docstring, exported exactly the
    way `MalformedRequest` and `TooManyAttempts` are: added to `web.__all__`, to
    `ERROR_STATUS` as `409` and to `ERROR_CODE` as `settlement_already_pending`, and added to
    `PUBLIC` in `tests/test_web_api.py`, so
    `test_the_public_surface_is_exactly_the_named_names`,
    `test_everything_else_the_module_defines_is_underscored` and
    `test_every_public_name_has_a_docstring` all pass.
14. `web.py`'s module docstring gains a sentence recording that the payer of a settlement is
    the acting member and that at most one settlement per ordered pair may be pending. All
    eight phrases `test_the_module_docstring_records_every_decision_it_makes` looks for are
    still present.
15. Nothing under `src/splitwise_lite/` other than `web.py` is modified: `git diff` shows no
    change to `events.py`, `balances.py`, `simplify.py`, `split.py`, `store.py`, `money.py`,
    `groups.py`, `accounts.py` or `__init__.py`. If a criterion appears to need a domain
    change, stop and raise it.

### The balances payload

16. `GET /api/balances` gains a top-level `pending` array and nothing else at the top level:
    the payload's keys are exactly `currency`, `net`, `transfers`, `pending`.
17. `pending` holds one entry per settlement in the group whose derived state is `PENDING`,
    each the same seven-key `_settlement_view` shape criterion 3 pins, and holds no confirmed
    and no rejected settlement. Appending a decision through the store removes that
    settlement from `pending` on the next read.
18. `pending` ascends by `(created_at, id)`, oldest first, and the list is built by filtering
    the events `_read_balances` has already read rather than by a second store call.
19. Every transfer gains `awaiting_confirmation`, a JSON boolean, so a transfer now holds
    exactly six keys. It is `true` when at least one pending settlement runs from that
    transfer's `from_member_id` to its `to_member_id`, and `false` otherwise, whatever the
    amounts are. A pending settlement running the other way, or naming a pair no transfer
    names, sets it nowhere.
20. **`tests/test_web_api.py` gains `test_a_pending_settlement_moves_no_balance_over_generated_ledgers`.**
    It builds at least 50 ledgers with `random.Random(SEED)`, in the style
    `tests/test_balances.py`'s `random_ledger` already uses; for each, it snapshots
    `derive_balances(store.list_events(group_id), ...)` and the `GET /api/balances` payload,
    posts one settlement through the endpoint, and asserts:
    * the new `Balances` compares `==` to the snapshot;
    * `net` and `pairwise` are equal item by item and in the same order;
    * the payload's `currency` and `net` are unchanged, and `transfers` is unchanged once
      `awaiting_confirmation` is dropped from every entry.

    **It is falsifiable, and the falsification is run.** Delete the line
    `if states[settlement.id] is not SettlementState.CONFIRMED: continue` from
    `src/splitwise_lite/balances.py`, run `uv run python -m pytest -k
    pending_settlement_moves_no_balance`, and record that it fails. Restore the line. A
    criterion that passes with that guard gone has not been met.
21. A companion test asserts the settlement is real rather than discarded: after the same
    `POST`, `store.list_settlements(group_id)` is one longer,
    `balances.settlement_states(store.list_events(group_id))` reports `PENDING` for the new
    id, and it appears in `pending` on the next read.
22. `GET /api/expenses` is byte-identical before and after the `POST`. A settlement is not an
    expense and the feed shows nothing about it.
23. `GET /api/debts/<debtor>/<creditor>` is byte-identical before and after the `POST`, for
    the pair the settlement names and for every other pair. A pending settlement is behind no
    debt, because `debt_sources` lists confirmed settlements only.
24. Every existing assertion in `tests/test_web_api.py` that pins the balances payload exactly
    is updated by **adding the new key at its exact value**, never by loosening an equality to
    a subset. At least these three: the empty-ledger `assert response.get_json() == {...}`,
    `test_balances_report_the_exact_figures_and_the_exact_transfer_list`, and
    `test_a_transfer_carries_both_ends_of_its_provenance`, whose `set(transfer) == {...}`
    gains `awaiting_confirmation`.

### The client

25. `app/api.js` gains exactly one exported name, `addSettlement(toMemberId, amount)`, taking
    the object literal from fourteen names to fifteen. It calls
    `call('POST', '/settlements', {to_member_id: toMemberId, amount: amount})` and builds no
    other key.
26. The body on the wire is exactly `{"to_member_id":"mem-2","amount":"600.00"}` for that
    call, key order included, pinned by a scenario's `expectRequests` entry.
27. Nothing else in `app/api.js` changes: no new handler, no new kind, no new status in the
    classification ladder, no retry, and no state. `test_the_api_client_holds_no_state_of_its_own`
    and `test_the_client_names_its_three_failure_paths` pass unchanged.

### The pending block

28. `app/index.html` gains exactly one block, inside `<section id="screen-balances">`, between
    `<ul id="balances-net">` and the `Suggested payments` heading: a
    `<div id="balances-pending-block" hidden>` holding an `<h2>` reading exactly
    `Awaiting confirmation`, a `<p class="balances-note">` reading exactly the note quoted in
    "The exact words", and an empty `<ul class="balances-list" id="balances-pending">`. The
    head, header, gate, notice, feed and add sections, the nav and the script tag are
    untouched.
29. `BALANCES_IDS` in `tests/test_web_shell.py` gains `balances-pending-block` and
    `balances-pending`, so `test_the_balances_section_carries_every_id_the_screen_toggles`
    passes with the set pinned exactly.
30. `#balances-pending-block` is shown only when at least one row of `pending` was rendered,
    and is hidden in every other state: nothing pending, the busy state, the failure state,
    the empty-roster state, a `pending` that is absent, a `pending` that is not an array, and
    a `pending` whose every row was unreadable.
    (scenarios: `everyone_sees_the_same_payment_awaiting_confirmation`,
    `a_pending_row_the_screen_cannot_read_is_left_out_rather_than_guessed_at`,
    `leaving_the_balances_screen_and_returning_clears_the_pending_list`)
31. `balancesClear()` empties `#balances-pending` and hides `#balances-pending-block`, so no
    claim survives a refresh or sits beside a failure message. Neutralise that line and
    `leaving_the_balances_screen_and_returning_clears_the_pending_list` goes red.
32. A pending row is one `<li class="balances-pending">` carrying `data-settlement`,
    `data-from` and `data-to` as attributes only, holding exactly two children: a line
    element and a `<time>`. Task 15 appends a third without unpicking either.
    (scenario: `everyone_sees_the_same_payment_awaiting_confirmation`)
33. The line reads `<Payer> marked <amount> as paid to <Receiver>.` with both names through
    `balancesName` and the amount inserted exactly as received inside its own
    `.balances-figure` span. The `<time>` holds `feedDate(created_at)` as text and
    `created_at` unchanged in a `datetime` attribute.
    (scenario: `everyone_sees_the_same_payment_awaiting_confirmation`)
34. The same fixture renders the same row on three phones, differing only in where ` (you)`
    falls: the payer's, the receiver's and a third member's.
    (scenario: `everyone_sees_the_same_payment_awaiting_confirmation`)
35. Rows render in the order `pending` arrived. `app/app.js` still contains no `.sort(` and no
    `.reverse(`, so `test_the_shell_never_reorders_what_the_server_sent` passes unchanged.
36. A pending row is rendered only when it is an object whose `id`, `from_member_id`,
    `to_member_id`, `amount` and `created_at` are all strings and whose `state` is exactly the
    string `'pending'`, by one strict equality. Any other row is left out and the rest of the
    list still renders; `pending` absent or not an array is treated as empty.
    (scenario: `a_pending_row_the_screen_cannot_read_is_left_out_rather_than_guessed_at`)
37. No settlement id and no member id is ever rendered as visible text, in any state, the
    failure state included.

### The action on a transfer row

38. An openable transfer `<li>` holds a third child, appended last, when and only when
    `awaiting_confirmation === true` or `from_member_id` equals the acting member's id.
    `childNodes[0]` is still the disclosure button and `childNodes[1]` is still the detail
    region in every case.
    (scenario: `the_payer_can_mark_a_suggested_payment_as_paid`)
39. When `awaiting_confirmation === true`, the third child holds one line reading exactly
    `Marked as paid, and not confirmed yet.` and **no button**, whoever is acting, the payer
    included.
    (scenario: `a_payment_already_marked_as_paid_says_so_instead_of_offering_the_button`)
40. When the acting member is the payer and `awaiting_confirmation` is not `true`, the third
    child holds a `<button type="button" class="balances-mark-button">` whose visible text is
    exactly `Mark as paid`, whose `aria-label` is exactly
    `Mark as paid: <Payer> pays <Receiver> <amount>` with the names through `balancesName`,
    and one `role="status"` element shipped holding `''`.
    (scenario: `the_payer_can_mark_a_suggested_payment_as_paid`)
41. A transfer row whose payer is not the acting member and whose `awaiting_confirmation` is
    not `true` holds exactly two children, byte for byte what task 13 rendered.
    (scenario: `a_payment_someone_else_owes_offers_no_way_to_mark_it_paid`)
42. An **inert** transfer row, one whose payload carries no usable provenance by task 13's
    predicate, holds exactly one `<span class="balances-line">` child and nothing else: no
    button, no awaiting line, no third child, even when the acting member is its payer and
    even when `awaiting_confirmation` is `true`. Task 13's criterion 12 is unchanged and
    unamended.
    (scenario: `a_transfer_row_without_provenance_offers_no_way_to_mark_it_paid`)
43. An account with no member row draws no `Mark as paid` button on any row, because it never
    reaches this screen at all; and a session view carrying a member this screen cannot
    identify draws none either, while the pending block still renders.
    (scenario: `an_unlinked_account_is_offered_no_way_to_mark_anything_paid`)

    > **Correction, 2026-09-07.** This criterion used to read "An account with no member row
    > draws no `Mark as paid` button on any row, while the pending block still renders." Its
    > second half is unreachable as stated, and the first half is true for a stronger reason
    > than the one it gives. `app/app.js`'s `ledgerIsUp()` refuses a session view with no
    > member, and boot raises the not-linked notice for one, so **an account with no member
    > row never reaches the balances screen**: no row, no control and no pending block is
    > drawn for it, and `balancesEntered()` asks for nothing. `balancesActingId()`'s null
    > branch is still real and still does exactly what this criterion describes, but it is
    > reached through a session view carrying a member with no `id` — which `ledgerIsUp()`
    > admits, and which `app/app.js` already records as a case it handles. The scenario proves
    > both halves: the notice case draws nothing at all, and the unidentifiable-member case
    > renders the pending block, names nobody ` (you)`, and offers no control on any row.
44. Two rows both payable by the acting member each carry their own button, their own status
    line and their own closure. Marking one changes nothing about the other.
    (scenario: `the_payer_can_mark_a_suggested_payment_as_paid`)
45. **The suggestion stays.** After a 201 and after a re-read, the transfer row is still in
    the list, with the same sentence and the same amount, and is neither removed, greyed,
    struck through, reordered nor collapsed. Its drill-down still opens and still lists the
    same debts.
    (scenario: `a_pending_payment_leaves_the_suggested_payment_where_it_was`)

### Pressing it

46. The handler calls `ledgerIsUp()` first and returns having changed nothing when it is
    false: no request, no message, no `disabled`, no `aria-busy`. `ledgerIsUp` is called,
    never reimplemented, and the region holds no second copy of the question.
    (scenario: `marking_a_payment_paid_behind_a_curtain_asks_for_nothing`)
47. The first press sends exactly one `POST /api/settlements` with the exact body of criterion
    26, and no other request. Entering the balances route still makes exactly two requests,
    `GET /api/members` and `GET /api/balances`, and drawing a payable row makes none.
    (scenario: `the_payer_can_mark_a_suggested_payment_as_paid`)
48. **At the moment the request goes out**, the action region already carries
    `aria-busy="true"` and its `role="status"` line already reads exactly
    `Recording this payment.` Proven with `page.onRequest`, which sees the page as it was when
    the call was made.
    (scenario: `marking_a_payment_paid_announces_it_before_and_after_the_request`)
49. When it settles, `aria-busy` is removed. After a 201 the status line reads exactly
    `Marked as paid. It is not counted until Ali confirms.` with the receiver's name through
    `balancesName`.
    (scenario: `marking_a_payment_paid_announces_it_before_and_after_the_request`)
50. After a 201 the button is still in the document, is `disabled`, and its label is
    unchanged. Nothing calls `focus()`: `app/app.js`'s balances region still contains no
    `.focus(`, so `test_the_drill_down_never_moves_focus` passes unchanged.
51. **Two presses record one settlement.** Dispatching `click` twice in a row sends exactly
    one `POST`. The guard is a closure flag and not the `disabled` attribute, which the
    harness does not consult.
    (scenario: `tapping_mark_as_paid_twice_records_one_settlement`)
52. Pressing again after a 201 sends nothing further. Pressing again after a failure sends a
    fresh `POST`, because nothing was kept.
    (scenarios: `tapping_mark_as_paid_twice_records_one_settlement`,
    `a_payment_that_will_not_record_says_so_and_can_be_tried_again`)
53. A failure of any kind writes exactly `That was not recorded.` into that row's status line
    and re-enables the button. `#balances-error` stays hidden, the net list is untouched, the
    pending block is untouched, an open drill-down stays open, and no server sentence appears
    anywhere. The balances region still contains none of `error.status`, `error.code`,
    `error.kind`, `error.say`.
    (scenario: `a_payment_that_will_not_record_says_so_and_can_be_tried_again`)
54. On a 201 whose `settlement` view validates, one pending row is appended to the end of
    `#balances-pending` and the block is unhidden, without a second request. On a 201 whose
    view does not validate, nothing is appended and the recorded sentence is still shown.
    (scenario: `the_payer_can_mark_a_suggested_payment_as_paid`)
55. The append is guarded by `balancesAttempt`, captured before the request and compared
    before the append, so an answer arriving after the list has been rebuilt writes into no
    list. Checkable by reading the source; this file records that no scenario proves it and
    why.
56. Leaving the route and returning rebuilds everything from the second read: the pending list
    holds exactly what that read said, no row survives from before, and no `POST` is replayed.
    (scenario: `leaving_the_balances_screen_and_returning_clears_the_pending_list`)
57. A group with no payments left to make still shows the pending block:
    `No payments needed. Every net position is zero.` and the claim are on screen together.
    (scenario: `a_group_with_nothing_left_to_settle_still_shows_a_pending_payment`)

### Layout and the shell rules

58. All new CSS is appended at the end of `app/styles.css`, inside the existing
    `/* Balances --- */` block, every selector prefixed `.balances-`, with no existing rule
    modified, so `test_every_balances_selector_is_namespaced_to_this_screen` passes.
59. `.balances-mark-button` carries a `min-height` of at least 44px, a `font-size` of at least
    16px and full-width padding, so the whole row is the target with no dead strip. Every
    `min-height` in the file is still at least 44px and every `font-size` still at least 16px:
    `test_no_rule_sets_a_hit_area_below_forty_four_pixels`,
    `test_every_transfer_row_clears_the_hit_area_floor` and
    `test_no_rule_sets_a_font_size_below_sixteen_pixels` pass unchanged.
60. `test_only_the_two_disclosure_buttons_look_tappable` is **replaced** by a test whose name
    says what is now true, allowing exactly three selectors to carry `cursor`, all of them
    `pointer`: `.balances-transfer-button`, `.balances-debt-button` and
    `.balances-mark-button`. The `content:` ban is kept unchanged. Nothing else about the test
    is relaxed.
61. `test_both_disclosure_buttons_show_a_keyboard_user_where_they_are` is **replaced** by the
    same test over the same three classes, each with a `:focus-visible` rule carrying a
    visible outline. No fourth selector is admitted.
62. `CARRIES_A_NAME` in `tests/test_web_shell.py` gains `.balances-pending-line` and
    `.balances-action-status`, and both carry `overflow-wrap: break-word`, so
    `test_every_line_that_carries_a_name_can_break_a_long_one` passes over the widened list.
    `.balances-figure` is still the only selector in the block carrying `white-space: nowrap`.
63. No `animation`, `transition` or `@keyframes` is added, no `row-reverse`,
    `column-reverse`, `order` or absolute positioning, and no `content:` declaration, so
    `test_the_balances_block_adds_no_animation` and
    `test_the_balances_block_never_moves_a_row_out_of_document_order` pass unchanged.
64. The `role="status"` line inside an action region is never given `hidden` and never given a
    `min-height` or padding, so it takes no vertical space while it is empty. No `:empty`
    selector is used.
65. `app/app.js` still contains none of `fetch`, `/api`, `innerHTML`, `outerHTML`,
    `insertAdjacentHTML`, `document.write`, `toFixed`, `parseFloat`, `parseInt`, `Number(`,
    `Math.round`, `Math.floor`, `/ 100`, `Intl`, `toLocaleString`, `NumberFormat`, `0.00`,
    `$`, `£` or `€`, so `test_the_narrowed_rule_still_bites`,
    `test_only_the_api_client_calls_the_back_end`,
    `test_the_balances_screen_reimplements_no_money_handling`,
    `test_the_shell_builds_rows_without_parsing_markup` and
    `test_no_shell_file_prints_a_currency_symbol` pass unchanged.
66. Every `setAttribute` in the balances region still names its attribute with a single-quoted
    lower-case literal, and the only `role` it ever sets is `'status'`; the region assigns no
    `.role` property and contains no `createElement('a')`, `createElement('details')`,
    `createElement('summary')`, `tabindex`, `onclick`, or `keydown`, `keyup`, `keypress`,
    `pointerdown` or `touchstart` listener, so
    `test_the_transfer_row_is_a_disclosure_and_nothing_hand_rolled` passes unchanged.
67. The balances region still contains none of `localStorage`, `sessionStorage`, `indexedDB`,
    `setInterval`, `setTimeout`, `requestAnimationFrame`, `onUnauthenticated`, `onNotLinked`,
    `onOffline` or `location.hash =`, so
    `test_the_balances_screen_keeps_no_copy_of_a_derived_figure` and
    `test_the_balances_screen_registers_none_of_the_three_global_handlers` pass unchanged.
68. Every `getElementById('...')` and `querySelector('.…')` literal added names something
    present in `app/index.html`, so
    `test_every_element_the_router_reaches_for_exists_in_the_document` passes unchanged.
    Dynamic nodes are reached through closures, never through a class selector.
69. `ROUTES` still holds exactly `#/feed`, `#/add` and `#/balances`. Marking a payment changes
    no hash, calls no `pushState` and no `replaceState`, and scrolls nothing.
    (scenario: `the_payer_can_mark_a_suggested_payment_as_paid`)

### The harness

70. `tests/shell_harness.mjs` gains no DOM stub widening at all: the diff touches the scenario
    list and its helpers only, and the guarded proxy is unchanged.
71. The following scenarios are appended, each named as a sentence, each declaring its exact
    ordered request list with `expectRequests`, each registering an answer for every call it
    makes, and each added to `SCENARIOS` in `tests/test_shell_behaviour.py` so the two lists
    stay exactly equal, in this order:
    - `the_payer_can_mark_a_suggested_payment_as_paid`
    - `marking_a_payment_paid_announces_it_before_and_after_the_request`
    - `tapping_mark_as_paid_twice_records_one_settlement`
    - `a_payment_that_will_not_record_says_so_and_can_be_tried_again`
    - `a_payment_someone_else_owes_offers_no_way_to_mark_it_paid`
    - `a_payment_already_marked_as_paid_says_so_instead_of_offering_the_button`
    - `a_transfer_row_without_provenance_offers_no_way_to_mark_it_paid`
    - `everyone_sees_the_same_payment_awaiting_confirmation`
    - `a_pending_payment_leaves_the_suggested_payment_where_it_was`
    - `a_pending_row_the_screen_cannot_read_is_left_out_rather_than_guessed_at`
    - `marking_a_payment_paid_behind_a_curtain_asks_for_nothing`
    - `an_unlinked_account_is_offered_no_way_to_mark_anything_paid`
    - `leaving_the_balances_screen_and_returning_clears_the_pending_list`
    - `a_group_with_nothing_left_to_settle_still_shows_a_pending_payment`
72. **Exactly one existing scenario changes, and only by strengthening.** In
    `opening_a_suggested_payment_shows_both_ends_of_it`, whose fixture makes the acting
    member `mem-1` the payer, `page.is(row.childNodes.length, 2, ...)` becomes `3` and
    assertions about the third child are added. Its comment records why. `childNodes[0]` and
    `childNodes[1]` keep their meanings and every other assertion in it is untouched.
73. No other existing scenario is weakened, renamed, deleted, reordered or turned into a
    source-text assertion, and no existing fixture's member ids are changed to dodge a new
    behaviour. Every other balances scenario stays green because its acting member is neither
    the payer nor the receiver of its transfers.
74. No new scenario asserts focus movement, a cached session view, an `aria-current` value or
    the escaping of markup: those are issue #37's recorded gaps and the stub cannot see them.
75. Running the harness with no substitutions passes every scenario and exits 0, and all six
    mutant tests still pass unchanged, still exiting 1 and still naming the scenarios they
    name today.

### The service worker and the suite

76. `app/sw.js` is edited on exactly one line: `SHELL_DIGEST` is set to the twelve hex
    characters `test_the_recorded_digest_matches_the_files_it_covers` prints when it fails,
    pasted verbatim. `VERSION` stays `'v4'`, `SHELL` is unchanged, and nothing else in the
    file moves. That test is never skipped, loosened, xfailed or deleted, and no file is added
    to or removed from `app/`, so `test_app_holds_exactly_the_promised_files` and
    `test_the_worker_precaches_exactly_the_shell` pass unchanged.
77. `uv run python -m pytest` passes with nothing skipped and nothing xfailed, and the pass
    count is master's 2223 plus exactly the tests this task adds. Plain `uv run pytest` fails
    on this machine with an access-denied spawn error and is not the command.
78. Every non-obvious choice made here carries a one-line comment where it is implemented, so
    the next person does not undo it by tidying: why the payer is the acting member and never
    the body, why the plan is not consulted, why a second pending claim per ordered pair is
    refused, why the zero and self-pair checks sit in the view rather than the constructor,
    why `pending` rides on the balances read instead of a second endpoint, why
    `awaiting_confirmation` is computed on the server, why the amount is not part of that
    match, why the pending list is oldest first, why the action is the third child and
    appended, why an inert row gets none of it, why the button is disabled rather than
    removed, why the closure flag and not `disabled` is the real guard, why the region is
    written to before the request goes out, why the failure sentence is fixed rather than the
    server's, and why the append is guarded by `balancesAttempt`.

---

## Verified by hand

Browser only. Record each as checked, against a store seeded by `scripts/setup_group.py` and
served with `uv run python scripts/serve.py --store ledger.sqlite3`. Tick "Update on reload"
in DevTools, Application, Service Workers first, or the cached shell serves the old files.

- Seed a ledger with one suggested payment the signed-in member owes. Mark it as paid, and
  read the screen aloud: it says a payment is claimed, that it is not counted, and that the
  suggestion stands until the other person confirms, without anybody asking a question.
- Sign in as the receiver on a second browser profile and confirm the pending row reads the
  same, with ` (you)` in the other place, and that no button is offered there.
- Sign in as a third member and confirm they see the same pending row and no button.
- Confirm the net positions are byte-identical before and after the mark, on all three.
- Mark a payment, then reload: the pending row is still there, from the server, and the
  suggested payment is still in the list.
- Press the button twice quickly and confirm the Network panel shows one `POST`.
- Stop the server, press the button, and confirm the failure sentence appears inside that row
  with the rest of the screen intact. Restart it and press again: it records.
- With VoiceOver or NVDA: tab to the button, hear its accessible name naming the payment,
  press Enter, hear `Recording this payment.` and then the recorded sentence, and confirm the
  pending row is reachable in the reading order.
- Tab through a payable row: the disclosure button, then the debt buttons when open, then
  `Mark as paid`, in visual order, with a visible focus ring on each.
- A display name containing `<`, `&` and a quote renders as those characters in the pending
  row and in the button's accessible name.
- At 320x568, 360x640, 390x844 and landscape 844x390, with a 40-character display name and a
  payment open with a debt open inside it: no horizontal scroll on `.content`, nothing
  clipped, the amounts whole, and the button reachable above the nav.
- Console is clean on entry, on marking, after a failed mark, and after signing back in.

---

## Out of scope

- **Confirming or rejecting a settlement.** Task 15 / issue #16. No
  `SettlementDecisionEvent` is appended anywhere in this task, no decision endpoint is
  registered, and no confirm or reject control is drawn.
- **Withdrawing or cancelling a claim.** There is no way for the payer to take a pending
  settlement back. Named as a consequence of the 409 above and as a backlog candidate; not
  built.
- **Editing or deleting a settlement.** Events are append-only.
- **Partial settlements and instalments.** The spec cuts them explicitly. The amount posted is
  whatever the person is recording, and nothing splits it.
- **Validating a settlement against the simplify plan**, snapping it to a suggested amount, or
  refusing an amount no transfer names. Reasoned about above; deliberately not done.
- **Any change to `derive_balances`, `simplify_debts`, `debt_sources`, `settlement_states`,
  `events.py` or `store.py`.** They already do what this task needs.
- **A `GET /api/settlements` endpoint**, a settlements screen, a settlement history view, or a
  fourth route. `ROUTES` keeps exactly three entries.
- **Showing settlements in the expense feed.** A settlement is not an expense.
- **Rate limiting this endpoint.** The limiter exists for credential guessing; a linked member
  appending an event is not that, `_create_expense` is not limited either, and the 409 is the
  guard against a flood of duplicates.
- **Notifications, reminders, badges, unread counts or a "chase Ali" button.** The spec cuts
  notifications outright: the receiver finds pending confirmations by opening the app.
- **Any staleness or incompleteness signal**, including "pending for 6 days" or highlighting
  an old claim. Task 16 owns that, and the pending row shows a plain date through `feedDate`
  and nothing derived from it.
- **Relative dates, a second date spelling, currency symbols or locale formatting.**
  `feedDate` and `format_amount` are the two edges.
- **Front-end arithmetic of any kind**, including matching a pending claim to a transfer by
  amount, totalling the pending list, or comparing two amount strings.
- **Branching on a status, a code or a kind in `app/app.js`.**
- **Deep linking to a pending claim**, remembering which rows were open, or restoring scroll.
- **Bumping `VERSION` in `app/sw.js`, or touching anything in it but `SHELL_DIGEST`.**
- **A JavaScript test runner, a bundler, a framework, ES modules, a linter or a formatter.**
- **Any new dependency in either language**, runtime or dev.
- **Docs.** `CLAUDE.md` and `README.md` are unchanged: nothing about how the app is run,
  installed or tested changes here.
- **`plans/spec.md` and `plans/backlog.md`.** This task implements what they already say.

## Constraints

- Files to modify, and nothing else: `src/splitwise_lite/web.py`, `app/api.js`, `app/app.js`,
  `app/index.html`, `app/styles.css`, `app/sw.js` (one line), `tests/test_web_api.py`,
  `tests/test_web_shell.py`, `tests/shell_harness.mjs`, `tests/test_shell_behaviour.py`.
- No file is created and no file is deleted. Nothing is added to or removed from `app/`.
- **`plans/tasks/13-transfer-drill-down.md` is not modified.** Its criterion 12 constrains
  this task, and it is not amended: an inert transfer row keeps exactly the shape it pins.
  Task 13's own rule allows correcting only a statement that is provably wrong, and nothing
  here proves one wrong.
- **Nothing under `src/splitwise_lite/` except `web.py` is modified.** If a criterion appears
  to need a domain change, a new field on an event or a change to the fold, **stop and raise
  it loudly** rather than editing it from here.
- Every change in `app/app.js` stays inside the balances region, from the
  `/* --- The balances screen ---` banner to the end of the file. No function above it is
  edited, `showApp()`, `ledgerIsUp`, `feedDate` and `feedInstant` included; the region calls
  the last three and modifies none of them. The net list, the currency line, the status region
  and the four fixed messages are untouched.
- In `app/index.html`, one block is added inside `<section id="screen-balances">` and nothing
  else in the document changes.
- In `app/styles.css`, rules are appended at the end of the file, in one block, every selector
  prefixed `.balances-`, with no existing rule modified.
- Every element id and class this task adds is prefixed `balances-`.
- JavaScript is plain, browser-native, classic (non-module) script, in the style already in
  `app/app.js`: an IIFE, `'use strict'`, `var`, named functions, single-quoted strings. No
  framework, no polyfill, no transpilation, no minification. The committed file is the file
  the browser runs.
- Element lookups stay `document.getElementById('literal-id')`, single quoted, naming only
  things present in `app/index.html`. Dynamic nodes are reached through closures.
- Every URL and asset reference stays relative. No absolute `http://` or `https://` anywhere
  under `app/`.
- **Money is integer cents everywhere it is a number, and a formatted string everywhere it
  crosses the wire.** `money.format_amount` is the one display edge and `money.parse_amount`
  the one input edge. The front end does no arithmetic, no formatting, no comparison and no
  parsing of an amount, ever. Every decision that depends on comparing money arrives as a
  server-computed field, as `direction`, `covers_whole_debt`, `effect` and now
  `awaiting_confirmation` do.
- All ordering is the server's, at every level: `net`, `transfers`, `payer_debts`,
  `receiver_credits`, `entries` and `pending`.
- New tests are appended at the end of their files. The only pre-existing tests that change
  are the ones named in criteria 13, 24, 29, 60, 61, 62 and 72, and each changes by gaining a
  name or a value, never by loosening an equality or dropping a ban.
- New scenarios are appended to the scenario list in `tests/shell_harness.mjs` and to
  `SCENARIOS` in `tests/test_shell_behaviour.py`, and the two stay exactly equal. Scenario
  fixtures are locals inside their scenario rather than module constants threaded into the
  fixtures above, following task 12a's note: one appended block conflicts with less on a file
  other branches are editing.
- Tests run with `uv run python -m pytest`. No test is skipped or xfailed, no test binds a
  socket, and assertions are exact, per `.claude/rules/testing.md`. CI runs the same command
  on Linux and Windows on every PR.
- **No new dependency of any kind, in either language.** Nothing is added to `pyproject.toml`,
  no `package.json` is created, and `.claude/hooks/guard-deps.hs.sh` blocks the ad hoc Python
  route anyway. Per `CLAUDE.md` a dependency is declared then installed with `uv sync`, never
  `pip install` or `uv pip install`. If something here genuinely cannot be built without a
  package, stop and get the user's approval first.
- **This file must not be modified, with one exception: a statement in it that is provably
  wrong may be corrected**, following the precedent tasks 5, 9b, 11 and 13 set. Sharpening a
  criterion, re-scoping one or softening one to suit an implementation is not covered and
  stays forbidden. Every correction carries a dated marker saying what the file used to say,
  what it says now and why.

---

## What task 15 / issue #16 gets from this, so it need not reopen these files

The receiver confirmation task should be able to start from the wire and the DOM, not from a
re-read of the renderer.

**On the server.**
* `_API_ROUTES` shows the whole shape of adding an endpoint: one appended row carrying rule,
  endpoint, view, methods and an explicit `_Access`, with the build-time audit and the
  per-request refusal behind it. #16 appends
  `_ApiRoute("/api/settlements/<settlement_id>/decision", "decide_settlement", ...,
  ("POST",), _Access.MEMBER)` and edits nothing else to register it.
* `_settlement_view(settlement, state)` and `_SETTLEMENT_STATE_WIRE` already exist and already
  cover `confirmed` and `rejected`. #16 adds values, not keys.
* `derive_balances` needs no change: it folds confirmed settlements only, so appending a
  `SettlementDecisionEvent` moves the balance by itself, and criterion 20's test becomes
  #16's mirror image, asserting the balance **does** move.
* `store.append_settlement_decision` exists and stores every answer it is given; the
  earliest-decision-wins rule is `settlement_states`', already applied by both
  `derive_balances` and `_read_balances`.
* The receiver-only rule is #16's to enforce, in the layer that can load both records:
  `events.py` and `store.py` both say so in as many words, and both refuse to check it.
* This task's 409 means at most one pending settlement per ordered pair **in one process, and
  nowhere else**. #16 should note that rejecting one frees that pair for a fresh claim, and
  decide whether that is what it wants.

  > **Correction, 2026-09-07.** This bullet used to open "This task's 409 means at most one
  > pending settlement per ordered pair", with no qualification. As shipped, the check reads
  > the ledger and the append writes it, and `scripts/serve.py` serves with `threaded=True`,
  > so the rule is enforced by `web._SETTLEMENT_LOCK`, a module-level `threading.Lock` held
  > across both halves. That lock is exact within one process and worth nothing across two
  > processes or two hosts, and `store.append_settlement` has no uniqueness constraint that
  > could catch a second claim, because pending is derived rather than stored. So the
  > unqualified sentence claimed more than the code delivers. **What #16 must do:** take
  > `web._SETTLEMENT_LOCK` across its own read and its own append, and count the pair's
  > pending claims inside it rather than trusting this endpoint to have kept it to one. The
  > lock is not reentrant, so count with a helper that is handed a ledger and takes no lock;
  > a helper that both counts and locks self-deadlocks the moment it is called from inside a
  > block that already holds it. `_SETTLEMENT_LOCK`'s docstring carries the same instruction
  > next to the code.

**On the wire.**
* `GET /api/balances` already carries `pending`, and each row already carries `id`,
  `from_member_id`, `to_member_id`, `amount`, `created_at`, `created_by` and `state`. #16
  needs no new read to render the receiver's controls.
* #16 must decide one thing this task deliberately did not: whether a rejected settlement
  joins `pending` (renaming the key in the same change) or gets a list of its own. The screen
  is safe either way, because it renders only rows whose `state` is exactly `'pending'`
  (criterion 36), so a widened list cannot make it mislabel a rejected claim as awaiting.

**On the screen.**
* The pending `<li>` carries `data-settlement`, `data-from` and `data-to`, and holds exactly
  two children (criterion 32). #16 appends a third holding the confirm and reject controls,
  the same way this task appended a third to the transfer row.
* `balancesPendingRow` is the one named function that takes one pending view and returns one
  `<li>`, and `balancesPendingFill` is the one place the list is filled.
* The action-region pattern is reusable as it stands: a `role="status"` line written before
  the request goes out, `aria-busy` on the region while it is in flight, a closure flag as
  the real double-submission guard with `disabled` beside it, one fixed failure sentence for
  all six kinds, `ledgerIsUp()` first, and no `focus()` anywhere.
* A confirmation **does** move balances, so #16 cannot follow this task's "do not re-read"
  rule: after a confirmed decision the net list and the transfer list are both stale, and
  #16 has to decide between a full `balancesLoad()` and something narrower. That is the one
  place where this task's shape does not carry over, and it is flagged here rather than
  discovered there.

**For task 18 / issue #19,** the end-to-end smoke test needs `POST /api/settlements` to exist
with the body and the 201 shape criteria 3 to 6 pin, and it needs criterion 20's guarantee
that the pending step moves nothing, so that the balance clearing can be attributed to the
confirmation and to nothing else.
