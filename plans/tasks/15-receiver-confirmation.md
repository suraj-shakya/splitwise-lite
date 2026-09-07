# Task 15: Receiver confirmation

**Depends on:** 4 (complete, on `master`), 14 (complete, on `master`), and in practice also
6, 9a, 9b, 12, 12a and 13, all complete on `master`. Everything this task reads exists today
and is quoted from the shipped source below.

**Consumed by:** task 18 / issue #19 (the end-to-end smoke test). "What #19 gets from this" at
the end of this file is part of the deliverable, not a note.

Sharpened from `plans/backlog.md` task 15, GitHub issue #16. The backlog entry stays as
written; this file is the implementable version.

---

## Goal

The person owed the money answers the claim. Confirming admits the settlement into the balance
fold, so the debt clears and every phone in the flat sees the same new figures. Rejecting
leaves the claim visible with its state changed, moves no figure, and frees the pair so the
payer can mark the payment again.

## Why this task is easy to get wrong

The spec names the hazard at "Receiver-confirms introduces an undefined state":

> The balance does not move until the receiver confirms. Pending payments render as a separate
> "awaiting Ali" row. Without this, two people see two different versions of the truth.

Task 14 built the half where nothing moves. This is the half where something does, and there
are four ways to get it wrong, all of them quiet:

* **A debt cleared by the wrong person.** If the payer, or anybody else, can confirm, then one
  person can both claim and confirm a payment, and the money never has to exist.
  Payer-creates plus receiver-confirms is what makes a settlement need two people; one rule
  without the other is worth nothing. Task 14 enforced its half structurally, and this task
  enforces the other half the same way.
* **A rejection that moves money, or a confirmation that does not.** `derive_balances` folds
  confirmed settlements only. Criteria 40 and 41 exist to make either failure loud, over
  ledgers nobody hand-picked, and both must be falsified before they are believed.
* **A rejected claim that vanishes.** The backlog is explicit: "Rejection leaves the pending
  row visible with its state changed." A screen that drops it tells the payer nothing, and the
  payer is the only person who can act next.
* **A screen showing figures from before the confirmation.** A confirmation moves the net
  positions, the transfer plan and the pending list all at once. Task 14's "do not re-read"
  rule was correct for a claim that moves nothing and is wrong here, which task 14 flagged in
  as many words. This task re-reads.

## What already exists, and is not rebuilt

Nothing in the domain layer changes. It is all shipped and quoted:

* `events.SettlementDecisionEvent` is "the receiver's answer to one settlement, appended rather
  than applied", carrying `id`, `settlement_id`, `decision`, `decided_by` and `created_at`. It
  "references the settlement by id and never restates the amount, so a decision cannot disagree
  with the settlement it decides", and its `decision` must be `CONFIRMED` or `REJECTED`:
  "`PENDING` is not a decision: it is the absence of one".
* It carries **no `group_id`**, and `plans/spec.md` says why: "an event that restates nothing
  about the settlement, neither amount nor group, cannot disagree with it", at the stated cost
  that "an orphaned decision is ignored rather than detected". The consequence
  `balances.py` draws is the one this task obeys: "a group's settlements and their decisions
  must be loaded **together**". `store.list_events(group_id)` already does exactly that, and
  it is the only read this endpoint makes.
* `events.py` and `store.py` both refuse to check who may decide, in as many words: "the rule
  that only the receiver may confirm belongs to the service layer that can load both". That
  layer is `web.py`, and this task is that rule.
* `balances.settlement_states` applies earliest-decision-wins, and `derive_balances` reaches
  the same code path, "so a rendered state and a balance can never disagree about whether a
  settlement counted".
* `balances.py` line 247 is the whole of "only confirmation moves balances":

      for settlement in settlements:
          if states[settlement.id] is not SettlementState.CONFIRMED:
              continue

* `store.append_settlement_decision` stores every answer it is given and refuses a duplicate
  decision id.
* `web._settlement_view` and `web._SETTLEMENT_STATE_WIRE` already cover `confirmed` and
  `rejected`. **This task adds values, not keys**: the settlement view stays exactly seven
  keys.

**So the domain layer needs no change at all.** This task is one HTTP endpoint, one widened
balances payload, one client method and a screen. If an implementer finds themselves editing
`events.py`, `balances.py`, `simplify.py`, `split.py` or `store.py`, they have taken a wrong
turn: stop and raise it.

## Who may decide, and how the server enforces it

**The decider is the acting member, always, and is never named in the body.** `decided_by`
comes from `flask.g.member.id`, exactly as task 14 takes `from_member_id` from there.
`_require_keys` already refuses an unrecognised key, so a body naming `decided_by`,
`settlement_id`, `id`, `created_at` or `group_id` is a 400 `malformed_request` with no special
code written for it.

**Only the receiver of that settlement may answer it.** The endpoint loads the settlement from
this group's ledger and compares `settlement.to_member_id` with the acting member's id. Anyone
else is **403 `not_the_receiver`**, and that includes the payer. The payer being refused is not
an oversight to be softened later: an endpoint that let the payer answer their own claim would
be a withdrawal mechanism wearing a confirmation's clothes, and withdrawal is issue #66 and is
out of scope here (see "Out of scope").

The refusal names no member id and is the same sentence whether the caller is the payer or a
third member. Not for privacy, since any linked member may already read the whole group's
ledger, but because there is nothing a second sentence would tell either of them that they
could act on.

Consequences, stated rather than discovered:

* **A claim whose receiver is an unlinked member can be answered by nobody.** It stays pending
  for ever and blocks that ordered pair. This is the mirror of task 14's accepted gap that "a
  payment whose payer is an unlinked member cannot be recorded by anybody", and it is accepted
  for the same reason: the alternative is letting somebody else answer on their behalf, which
  is the hole this rule exists to close. `setup_group.py link` is the fix.
* **The amount is never re-checked against anything.** `balances.py` already refuses to
  validate a settlement against the pairwise debt it appears to clear, and states that "a
  settlement larger than the debt flips the pair". Confirming a claim for more than the debt
  is therefore allowed and moves the pair the other way; confirming a claim after the ledger
  has moved on is allowed too. The receiver is the check, and the receiver has just checked.
* **A confirmation cannot be undone.** Events are append-only, a second decision is refused
  (below), and there is no correction event for settlements. The screen says so before the
  buttons.

## The endpoint

    POST /api/settlements/<settlement_id>/decision

registered as one row appended to `_API_ROUTES` in `src/splitwise_lite/web.py`:

    _ApiRoute(
        "/api/settlements/<settlement_id>/decision", "decide_settlement",
        _decide_settlement, ("POST",), _Access.MEMBER,
    )

Adding an endpoint is one edit and the access is not optional. `_ApiRoute` gives `access` no
default, so a row that does not state what it requires is a `TypeError` at import;
`_audit_routes` refuses to build an app serving a rule no row declares; `_before_request`
refuses one at request time as a second line. There is no second literal of endpoint names to
update. CSRF, the session check and the member check all follow from that one row.

The path shape is the one task 14 handed forward by name, so nothing here is invented.

### The request body

    {"decision": "confirmed"}

Exactly that one key. Its two legal values are exactly the two non-`PENDING` values of
`_SETTLEMENT_STATE_WIRE`, and the mapping back to the domain is **derived from that map, not
written a second time**:

    _SETTLEMENT_DECISION_WIRE: Final[dict[str, events.SettlementState]] = {
        wire: state
        for state, wire in _SETTLEMENT_STATE_WIRE.items()
        if state is not events.SettlementState.PENDING
    }

One literal, one derivation. A renamed wire spelling moves both directions at once, and
`"pending"` cannot be sent because it is not in the map.

The refusals, all before anything is written, all `MalformedRequest` (400,
`malformed_request`) unless named otherwise:

| what | answer |
|---|---|
| a missing, extra or misspelled key | 400 `malformed_request` |
| `decision` not a JSON string | 400 `malformed_request` |
| `decision` not exactly `"confirmed"` or `"rejected"` | 400 `malformed_request` |
| `decision` of `"pending"`, `"CONFIRMED"`, `"Confirmed"` or `""` | 400 `malformed_request` |
| a `settlement_id` naming no settlement in this group | 404 `record_not_found` |
| the acting member is not that settlement's receiver | 403 `not_the_receiver` |
| that settlement already carries a decision | 409 `settlement_already_decided` |
| confirming while the ordered pair carries two unanswered claims | 409 `settlement_already_pending` |

Order matters and is checkable: the body is validated first, then the settlement is resolved,
then the receiver rule, then the decision state, then the pair count. A caller who is not the
receiver of an already-decided settlement gets the 403, because "you may not answer this" is
true regardless of what the ledger says about it.

**Why `"pending"` in the body is a 400 and never a 500.** `SettlementDecisionEvent.__post_init__`
raises `InvalidEvent` for a `PENDING` decision, and `InvalidEvent` is in neither `ERROR_STATUS`
nor `ERROR_CODE`, so an escape would reach the client as a generic 500 with the real reason in
the log only. The wire map refuses it first. The constructor stays as the backstop it is, and
this is exactly the trap task 14 recorded for the self-pair and the zero amount.

**Why an unknown settlement is 404 and not 400.** `_read_debt` answers 400 for a path segment
naming a member outside the group, because a member id there is an argument to a query about
the group. A settlement id here names a resource, and the honest answer for a resource that is
not there is 404. `store.RecordNotFound` is already mapped to 404 `record_not_found`, is the
exception the store itself raises for an unknown settlement id in
`list_settlement_decisions`, and is the code `app/api.js` already classifies as `refused`, so
no new class and no new code is needed for it. A settlement belonging to **another group** is
the same 404: the ledger this endpoint reads is `_store().list_events(group.id)` and a
settlement outside it does not exist as far as this request is concerned.

### The response

`200`, body `{"settlement": <settlement view>}`, whose `state` is now `confirmed` or
`rejected`. The same `_settlement_view` builder task 14 shipped, with no new key.

**200 and not 201.** The body names the settlement, and the settlement was not created here.
A decision has no URL of its own to hand back, and the client branches on neither status, so
201 would claim a resource was created at an address that does not exist. Task 14's two
appends both answer 201 and both create the thing their body names, which is the rule this
follows rather than breaks.

**The response does not carry balances.** The screen re-reads through the endpoint it already
has. A second shape of balances payload would be a second builder and a second thing to keep
in step with `_read_balances`.

### The lock, and the one way to misuse it

`web._SETTLEMENT_LOCK`'s docstring is an instruction to this task and must be obeyed literally:

> **For issue #16.** Do not read "at most one pending claim per pair" as given. Confirming is
> the same check-then-act shape, so #16 should take *this* lock across its own read and its own
> append, and count the pair's pending claims inside it rather than trusting this endpoint to
> have kept it to one.

So `_decide_settlement` holds `_SETTLEMENT_LOCK` across its ledger read, every check that
depends on ledger state, and its append. Everything that validates the body alone happens
before the lock is taken.

**The lock is not reentrant, and a helper that both counts and locks self-deadlocks silently**,
hanging that request for good with no exception and no log line, and hanging every later
request for the same rule behind it. The docstring names the shape that keeps that impossible:
a helper that counts is handed a ledger and takes no lock, and the caller holds the lock around
it. This task therefore extracts, from the loop already inside `_create_settlement`:

    def _pending_claims(ledger, states, payer_id, receiver_id) -> int

taking no lock, and both endpoints call it inside their own `with _SETTLEMENT_LOCK:` block.
That is the sharing the docstring asks for, "by passing the ledger rather than by taking the
lock in two places".

**What the count is for**, so it is not ceremony. Within one process task 14's 409 keeps the
count at one and this is a cheap restatement. Across two processes, two workers hold two locks
and two pending claims for one pair can exist. Confirming one of two identical unanswered
claims would be the receiver guessing which payment they were paid, and confirming both clears
the debt twice, which is the failure the whole arrangement exists to prevent. So:

* **Confirming is refused, 409 `settlement_already_pending`,** when the settlement's ordered
  pair carries more than one unanswered claim.
* **Rejecting is always allowed.** Rejecting is the recourse: the receiver rejects the
  duplicate, the pair drops back to one unanswered claim, and the real one can then be
  confirmed. A rule that blocked both answers would leave the pair stuck with no way out.

`SettlementAlreadyPending`'s docstring gains one sentence recording this second use. It is the
same situation seen from the other end and deserves the same code.

## What the balances payload gains

Task 14 left one decision explicitly open: "whether a rejected settlement joins `pending`
(renaming the key in the same change) or gets a list of its own".

**It gets a list of its own.** `GET /api/balances` grows one top-level key, `rejected`, so the
payload's keys are exactly `currency`, `net`, `transfers`, `pending`, `rejected`. Reasons, in
order of weight:

* A widened `pending` would be **invisible on the shipped screen**, not merely untidy:
  `balancesValidPending` compares `state` against `'pending'` by one strict equality and drops
  everything else, which is criterion 36 of task 14 and is deliberate. A rejected claim in
  `pending` would be silently dropped, and the backlog requires it to stay visible.
* `awaiting_confirmation` is computed from unanswered claims, and a rejected claim must not
  mark a transfer as awaiting anybody. Two arrays keep that true with no filtering; one array
  makes every consumer re-derive the split.
* The two lists carry different headings and different prose on screen, so they were always
  going to be two lists. Two arrays means the screen sorts nothing, filters nothing and
  branches on `state` nowhere beyond the equality it already has.

`rejected` holds every settlement in the group whose derived state is `REJECTED`, as
`_settlement_view`, in ascending `ordering_key` order, oldest first, filtered out of the same
`ledger` list `_read_balances` has already read. One snapshot, one instant, one ordering rule
for both lists, and nothing sorted in `web.py`.

A confirmed settlement appears in **neither** list. It has moved the figures, it is in the
drill-down through `debt_sources`, and a third list would be an activity feed, which nothing
asks for.

**`awaiting_confirmation` needs no refinement.** `_read_balances`'s docstring currently predicts
that "task 15 refines it when rejected settlements join the list". They join a list of their
own instead, so the match is unchanged: pending claims only, by ids only, amount no part of it.
That sentence in the docstring is updated to record what task 15 actually did.

**The payload is identical for every member of the group.** `_read_balances` reads nothing from
`flask.g.member`. That is what criterion 44 turns into a test.

## What moves, what does not, and how it is proved

`derive_balances`, `simplify_debts`, `debt_sources` and `settlement_states` are untouched.
Appending a `SettlementDecisionEvent` is the whole of the movement, and the fold does the rest.

Two generated-ledger tests, mirror images of task 14's criterion 20, over ledgers nobody
hand-picked, built with `random.Random(LEDGER_SEED)` through the existing `generate_ledger`
helper:

* **Confirming moves exactly the amount and nothing else.** For each ledger: snapshot
  `derive_balances`, confirm one settlement through the endpoint, and assert the payer's
  `net_for` rose by exactly `amount_cents`, the receiver's fell by exactly `amount_cents`,
  every other member's `net_for` is unchanged, `owed_between(receiver, payer)` rose by exactly
  `amount_cents`, and `after != before`.
* **Rejecting moves nothing.** The same walk, rejecting instead, asserting `after == before` by
  `Balances` value equality, which covers `net` and `pairwise` both.

**Both are falsifiable, and all three falsifications are run and recorded before either is
believed:**

1. Make `_decide_settlement` append `SettlementState.REJECTED` whatever the body said. The
   confirming test must go red.
2. Make it append `SettlementState.CONFIRMED` whatever the body said. The rejecting test must
   go red.
3. Delete `if states[settlement.id] is not SettlementState.CONFIRMED: continue` from
   `src/splitwise_lite/balances.py`. The rejecting test must go red, and task 14's
   `test_a_pending_settlement_moves_no_balance_over_generated_ledgers` must go red with it.

Restore the source after each. A criterion that still passes under its own mutation has not
been met.

## Two users never see different balances for the same group

The backlog's own test, made concrete rather than gestured at. Balances are a pure function of
one ledger and the payload carries nothing about who asked, so two members must read the same
bytes. That is asserted **as bytes**, with `get_data(as_text=True)`, by two and then three
signed-in clients for three different linked accounts, at every state the ledger passes
through:

1. before anything is claimed,
2. after Sam marks a payment as paid (pending),
3. after Ali confirms it,
4. and, on a second pair, after Ali rejects it.

At step 3 the test also asserts the figures actually moved between step 2 and step 3, so byte
equality cannot be satisfied by an endpoint that does nothing. The third client, Jo, is party
to neither the payment nor the decision and reads the same bytes as both parties, which is what
makes it a statement about the group rather than about the two people involved.

On the screen the same claim is task 12's ` (you)` rule, and it is proved the way task 14
proved it: one fixture rendered on three phones, differing only in where ` (you)` falls.

## Two decisions on one settlement

`balances._decided_states` builds its answer with
`earliest.setdefault(decision.settlement_id, decision.decision)` over decisions in
`ordering_key` order, so the earliest decision wins and a later one changes nothing. Verified
against the shipped source rather than assumed, and `balances.py`'s module docstring states it
directly, "a later `CONFIRMED` after an earlier `REJECTED` included".

The endpoint therefore has nothing to gain from appending a second decision: the fold would
ignore it, and the log would carry an answer that can never take effect. **A second decision on
a settlement that already carries one is 409 `settlement_already_decided`**, whether or not it
agrees with the first, and nothing is written.

It is a race guard and not the normal path, exactly as task 14's 409 is: the screen offers no
control on a settlement that is not pending, so reaching this needs a second device, or a
second tap against an answer that was lost in flight. `SettlementAlreadyDecided` is a new
`WebError` subclass, 409, code `settlement_already_decided`, exported the way
`SettlementAlreadyPending` is.

## What each of the three parties sees

One ledger read off any phone says the same thing. The **rows are identical for everybody**,
differing only in where ` (you)` falls; the only thing that differs by reader is **the offer of
the action**, which is an offer and not information.

| | the payer, Sam | the receiver, Ali | a third member, Cass |
|---|---|---|---|
| the pending row | `Sam (you) marked 600.00 as paid to Ali.` | `Sam marked 600.00 as paid to Ali (you).` | `Sam marked 600.00 as paid to Ali.` |
| controls on it | none | `Confirm` and `Reject` | none |
| the transfer row while pending | `Marked as paid, and not confirmed yet.` | the same | the same |
| after Ali confirms | the debt is gone from the figures and the plan on every phone; the claim is in neither list | | |
| the rejected row | `Sam (you) marked 600.00 as paid to Ali, and it was not confirmed.` | `Sam marked 600.00 as paid to Ali (you), and it was not confirmed.` | `Sam marked 600.00 as paid to Ali, and it was not confirmed.` |
| after Ali rejects | `Mark as paid` is offered again on the transfer row, because the pair is free | none | none |

The payer learns of a rejection by opening the app. The spec cuts notifications outright: "The
receiver finds pending confirmations by opening the app", and the same is true in reverse.

## The screen

### The markup this task adds

Two things, both inside `<section id="screen-balances">`, and nothing else in `app/index.html`
changes.

**1. One live region for the outcome**, immediately after `<p id="balances-derived">` and
before the `Net positions` heading:

    <p class="balances-decision" id="balances-decision" role="status"></p>

It ships empty, is **never** given `hidden`, and its rule gives it no height, no padding and no
`:empty` selector, so it takes no vertical space until there is something to say. It is at the
top because a confirmation rebuilds every list below it: the sentence explaining why the screen
just changed has to be readable before the thing it changed, and a screen reader user reading
from the top after the rebuild meets it first.

**2. The rejected block**, immediately after `#balances-pending-block` and before the
`Suggested payments` heading, shipped hidden:

    <div id="balances-rejected-block" hidden>
      <h2 class="balances-heading">Not confirmed</h2>
      <p class="balances-note">These were marked as paid and the person receiving the money did
        not confirm them. They are not counted in the figures above, and whoever paid can mark
        the payment again.</p>
      <ul class="balances-list" id="balances-rejected"></ul>
    </div>

One wrapper with one `hidden` flag, for the reason task 14 gave: a bare heading over an empty
list on an ordinary day is noise. Below the awaiting block and above the suggestions, so the
two things that explain why a payment is still suggested are read together and both point down
at the list they are about.

### The exact words

These are the contract. Reword one and a scenario goes red, which is the point. Raise a change;
do not make it quietly.

Fixed prose, in `app/index.html`, shown at most once on the screen:

    Not confirmed
    These were marked as paid and the person receiving the money did not confirm them. They
    are not counted in the figures above, and whoever paid can mark the payment again.

Composed per row or per act, in `app/app.js`, because a sentence that belongs to a row cannot
live in markup:

    <Payer> marked <amount> as paid to <Receiver>, and it was not confirmed.   (a rejected row)
    Neither answer can be undone.                        (in the receiver's action region)
    Confirm                                              (the confirm button's visible label)
    Reject                                               (the reject button's visible label)
    Confirm: <Payer> marked <amount> as paid to <Receiver>     (the confirm aria-label)
    Reject: <Payer> marked <amount> as paid to <Receiver>      (the reject aria-label)
    Answering this payment.                              (in flight, in the row's status line)
    That was not answered.                               (any failure, in the row's status line)
    Confirmed. The payment of <amount> from <Payer> to <Receiver> is now counted in the
      figures below.                                     (in #balances-decision, after a 200)
    Not confirmed. The payment of <amount> from <Payer> to <Receiver> is not counted, and it
      can be marked as paid again.                       (in #balances-decision, after a 200)

Every `<Payer>` and `<Receiver>` goes through the existing `balancesName`, so ` (you)` and
`Unknown member` apply here as everywhere else. `<amount>` is the string the server sent,
inserted exactly as received, inside its own `.balances-figure` span.

Each `aria-label` begins with the visible label and then names the payment, so a screen reader
user listing the buttons on a screen with three claims hears six different names and each
visible label is contained in its accessible name. Two buttons per row is exactly why the
labels cannot be the visible text alone.

`Neither answer can be undone.` is inside the action region rather than in the block's fixed
prose, because it has to be read at the moment the decision is made rather than at the top of
a list the reader did not know would ask them anything, and because the payer and third
members are shown no controls and need no warning about them. The cost, stated: a receiver with
three claims on screen reads the same sentence three times.

**Why the failure sentence is fixed and is never `error.say`.** Every refusal this endpoint can
produce describes a body the person did not type, a settlement they cannot see from here, or a
rule about who they are. There is no refusal on this path whose words help a flatmate, and this
screen renders no member id and no settlement id as visible text. One sentence, composed here,
for every one of `app/api.js`'s six kinds. The balances region still reads no `error.status`,
no `error.code`, no `error.kind` and no `error.say`.

The accepted imprecision, the same one task 14 recorded: when the true answer is a 409 because
another device answered first, the screen still says `That was not answered.` It is imprecise
and never wrong in the dangerous direction, because it never claims something was recorded that
was not, and leaving the screen and returning shows the truth from the server.

### The pending row: a third child, and nothing else moved

Task 14 built the seam and said so: a pending `<li>` holds "exactly two children, a line and a
date, so task 15 can append its confirm and reject controls as a third without unpicking
either".

This task **appends a third child** and reorders neither of the first two. `childNodes[0]` is
still the line and `childNodes[1]` is still the `<time>`. The third child is a
`<div class="balances-answer">` and it is present **only** when `to_member_id` equals the acting
member's id. Otherwise there is no third child at all, and the row is byte for byte what task
14 rendered, which is what keeps every existing balances scenario green except the one named in
criterion 74.

The region holds, in this order:

1. `<p class="balances-answer-note">Neither answer can be undone.</p>`
2. `<button type="button" class="balances-confirm-button">Confirm</button>`
3. `<button type="button" class="balances-reject-button">Reject</button>`
4. `<p class="balances-answer-status" role="status"></p>`, shipped empty

Real buttons, so Enter and Space work with no key handler, the focus order is right with
nothing written to put it there, and no role is needed. Stacked full width rather than laid out
side by side: at 320px two labelled buttons on one line is what pushes this screen into a
horizontal scroll, and a mis-tap between two adjacent targets is the one mistake here that
cannot be undone.

**A rejected row never gets a third child.** Nobody can act on it from this screen: the payer's
next act is `Mark as paid` on the transfer row, which is already there.

### What happens when Confirm or Reject is pressed

In this order, and the order is load-bearing:

1. `ledgerIsUp()`. If false, return having changed nothing: no request, no message, no disabled
   button, no `aria-busy`. The same shared helper the feed retry, the add retry, both
   disclosure handlers and task 14's mark handler call, and not a sixth copy of the question.
2. If this row's own `answering` closure flag is set, return. **One flag for the row, not one
   per button**, so Confirm followed by Reject before the first answer sends one request. The
   flag is the real guard and not the `disabled` attribute: the harness dispatches straight to
   listeners and never consults `disabled`, so a guard living only in the attribute would be
   asserted nowhere. `disabled` is set on both buttons as well, for the browser.
3. `answering = true`; both buttons `disabled = true`; capture `var attempt = balancesAttempt`.
4. Empty `#balances-decision`, so at most one act's outcome is ever on screen and it is always
   the most recent one.
5. Set `aria-busy="true"` on the action region and write `Answering this payment.` into its
   `role="status"` line. This happens **before** the request goes out, and criterion 62 proves
   it with `page.onRequest`.
6. `api.decideSettlement(settlementId, decision)`.

On the answer:

* **200.** `aria-busy` removed. If `attempt !== balancesAttempt`, stop here and do nothing else:
  the person left and came back, a newer read owns the screen, and a sentence written now would
  describe a screen that is gone. Otherwise write the outcome sentence into `#balances-decision`
  and **then** call `balancesLoad()`.
* **Any failure.** `aria-busy` removed; `answering = false`; both buttons re-enabled, so it can
  be tried again; the row's status line reads `That was not answered.` Nothing else on the
  screen changes: `#balances-decision` stays empty, `#balances-error` stays hidden, the net list
  is untouched, both blocks are untouched, an open drill-down stays open, and no re-read is
  fired. Five of `api.js`'s six kinds raise a curtain over the frame anyway, which is `api.js`'s
  doing and not this screen's.

**Why it re-reads, and why the sentence is written first.** A confirmation moves the net
positions, the transfer plan, `pending` and `awaiting_confirmation` all at once, and a rejection
moves the claim from one list to the other and unblocks the pair. Nothing narrower than a
re-read is honest, and this screen may compute none of it itself. The sentence is written
before the re-read starts rather than after it finishes because the decision is recorded either
way: a re-read that fails must not swallow the only statement that the answer was accepted.

**The `attempt` guard.** `balancesAttempt` is task 12's sequence number, bumped by every read.
Without capturing it, an answer arriving after the person left and came back would fire a
second pair of reads over a screen that had already rebuilt, and would leave a sentence about
an act on a screen nobody is looking at. Recorded gap, in the repo's habit of naming them: **no
scenario proves this guard**, because the harness settles a request before a navigation can be
driven against it. It is held by criterion 69, read off the source, and by the hand check.

### The focus gap, named rather than found

The re-read destroys the list that holds the button that has focus, so focus falls to `<body>`.
This task calls `focus()` nowhere and does not fix it: `test_the_drill_down_never_moves_focus`
pins that the balances region contains no `.focus(`, and moving focus from an event handler is
a decision this screen has never made.

It is mitigated rather than ignored. `#balances-decision` is a `role="status"` region that
survives the rebuild, so the outcome is announced without depending on focus, and it sits above
every list, so the first thing a reader meets on the rebuilt screen is the sentence explaining
it. The residual cost is real: a keyboard user's next Tab starts from the top of the document.
It is on the hand-check list, and closing it properly is a focus-management decision for the
whole shell rather than for one button.

### The empty and awkward cases

* **Nothing rejected.** `rejected` is `[]`, `#balances-rejected-block` stays hidden, and the
  screen is exactly what task 14 left.
* **`rejected` absent, or not an array.** Treated as empty. An older server is a screen without
  the block, not a broken one.
* **A rejected row the screen cannot read.** A row that is not an object, or whose `id`,
  `from_member_id`, `to_member_id`, `amount` or `created_at` is not a string, or whose `state`
  is not exactly `'rejected'`, is left out and the rest of the list still renders. The same
  strict equality the pending list uses, in one shared validator taking the expected state.
* **A pending claim and a rejected claim for the same pair.** Both are shown, in their own
  blocks, and `awaiting_confirmation` is `true` from the pending one, so the transfer row says
  `Marked as paid, and not confirmed yet.` and offers the payer no second claim. Correct: the
  pair is still blocked by the unanswered one.
* **Two rejected claims for one pair.** Both are shown, oldest first. Nothing is deduplicated.
* **Confirming the only claim in a group with nothing left to settle.** The group moves away
  from zero: `No payments needed. Every net position is zero.` is replaced by a real transfer
  list on the re-read, and the pending block goes. Both readings are correct, and the screen
  states the new one rather than reconciling them.
* **The rejected list grows without bound.** Rejections are events and are never deleted, so a
  rejection from months ago is still on the balances screen. Accepted, and named: a cut-off
  would be a product rule nobody has asked for, and a screen that hides part of the ledger is
  the worse failure. Ageing the list out is a backlog candidate, not this task.
* **A member missing from the roster.** `Unknown member` at both ends, in both blocks, and the
  row still shows. The controls are still offered when the acting id matches `to_member_id`,
  because an id match needs no name, and pressing one works: the server has never needed a
  display name.
* **An unlinked account, or a session view carrying a member this screen cannot identify.**
  `balancesActingId()` is `null`, so no row matches and no control is drawn anywhere. Both
  blocks still render, because they are information.
* **The busy, failure and empty-roster states.** `balancesClear()` empties `#balances-rejected`
  and hides its block, exactly as it does for the pending list, so nothing from a previous
  visit sits beside `These figures could not be worked out just now.`, and the `net.length === 0`
  early return keeps both blocks hidden there too.
* **`#balances-decision` and navigation.** It is emptied at the start of every press and by
  `balancesEntered()` before it calls `balancesLoad()`, and by nothing else. It is **not**
  emptied by `balancesClear()`, because the re-read a decision fires runs through
  `balancesClear()` and would wipe the sentence it just wrote.

## How it is tested

Four layers, each allowed to claim only what it can see.

**Python, `tests/test_web_api.py`:** the endpoint, its refusals, its gates, the widened payload,
the two generated-ledger proofs, the byte-equality proof across three readers, and the
interleaving proof for the lock. Appended in one block at the end of the file.

**Python, `tests/test_web_shell.py`:** markup, ids, prose in markup, CSS and the bans. Five
existing tests change and are named in criteria 71 to 73 and 78. No new test asserts a string
is present in `app/app.js` in order to claim a rendering behaviour is covered; PR #30's rule
stands. Bans are permitted, because a ban is falsified by one occurrence.

**The JavaScript harness, `tests/shell_harness.mjs` plus `tests/test_shell_behaviour.py`:**
everything the screen renders, against the real shipped files. Scenarios are appended; the
harness is not restructured; the DOM stub is not widened, because `createElement`,
`createTextNode`, `setAttribute`, `removeAttribute`, `appendChild`, `removeChild`, `className`,
`textContent`, `hidden`, `id`, `type`, `disabled`, `addEventListener` and `querySelectorAll` are
all present already.

**By hand, in a browser:** listed at the end. Two browser profiles are required, because one
person cannot both claim and answer a payment.

---

## Acceptance criteria

Numbered so each can be ticked yes or no by reading the result or running one command.
Behavioural criteria name the harness scenario that proves them; a criterion with no scenario
named is checkable by reading a file or running the suite.

### The endpoint

1. `src/splitwise_lite/web.py` gains exactly one row, appended to `_API_ROUTES`:
   `_ApiRoute("/api/settlements/<settlement_id>/decision", "decide_settlement",
   _decide_settlement, ("POST",), _Access.MEMBER)`. No second literal, set or list of endpoint
   names is added or edited, and `_SHELL_ROUTES` is unchanged.
2. The ordered literal in `test_the_route_tables_hold_exactly_the_routes_the_app_serves` gains
   that row in the same position, and no other row in it moves.
3. Deleting the row and leaving `_decide_settlement` registered by any other means fails at
   `create_app` with `_RouteNotDeclared` naming the rule, and constructing the row without
   `_Access` fails with `TypeError`. Both are tests, following the two task 14 wrote for its
   own row.
4. `POST /api/settlements/<id>/decision` with `{"decision": "confirmed"}`, sent by that
   settlement's receiver, answers `200` and a body of exactly `{"settlement": {...}}` whose
   value holds exactly the seven keys `id`, `from_member_id`, `to_member_id`, `amount`,
   `created_at`, `created_by`, `state`, and whose `state` is `"confirmed"`.
5. The same with `{"decision": "rejected"}` answers `200` and `state` is `"rejected"`. The
   other six keys are byte-identical to the view the settlement had while pending.
6. `_settlement_view` gains no key and no argument, and `_SETTLEMENT_STATE_WIRE` is unchanged:
   `test_the_settlement_state_wire_map_covers_every_state` passes untouched.
7. The stored decision carries `decided_by` equal to the acting member's id, `created_at` from
   `_now()` spelled `isoformat(timespec="microseconds")`, and an `id` from `events.new_id()`.
   No endpoint accepts a client-supplied time, so
   `test_no_endpoint_accepts_a_client_supplied_time` and
   `test_the_clock_is_read_once_and_only_in_one_place` pass unchanged.
8. `_SETTLEMENT_DECISION_WIRE` is **derived** from `_SETTLEMENT_STATE_WIRE` in a comprehension
   that drops `PENDING`, and is not a second literal. A test asserts its keys are exactly
   `{"confirmed", "rejected"}` and that its values are exactly the two non-`PENDING` members of
   `SettlementState`, computed from the enum rather than typed out.
9. Every row of the refusal table in "The request body" is a test asserting the exact status
   **and** the exact `error.code`. The `"pending"` row asserts `400` and never `500`, which is
   what an escaped `InvalidEvent` would produce.
10. A refused request writes nothing: after each refusal in criterion 9,
    `store.list_settlement_decisions` for the settlement is unchanged and its derived state is
    unchanged.
11. The checks run in the stated order, and a test proves the one case where the order is
    visible: a member who is neither party, answering a settlement that already carries a
    decision, gets `403 not_the_receiver` and not the 409.
12. Only the receiver may answer. A test signs in as the payer and as a third member and
    asserts both get `403` with code `not_the_receiver`, that the message names no member id,
    and that the two messages are identical.
13. `NotTheReceiver` and `SettlementAlreadyDecided` are `WebError` subclasses with docstrings,
    exported exactly the way `SettlementAlreadyPending` is: added to `web.__all__`, to
    `ERROR_STATUS` as `403` and `409`, to `ERROR_CODE` as `not_the_receiver` and
    `settlement_already_decided`, and added to `PUBLIC` in `tests/test_web_api.py`, so
    `test_the_public_surface_is_exactly_the_named_names`,
    `test_everything_else_the_module_defines_is_underscored` and
    `test_every_public_name_has_a_docstring` all pass.
14. A `settlement_id` naming no settlement in this group is `404` `record_not_found`, including
    an id that names a settlement in another group in a multi-group store. A test builds the
    second group and proves the second half, and proves no decision was written to it.
15. A second decision on a settlement that already carries one is `409`
    `settlement_already_decided`, whether it agrees with the first or contradicts it, and
    `store.list_settlement_decisions` still holds exactly one.
16. Earliest-decision-wins is verified against `balances.py` rather than assumed: a test appends
    two contradicting decisions **directly through the store**, asserts `settlement_states`
    reports the earlier one, and asserts `derive_balances` agrees. The endpoint's 409 is
    proved separately by criterion 15, so the domain rule and the HTTP rule are two claims.
17. `POST` on the decision path is gated by its `_Access.MEMBER` row: no session is `401`
    `not_authenticated`; a signed-in account with no member row is `403` `member_not_linked`; a
    request with no `X-CSRF-Token` header is `403` `csrf_failed`; `PUT`, `PATCH` and `DELETE`
    are `405` `method_not_allowed`; and a `GET` is the shell catch-all's `404` `not_found`,
    exactly as task 14's criterion 10 records for `/api/settlements`.
18. Nothing under `src/splitwise_lite/` other than `web.py` is modified: `git diff` shows no
    change to `events.py`, `balances.py`, `simplify.py`, `split.py`, `store.py`, `money.py`,
    `groups.py`, `accounts.py` or `__init__.py`. If a criterion appears to need a domain
    change, stop and raise it.
19. `web.py`'s module docstring gains a sentence recording that only the receiver may answer a
    claim and that a settlement may be answered once. The tuple in
    `test_the_module_docstring_records_every_decision_it_makes` gains one phrase from that
    sentence, and all eight existing phrases are still present and still asserted.

### The lock

20. `_pending_claims(ledger, states, payer_id, receiver_id)` exists, takes no lock, acquires
    nothing, and is called by both `_create_settlement` and `_decide_settlement` from inside
    their own `with _SETTLEMENT_LOCK:` block. `_create_settlement`'s inline loop is replaced by
    the call and its behaviour is unchanged: every task 14 test about the 409 passes untouched.
21. A test asserts, by reading `web.py`, that `_SETTLEMENT_LOCK` is acquired exactly twice in
    the module, once in each endpoint, and that `_pending_claims` and any other helper handed a
    ledger contains no `_SETTLEMENT_LOCK`. A helper that both counts and locks self-deadlocks
    silently, and this is the check that stops one being written.
22. `test_the_rule_is_held_by_one_lock_the_whole_module_shares` passes unchanged: the lock is
    still `threading.Lock`, still not an `RLock`, and still declared exactly once.
23. `_decide_settlement` holds the lock across its ledger read, the receiver check, the
    already-decided check, the pair count and the append, and holds it across nothing else:
    body validation happens before it is taken.
24. **`tests/test_web_api.py` gains `test_two_decisions_at_once_answer_one_settlement_and_refuse_the_other`.**
    Built exactly like task 14's `test_two_marks_at_once_record_one_settlement_and_refuse_the_other`:
    two clients for the receiver, the first request stopped inside the rule at the moment it has
    read the ledger by monkeypatching `balances.settlement_states`, the second sent while it is
    stopped there, every wait bounded by `INTERLEAVE_GRACE`, no socket bound. The two statuses
    are `[200, 409]` in some order and exactly one decision is stored.
25. Confirming is refused `409 settlement_already_pending` when the settlement's ordered pair
    carries more than one unanswered claim. The second claim is fabricated by appending a
    `SettlementEvent` directly through the store, since one process cannot produce it through
    the endpoint, and the test says so in a comment.
26. Rejecting the same settlement in the same state is accepted, and after that rejection the
    pair carries one unanswered claim and confirming it is accepted. Rejection is the recourse,
    and this is what proves it exists.
27. `SettlementAlreadyPending`'s docstring gains a sentence recording this second use, and the
    docstring of `_SETTLEMENT_LOCK` gains a sentence recording that issue #16 did what it asked.

### The balances payload

28. `GET /api/balances` gains a top-level `rejected` array and nothing else at the top level:
    the payload's keys are exactly `currency`, `net`, `transfers`, `pending`, `rejected`.
29. `rejected` holds one entry per settlement in the group whose derived state is `REJECTED`,
    each the same seven-key `_settlement_view` shape, and holds no pending and no confirmed
    settlement. `pending` still holds only settlements whose state is `PENDING`.
30. A confirmed settlement appears in neither array, and a test asserts that directly after a
    confirmation through the endpoint.
31. `rejected` ascends by `(created_at, id)`, oldest first, and is built by filtering the events
    `_read_balances` has already read rather than by a second store call. A test with two
    rejected settlements sharing a timestamp pins the id tiebreak.
32. Every transfer still carries exactly six keys and `awaiting_confirmation` is still computed
    from unanswered claims only: a rejected settlement whose pair matches a transfer sets it
    nowhere. `_read_balances`'s docstring sentence predicting a refinement is replaced by one
    recording that none was needed.
33. Every existing assertion in `tests/test_web_api.py` that pins the balances payload exactly is
    updated by **adding the new key at its exact value**, never by loosening an equality to a
    subset. At least these two: the empty-ledger `assert balances_of(signed) == {...}` in
    `test_a_settled_group_reports_an_empty_pending_list`, and
    `test_the_balances_payload_gains_pending_and_nothing_else_at_the_top_level`, whose set
    equality gains `rejected`.
34. `GET /api/expenses` is byte-identical before and after a confirmation and before and after a
    rejection. A settlement decision is not an expense and the feed shows nothing about it.
35. After a confirmation, `GET /api/debts/<payer>/<receiver>` gains exactly one entry, of kind
    `settlement`, whose amount is the settlement's amount, because `debt_sources` lists
    confirmed settlements only. After a rejection, every pair's payload is byte-identical to
    what it was before.

### What moves and what does not

36. **`tests/test_web_api.py` gains
    `test_a_confirmed_settlement_moves_exactly_the_amount_over_generated_ledgers`.** At least
    50 ledgers built with `random.Random(LEDGER_SEED)` through the existing `generate_ledger`,
    each with two linked clients, a settlement marked by the payer and confirmed by the
    receiver through the endpoint, asserting for each:
    * `after.net_for(payer).cents == before.net_for(payer).cents + amount_cents`
    * `after.net_for(receiver).cents == before.net_for(receiver).cents - amount_cents`
    * every other member's `net_for` is unchanged
    * `after.owed_between(receiver, payer).cents == before.owed_between(receiver, payer).cents +
      amount_cents`
    * `after != before`
37. **`tests/test_web_api.py` gains
    `test_a_rejected_settlement_moves_no_balance_over_generated_ledgers`.** The same walk,
    rejecting, asserting `after == before` by `Balances` value equality, that `net` and
    `pairwise` are equal item by item, and that the payload's `currency`, `net` and `transfers`
    are unchanged.
38. **Both are falsified, and the falsification is run and recorded.** Make `_decide_settlement`
    append `REJECTED` regardless of the body: criterion 36's test must fail. Make it append
    `CONFIRMED` regardless: criterion 37's test must fail. Delete
    `if states[settlement.id] is not SettlementState.CONFIRMED: continue` from `balances.py`:
    criterion 37's test and task 14's
    `test_a_pending_settlement_moves_no_balance_over_generated_ledgers` must both fail. Restore
    the source after each, and record all three results. A criterion that passes under its own
    mutation has not been met.
39. A companion test asserts the decision is real rather than discarded: after the same request,
    `store.list_settlement_decisions(settlement_id)` is one longer and
    `balances.settlement_states(store.list_events(group_id))` reports the state that was asked
    for.
40. A confirmation for more than the pairwise debt is accepted and flips the pair, and a test
    asserts the resulting `owed_between` runs the other way. `balances.py`'s stated rule, that
    a settlement is never validated against the debt it appears to clear, is not weakened by
    anything in this task.

### Two users never see different balances

41. **`tests/test_web_api.py` gains
    `test_two_members_read_the_same_balances_bytes_through_every_state`.** Two clients linked to
    two different members read `GET /api/balances` and compare
    `get_data(as_text=True)` byte for byte at four points: before any claim, after the payer
    marks a payment, after the receiver confirms it, and after the receiver rejects a second
    claim on another pair. All four comparisons are equalities.
42. The same test asserts the bytes **changed** between the pending read and the confirmed
    read, so byte equality across readers cannot be satisfied by an endpoint that does nothing.
43. **`tests/test_web_api.py` gains
    `test_a_third_member_reads_the_same_balances_bytes_as_both_parties`.** A third linked member
    who is party to neither the payment nor the decision reads the same bytes as the payer and
    the receiver, at every one of those four points.
44. A test asserts `_read_balances` reads nothing about the acting member: the source of
    `_read_balances` contains no `flask.g.member`, and the three payloads above are equal by
    construction rather than by coincidence.
45. On the screen, the same claim is task 12's ` (you)` rule: one fixture is rendered on three
    phones and the rejected row differs only in where ` (you)` falls.
    (scenario: `everyone_sees_the_same_rejected_payment`)

### The client

46. `app/api.js` gains exactly one exported name, `decideSettlement(settlementId, decision)`,
    taking the object literal from fifteen names to sixteen, and `API_SURFACE` in
    `tests/test_web_shell.py` gains it. It calls
    `call('POST', '/settlements/' + encodeURIComponent(settlementId) + '/decision',
    {decision: decision})` and builds no other key.
47. The id is percent-encoded, proved by a scenario whose fixture uses a settlement id carrying
    a space, a percent sign and a hash, declaring the exact encoded path, in the style
    `the_api_client_builds_a_debt_path_from_two_ids` uses for the debts route.
48. The body on the wire is exactly `{"decision":"confirmed"}` and exactly
    `{"decision":"rejected"}`, pinned by `expectRequests` entries.
49. Nothing else in `app/api.js` changes: no new handler, no new kind, no new status in the
    classification ladder, no retry and no state, so
    `test_the_api_client_holds_no_state_of_its_own` and
    `test_the_client_names_its_three_failure_paths` pass unchanged. The header comment's status
    table gains `settlement_already_pending`, `settlement_already_decided` and
    `not_the_receiver` on the rows they fall on, which is a correction of a list that reads as
    exhaustive and has been stale since task 14.

### The markup

50. `app/index.html` gains exactly two things, both inside `<section id="screen-balances">`: a
    `<p class="balances-decision" id="balances-decision" role="status"></p>` between
    `#balances-derived` and the `Net positions` heading, and a
    `<div id="balances-rejected-block" hidden>` between `#balances-pending-block` and the
    `Suggested payments` heading, holding an `<h2>` reading exactly `Not confirmed`, a
    `<p class="balances-note">` reading exactly the note quoted in "The exact words", and an
    empty `<ul class="balances-list" id="balances-rejected">`. The head, header, gate, notice,
    feed and add sections, the nav and the script tag are untouched.
51. `#balances-decision` ships empty and carries no `hidden` attribute in the committed markup,
    and `app/app.js` never sets `hidden` on it.
52. `BALANCES_IDS` in `tests/test_web_shell.py` gains `balances-decision`,
    `balances-rejected-block` and `balances-rejected`, so
    `test_the_balances_section_carries_every_id_the_screen_toggles` passes with the set pinned
    exactly.
53. A test asserts the document order `#balances-derived` < `#balances-decision` <
    `Net positions` < `#balances-pending-block` < `#balances-rejected-block` <
    `Suggested payments`.

### The rejected block

54. `#balances-rejected-block` is shown only when at least one row of `rejected` was rendered,
    and is hidden in every other state: nothing rejected, the busy state, the failure state, the
    empty-roster state, a `rejected` that is absent, a `rejected` that is not an array, and a
    `rejected` whose every row was unreadable.
    (scenarios: `everyone_sees_the_same_rejected_payment`,
    `a_rejected_row_the_screen_cannot_read_is_left_out_rather_than_guessed_at`,
    `leaving_the_balances_screen_and_returning_clears_the_rejected_list`)
55. `balancesClear()` empties `#balances-rejected` and hides `#balances-rejected-block`, and
    leaves `#balances-decision` alone. Neutralise the first and
    `leaving_the_balances_screen_and_returning_clears_the_rejected_list` goes red; neutralise
    the second and `confirming_a_payment_reads_the_figures_again_and_says_what_changed` goes
    red.
56. A rejected row is one `<li class="balances-rejected">` carrying `data-settlement`,
    `data-from` and `data-to` as attributes only, holding exactly two children, a line and a
    `<time>`, and never a third.
    (scenario: `everyone_sees_the_same_rejected_payment`)
57. The line reads `<Payer> marked <amount> as paid to <Receiver>, and it was not confirmed.`
    with both names through `balancesName` and the amount inserted exactly as received inside
    its own `.balances-figure` span. The `<time>` holds `feedDate(created_at)` as text and
    `created_at` unchanged in a `datetime` attribute.
    (scenario: `everyone_sees_the_same_rejected_payment`)
58. One validator serves both lists, taking the expected state string, and each list passes its
    own: a row is rendered only when it is an object whose `id`, `from_member_id`,
    `to_member_id`, `amount` and `created_at` are all strings and whose `state` is exactly the
    expected string, by one strict equality. Any other row is left out and the rest of the list
    still renders; an absent or non-array list is treated as empty.
    (scenario: `a_rejected_row_the_screen_cannot_read_is_left_out_rather_than_guessed_at`)
59. Rows render in the order the server sent them. `app/app.js` still contains no `.sort(` and
    no `.reverse(`, so `test_the_shell_never_reorders_what_the_server_sent` passes unchanged.
60. No settlement id and no member id is ever rendered as visible text, in any state, the
    failure state included.

### The controls on a pending row

61. A pending `<li>` holds a third child, appended last, when and only when its `to_member_id`
    equals the acting member's id. `childNodes[0]` is still the line and `childNodes[1]` is
    still the `<time>` in every case, and a row with no third child is byte for byte what task
    14 rendered.
    (scenarios: `the_receiver_can_confirm_a_payment_that_was_marked_as_paid`,
    `the_payer_is_offered_no_way_to_answer_their_own_claim`,
    `a_third_member_is_offered_no_way_to_answer_someone_elses_claim`)
62. The third child is a `<div class="balances-answer">` holding exactly four children in this
    order: a `<p class="balances-answer-note">` reading exactly `Neither answer can be undone.`,
    a `<button type="button" class="balances-confirm-button">` whose visible text is exactly
    `Confirm`, a `<button type="button" class="balances-reject-button">` whose visible text is
    exactly `Reject`, and a `<p class="balances-answer-status" role="status">` shipped holding
    `''`.
    (scenario: `the_receiver_can_confirm_a_payment_that_was_marked_as_paid`)
63. The two `aria-label` values are exactly
    `Confirm: <Payer> marked <amount> as paid to <Receiver>` and
    `Reject: <Payer> marked <amount> as paid to <Receiver>`, with both names through
    `balancesName`, so on the receiver's phone the receiver carries ` (you)`. Each visible label
    is a prefix of its accessible name, and two claims on one screen produce four different
    accessible names.
    (scenario: `the_receiver_can_confirm_a_payment_that_was_marked_as_paid`)
64. Two pending rows both addressed to the acting member each carry their own controls, their
    own status line and their own closure. Answering one changes nothing about the other before
    the re-read.
    (scenario: `the_receiver_can_confirm_a_payment_that_was_marked_as_paid`)
65. The payer of a claim, a third member, and an account whose acting id is `null` are offered
    no control on any pending row, and both blocks still render for all three.
    (scenarios: `the_payer_is_offered_no_way_to_answer_their_own_claim`,
    `a_third_member_is_offered_no_way_to_answer_someone_elses_claim`,
    `an_unlinked_account_is_offered_no_way_to_answer_anything`)

### Pressing them

66. The handler calls `ledgerIsUp()` first and returns having changed nothing when it is false:
    no request, no message, no `disabled`, no `aria-busy`, and `#balances-decision` still empty.
    `ledgerIsUp` is called, never reimplemented.
    (scenario: `answering_a_payment_behind_a_curtain_asks_for_nothing`)
67. **At the moment the request goes out**, the action region already carries `aria-busy="true"`,
    its `role="status"` line already reads exactly `Answering this payment.`, both buttons are
    already `disabled`, and `#balances-decision` is already empty. Proven with `page.onRequest`.
    (scenario: `confirming_a_payment_announces_it_before_and_after_the_request`)
68. The first press sends exactly one `POST` with the exact body of criterion 48, followed by
    exactly `GET /api/members` and `GET /api/balances` from the re-read, and no other request.
    Drawing the controls makes no request at all.
    (scenario: `the_receiver_can_confirm_a_payment_that_was_marked_as_paid`)
69. After a 200, `aria-busy` is removed, `#balances-decision` reads exactly
    `Confirmed. The payment of 600.00 from Sam to Ali (you) is now counted in the figures
    below.` for a confirmation and exactly
    `Not confirmed. The payment of 600.00 from Sam to Ali (you) is not counted, and it can be
    marked as paid again.` for a rejection, and the screen is rebuilt from the second read: the
    net list, the transfer list and both blocks hold exactly what that read said.
    (scenarios: `confirming_a_payment_reads_the_figures_again_and_says_what_changed`,
    `the_receiver_can_reject_a_payment_that_was_marked_as_paid`)
70. The sentence is written **before** the re-read is started, so a re-read that fails still
    leaves it on screen. Proven by a scenario whose second `GET /api/balances` fails: the
    balances failure message is showing, the lists are empty, and `#balances-decision` still
    carries the outcome.
    (scenario: `an_answer_whose_refresh_fails_still_says_the_answer_was_recorded`)
71. **Two presses answer one settlement.** Dispatching `click` twice on `Confirm`, and
    dispatching `Confirm` then `Reject`, each send exactly one `POST`. The guard is one closure
    flag for the row, not the `disabled` attribute, which the harness does not consult.
    (scenarios: `tapping_confirm_twice_answers_one_settlement`,
    `tapping_reject_after_confirm_sends_one_answer`)
72. A failure of any kind writes exactly `That was not answered.` into that row's status line and
    re-enables both buttons. `#balances-decision` stays empty, `#balances-error` stays hidden,
    the net list, both blocks and an open drill-down are untouched, no re-read is fired, and no
    server sentence appears anywhere. The balances region still contains none of `error.status`,
    `error.code`, `error.kind`, `error.say`.
    (scenario: `an_answer_that_will_not_record_says_so_and_can_be_tried_again`)
73. Pressing again after a failure sends a fresh `POST`, because nothing was kept.
    (scenario: `an_answer_that_will_not_record_says_so_and_can_be_tried_again`)
74. The re-read and the sentence are guarded by `balancesAttempt`, captured before the request
    and compared before either happens, so an answer arriving after the list has been rebuilt
    writes nothing and fires nothing. Checkable by reading the source; this file records that no
    scenario proves it and why.
75. `#balances-decision` is emptied at the start of every press and by `balancesEntered()`
    before it calls `balancesLoad()`, and by nothing else. Leaving the route and returning
    clears it.
    (scenario: `leaving_the_balances_screen_and_returning_clears_the_rejected_list`)
76. After a rejection and its re-read, the transfer row for that pair carries
    `awaiting_confirmation: false` and offers the payer `Mark as paid` again, and the claim is
    in the rejected block.
    (scenario: `a_rejected_payment_can_be_marked_as_paid_again`)
77. Confirming the only claim in a group with nothing left to settle rebuilds the screen from
    the second read: the pending block is gone, `No payments needed. Every net position is
    zero.` is replaced by whatever that read said, and `#balances-decision` carries the outcome.
    (scenario: `confirming_the_last_claim_in_a_settled_group_reads_the_figures_again`)
78. Nothing calls `focus()`: `app/app.js`'s balances region still contains no `.focus(`, so
    `test_the_drill_down_never_moves_focus` passes unchanged. This file records the focus gap
    the re-read leaves and the hand check that covers it.

### Layout and the shell rules

79. All new CSS is appended at the end of `app/styles.css`, inside the existing
    `/* Balances --- */` block, every selector prefixed `.balances-`, with no existing rule
    modified, so `test_every_balances_selector_is_namespaced_to_this_screen` passes.
80. `.balances-confirm-button` and `.balances-reject-button` each carry a `min-height` of at
    least 44px, a `font-size` of at least 16px and full-width block layout, and are stacked
    rather than laid out on one line, so
    `test_no_rule_sets_a_hit_area_below_forty_four_pixels`,
    `test_every_transfer_row_clears_the_hit_area_floor` and
    `test_no_rule_sets_a_font_size_below_sixteen_pixels` pass unchanged.
81. `test_only_the_three_controls_that_really_do_something_look_tappable` is **replaced** by a
    test whose name says what is now true, allowing exactly five selectors to carry `cursor`,
    all of them `pointer`: `.balances-transfer-button`, `.balances-debt-button`,
    `.balances-mark-button`, `.balances-confirm-button` and `.balances-reject-button`. The
    `content:` ban is kept unchanged and nothing else about the test is relaxed.
82. `test_all_three_controls_show_a_keyboard_user_where_they_are` is **replaced** by the same
    test over the same five classes, each with a `:focus-visible` rule carrying a visible
    outline. No sixth selector is admitted.
83. `test_the_three_lists_ship_empty_under_headings_in_the_stated_order` is **replaced** by a
    four-list version asserting the `<h2>` sequence is exactly `Net positions`,
    `Awaiting confirmation`, `Not confirmed`, `Suggested payments`, and that all four `<ul>`
    elements ship empty.
84. `CARRIES_A_NAME` gains `.balances-rejected-line` and `.balances-decision`, and both carry
    `overflow-wrap: break-word`, so `test_every_line_that_carries_a_name_can_break_a_long_one`
    passes over the widened list. `.balances-figure` is still the only selector in the block
    carrying `white-space: nowrap`.
85. `test_the_action_region_never_takes_space_while_it_is_empty` gains
    `.balances-answer-status` and `.balances-decision`: neither carries `min-height` or padding,
    neither is ever given `hidden`, and no `:empty` selector is used anywhere in the block.
86. No `animation`, `transition` or `@keyframes` is added, no `row-reverse`, `column-reverse`,
    `order` or absolute positioning, and no `content:` declaration, so
    `test_the_balances_block_adds_no_animation` and
    `test_the_balances_block_never_moves_a_row_out_of_document_order` pass unchanged.
87. `app/app.js` still contains none of `fetch`, `/api`, `innerHTML`, `outerHTML`,
    `insertAdjacentHTML`, `document.write`, `toFixed`, `parseFloat`, `parseInt`, `Number(`,
    `Math.round`, `Math.floor`, `/ 100`, `Intl`, `toLocaleString`, `NumberFormat`, `0.00`, `$`,
    `£` or `€`, so `test_the_narrowed_rule_still_bites`,
    `test_only_the_api_client_calls_the_back_end`,
    `test_the_balances_screen_reimplements_no_money_handling`,
    `test_the_shell_builds_rows_without_parsing_markup` and
    `test_no_shell_file_prints_a_currency_symbol` pass unchanged.
88. Every `setAttribute` added in the balances region names its attribute with a single-quoted
    lower-case literal, the only `role` it ever sets is `'status'`, and the region assigns no
    `.role` property and contains no `createElement('a')`, `createElement('details')`,
    `createElement('summary')`, `tabindex`, `onclick`, or `keydown`, `keyup`, `keypress`,
    `pointerdown` or `touchstart` listener, so
    `test_the_transfer_row_is_a_disclosure_and_nothing_hand_rolled` passes unchanged.
89. The balances region still contains none of `localStorage`, `sessionStorage`, `indexedDB`,
    `setInterval`, `setTimeout`, `requestAnimationFrame`, `onUnauthenticated`, `onNotLinked`,
    `onOffline` or `location.hash =`, so
    `test_the_balances_screen_keeps_no_copy_of_a_derived_figure` and
    `test_the_balances_screen_registers_none_of_the_three_global_handlers` pass unchanged.
90. Every `getElementById('...')` literal added names something present in `app/index.html`, so
    `test_every_element_the_router_reaches_for_exists_in_the_document` passes unchanged. Dynamic
    nodes are reached through closures, never through a class selector.
91. `ROUTES` still holds exactly `#/feed`, `#/add` and `#/balances`. Answering a claim changes
    no hash, calls no `pushState` and no `replaceState`, and scrolls nothing.
    (scenario: `the_receiver_can_confirm_a_payment_that_was_marked_as_paid`)

### The harness

92. `tests/shell_harness.mjs` gains no DOM stub widening at all: the diff touches the scenario
    list and its helpers only, and the guarded proxy is unchanged.
93. The following scenarios are appended, each named as a sentence, each declaring its exact
    ordered request list with `expectRequests`, each registering an answer for every call it
    makes, and each added to `SCENARIOS` in `tests/test_shell_behaviour.py` so the two lists
    stay exactly equal, in this order:
    - `the_receiver_can_confirm_a_payment_that_was_marked_as_paid`
    - `the_receiver_can_reject_a_payment_that_was_marked_as_paid`
    - `confirming_a_payment_announces_it_before_and_after_the_request`
    - `confirming_a_payment_reads_the_figures_again_and_says_what_changed`
    - `an_answer_whose_refresh_fails_still_says_the_answer_was_recorded`
    - `tapping_confirm_twice_answers_one_settlement`
    - `tapping_reject_after_confirm_sends_one_answer`
    - `an_answer_that_will_not_record_says_so_and_can_be_tried_again`
    - `the_payer_is_offered_no_way_to_answer_their_own_claim`
    - `a_third_member_is_offered_no_way_to_answer_someone_elses_claim`
    - `everyone_sees_the_same_rejected_payment`
    - `a_rejected_payment_can_be_marked_as_paid_again`
    - `a_rejected_row_the_screen_cannot_read_is_left_out_rather_than_guessed_at`
    - `answering_a_payment_behind_a_curtain_asks_for_nothing`
    - `an_unlinked_account_is_offered_no_way_to_answer_anything`
    - `leaving_the_balances_screen_and_returning_clears_the_rejected_list`
    - `confirming_the_last_claim_in_a_settled_group_reads_the_figures_again`
    - `the_api_client_builds_a_decision_path_from_a_settlement_id`
94. **Exactly one existing scenario changes, and only by strengthening.** In
    `everyone_sees_the_same_payment_awaiting_confirmation`, the receiver's phone now sees a
    third child on the pending row, so its `children` reading becomes 3 for the receiver and
    stays 2 for the payer and the third member, and assertions about the two controls and their
    accessible names are added on the receiver's phone only. Its comment records why.
    `childNodes[0]` and `childNodes[1]` keep their meanings and every other assertion in it is
    untouched.
95. No other existing scenario is weakened, renamed, deleted, reordered or turned into a
    source-text assertion, and no existing fixture's member ids are changed to dodge a new
    behaviour. In particular `a_pending_row_the_screen_cannot_read_is_left_out_rather_than_guessed_at`
    already carries a claim addressed to the acting member and stays green unchanged, because it
    asserts the row's line and not its child count.
96. No new scenario asserts focus movement, a cached session view, an `aria-current` value or
    the escaping of markup: those are issue #37's recorded gaps and the stub cannot see them.
97. Running the harness with no substitutions passes every scenario and exits 0, and all six
    mutant tests still pass unchanged, still exiting 1 and still naming the scenarios they name
    today.

### The documents, the worker and the suite

98. `Receiver confirmation` moves from `What does not exist yet` to `What works today` in
    **both** `CLAUDE.md` and `README.md`, with the backlog citation dropped, in the way task 14
    moved `Mark as paid`. Its entry moves from `NOT_YET` to `WORKS_TODAY` in
    `tests/test_web_shell.py`, with evidence that must now be present:
    `("index.html", 'id="balances-rejected"')` and `("app.js", "api.decideSettlement(")`.
    `test_both_documents_agree_on_what_works_today`,
    `test_both_documents_agree_on_what_does_not_exist_yet`,
    `test_every_capability_the_documents_claim_is_in_the_shell` and
    `test_nothing_the_documents_call_missing_is_in_the_shell` all pass.
99. The two moved bullets say what is now true and name the two gaps that remain: only the
    receiver may answer, an answer cannot be undone, a claim whose receiver is not linked can be
    answered by nobody, and a payer cannot withdraw a claim the receiver has not answered
    (issue #66).
100. `app/sw.js` is edited on exactly one line: `SHELL_DIGEST` is set to the twelve hex
     characters `test_the_recorded_digest_matches_the_files_it_covers` prints when it fails,
     pasted verbatim. `VERSION` stays `'v4'`, `SHELL` is unchanged, and nothing else in the file
     moves. That test is never skipped, loosened, xfailed or deleted, and no file is added to or
     removed from `app/`, so `test_app_holds_exactly_the_promised_files` and
     `test_the_worker_precaches_exactly_the_shell` pass unchanged.
101. **No test name added to any module already exists in that module.** Before naming a test,
     grep the file: `tests/test_web_api.py` is over 5000 lines, a collision silently deletes the
     earlier test with the suite green, and it has happened twice. A `--collect-only` id diff
     against `master` is what proves no test was lost.
102. `uv run python -m pytest` passes with nothing skipped and nothing xfailed, and the count
     reconciles: master collects **2343**, and this branch collects 2343 plus the tests this task
     adds minus the three it renames, which are criteria 81, 82 and 83, each with its stronger
     replacement among the additions. Diff the two `--collect-only` id sets and show the
     arithmetic. Plain `uv run pytest` fails on this machine with an access-denied spawn error
     and is not the command.
103. Every non-obvious choice made here carries a one-line comment where it is implemented, so
     the next person does not undo it by tidying: why only the receiver may answer and why that
     includes the payer, why the wire map is derived rather than written twice, why an unknown
     settlement is a 404 while an unknown member on the debts path is a 400, why a second
     decision is refused rather than appended, why the pair count exists and what it is worth,
     why the counting helper takes no lock, why rejected settlements get a list of their own
     rather than joining `pending`, why `awaiting_confirmation` needed no refinement, why the
     answer is 200 and not 201, why this task re-reads where task 14 did not, why the outcome
     sentence is written before the re-read, why `#balances-decision` survives
     `balancesClear()`, why the two buttons are stacked, and why one closure flag serves both.

---

## Verified by hand

Browser only, two profiles. Record each as checked, against a store seeded by
`scripts/setup_group.py` and served with `uv run python scripts/serve.py --store ledger.sqlite3`.
Tick "Update on reload" in DevTools, Application, Service Workers first, or the cached shell
serves the old files.

- Sam marks a payment. Ali, in a second profile, opens Balances, reads the claim, presses
  `Confirm`, and reads the screen aloud: it says the payment is counted and the figures below
  include it, without anybody asking a question.
- Confirm the net positions and the suggested payments moved on Ali's phone, and that reloading
  Sam's phone shows the same figures.
- Sam marks another payment. Ali presses `Reject`. The claim moves to `Not confirmed` on both
  phones, no figure moved, and Sam is offered `Mark as paid` on that row again. Sam marks it
  again and it is accepted.
- Cass, a third member, sees both rows and no controls at all.
- Sam opens the claim addressed to Ali and confirms there is no control on it.
- Press `Confirm` twice quickly and confirm the Network panel shows one `POST` and one refresh.
- Stop the server, press `Confirm`, and confirm the failure sentence appears inside that row
  with the rest of the screen intact. Restart it and press again: it records.
- With VoiceOver or NVDA: tab to `Confirm`, hear its accessible name naming the payment, hear
  the note that it cannot be undone, press Enter, hear `Answering this payment.` and then the
  outcome sentence after the screen rebuilds. Record where focus lands afterwards and confirm
  the outcome sentence is reachable at the top of the screen.
- Tab through a pending row addressed to you: `Confirm`, then `Reject`, in visual order, with a
  visible focus ring on each.
- A display name containing `<`, `&` and a quote renders as those characters in the rejected
  row, in the outcome sentence and in both accessible names.
- At 320x568, 360x640, 390x844 and landscape 844x390, with a 40-character display name and two
  claims addressed to you: no horizontal scroll on `.content`, nothing clipped, the amounts
  whole, and both buttons reachable above the nav.
- Console is clean on entry, on confirming, on rejecting, after a failed answer, and after
  signing back in.

---

## Out of scope

- **Withdrawing or cancelling a claim, in any form.** This is **issue #66** and is deliberately
  left open. A rejected claim already frees the ordered pair for a fresh one, which #64 pinned
  with `test_an_answered_claim_frees_the_pair_for_a_fresh_one`, so the only gap that remains is
  a receiver who never answers at all, leaving the pair blocked with no recourse for the payer.
  That gap is real, it is known, it is #66, and it is **not** built here. No endpoint, no
  control, no `DELETE`, and no widening of this endpoint to let the payer decide. It has not
  been forgotten: it was decided against, by the repository owner, for this task.
- **Any expiry, reminder, escalation or auto-rejection of an unanswered claim.** The same gap,
  wearing a timer.
- **Notifications of any kind**, push, email, badge, unread count or a "chase Ali" button. The
  spec cuts notifications outright: people find claims and answers by opening the app.
- **Undoing, editing or deleting a decision.** Events are append-only and a second decision is
  refused.
- **Partial confirmation**, confirming part of a claimed amount, or splitting one claim into
  instalments. The spec cuts partial settlements: "a suggested transfer is confirmed in full or
  not at all".
- **Validating the claim against the simplify plan or the pairwise debt** at decision time, and
  warning, blocking or annotating a confirmation that would flip a pair or move the group away
  from zero. `balances.py` states why, and task 14 already refused the same thing at the other
  end.
- **Any change to `derive_balances`, `simplify_debts`, `debt_sources`, `settlement_states`,
  `events.py` or `store.py`.** They already do what this task needs.
- **A `GET /api/settlements`, a settlements screen, a decision history view or a fourth route.**
  `ROUTES` keeps exactly three entries and the claims keep riding on the balances read.
- **Showing settlements or decisions in the expense feed.** A settlement is not an expense.
- **A third list for confirmed settlements**, or any activity log. A confirmation shows up as
  moved figures and in the drill-down, which is where the ledger already explains itself.
- **Ageing out or capping the rejected list.** Named as an accepted cost above and left as a
  backlog candidate.
- **Rate limiting this endpoint.** The limiter exists for credential guessing; a linked member
  answering a claim is not that, `_create_expense` and `_create_settlement` are not limited
  either, and the 409s are the guard against duplicates.
- **Any staleness or incompleteness signal**, including "pending for 6 days" or highlighting an
  old claim. Task 16 owns that, and both blocks show a plain date through `feedDate` and nothing
  derived from it.
- **Relative dates, a second date spelling, currency symbols or locale formatting.** `feedDate`
  and `format_amount` are the two edges.
- **Front-end arithmetic of any kind**, including comparing a claimed amount against a
  suggestion or totalling either list.
- **Branching on a status, a code or a kind in `app/app.js`.**
- **Moving focus after the re-read.** Named as a gap above; fixing it is a shell-wide focus
  decision.
- **Bumping `VERSION` in `app/sw.js`, or touching anything in it but `SHELL_DIGEST`.**
- **A JavaScript test runner, a bundler, a framework, ES modules, a linter or a formatter.**
- **Any new dependency in either language**, runtime or dev.
- **`plans/spec.md` and `plans/backlog.md`.** This task implements what they already say.
- **`plans/tasks/14-mark-as-paid.md`.** Not modified. Its criteria 32, 36, 45 and 50 constrain
  this task and are not amended.

## Constraints

- Files to modify, and nothing else: `src/splitwise_lite/web.py`, `app/api.js`, `app/app.js`,
  `app/index.html`, `app/styles.css`, `app/sw.js` (one line), `CLAUDE.md`, `README.md`,
  `tests/test_web_api.py`, `tests/test_web_shell.py`, `tests/shell_harness.mjs`,
  `tests/test_shell_behaviour.py`.
- No file is created and no file is deleted. Nothing is added to or removed from `app/`.
- **Nothing under `src/splitwise_lite/` except `web.py` is modified.** If a criterion appears to
  need a domain change, a new field on an event or a change to the fold, **stop and raise it
  loudly** rather than editing it from here.
- Every change in `app/app.js` stays inside the balances region, from the
  `/* --- The balances screen ---` banner to the end of the file. No function above it is
  edited, `showApp()`, `ledgerIsUp`, `feedDate` and `feedInstant` included; the region calls the
  last three and modifies none of them. The net list, the currency line, the status region and
  the four fixed messages are untouched.
- In `app/index.html`, two elements are added inside `<section id="screen-balances">` and
  nothing else in the document changes. Task 14's pending block, its heading and its note are
  not reworded.
- In `app/styles.css`, rules are appended at the end of the file, in one block, every selector
  prefixed `.balances-`, with no existing rule modified.
- Every element id and class this task adds is prefixed `balances-`.
- JavaScript is plain, browser-native, classic (non-module) script, in the style already in
  `app/app.js`: an IIFE, `'use strict'`, `var`, named functions, single-quoted strings. No
  framework, no polyfill, no transpilation, no minification. The committed file is the file the
  browser runs.
- Element lookups stay `document.getElementById('literal-id')`, single quoted, naming only
  things present in `app/index.html`. Dynamic nodes are reached through closures.
- Every URL and asset reference stays relative. No absolute `http://` or `https://` anywhere
  under `app/`.
- **Money is integer cents everywhere it is a number and a formatted string everywhere it
  crosses the wire.** `money.format_amount` is the one display edge and `money.parse_amount` the
  one input edge. This endpoint parses no amount at all: a decision restates nothing about the
  settlement. The front end does no arithmetic, no formatting, no comparison and no parsing of
  an amount, ever, and every decision that depends on money arrives server-computed, as
  `direction`, `covers_whole_debt`, `effect` and `awaiting_confirmation` do.
- All ordering is the server's, at every level: `net`, `transfers`, `payer_debts`,
  `receiver_credits`, `entries`, `pending` and `rejected`.
- New tests are appended at the end of their files. The only pre-existing tests that change are
  the ones named in criteria 2, 13, 19, 33, 52, 81, 82, 83, 84, 85, 94, 98 and 101, and each
  changes by gaining a name, a value or an assertion, never by loosening an equality or dropping
  a ban. The three in criteria 81, 82 and 83 are renamed because their names state a number that
  is no longer true; each keeps every rule it had.
- New scenarios are appended to the scenario list in `tests/shell_harness.mjs` and to
  `SCENARIOS` in `tests/test_shell_behaviour.py`, and the two stay exactly equal. Scenario
  fixtures are locals inside their scenario rather than module constants threaded into the
  fixtures above, following task 12a's note.
- Tests run with `uv run python -m pytest`. No test is skipped or xfailed, no test binds a
  socket, and assertions are exact, per `.claude/rules/testing.md`. CI runs the same command on
  Linux and Windows on every PR.
- **No new dependency of any kind, in either language.** Nothing is added to `pyproject.toml`,
  no `package.json` is created, and `.claude/hooks/guard-deps.hs.sh` blocks the ad hoc Python
  route anyway. Per `CLAUDE.md` a dependency is declared then installed with `uv sync`, never
  `pip install` or `uv pip install`. If something here genuinely cannot be built without a
  package, stop and get the user's approval first.
- **This file must not be modified, with one exception: a statement in it that is provably wrong
  may be corrected**, following the precedent tasks 5, 9b, 11, 13 and 14 set. Sharpening a
  criterion, re-scoping one or softening one to suit an implementation is not covered and stays
  forbidden. Every correction carries a dated marker saying what the file used to say, what it
  says now and why.

---

## What task 18 / issue #19 gets from this

The end-to-end smoke test walks "seed a group, enter three expenses covering all three split
modes, assert the simplified transfers, then run one of them through mark-and-confirm and assert
the balance clears". Everything it needs from this task, so it need not reopen these files:

* **Two linked accounts.** `linked_client(app, path, display_name="Ali")` already signs up and
  links a second member, and #19 needs one per party, because one person cannot both claim and
  answer a payment. That is the whole cost of the two-person rule, and it is one line.
* **The claim.** `POST /api/settlements` with `{"to_member_id": ..., "amount": "..."}` from the
  payer, answering `201 {"settlement": {...}}`. The settlement id #19 needs is `settlement.id`
  in that body, or the `id` of the matching row in `pending` on the next balances read.
* **The answer.** `POST /api/settlements/<settlement_id>/decision` with
  `{"decision": "confirmed"}` from the receiver, answering `200 {"settlement": {...}}` with
  `state: "confirmed"`.
* **The attribution #19 depends on.** Task 14's criterion 20 guarantees the mark alone moves
  nothing, and criteria 36 and 38 here guarantee the confirmation moves exactly the amount, so a
  balance that clears after the confirmation clears **because of** the confirmation and because
  of nothing else. That is what makes the smoke test's final assertion mean something.
* **The read.** `GET /api/balances` after the confirmation: the pair is gone from `transfers`,
  `pending` is `[]`, `rejected` is `[]`, and the payload is byte-identical for both parties, so
  #19 may assert it from either client.
* **The rejection path**, if #19 wants it: `{"decision": "rejected"}` moves no figure and leaves
  the claim in `rejected`, and the pair is then free for a fresh `POST /api/settlements`.
* **What #19 must not assume.** The confirmation is refused for anybody but the receiver, so a
  smoke test that reuses one client throughout will get a `403 not_the_receiver` and should read
  that as the rule working rather than as a bug.
