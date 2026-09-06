# Task 43: a screen that waits for a session, and a draft that survives signing back in

Closes GitHub issue #43. Two defects, both pre-existing, both spread across all three
screens, and both caused by the same thing: each screen decides on its own when it is
allowed to act, and none of them asks whether anybody is signed in.

Depends on work that already exists on this branch and is assumed present: task 9a (the
HTTP API), task 9b (the JavaScript harness), task 32 (`kind`, `say`, the three handlers
and the four notice paragraphs), task 10 (the add screen), task 11 (the feed) and task 12
(the balances screen).

## What is wrong today

### Defect 1: a screen loads while nobody is signed in

With the sign-in gate up, moving the hash to a screen's route runs that screen's entry
function anyway. Each entry function guards on two things, and neither of them is a
session:

* `loadFeed()` guards on `!api`, on the hash being `#/feed` and on `feedBusy`
  (`app/app.js:541`), then issues `GET /api/expenses` and `GET /api/members`
  (`app/app.js:556`).
* `balancesEntered()` has the same guard shape (`app/app.js:1612`) and then reads the
  roster and the figures.
* `addEntered()` inherits the pattern (`app/app.js:1095`), clears the form, focuses
  `#add-amount` and reads the roster.

The consequences, in the order they hurt:

1. **A request goes out that is certain to be refused.** Every endpoint except signup and
   the three session endpoints needs both a session and a member row, and answers 401 or
   403 `member_not_linked` otherwise; `src/splitwise_lite/web.py` says so in its module
   docstring. So on every route change made by anybody who is signed out, this app asks
   the server for the ledger and is told no.
2. **Focus lands inside something the person cannot see.** `render()` focuses the new
   screen's heading, and the add screen then moves focus on to `#add-amount`. Both of
   those elements sit inside `.content`, which `show()` has hidden behind the gate. For a
   screen reader or a keyboard user that is not a cosmetic problem: focus leaves the
   password field and lands in hidden content, with nothing announcing why.
3. **The refusal is classified and can raise a curtain over a curtain.** The 401 reaches
   `onUnauthenticated`, which calls `showGate(error.say)`. `say` is `''` for
   `not_authenticated`, so `#gate-error` is blanked and `#gate-title` is refocused. A
   person who has just been told "Those details did not match an account." and who then
   uses Back loses that sentence to a request they never asked for.

The third copy of the guard is how one defect became three. The fix is one helper, not
three corrections.

### Defect 2: signing back in wipes a draft the app promised to keep

A 401 on save correctly preserves everything typed: `addRefused()` sees a `kind` other
than `refused`, returns early, and touches nothing. The gate goes up carrying the
server's sentence. So far the standing promise on the offline curtain, "Nothing you have
recorded is lost", is true.

Then the person does the one thing the screen is telling them to do. They sign in.
`refresh()` calls `showApp()`, `showApp()` calls `addEntered()`, and `addEntered()`
clears `#add-amount`, `#add-description`, the split mode, the confirmation and the error
region, because it cannot tell "the person navigated here" from "the curtain this screen
was already behind has come down". The form is empty and the expense is gone.

Clearing on every `showApp()` is what makes the promise false.

## Goal

No screen reads, and no focus moves, while a curtain is over the app frame: the three
screens act only when this client holds a session that carries a member and the ledger is
what the person is actually looking at. That question is asked in one place, of session
state, never of a status. And a screen the person is returned to after an interrupted
save is the screen they left: what they typed is still there, because clearing belongs to
navigating and to signing out, and not to a curtain coming down.

## The decisions this task makes

### 1. One helper, six call sites

`app/app.js` gains exactly one function, `ledgerIsUp()`, declared in the file's shared
preamble beside `var api = null;`, above the feed block. It is the only place any of its
conditions is written down. Function declarations hoist within the file's one IIFE, so
every block can call it wherever it sits.

The preamble is chosen deliberately: it is the smallest region of this file, and the
three screen blocks below it are being edited by sibling branches. A helper added to a
screen block would be a helper the other two blocks reach into.

### 2. What "signed in" means to a screen

`ledgerIsUp()` is true when all three of these hold, and false otherwise:

| Condition | The case it covers |
|---|---|
| `api` has been assigned | `app.js` loads `api.js` asynchronously, and `api.js` may fail to load altogether. A hashchange can arrive before either has happened. |
| `api.cachedSession()` returns a view whose `member` is truthy | Nobody is signed in (the cache is null), or somebody is signed in with no member row, which the server refuses with 403 `member_not_linked` on every one of these endpoints. |
| `show()` last put the app frame up | A curtain is over the frame. This is the only condition that catches an `offline`, `unavailable` or `not-linked` curtain, because task 32 decided those three leave the cached view alone, on purpose, and that decision stands. |

Two rules survive intact. **`app/api.js` remains the only place that decides what a
status means**, and this helper reads no `status`, no `code` and not even a `kind`: it
asks the client what session it holds, which is a question `cachedSession()` already
answers, and asks this file what it last drew, which is a decision this file already
made. And **`app/api.js` is not edited at all**, which is the cheapest possible proof
that the #32/#41 contract is untouched.

The third condition needs a place to live. `show()` already takes exactly one of `'app'`,
`'gate'` and `'notice'`, so it records what it applied in one module-scope variable and is
the only writer of it. Deriving it back out of `.content.hidden` would work today, but a
decision this file makes should be held as a decision rather than re-read out of the
markup it produced.

The three conditions are complementary, and each has a case no other covers. Keep all
three even though the third alone would pass the harness: it passes only because
`show('app')` happens to be reachable from one place.

### 3. Focus does not move while a curtain is up, on any route

`render()`'s heading focus is guarded by the same helper. Everything else `render()` does
stays exactly as it is: the screens' `hidden` flags, `aria-current` and `document.title`
still track the hash, so signing in still reveals the screen the person was on.

The add screen's own focus move is not separately guarded, because `addEntered()` and
`addResumed()` do not run at all when the helper says no.

### 4. Clearing belongs to navigating and to signing out

`showApp()` stops calling `addEntered()` and calls `addResumed()` instead. The add block
splits into four small functions, all prefixed, per that block's convention:

| Function | What it does | Called from |
|---|---|---|
| `addCleared()` | Empties the amount and the description, returns the mode to Equally, hides the confirmation, hides the error region | `addEntered()`, and the sign out button's success path |
| `addOpened()` | Shows the currency line, focuses `#add-amount`, calls `addLoadRoster()` | `addEntered()`, `addResumed()` |
| `addEntered()` | Guard, then `addCleared()`, then `addOpened()`. The `hashchange` listener | `hashchange` only |
| `addResumed()` | Guard, then `addOpened()` | `showApp()` only |

So a fresh entry is a hashchange onto `#/add`, and it clears, exactly as today. A
resume is the curtain coming down on a screen the person never left, and it clears
nothing. The hash never moved, and `show()`'s own comment already says signing in returns
the person to the screen they were on.

**Signing out clears.** A successful `DELETE /api/session` is the strongest signal there
is that the next person at this phone is not the previous one, and a flat shares phones.
Without this, Sam types an expense, signs out, and Ali signs in to find Sam's amount and
description sitting in the form with Ali named as the payer. So the sign out button's
success path calls `addCleared()`, whatever route is current. A sign out the server
refuses clears nothing: the visit did not end.

The feed and the balances screens hold nothing typed, so entry and resume are the same
act for them. Neither is renamed and neither gains a second entry point; `showApp()` goes
on calling `loadFeed()` and `balancesEntered()`, which re-read, which is right, because
their figures may be stale after the interruption.

### 5. What a resume does not preserve, and why

A resume re-reads the roster, and `addLoadRoster()` empties the payer picker and the
people rows before it sends. So these do not survive a resume, and that is what ships:

* the ticks in "Some of us" and the amounts typed into "Uneven amounts": the rows only
  exist while a roster is held, and they are rebuilt empty;
* a payer chosen by hand: the picker is rebuilt and the default is reapplied.

That is the deliberate trade. Rebuilding from a fresh read is what keeps the "(you)"
marker and the default payer true for whoever is signed in **now**, and on a shared
ledger the payer field decides who is owed money. A stale "(you)" is a worse failure than
a re-ticking.

The chosen split mode **is** preserved, and that is not an inconsistency. Resetting Exact
back to Equally would silently turn "these three uneven shares" into "split this evenly",
which is a wrong ledger entry one tap away. Leaving the mode on Exact with empty share
fields sends `{"mode":"exact","amounts":{}}`, which the server refuses, and a refusal is
a much better outcome than a silently different split.

The confirmation panel and any server refusal already on screen are also left alone by a
resume. Both describe things that really happened, to the draft that is still there.

## Acceptance criteria

Each of these is a yes or no a QA agent can get to. Behavioural criteria name the harness
scenario that expresses them; the scenarios themselves are specified in criteria 24 to 32.

### The helper

1. `app/app.js` declares exactly one function named `ledgerIsUp`, in the shared preamble
   above the feed block. `grep -c "function ledgerIsUp(" app/app.js` is 1.
2. `ledgerIsUp()` returns true only when all three conditions in decision 2 hold: `api`
   is assigned, `api.cachedSession()` returns an object whose `member` is truthy, and the
   state `show()` last applied is the app frame. Readable in the source.
3. `ledgerIsUp()` short-circuits on `api` before it reads `api.cachedSession()`, so it
   never throws while the client is unloaded. Scenario:
   `a_route_change_with_no_api_client_loaded_asks_for_nothing`.
4. `ledgerIsUp()` contains no comparison against a `status`, a `code` or a `kind`, and no
   HTTP status number. `grep -n "status\|\.code\|\.kind" app/app.js` returns nothing
   inside the helper.
5. `show()` records the state it applied in one module-scope variable, and is the only
   thing that assigns it. The variable is assigned in exactly one place in the file.
6. `!api` appears exactly once in `app/app.js`, inside `ledgerIsUp()`. Every former
   "has the client loaded" test is gone, including `balancesEntered()`'s separate
   `if (!api)` block.
7. `ledgerIsUp` appears exactly seven times in `app/app.js`: the declaration, and calls in
   `render()`, `loadFeed()`, `addEntered()`, `addResumed()`, `addLoadRoster()` and
   `balancesEntered()`. No other function asks the question, and no second spelling of it
   exists anywhere in `app/`.
8. `render()` uses it to guard the heading focus and nothing else: the screens' `hidden`
   flags, `aria-current` and `document.title` are still updated on every route change.
   Scenario: `a_route_change_behind_the_gate_asks_for_nothing_and_leaves_the_gate_alone`.

### Nothing loads and no focus moves behind a curtain

9. With the gate up, changing the hash to each of the three routes issues no request at
   all. Scenario: `a_route_change_behind_the_gate_asks_for_nothing_and_leaves_the_gate_alone`,
   whose whole declared request list is the boot session read and the refused sign-in.
10. With the gate up, three route changes leave focus on `#gate-title`. Same scenario.
11. With the gate up, a route change does not touch `#gate-error`: a message from a
    refused sign-in is still visible and still reads what the server sent. Same scenario.
12. With the gate up, a route change onto `#/add` leaves `#add-amount` exactly as it was.
    Same scenario, which sets the field directly before navigating so that the claim is
    falsifiable.
13. With the not-linked notice up, route changes issue no request and leave focus on
    `#notice-title`. Scenario:
    `a_route_change_behind_the_not_linked_notice_asks_for_nothing`.
14. With a curtain raised over a session that is still live and still linked, a 500 in
    this case, route changes issue no request, focus stays on `#notice-title`, and
    `#notice-problem` still reads the server's sentence character for character.
    Scenario: `a_route_change_under_a_curtain_a_live_session_raised_asks_for_nothing`.
    This is the criterion the session check alone cannot satisfy, because `unavailable`
    leaves the cached view in place by design.
15. With `app/api.js` absent, route changes issue no request, write nothing to the
    console and throw nothing; the offline notice stays up with focus on `#notice-title`.
    Scenario: `a_route_change_with_no_api_client_loaded_asks_for_nothing`, whose declared
    request list is empty.
16. With the gate up, a click on `#feed-retry` and a click on `#add-roster-retry` issue no
    request. Scenario: `the_retry_controls_behind_the_gate_ask_for_nothing`.
17. Signed in and linked, routing behaves exactly as it does today. These four scenarios
    are green and unedited: `routing_shows_one_screen_and_moves_focus`,
    `going_back_to_a_screen_reads_it_again`, `an_unknown_hash_is_replaced_not_pushed`,
    `the_add_screen_takes_focus_only_while_it_is_the_current_screen`.

### The draft

18. `showApp()` calls `loadFeed()`, `balancesEntered()` and `addResumed()`, and does not
    call `addEntered()`. `addEntered` appears exactly twice in `app/app.js`: its
    declaration and its `hashchange` registration.
19. The clearing lives in exactly one function, `addCleared()`, and is called from exactly
    two places: `addEntered()` and the sign out button's success path. No other function
    assigns `''` to `#add-amount` or `#add-description`, apart from `addSaved()`, which
    clears the form after a save the server confirmed and is unchanged.
20. Type an amount and a description on `#/add`, save, take a 401, and the gate comes up
    carrying the server's sentence with both fields still holding what was typed and
    `#add-submit` enabled. Scenario:
    `an_interrupted_save_keeps_what_was_typed_through_signing_back_in`, mid-point
    assertions. This is today's behaviour, now pinned.
21. Sign back in from there and the app frame returns with `#add-amount` and
    `#add-description` still holding exactly what was typed, `#add-saved` hidden,
    `#add-error` hidden, the roster read again, `#add-payer` holding the three members
    with the acting one marked `(you)`, `#add-payer` set to the acting member, and focus
    on `#add-amount`. Same scenario.
22. The same interruption with Uneven amounts chosen leaves the mode on Exact after
    signing back in, with one row per member and every share field empty. Scenario:
    `an_interrupted_save_keeps_the_split_mode_and_rebuilds_the_person_rows`. This pins
    decision 5 as a decision rather than an accident.
23. A successful sign out empties `#add-amount` and `#add-description` and returns the
    mode to Equally, and they are still empty when the next sign-in brings the frame back.
    Scenario: `signing_out_clears_the_draft_before_the_next_person_signs_in`. A sign out
    the server refuses clears nothing: scenario
    `a_sign_out_the_server_refuses_leaves_the_draft_alone`.
24. `leaving_add_and_coming_back_starts_a_fresh_entry` is green and unedited. A resume
    that stopped clearing must not have stopped a navigation clearing, and that scenario
    is what catches it.

### The harness

25. Nine scenarios are appended to `SCENARIOS` in `tests/shell_harness.mjs`, after the add
    screen block, under one new section comment naming this task, in this order and with
    these exact names:
    1. `a_route_change_behind_the_gate_asks_for_nothing_and_leaves_the_gate_alone`
    2. `a_route_change_behind_the_not_linked_notice_asks_for_nothing`
    3. `a_route_change_under_a_curtain_a_live_session_raised_asks_for_nothing`
    4. `a_route_change_with_no_api_client_loaded_asks_for_nothing`
    5. `the_retry_controls_behind_the_gate_ask_for_nothing`
    6. `an_interrupted_save_keeps_what_was_typed_through_signing_back_in`
    7. `an_interrupted_save_keeps_the_split_mode_and_rebuilds_the_person_rows`
    8. `signing_out_clears_the_draft_before_the_next_person_signs_in`
    9. `a_sign_out_the_server_refuses_leaves_the_draft_alone`
26. Every one of the nine declares its full ordered `expectRequests` list, with the exact
    body for every request that changes something, which `finish()` already enforces.
27. Every one of the nine asserts a whole screen state through the existing helpers
    (`gateIsUp`, `noticeIsUp`, `appIsUp`), never one flag at a time, and every one that
    raises a notice names which of the four paragraphs it expects.
28. The nine add no new module-level constant, fixture or helper to the harness. They
    reuse `A_MEMBER`, `NO_MEMBER`, `ADD_ROSTER`, `EMPTY_FEED`, `EMPTY_ROSTER`,
    `EMPTY_BALANCES`, `ADD_MILK`, `ADD_UNEVEN_SHORT`, `SIGN_IN_BODY`, `NO_BODY`,
    `REFUSED`, `EXPIRED`, `GENERIC_500`, `addBoot`, `signIn`, `screensLoad`,
    `addPayerOptions`, `addPersonFields`, `addModeChecks`, `addRosterStates`,
    `visibleScreens` and the response fixtures. Nothing in the first 1400 lines of the
    harness is edited.
29. No existing scenario is edited, renamed, reordered or deleted. The diff of
    `tests/shell_harness.mjs` is one appended block. If an existing scenario turns red,
    stop and re-read it rather than loosening it: nothing in this task should make one
    fail, and one that does is telling you the change went wider than it should.
30. `SCENARIOS` in `tests/test_shell_behaviour.py` gains the same nine names, in the same
    order, appended at the end under one new comment header. No existing entry moves.
31. `MUTANT_D` is added to `tests/test_shell_behaviour.py`: it restores the
    client-loaded-only test at `loadFeed()`'s call site, so defect 1 comes back on one
    screen and the app otherwise works. Its anchor matches exactly once, and its test
    asserts exit 1, that
    `a_route_change_behind_the_gate_asks_for_nothing_and_leaves_the_gate_alone` failed
    with `GET /api/expenses` named in its failure messages, and that
    `an_unknown_hash_is_replaced_not_pushed` still passed.
32. `MUTANT_E` is added: it replaces `addResumed();` with `addEntered();` inside
    `showApp()`, which is defect 2 exactly. Its anchor matches exactly once, and its test
    asserts exit 1, that `an_interrupted_save_keeps_what_was_typed_through_signing_back_in`
    failed with `#add-amount` named in its failure messages, and that
    `an_unknown_hash_is_replaced_not_pushed` still passed.
33. `MUTANT_A`, `MUTANT_B` and `MUTANT_C` still match their anchors exactly once and still
    kill what they killed before, unedited. `show()` gains a line, so check `MUTANT_A`
    first: if its anchor no longer matches exactly once, re-express it in this same change
    to reintroduce the same defect rather than weakening it.

### The suite and the rules that must survive

34. `uv run python -m pytest` is green, with nothing skipped and nothing xfailed. The
    count rises from master's 2052 by exactly eleven: nine new scenario cases and two new
    mutant tests.
35. `node tests/shell_harness.mjs < /dev/null` exits 0 against the shipped files.
36. `app/api.js` is not edited. `git diff --name-only` against the merge base lists
    exactly `app/app.js`, `tests/shell_harness.mjs`, `tests/test_shell_behaviour.py` and
    this file.
37. `test_only_the_api_client_interprets_a_status`, `test_the_narrowed_status_rule_still_bites`
    and `test_only_the_api_client_calls_the_back_end` are green and unedited. No file
    under `app/` other than `api.js` compares against a status or an HTTP status number,
    and `app/app.js` still calls no `fetch` and names no `/api` path.
38. `tests/test_web_shell.py` needs no edit at all. If one of its tests breaks, stop and
    re-read it rather than loosening it.
39. Nothing typed reaches browser storage: `localStorage`, `sessionStorage`, `indexedDB`
    and any cookie write are absent from `app/app.js`, as they are today.
40. The comments that describe the changed behaviour are corrected in the same change, and
    a reviewer can read the new rule without opening this file. Specifically:
    `ledgerIsUp()` carries its own comment naming the three conditions, the case each one
    covers, and the two harms the guard prevents; `loadFeed()` and `addLoadRoster()` no
    longer say "Three guards ... the client has loaded"; `addEntered()` no longer says it
    is "called on every entry to this route, and once more from showApp" and its "nothing
    is kept between visits" is corrected to say what a resume keeps and what it does not;
    `balancesEntered()`'s "once more from showApp" is corrected; `render()`'s focus
    comment says why focus stays put behind a curtain; and `show()`'s comment mentions the
    state it records.

## Out of scope

* **`app/api.js`.** It already exposes everything this task needs. No new kind, no new
  handler, no change to what a status means, and no change to which kinds drop the cached
  session view. In particular `not-linked` goes on leaving `cached` alone, which is task
  32's decision, and the third condition in the helper is what covers it instead.
* **`app/index.html` and `app/styles.css`.** No new copy and no new element. Both files
  stay completely clear for the sibling branches.
* **Anything under `src/splitwise_lite/` or `scripts/`.**
* **Preserving ticks, typed shares or a hand-picked payer across a resume.** Decision 5
  says why, and criterion 22 pins the behaviour that ships.
* **A way back from the offline and problem curtains.** Neither has a retry today and
  neither gains one here: a reload is still the only route out. Worth its own issue, and
  it is not this one.
* **Emptying the feed and balances lists when somebody signs out.** They sit hidden behind
  the gate and are replaced before anything is drawn on the next read.
* **A draft that survives a page reload.** Nothing goes into browser storage, ever.
* **Guarding the save itself.** `addSubmitted()` is a person's explicit write, not a
  screen reading on its own initiative, and it is unreachable behind a curtain anyway.
* **What `document.title` says while a curtain is up.** It still names the current screen,
  as it does today.
* **Issue #37.** Its item 2, that the session cache is only ever asserted null, is
  adjacent: after this task the guard depends on the cache holding a view with a member,
  so several of the new scenarios fail if it stops doing so, and item 2's blind spot gets
  a behavioural user for the first time. That is the overlap, and it is all of it. Do not
  add #37's ten mutations here. If #37 lands first, rebase and keep both.
* **Bumping `VERSION` in `app/sw.js`.** An installed client keeps serving the cached shell
  until somebody does. Raise it at merge time, with whichever of the concurrent changes
  lands last.

## Constraints

* **Edit exactly three files**, plus this one: `app/app.js`, `tests/shell_harness.mjs` and
  `tests/test_shell_behaviour.py`.
* **The edits to `app/app.js` are surgical and confined to named places**, because sibling
  branches are in this same file. A reviewer checks the diff touches these and nothing
  else:
  * the shared preamble: the new `ledgerIsUp()` and nothing else;
  * `render()`: the focus condition;
  * `loadFeed()`: its guard and the comment above it;
  * the add block: `addEntered()` split into `addCleared()`, `addOpened()`, `addEntered()`
    and `addResumed()`, and `addLoadRoster()`'s guard;
  * `balancesEntered()`: its two early returns become one guard;
  * the gate block: the state `show()` records, `showApp()`'s third call, and the sign out
    button's success path.
* **`app/api.js` is the only place that decides what a response means**, and widening
  nothing here widens that. `app/app.js` must not gain an `if (error.status === ...)`, an
  `if (error.code === ...)`, a comparison against an HTTP status number, or a second
  reading of `kind` beyond the two that already exist in `addCurtained()` and `wire()`.
* **`tests/shell_harness.mjs` is shared with the concurrent #38 branch.** Append scenarios
  at the end of `SCENARIOS`; do not restructure the file, do not touch the helpers above
  it, and do not renumber or regroup anything. Whichever of #38 and #43 lands second will
  have to rebase: expect a conflict at the end of the `SCENARIOS` array and at the end of
  the `SCENARIOS` list in `tests/test_shell_behaviour.py`, resolve it by keeping both
  blocks in harness order, and re-run `uv run python -m pytest` afterwards, because that
  list has to match the harness exactly. If #38 also adds a mutant, take the next free
  letters for these two rather than renaming theirs.
* **No new dependency of any kind.** No npm, no `package.json`, no `node_modules`. The
  harness goes on importing `node:vm`, `node:fs`, `node:path` and `node:url` and nothing
  else.
* **No money arithmetic anywhere.** Nothing in this change parses, adds, divides, rounds
  or reformats a cent value. What was typed is carried as the characters that were typed.
* **Every string a screen puts on the page still goes in through `textContent`.** No
  `innerHTML` anywhere under `app/`.
* **No new user-facing copy.** Standing copy lives in `app/index.html`, which this task
  does not open.
* **No test is skipped or marked xfail to make the suite green**, per
  `.claude/rules/testing.md`. The test command is exactly `uv run python -m pytest`; plain
  `uv run pytest` fails on this machine with an access-denied spawn error.
* **`node` 20 or later must be on `PATH`**, as CLAUDE.md says. A missing `node` fails the
  suite loudly and is never skipped.

## Amendment after review, PR #48

Everything above is the task as written and as built. This section is what changed after
review, and nothing above it was edited: the acceptance criteria are left exactly as they
were checked, including the one relaxed below, so a later reader can see what was asked
for and what was then found to be missing from it.

### Decision 6: a resume is keyed on identity, not on a sign out

Review found a defect the forty criteria do not cover, and it is a money bug.

Decision 4 above names the harm exactly: "Sam types an expense, signs out, and Ali signs
in to find Sam's amount and description sitting in the form with Ali named as the payer."
Its mitigation is a clear on a confirmed `DELETE /api/session`, and that guards the wrong
door. The dominant path into "gate up, draft alive" is not a sign out, it is a **401 on
save**, which is the path this whole change exists to serve. Nobody signs out there, so
`addCleared()` never runs, `addResumed()` keeps Sam's draft, `addLoadRoster()` rebuilds
the picker and names Ali as the payer of it, and one tap on Save records Sam's expense
against Ali.

"Did a sign out succeed" is a proxy for "is this the same person", and it misses the
common case. The direct question is available and costs nothing:

* `addOpened()` records the acting member id in `addDraftMember`, taken from the existing
  `addActingId()` helper. It is written **on the way in**, while somebody is demonstrably
  signed in and looking at the ledger, and never when the draft is restored. By the time
  a curtain is up the answer can be gone: `announce()` in `api.js` drops the cached view
  for `signed-out` and `sign-in-not-kept`, which is exactly the 401 path.
* `addResumed()` calls `addCleared()` unless `addActingId()` matches `addDraftMember`,
  then opens as before. So the same person coming back keeps everything decision 5
  promises, and anybody else gets a fresh entry.

This reads no status, no code and no kind, needs no change to `app/api.js`, and stays in
the files the task already opens. The sign out clear stays: an explicit sign out is a real
end of visit and should not depend on who signs in next.

`addCleared()` therefore has three callers, not two, and its comment says so.

### Criterion 28 is relaxed, deliberately

Criterion 28 forbade the nine scenarios any new module-level constant or fixture. That is
what kept the diff clean, and it is also what made this defect unassertable: every session
fixture in the harness is `acc-1`/`mem-1`, or that same account with `member: null`, so
there was no way to put two people at one phone.
`signing_out_clears_the_draft_before_the_next_person_signs_in` is named for the next
person and then signs the **same** person back in, because the fixture for a different one
did not exist.

**The relaxation:** the harness gains `A_SECOND_MEMBER` and `SECOND_SIGN_IN_BODY`. Two
constants, one purpose, and they unlock the whole shared-phone class of scenario.

Everything else in criteria 28 and 29 still holds and was held to. The addition is append
only, nothing in the first 1400 lines is edited, and no existing scenario is edited,
renamed, reordered or deleted, because #38 is appending to the same file. The two
constants sit **below** `SCENARIOS` rather than beside `A_MEMBER` for that reason alone;
module evaluation reaches them long before `main()` runs.

### Two more scenarios and a sixth mutant

Appended after the nine, in this order:

10. `a_401_on_save_then_a_different_person_signs_in_starts_a_fresh_entry`, the reviewer's
    scenario: the 401, the draft held at the mid-point so "empty afterwards" is a change,
    then Ali signs in and gets empty fields, `Ali (you)` in the picker and `mem-2` as the
    payer.
11. `a_401_on_save_then_a_different_person_signs_in_returns_the_split_to_equally`: the
    mode exception decision 5 makes is an exception for the person who chose it, not for
    the phone, so Sam's Exact and the rows under it go too.

`an_interrupted_save_keeps_what_was_typed_through_signing_back_in` is the mirror and is
untouched: the same person signing back in still keeps their draft, which is the whole
point of the feature.

`MUTANT_F` switches the identity check off, which is the shape this branch first shipped.
It kills both new scenarios and leaves the same-person resume, the navigation clear and
the unrelated control green, so the two new scenarios are evidence rather than decoration.
`MUTANT_E`'s anchor, `addResumed();`, is untouched by this fix and still matches once.

### One thing that is not load bearing, said plainly

The second condition of `ledgerIsUp()`, the `!view.member` half, still has no behavioural
user after this fix: weakening it to `if (!view)` leaves all 82 scenarios green, while
conditions 1 and 3 each kill one. That is not a gap in the scenarios. `show('app')` has
one caller and is reached only for a view that carries a member, so the app frame over a
memberless view is unreachable, and the fix above reads the member through
`addActingId()`, which is null safe in its own right. The condition stays, because it is
what says what the helper means and callers read a member off that view once it says yes,
and the helper's comment now says it is the invariant's statement rather than the line the
tests are holding.

### Criterion 34's arithmetic, restated at merge

QA reported criterion 34 as unreconciled rather than failing it, and was right to.
The criterion says the count rises "by exactly eleven"; it rises by fourteen. The
amendment above restates criteria 19, 25 and 30 but never restated 34's number, so a
reader checking it literally finds a figure nobody updated.

The fourteen are the original nine scenarios and two mutants, plus the two
shared-phone scenarios and `MUTANT_F` this amendment adds.

Criterion 34's baseline is stale in a second way. It names master at 2052, which is
where master stood when this branch was cut. Master has since taken PR #47 (the shell
precache digest) and PR #50 (transfer provenance) and stands at 2158. The number to
check on the merged branch is therefore **2172**, and the harness runs **83**
scenarios: this task's 82 plus the debt-path scenario task 12a appended to the same
array.

### The precache digest, recomputed at the merge

`app/app.js` is one of the nine files `app/sw.js` precaches, so merging master turned
`test_the_recorded_digest_matches_the_files_it_covers` red, exactly as PR #47 intended
and exactly where issue #49 predicted it would matter: on a merge commit, not on
either branch. `SHELL_DIGEST` moves from `141951154c0a` to `62daaf7c5a5b`. `VERSION`
stays `v4`, since the worker's own behaviour is unchanged.

The failing test printed the line to paste; nothing here was worked out by hand. That
is the mechanism doing its job, and this is the first time it has fired on a real
merge rather than on a deliberate proof.
