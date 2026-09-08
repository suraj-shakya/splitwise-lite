# Task 82: the unreachability claim gets checked

GitHub issue #82, "Fifty rows claim no request can reach them, and nothing checks that
claim".

`tests/test_error_messages.py` declares every refusal message raised under
`src/splitwise_lite/` and checks that declaration as a two-way set equality against an
`ast` walk of the raise sites. That half fails closed. Of its rows, some are driven by a
request and asserted to put no store-held identifier in a 4xx body, and the rest carry
the marker `NO_REQUEST_REACHES_IT` with a reason. The marker is a claim about
reachability, and the module's own docstring says so plainly at lines 44 to 46:

> What is **not** covered, stated plainly: a row marked `NO_REQUEST_REACHES_IT` is a
> claim this module records rather than verifies

The falsifying event is a new route reaching an existing raise. The set of raise sites
does not change, no message skeleton changes, the equality still holds, and a message
interpolating a stored value has silently become something a client can be shown.

## How the numbers here were obtained

**No Bash tool was available in the session that produced this spec.** Nothing below was
run under `pytest`, `uv`, `gh` or a shell. Every count is a run of the ripgrep-backed
Grep tool with the pattern quoted beside it, and every other statement is a read of a
file at the path quoted beside it. Anything a run would be needed for is written as a
criterion for the implementer to run and record, never as a result.

Measured in the worktree `splitwise-lite-task-82`, branch `task-82`, over
`tests/test_error_messages.py` **as it stood on 2026-09-07, when this spec was
written**. These are not the live counts; see the note under the table.

| Pattern (ripgrep, over that one file) | Count |
| --- | --- |
| `^    unreachable\(` | 50 |
| `^    Site\(` | 56 |
| `unreachable\(` (unanchored) | 51 |

So: **50 marked rows, 56 driven rows, 106 rows in `FOUR_HUNDRED_SITES`.** The unanchored
count is 51 because it also matches the helper's own `def unreachable(` line at
`tests/test_error_messages.py:494`. The issue's warning about this trap is correct and
the anchored patterns above are the ones to measure with.

> **Superseded 2026-09-08.** Three of those fifty marks turned out to be false and
> those rows are now driven, so the live figures are **47 marked and 59 driven**, still
> 106 rows. The correction section below carries the measurement and the reasoning. The
> table above is kept because it is the reading this spec was written against, and it
> is not the current count: quote 47 and 59, measured with the same two patterns.

An independent cross-check, by reading the table rather than by pattern: on 2026-09-07
the marked rows distributed as `accounts.py` 4, `balances.py` 1, `groups.py` 8,
`money.py` 3, `simplify.py` 1, `split.py` 2, `store.py` 29, `web.py` 2, which sums to 50
and agreed with the anchored count. Two measurements by different means, one answer.

Re-measured 2026-09-08, after the three rows moved: `accounts.py` 4, `balances.py` 1,
`groups.py` 8, `money.py` 3, `simplify.py` 1, `split.py` 2, `store.py` 28, `web.py` 0,
which sums to **47** and agrees with the anchored count of 47. The three that moved are
one in `store.py` and both of `web.py`'s, which is why those two figures are the only
ones that change.

Other reads used below:

- `pyproject.toml` declares one runtime dependency, `flask>=3.0,<4`, and one dev
  dependency, `pytest>=8.0,<10`. **There is no coverage dependency**, and
  `requires-python = ">=3.12"`.
- `tests/test_suite_integrity.py:72` sets `TEST_SOURCES = sorted(TESTS.rglob("*.py"))`,
  derived from the filesystem. Adding a test file therefore needs **no edit** to that
  module, which is what keeps this task clear of PR #70a.
- `web.py` has 11 rows in `_API_ROUTES` (ripgrep `_ApiRoute\(` over
  `src/splitwise_lite/web.py`).
- `tests/conftest.py` does not exist (glob `**/conftest.py` over the worktree found
  nothing).

## Where the issue is wrong, and this is the important part

The issue proposes, verbatim:

> **assert that no line marked `NO_REQUEST_REACHES_IT` is ever executed while serving a
> request**

**That check would go red today, on rows whose marks are correct.** It is retracted
here rather than quietly reshaped, because two definitions of "reached" standing side by
side, one of them superseded and unmarked, is the defect this repo keeps finding.

Several marked rows describe a refusal that is raised inside `src/splitwise_lite/`,
caught inside `src/splitwise_lite/`, and answered with a different exception. Their
reasons say so in as many words. Three of them are executed by requests the suite
already drives, established by reading the source:

1. **`store.py::get_user_by_email::"no user with email "`.** `accounts.sign_up`
   (`src/splitwise_lite/accounts.py:657` to `662`) calls it inside `try` and treats
   `RecordNotFound` as the success path with `except RecordNotFound: pass`. So this
   raise executes on **every successful signup**, which is every `linked_client` and
   `unlinked_client` setup in the module. `accounts.log_in:698` to `702` catches it too,
   which is what the driven `_fail_login` row (`{"email": "nobody@example.com"}`)
   exercises.
2. **`store.py::get_session::"no session with token hash "`.** The driven row
   `Drive("GET", SESSION, "session_invalid", who="stale")` sets the cookie
   `this-token-names-no-live-session`. That string is 32 characters drawn from the
   alphabet in `accounts.py:225` to `227` and the ceiling in `accounts.py:221` is 4096,
   so `_is_token_shaped` returns true, `accounts.authenticate:734` calls
   `store.get_session`, and the raise executes. `accounts.authenticate:735` to `736`
   catches it and raises `SessionInvalid` instead.
3. **`store.py::get_member_for_user::"no member of group  is linked to user "`.** The
   driven row `Drive("GET", "/api/members", "member_not_linked", who="unlinked")`
   reaches `groups.acting_member:773`, whose `except RecordNotFound` at `groups.py:774`
   raises `MemberNotLinked` instead.

Every one of those three marks is right, and each is right for the reason its own text
gives. What is wrong is the predicate. **Execution is not the harm.** The harm, and the
premise two screens in `app/app.js` are built on, is a message with a stored value in it
**being shown to a client**. A refusal that is raised and then swallowed inside the
package never becomes a body and never reaches anybody.

So the predicate this task adopts is escape, not execution:

> A marked row is **reached by a request** when the exception raised at one of that
> row's raise sites is the exception `web._handle_error` turns into the response.

This is narrower than the issue's wording, it is the property that actually matters, and
it needs no allowlist: the three rows above are excluded by construction rather than by
an exemption somebody has to maintain.

## What "while serving a request" means, exactly

The issue is right that this is the criterion most likely to be got wrong, and right
that a check which goes green because some unit test happened to execute the line is
worthless. The escape predicate answers that worry structurally rather than by scoping.

`web._handle_error` runs only inside a WSGI call. A unit test in `tests/test_store.py`
that calls `store.get_expense("nope")` and asserts it raises can never route through it.
There is no window to open and close, no thread to bind, no tracer whose installation
could be mistimed, and no boundary a reader has to trust somebody drew correctly.

**A reader tells whether a given execution counts by asking two questions:**

1. Did the exception pass through `web._handle_error`? If not, it does not count.
   `web._handle_error` is registered in `create_app` at `src/splitwise_lite/web.py:2575`
   as the handler for `Exception`, so every exception raised in `before_request`, in a
   view, or in `after_request` reaches it, and nothing else does.
2. Is the raise site the **deepest** frame of that exception's own traceback? If the
   exception was caught inside `src/splitwise_lite/` and a different one was raised, the
   deepest frame belongs to the second raise, and the first does not count. The `cause`
   and `context` chains are not consulted, which is exactly what excludes the three rows
   above.

The hook is complete, which is a fact and not an assumption: ripgrep for `_error_body\(`
over `src/splitwise_lite/web.py` finds the definition at line 778 and three calls, at
lines 2704, 2723 and 2725, all three inside `_handle_error`, which begins at line 2673.
**Every error body this application sends is composed there, from an exception.** A
criterion below pins that, because a second error-body path is the one change that would
make the observer blind while leaving it green.

## The dependency decision: nothing is added

**No new dependency.** Not `coverage`, and no hand-rolled tracer either.

The argument is not that a hand-rolled tracer would be cheap. This repo has a strong
record of instruments that could not fail, and "we would write our own" is how several
of them started. The argument is that **both tracers answer the wrong question.** Line
execution is the predicate retracted above. A coverage-based check, correctly scoped and
perfectly implemented, would report the three rows in the previous section as reached
and would need three or more hand-written exemptions on day one, growing by one every
time somebody adds a `try` in the package. That is per-row maintenance and an allowlist,
which is precisely what `tests/test_error_messages.py`'s docstring is proud of not
having ("the driven half needs no allowlist, no exemption set and no marker comment.
There is nothing in it to rot", lines 42 to 44). A dependency that buys an allowlist is
a bad trade at any price.

Failure modes, stated for each option so the choice is auditable:

- **`coverage` as a dev group entry.** Fails by answering a different question, as
  above. Secondary costs: `pyproject.toml` and `uv.lock` both move, both CI legs install
  it, and scoping measurement to requests needs either dynamic contexts or a
  `start()`/`stop()` pair per request, neither of which is the well-trodden part of that
  library. Its engine is well tested; the part most likely to be wrong here is the
  scoping and the line-to-row mapping, and the dependency does not supply either.
- **`sys.settrace` or `sys.monitoring` in a fixture.** Same wrong predicate, plus an
  instrument that would itself need proving, plus line-tracing overhead across a suite
  the issue says already runs close to the ten-minute watchdog under contention. Its
  characteristic silent failure is a filename comparison that never matches, on a
  Windows path or a resolved symlink, after which every marked row looks unreached and
  the check is green forever.
- **A static call graph from `_API_ROUTES` into the package.** Sound in one direction
  only. Reading the 50 reasons, roughly a third are of the form "no route calls this
  function", which a call graph could settle, and the rest are of the form "the function
  is called but this branch cannot be taken", where a call graph says "reachable" and is
  simply wrong. It would red most of the correctly marked rows.
- **The chosen mechanism, a wrapper around `web._handle_error` reading
  `error.__traceback__`.** Its characteristic silent failure is that the wrapper is not
  installed, or is installed after an app was built, or Flask stops routing through the
  registered handler. In every one of those cases it records nothing and passes
  vacuously. That is the failure this repo keeps shipping, so it gets an always-on guard
  of its own, criterion group C, which reds when the observation set is empty or does
  not match the driven rows. The guard is not optional and is not a suggestion.

## Where the check lives

Two files, neither of them one PR #70a touches:

- **`tests/conftest.py`**, new. Holds the session-scoped installer and the per-test
  guard. It has to be a conftest, because the wrapper must be in place before the first
  test builds an app and the assertion must run after every test in the suite.
  `tests/test_end_to_end.py:11` to `15` records this repo's reason for not introducing a
  conftest, and that reason is about sharing fixture scaffolding between two modules,
  which this is not. Say so in the docstring rather than leaving a reader to wonder.
- **`tests/test_error_messages.py`**, extended. Owns the table, so it owns the raise-site
  index and the tests that prove the observer works.

## Relationship to work in flight

- **PR #70a** touches `tests/test_suite_integrity.py` and `.claude/rules/testing.md`.
  Neither is edited by this task and no change to either is proposed here.
- **Issue #79** concerns two marked rows carrying values that should not be shown. Both
  stay marked, and this task neither rewords nor drives them. What changes is that they
  move from trusted-on-reading to policed: if a future route ever makes either escape as
  a response, this check reds instead of nothing happening. #79 is not absorbed and is
  not closed by this task.
- **Issue #70** concerns substring assertions with a superstring hazard. Different
  defect, same family. Untouched.

## Correction, 2026-09-08: three of the fifty marks were false

The guard this task builds was run against the suite, chunked by module. It reached
three rows marked `NO_REQUEST_REACHES_IT`. Measured with
`PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_web_api.py -q`, which
reported `493 passed, 4 errors`, those four being teardown failures of the guard over
three distinct rows:

| row | raised at | how it was answered |
| --- | --- | --- |
| `store.py::_require_name::" must not be blank"` | `src/splitwise_lite/store.py:264` | 400 `User display_name must not be blank`, to a plain `POST /api/signup` carrying a blank `display_name` |
| `web.py::_signup::"an account already exists for "` | `src/splitwise_lite/web.py:1347` | 409, with `accounts.sign_up` stubbed to raise `DuplicateRecord` |
| `web.py::_decide_settlement::"there is more than one payment ..."` | `src/splitwise_lite/web.py:2064` | 409, with a second unanswered claim written straight through the store |

**All three marks are false, and the reasoning matters more than the verdict.**
`NO_REQUEST_REACHES_IT` claims that no client can ever be shown that message, which is
what would make it safe for the message to carry a stored value. A measurement showing
that, given a state, a request does produce that response falsifies exactly that claim.
How hard the state is to reach is not what the marker asserts. Row 3 makes it sharpest:
a second unanswered claim for one ordered pair is what `web._SETTLEMENT_LOCK` exists to
prevent, and that lock is honestly scoped to one process, so the state is the one the
defensive raise exists for rather than an artefact of a test. A mark claiming nothing
reaches it is the wrong description of a guard that exists because something might.

**None of the three leaks an identifier.** All three now pass the driven half's
assertion that no identifier the store holds appears in the body. Nothing shipped was
ever wrong: the defect was in the description, not in the behaviour.

**Better reasons than the ones first recorded, found in review and verified here.** Row
2 needs no second process at all. `scripts/serve.py:127` runs `app.run(threaded=True)`,
and `web._signup` takes no lock around `accounts.sign_up`, whose read at
`src/splitwise_lite/accounts.py:658` and write at `src/splitwise_lite/accounts.py:664`
are six lines apart, so two threads in the one process the dev server runs can
interleave between them. That the omission is deliberate elsewhere is visible in the
same file: `web._SETTLEMENT_LOCK` is defined at `src/splitwise_lite/web.py:1767` and
taken on the settlement paths at 1924 and 2021, and the signup path takes nothing. Row
3 is settled by the package's own comment at `src/splitwise_lite/web.py:2060`, which
says in as many words that the raise is "Unreachable in one process" and exists for two.
Both reasons are stronger than the ones recorded when the rows were moved, because each
is a property of the shipped product rather than of a test.

### What is retracted

> **F2.** In the shipped diff, no row of `FOUR_HUNDRED_SITES` changes its `drive`,
> `reason` or `skeleton`. The anchored counts stay at 50 marked and 56 driven, measurable
> with the two patterns in the table at the top of this file.

and, from **Out of scope**:

> **Driving any currently marked row.** No row moves from marked to driven in the
> shipped diff. If the check reveals that one is reachable, that is a finding to report,
> and fixing it is its own task.

Both were written before anybody knew these three rows existed. Together with D1 and D4
they left no permitted route to a green branch: the guard must red on a false mark, no
skip, no xfail and no allowlist is available, and the rows could not be corrected. They
are withdrawn **for exactly these three rows** and for nothing else.

**What replaces them.** No row of `FOUR_HUNDRED_SITES` changes its `drive`, `reason` or
`skeleton` except the three named above, each of which moves from `unreachable(...)` to
a `Drive`. The anchored counts become **47 marked and 59 driven**, still 106 rows,
measured with the same two patterns over `tests/test_error_messages.py`:
`grep -c '^    unreachable('` reports 47, and `grep -c '^    Site('` reports 59.

D1 and D4 are unchanged. That the guard reds on a false mark is shown by a recorded
mutation in `plans/mutations/82-the-unreachability-claim.md`, not by leaving a real red
in the branch: that is the difference between a check proved to work and a branch nobody
can merge.

### Why `Drive.setup`'s vocabulary grew

`Drive` could express who makes a request, what it carries, and what state a sequence of
earlier requests leaves behind. It could express neither state rows 2 and 3 need,
because neither is reachable by any sequence of requests in one process. Its four values
were asserted in one place; that assertion is now made against a named `SETUPS` tuple
carrying six. The two new ones:

- `two_pending`, a second unanswered claim for one ordered pair, written through the
  store because task 14's 409 refuses the second one through the endpoint.
- `racing_signup`, `accounts.sign_up` raising `DuplicateRecord`, installed only for the
  duration of the one request, because what it stands in for is a second process landing
  between the check and the write.

The vocabulary stays closed: a value not in `SETUPS` is refused in `drive`, and the
refusal is what keeps it a vocabulary rather than a free string.

## Goal

The fifty rows of `FOUR_HUNDRED_SITES` marked `NO_REQUEST_REACHES_IT` stop being a claim
the suite records and become one it checks: if any request any test in this suite makes
turns one of those raise sites into the response a client receives, a test goes red and
names the row, the raise site, and the test that drove it. It is done with no new
dependency, no allowlist, no per-row exemption and no marker beyond the one already
there.

## Acceptance criteria

### A. The definition is written down once, where it is implemented

- A1. `tests/conftest.py`'s module docstring states the predicate in one sentence: a
  marked row is reached by a request when the exception raised at one of that row's
  raise sites is the exception `web._handle_error` turns into the response.
- A2. It states the negative half in the same place: executing a marked raise and being
  caught inside `src/splitwise_lite/` is not reaching, and the `cause` and `context`
  chains of an exception are not consulted.
- A3. It names, with a file and line for each, the marked rows known to execute without
  escaping, so the next reader does not rediscover them. At least the three established
  above are named: `store.get_user_by_email` caught at `accounts.py:659` and
  `accounts.py:701`, `store.get_session` caught at `accounts.py:735`,
  `store.get_member_for_user` caught at `groups.py:774`. Each is checkable by opening the
  line named.
- A4. In the code, the predicate is stated in exactly one place, the docstring A1 names.
  No test docstring and no comment states a second, differing version of it. A test may
  refer to it by pointing at `tests/conftest.py`. This spec states it too, which is where
  a decision and its argument belong; the constraint is on the code, so that a reader who
  finds two versions in the suite knows one of them is a bug.

### B. The observer

- B1. A session-scoped autouse fixture in `tests/conftest.py` replaces
  `splitwise_lite.web._handle_error` with a wrapper before the first test runs, and
  restores the original at session end. After the session, `web._handle_error` is the
  same object it was before.
- B2. The wrapper delegates to the original and returns its response unchanged. No
  status, header, `Set-Cookie` or body byte differs from an unwrapped run. The evidence
  is the rest of the suite staying green, module by module.
- B3. The wrapper records and does not raise. A failure in its own bookkeeping is
  recorded as a violation carrying its own message, never propagated into the response,
  so a bug in the observer cannot change what the application under test returns.
- B4. A raise-site index maps `(absolute file path, line number)` to the same `Key` the
  existing `four_hundred_raise_sites()` walk produces. It is built from one walk, not a
  second one: the existing walk is extended to carry `node.lineno` through
  `node.end_lineno`, and both the equality test and the index read the same result.
- B5. Every line in a raise statement's span maps to that statement's key, so a `raise`
  spread over several lines is found whichever line of it the traceback reports.
- B6. Three raise statements that share a key, which is what `accounts.authenticate`'s
  `SessionInvalid` refusals are, contribute three spans mapping to that one key. No
  special case in the row table.
- B7. A row whose skeleton is `None`, which is `store._require_free` today, is indexed by
  line span like any other and needs no special case, because the index is keyed by
  position rather than by message.
- B8. A `(file, line)` with no raise site in the index records nothing. An implicit
  `TypeError`, a werkzeug `HTTPException`, and any raise outside
  `src/splitwise_lite/` are all silently ignored.
- B9. Only the deepest frame of `error.__traceback__` is consulted.
- B10. When one test reaches the same marked row from several requests, the row is
  reported once, with the method and path of the first request that did it, so a failure
  is legible rather than a wall of repeats.

### C. The observer is proved to work, on every run

- C1. A test in `tests/test_error_messages.py` asserts that for **each driven row**, the
  exception behind that row's 4xx response was raised at the site that row declares. The
  recorded observations are cleared immediately before the row's own request, so
  exceptions raised by its setup requests, which `spend_the_login_budget`,
  `mark_one_payment` and `answer_one_payment` all produce, are not attributed to it.
- C2. That test asserts the observation set is non-empty before comparing it, following
  `assert walked, "the ast walk found no 4xx raise site at all, so this checks nothing"`
  at `tests/test_error_messages.py:1810`. An observer that recorded nothing reds here
  rather than passing over an empty set.
- C3. C1 is a new guarantee and is stated as one: today a driven row asserts the error
  `code` and the absence of identifiers, and nothing asserts that the response came from
  the site the row names. Several rows share a `code`, `malformed_request` most of all,
  so this distinguishes rows that were previously indistinguishable. It also separates
  the two `authentication_failed` rows, `accounts._fail_login` and `accounts.log_in`,
  which today no test tells apart.
- C4. If any driven row turns out to answer from a site other than the one it declares,
  the implementer records which row, which site and why, as a dated correction note in
  this file, and does not delete or weaken C1 to accommodate it.
- C5. A test asserts, by walking `src/splitwise_lite/web.py` with `ast`, that every call
  to `_error_body` is lexically inside `_handle_error`. Today that is three calls at
  lines 2704, 2723 and 2725 against a definition at line 778. This test opens `web.py`
  itself rather than asserting over an imported symbol, so it is a check about that
  module. A second error-body path would make the observer blind, and this is what makes
  that a red test rather than a silent hole.

### D. The per-test guard

- D1. A function-scoped autouse fixture in `tests/conftest.py` asserts, after every test
  in the suite, that no marked row was reached during that test.
- D2. Its failure message names the row's `Key`, the raise site's file and line, the
  request method and path, the response status, and the response message. A reader can
  act on it without rerunning anything.
- D3. The failure is attributed to the test that drove the request. There is no
  session-end summary and no separate reporting test.
- D4. The guard introduces no `skip` and no `xfail` anywhere, under any condition,
  including when the observer is not installed.
- D5. A partial run of the suite observes fewer requests than a full run. The docstring
  says so and states the consequence in the narrow form that is true: a partial run can
  produce a false pass and can never produce a false failure.
- D6. The reach of the guard is stated honestly and once: it covers requests this suite
  actually makes, which includes the route surface driven by `tests/test_web_api.py`. It
  is not a proof of unreachability and nothing in the code or the documents calls it one.

### E. The positive control, run and recorded

- E1. `plans/mutations/82-the-unreachability-claim.md` exists and holds records in the
  seven-key JSON format `plans/mutations/README.md` specifies, so
  `tests/test_suite_integrity.py`'s machine-readability checks pass over it.
- E2. One record converts a driven row of `FOUR_HUNDRED_SITES` into an `unreachable(...)`
  row with a reason of at least `MIN_REASON` characters, which is a line a request
  demonstrably does reach. `result` is `"killed"`. This is the criterion the issue asked
  for as a criterion and not a suggestion: without it this is another check nobody has
  seen fail.
- E3. One record disables the observer's recording, for instance by making the wrapper
  record nothing. The always-on proof in group C must red. `result` is `"killed"`. This
  is what stops the observer being switched off silently.
- E4. At least one record is a named control that must **survive**, listed in
  `survives`, so the new check is shown not to red at everything. Reword a marked row's
  `reason` text, which changes no behaviour.
- E5. `kills` and `survives` hold **pytest node ids**, never `name: count`.
- E6. Every `find` string is verified to match **exactly once** in the target file before
  the run, using the assertion in the recipe at `plans/mutations/README.md:56` to `65`.
  A multi-line anchor is checked against this tree's line endings before it is recorded.
- E7. The working tree is committed before any mutation is applied. Reverting is
  `git checkout --` against the single named file, and nothing else.
- E8. Every mutation run sets `PYTHONDONTWRITEBYTECODE=1`.
- E9. Each run records the **whole-module unfiltered** pass and fail figures for the
  module it ran, and names the quantity those figures count. The suite is not run whole;
  runs are chunked by module and any collected count comes from `--collect-only -q`.

### F. Nothing else moves

- F1. `tests/test_suite_integrity.py` is not edited, and neither is
  `.claude/rules/testing.md`. Both are PR #70a's.
- F2. **Superseded by the correction dated 2026-09-08 above,** which quotes the
  withdrawn wording. In the shipped diff, no row of `FOUR_HUNDRED_SITES` changes its
  `drive`, `reason` or `skeleton` except the three the guard found to be falsely marked,
  each of which moves from `unreachable(...)` to a `Drive`. The anchored counts become 47
  marked and 59 driven, still 106 rows, measurable with the two patterns in the table at
  the top of this file.
- F3. No file under `src/splitwise_lite/` changes. The observer patches at run time from
  the test side and the package is untouched.
- F4. No file under `app/` changes, so `app/sw.js` needs no `SHELL_DIGEST` line and the
  shell digest test does not move.
- F5. `pyproject.toml` and `uv.lock` are byte-identical before and after. No dependency
  is added to either group.
- F6. `CLAUDE.md` and `README.md` are unchanged. This adds no product capability and no
  bullet in either pinned list in `tests/test_web_shell.py` moves.
- F7. The observer performs no line tracing and installs no trace function, so no
  measurable runtime is added. `sys.settrace` and `sys.monitoring` are not called
  anywhere in the diff.
- F8. `tests/conftest.py` and any other new file under `tests/` satisfy
  `tests/test_suite_integrity.py`'s existing duplicate-definition and anchored-pin
  checks, which pick it up automatically through the `rglob` at line 72.

### G. Browser

- G1. No criterion in this task needs a browser. This is server-side test
  infrastructure and every criterion above is decidable from a Python run or from
  reading a file.
- G2. If review adds a criterion that does need a browser, it is marked **NOT RUN**, no
  verdict depends on it, and it is routed to issue #80. Recording an unrun browser check
  as "pass" is a FAIL.

## Out of scope

- **Rewording any message.** Not the two rows in issue #79, not the raw cents in
  `store._require_storable_cents`, not anything else. This task changes what is checked,
  not what is said.
- **Driving any currently marked row. Superseded by the correction dated 2026-09-08
  above,** which quotes the withdrawn wording. No row moves from marked to driven except
  the three this task's own guard found reachable, which are corrected here rather than
  left as a red nobody can merge. A reachable row found after this lands is a finding to
  report and its own task.
- **Verifying the marks that this predicate does not cover.** A row whose raise never
  executes and a row whose raise executes and is swallowed are treated alike here: both
  pass. Proving that a raise cannot execute at all is not attempted.
- **Any change to `src/splitwise_lite/`,** including refactoring `_handle_error` to make
  it easier to observe.
- **Coverage measurement of the package,** as a metric, a CI gate or a report.
- **A route census.** Requiring every row of `_API_ROUTES` to be driven at least once is
  a different and defensible check, and it is not this one.
- **Issues #70, #70a and #79.** Noted above, not absorbed, not closed.
- **Anything under `app/`,** and any change to `CLAUDE.md` or `README.md`.

## Constraints

- **Files this task may create or change:** `tests/conftest.py` (new),
  `tests/test_error_messages.py`, `plans/mutations/82-the-unreachability-claim.md` (new),
  and this file. Nothing else.
- **`tests/test_suite_integrity.py` and `.claude/rules/testing.md` are off limits,** for
  the duration, because PR #70a is open against both.
- **No new dependency,** in either group. The decision and its argument are in the
  section above; a PR that adds one is answering a different task.
- **One walk, not two.** The raise-site index and the existing equality test read the same
  `ast` walk. A second walk over the same files is two things to keep in step.
- **Standard library, `pytest` and the package under test only** in
  `tests/test_error_messages.py`, which is what its docstring at lines 54 to 57 already
  promises. `tests/conftest.py` holds to the same limit.
- **No `skip`, no `xfail`,** to make anything green, per the third bullet of
  `.claude/rules/testing.md`.
- **Anchored measurements only.** Any count written into a docstring, a message or a
  commit names the command that produced it. This project has produced six wrong counts,
  every one from an unanchored or eyeballed measurement.
- **A correction quotes what it retracts,** in this committed file, not in a PR body. The
  retraction of the issue's execution predicate above is the shape to follow.
- **Do not run the full suite.** Chunk by module. Collected counts come from
  `--collect-only -q`. Use `uv run python -m pytest`, never `uv run pytest`, and set
  `PYTHONDONTWRITEBYTECODE=1`.
- **The observer must not be able to pass vacuously.** Group C is not negotiable and is
  not satisfied by a test that only asserts an empty set is empty.

## Size

An estimate, not a measurement, and labelled as one.

The two commands behind it: `tests/test_error_messages.py` is 2012 lines, of which the
table is 106 rows spanning lines 511 to 1633 (read), and there are 9 module-level test
functions in it (ripgrep `^def test_`).

Expected diff:

- `tests/conftest.py`, new, roughly 80 to 120 lines including the docstring that carries
  criteria A1 to A3 and D5 to D6.
- `tests/test_error_messages.py`, roughly 120 to 180 added lines: the line spans threaded
  through the existing walk, the index, and the group C and C5 tests. No line of the
  106-row table changes.
- `plans/mutations/82-the-unreachability-claim.md`, new, three records, roughly 40 lines.

The risk is not the line count. It is group C: an observer that records nothing is the
likely outcome of a rushed implementation, and it looks exactly like success. Budget the
time there, and treat E2 and E3 as the gate on believing any of it.
