# Splitwise Lite: Build Backlog

Derived from `plans/spec.md`. Stack-neutral: task 1 picks the technology, everything
after that describes capability.

Dependencies are listed only where a task genuinely cannot be built or tested without
another. Tasks that merely read better in sequence are left independent.

## Assumptions

1. **Stack-neutral.** Task 1 chooses the technology. Auth is therefore a real task
   rather than configuration.
2. **Flat membership list.** The spec cuts member departure from v1, so tasks 6 and 9
   assume members are a plain list with no join or leave dates. This is open question 1
   in the spec, and it is the decision most expensive to retrofit.
3. **Expense correction is in v1** (spec: "Expenses can be corrected"), implemented as
   append-only correction events. Open question 2 is flagged inside task 17.

## 1. Project skeleton with one passing test
Goal: A repo that runs and tests green with nothing in it.
Depends on: none
Description: Pick the stack, initialise the project, wire a test runner, and commit a
single trivial passing test. This task exists to make every later task verifiable, so
it is finished when the test command runs green from a clean clone. No application code.

## 2. Domain types and money primitives
Goal: The shared vocabulary every other module compiles against.
Depends on: 1
Description: Define money as integer cents with a currency tag, plus the core types:
member id, allocation (member, cents), expense event, and settlement event. Include
parsing and formatting of user-facing amounts. Floating point never touches money.

## 3. Split resolver
Goal: Turn any of the three split modes into explicit per-person cent amounts.
Depends on: 2
Description: Given a total and a mode (equal across all, equal across a subset, or
uneven by weight or exact amount), produce allocations that sum exactly to the total.
Remainder cents are assigned by a deterministic rule, not to whoever sorts first.
Property-test that allocations always sum to the total across random inputs.

## 4. Balance derivation
Goal: Fold events into pairwise balances without ever storing a balance.
Depends on: 2
Description: A pure function taking a list of expense and confirmed settlement events
and returning who owes who, pairwise. Pending settlements are excluded from the fold.
Tested with hand-written event fixtures covering payer-is-participant, payer-is-not,
and full settlement back to zero.

## 5. Debt simplification with provenance
Goal: Fewest transfers, each traceable to the debts it absorbed.
Depends on: 4
Description: Reduce pairwise balances to a minimum set of transfers, where every
transfer carries references to the pairwise debts it replaced. Provenance is the point
of this task, not an extra: without it the drill-down in task 13 is impossible. Verify
that simplified transfers settle the group to zero.

## 6. Persistence and event store
Goal: Durable, append-only storage for the ledger.
Depends on: 2
Description: Schema for users, groups, members, expense events and settlement events,
with expenses and settlements append-only. Group currency is immutable once set. The
schema is multi-group capable even though v1 exposes one group. Members are a flat
list, with no join or leave dates.

## 7. Accounts and sessions
Goal: Each flatmate can sign in as themselves.
Depends on: 6
Description: Signup, login, logout and session handling, with a user mapping to one
member within a group. Keep it minimal: no password reset flow, no email verification,
no invites. Enough that the app knows who is acting.

## 8. Mobile web shell
Goal: An installable, responsive app frame with placeholder screens.
Depends on: 1
Description: Responsive layout tuned for phones, a web app manifest so it installs to
the home screen, and routing between placeholder screens for feed, add, and balances.
Deliberately independent of auth and the domain layer, so it can be built in parallel
with all of them.

## 9. Group and member setup
Goal: One real group with real people in it.
Depends on: 6, 7
Description: Create the single group with its fixed currency, populate members from a
manual list, and link signed-in users to their member record. No invite links, no
join requests. This is the fixture every screen task needs to show real names.

## 10. Expense entry screen
Goal: Log a spend in under ten seconds.
Depends on: 3, 6, 8, 9
Description: A form for amount, payer, description and split mode, covering all three
modes, resolving to explicit allocations on save. Speed is the requirement, not a nice
to have: default to equal across everyone, keep the amount field focused on open, and
make saving one tap from a filled form.

## 11. Expense feed
Goal: See what the flat has spent.
Depends on: 6, 8, 9
Description: Reverse-chronological list of expenses showing payer, total, description
and who it was split across. Tapping one opens its allocation detail. Read-only in
this task; editing arrives in task 17.

## 12. Balances screen
Goal: Answer who owes who, in the fewest payments.
Depends on: 5, 8, 9
Description: Show each member net position and the simplified transfer list. Every
figure is derived on read from the event log; this screen stores nothing. It is the
screen the whole product exists to render.

## 13. Transfer drill-down
Goal: Prove any suggested payment back to real expenses.
Depends on: 5, 12
Description: Tapping a suggested transfer reveals the pairwise debts it absorbed, and
each of those expands to the source expenses. This answers "why am I paying someone I
never bought anything with", which is the known failure mode of debt simplification.

## 14. Mark as paid
Goal: The payer records that they have transferred the money.
Depends on: 6, 12
Description: From a suggested transfer, the payer appends a settlement event in pending
state. Balances do not move. The transfer renders as awaiting confirmation for both
parties, so nobody sees a cleared debt that is not cleared.

## 15. Receiver confirmation
Goal: A debt clears only when the person owed says so.
Depends on: 4, 14
Description: The receiver confirms or rejects a pending settlement. Only confirmation
admits the event into the balance fold. Rejection leaves the pending row visible with
its state changed. Test that two users never see different balances for the same group.

## 16. Incompleteness signal
Goal: Stop a half-filled ledger from reading as settled truth.
Depends on: 11, 12
Description: Surface staleness on the feed and balances screens: days since the last
expense, and which members have logged nothing recently. This is the mitigation for the
largest risk in the spec, that people stop entering expenses and the app keeps quietly
presenting confident numbers.

## 17. Expense correction
Goal: Fix a wrong amount without rewriting history.
Depends on: 6, 11
Description: Edit or void an expense by appending a correction event rather than
mutating the original. No version timeline UI. Open question: what happens when the
corrected expense already sits behind a confirmed settlement. Decide that before
building this one.

## 18. End-to-end smoke test
Goal: One test that walks the whole product.
Depends on: 10, 12, 15
Description: Seed a group, enter three expenses covering all three split modes, assert
the simplified transfers, then run one of them through mark-and-confirm and assert the
balance clears. This is the regression net for every later change.

## Dependency graph

**Start immediately**
1

**After 1**
2, 8

**After 2**
3, 4, 6

**After 4 / after 6**
5, 7

**After 6 and 7**
9

**After 9 (with 3, 5, 8)**
10, 11, 12

**After 12**
13, 14, 16, 17

**After 14**
15

**After 10, 12, 15**
18

Notes on parallelism:

* Task 8 is the only substantial task with no domain dependency. It can run alongside
  the entire 2 to 7 chain.
* Tasks 3 and 4 are siblings and never touch each other code.
* The graph narrows hard at task 9, because every screen needs real members to render.
  If you want to widen it, stub members in task 8 and pull the screen tasks forward.
* Longest chain is 1 to 2 to 6 to 7 to 9 to 12 to 14 to 15 to 18, nine tasks deep.
