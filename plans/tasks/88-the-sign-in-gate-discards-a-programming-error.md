# Task 88: the sign-in gate discards a programming error with no symptom at all

Issue #88. Branch `task-88`, cut from master after #72 landed.

> **How every number in this document was obtained.** Nothing below was **run**. Every
> line number, count and literal is a **read**, taken with the Read and Grep tools
> against the worktree at
> `C:\Users\SurajShakya\source\other\learn-claude\splitwise-lite-task-88`, and each one
> names the file and line it came from so it can be re-derived. Where a number could not
> be read, the criterion names the command and leaves the number to the engineer.
>
> **Consequence for the engineer:** every "recorded" criterion below is a run *you* must
> perform. None of them has been performed here. Treat an unrun criterion as unmet.

---

## Verdict: build it, in #72's shape, with the one decision #72 declined to make

Issue #72 landed on master before this task was written, and it is present in this
worktree: `app/app.js:668` reads `    ).finally(done);`, and Grep of `\.finally\(`
across `app/` returns exactly **1** occurrence. So the question "what should a shell
promise chain do with a programming error thrown out of its fulfilled handler" already
has an answer in this repository, and that answer is: **clear the in-flight state on
every path with `.finally`, and let the error escape as an unhandled rejection carrying
its own stack.** Nothing a person sees changes, and nothing is written to the console
by hand.

**This task gives the gate the same answer, and the shape is right for the gate.** It
is worth saying why, because two of #72's three stated obstacles are about the gate
specifically:

- The trailing `.then` at `app/app.js:1472-1474` becomes `.finally`, which is exactly
  what stops the bare re-raise from leaving `gateSubmit` permanently disabled. #72
  already introduced `.finally` to this file, so this is the same idiom a second time
  rather than a new one.
- A genuine offline sign-in must not become an unhandled rejection, and #72's answer
  covers that too: the feed still routes a refused request to `feedState('error')` and
  only a programming error escapes. The gate's version of the same split is the
  discrimination this task exists to build.

**One place the gate genuinely differs from the feed, and it does not change the
answer.** On the feed, a throw is visible from outside even before the fix, because
`feedState('list')` is the last statement of `feedRender` so `#feed-loading` stays up
and the in-flight invariant fires (`tests/shell_harness.mjs:1001-1008`). On the gate
there is nothing to see: the trailing `.then` tidies the in-flight state away, so the
screen looks entirely normal. That makes the gate's version **worse** than the feed's,
not different in kind, and it changes only what the suite has to do to observe the fix,
not what the fix is. See [The symptom](#the-symptom-and-the-instrument-that-can-see-it).

---

## The shape, re-derived

The gate's chain, `app/app.js:1444-1474`:

```js
    started
      .then(function () {          // 1445
        gatePassword.value = '';
        setMode(false);
        return refresh();          // 1448
      })
      .catch(function (error) {    // 1450
        if (!error || (error.kind !== 'signed-out' && error.kind !== 'refused')) {
          return;                  // 1456
        }
        ...
      })
      .then(function () {          // 1472
        gateSubmit.disabled = false;
      });
```

A `TypeError` has no `kind`, so both comparisons at `app/app.js:1451` are true and the
handler returns at `app/app.js:1456`. The trailing `.then` then re-enables the control.
The rejection is consumed, the DOM is left valid, and nothing is recorded anywhere.

Three measured facts about the blast radius:

1. **The gate's `.catch` is the only handler on that fulfilled path.** `refresh()`
   (`app/app.js:1415-1429`) is `api.session().then(f, r)` where `r` is empty, so
   `refresh()` never rejects on its own; a throw inside `showApp()`
   (`app/app.js:1386-1398`), which calls `loadFeed()`, `balancesEntered()` and
   `addResumed()`, rejects `refresh()`'s promise and lands in the gate's `.catch`.
2. **The same throw reached any other way surfaces.** `refresh()` is also called bare at
   `app/app.js:1528`, where a rejection reaches nobody and escapes. So the asymmetry is
   the gate's chain, not `refresh()`'s.
3. **No existing scenario delivers an unrecognised error to that `.catch`.** Every
   rejection out of `api.signUp` and `api.signIn` is an `ApiError` classified by
   `announce()` (`app/api.js:277-314`), and `gatePassword.value = ''` and
   `setMode(false)` cannot throw. So the re-raise fires in none of the 160 scenarios
   and the unsubstituted run must stay green.

---

## The decision: which errors the shell recognises

**Recognised means "app/api.js produced this".** The recognised set is every rejection
`app/api.js` can produce, which is exactly the set of `ApiError` instances
(`app/api.js:175-186`, constructed at `app/api.js:222` and `app/api.js:236` and nowhere
else), each carrying exactly one of **six** kinds. Read off `app/api.js:17-28` and
`app/api.js:244-264`:

| kind | how it reaches the gate's `.catch` | what the gate does with it, unchanged |
| --- | --- | --- |
| `offline` | the sign-up or the sign-in got no answer at all | `onOffline` has raised the offline notice; the `.catch` returns early and writes nothing |
| `signed-out` | a 401 answering the sign-in (`authentication_failed`) or the sign-up | `onUnauthenticated` has re-shown the gate; the `.catch` writes `error.say`, or `'That did not work.'` when the body carried nothing |
| `sign-in-not-kept` | a 401 answering `POST /signup` while armed (a 401 answering `POST /session` is always `signed-out`, `app/api.js:142, 255`) | `onOffline` has raised the not-kept notice; returns early |
| `not-linked` | a 403 `member_not_linked` answering either request | `onNotLinked` has raised the unlinked notice; returns early |
| `unavailable` | a 500, a 503, or a status this client cannot read, answering either request | `onOffline` has raised the problem or offline notice; returns early |
| `refused` | any other 4xx: a 409 on sign-up, a 429 rate limit, a 403 `csrf_failed`. Not escalated, because `ESCALATED` is `GET /session` and `DELETE /session` only (`app/api.js:138`) | no handler spoke; the `.catch` writes the server's sentence on the gate |

**How an unrecognised error is told apart from a recognised one: `instanceof` against the
client's own exported constructor, `api.ApiError`, and not by comparing `kind` against a
list of six strings copied into `app/app.js`.** Three reasons, and this is the decision
an engineer must not have to make alone:

1. `classify()` ends in a default arm (`app/api.js:263`), so every rejection `api.js`
   produces already carries one of the six. A list of the six in `app/app.js` would
   exist only to be kept in step with `api.js`, and this repo has already paid for that
   shape once: `addCurtained` (`app/app.js:997-1016`) used to reconstruct api.js's
   classification from statuses, and its own comment records the lesson, "two spellings
   of one decision drift the moment either is edited."
2. The question is not *which* kind this is. That question is `kind`'s, it is answered in
   the same two-way test as today, and it stays there. The question is whether `api.js`
   produced the object at all, and `instanceof` answers exactly that and nothing else.
3. It keeps an `ApiError` whose `kind` is `''` on the **recognised** side. That state is
   only reachable with `classify()` broken, which is what `MUTANT_C` does
   (`tests/test_shell_behaviour.py:261-265`), and a broken classifier must stay a
   missing gate message rather than becoming a crash report.

`instanceof` is already how the suite itself asks this question:
`tests/shell_harness.mjs:2520` and `tests/shell_harness.mjs:2582` both assert
`instanceof window.SplitwiseApi.ApiError`. It works under `node:vm` because both shipped
files run in one context, and in the browser because both are scripts in one document.
`ApiError` is already a declared part of the client's surface (`API_SURFACE`,
`tests/test_web_shell.py:1328-1348`), so nothing new is exported.

**Unrecognised is therefore everything else, and the list is closed by that:** a
`TypeError` or `ReferenceError` thrown out of `setMode`, `refresh`, `showApp`,
`loadFeed`, `balancesEntered` or `addResumed`; a plain `Error`; a thrown string; `null`;
`undefined`.

**Where that test lives so it is not duplicated per screen:** one function,
`apiRaised(error)`, in `app/app.js`'s preamble beside `ledgerIsUp()`
(`app/app.js:71-80`). The preamble is where this file already puts a predicate that
every screen block asks and none of them owns, in that helper's own words, and it is
above all four region markers (`app/app.js:147, 689, 1313, 1558`). The gate is its only
caller in this task.

---

## Goal

A programming error on the sign-in success path stops being discarded: the gate's
`.catch` re-raises anything `app/api.js` did not produce, its trailing handler becomes
`.finally` so the submit control comes back on every path including that one, and the
error reaches the harness's rejection hook carrying its own stack instead of vanishing.
Every one of api.js's six kinds keeps the outcome it has today, a genuine offline
sign-in included, and nothing a person sees changes.

---

## Acceptance criteria

Numbered for reference. Criteria marked **NOT RUN** are defined in
[The browser gap](#the-browser-gap) and **no verdict on this task may depend on them**.

### The recogniser

1. `app/app.js` defines `apiRaised(error)` once, in the preamble above the first region
   marker at `app/app.js:147`. Grep of `function apiRaised\(` across `app/` returns 1.
2. It decides by `instanceof` against the client's exported constructor. Grep of
   `instanceof` across `app/` returns exactly **1** occurrence, inside that function.
   Measured on this worktree before the change: **0** occurrences.
3. It returns false rather than throwing when the client has not loaded. `api` is null
   until `client.onload` runs (`app/app.js:31, 1535-1544`), and a predicate that throws
   while deciding what to do with an error is a second copy of this bug.
4. It reads no status, no code and no `kind`. `test_only_the_api_client_interprets_a_status
   in tests/test_shell_behaviour.py` (`tests/test_shell_behaviour.py:974-997`) stays
   green unmodified, and so does `test_only_the_api_client_calls_the_back_end in
   tests/test_web_shell.py`.
5. `addCurtained` (`app/app.js:997-1016`) is unchanged and is **not** rewritten to call
   the new predicate. The add screen's two chains already propagate, because each clears
   its in-flight state as the first statement inside both handlers
   (`app/app.js:1122, 1126, 1150, 1180`), so touching it would be a refactor with no
   defect behind it. This task adds exactly one caller.

### The gate's chain

6. The `.catch` at `app/app.js:1450` re-raises an unrecognised reason as its first act,
   before any `kind` is read.
7. The `!error ||` half of `app/app.js:1451` is gone: a falsy reason is unrecognised and
   re-raised rather than swallowed. Grep of `!error` across `app/` returns exactly
   **1** occurrence afterwards, at `app/app.js:1015` in `addCurtained`. Measured before
   the change: **2**.
8. The two-way `kind` test that decides what the gate draws is kept, still asks only
   about `'signed-out'` and `'refused'`, and still returns early for the other four
   kinds. What a person sees on every recognised path is byte-identical to master.
9. The chain's trailing handler becomes `.finally`, so `gateSubmit.disabled = false`
   runs on every path including the re-raise. Grep of `\.finally\(` across `app/`
   returns exactly **2** occurrences afterwards: `app/app.js:668`, which is #72's, and
   the gate's. Measured before the change: **1**.
10. A throw inside the `.catch` handler's own body, for instance while writing
    `#gate-error`, now also re-enables the submit control, where before it did not.
    This follows from criterion 9 and is deliberately **not** asserted separately: it
    would need a third substitution and a third run to observe, and it is the same
    property criterion 9 pins. Stated here so the omission reads as a decision rather
    than a gap.

### What must not change

11. `a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone`
    (`tests/shell_harness.mjs:1871-1887`) passes with an empty failures list, in the
    unsubstituted run and in the substituted one. **This is the criterion that makes the
    naive fix wrong**: a genuine offline sign-in arrives on the same path, it is an
    `ApiError` of kind `offline`, and it must stay a silent early return with the
    offline notice already up, never an unhandled rejection.
12. `a_refused_sign_in_tells_the_person_why` (`tests/shell_harness.mjs:1828`) and
    `a_refused_sign_in_with_an_unreadable_body_still_says_something`
    (`tests/shell_harness.mjs:1847`) pass unchanged: `signed-out` still writes
    `error.say` on the gate, and a refusal whose body carried nothing still gets the
    gate's own `'That did not work.'`
13. `a_rate_limited_sign_in_reads_on_the_gate_with_no_curtain_over_it`
    (`tests/shell_harness.mjs:2151`) and
    `creating_an_account_that_already_exists_says_so_on_the_gate`
    (`tests/shell_harness.mjs:2123`) pass unchanged: `refused` still reports on the gate
    with no curtain over it.
14. **Three of the six kinds are not reachable through the gate's chain in the current
    scenario set, and that is recorded rather than asserted.** Measured:
    `sign-in-not-kept` is not, because a 401 answering `POST /session` is always
    `signed-out` (`app/api.js:142, 255`) and the not-kept scenario's 401 answers
    `GET /session` inside `refresh()`, whose own rejection handler swallows it
    (`app/app.js:1425-1428`), so the gate's `.catch` never sees it; `not-linked` is not,
    because no scenario answers a sign-in with a 403 `member_not_linked`; `unavailable`
    is not, because `a_server_error_prints_what_the_server_said_and_never_the_gate`
    (`tests/shell_harness.mjs:1660-1668`) answers `GET /session` on boot. All three
    reach the same early-return arm through the same one test as `offline`, so the change
    cannot treat them differently. No scenario is added for them; see
    [Out of scope](#out-of-scope).
15. The unsubstituted harness run exits 0 with all 160 scenarios green, so
    `test_the_harness_exits_zero_against_the_shipped_files in
    tests/test_shell_behaviour.py` passes unmodified.
16. `MUTANT_C` (`tests/test_shell_behaviour.py:261-265`) is still killed and
    `test_mutant_c_a_classifier_that_drops_what_it_does_not_recognise_is_killed in
    tests/test_shell_behaviour.py` is unchanged. An `ApiError` whose `kind` is `''` is
    recognised, takes the early-return arm, and does not become an unhandled rejection,
    so that mutant's verdict is still a missing `#gate-error` and not a crash.

### The symptom, and the instrument that can see it

17. The observable thing that appears after the fix is **one failure line recorded
    against the running scenario**, written by `escaped()`
    (`tests/shell_harness.mjs:9069-9076`) from the hook at
    `tests/shell_harness.mjs:9102`, of the form
    `unhandled rejection: TypeError: ...` followed by the thrown error's stack. It
    carries the error's type and the line it was thrown from, which is what makes it a
    diagnosis rather than a symptom.
18. **The existing in-flight invariant cannot see this class, and it is not the
    instrument.** It reads the `hidden` flag of two elements, `#feed-loading` and
    `#balances-busy` (`tests/shell_harness.mjs:1001-1008`), and after the fix the gate
    leaves the DOM valid on every path, so nothing an id-and-`hidden` invariant reads
    changes. The instrument is the rejection hook of criterion 17. This is written down
    because "the suite covers this" would otherwise be assumed of the invariant.
19. **The invariant gains a second clause, which catches the opposite bug.** `finish()`
    fails any scenario that returns with `#gate-submit` disabled, with its own message
    naming `#gate-submit`, so a gate left permanently disabled is caught across all 160
    scenarios and every future one instead of only where somebody asserted the button.
    It reads a `disabled` property rather than a `hidden` one, so it is a second clause
    beside the two-id loop and not a third id in it. Measured expectation against
    unmodified `app/`: **0** scenarios red on it, because the trailing `.then`
    re-enables on every path today. If the run reds any, name them and stop; do not
    weaken the clause.
20. **Recorded positive control for criterion 19.** With the substitution of criterion 21
    applied and the trailing handler left as `.then`, which is the naive fix the issue
    warns is worse than the bug, the clause fires and the output names `#gate-submit`.
    Paste that output into the mutation record. Without it, criterion 19 is a check
    nobody has seen fail.

### The reproduction

21. A new module-level substitution in `tests/test_shell_behaviour.py`, **one line**,
    anchored on `        return refresh();` (`app/app.js:1448`; measured, `return
    refresh();` occurs exactly **once** across `app/`). Its replacement appends a
    `.then` to the promise the gate's fulfilled handler returns and throws a plain
    `TypeError` inside it by dereferencing a missing key on a plain JavaScript object.
    The recommended form, which is #72's `THE_FEED_RENDER_THROW`
    (`tests/test_shell_behaviour.py:871-878`) transplanted:

        return refresh().then(function () { return api.cachedSession().nope.alsoNope; });

    `cachedSession()` (`app/api.js:346-348`) returns the view `signIn` cached
    (`app/api.js:359-369`), which is a plain object, so a missing key on it throws a
    plain `TypeError`; and if the cached view is null on some path that reaches this
    line, it throws a plain `TypeError` there too. Either way no stub guard is involved
    and the shipped chain alone decides what happens next.

22. **Why that anchor and not one inside `showApp()` or `refresh()`.** Three
    requirements, all of them load-bearing:
    - It must throw where **only the gate's chain** decides the fate of the throw.
      `refresh()` is also called bare at `app/app.js:1528`, so a substitution inside
      `refresh()` or `showApp()` would put an `unhandled rejection` line in the report
      before the fix as well, and could prove nothing.
    - It must not reach for a property the stub does not define. `guarded()`
      (`tests/shell_harness.mjs:305-330`) is wrapped round elements, `document`
      (`tests/shell_harness.mjs:660`) and `history`
      (`tests/shell_harness.mjs:775`) and routes a missing property through
      `refusedProperty()` (`tests/shell_harness.mjs:9091-9099`), which records a failure
      line **whatever the app then does with the exception**. `window.SplitwiseApi` is
      not guarded, so a missing key on the session view throws a plain `TypeError` the
      shipped chain alone disposes of. This is #72's criterion 12 in this task's shape.
    - It must throw **after** `refresh()` has settled, so every request the scenario
      declares still goes out and every assertion it makes still holds. That is what
      makes the before-run green, and the before-run being green is the whole
      reproduction.
23. **The before-run, which is the bug stated as a measurement.** The substitution
    applied to `app/app.js` exactly as it ships today, over the whole scenario list
    unfiltered, exits **0** with every scenario green and the string `unhandled
    rejection` appearing **0** times anywhere in the run. Record the exit status and
    that count. A programming error on the sign-in success path, and a green suite.
24. **The after-run.** The same substitution, the same configuration, exit **1**, with
    an `unhandled rejection` line against every scenario that reaches the gate's
    fulfilled handler. Record the complete list as `kills`, **measured over the whole
    list unfiltered rather than predicted**;
    `a_successful_sign_in_keeps_the_screen_the_person_was_on`
    (`tests/shell_harness.mjs:1890`) is in it.
25. **The new pytest test**,
    `test_a_throw_on_the_gates_success_path_arrives_as_an_unhandled_rejection` in
    `tests/test_shell_behaviour.py`, runs the harness with that one substitution and
    asserts, in this order:
    - exit status **exactly 1**, never merely non-zero: a substitution that broke the
      file into a syntax error exits 2 and must not be mistaken for a caught defect;
    - `a_successful_sign_in_keeps_the_screen_the_person_was_on` did not pass, and its
      failures contain `unhandled rejection`, `TypeError`, and `app.js`, which is the
      stack naming the file and the line;
    - the two named controls passed, each with its own assertion and its failures shown
      on failure: `a_refused_sign_in_tells_the_person_why`, where the sign-in is refused
      so the fulfilled handler never runs and the substitution is inert, and
      `a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone`, which is criterion
      11's control;
    - `a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate`
      carries an `unhandled rejection` line and **no** `#gate-submit` line. That
      scenario signs in successfully (`tests/shell_harness.mjs:1924`) so the
      substitution fires in it, and it already asserts `#gate-submit disabled === false`
      at `tests/shell_harness.mjs:1933`. **That is how "the submit button still comes
      back" is checked rather than claimed in prose.**
26. **Do not pin a stack frame name you have not read off the run.** The throw is inside
    an anonymous function, so V8 may name that frame by position alone; #72's record
    shows both shapes, a named frame and a bare `app.js:658:11`
    (`plans/mutations/72-the-feed-swallows-its-own-errors.md:85-87`). Assert `app.js`,
    paste the real line into the record, and pin a frame name only if the run produced
    one.
27. **The assertion is on the failure line, not on redness**, even though redness alone
    would distinguish the two runs here. Unlike #72's case, where the same 14 scenarios
    red either side of the change, the before-run of criterion 23 is entirely green, so
    a redness assertion would bite. It is still wrong: a scenario that reds for an
    unrelated reason would satisfy it, and this test exists to say the hook fired.
28. **No tenth committed mutant.** `MUTANT_A` through `MUTANT_I`
    (`tests/test_shell_behaviour.py:228-371`) each assert that a mutation turns named
    scenarios red. A `MUTANT_J` on this anchor cannot be added in commit 1 at all,
    because before the fix the mutation **survives**, and after the fix it would assert
    a weaker version of what criterion 25 already asserts precisely. State that
    reasoning in the record, and state it as a judgement about duplication rather than
    borrowing #72's reason, which was that a redness check there could not fail.
29. **A second recorded mutation, run once, recorded, and asserted by no test.** The same
    anchor with a replacement that rejects with no reason at all:

        return refresh().then(function () { return Promise.reject(); });

    This is the case the deleted `!error ||` half of `app/app.js:1451` used to swallow.
    Record the exit status and the failure line, expected to read `unhandled rejection:
    undefined`, because `escaped()` stringifies a reason that has no `.stack`
    (`tests/shell_harness.mjs:9070`). It is a second run and a second JSON block: one
    configuration cannot carry two replacements for one anchor, because `readSource`
    (`tests/shell_harness.mjs:9114-9128`) refuses an anchor that does not match exactly
    once and the first replacement consumes it.

### The record

30. `plans/mutations/88-the-sign-in-gate-discards-a-programming-error.md` exists and
    holds both mutations as fenced `json` blocks with exactly the seven keys `id`,
    `file`, `find`, `replace`, `kills`, `survives`, `result`
    (`plans/mutations/README.md:18-31`), every section carrying a block rather than a
    description of one (`test_a_mutation_record_holds_no_prose_only_section in
    tests/test_suite_integrity.py`), plus the before-run and after-run outputs of
    criteria 23, 24 and 20 pasted in. Both `find` values are **one line**: `MUTANT_F`,
    `MUTANT_H` and `MUTANT_I` each record that a multi-line anchor rots on a CRLF
    checkout (`tests/test_shell_behaviour.py:334-338, 363-366`), and this working tree
    is CRLF.
31. Any pytest node id in that record's prose also appears in its `kills` or `survives`.
    A node id cited as a precedent rather than as a claim is written bare, as
    `test_name in tests/test_file.py` (`prose_node_ids` and `stray_node_ids`,
    `tests/test_suite_integrity.py:1705-1739`).

### Guards that must not move

32. `SHELL_DIGEST` at `app/sw.js:35` is updated to the value printed by the failing
    `test_the_recorded_digest_matches_the_files_it_covers in tests/test_web_shell.py`
    (`tests/test_web_shell.py:1055-1061`), taken from that test's output and never
    computed by hand. Its value on this worktree before the change is `'9dd856b33f5b'`.
33. `VERSION` at `app/sw.js:34` still reads `'v4'`. **It is not what you bump.**
    CLAUDE.md is explicit that the pasted digest line is the whole fix and that
    `VERSION` is left for a change to how the worker itself behaves, and
    `tests/test_suite_integrity.py` twice cites
    `plans/tasks/46-shell-precache-digest.md` as the record of what happens when a rule
    about `VERSION` outlives the reader.
34. `git diff master -- app/` touches exactly two files, `app/app.js` and `app/sw.js`,
    and the only change in `app/sw.js` is the `SHELL_DIGEST` string literal.
35. `app/app.js` still contains neither the byte sequence `fetch` nor `/api`.
    `test_the_narrowed_rule_still_bites in tests/test_web_shell.py` asserts both
    (`tests/test_web_shell.py:624-627`), so a comment explaining the new predicate must
    not use the word "fetch" and must not name an API path. This is the easiest way to
    red the suite while writing this fix, and the comment this fix wants to write is
    exactly the one that reaches for that word.
36. `API_SURFACE` (`tests/test_web_shell.py:1328-1348`) is unchanged and still holds
    **16** entries, `ApiError` among them. Counted by Read of those lines: `ApiError`,
    `onUnauthenticated`, `onNotLinked`, `onOffline`, `session`, `cachedSession`,
    `signUp`, `signIn`, `signOut`, `members`, `expenses`, `addExpense`, `balances`,
    `debt`, `addSettlement`, `decideSettlement`. `app/api.js` is not touched, and the
    new predicate consumes an export that is already declared rather than adding one.
37. `SCENARIOS` (`tests/test_shell_behaviour.py:42-217`) is unchanged and still holds
    **160** names, and Grep of `    name: '` in `tests/shell_harness.mjs` still returns
    **160**, so `test_the_harness_reports_exactly_the_declared_scenarios in
    tests/test_shell_behaviour.py` passes unmodified. This task adds no scenario: the
    only way to provoke an unrecognised error in shipped code is a substitution, and a
    scenario cannot carry one.
38. Neither `CLAUDE.md` nor `README.md` gains or loses a capability bullet. No
    user-visible capability changes. Both documents' two delimited lists are compared
    against the same literals in `tests/test_web_shell.py` (the section starts at
    `tests/test_web_shell.py:1319-1322`, `WORKS_TODAY` at `1355`), by
    `test_both_documents_agree_on_what_works_today in tests/test_web_shell.py` and
    `test_both_documents_agree_on_what_does_not_exist_yet in tests/test_web_shell.py`,
    and on this worktree `What does not exist yet` holds only **Expense correction**
    (`CLAUDE.md:77-78`).
39. `CARRIED_TOTAL` at `tests/test_suite_integrity.py:1118` still reads **107** or less.
    No new `pytest.raises` block is added; if one is, it is anchored and never added to
    the baseline, which may only shrink.
40. The new test function and the new substitution constants are names that do not
    already exist in `tests/test_shell_behaviour.py`. A module-level definition made
    twice deletes the first one silently, and `tests/test_suite_integrity.py` refuses it
    with no allowlist.

### Commit shape

41. Two commits, in this order. **Commit 1** adds the new test, the invariant clause of
    criterion 19 and the mutation record, and changes nothing under `app/`:
    `git diff master -- app/` is empty at that commit, and the new test fails, which is
    the before-run of criterion 23. **Commit 2** makes the change in `app/app.js` and
    the `SHELL_DIGEST` update, after which the new test passes and the unsubstituted run
    exits 0. The reason is the demonstration and not task 9b's rule:
    `plans/tasks/72-the-feed-swallows-its-own-errors.md:371-402` sets out that reasoning
    and retracts the broader reading of 9b.

### NOT RUN

42. **NOT RUN.** In a browser, a programming error on the sign-in success path produces
    an unhandled rejection in the devtools console naming `app.js`, and the person sees
    no change: the submit control is enabled, and whatever the screen was showing when
    the throw happened is still what it shows.
43. **NOT RUN.** Whether a silent sign-in failure is as invisible to a person as it is
    to the suite, which is the issue's own question.

---

## Out of scope

- **Any change to what a person sees.** No new notice paragraph, no message on
  `#gate-error` for a programming error, and no repurposing of an existing paragraph as
  a crash notice. See [What the person sees](#what-the-person-sees-and-why-no-new-copy).
- **A top-level `unhandledrejection` handler in the shell.** #72 forbade adding one so
  that the future design starts from a clean absence rather than from something to undo
  (`plans/tasks/72-the-feed-swallows-its-own-errors.md:428-433`), and this task must not
  add `window.addEventListener('unhandledrejection', ...)` or
  `window.onunhandledrejection` either.
- **Writing to the console from the gate.** A `console.error` in the `.catch` would also
  be caught by the suite, because `finish()` fails any scenario with console output it
  did not declare (`tests/shell_harness.mjs:1046-1049`), and it would be visible in a
  browser. It is refused anyway, for two reasons: it would be a second answer to the
  question #72 has already answered with a re-raise, in the same file, for the same
  class of error; and it would consume the rejection, so the stack would reach the report
  only if the gate composed the line itself, which is prose in `app/app.js` about an
  error `app/app.js` did not classify.
- **Any change to `app/api.js`.** The classification, the six kinds and the three
  handlers are unchanged. Criterion 36 holds trivially.
- **Rewriting `addCurtained`** (`app/app.js:997-1016`) to use the new predicate, or
  changing the add screen, the feed or the balances screen at all. Criterion 5 gives the
  reason. A later task may make `addCurtained` the second caller; this one does not.
- **Adding `#add-submit` or `#add-roster-busy` to the in-flight invariant.** For
  `#add-submit` (`app/app.js:745`) a clause would be inert today: `settled()`
  (`app/app.js:1106-1110`) is the first statement inside both handlers
  (`app/app.js:1122, 1126`), so no throw in either can leave the control disabled.
  `#add-roster-busy` was already routed out of scope by #72 with its own measured limit
  (`plans/tasks/72-the-feed-swallows-its-own-errors.md:311-319`), and that stands.
- **Adding a scenario for the three kinds of criterion 14.** A sign-in answered with a
  500, with a 403 `member_not_linked`, or a sign-up answered with a 401 while armed, are
  three real gaps in the gate's coverage. Each is a new scenario, a new entry in
  `SCENARIOS`, and a change to the count criterion 37 pins, and none of them is this
  issue's subject: they would cover paths this change does not alter. Raise them as one
  issue about the gate's kind coverage and link it from the PR.
- **Re-measuring #37's ten mutations**, and any change to #72's own record. #72 already
  notes that #37 is downstream of it
  (`plans/tasks/72-the-feed-swallows-its-own-errors.md:463-473`); this task changes a
  different chain and does not move that dependency.
- **New dependencies, npm, `package.json`, `node_modules`, a JS test framework or a
  browser driver.** All already forbidden by task 9b
  (`plans/tasks/09b-javascript-test-harness.md:584-592`).

---

## Constraints

- **Files that may change:** `app/app.js` (the new predicate, the `.catch`'s first act,
  and the trailing handler), `app/sw.js` (the `SHELL_DIGEST` literal only),
  `tests/test_shell_behaviour.py` (two substitution constants and one new test),
  `tests/shell_harness.mjs` (the one clause of criterion 19, inside `finish()`), and a
  new `plans/mutations/88-the-sign-in-gate-discards-a-programming-error.md`. Nothing
  else.
- **Editing anything under `app/` means dealing with the shell digest, and `VERSION` is
  not it.** `app/sw.js` records `SHELL_DIGEST`, a digest of the nine shell files, and
  names its cache after `VERSION` and that digest together, so a shipped edit that would
  have sat behind a cache nobody retired is a failing test rather than a silent
  regression. The failing test prints the one line to paste back into `app/sw.js`, and
  **that pasted line is the whole fix**. Do not bump `VERSION`, do not compute the digest
  by hand, and do not reach for the local workaround of bumping `VERSION` to see an edit
  in a browser: that is a local convenience, not a commit. Criteria 32 and 33.
- **The trailing `.then` cannot be edited by a single-line anchor.**
  `      .then(function () {`, with six spaces, matches **twice** in `app/app.js`, at
  1445 and 1472; with ten spaces it matches once, at 1440. So a hand edit must carry
  surrounding context. `        gateSubmit.disabled = false;` matches exactly once
  (`app/app.js:1473`), and so does
  `        if (!error || (error.kind !== 'signed-out' && error.kind !== 'refused')) {`
  (`app/app.js:1451`).
- **Every harness substitution anchor in this task is one line**, for the CRLF reason at
  criterion 30. The one-line rule is about substitutions, which match by `split(find)`
  on the file's text; a hand edit through an editor is a different mechanism and the
  bullet above governs it.
- **`uv run python -m pytest`, never `uv run pytest`**, which fails on this machine with
  an access-denied spawn error (CLAUDE.md). Set `PYTHONDONTWRITEBYTECODE=1` on every run
  (`plans/mutations/README.md:75-85`), even though the JavaScript harness is immune to
  the bytecode trap, because the Python half of these runs is not.
- **Do not run the full suite in one command.** Chunk by module and take counts from
  `--collect-only -q`. The modules this task can affect are
  `tests/test_shell_behaviour.py`, `tests/test_web_shell.py` and
  `tests/test_suite_integrity.py`; run those three and no more unless one of them points
  elsewhere.
- **The harness can also be driven directly**, which is how the before-run and after-run
  of criteria 23 and 24 are cheapest to take:
  `node tests/shell_harness.mjs < config.json`, where the config is
  `{"substitutions": [ ... ]}` holding the block from the record
  (`plans/mutations/README.md:42-47` explains why a record pastes straight in).
- **A rejection that arrives after its scenario has finished is a harness error, not a
  recorded failure.** `main()` sets `running = null` at `tests/shell_harness.mjs:9190`
  before pushing the result, and `escaped()` with no scenario running writes
  `harness error:` to stderr and exits 2 (`tests/shell_harness.mjs:9071-9074`). If the
  after-run exits 2 with no JSON on stdout, that is what happened, and the fix is a
  `settle()` after the provocation rather than a change to the shipped file. It should
  not happen: `settle()` hops through `setImmediate` twice
  (`tests/shell_harness.mjs:811-832`), which returns to the event loop and lets Node
  emit the rejection while the scenario is still running, which is how #72's line lands
  on its own scenario.
- **`passed` is a snapshot and `failures` is live.** `main()` computes `passed` at
  `tests/shell_harness.mjs:9191` and pushes the failures array by reference at
  `9192-9198`, and the JSON is written at `9202`. A line appended after the snapshot
  would show in `failures` with `passed` still true. Assert on the failure text, as
  criterion 25 does, and do not infer redness from it.
- **No scenario may read the source text of `app/app.js` or `app/api.js` and assert on
  it** (`plans/tasks/09b-javascript-test-harness.md:394-398`). Criteria 1, 2, 7 and 9
  are greps a reviewer or a `tests/test_web_shell.py`-style structural test performs,
  never a harness scenario.
- **`node` 20 or later on `PATH`** is a test-time requirement, and a missing `node`
  fails the suite loudly rather than skipping (CLAUDE.md).
- **CI runs `ubuntu-latest` and `windows-latest`** and both must be green. A pull request
  whose base has moved has to be brought up to date and re-run, because the merge commit
  is where a stale shell digest surfaces (CLAUDE.md).
- **Narrate one line before every command.**

---

## What the person sees, and why no new copy

**Nothing changes, and that is the decision.** The issue asks whether a programming
error during sign-in should become a generic failure message, and notes that `#notice`
has four paragraphs and none of them says the app is broken. Measured: four, at
`app/app.js:1377-1381`, listed as `NOTICES` at `tests/shell_harness.mjs:1309`, with an
invariant at `tests/shell_harness.mjs:968-981` that fails any scenario where the curtain
is up without exactly one of them showing.

Three answers were available and two are refused here:

- **Write the gate's last resort, `'That did not work.'`, on the gate.** Refused. It is
  false: on this path the server accepted the sign-in. And it would drag the gate back
  over an app frame or a notice that is already up, which is the exact hazard the
  existing comment at `app/app.js:1452-1455` names.
- **Add a fifth notice paragraph.** Refused here, and it is a product decision rather
  than a refactor: new copy, a change to `NOTICES`, a change to that invariant, and a
  judgement about whether a programming error should cover the whole frame and hide a
  ledger that may still be perfectly readable. #72 reached the same conclusion for the
  feed (`plans/tasks/72-the-feed-swallows-its-own-errors.md:406-433`).
- **Change nothing visible.** Chosen. The submit control comes back, whatever the screen
  was showing stays, and the error escapes to the console. In production this change is
  neutral for a person and positive for a developer with devtools open; its real value
  is in the harness, where the hook turns the rejection into a recorded failure with a
  stack.

So the honest account for the PR is: **this is diagnosis, not correctness.** Anybody
writing that it repairs what a person sees is claiming something false, and that is the
sentence #72's PR was warned about too.

Raise the fifth-paragraph question as its own issue, with the invariant and the copy
named, and link it from this PR. Do not fold it in.

---

## The browser gap

Nothing in this project has ever been verified in a browser, and this change is about
what a browser does with an error. The harness runs under `node:vm` against a stubbed
DOM and a stubbed `fetch`, and task 9b's `What stays browser-only` section
(`plans/tasks/09b-javascript-test-harness.md:317-322`) states that the harness must not
pretend to cover browser behaviour and that no scenario may be named as if it did.

Criteria 42 and 43 are therefore **NOT RUN**. They are neither failures nor passes.
**Recording an unrun browser check as a pass is a FAIL of this task**, and no verdict may
depend on either. Route both to issue **#80**, which already carries the browser
questions, adding:

- Open the app in a browser, provoke a throw on the sign-in success path, and confirm the
  devtools console shows an unhandled rejection naming `app.js`, that the submit control
  is enabled, and that the visible screen is unchanged from master's behaviour.
- Confirm that a person cannot tell a silent sign-in failure from a successful one, which
  is the question the issue raises and the suite cannot answer.

---

## Size estimate

**Small: three or four shipped lines plus one new function, roughly 120 lines of test and
record, six files.**

The estimate is a **read, not a run**. It is built from these reads:

- `app/app.js`: one new function in the preamble, the first statement of the `.catch`,
  the `!error ||` half of `app/app.js:1451` removed, and `.then` to `.finally` at
  `app/app.js:1472`.
- `app/sw.js`: one line, the `SHELL_DIGEST` literal at `app/sw.js:35`.
- `tests/shell_harness.mjs`: one clause inside `finish()`, sized against the two-id loop
  it sits beside (`tests/shell_harness.mjs:1001-1008`, eight lines including its
  message).
- `tests/test_shell_behaviour.py`: two substitution dicts and one test function. Sized
  against #72's, which is 8 lines of constant with 10 lines of comment
  (`tests/test_shell_behaviour.py:861-878`) and a 43-line test
  (`886-928`); budget 70 to 90 lines including the reasoning criteria 26, 27 and 28
  require.
- `plans/mutations/88-the-sign-in-gate-discards-a-programming-error.md`: one new file,
  two seven-key JSON blocks plus the three recorded outputs of criteria 20, 23 and 24;
  `plans/mutations/72-the-feed-swallows-its-own-errors.md` is the format precedent.
- This task file.

The cost is not in the diff. It is in criteria 23 and 24: producing a **green** run that
contains a programming error, and then the same run red with one line in it, is the part
that takes the time, and it is the part that makes the task worth doing at all.
