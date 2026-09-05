# Task 9b: JavaScript test harness for the shell

**Depends on:** 9a (complete, on `master`)
**Consumed by:** 10 (expense entry), 11 (expense feed), 12 (balances screen), 13 (transfer
drill-down), and every later task that edits `app/`.

Added after the original numbering, as GitHub issue #31. `plans/backlog.md` has no 9b entry
and this task does not add one; the issue is the backlog entry, and this file is the
implementable version.

## Why this task exists

Task 9a shipped `test_a_refused_sign_in_tells_the_person_why` in `tests/test_web_shell.py`.
It slices the body of `submitted()` out of `app/app.js` with two `str.index` calls and
asserts substrings against that slice. The engineer labelled it honestly in its own
docstring as a structural check rather than behavioural coverage.

The task 9a reviewer then proved it gives no signal at all. Two mutants reintroduce the
exact defect it was written to pin while leaving the sliced function byte-identical:

* **`show()` also hides `gateError`.** A one-line tidy of the kind a later screen task
  makes, and it looks like an improvement: every other curtain-switching concern already
  lives in `show()`.
* **The 401 handler is deferred to a macrotask.** `announce()` in `api.js` schedules
  `handlers.unauthenticated(error)` instead of calling it, so `showGate('')` blanks the
  message that `submitted()` had already written.

Both leave a person who types a wrong password looking at a button that greys and ungreys,
with no message. **The structural test passed both.** A harness that ran the real files in
Node's `vm` caught both.

That is not bad luck. The defect is an interaction across three functions in two files,
`announce()` in `api.js`, `showGate()` and `submitted()` in `app.js`, and the ordering
between them. A test that reads the text of one of those functions cannot see it by
construction. No amount of sharpening the substrings fixes that.

## Goal

`tests/` gains a Node harness that loads the real `app/index.html`, `app/app.js` and
`app/api.js`, runs them against a stubbed DOM and a stubbed `fetch`, and asserts what a
person would see on the screen. pytest drives it, so `uv run python -m pytest` is still the
one test command and one failure list covers both languages. The two mutants above are
killed by tests that build them from the shipped source at run time, so the harness's value
is demonstrated rather than asserted. The structural test is deleted.

## The runtime decision

**Decided here: `node` is a test-time requirement of this repo. The user approved it.
`node v20.16.0` is already on this machine. The engineer implements this decision and does
not re-open it.**

The scope is deliberately narrow, and the whole point is that it stays there:

* **No npm.** No `package.json`, no `package-lock.json`, no `node_modules`, no registry
  fetch at any point.
* **No test framework.** No jest, vitest, mocha, tape, uvu or `node:test`. The harness
  reports its own results.
* **No DOM library.** No jsdom, happy-dom, linkedom or cheerio.
* **No browser automation.** No Playwright, Puppeteer, Selenium or WebDriver.
* **No bundler, transpiler, linter, formatter or type checker**, in either language.
* **Node's built-in `vm` and `fs` only**, plus `path` and `url` for resolving files from
  the harness's own location. Nothing else is imported, not even another built-in, without
  a reason written next to it.
* **No Python dependency.** `pyproject.toml` and `uv.lock` are not touched.

Task 8 refused the JavaScript toolchain and named "a JavaScript test runner, browser
automation, a linter, a formatter or a type checker" in its out of scope list, adding that
"a later task with real client logic can revisit it". Task 9a then shipped real client
logic. **This does not reopen that door.** A runtime that is already installed, used by two
files that are already committed, with no package manager and no dependency graph behind
it, is the smallest thing that turns the shell from untested into tested. If implementation
appears to need any package from any registry, **stop and get the user's approval before
writing code.**

## How the real files are loaded

**`app/app.js` and `app/api.js` are not modified, at all, for any reason.** No export hook,
no `if (typeof module !== 'undefined')` tail, no test-only branch, no dependency injection
seam, no splitting a function out so it can be imported. They are classic browser scripts
and the harness's job is to be a browser-shaped enough environment to run them as they
ship. A harness that needs the subject changed to be testable has the same problem as the
test it replaces: it stops testing what runs.

The sequence, per scenario:

1. Read `app/index.html` and build an element tree from it. **The DOM comes from the
   shipped document, never from a hand-written fixture.** That is what makes a renamed id
   in `index.html` a loud harness failure instead of a stub that quietly drifts.
2. Create a fresh `vm` context holding the stubs below. `window` is the context's own global
   object, as in a browser, so `window.SplitwiseApi = {...}` in `api.js` is visible as
   `SplitwiseApi` to `app.js`.
3. Run `app/app.js` in that context with `vm.Script`, giving the real file path as the
   script filename so a thrown error reports a real location.
4. `app.js` boots by creating a `<script src="api.js">` and appending it to `document.head`.
   The stub's `appendChild` resolves that `src` against `app/`, reads the file, and schedules
   the load as a **macrotask**, matching a browser: `api.js` runs, then `onload` fires, then
   `wire()` runs. A `src` that names a missing file fires `onerror` instead, which is a real
   path in `app.js` and gets its own scenario.
5. The scenario drives the page: dispatch a `submit`, a `click`, a `hashchange`, set a field
   value.
6. **Settle**, then assert. Nothing is asserted mid-flight.

**Settling is the load-bearing part.** The defect this harness exists to catch is an
ordering defect, so a scenario that samples the DOM too early sees a message that is about
to be blanked and reports a pass. `settle()` returns only when the sandbox's microtask queue
is empty **and** its timer queue has been drained to nothing, including timers scheduled by
timer callbacks. It loops, bounded; a run that will not quiesce fails with a message naming
the scenario rather than hanging the suite.

Each scenario gets a fresh context and a freshly parsed document. `api.js` holds `cached`
and `handlers`; `app.js` holds `current` and `creating`. No scenario may inherit another's
state.

## How pytest invokes node

`tests/test_shell_behaviour.py` runs the harness once per session through
`subprocess.run`, and turns its report into individual pytest results.

* The interpreter is `shutil.which("node")`, and the resolved path is passed as `argv[0]`,
  not the bare string, so Windows does not depend on `PATHEXT` resolution inside the
  subprocess.
* The run configuration goes in as a JSON document on **stdin**: which scenarios to run,
  and which source substitutions to apply. The mutant text therefore lives in the Python
  test, where a reviewer reads it, not buried in the harness.
* The report comes back as a **single JSON object on stdout** listing every scenario with
  its name, its pass or fail, and its failure messages. Human-facing chatter goes to stderr
  and never to stdout.
* Exit status is **0** when every requested scenario passed, **1** when one or more failed,
  and **2** for a harness error: unparseable stdin, a substitution that did not match
  exactly once, a missing file, a script that threw while loading, a run that would not
  quiesce. The 1 and 2 distinction is not decoration; the mutant tests below depend on it.
* `subprocess.run` passes `timeout=60`, `encoding="utf-8"` and `check=False`. UTF-8 is
  explicit because the Windows default code page mangles anything outside it and turns a
  clear harness message into a decode error.
* The harness resolves `app/` from its own location via `import.meta.url`, never from the
  current working directory, matching every other test file in this repo.

**A missing `node` fails, loudly, and is never skipped.** `.claude/rules/testing.md` says
never mark a test skipped or xfail to make the suite green, and a JavaScript suite that
silently evaporates on a machine without the runtime is the same failure wearing a hat. One
dedicated test asserts `node` is on `PATH` and that `node --version` reports major 20 or
above, and its failure message names the requirement and points at CLAUDE.md. Every other
test in the file depends on the fixture that ran it, so a missing runtime produces one clear
failure plus errors that all name it, and never a green suite.

**The two suites report together.** The harness runs once for the session. A parametrized
pytest test then asserts one scenario each, so a failure reads as
`test_scenario[a_refused_sign_in_tells_the_person_why]` with the harness's own message
attached, rather than one opaque "node exited 1". A separate test asserts that the set of
scenario names the harness reported is exactly the list declared in the Python file, so a
scenario quietly deleted from the harness fails pytest instead of disappearing.

## The two mutants, exactly

**This is the acceptance bar for the whole task.** A harness that passes either mutant is
worth no more than the test it replaces, so killing them is a criterion and not an
aspiration.

Neither mutant is a committed copy of a shipped file. Both are **anchored text
substitutions applied to the real source at run time**, so they cannot rot into a false pass
and cannot be run by accident against anything the app serves. The harness applies each
substitution to the source it is about to load, and refuses the whole run with exit 2 unless
the anchor matched **exactly once**. A later task that edits either anchor gets a loud
failure and has to re-express the mutant, which is the correct outcome.

**Mutant A, in `app/app.js`.** Inside `show()`, hide the error along with everything else:

    find:     gate.hidden = which !== 'gate';
    replace:  gate.hidden = which !== 'gate';
              gateError.hidden = true;

`submitted()` writes the message, reveals it, and then calls `show('gate')`, which hides it
again. Nothing in `submitted()` changed by a single byte.

**Mutant B, in `app/api.js`.** Inside `announce()`, defer the 401 handler:

    find:     handlers.unauthenticated(error);
    replace:  setTimeout(function () { handlers.unauthenticated(error); }, 0);

`submitted()`'s `catch` now runs first and writes the message, and the deferred
`showGate('')` blanks it afterwards. `app/app.js` is untouched entirely.

Each mutant gets its own pytest test, and each asserts four things:

1. The harness exits **1**, not 2. A mutation that broke the file into a syntax error would
   also make a scenario "fail", and would prove nothing.
2. `a_refused_sign_in_tells_the_person_why` is among the failed scenarios.
3. At least one unrelated scenario still **passes** under the mutant, so the record shows a
   still-working app with one specific behaviour broken, not a smoking crater.
4. The slice the deleted structural test used to read, from `function submitted(` up to
   `function wire(`, is **byte-identical** between the shipped source and the mutated
   source. This is the reviewer's proof, written down where it cannot be forgotten: the old
   test could not have seen either mutant.

## What the stub fakes

Minimal on purpose. Every stub member exists because a shipped file uses it, and anything a
shipped file reaches for that the stub does not provide throws with a message naming it,
rather than returning `undefined` and producing a confusing failure three steps later.

* **`document`**, built from the parsed `app/index.html`: `getElementById`, `querySelector`,
  `querySelectorAll`, `createElement`, `head.appendChild`, a settable `title`, and `cookie`
  backed by the scenario's cookie jar so `api.js`'s `readCookie` works.
* **Elements**: `hidden` as a boolean property initialised from the presence of the `hidden`
  attribute in the document, `textContent`, `value`, `disabled`, `getAttribute`,
  `setAttribute`, `removeAttribute`, `addEventListener`, `focus`, and a scoped
  `querySelector`. `focus()` records the element, so focus can be asserted.
* **Selectors**: `#id`, `.class`, `.class descendant-tag` and a bare tag scoped to an
  element. That is exactly what `app.js` uses. Anything else throws rather than returning
  null, so a screen task that introduces an attribute selector breaks the harness visibly
  and someone widens it deliberately.
* **`window`**: the context global. `addEventListener` for `hashchange` and `load`, with a
  way for a scenario to dispatch them.
* **`location`**: a mutable `hash`, which is all `app.js` reads.
* **`history`**: `replaceState`, which records the call and updates `location.hash`.
  `pushState` exists only to record that it was called, because "replace, never push" is a
  decision task 8 made and a scenario asserts it.
* **`navigator`**: an object with **no** `serviceWorker` property, so `'serviceWorker' in
  navigator` is false and the registration branch is not entered. The harness does not
  pretend to cover service workers, and this is how it stays honest about that.
* **`console`**: records everything. Any console output during a scenario that the scenario
  did not declare is a scenario failure.
* **`setTimeout` and `clearTimeout`**: a deterministic queue the harness owns. Callbacks run
  in scheduling order and the declared delay is ordering information only, never real
  elapsed time. Nothing in the harness sleeps, and no assertion depends on the wall clock.
  Mutant B needs `setTimeout` to exist for the mutation to run at all.
* **`fetch`**: records every call, with its method, URL, headers, body and `credentials`,
  and answers from responses the scenario registered by method and path. **A request no
  answer was registered for is a scenario failure naming the method and the path**, rather
  than being served the next thing in a queue. That is what keeps the harness honest when
  tasks 12 and 13 add calls at boot: the new call fails loudly and the task that added it
  registers an answer.

How the failures are simulated:

* **A 401**: a response object with `status: 401`, `ok: false`, and a `json()` resolving to
  `{"error": {"code": "authentication_failed", "message": "..."}}`, the shape `web.py`
  actually returns.
* **A 403 `member_not_linked`**: the same with `status: 403` and that code.
* **A 500**: `status: 500`, which `api.js` folds into the same path as offline.
* **A 204**: `status: 204` with no body, which `api.js` must return `null` for without
  calling `json()`.
* **A body that is not JSON**: a `json()` that rejects, which `api.js` swallows into a null
  payload and an `ApiError` with an empty message.
* **A network failure**: `fetch` itself returning a rejected promise carrying a `TypeError`,
  which is what a real `fetch` does when the request never gets an answer.

The `code` strings in those fixtures are the real ones. A pytest test asserts that every
code the harness names appears in `src/splitwise_lite/web.py`, so the fixtures cannot drift
away from the contract they are imitating.

## The scenarios

Named as sentences, because the name is the failure message. These are the minimum; more are
welcome, fewer are not.

**Boot**

| Scenario | What it pins |
|---|---|
| `boot_with_no_session_shows_the_gate` | 401 on `GET /api/session`: gate visible, content and tab bar hidden, sign out hidden, gate title focused, no error message showing |
| `boot_with_a_linked_session_shows_the_app` | 200 with a member: content and tab bar visible, gate and notice hidden, sign out visible |
| `boot_with_an_unlinked_session_shows_the_not_linked_message` | 200 with `member: null`: the unlinked notice, the offline notice hidden, sign out visible, no gate |
| `a_403_member_not_linked_shows_the_not_linked_message` | The other route to the same screen, through `announce`, not through `refresh` |
| `a_network_failure_shows_the_offline_message_and_never_the_gate` | The offline notice up and `gate.hidden === true`, asserted explicitly |
| `a_server_error_is_the_same_screen_as_being_offline` | A 500 lands on the offline notice, not the gate |
| `the_api_client_failing_to_load_shows_the_offline_message` | `client.onerror`: `api.js` missing, so nothing is ever wired |

**Signing in**

| Scenario | What it pins |
|---|---|
| `a_refused_sign_in_tells_the_person_why` | The replacement for the deleted test. Gate visible, `#gate-error` not hidden, its text equal to the message the 401 carried, submit control enabled again, notice hidden, content still hidden |
| `a_refused_sign_in_with_an_unreadable_body_still_says_something` | A 401 whose body will not parse still puts `That did not work.` on the gate |
| `a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone` | The quiet branch: offline notice up, gate hidden, no message written, and the submit control enabled again anyway |
| `a_successful_sign_in_keeps_the_screen_the_person_was_on` | Start on `#/balances`, sign in, land on the app with the hash unchanged and balances still the visible screen |
| `a_session_that_dies_between_sign_in_and_session_read_returns_to_a_blank_gate` | 200 on the sign in, 401 on the following `GET /api/session`: the gate comes back **blank** and the submit control is usable again |
| `creating_an_account_signs_in_straight_after` | Toggle to create mode, submit, and see `POST /api/signup` then `POST /api/session` in that order, because signup issues no session |
| `the_gate_switches_the_password_autocomplete_with_the_mode` | `new-password` while creating, `current-password` after switching back |
| `the_form_never_lets_the_browser_navigate` | `preventDefault` called on the submit event. Without it the browser navigates and the whole app blanks |
| `the_email_is_trimmed_and_the_password_is_not` | The request body carries the trimmed address and the password exactly as typed, spaces included |
| `signing_out_returns_to_the_gate` | 204 on `DELETE /api/session`: gate visible, sign out hidden, the title back to `Sign in` |

**Routing**

| Scenario | What it pins |
|---|---|
| `routing_shows_one_screen_and_moves_focus` | Navigate to `#/balances`: exactly one section visible, `aria-current` on exactly one tab, `document.title` updated, the new heading focused |
| `an_unknown_hash_is_replaced_not_pushed` | `#/nope` calls `replaceState` and never `pushState`, and lands on `#/feed` |

**The client**

| Scenario | What it pins |
|---|---|
| `every_request_goes_to_the_api_with_credentials` | Every recorded URL starts with `/api/`, every call sets `credentials: 'same-origin'`, and safe methods send no `Content-Type` and no CSRF header |
| `the_csrf_token_is_read_at_request_time_not_cached` | Change the cookie jar between two POSTs and see the second request carry the second token. Today this is a substring assertion in `test_web_shell.py`; here it is the behaviour |
| `a_204_is_not_parsed_as_json` | Sign out succeeds against a response whose `json()` would throw if it were called |

`a_session_that_dies_between_sign_in_and_session_read_returns_to_a_blank_gate` is the one to
read carefully. The harness pins whatever the shipped code does today. If the resulting
screen looks wrong to the engineer, **raise it; do not edit `app/` to change it.** Fixing
front end behaviour is not this task.

**Corrected 2026-09-06, during implementation.** That scenario was named
`..._returns_to_the_gate` in this file, here and in the table above and in the out of
scope list below. The name described correct behaviour, but the scenario pins a known
defect: the sign-in succeeds, the session read behind it 401s, and the person is
returned to a gate carrying **no message at all**, because the 401 handler calls
`showGate('')` and the success path never writes one. A name that reads as correct
behaviour means that whoever eventually fixes that screen sees this test go red with
no hint that going red is the point, and the likely reaction is to revert the fix. The
new name says the gate comes back blank, and the scenario carries a comment saying it
pins a defect and that a later fix updates the scenario rather than reverting. The
criterion below requiring the names in these tables "spelled the same way" reads
against the corrected spelling.

## What stays browser-only

The harness must not pretend to cover any of these, and no scenario may be named as if it
did. They stay on the hand checklist in
`plans/tasks/09a-application-server-and-http-api.md`, and the harness's module docstring
lists them under a heading saying so:

* **Service worker registration**, activation, scope, the `skipWaiting` and `clients.claim`
  behaviour, and the `/api` bypass. The stub `navigator` deliberately has no
  `serviceWorker`.
* **Cache Storage**: what is in it, that there is exactly one cache, and that bumping
  `VERSION` clears the old ones.
* **Installability**: the manifest parsing, the install affordance, launching standalone,
  and whether an installed window shares the browser's cookie jar.
* **Offline reload of the document itself.** The harness stubs `fetch`; it does not stub a
  browser that has lost its network.
* **Real cookie enforcement.** `HttpOnly`, `SameSite` and `Secure` are enforced by a
  browser, not by a fake `document.cookie`. That `sl_session` is invisible to script and
  `sl_csrf` is visible stays a DevTools check.
* **Console cleanliness in a real browser**, which includes the service worker warning path
  the harness never enters.
* **Focus actually announcing a screen.** The harness records that `focus()` was called on
  the right element. Whether a screen reader says anything is a different question and is
  not answered here.
* **Layout**: viewport, safe area insets, hit areas, font sizes, iOS auto-zoom, and every
  responsive check in task 8's list.
* **A disabled button really refusing a second click.** The harness dispatches handlers
  directly, so it cannot prove that, and must not claim to.

## The fate of the structural test

`test_a_refused_sign_in_tells_the_person_why` and its helper `gate_submit_handler()` are
**deleted** from `tests/test_web_shell.py`. Not renamed, not kept alongside, not marked
xfail, not moved to another file. Two tests covering one property, where one of them is
known to pass a defect, is worse than one: the failing one gets read as noise next to its
green neighbour.

The name moves to the harness as a scenario, so `git log -S` still finds the trail.

Every other test in `tests/test_web_shell.py` stays exactly as it is, including the ones
that read `app/app.js` as text for a different purpose: the `ROUTES` table check, the
`getElementById` inventory, the `'new-password'` check, and the whole `fetch` and `/api`
containment family. Those are inventory and containment rules, not behaviour asserted
through source, and they are not this task's business.

## Acceptance criteria

**The harness kills both mutants**

- A pytest test builds mutant A by substituting `gateError.hidden = true;` into `show()` in
  the text of `app/app.js` at run time, runs the harness against the mutated source, and
  asserts the harness exits **1**.
- That test asserts `a_refused_sign_in_tells_the_person_why` is among the scenarios the
  harness reported as failed, and that the reported failure message names the gate error
  element or its text, so the failure is the right failure and not a coincidence.
- That test asserts at least one named unrelated scenario still passed under mutant A, so
  the mutation is proven to leave a working app with one broken behaviour.
- That test asserts the slice of `app/app.js` from `function submitted(` up to
  `function wire(` is byte-identical between the shipped source and the mutated source,
  which is the proof that the deleted structural test could not have seen it.
- A second pytest test does all four of the above for mutant B, substituting
  `setTimeout(function () { handlers.unauthenticated(error); }, 0);` for
  `handlers.unauthenticated(error);` in `app/api.js`, and asserts the byte-identical slice
  in `app/app.js`, which mutant B does not touch at all.
- Neither mutant is a committed copy of a shipped file. Both are anchored substitutions
  applied at run time, and the harness exits **2** with a message naming the file and the
  anchor if an anchor matches zero times or more than once. A test proves that by feeding
  the harness an anchor that is not in the file and asserting exit 2.
- The mutant tests assert exit **1**, never merely "non-zero", so a substitution that broke
  the file into a syntax error cannot be mistaken for a killed mutant.
- Running the harness with no substitutions passes every scenario, and the exit status is 0.

**How the files are loaded**

- `app/app.js` and `app/api.js` are byte-identical to `master`. `git diff master -- app/`
  is empty. No export hook, no `module.exports`, no `typeof module` branch, no test-only
  global, no function extracted so it can be imported.
- The harness executes both files with `node:vm` against a stubbed global. It reads them
  with `node:fs` and does nothing else with them: **no scenario reads the text of
  `app/app.js` or `app/api.js` and asserts on it.** A `grep` of the harness finds no
  substring, regular expression or slice taken against either file's source outside the
  substitution machinery.
- The DOM is built by parsing `app/index.html`. There is no hand-written element list, and
  no scenario creates an element that the shipped document does not contain.
- `getElementById` returning nothing for an id `app.js` asks for is a harness error with a
  message naming the id, never a silent `null`.
- `api.js` is loaded the way `app.js` loads it: `document.createElement('script')`, a `src`
  resolved against `app/`, `appendChild`, then a macrotask, then `onload`. A `src` naming a
  file that does not exist fires `onerror`.
- `window === globalThis` inside the sandbox, so `window.SplitwiseApi` set by `api.js` is
  reachable as a bare global from `app.js`.
- Each scenario runs in a fresh `vm` context with a freshly parsed document. A test proves
  isolation: two scenarios that both boot see two separate `fetch` recorders, and the cached
  session view inside `api.js` does not survive from one to the next.
- Scripts are run with the real file path as the script filename, so an exception inside
  `app/app.js` reports that path and a line number.

**Settling and determinism**

- Every scenario asserts only after a `settle()` that drains the sandbox's microtask queue
  and its timer queue to empty, including timers scheduled from inside timer callbacks. No
  assertion runs mid-flight.
- `settle()` is bounded. A run that will not quiesce exits **2** with a message naming the
  scenario, and never hangs. A test proves it by registering a scenario-local timer that
  reschedules itself, or by an equivalent mechanism the harness owns.
- `setTimeout` delays are ordering information only. Nothing sleeps, no assertion reads the
  wall clock, and the suite's runtime does not depend on any declared delay.
- The harness uses no randomness, no `Date.now`, no locale-dependent formatting and no
  network. Two runs of the same configuration produce byte-identical JSON on stdout.
- The harness opens no socket, spawns no process, writes no file, and reads no path outside
  the repository.

**How pytest invokes node**

- `tests/test_shell_behaviour.py` locates the interpreter with `shutil.which("node")` and
  passes the resolved path as `argv[0]`.
- One test asserts `node` is present and that `node --version` reports major version 20 or
  above, with a failure message naming the requirement and pointing at CLAUDE.md.
- **A missing or too old `node` fails the suite.** No test in the repo is skipped, xfailed,
  or made conditional on the runtime being present, per `.claude/rules/testing.md`. A
  `grep` for `skipif`, `pytest.skip` and `xfail` in `tests/` finds nothing new.
- The harness runs **once per session** through a session-scoped fixture, not once per
  scenario, so the suite pays for one process.
- `subprocess.run` is called with a list, no shell, `timeout=60`, `encoding="utf-8"`,
  `text=True` and `check=False`. A timeout is a test failure carrying whatever the harness
  wrote to stderr.
- The run configuration goes to the harness on stdin as JSON. The report comes back as one
  JSON object on stdout. Nothing else is written to stdout; human-facing output goes to
  stderr.
- A non-zero exit or stdout that will not parse is one pytest failure whose message includes
  the exit status and stderr verbatim, not a `JSONDecodeError` traceback.
- Each scenario becomes its own pytest result through a parametrized test, so a failure
  reads as `test_scenario[a_refused_sign_in_tells_the_person_why]` and carries the harness's
  own failure messages.
- `SCENARIOS` is a list in `tests/test_shell_behaviour.py`, and one test asserts the set of
  names the harness reported equals it exactly. A scenario deleted from the harness fails
  pytest; a scenario added to the harness without being declared fails pytest too.
- `SCENARIOS` contains at least every name in the tables above, spelled the same way.
- The harness runs standalone as `node tests/shell_harness.mjs` with no stdin, running every
  scenario against the unmodified files, so a person debugging one can run it directly.
- Files are located from the harness's own `import.meta.url` and from
  `Path(__file__).resolve().parents[1]` on the Python side. Neither depends on the current
  working directory, and a test proves the suite passes when pytest is run from another
  directory.

**What the stub fakes**

- `document` provides `getElementById`, `querySelector`, `querySelectorAll`,
  `createElement`, `head.appendChild`, `title` and `cookie`, and nothing that no shipped
  file uses.
- Elements provide `hidden` as a boolean initialised from the document, `textContent`,
  `value`, `disabled`, `getAttribute`, `setAttribute`, `removeAttribute`,
  `addEventListener`, `focus` and a scoped `querySelector`.
- Selector support is exactly `#id`, `.class`, `.class tag` and a bare tag scoped to an
  element. Any other selector throws with a message naming it, and a test proves that.
- `window` is the sandbox global and carries `addEventListener`, with a scenario-facing way
  to dispatch `hashchange`.
- `location.hash` is mutable, and `history.replaceState` updates it. `history.pushState`
  exists only so a scenario can assert it was never called.
- `navigator` has no `serviceWorker` property, and a test asserts the service worker
  registration branch in `app.js` is never entered. **Noted 2026-09-06, during
  implementation.** Each scenario reports the window events `app.js` subscribed to and
  the test asserts that set is exactly `{"hashchange"}`, so a `load` listener, which
  only that branch registers, fails it. A set and not a list: tasks 11 and 12 each
  register a `hashchange` listener of their own and the screens after them will add
  more, so pinning the count would fail on an unrelated change. The isolation test was
  tightened in the same commit to pin each scenario's exact request list, which is a
  stronger statement than the one it replaced, so nothing was traded away here.
- `console` is recorded, and any console output a scenario did not declare fails that
  scenario.
- `fetch` records method, URL, headers, body and `credentials` for every call, and answers
  from responses registered by method and path. A request with no registered answer fails
  the scenario with a message naming the method and the path. **Noted 2026-09-06, during
  implementation.** Recording those five fields is not asserting them, and the first two
  rounds of review asserted only method and path, then only header *names*. That passes a
  `Content-Type` of `text/plain`, an `Accept` that takes anything, an added
  `mode: 'no-cors'`, a CSRF header carrying the raw undecoded cookie, and a `signUp` that
  sends the password where the display name belongs. `web.py` refuses the first and the
  fourth outright, so each is a shipping bug the harness would have called green. Every
  recorded call is now held to the whole contract in `finish()`, header values, the shape
  of the options object and `credentials` included, and a call that changes something must
  declare its exact body or the scenario fails. The rule to carry forward: a field the
  stub records but nothing asserts is a field that can be rewritten silently.
- **Fixed 2026-09-06, during implementation.** The stub snapshotted `classList` when the
  document was parsed, so `setAttribute('class', ...)` and `className` were both accepted
  and neither reflected. Tasks 11 and 12 set `className` on every node they build, so the
  first `.class` selector scenario written against those screens would have matched nothing
  and read as a passing test. Both now reflect the attribute, and the guarded proxy refuses
  a *set* of any property the stub does not define, the way it already refused a get.
  Silent acceptance is the one behaviour a stub must never have.
- A 401, a 403 `member_not_linked`, a 500, a 204, a body whose `json()` rejects, and a
  `fetch` that rejects with a `TypeError` are all expressible, and each is used by at least
  one scenario.
- Every error `code` string the harness names appears in `src/splitwise_lite/web.py`, and a
  pytest test asserts it, so the fixtures cannot drift from the real error contract.

**What the scenarios cover**

- Every scenario named in the tables above exists and passes against the shipped files.
- `a_refused_sign_in_tells_the_person_why` asserts the gate is visible, `#gate-error` is not
  hidden, its `textContent` equals the message the 401 carried, the submit control is
  enabled again, and both notices stay hidden.
- `a_network_failure_shows_the_offline_message_and_never_the_gate` asserts
  `gate.hidden === true` explicitly. The offline notice being up is not enough on its own.
- `a_403_member_not_linked_shows_the_not_linked_message` asserts the unlinked notice is
  visible, the offline notice is hidden, and the gate is hidden.
- `a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone` asserts the submit control
  is enabled again on the quiet path, which is the branch that returns early.
- `a_successful_sign_in_keeps_the_screen_the_person_was_on` starts on `#/balances` and
  asserts the hash is unchanged and the balances section is the visible one.
- `the_csrf_token_is_read_at_request_time_not_cached` changes the cookie jar between two
  state-changing requests and asserts the second carries the second token.
- `the_email_is_trimmed_and_the_password_is_not` uses an address with leading and trailing
  spaces and a password with a leading space, and asserts the request body exactly.
- No scenario asserts anything about service workers, Cache Storage, installability,
  layout, the manifest, real cookie attributes, or a disabled control refusing a click.

**The structural test**

- `test_a_refused_sign_in_tells_the_person_why` and `gate_submit_handler` are deleted from
  `tests/test_web_shell.py`. A `grep` for either name across the repository finds them only
  in `plans/`.
- Nothing replaces them in `tests/test_web_shell.py`. Its remaining tests are unchanged, and
  `git diff` on that file shows one deletion of the function, its helper and their comments,
  and nothing else.
- No test anywhere slices a function body out of `app/app.js` or `app/api.js` and asserts
  substrings against it.

**Documentation**

- CLAUDE.md gains node as a test-time requirement: the version floor, that
  `tests/shell_harness.mjs` runs the real `app/` files under Node's `vm`, that there is
  still no npm, no `package.json` and no `node_modules`, and that a missing node fails the
  suite rather than skipping it.
- README.md's `## Test` section gains the same requirement in one or two sentences.
- **Neither addition contains the phrase "no build step".**
  `tests/test_web_shell.py::test_the_no_build_step_claim_carries_its_caveat_where_it_is_made`
  asserts exactly one paragraph in each file names it, and a second paragraph fails that
  test. If the claim needs restating, extend the existing paragraph and keep its `VERSION`
  and `app/sw.js` caveat intact.
- `test_claude_md_names_the_real_run_command`, `test_the_readme_documents_how_to_run_the_app`
  and every other docs test in `tests/test_web_shell.py` still passes.

**Suite**

- `uv run python -m pytest` passes. Plain `uv run pytest` fails on this machine with an
  access-denied spawn error.
- Every test on `master` still passes, apart from the one deletion named above. No test in
  `tests/test_web_api.py`, `test_dev_server.py`, `test_store.py`, `test_accounts.py`,
  `test_groups.py`, `test_events.py`, `test_money.py`, `test_split.py`, `test_balances.py`,
  `test_simplify.py`, `test_setup_group_cli.py` or `test_smoke.py` changes at all.
- `tests/test_web_shell.py::test_app_holds_exactly_the_promised_files` passes unchanged:
  nothing is added to `app/`.
- `tests/test_web_shell.py::test_scripts_holds_exactly_the_promised_python_files` passes
  unchanged: nothing is added to `scripts/`.
- No test binds a socket, opens a port or starts a thread.
- The whole JavaScript half adds no more than a few seconds to the suite.

## Out of scope

- **Any change to `app/`.** Not `index.html`, not `app.js`, not `api.js`, not `styles.css`,
  not `sw.js`, not the manifest, not the icons. This task tests what is there. If a scenario
  exposes a bug, it is reported and fixed in its own task, not here.
- **Fixing the front end.** If `a_session_that_dies_between_sign_in_and_session_read_returns_to_a_blank_gate`
  or any other scenario documents behaviour that looks wrong, the harness pins the current
  behaviour and the engineer raises it. Changing the app and its test in one commit is how a
  test ends up asserting whatever the code happens to do.
- **npm, `package.json`, `package-lock.json`, `node_modules`, and any registry package.**
- **A JavaScript test framework**, including `node:test`. The harness reports its own
  results, because a framework's runner is a second reporting path to keep in step with
  pytest's.
- **jsdom, happy-dom, linkedom, cheerio or any DOM implementation.** The stub is small
  because the shipped files are small.
- **Playwright, Puppeteer, Selenium, WebDriver or any real browser.** That is a real
  dependency decision with a real cost, and it is not made here. The browser-only list stays
  on the hand checklist.
- **A JavaScript linter, formatter, type checker, bundler, transpiler or minifier.**
- **Coverage measurement**, in either language.
- **`app/sw.js`.** Service worker semantics need real Cache Storage, a real fetch handler
  registration and a real install lifecycle. Faking them would produce a test that passes
  while the worker is broken, which is the exact failure this task exists to end.
- **Screen behaviour that does not exist yet.** Tasks 10, 11, 12 and 13 add screens, and each
  adds its own scenarios. This task covers the gate, the notices, routing and the client.
- **Visual, layout, CSS or accessibility-tree assertions.** No screenshots, no computed
  styles, no axe.
- **A second test command.** `uv run python -m pytest` stays the only one. `node
  tests/shell_harness.mjs` is a debugging convenience, not a documented test command, and CI
  does not call it directly.
- **Changing `pyproject.toml`, `uv.lock` or any Python dependency.**
- **Changing `.claude/rules/testing.md`, the hooks, or any agent definition** to accommodate
  a second language. If the testing rule genuinely needs a line about node, raise it rather
  than editing it.
- **A mutation testing tool or a general mutation framework.** Two named mutants, expressed
  as two anchored substitutions, is the whole of it.

## Constraints

- Files to create: `tests/shell_harness.mjs` and `tests/test_shell_behaviour.py`. Nothing
  else.
- Files to modify: `tests/test_web_shell.py` (the one deletion and nothing else), `CLAUDE.md`
  and `README.md` (the node requirement only).
- **Nothing under `app/` is created, modified or deleted.** `git diff master -- app/` is
  empty at the end of this task. This is also what keeps this branch out of the way of #12
  and #13, which are being built concurrently and both edit `app/index.html`, `app/app.js`
  and `app/styles.css`. Touching any of those three here would produce a conflict for work
  that has nothing to do with a test harness.
- When #12 or #13 lands and legitimately changes what a scenario sees, whichever task lands
  second owns updating the scenario. **The fix is never to weaken a scenario into a
  source-text assertion, and never to delete one.** If a scenario cannot be kept honest,
  stop and raise it.
- **Happened 2026-09-06, during implementation.** Tasks 11 and 12 landed on `master`
  while this branch was open, so this task landed second and owned the update. Both read
  as soon as the app frame appears, the feed loading the expenses and the roster and the
  balances screen loading the roster and the figures, and the harness refused every one
  of those calls with `no answer was registered for GET /api/expenses`. **That is the
  design working, not breakage.** Whoever adds the next screen will hit the same wall and
  should read it that way. What it took: four more element members in the stub
  (`appendChild`, `removeChild`, `replaceChildren`, `firstChild`), an answer registered
  for each new read using the empty valid payload shape, and the longer request list
  declared in the eight scenarios that reach the app frame. No scenario was weakened and
  none was deleted. This task added no scenario about what those two screens draw: that
  belongs to the tasks that own them. One thing to know if the harness ever dies with a
  bare Node stack and no report: an error escaping into a promise nobody handled is now
  recorded against the scenario that was running, which is how the first of these
  failures was found.
- Do not modify anything under `src/splitwise_lite/`, `scripts/`, `plans/`, `.claude/`,
  `pyproject.toml`, `uv.lock`, `group.example.toml`, or any test file other than the two
  named above.
- **This file is the one exception, and only for a statement that is provably wrong,**
  following the precedent tasks 5, 9 and 11 set: it is created by this PR and nothing on
  `master` depends on it. Sharpening a criterion, re-scoping one or softening one to suit
  an implementation is not covered and stays forbidden. Every correction carries a dated
  marker saying what the file used to say, what it says now and why, so the next reader
  inherits the reasoning instead of a choice between two contradictory lines. One was
  made on 2026-09-06 and is marked in place: the scenario name
  `..._returns_to_the_gate`, which described correct behaviour while the scenario pins a
  known defect. Two other markers in this file record what implementation found rather
  than correcting anything. A spec left contradicting the code its own PR produced is
  how four agents rediscovered the `group_id` contradiction on this project.
- `plans/backlog.md` is not edited. Issue #31 is the backlog entry for this task.
- **No dependency in either language.** No `package.json` and no addition to
  `pyproject.toml`. `.claude/hooks/guard-deps.hs.sh` blocks the ad hoc Python route already;
  the JavaScript side has no guard, so the discipline is the rule. If implementation appears
  to need a package, **stop and get the user's approval first.**
- The harness imports `node:vm`, `node:fs`, `node:path` and `node:url` and nothing else. Any
  further import, built-in or not, needs a one-line comment saying why.
- The harness is ESM in a `.mjs` file: Node treats `.mjs` as a module without a
  `package.json` to declare it, and top-level `await` makes the settle loop readable.
- The harness targets node 20 or above and uses no flag, no environment variable and no
  experimental feature.
- Python is the standard library plus pytest, targeting 3.12: `subprocess`, `shutil`,
  `json`, `pathlib`, `re`.
- Tests locate repo files from `Path(__file__).resolve().parents[1]`, and the harness from
  `import.meta.url`. Never the current working directory.
- Assertions are exact: exact element states, exact strings, exact request method and path,
  exact ordered request lists, exact exit statuses. No substring guess at prose that the
  shipped files did not put there, and no approximate comparison, per
  `.claude/rules/testing.md`.
- No test is skipped or xfailed, and no test is made conditional on the environment. If
  something here cannot be tested, stop and raise it.
- Every non-obvious choice in the harness gets a one-line comment where it is implemented:
  why the DOM is parsed rather than declared, why the `api.js` load is a macrotask, why
  `navigator` has no `serviceWorker`, why an unregistered request is a failure rather than a
  default, why exit 2 is separate from exit 1, and why `settle()` is bounded.
- The harness's module docstring states, at the top, that it exists because a test that
  reads one function's source cannot see an ordering defect across three, names the two
  mutants it is measured against, and lists what stays browser-only.
- `tests/test_shell_behaviour.py`'s module docstring names this file, says the harness runs
  once per session, and says that a missing `node` is a failure and never a skip.
