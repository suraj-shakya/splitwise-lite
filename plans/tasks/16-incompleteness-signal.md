# Task 16: the incompleteness signal

**Depends on:** 11 (expense feed) and 12 (balances screen), both landed. Nothing this task
needs is unbuilt.
**Consumed by:** nothing. This is a leaf.
**Closes GitHub issue #17.** The numbering is confusing and has already cost time, so it is
stated once here: **backlog task 16 is GitHub issue #17**, the branch is `task-17`, this file
is named by task number. Issue #16 is a different, already closed task. Anybody writing a
commit message or a PR title reads this paragraph first.

**On duplicated guarantees.** `plans/tasks/60-65-67-checks-that-could-not-fail.md` records,
under "Four copies, not three", what happens when one claim is written into four documents
and pinned by none: rewording the source left four documents false with nothing going red.
So each guarantee below is stated **once**, at the place it is implemented, and a criterion
that wants to restate one points at it by number instead. If review adds a duplicate, delete
the duplicate rather than correcting both.

---

## The four decisions, and why

These are the decisions this task exists to make. Everything in "Acceptance criteria" follows
from them, so argue with these first.

### 1. Where the clock enters, and how a test controls it

**Decision: no new clock seam anywhere. The clock enters at `web.py::_now()`, which already
exists and is already pinned to one place, and the new domain function takes `now` as a
required keyword-only parameter and reads no clock at all.**

This was settled by measurement rather than preference. The repo has already answered this
question in every layer where it has come up, and every one of those answers points the same
way:

* Every ledger event already carries a usable timestamp. `ExpenseEvent`, `SettlementEvent`
  and `SettlementDecisionEvent` each carry `created_at`, and each `__post_init__` runs it
  through `events._require_utc` (`src/splitwise_lite/events.py:150`), which **rejects a naive
  datetime** rather than guessing a zone and normalises to UTC. So there is no work to do to
  get a trustworthy instant, and this was verified rather than assumed.
* The store persists it as fixed-width UTC text, `isoformat(timespec="microseconds")`
  (`store.py:324`), with a schema `CHECK` on every such column requiring length 32, a `T` at
  position 11 and a `+00:00` tail (for example `store.py:620`), and reads it back with
  `datetime.fromisoformat` (`store.py:335`). Round-tripped microsecond-precision UTC, with the
  invariant enforced by the database.
* Three modules are already proven clock-free by a test: `tests/test_store.py:1503`,
  `tests/test_accounts.py:269` and `tests/test_groups.py:280` each parametrise over
  `["now(", "utcnow(", "time.time", "today("]` and refuse them in the module's source.
  `store.py:1079` says it in prose: "The store never reads the clock."
* `balances.py` is proven clock-free more strongly still:
  `test_the_fold_is_a_pure_function_of_its_inputs` resolves every import back to the module it
  names, and `test_a_clock_read_smuggled_in_under_any_name_fails_the_purity_proof` is its
  positive control, with eight cases including the alias `_Instant` that is already in the file.
* `web.py` holds **exactly one** clock read, `_now()` at `web.py:724`, cached on `flask.g` so
  one request has one instant. And that is enforced:
  `tests/test_web_api.py:827::test_the_clock_is_read_once_and_only_in_one_place` asserts
  `len(reads) == 1` and that the one read sits inside `_now`. **An engineer who adds a second
  `datetime.now()` to `web.py` turns the suite red.** This is an interlock, not a convention.

So a test controls the clock in two ways, and neither needs a seam:

* **Domain tests** pass a literal `datetime` to `now=`. The function is pure, so this is total
  control with no monkeypatching, no freezegun and no dependency.
* **Endpoint tests** control the *answer* instead of the clock, by choosing each event's
  `created_at` relative to the real clock, which is what `tests/test_web_api.py` already does
  for ordering. An expense written at `now - timedelta(days=9)` yields 9 whatever hour the
  suite runs at, because the answer depends only on the difference. This is the second reason
  decision 3 picks elapsed periods over calendar days: with a calendar rule, this style of test
  is flaky at midnight, and it is the style the whole file is written in.

Rejected: a `clock` callable on `_Settings`. It would need a field, validation, a
`scripts/serve.py` flag and a documented default, and it buys nothing that choosing event
timestamps does not already buy.

Rejected: computing staleness on the client. **`tests/test_feed_screen.py:385` bans `Date.now(`
and `new Date()` from the whole of `app/app.js`**, so the client cannot know what time it is.
Worth stating plainly because the repo currently predicts the opposite: the `NOT_YET` reason at
`tests/test_web_shell.py:1274` says "Staleness can be computed on the client from the feed
payload the app already fetches". Given that ban, it cannot. That premise is false and this
task's build differs from the one that entry predicts. See "What the backlog and the existing
notes get wrong".

The new function lives in a **new module, `src/splitwise_lite/staleness.py`**, not in
`balances.py`. Reason, measured: `test_the_fold_is_a_pure_function_of_its_inputs` forbids the
name `datetime` at runtime in `balances.py`, resolving aliases, and a threshold expressed with
`timedelta` resolves back to the `datetime` module and would fire it. The new module also gets
its own purity rule, which is deliberately **narrower** than `balances.py`'s: it forbids clock
*reads* and permits clock *arithmetic*, because subtracting two instants is the whole job. As
it happens the implementation needs no runtime `datetime` name at all (see criterion 8), so it
can carry the same annotation-only exemption `balances.py` carries.

### 2. What "recently" means, as a number, and where that number lives

**Decision: seven days. It lives as one `Final` module constant, `QUIET_AFTER_DAYS = 7`, in
`staleness.py`, exposed as a default on the pure function's `quiet_after_days` parameter and
sent to the client on the wire. It is not configuration, not a query parameter and not a
literal in `app/`.**

Seven because the product is a flat: a grocery shop is a weekly rhythm, three days would nag a
flat that shops on Saturdays, and fourteen is too late to reconstruct a fortnight of receipts.
This is a product judgement, not a measurement, and it is the one number in this document that
the user should feel free to overrule. Nothing else depends on its value except criterion 12.

Where it lives, and the cost of each option:

* **A parameter with a constant default** is what tests need: a test varies the threshold by
  passing it, so no test monkeypatches a module constant, and the shipped answer stays one
  number in one place.
* **Not a query parameter.** `tests/test_web_api.py:852::test_no_endpoint_accepts_a_client_supplied_time`
  establishes that no endpoint takes a time from the caller. A client choosing what counts as
  stale is a client choosing a product rule, which is the same mistake one level up.
* **Not a `_Settings` field or a CLI flag.** That is a field, validation, a flag, a default and
  a line of documentation, for a number nobody has asked to vary, and it would let two flats
  read the same sentence with different meanings.
* **The cost, stated honestly:** changing the threshold is a code edit and a release, not a
  setting. That is accepted.

It goes on the wire as `quiet_after_days` so the client can print it without knowing it. The
alternative, hard-coding `7` into `app/index.html`, is the duplicated-claim defect this
repository has already paid for twice: two copies of one number with nothing forcing them to
agree. Criterion 21 refuses a digit in the new copy for exactly that reason.

### 3. Timezone and day boundaries

**Decision: whole elapsed 24-hour periods, computed in UTC, floored, clamped at zero. Not
calendar days, and no timezone is chosen anywhere.**

`days_since_last_expense = (now - newest_expense.created_at).days`, which floors for a positive
difference, with a negative result reported as `0`.

1. **It needs no timezone, and there is none to use.** The `groups` table carries
   `id, name, currency_code, created_at` and no zone column (`store.py:557`). The spec fixes one
   currency per group and says nothing about a zone. A calendar-day rule would require inventing
   one, which is a schema change and a product decision the spec has not made.
2. **Two readers in different zones must read the same number.** Spec section 3 exists to stop
   "two people see two different versions of the truth", and the confirmation design pays real
   cost to keep every phone on one answer. A calendar count in the reader's own zone would show
   7 to the flatmate at home and 8 to the one who is travelling.
3. **It has no boundary in wall-clock time, so no test is flaky at midnight.** A calendar rule
   computed server-side in UTC flips at 00:00 UTC, which is mid-afternoon in Australia, and a
   test asserting `7` would pass or fail depending on the hour CI happened to start. The elapsed
   rule depends only on a difference.
4. **The boundary, stated exactly.** At exactly 7 days and 0 microseconds the figure is 7 and
   the state is `stale`, because the comparison is `>=`. At 6 days 23:59:59.999999 the figure is
   6 and the state is `fresh`. The figure ticks over on the anniversary of the instant, not at
   any midnight.
5. **A future-dated expense gives 0, never a negative number.** `timedelta.days` floors toward
   negative infinity, so a difference of minus half a day is `-1`, and "recorded minus one days
   ago" is nonsense on a screen. The server sets `created_at` from `_now()`
   (`web.py:1404`), so this should be unreachable through the API, but `store.py:1687` records
   that the store deliberately accepts timestamps that disagree because "Phone clocks disagree",
   and a row written by a future `setup_group.py` or a hand-edited database would reach it.
   Clamped, and tested.
6. **The cost, stated honestly.** The figure is elapsed 24-hour periods, which can read one lower
   than a person's calendar intuition: somebody who logged at 23:00 last night and looks at 08:00
   today has elapsed 9 hours, so 0, where their intuition says "yesterday". Because the line only
   ever appears at 7 or more (criterion 12), the worst visible consequence is that the signal can
   appear up to about 24 hours later than a calendar count would have shown it. It errs toward not
   nagging, which is the right direction for a signal whose failure mode is being ignored.

**Which event's timestamp.** The newest **`ExpenseEvent`** only. Settlements and decisions are
excluded: the risk being mitigated is unrecorded *spend*, and a flat that settles up but stops
logging groceries is precisely the failure mode, so letting a settlement reset the clock would
hide the thing the signal is for.

### 4. What the signal says when it cannot know

**Decision: "we do not know" is its own state with its own sentence, and is never rendered as a
confident zero or an empty list. The wire carries a three-valued `state`, not a boolean, so the
client cannot pair "stale" with "no idea how stale".**

This is the shape of issue **#44**, which reports an empty roster being shown a message saying
the roster has not arrived: "known to be empty" rendered with the words for "not known yet".
The two cases here, and the answer to each:

* **A ledger with no expense at all.** There is no last expense, so there is no number.
  `state` is `"never"`, `days_since_last_expense` is `null`, and the balances screen shows a
  sentence with no number in it. The feed never reaches the question, because
  `loadFeed` routes an empty `expenses` array to `feedState('empty')` (`app/app.js:617`), which
  already says the honest thing. This is the worst case for the spec's risk, a brand-new flat
  reading "Every net position is zero" as a settled position, and it is the case a zero would
  have lied about.
* **A member who joined yesterday and has logged nothing.** Not quiet. A member is quiet only if
  they have recorded no expense in the window **and** have been in the group for the whole
  window, which is `member.created_at <= now - quiet_after_days`. Listing somebody who has not
  had time to log anything is #44's mistake again: an absence of data reported as a finding.
  On a group set up yesterday nobody is quiet, and the "nothing recorded yet" sentence carries
  the whole message.
* **A group whose ledger is empty reports nobody as quiet**, even if every member is old enough.
  `quiet_member_ids` is empty whenever `state` is `"never"`. Naming five people for one fact the
  sentence above them already states is noise, and it reads as an accusation of five people for
  one circumstance.
* **A `state` the client does not recognise draws nothing**, following the inert fallback
  `balancesTransferRow` already uses for a transfer with no usable provenance
  (`app/app.js:2592`): silence is the honest answer to a payload this client cannot read.

**The limitation to state and not paper over.** `store.Member.created_at` is when the member
*row* was created, which is when an operator ran `setup_group.py apply`. It is not a join date
in any product sense, and it cannot be: spec open question 1 records that membership is a flat
list with no dated intervals, and calls retrofitting them expensive. So a member re-added after
leaving looks new, and a member whose row was created months after they moved in looks older
than they are. This is the best available proxy, it is used deliberately, and criterion 9
requires the docstring to say so.

---

## What the backlog and the existing notes get wrong

The backlog entry is two sentences and is not authoritative. Four things:

1. **"which members have logged nothing recently" does not say what "logged" means, and the two
   readings differ.** `created_by` (who typed it in) or `payer_id` (who paid)? This task uses
   **`created_by`**, because the spec's risk is that "nothing gets recorded" and "this design
   only works if every flatmate logs their own spends". The consequence has to be said out loud,
   because it will surprise somebody: a flatmate who pays for everything but never opens the app
   is listed as quiet, even though their spending is in the ledger, because somebody else entered
   it. That is correct for the risk being mitigated, and the copy in criterion 20 therefore states
   the bare fact ("no expense entered by") rather than implying the person owes anybody data.
2. **"days since the last expense" is silent on the empty ledger**, which is the single most
   important case, because it is the state a new flat is in and the state where confident zeros
   do the most damage. Decision 4 answers it.
3. **"Surface staleness on the feed and balances screens" reads as symmetric, and it should not
   be.** The two signals are not equally at home on the two screens. Scope, decided: the feed
   carries the age signal only; the balances screen carries both. The feed is a list of expenses,
   so how old the newest one is belongs there, but who has entered nothing is a caveat on
   *figures*, and the feed presents none. The balances screen is, in task 12's words, "the screen
   the whole product exists to render", so both caveats belong on it.
4. **The `NOT_YET` reason in `tests/test_web_shell.py:1274` predicts a build that is impossible.**
   It says staleness "can be computed on the client from the feed payload the app already
   fetches, adding no API method and no new call". The client cannot: `Date.now(` and
   `new Date()` are both banned from `app/app.js`. The rest of that entry is right, and more
   right than it knows: this build adds no API method and no new call either, so the entry is
   still **SILENCE** and the bullets still have to be moved by hand. Criterion 41 replaces the
   reason with what actually happened.

   > **Corrected 2026-09-07, during implementation.** This paragraph used to end "Criterion 30
   > replaces the reason with what actually happened". Criterion 30 is about a payload that
   > carries no `staleness` key at all; the criterion that replaces the `NOT_YET` reason is 41.
   > The claim is unchanged and only the pointer was wrong.

One thing the backlog gets right and this task keeps: it is a display signal. It moves no figure,
stores nothing, and derives everything on read.

---

## Goal

A person opening the feed or the balances screen can tell how much the ledger does not know.
The age of the newest expense and the members who have entered nothing recently are computed on
read from the event log, at one instant per request, by a pure function the domain layer owns,
and are shown on the two screens that present the ledger as answers. A ledger that holds nothing
says so in its own words rather than through a zero, and a member who has not had time to log
anything is not named.

The spec's largest risk, quoted from `plans/spec.md` section "1. The real risk is adoption, not
arithmetic", is what these criteria are designed against:

> The stated pain is the settle-up maths, but nothing gets recorded today, and this design only
> works if every flatmate logs their own spends. A half-filled ledger is worse than memory,
> because it looks authoritative while being wrong.

and its second implication:

> The app needs an obvious "this looks incomplete" signal rather than presenting a partial ledger
> as settled truth.

The word "obvious" in that sentence is a layout property. This suite cannot judge it. See "The
browser gap".

---

## Acceptance criteria

Each is a yes or no reachable by reading a file or running one command. `REPO` is the worktree
root, every path is relative to it, and every path in a message or a test id is POSIX form.

### The domain module

1. `src/splitwise_lite/staleness.py` exists and is the only module this task adds under `src/`.
   Its module docstring states what it computes, that it reads no clock, that `now` is supplied
   by the caller, and the dependency direction: it imports from `events` only, and nothing in the
   package imports it except `web.py`.
2. It declares `__all__`, and `src/splitwise_lite/__init__.py` re-exports those names into its
   own sorted `__all__`, which is the pattern every other domain module follows.
   `tests/test_staleness.py` asserts the re-export in the shape of
   `test_the_package_re_exports_the_public_names_of_both_modules`
   (`tests/test_events.py:522`): for every name, `getattr(splitwise_lite, name) is
   getattr(staleness, name)` and the name is in `splitwise_lite.__all__`.
   **This is also what makes the Flask-absent guarantee cover the new module without editing
   anything.** `test_importing_the_package_does_not_import_the_framework`
   (`tests/test_web_api.py:118`) runs `import splitwise_lite, sys; assert 'flask' not in
   sys.modules` in a fresh interpreter, so once the package imports this module the check reaches
   it. It enumerates no modules and needs no edit.
3. `QUIET_AFTER_DAYS: Final[int] = 7` is declared at module level with a comment giving the
   product reason from decision 2, and is the only place the number 7 appears in `src/`.
4. `StalenessState` is an `Enum` with exactly three members, `NEVER`, `FRESH` and `STALE`, each
   with a docstring line saying what it means. `NEVER` is documented as "no expense has ever been
   recorded, so the age is unknown", which is the distinction decision 4 rests on.
5. `Staleness` is a frozen, slotted dataclass carrying exactly `state: StalenessState`,
   `days_since_last_expense: int | None`, `quiet_member_ids: tuple[MemberId, ...]` and
   `quiet_after_days: int`. Its `__post_init__` enforces the two invariants that make the type
   unable to express a contradiction: `days_since_last_expense is None` if and only if `state is
   StalenessState.NEVER`, and `quiet_member_ids` is empty when `state is StalenessState.NEVER`.
   A test proves each refusal separately.
6. `ledger_staleness(events, members, *, now, quiet_after_days=QUIET_AFTER_DAYS) -> Staleness` is
   the one public function. `events` is an `Iterable[LedgerEvent]`, `members` is a
   `Mapping[MemberId, datetime]` of member id to the instant that member's row was created, and
   `now` is keyword-only and has **no default**, so a caller cannot forget to supply it and
   silently get a clock read.
7. It rejects a naive `now`, and a naive value in `members`, the way `events._require_utc` does
   and with the same wording shape, rather than subtracting it and raising an unhelpful
   `TypeError` from inside the arithmetic. Two tests, each with an anchored `match=`.
8. The module reads no clock, and this is asserted rather than asserted about: a test in
   `tests/test_staleness.py` refuses `now(`, `utcnow(`, `today(`, `time.time` and `monotonic` in
   the module source, in the shape `tests/test_store.py:1503` already uses. A comment beside it
   records that this rule is deliberately **narrower** than `balances.py`'s, permitting clock
   arithmetic and forbidding only clock reads, and that as implemented the module happens to need
   no runtime `datetime` name at all, because `(now - created_at).days` names no class.
9. Every one of these is stated in a docstring, once, where it is implemented: the newest
   `ExpenseEvent` only and why settlements are excluded (decision 3); the elapsed-24-hour rule and
   its `>=` boundary; the clamp at zero and the `store.py:1687` reason a future timestamp is
   reachable; that `members` iteration order is the result's order, so the caller passes a mapping
   built in roster order; that `store.Member.created_at` is a row creation date and not a join
   date, pointing at spec open question 1; and the precondition that `events` are already scoped
   to one group.
10. The function takes **no `group_id`, and checks nothing against one**, and a comment says why:
    it has no group to check against unless it is given one, both call sites obtain their events
    already filtered by group, and it computes no money, so the worst a *single* foreign group's
    events could do is make the ledger read fresher than it is. The docstring states that
    consequence, so a future caller knows the precondition is load-bearing. It is deliberately a
    documented precondition rather than a caller-supplied group, and if review disagrees the fix
    is to add `group_id` and reuse `balances`'s refusal wording.

    > **Corrected 2026-09-07, during implementation, at the manager's instruction.** This
    > criterion previously opened "The function performs **no group check**" and gave the
    > precondition no failure behaviour at all. That half is withdrawn: a precondition with no
    > stated failure behaviour becomes a traceback or, far worse, a plausible wrong number.
    > Criterion 10a now states the failure behaviour. What stands is the rest of it: no
    > `group_id` parameter is added, nothing is filtered, and no event is compared against a
    > group the caller names, so both call sites and both payloads are unchanged.
10a. **A violated precondition is an explicit refusal, and the refusal is a named domain
    exception, not an exception out of the arithmetic and not a computed figure.** The
    precondition criterion 9 documents is that `events` are already scoped to **one** group.
    Exactly one violation of it is detectable with no `group_id` argument, and that one is
    refused: an `events` list carrying two or more distinct `group_id` values raises
    `MixedGroupLedger`, declared in `staleness.py`, named in its `__all__` and a subclass of
    `events.InvalidEvent` and so of `DomainError`. It is raised before any subtraction runs, and
    it is not added to `ERROR_STATUS` or `ERROR_CODE`: neither call site can produce it, so
    reaching it is a server defect and the unmapped 500 `web.py` documents is the right answer,
    exactly as it is for `balances.InvalidLedger`. Decisions carry no `group_id` of their own
    (`events.py:59`), so the check reads expenses and settlements and ignores decisions, which is
    the same asymmetry `balances.derive_balances` lives with. Two tests: one pins the refusal with
    an anchored `match=`, and one proves no figure is computed, by handing it a two-group list
    whose newest expense is the foreign one and asserting it raises rather than returning the
    fresher figure that expense would have produced. What stays undetectable is stated rather
    than papered over: a list scoped to exactly one group that is the *wrong* group satisfies the
    precondition as written, is computed, and is the case criterion 10's "reads fresher than it
    is" covers.
11. The result's ordering rule is not re-derived: the newest expense is chosen with
    `events.ordering_key`, and a test asserts `staleness.ordering_key is events.ordering_key`, in
    the shape `test_the_fold_sorts_with_the_ordering_key_events_py_defines`
    (`tests/test_balances.py:1194`) already uses.
12. `QUIET_AFTER_DAYS` is at least 2, and a test asserts it **with the reason attached in the
    assertion message**: the day count is only ever rendered when it is at or above the threshold,
    so no singular form of "days" is ever needed and there is no pluralisation code anywhere in
    this feature. This is the criterion that keeps that simplification true if somebody lowers the
    threshold to 1.

### What the domain function computes

13. With no `ExpenseEvent` in `events`: `state` is `NEVER`, `days_since_last_expense` is `None`,
    and `quiet_member_ids` is empty, whatever `members` holds and however old they are.
14. With at least one `ExpenseEvent`: `days_since_last_expense` is
    `(now - newest.created_at).days` where `newest` is the `ExpenseEvent` maximal under
    `ordering_key`, clamped to `0` below zero, and `state` is `STALE` when that figure is
    `>= quiet_after_days` and `FRESH` otherwise.
15. A ledger holding settlements and decisions but no expense is `NEVER`. A ledger whose only
    recent event is a settlement is `STALE` on the age of its newest expense. One test each,
    because this is the substance of "settlements do not reset the clock".
16. `quiet_member_ids` holds every member id in `members` for which both hold: the member has
    created no `ExpenseEvent` with `created_at > now - quiet_after_days`, and
    `member_created_at <= now - quiet_after_days`. Membership is by `created_by`, never
    `payer_id`, and a test proves the distinction by giving a member an expense they paid for and
    somebody else recorded, then asserting they are still listed.
17. The order of `quiet_member_ids` is the iteration order of `members`, and a test pins it with a
    mapping whose insertion order is not sorted order, so the guarantee is behaviour and not a
    comment.
18. The boundary cases each have a test, and each asserts an exact integer: exactly
    `quiet_after_days` days elapsed is `STALE`; one microsecond less is `FRESH`; a `created_at`
    one microsecond in the future gives `0` and `FRESH`; a member created exactly
    `quiet_after_days` ago is quiet; one microsecond later is not.
19. A member in `members` who is not in the ledger at all, and a `created_by` in the ledger who is
    not in `members`, are both handled without raising: the first can be quiet, the second is
    ignored. The second is the case an operator creates by deleting nothing and adding a member
    row late, and it must not turn a display signal into a 500.

### The wire

20. `GET /api/expenses` and `GET /api/balances` each gain one key, `staleness`, built by **one**
    helper in `web.py` so the two cannot drift, carrying exactly four keys:

    ```json
    "staleness": {
      "state": "stale",
      "days_since_last_expense": 9,
      "quiet_after_days": 7,
      "quiet_member_ids": ["m3", "m5"]
    }
    ```

    `state` is one of `"never"`, `"fresh"` or `"stale"`, mapped from `StalenessState` by a
    module-level dict in the shape of `_ENTRY_KIND_WIRE` (`web.py:1069`), never by
    `.value.lower()` or an f-string. `days_since_last_expense` is a JSON integer or `null`.
    Both endpoints send the identical object for the same ledger at the same instant, and a test
    asserts that by reading both in one test.

    A three-valued `state` rather than a boolean, for the reason `direction` exists on a net row
    (`web.py:1504`): what counts as stale is a product rule, it lives in one place, and the client
    never compares a count against a threshold. A boolean plus a nullable count can express
    "stale, and I do not know how stale", which is the #44 shape; three states cannot.
21. No new route, and `_API_ROUTES` is not touched. Both endpoints already exist and already
    declare their `_Access.MEMBER`. If a new row appears in that table, this task has gone wrong:
    `_audit_routes` would have refused the app anyway, and the reason there is no new route is that
    a signal about a ledger belongs on the reads that present the ledger, not on a read of its own
    that could disagree with them by arriving at a different instant.
22. `app/api.js` gains and loses nothing. `expenses()` and `balances()` already return the whole
    parsed payload (`app/api.js:389` and `:400`), so the new key arrives with no client change.
    `API_SURFACE` in `tests/test_web_shell.py` is therefore **unchanged**, and
    `test_the_api_client_offers_exactly_the_named_calls` passes unedited. See the note in
    "Constraints" about what that literal actually holds today.
23. `_now()` is called once per request, as it already is, and the same instant reaches
    `ledger_staleness` and everything else in that request.
    `test_the_clock_is_read_once_and_only_in_one_place` passes unedited, and if it fails, the fix
    is to pass `_now()` down rather than to relax the test.
24. `_list_expenses` gains one `list_members()` call, because quiet members need the roster. The
    cost is stated in its docstring: a feed load now queries the roster twice across its two
    requests, which is accepted at flat scale for a handful of rows. The alternative was to send
    the feed only the half it renders, and it was rejected because two differently shaped objects
    both named `staleness` are two copies of one contract with nothing forcing them to agree,
    which is the defect family `plans/tasks/18-end-to-end-smoke-test.md:155` lists this repository
    as having spent days on. One builder, one shape, one test, and the feed ignoring a field it
    does not render costs nothing.

    **So the feed payload carries `quiet_member_ids` and renders none of it, deliberately.** The
    feed shows the age signal only, per "What the backlog and the existing notes get wrong" item
    3, and the key is on that payload because one builder serves both endpoints. State it in this
    criterion and in a comment at the builder, with the reason: an unrendered field is exactly
    what a later reader "optimises" away, and dropping it would give the two screens two shapes
    for one contract and let them disagree about staleness, which is the confidence-undermining
    bug this task exists to prevent. The comment names criterion 20's identical-object test as
    what goes red if somebody trims it.
25. `_member_view` is **not** changed. No member `created_at` reaches the wire. The server computes
    who is quiet and sends ids; task 9's decision that a member view is id and display name only
    stands, and a screenshot of the roster is still not an account list.

### The screens

26. `app/index.html` gains, inside the balances section and immediately after `id="balances-derived"`,
    exactly these three things, and inside the feed section exactly one. Every sentence below is
    fixed prose in markup so a Python test can pin it character for character, which is the rule
    stated at `app/index.html:301`; the only composed text is a number and a name.

    Balances:

    ```html
    <p class="balances-note" id="balances-stale" hidden>Nothing new has been recorded for
      <span id="balances-stale-days"></span> days. These figures may be missing recent
      spending.</p>
    <p class="balances-note" id="balances-never" hidden>Nothing has been recorded in this group
      yet, so there is nothing behind these figures.</p>
    <div id="balances-quiet-block" hidden>
      <p class="balances-note">No expense entered in the last
        <span id="balances-quiet-days"></span> days by:</p>
      <ul class="balances-list" id="balances-quiet"></ul>
    </div>
    ```

    Feed:

    ```html
    <p class="feed-stale" id="feed-stale" hidden>Nothing new has been recorded here for
      <span id="feed-stale-days"></span> days. The app only knows what people enter.</p>
    ```

    The quiet signal is a wrapper over a note and a list, carrying one `hidden` flag, for the
    reason task 14 gave at `app/index.html:263`: a bare intro over an empty list on an ordinary
    day is noise. The two age sentences are standalone `<p hidden>` elements, like
    `balances-drill-hint`, because each is self-contained and at most one is ever shown.

    Three existing document tests must pass unedited, and the placement above is chosen so they
    do. `test_the_two_things_task_fifteen_added_sit_in_the_stated_order`
    (`tests/test_web_shell.py:2158`) asserts a chain from `id="balances-derived"` through
    `id="balances-decision"` to "Suggested payments", and inserting between the first two leaves
    every link in that chain intact. `test_the_pending_block_is_the_only_thing_task_fourteen_added_to_the_document`
    and `test_the_two_additions_are_the_only_thing_task_fifteen_put_in_the_document` assert only
    that tasks 14's and 15's own strings do not appear **outside** the balances section, so
    additions inside it do not disturb either. If any of the three goes red, the new markup is in
    the wrong place and the fix is to move it, never to edit the test.
27. `test_no_feed_copy_claims_the_ledger_is_current` (`tests/test_feed_screen.py:307`) **passes
    unedited**. The feed sentence in criterion 26 was written against its seven banned substrings
    and contains none of them: it says "for N days", not "days ago", and never "today",
    "yesterday", "just now", "up to date", "everything is here" or "last updated". This is a
    criterion and not an accident, because that test's own comment says task 16 owns this
    vocabulary and it would be easy to narrow the test instead of choosing words. If the copy is
    reworded during review and a banned substring becomes unavoidable, the test may be narrowed to
    keep the three currency claims and drop the relative-date bans, in one commit, with a comment
    naming this task and the wording that forced it, and the change recorded in Findings. Silently
    deleting a ban is a FAIL.
28. `app/app.js` renders them from `state` alone:
    * `feedState` (`app/app.js:203`) hides `feed-stale` in every state but `list`, so the fourth
      element joins the existing "exactly one state is up" structure rather than becoming a fifth
      thing a caller has to remember. An empty ledger reaches `feedState('empty')` and shows no age
      line, which is decision 4 on the feed.
    * `balancesClear` (`app/app.js:1649`) hides `balances-stale`, `balances-never` and
      `balances-quiet-block` and empties the quiet list, so nothing from a previous visit sits
      beside a failure message and the `net.length === 0` early return at `app/app.js:2686`
      leaves all three hidden with no extra code.
    * At most one of `balances-stale` and `balances-never` is ever not hidden, enforced by one
      toggler in the shape of `balancesMessage` (`app/app.js:1633`) rather than by three call
      sites remembering.
    * Names in the quiet list come from `balancesName` (`app/app.js:1707`), so an id the roster
      does not know renders as `Unknown member` and the acting member's own row carries
      ` (you)`. No member id is ever rendered as visible text, which is the rule this screen
      already holds everywhere.
    * The quiet list is rendered in the order the array arrived, with nothing sorted, reversed or
      filtered, matching `balancesFill` (`app/app.js:2662`).
29. The client does **no** arithmetic and no comparison on these fields. It switches on `state`,
    prints `days_since_last_expense` in the `stale` arm and `quiet_after_days` in the quiet arm,
    and compares neither against the other. A `state` it does not recognise draws nothing.
    Criteria 38c and 38h are the checks that prove this rather than asserting it: a source-reading
    lint cannot tell a comparison that is absent from one that is merely spelled differently, and
    a payload whose two fields disagree can.
30. A payload carrying **no** `staleness` key draws neither signal, on both screens, and is not an
    error. `feedValidPayload` (`app/app.js:251`) is **not** given a `staleness` requirement: a
    missing signal must not turn a whole feed into "The feed did not arrive", which would be
    reporting an absence as a breakage, which is #44 one more time. Criterion 38g proves it.
31. `app/styles.css` gains a rule for `.feed-stale` and any new class, and no new rule introduces
    a `:empty` selector inside the balances section or a `white-space: nowrap` anywhere, so
    `test_the_action_region_never_takes_space_while_it_is_empty` and
    `test_the_figure_is_still_the_only_thing_that_refuses_to_wrap` both pass unedited. The balances
    sentences reuse the existing `.balances-note` class and need no new rule.
32. No timer is introduced. `test_the_feed_never_polls_or_refreshes_itself`
    (`tests/test_feed_screen.py:418`) bans `setInterval`, `setTimeout`, `visibilitychange` and
    `requestAnimationFrame` from `app/app.js` and passes unedited. The figure is as of the last
    read and does not tick while a screen sits open, which is consistent with every other figure on
    both screens and is a further argument for elapsed days over a live countdown.
33. No digit appears in any new sentence in `app/index.html`, and a test asserts it over the new
    elements' text. Every number on screen comes from the payload, so the threshold cannot be
    stated in two places that disagree.
34. `test_every_element_the_router_reaches_for_exists_in_the_document`
    (`tests/test_web_shell.py:544`) covers the new ids for free: every `getElementById` in
    `app/app.js` must match an id in the document. A mistyped new id goes red rather than becoming
    a blank line in a browser nobody opened.

### That the checks can fail

35. **Every check this task adds is demonstrated capable of failing, and the demonstration is
    recorded.** A check that has not been made to go red is not evidence. This is a criterion, not
    a suggestion. The vehicle is `plans/mutations/16-incompleteness-signal.md`, in the format
    `plans/mutations/README.md` states, and every Python mutation run sets
    `PYTHONDONTWRITEBYTECODE=1` per `.claude/rules/testing.md` rule (f).
36. **One committed mutant, `MUTANT_H`**, added to `tests/test_shell_behaviour.py` beside
    `MUTANT_A` through `MUTANT_G`, and it is the #44 defect in this feature's own shape: the
    `never` arm is removed so a ledger with no expense renders the age sentence, printing the word
    `null` where a number belongs. It qualifies under all three of
    `plans/mutations/README.md`'s tests: it is the only evidence the `never` scenario bites, it
    survives against the code as it was before that scenario existed, and it leaves a working app
    with one sentence wrong rather than a smoking crater. A named control survives it and is
    asserted to, `UNRELATED` being the one the repo already keeps for this, and the PR states the
    run cost the new mutant adds. At most one committed mutant, per that file's cap.
37. Recorded and not committed, each an anchor and a replacement with the node ids it kills:
    a. the clamp at zero deleted, so a future timestamp yields a negative day count;
    b. `>=` weakened to `>` at the threshold, killed by the exact-boundary test in criterion 18;
    c. the member-age condition deleted, so a member who joined yesterday is named as quiet;
    d. `created_by` swapped for `payer_id` in the quiet computation, killed by criterion 16's test;
    e. `ordering_key` replaced by "the last element of the list", killed by a ledger whose newest
       expense is not last.
38. The harness scenarios below are added to `tests/shell_harness.mjs` and appended to the
    `SCENARIOS` literal in `tests/test_shell_behaviour.py`, **keeping every existing entry verbatim
    and in its existing order**, so `test_the_harness_reports_exactly_the_declared_scenarios` stays
    a pin on the whole list rather than a count anybody has to maintain:
    a. a stale feed shows the age sentence with the exact composed text;
    b. a fresh feed shows nothing, with the age element hidden;
    c. **a payload whose `state` is `fresh` while `days_since_last_expense` is 99 shows nothing.**
       This is the positive control for criterion 29: a payload whose two fields disagree proves
       which one the client obeys, and no amount of reading the source proves it;
    d. a balances read with `state: "never"` shows the no-ledger sentence and leaves the age
       sentence hidden;
    e. a stale balances read names the quiet members, in payload order, with ` (you)` on the acting
       member;
    f. a quiet id absent from the roster renders `Unknown member`, and the raw id appears nowhere
       in the document text;
    g. a payload with no `staleness` key at all draws neither signal and still draws the figures;
    h. a `state` the client does not recognise draws neither signal;
    i. a group with exactly one quiet member reads grammatically, which is the case the wording in
       criterion 26 was chosen for.
39. The harness fixtures `EMPTY_FEED` and `EMPTY_BALANCES` (`tests/shell_harness.mjs:1160`) gain
    the shape the server now sends, and a cross-language pin stops them drifting from it, in the
    shape of `test_every_error_code_the_harness_names_appears_in_web_py`
    (`tests/test_shell_behaviour.py:805`): the four `staleness` key names and the three `state`
    values the harness uses are asserted present in `src/splitwise_lite/web.py` as text. Rule (d)
    of `.claude/rules/testing.md` is exactly this defect, and a stubbed payload that is also the
    expected value cannot detect its own drift.
40. `tests/test_staleness.py` is the one new test module. Because both parametrised checks in
    `tests/test_suite_integrity.py` are driven by `TESTS.rglob("*.py")`, adding it adds **two**
    cases beyond its own tests, one to each. QA's arithmetic in criterion 43 accounts for that
    explicitly, because reconciling a count is the only thing that ever caught #67.

### The documents

41. The `"The incompleteness signal"` key moves from `NOT_YET` to `WORKS_TODAY` in
    `tests/test_web_shell.py`, keeping the key string verbatim so the move is a move and not a
    rename, and gains two present-substring pairs that are real machinery rather than prose:
    `("index.html", 'id="balances-quiet-block"')` and `("app.js", "staleness")`. A comment above it
    records what actually happened, in the shape the entries for tasks 13, 14 and 15 already carry:
    the entry was **SILENCE**, nothing in the suite fired, the bullets were moved by hand, and the
    reason it predicted a client-side computation was wrong because `app/app.js` may not read the
    clock.
42. `CLAUDE.md` and `README.md` each move their `**The incompleteness signal**` bullet from "What
    does not exist yet" to "What works today", in each document's own voice, and each says what the
    signal is and what it is not: it reports the age of the newest expense and who has entered
    nothing recently, in whole elapsed days, computed on every read; it moves no figure; it is not
    a notification, and nobody is told anything, which is consistent with the existing
    "nobody is told" clause. `test_both_documents_agree_on_what_works_today` and
    `test_both_documents_agree_on_what_does_not_exist_yet` pass with no other edit to either
    document. The comment at `app/index.html:240` saying "Task 16 owns the real signal" and the one
    at `app/app.js:2717` saying task 16 owns the incompleteness signal are both updated to point at
    what now exists instead of at a future task; the instruction at `app/app.js:2721` not to
    special-case the empty transfer list **stands**, because this task answers that ambiguity in a
    separate sentence rather than by changing the `none` message.
43. QA records, and the PR states: the passed count on the branch, the count on `master` it
    reconciles against, and the arithmetic between them, including the two extra parametrised cases
    from criterion 40. `0 failed, 0 skipped, 0 xfailed`.

---

## The browser gap

**Nothing in this project has ever been verified in a browser.** `tests/shell_harness.mjs` runs
the real `app/index.html`, `app/app.js` and `app/api.js` under Node's `vm` against a stubbed DOM
and a stubbed `fetch`. Its own header, at `tests/shell_harness.mjs:29`, lists what stays
browser-only, and one line of that list is decisive for this task:

> Layout: viewport, safe area insets, hit areas, font sizes, iOS auto-zoom.

So the two halves of this feature are not equally verifiable, and the split is worth being blunt
about, because a staleness banner is a layout-bearing thing on a 320px screen:

**What the suite really judges.** Which elements are hidden, the exact text they hold, the order
they sit in the document, that names resolve through `balancesName`, that a raw id never reaches
visible text, that the client obeys `state` and not the count, that a missing key draws nothing,
and every domain figure to the microsecond. That is the whole of criteria 1 to 43 and it is a lot.

**What no check here can judge, and what therefore has no criterion above.** Whether the signal is
*obvious*, which is the actual word the spec uses. Whether three stacked notes above "Net
positions" push the first figure below the fold at 320px. Whether the age sentence reads as a
warning or as more small print. Whether a screen reader announces the new copy in a useful order
now that three more elements sit above the existing live region. Whether the quiet list is
legible at five names.

**These are recorded as NOT RUN.** No verdict in this task depends on any of them. **Recording an
unrun browser check as "pass" is a FAIL**, and so is writing a criterion whose only honest verdict
is "looked at the code and it seemed fine".

The mechanism for closing this gap already exists and is not reinvented here: **issue #80** is
open to do one dated manual sweep. This task adds its five questions above to that issue and does
not open a second mechanism, does not add a hand checklist of its own, and does not block on #80.

---

## Out of scope

* **Notifications, reminders, nagging, badges and email.** The spec cuts them explicitly, and
  `CLAUDE.md` already says "nobody is told: people find claims and answers by opening the app".
  This signal is read when somebody opens a screen and at no other time.
* **A third screen.** The add screen gains nothing.
  `test_no_copy_on_this_screen_says_anything_about_balances` (`tests/test_add_screen.py:472`)
  stays passing and unedited.
* **Any change to a figure, an order or a state machine.** No balance moves, no transfer changes,
  nothing is stored, no settlement state is touched, and the `none` message logic at
  `app/app.js:2722` is left exactly as it is. This task adds sentences beside the figures and
  changes no figure.
* **Expense correction.** Task 17, issue unrelated. A stale expense is not edited or voided here.
* **Highlighting, sorting or badging an old expense row, an old claim or a quiet member anywhere
  else.** "Pending for 6 days" was declared out of scope by tasks 14 and 15 and stays out. No row
  in any list changes.
* **A per-member "last logged" date, a coverage percentage, a chart or any analytics.** The spec
  cuts categories, budgets and analytics. Two sentences and a list of names is the whole feature.
* **Making the threshold configurable**, by flag, environment variable, query parameter, group
  column or account setting. Decision 2.
* **A timezone anywhere.** No zone column, no zone setting, no calendar arithmetic, no locale
  formatting. Decision 3.
* **Reading the client clock**, in any form, for any purpose.
* **Any new route, any change to `_API_ROUTES`, any change to `app/api.js`, and any new key on
  `window.SplitwiseApi`.**
* **A new dependency, in either language.** `pyproject.toml` and `uv.lock` are byte-identical to
  `master`.
* **Any change to how the service worker behaves.** `SHELL` keeps the same nine entries and the
  worker's logic is untouched, which is what leaves `VERSION` out of it; the one line that moves
  and the reason are in "Constraints".
* **Fixing issue #44.** This task must not repeat #44's shape, which is criterion-bearing, but it
  does not fix the empty-roster message that #44 reports. Different screen, different task.
* **The 94 unanchored `pytest.raises(match=)` pins of issue #70.** The pins this task adds are
  anchored; the existing ones are not this task's to fix.
* **Re-verifying or reorganising `MUTANT_A` through `MUTANT_G`.** One mutant is added and the
  existing ones are left alone.

## Would be a separate issue

Written down here rather than smuggled into a criterion. None of these is built.

* **A "you have logged nothing" line on the add screen**, aimed at the person holding the phone
  rather than at the group. Plausibly the highest-value version of this whole feature, since it is
  the only one addressed to somebody who can act immediately, and it is a third screen and a
  different audience.
* **Ranking or counting the quiet members** ("Ali has entered nothing for 24 days"). Needs a
  per-member age, which needs a per-member last-expense lookup, and turns a caveat into a
  scoreboard. The social cost of a scoreboard in a shared flat is a product question nobody has
  asked yet.
* **Distinguishing "never spent anything" from "spent and settled every penny"** in the `none`
  message itself, which `app/app.js:2717` explicitly asks a future task not to do inline. This task
  answers it in a separate sentence; folding the answer into that message is a separate edit with a
  separate argument.
* **A staleness signal on the transfer drill-down**, so a debt whose newest source expense is
  months old says so.
* **Using settlement activity as a liveness signal**, deliberately excluded by decision 3, which
  would be a different signal answering a different question.
* **Dated membership intervals**, so "has been in the group for the whole window" stops being a
  proxy. This is spec open question 1 and is expensive; decision 4 records the proxy it uses
  instead.

---

## Constraints

* **Files edited: exactly these.** Nothing else, in either direction.
  * `src/splitwise_lite/staleness.py` (new)
  * `src/splitwise_lite/__init__.py` (the re-export and its `__all__`)
  * `src/splitwise_lite/web.py`
  * `app/index.html`, `app/app.js`, `app/styles.css`
  * `app/sw.js` (one line, `SHELL_DIGEST`)
  * `tests/test_staleness.py` (new)
  * `tests/test_web_api.py`, `tests/test_web_shell.py`, `tests/test_feed_screen.py`,
    `tests/test_shell_behaviour.py`, `tests/shell_harness.mjs`
  * `CLAUDE.md`, `README.md`
  * `plans/mutations/16-incompleteness-signal.md` (new)
  * this spec, if it needs correcting
* **`SHELL_DIGEST` in `app/sw.js` is set to the twelve hex characters
  `test_the_recorded_digest_matches_the_files_it_covers` prints when it fails, pasted verbatim.
  `VERSION` stays `'v4'` and `SHELL` is unchanged.** Three of the nine precached files change
  (`index.html`, `app.js`, `styles.css`), so that test will fail once and its message is the whole
  fix. Never invent the digest, and never bump `VERSION` to clear it.
* **Money is integer cents and no amount appears in this feature at all.** If one ever does,
  `money.format_amount` is the only display edge. Nothing here parses, adds, compares or formats a
  cent value, and no new number reaches the front end except a whole count of days.
* **The domain layer imports with Flask absent**, and only `web.py` may import Flask. The new
  module imports from `events` and from nothing else in the package.
* **Every `pytest.raises(match=...)` this task adds is anchored with `^`.** `match=` is an
  `re.search`, so an unanchored pattern is satisfied by a superstring and pins nothing. This has
  bitten the repo twice, `.claude/rules/testing.md` rule (a) carries the scar, and
  `tests/test_suite_integrity.py` refuses an unanchored pin without a `# unanchored: <why>` reason.
  A raw string, with any regex metacharacter in the message escaped.
* **A test whose name mentions staleness has a real second condition in its body**, per
  `.claude/rules/testing.md` rule (c). The boundary tests in criterion 18 are the ones this is
  aimed at: a test named for a boundary that only ever runs one side of it could not fail for the
  reason its name gives.
* **No test binds a socket, spawns a shell, or writes anywhere but `tmp_path`.**
* Tests run with `uv run python -m pytest`. Plain `uv run pytest` fails on this machine with an
  access-denied spawn error. `node` 20 or later is a test-time requirement and the JavaScript half
  still runs.
* **Do not run the full suite in one go while iterating.** It has grown past the ten-minute agent
  watchdog under contention. Chunk by module, get counts from `--collect-only -q`, and let CI be
  the full-suite oracle. Both CI legs, `ubuntu-latest` and `windows-latest`, must be green, and a
  PR whose base has moved is brought up to date and re-run, because a stale shell digest surfaces
  at the merge commit.
* **Python 3.12.** Type annotations on every new function, a docstring on every new name stating
  the invariant it enforces, and a one-line comment at each decision recorded in criteria 8, 10,
  20, 24, 27 and 30, so the next person does not undo one by tidying.
* **Two numbers in this document that I could not measure, flagged rather than asserted.** Bash was
  disabled for the session this spec was written in, so no `pytest` or `git` command was run.
  Everything numeric above was read out of the files with ripgrep and file reads, and every count
  is stated as a property wherever a property would do. Two consequences:
  > **Measured 2026-09-07, at the start of implementation, on `task-17` at `c685cee`, which is
  > `master`.** Bash was available for the build, so the two flagged numbers below were checked
  > rather than trusted, and the baseline the PR reconciles against was taken before a line was
  > edited. `uv run python -m pytest --collect-only -q` collects **2498** over the whole suite,
  > and per module: `tests/test_web_api.py` 475, `tests/test_web_shell.py` 144,
  > `tests/test_feed_screen.py` 22, `tests/test_shell_behaviour.py` 172,
  > `tests/test_suite_integrity.py` 52. `API_SURFACE` holds **sixteen**, confirming the figure
  > below and refuting both the in-file comment's "fifteen" and the brief's "fourteen": the
  > parse `test_the_api_client_offers_exactly_the_named_calls` runs over `app/api.js` returns
  > sixteen keys and they equal the literal exactly.

  * **`API_SURFACE` holds sixteen names, not fourteen.** Counted from the literal at
    `tests/test_web_shell.py:1147` to `:1167`, one short quoted string per line, none wrapped:
    fourteen at lines 1148 to 1161, plus `addSettlement` and `decideSettlement`. The in-file
    comment at `:1264` says "it holds fifteen" and is itself stale by one, because it was written
    before task 15 landed. Criterion 22 does not touch the literal, so the true figure only
    matters if somebody tries to reconcile it; the engineer should confirm with
    `uv run python -m pytest tests/test_web_shell.py -k api_client` before trusting any of the
    three numbers, including mine.
  * **The suite total is not stated anywhere in this document.** Criterion 43 asks QA to measure it
    and show the arithmetic, which is the only form this repo trusts.

## Size

**Medium, and the domain half is small.** Measured with ripgrep line counts of the files involved,
not estimated by eye:

* `src/splitwise_lite/staleness.py` is new and is the smallest interesting file in `src/`: one
  enum, one frozen dataclass with two invariants, one function, two guards. Well under a hundred
  lines of code, and probably as much docstring again given criterion 9.
* `src/splitwise_lite/web.py` is 2,597 lines and gains one helper, one wire dict and three or four
  lines in each of two endpoints.
* `app/app.js` is 2,782 lines and gains one toggler, one quiet-list renderer, and one line each in
  `feedState`, `feedRender`, `balancesClear` and `balancesRender`.
* `app/index.html` is 332 lines and gains the four elements in criterion 26.
* `tests/test_staleness.py` is new and is where most of the writing is: criteria 13 to 19 are
  roughly two dozen small, exact, pure-function tests.
* `tests/shell_harness.mjs` is 8,763 lines and gains nine scenarios plus two fixture edits.

**The expensive part is not the code.** It is criteria 35 to 39: one committed mutant, five
recorded mutations each with a run behind it, and nine harness scenarios. Budget for that rather
than for the implementation, and do not shorten it by reading the code instead of breaking it.
`plans/tasks/60-65-67-checks-that-could-not-fail.md` records that its own size estimate was out by
about three times, and that the excess was spec-driven rather than sprawl, so treat the paragraph
above as a floor.

Base the estimate on your own count before starting:
`uv run python -m pytest --collect-only -q tests/test_web_api.py tests/test_web_shell.py tests/test_feed_screen.py tests/test_shell_behaviour.py`

**If this task grows** a new route, a client-side clock read, a timezone, a configurable threshold,
a notification, a third screen, a per-member age, a change to any figure, a new dependency, or an
edit to `app/api.js`, it has gone wrong.

## Findings

Filled in before the PR was opened, per criterion 43 and the note on criterion 27. Every number
here was produced by a command on this branch, not read out of a file.

### The count, and the arithmetic

**Restated against the current base.** The first measurement was taken against `c685cee`, and
master has since moved to `bea0da7` through PR #76 and PR #81. Master was merged into this
branch rather than rebased onto it, so published SHAs stay reachable, and
`git merge-base --is-ancestor origin/master HEAD` now succeeds. Master's own count was measured
in a throwaway detached worktree rather than taken on trust or read out of a sibling.

`uv run python -m pytest --collect-only -q`:

| | master (`bea0da7`) | branch | delta |
|---|---|---|---|
| whole suite | 2572 | 2668 | **+96** |
| `tests/test_staleness.py` | absent | 59 | +59 |
| `tests/test_web_api.py` | 478 | 493 | +15 |
| `tests/test_shell_behaviour.py` | 173 | 186 | +13 |
| `tests/test_web_shell.py` | 146 | 153 | +7 |
| `tests/test_suite_integrity.py` | 56 | 58 | +2 |
| `tests/test_feed_screen.py` | 22 | 22 | 0 |
| `tests/test_error_messages.py` | 64 | 64 | 0 |

59 + 15 + 13 + 7 + 2 = **96**, and 2572 + 96 = **2668**. The +96 is one more than the +95
measured before the merge, and the extra one is the positive control added with the repair in
finding 2 below, not anything the merge brought in.

The two in `tests/test_suite_integrity.py` are criterion 40's: both of its checks are driven by
`TESTS.rglob("*.py")`, so a new test module adds one case to each with no list to edit. That
mechanism runs in the other direction too, and it was worth checking after the merge: PR #76
tightened those rules and `tests/test_staleness.py` had never met them. It meets them unedited.
The 13 in `tests/test_shell_behaviour.py` are the 9 harness scenarios, `MUTANT_H`'s test and
the 3 cross-language pins of criterion 39.

**The scenario list is a union, not an overwrite.** `SCENARIOS` held 149 rows on `c685cee`, 150
on `bea0da7` after PR #81 added one, and **159** on the merge: 150 + 9.
`test_the_harness_reports_exactly_the_declared_scenarios` asserts exact ordered equality against
what the harness reports, and it passes, which is what makes that a checked claim rather than a
count somebody eyeballed.

**Run in six chunks, never the whole suite in one go**, because it has grown past the
ten-minute agent watchdog under contention:

* `money, events, split, balances, simplify, smoke`: 733 passed
* `store, accounts, groups, setup_group_cli, dev_server, end_to_end`: 873 passed
* `web_api`: 493 passed
* `web_shell, feed_screen, add_screen, suite_integrity, staleness`: 319 passed
* `shell_behaviour`: 186 passed
* `error_messages`: 64 passed

733 + 873 + 493 + 319 + 186 + 64 = **2668 passed, 0 failed, 0 skipped, 0 xfailed**, which is
the collected total exactly. `tests/test_error_messages.py` arrived with the merge and is a
sixth chunk; the first sum of the chunks came to 2604 against a collected 2668, and that
64-test gap is what named it. The arithmetic is the check, which is the whole reason for doing
it.

**The merge produced one conflict, in `app/sw.js`, and it was the expected one.** Both sides had
moved `SHELL_DIGEST`, because both changed files under `app/`. Neither side's value is right for
the merged tree, so neither was kept: the resolution is the twelve characters
`test_the_recorded_digest_matches_the_files_it_covers` printed for the merged content,
`5ad02b8ea4e8`, pasted verbatim. `VERSION` stays `v4`. This is exactly the case CLAUDE.md warns
about when it says a stale shell digest surfaces at the merge commit.

### What the mutation runs found that I had not predicted

Recorded in full in `plans/mutations/16-incompleteness-signal.md`, each with a whole-module,
unfiltered `N failed, M passed`. Three are worth naming here because they are not what a
prediction would have said:

1. **The clamp mutation is killed by the result type, not by the assertion.** Deleting the clamp
   met `TypeError: Staleness days_since_last_expense must be zero or positive, got -1` from
   `Staleness.__post_init__` before the test's own assertion ran. The clamp is guarded twice and
   the mutation removes one guard. Still `killed`: the deleted clamp is the cause and the test
   that names it is the test that went red.
2. **`test_the_newest_expense_is_chosen_with_the_ordering_key_events_py_defines` survived the
   mutation that stops `ordering_key` being used, so it was a check that could not fail. It has
   been repaired rather than merely reported.** The identity assertion held because the import
   still resolves; the module simply stopped calling what it imported. The cause was a copying
   error worth naming: the precedent in `tests/test_balances.py` carries **two** assertions, and
   only the second was copied. The first, the runtime-name check, is the half that bites.

   The test now asserts, in the order they bite: the behaviour, over a list whose newest expense
   is neither first nor last and over every rotation of it; the name being reached at run time,
   read off the module's own syntax tree; and then the identity criterion 11 asks for.
   Re-measured on the same mutation: **`1 failed, 57 passed`** of 58 before, **`2 failed, 57
   passed`** of 59 after, with the repaired test among the failures.

   The structural half was measured separately against the mutant rather than assumed, because a
   repair carrying the bug's own defect has happened in this repo before: under the mutation
   `runtime_names(...)` reports `ordering_key` reached at run time **False**, while a plain text
   search for the same name in the same file reports **True**. So the syntax-tree check kills the
   mutant and the text search a hastier repair would have reached for does not. A positive
   control for that check was added beside it, and it is the 59th test in the module.
3. **Four of the five mutations survive all 490 tests in `tests/test_web_api.py`.** Only the
   member-age one is visible through a real request. That is not a gap in the endpoint tests: a
   future timestamp is unreachable through an endpoint that stamps `created_at` from `_now()`,
   and no endpoint test sits on the exact boundary. It does mean the domain module is the sole
   guard on four of the five, which is stated rather than left to be discovered.

### Criterion 27: the copy was not reworded and no ban was narrowed

`test_no_feed_copy_claims_the_ledger_is_current` passes **unedited**. The feed sentence contains
none of its seven banned substrings: it says "for 9 days", never "days ago", and none of
"today", "yesterday", "just now", "up to date", "everything is here" or "last updated".

### Deviations from this document, each with its reason

1. **`tests/test_end_to_end.py` was edited and is not in the Constraints file list.** It had to
   be: step 0 pins the balances payload's top-level key set exactly, so the new key turned it
   red, which is the interlock working. The edit adds `"staleness"` to the set and one assertion
   that a group which has recorded nothing reports `never` with no number and nobody named, so
   the walk covers the new signal rather than merely tolerating it.
2. **`app/app.js` orders the toggler's arms stale-then-never.** The natural order is
   never-then-stale and that is how it was first written. It was reordered so `MUTANT_H` has a
   **one-line** anchor: the three-line version matched zero times on this working tree, which is
   CRLF, and `MUTANT_F` already carries that scar. Behaviour is identical either way.
3. **The endpoint tests replace `web._now` rather than choosing event timestamps relative to the
   real clock**, which is what decision 1's rationale suggested. Both styles are already in that
   file. Replacing the seam was chosen because the roster's ages cannot be controlled the other
   way: `seed_group` stamps every member row with `at()`, a fixed instant, so a quiet-member
   assertion written against the real clock would pass today and fail in a fortnight. Replacing
   the seam is not a second clock read, and `test_the_clock_is_read_once_and_only_in_one_place`
   passes unedited.
4. **`staleness.py` names `datetime` at runtime, in exactly one place.** Criterion 8's
   parenthetical predicted it would need no runtime `datetime` name at all. It needs one:
   `_require_instant`'s `isinstance` guard, which is what criterion 7 asks for, because refusing
   a naive value the way `events._require_utc` does means naming the class. Everything else is
   annotation-only, no `timedelta` is constructed, and the arithmetic names no class because
   `(later - earlier).days` does not. The rule the criterion states is unaffected: this module's
   check forbids clock **reads**, and an `isinstance` is not one. The comment in the file says
   that rather than repeating the prediction.

### What was verified, and what was not

**Verified by the suite**: every domain figure to the microsecond, both wire payloads, which
elements are hidden, the exact text they hold, the order they sit in the document, that names
resolve through `balancesName`, that no member id reaches visible text, that the client obeys
`state` and not the count, and that a missing key draws nothing.

**NOT RUN, and no verdict here depends on any of it**: whether the signal is *obvious*, which is
the word the spec uses; whether three stacked notes push the first figure below the fold at
320px; whether the age sentence reads as a warning or as more small print; whether a screen
reader announces the new copy in a useful order now that three more elements sit above the
existing live region; whether the quiet list is legible at five names. **Nothing in this project
has ever been verified in a browser.** These five were added to issue #80, the existing
mechanism for one dated manual sweep. No second mechanism was opened and nothing here blocks on
it.
