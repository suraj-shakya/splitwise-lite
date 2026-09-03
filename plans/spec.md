# Splitwise Lite: Product Spec

**Status:** Draft, pre-build
**Date:** 2026-09-03

## What it is

A shared expense ledger for small groups, delivered as a mobile web app, where the
ledger is the product and settlement is a confirmed event rather than a suggestion.

It is not a payments app (no money moves through it), not a budgeting tool, and it
does not connect to banks.

## Decisions locked

| Question | Decision |
|---|---|
| Core job | Resolve who owes who across the group |
| Who enters data | Every member, with their own account |
| Split rules | Equal, equal across a subset, and uneven shares |
| Settle-up output | Fewest possible transfers, with drill-down to source expenses |
| Payment closure | Payer marks as paid, receiver confirms |
| Platform | Mobile web, installable to the home screen |
| Group scope | Multiple groups eventually (flat, trips) |
| Currency | One currency per group, fixed at creation |

## Three things that will bite

### 1. The real risk is adoption, not arithmetic

The stated pain is the settle-up maths, but nothing gets recorded today, and this
design only works if every flatmate logs their own spends. A half-filled ledger is
worse than memory, because it looks authoritative while being wrong.

Implications:
* Expense entry must take under ten seconds from lock screen.
* The app needs an obvious "this looks incomplete" signal rather than presenting a
  partial ledger as settled truth.

### 2. Netting and audit trail pull in opposite directions

"Fewest payments" discards exactly the information that "show me how you got there"
requires.

Resolution:
* Never store balances. Store immutable expense and settlement events.
* Derive pairwise balances from those events.
* Run debt simplification as a pure display layer on top.
* Every suggested transfer keeps a pointer back to the pairwise debts it absorbed,
  so any figure can be traced to real expenses.

### 3. Receiver-confirms introduces an undefined state

When Sam marks a $40 payment and Ali has not confirmed it, the group balance is
ambiguous.

Resolution:
* The balance does not move until the receiver confirms.
* Pending payments render as a separate "awaiting Ali" row.

Without this, two people see two different versions of the truth.

## Modelling notes

**Collapse all three split rules into one shape.** Every expense stores an explicit
list of `(person, cents)`. Equal and subset splits are resolved to explicit amounts
at entry time. This removes rule types from the data model entirely and leaves one
rounding problem instead of three. Leftover cents must be assigned deterministically,
not to whoever happens to sort first.

**Group currency is immutable** once the first expense lands. Otherwise historical
amounts silently change meaning.

## Version one

Ship:
* A single group
* Expense entry
* All three split modes
* Balances derived from events
* Simplified transfers with drill-down to source expenses
* Mark-and-confirm settlement

Multiple groups is a navigation and schema concern that costs real time and teaches
nothing about whether flatmates will actually log a $12 milk run. That is the question
version one exists to answer.

## Explicitly out of scope for version one

Each of these is a deliberate cut, not an oversight.

**Money movement.** No payment integrations, no PayID, no card handling, no transfer
initiation. The app records that a payment happened; it never moves funds.

**Bank feeds and open banking.** No automatic detection of transfers, no statement
import, no transaction matching. Settlement is confirmed by humans.

**Receipt photos and OCR.** No image upload, no line-item extraction. Amounts are
typed in.

**Multiple groups in the UI.** The schema is built to support them, but only one
group is exposed. No group switcher, no cross-group totals, no group creation flow.

**Invites and onboarding.** Members are added from a manual list. No email invites,
no invite links, no join requests.

**Recurring and scheduled expenses.** Rent, power and internet are entered manually
each time. No templates, no automation.

**Multi-currency within a group.** No exchange rates, no rate storage, no decision
about who absorbs rate movement. One group, one currency.

**Notifications.** No push, no email, no reminders, no nagging. The receiver finds
pending confirmations by opening the app.

**Native apps.** No iOS or Android build, no app store presence.

**Categories, budgets and analytics.** No spend breakdowns, no charts, no monthly
reports. The app answers who owes who, nothing else.

**Partial settlements.** A suggested transfer is confirmed in full or not at all.
Splitting a settlement into instalments is deferred. Flagged as the cut most likely
to need revisiting.

**Member departure handling.** Joining and leaving dates are not modelled, so
historical expenses cannot be scoped to who was actually present. See open questions.

**Offline entry.** No local queue, no conflict resolution. The app requires a
connection to record an expense.

**Edit history UI.** Expenses can be corrected, but there is no version timeline or
"who changed what" view beyond the drill-down.

## Open questions

1. **What happens when someone moves out with an unsettled balance?** This needs an
   answer before build, because it determines whether membership is a flat list or a
   set of dated intervals. Retrofitting dated membership onto a live ledger is
   expensive.
2. Does an expense need to be editable after another member has settled against it,
   and if so, what happens to the confirmed settlement?
