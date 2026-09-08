# Task 72: `loadFeed` swallows programming errors as refused requests

Issue #72. Branch `task-72`, cut from master `6c5e144`.

> **How every number in this document was obtained.** The Bash tool was unavailable for
> the whole of this analysis, and the GitHub MCP tools were unavailable with it. Nothing
> below was **run**. Every line number, count and literal is a **read**, taken with the
> Read and Grep tools against the worktree at
> `C:\Users\SurajShakya\source\other\learn-claude\splitwise-lite-task-72`, and each one
> names the file and line it came from so it can be re-derived. Issue #72's own text
> could not be fetched; this document works from the issue's claims as relayed in the
> brief, and **re-derives each of them against the source** rather than inheriting it.
> Wherever a claim in the issue turned out to be stale, this document says so and quotes
> what it retracts.
>
> **Consequence for the engineer:** every "recorded" criterion below is a run *you* must
> perform. None of them has been performed here. Treat an unrun criterion as unmet.

---

## Verdict: build it, but the reason in the issue is obsolete and the goal changes

**This issue should not close as obsolete, but its stated justification no longer holds
and must not be repeated in the PR.**

What the issue says the fix buys is that a broken render will stop going unnoticed. That
is no longer true, because #57 landed two independent nets and either one catches the
original defect:

1. `refusedProperty()` (`tests/shell_harness.mjs:9091`) records a refused stub property
   against the running scenario **and** returns the `Error` for the guard to throw, so
   what the app does with the exception is irrelevant. Its own comment at
   `tests/shell_harness.mjs:9078-9085` names `loadFeed`'s `.then(done, done)` as the
   reason it works this way.
2. The in-flight invariant (`tests/shell_harness.mjs:1001-1008`) fails any scenario that
   returns with `#feed-loading` or `#balances-busy` visible. `feedState('list')` is the
   last statement of `feedRender` (`app/app.js:622`), so **any** throw inside
   `feedRender` leaves `#feed-loading` up and the invariant fires.

So the sentence in the issue that "the entire render path went unexecuted through two
whole tasks with nobody noticing" describes a hole that is now closed twice over. A PR
for this task that re-states that hole as the benefit is claiming something false.

**What is genuinely left is narrow, and it is diagnosis, not correctness.** The invariant
reports a symptom with no cause: it prints `#feed-loading is still showing after settle`
(`tests/shell_harness.mjs:1004-1005`) and says nothing about which line threw. A chain
that re-raises sends the original error and its stack to `escaped()`
(`tests/shell_harness.mjs:9069-9076, 9102`), which records the stack against the
scenario. The engineer then reads `TypeError ... at feedRender (app.js:600)` instead of
inferring it.

That is worth one line of source. It is not worth a paragraph of justification claiming
more than it does.

**A second, stronger reason to keep the issue open surfaced during the survey below: the
sign-in path swallows programming errors too, and nothing covers it at all.** That is
routed to its own issue rather than folded in here, for reasons given under
[Out of scope](#out-of-scope). Naming it is part of this task's output.

---

## Findings: every line number in the issue, re-derived

The brief warns that #74, #57, #83 and #85 all merged after the issue was filed and that
every line number predates them. Re-derived, by Read against this worktree:

| Claim in the issue | Status | Re-derived location |
| --- | --- | --- |
| `loadFeed` ends `.then(done, done)` at `app/app.js:668` | **Holds, unchanged** | `app/app.js:668` reads `    ).then(done, done);`. The four merges did not move it |
| `balancesLoad` ends `.then(f, r)` with nothing after | **Holds** | `app/app.js:2875` opens the chain, `app/app.js:2896` closes it with `    );` |
| The `unhandledRejection` hook is in `tests/shell_harness.mjs` | **Holds** | `tests/shell_harness.mjs:9102` |

Two corrections to the issue's framing, both of which change what should be built.

**Correction 1. The issue implies feed and balances differ in how they clear in-flight
state. They do not have comparable in-flight state.** `loadFeed` guards on a boolean
`feedBusy` (`app/app.js:631, 634`) which `done` clears (`app/app.js:637-639`).
`balancesLoad` has no busy boolean at all: it uses a monotonic generation counter,
`balancesAttempt` (`app/app.js:2867-2868`), compared at `app/app.js:2877` and
`app/app.js:2886`. There is nothing for a `balancesLoad` equivalent of `done` to clear.
So the two functions are not two idioms for the same job, and "make the feed look like
balances" is not a coherent instruction.

**Correction 2. `.finally(done)` fixes nothing a user can see.** Trace a throw out of
`feedRender` today: the fulfilled handler at `app/app.js:647` throws, the first `.then`
returns a rejected promise, `done` runs as the rejection handler at `app/app.js:668`, and
`feedBusy` is cleared. `feedState('list')` at `app/app.js:622` never ran, so the screen
stays on its loading paragraph. With `.finally(done)` the screen stays on its loading
paragraph **in exactly the same way**; the only difference is that the error is also
re-raised. The user-visible outcome is identical. Any criterion or PR sentence claiming
this change repairs what a person sees is false.

### The survey the issue never did

Grep of `\.then\(|\.catch\(|\.finally\(` across `app/`, restricted to `app/app.js`,
returns **15 occurrences** at lines 646, 668, 1120, 1148, 1416, 1440, 1445, 1450, 1472,
1511, 1548, 2156, 2453, 2675, 2875. Those 15 calls form **11 distinct chains**:

| # | Chain | Ends with | Swallows a throw in its fulfilled handler? |
| --- | --- | --- | --- |
| 1 | `loadFeed`, `app/app.js:646` | `.then(done, done)` at 668 | **Yes** |
| 2 | `addSubmitted` save, `app/app.js:1115` | `.then(f, r)` at 1120 | No |
| 3 | `addLoadRoster`, `app/app.js:1148` | `.then(f, r)` | No |
| 4 | `refresh`, `app/app.js:1416` | `.then(f, r)`, returned to caller | No |
| 5 | gate `submitted`, `app/app.js:1444` | `.catch` at 1450, then `.then` at 1472 | **Yes, by a different mechanism** |
| 6 | sign out, `app/app.js:1511` | `.then(f, r)` | No |
| 7 | `serviceWorker.register`, `app/app.js:1548` | `.catch` | Not applicable |
| 8 | debt drill-down, `app/app.js:2156` | `.then(f, r)` | No |
| 9 | `decideSettlement`, `app/app.js:2453` | `.then(f, r)` | No |
| 10 | `addSettlement`, `app/app.js:2675` | `.then(f, r)` | No |
| 11 | `balancesLoad`, `app/app.js:2875` | `.then(f, r)` | No |

Grep of `\.finally\(` across `app/` returns **0 occurrences**. This task introduces the
first use in the shell.

**Does the add screen share the shape? No, and this was checked rather than assumed.**
Both add-screen paths end in a bare two-argument `.then`, and both clear their in-flight
state as the **first statement inside each handler**, before anything that can throw:
`addSubmitted` calls `settled()` at `app/app.js:1122` and `app/app.js:1126`, and
`addLoadRoster` sets `addRosterInFlight = false` at `app/app.js:1150` and
`app/app.js:1180`. A throw in `addFillPayer()` or `addBuildPeople()`
(`app/app.js:1176-1177`) therefore leaves the flag correctly cleared and rejects a promise
nobody handles, which reaches the `unhandledRejection` hook. The add screen already
behaves the way this task wants the feed to behave. **Nothing in `addLoadRoster` or the
save path is changed by this task.**

**The fourth path exists, and it is the gate.** Chain 5 is
`started.then(f).catch(g).then(h)`. A `TypeError` thrown inside `f` (`app/app.js:1445-1449`,
which calls `setMode(false)` and `refresh()`) is delivered to `g`, whose first statement
is:

```js
if (!error || (error.kind !== 'signed-out' && error.kind !== 'refused')) {
  return;
}
```

(`app/app.js:1451-1457`.) A `TypeError` has no `kind`, so both comparisons are true and
the handler returns silently. The trailing `.then` at `app/app.js:1472-1474` then
re-enables `gateSubmit`. The result is worse than the feed's: the error is swallowed,
**and** the in-flight state is tidied away, so the screen looks entirely normal and the
in-flight invariant cannot see it (that invariant reads two element ids, and
`gateSubmit.disabled` is not an element id it reads). A programming error on the sign-in
success path leaves no trace anywhere: no stuck screen, no unhandled rejection, no console
line.

Note the asymmetry this produces for one function: `refresh()` is also called bare at
`app/app.js:1528`, where a throw in `showApp()` rejects with no handler and surfaces. The
same throw reached through the gate is swallowed. That is chain 5's doing, not
`refresh()`'s.

This is a real, currently-uncovered hole and it is **not fixed here**. See
[Out of scope](#out-of-scope) for why folding it in would be wrong.

---

## Goal

`loadFeed` stops routing a programming error to the same handler as a refused request:
its chain clears `feedBusy` on both paths and re-raises anything thrown out of its
fulfilled handler, so a broken feed render reaches the harness's `unhandledRejection` hook
carrying its own stack instead of arriving as an anonymous stuck screen. Nothing a user
sees changes.

---

## Acceptance criteria

Numbered for reference. Criteria marked **NOT RUN** are defined in [The browser
gap](#the-browser-gap) and **no verdict on this task may depend on them**.

### The source change

1. `app/app.js:668` no longer contains `).then(done, done);`. Grep of
   `\.then\(done, done\)` across `app/` returns 0 occurrences.
2. The chain opened at `app/app.js:646` terminates with `.finally(done);`. Grep of
   `\.finally\(` across `app/` returns exactly 1 occurrence.
3. `done` (`app/app.js:637-639`) is unchanged, still clears only `feedBusy`, and is still
   the only place `feedBusy` is set false.
4. The two handlers passed to the `.then` at `app/app.js:646` are byte-identical to their
   state on master. In particular the rejection handler still calls `feedState('error')`
   and still reads no status code.
5. No other file under `app/` changes except `app/sw.js`, and the only change in
   `app/sw.js` is the `SHELL_DIGEST` string literal at `app/sw.js:35`. `git diff master --
   app/` touches exactly two files.

### The behaviour, demonstrated

6. **`feedBusy` is cleared on both paths, and this is deliberately not asserted
   separately.** It follows from `.finally` running its callback on settle either way, and
   it is already pinned by criteria 2 and 3 together. A separate scenario asserting it
   would need a new scenario name, which criterion 22 says this task does not add, and it
   would assert a property of the language rather than of this code. Stated here so the
   omission reads as a decision rather than a gap.
7. A throw out of `feedRender` produces a failure line against the running scenario whose
   text contains `unhandled rejection` and the thrown error's type. This is the guarantee
   the task exists for and it is stated only here.
8. A refused request (any rejection of `api.expenses()` or `api.members()`) produces
   **no** `unhandled rejection` line, and still reaches `feedState('error')`. The change
   must not turn an ordinary server refusal into an unhandled rejection.
9. The harness exits 0 against the shipped files after the change, so
   `tests/test_shell_behaviour.py::test_the_harness_exits_zero_against_the_shipped_files`
   passes unmodified.

### The check that proves criterion 7, and the trap in it

10. A new pytest test in `tests/test_shell_behaviour.py` runs the harness with a
    **single-line anchored substitution** that makes `feedRender` throw a plain
    `TypeError`, and asserts that the failures recorded for
    `a_feed_row_names_the_payer_the_amount_and_what_it_was_for` include a line containing
    `unhandled rejection`.
11. That same test asserts `a_feed_with_nothing_recorded_says_so_and_draws_no_row` still
    passes, as the named survivor. It is already designated for this role at
    `tests/test_shell_behaviour.py:377-381`, where it is bound to `THE_EMPTY_FEED` and
    described as "the one that never reaches `feedRender`".
12. **The substitution must provoke a throw that the stub's property guard does not
    produce.** A substitution that reaches for a missing DOM member routes through
    `refusedProperty()` (`tests/shell_harness.mjs:9091`), which records its own failure
    line independently of the app's promise shape, so the test would pass with or without
    the change. Anchoring on a plain-object dereference in the payload avoids this,
    because `payload` is parsed JSON and no stub guard applies to it.
13. **Recorded demonstration that criterion 10 can fail.** With the substitution applied
    to an `app/app.js` that still ends `.then(done, done)`, the new test fails, and the
    recorded output shows the scenario failing with the in-flight invariant's line
    (`#feed-loading is still showing after settle`) and **without** any `unhandled
    rejection` line. Paste both outputs into the mutation record. This is the whole
    demonstration: the invariant fires either way, so a test that merely asserted "the
    scenario went red" would pass before and after and could not fail.
14. **No tenth committed mutant is added.** `MUTANT_A` through `MUTANT_I` at
    `tests/test_shell_behaviour.py:228-371` assert that a mutation turns named scenarios
    red. A `MUTANT_J` in that family would be exactly the check criterion 13 forbids: the
    in-flight invariant reds those scenarios under both promise shapes, so the mutant test
    could not fail. The targeted test of criterion 10, which asserts on a specific failure
    line, is the correct instrument. State this reasoning in the mutation record.

### The record

15. `plans/mutations/72-the-feed-swallows-its-own-errors.md` exists and holds the
    substitution of criterion 10 as one fenced `json` block with exactly the seven keys
    `id`, `file`, `find`, `replace`, `kills`, `survives`, `result`
    (`plans/mutations/README.md:18-31`).
16. `find` is a **single line**. `MUTANT_F`, `MUTANT_H` and `MUTANT_I` each record that a
    multi-line anchor rots on a CRLF checkout, and this working tree is CRLF
    (`tests/test_shell_behaviour.py:334-338, 363-366`).
17. Any pytest node id appearing in that record's prose also appears in its `kills` or
    `survives`. A node id cited as a precedent rather than as a claim is written bare, in
    the form `test_name in tests/test_file.py` (`tests/test_suite_integrity.py:1708-1710`).

### Guards that must not move

18. `SHELL_DIGEST` at `app/sw.js:35` is updated to the value printed by the failing
    `tests/test_web_shell.py::test_the_recorded_digest_matches_the_files_it_covers`, taken
    from that test's output and not computed by hand. Its value on master is
    `'f8453329c392'`.
19. `VERSION` at `app/sw.js:34` still reads `'v4'`.
20. `API_SURFACE` in `tests/test_web_shell.py:1328-1348` is unchanged and still holds
    **16** entries. Counted by Read of those lines: `ApiError`, `onUnauthenticated`,
    `onNotLinked`, `onOffline`, `session`, `cachedSession`, `signUp`, `signIn`, `signOut`,
    `members`, `expenses`, `addExpense`, `balances`, `debt`, `addSettlement`,
    `decideSettlement`. `app/api.js` is not touched, so the guard has nothing to fire on.
21. `CARRIED_TOTAL` at `tests/test_suite_integrity.py:1118` still reads **107** or less.
    If a new `pytest.raises` block is introduced it is anchored, never added to the
    baseline; the baseline may only shrink
    (`tests/test_suite_integrity.py:1192-1217`).
22. `SCENARIOS` in `tests/test_shell_behaviour.py:42-217` and the scenario list in
    `tests/shell_harness.mjs` still agree exactly, per
    `test_the_harness_reports_exactly_the_declared_scenarios` at
    `tests/test_shell_behaviour.py:500-503`. Grep of `    name: '` in
    `tests/shell_harness.mjs` returns **160** occurrences on master; if this task adds no
    scenario, that count is unchanged.
23. Neither `CLAUDE.md` nor `README.md` gains or loses a capability bullet. This task adds
    no user-visible capability. Both documents' two delimited lists are pinned to a
    literal in `tests/test_web_shell.py` (`tests/test_web_shell.py:1319-1322`), and on this
    worktree `What does not exist yet` holds only **Expense correction** at
    `CLAUDE.md:77-78`, the incompleteness signal having moved up at `CLAUDE.md:52-55` when
    #83 landed.

### Commit shape

24. Two commits, in this order. **Commit 1** adds the new test and the mutation record and
    changes nothing under `app/`; `git diff master -- app/` is empty at that commit and
    the new test fails, which is the recording criterion 13 asks for. **Commit 2** makes
    the one-line change in `app/app.js` and the `SHELL_DIGEST` update, and the new test
    passes. See [How task 9b's rule is satisfied](#how-task-9bs-rule-is-satisfied).

### NOT RUN

25. **NOT RUN.** In a browser, a throw out of `feedRender` produces an unhandled rejection
    visible in the devtools console, and produces no visible change for a person using the
    app.
26. **NOT RUN.** `Promise.prototype.finally` is available in every browser this shell
    supports.

---

## Out of scope

- **The gate's swallow (chain 5, `app/app.js:1444-1474`). Raise it as its own issue and
  link it from the #72 PR.** It is a different fix, not the same one applied twice.
  Changing `return;` at `app/app.js:1456` to `throw error;` would skip the trailing
  `.then` at `app/app.js:1472-1474`, because a rejected promise skips a fulfilled handler,
  leaving `gateSubmit` permanently disabled and the gate unusable. So the trailing `.then`
  would have to become `.finally` as well, and, more importantly, a bare re-raise would
  turn **every** offline or unavailable sign-in into an unhandled rejection, since those
  errors also reach that handler and are swallowed there deliberately. Doing it correctly
  needs the handler to discriminate an `ApiError` from a programming error, which is a new
  coupling to a type currently used only as an export. That is a design decision with its
  own blast radius and it does not belong in a one-line change to the feed.
- **A top-level `unhandledrejection` handler in the shell.** See [What an unhandled
  rejection should do in production](#what-an-unhandled-rejection-should-do-in-production).
- **Adding `#add-roster-busy` to the in-flight invariant** at
  `tests/shell_harness.mjs:1001`. The element exists (`app/index.html:202`) and the
  invariant does not read it, so there is a gap. It is left alone here for two reasons.
  It would change what the invariant asserts for all 160 scenarios, and whether any
  currently-passing scenario ends with that note visible could not be determined without
  running the suite, which was not possible during this analysis. And it would be partly
  blind anyway: `addLoadRoster` calls `addRosterState('')` at `app/app.js:1174` **before**
  `addFillPayer()` and `addBuildPeople()` at `app/app.js:1176-1177`, so a throw in either
  leaves the busy note already hidden. Raise it separately with that limit stated.
- **Re-measuring #37's ten mutations.** See [Ordering against #37](#ordering-against-37).
- **Any change to `balancesLoad`.** It already propagates. Correction 1 above explains why
  it is not a template for the feed either.
- **Any change to `addLoadRoster` or the add save path.** Both already propagate.
- **Changing what a user sees on a feed error.** The rejection handler at
  `app/app.js:660-667` keeps `feedState('error')` and keeps not reading a status code.
  Routing the re-raised programming error into `feedState('error')` is specifically
  forbidden: that would restore the exact conflation this issue objects to, a `TypeError`
  presented as a refused request, while adding a re-raise on top of it.
- **`app/api.js`.** Untouched, so criterion 20 holds trivially.
- **New dependencies, npm, `package.json`, `node_modules`, a JS test framework, or a real
  browser driver.** All already forbidden by task 9b
  (`plans/tasks/09b-javascript-test-harness.md:584-592`).

---

## Constraints

- **Files that may change:** `app/app.js` (one line), `app/sw.js` (the `SHELL_DIGEST`
  literal only), `tests/test_shell_behaviour.py` (one new test, one substitution literal),
  and a new `plans/mutations/72-the-feed-swallows-its-own-errors.md`. Nothing else.
- **The anchor for the source change** is the single line `    ).then(done, done);` at
  `app/app.js:668`, four spaces of indentation. It matches exactly once, verified by Grep
  of `\.then\(done, done\)` across `app/` returning one hit.
- **Every anchor in this task is one line.** Constraint reason at criterion 16.
- **`uv run python -m pytest`, never `uv run pytest`**, which fails on this machine with an
  access-denied spawn error (`CLAUDE.md`). Set `PYTHONDONTWRITEBYTECODE=1` on every run
  (`plans/mutations/README.md:75-85`).
- **Do not run the full suite.** It exceeds the ten-minute agent watchdog. Chunk by module
  and take counts from `--collect-only -q`. The modules this task can affect are
  `tests/test_shell_behaviour.py`, `tests/test_web_shell.py` and
  `tests/test_suite_integrity.py`; run those three and no more unless one of them points
  elsewhere.
- **Narrate one line before every command.**
- **`node` 20 or later on `PATH`** is a test-time requirement and a missing `node` fails
  the suite loudly rather than skipping (`CLAUDE.md`).
- **The harness runs the real `app/` files** under `node:vm` with
  `vm.createContext(sandbox)` at `tests/shell_harness.mjs:768`, which supplies the full set
  of V8 intrinsics. There is no `Promise` stub: Grep of `sandbox\.Promise|Promise:|Promise =`
  across `tests/shell_harness.mjs` returns 0 occurrences. `.finally` therefore resolves to
  the native implementation.
- **No scenario may read the source text of `app/app.js` or `app/api.js` and assert on
  it** (`plans/tasks/09b-javascript-test-harness.md:394-398`). Criteria 1 and 2 are checks
  a reviewer or a `tests/test_web_shell.py`-style structural test performs, not a harness
  scenario.
- **CI runs `ubuntu-latest` and `windows-latest`** and both must be green. A PR whose base
  has moved must be brought up to date and re-run, because the merge commit is where a
  stale shell digest surfaces (`CLAUDE.md`).

---

## How task 9b's rule is satisfied

The issue records, as one of three reasons this was not done inside #57, that it "would
change a subject and its test in the same commit, which task 9b forbade by name."

**That reading is too broad, and this document retracts it.** The rule is a bullet in task
9b's own `Out of scope` section, `plans/tasks/09b-javascript-test-harness.md:577-583`:

> - **Any change to `app/`.** Not `index.html`, not `app.js`, not `api.js`, not
>   `styles.css`, not `sw.js`, not the manifest, not the icons. This task tests what is
>   there. If a scenario exposes a bug, it is reported and fixed in its own task, not here.
> - **Fixing the front end.** [...] the harness pins the current behaviour and the engineer
>   raises it. Changing the app and its test in one commit is how a test ends up asserting
>   whatever the code happens to do.

Two things follow. The prohibition is scoped to task 9b, a task whose entire purpose was to
build a harness against unchanged app files; it is not a repo-wide law. And the same bullet
**positively routes** the fix: "reported and fixed in its own task, not here." Task 72 is
that own task. Far from forbidding this work, 9b anticipates it.

`plans/tasks/57-the-feed-render-path-runs-under-test.md:152-154` is where the broad reading
was written down, and it is the sentence the issue inherited. It was a reasonable
conservative call inside #57, whose criterion 1 required `git diff master -- app/` to be
empty (`plans/tasks/57-the-feed-render-path-runs-under-test.md:150`). It does not bind #72.

**But the rationale still has force,** and it is honoured by the commit order of criterion
24 rather than by an exemption. Writing the check and the fix in one commit is how a check
ends up asserting whatever the fix happens to do. Landing the check first, red, against an
unmodified `app/`, and recording that failure, proves the check bites before the fix exists
to flatter it. That is the "demonstrated capable of failing" standard the repo applies
anyway, so no special pleading is needed: **two commits, and the reason is the
demonstration, not 9b.**

---

## What an unhandled rejection should do in production

**Today, nothing.** Grep for a top-level rejection handler finds none; the shell registers
no `unhandledrejection` listener. So after this change, a broken feed render in a browser
writes a line to a devtools console that no user has open, and nothing else. No user sees
it, nothing is reported anywhere, and no server records it: there is no telemetry in this
project and no logging endpoint.

So the honest account of this change in production is that it is **neutral for users and
positive for a developer with devtools open**. Its real value is in the harness, where the
hook at `tests/shell_harness.mjs:9102` turns the rejection into a recorded failure with a
stack.

**Should the shell get a top-level handler that reports rather than swallows? Probably
yes, and definitely not here.** It is a product decision, not a refactor. The app's curtain
vocabulary is a fixed set: `#notice` carries exactly four paragraphs and an invariant at
`tests/shell_harness.mjs:968-981` fails any scenario where the curtain is up without
exactly one of them showing. There is no paragraph for "this app has a bug". Adding a fifth
means new copy, a change to `NOTICES`, and a decision about whether a programming error
should cover the whole frame and hide a ledger that may still be perfectly readable. That
deserves its own issue with its own scenario.

**What this task must not foreclose.** It must not add any `window.addEventListener('unhandledrejection', ...)`
or `window.onunhandledrejection`, so that the future issue starts from a clean absence
rather than from something to undo. It must not repurpose any existing notice paragraph as
a crash notice. And it must not route the re-raised error into `feedState('error')`, which
would both foreclose the future design and reintroduce the conflation this issue exists to
remove.

---

## The browser gap

**Nothing in this project has ever been verified in a browser, and this change is precisely
about what a browser does with an error.** The suite cannot answer it. The harness runs
under `node:vm` against a stubbed DOM and a stubbed `fetch`, and task 9b's `What stays
browser-only` section (`plans/tasks/09b-javascript-test-harness.md:317-322`) states that the
harness must not pretend to cover browser behaviour and that no scenario may be named as if
it did.

Criteria 25 and 26 are therefore marked **NOT RUN**. They are not failures and they are not
passes. **Recording an unrun browser check as "pass" is a FAIL of this task**, and no
verdict on this task may depend on either of them.

Route both to **issue #80**, which already carries eleven items across three comments, as
two further items:

- Open the app in a browser, provoke a throw inside `feedRender`, and confirm the devtools
  console shows an unhandled rejection naming `feedRender`, and that the visible screen is
  the loading paragraph and is otherwise unchanged from master's behaviour.
- Confirm `Promise.prototype.finally` resolves natively in the browsers under test. Low
  risk, since `app/app.js` already calls `replaceChildren` (`app/app.js:612`), which is
  newer than `.finally`, but it is a browser fact and so it belongs on the browser list
  rather than being asserted from a Node run.

---

## Ordering against #37

**#37 is downstream of this task and is not absorbed by it.** Six of the ten mutations #37
recorded as "surviving" were measured against a feed whose render path was not executing.
#74 has since made that path run, and this task changes the feed's error path again. Any
re-measurement of those ten mutations must therefore be taken **after** this task lands,
not before, or it will be a third measurement of a third feed.

This task does not re-measure them, does not edit #37's record, and does not close #37. The
#72 PR should note the dependency so whoever picks up #37 does not start against a base that
is about to move.

---

## Size estimate

**Small: two shipped lines, roughly 80 lines of test and record, five files.**

The estimate is a **read, not a run**: `git diff --stat` could not be executed, because
Bash was unavailable throughout. It is built from these reads:

- `app/app.js`: 1 line replaced, at line 668.
- `app/sw.js`: 1 line replaced, the `SHELL_DIGEST` literal at line 35.
- `tests/test_shell_behaviour.py`: one substitution dict plus one test function. Sized
  against this file's existing density, where the `MUTANT_H` comment block alone runs 22
  lines (`tests/test_shell_behaviour.py:317-338`); budget 40 to 60 lines including the
  reasoning criterion 14 requires.
- `plans/mutations/72-the-feed-swallows-its-own-errors.md`: one new file, one seven-key
  JSON block plus the two recorded outputs from criterion 13; the comparable
  `plans/mutations/57-fragment-flattening.md` is the format precedent.
- This task file.

The cost is not in the diff. It is in criterion 13: producing and recording a failure that
is distinguishable from the in-flight invariant's failure is the part that takes the time,
and it is the part that makes the task worth doing at all.
