# Task 32: the client error contract, end to end

Closes GitHub issues #32 (three defects in `announce()`) and #36 (a blank gate after a
sign-in the server accepted). This is the client half of the contract task 9a wrote down:
`src/splitwise_lite/web.py` decides what every refusal is, and `app/api.js` is the one
place that decides what a refusal means to the person holding the phone. The screens print
what they are handed and classify nothing.

## What is wrong today

`announce()` in `app/api.js` is three `if` arms and no `else`:

* a 401 drops the cached session view and raises the gate,
* a 403 whose code is exactly `member_not_linked` raises the not-linked notice,
* `status === 0` or `status >= 500` raises the offline notice,
* and **everything else falls off the end and nothing happens at all**.

Three reported symptoms, one cause:

1. A 503 is reported as "cannot reach the server". `web.py` composes two 503 messages on
   purpose, `no_group_configured` naming the setup command and `ambiguous_group` naming
   both group ids, and both are thrown away by the `status >= 500` arm. An operator who
   has not run `setup_group.py` is told their network is broken.
2. A 401 on the session read straight after a successful sign-in returns the person to a
   blank gate. The gate they just used, with nothing on it, which invites them to type the
   same password again, and again. This is the shape a browser that will not keep the
   session cookie produces, and the loop is the harm.
3. A 403 whose code is not `member_not_linked` matches no arm. Nothing on screen changes
   and the person is left looking at an empty app frame.

The default has to stop being "do nothing". A classifier that recognises a few cases and
silently drops the rest is not a classifier.

**A half fix would be worse than today.** Classifying the 503 correctly, handing the
handler the server's exact sentence naming the setup command, and then still printing
"cannot reach the server" is a bug with a correct-looking implementation behind it, which
is harder to find than the original. So the sentence has to reach the screen in this task,
which is why the file list includes two shell files as well as the client.

## Goal

`announce()` classifies every response the server can produce, against `web.py`'s error
table rather than against a guess; every failed request ends in exactly one of two places,
a curtain over the whole frame or a rejection the screen that asked for it reports; and
what the person reads is the sentence the server sent, printed by a screen that never looks
at a status code. Nothing is silently dropped, no answer from the server is reported as a
network failure, and no sign-in the server accepted ends on a blank gate.

## The decisions this task makes

### 1. The words come from the server

`web.py` already composes a sentence for every refusal and `_handle_error` sends it in
`error.message` at every status except 500. The client shows that sentence and does not
write its own version of it. Two sentences for one situation drift the moment either is
edited, which this project has already paid for once in the `group_id` contradiction.

The client owns the words in exactly two situations, both because the server has no
sentence to offer:

* nothing came back at all, so there is no message to show;
* the server accepted a sign-in and then answered the very next request with a 401, so the
  server believes it succeeded and its message describes a different situation.

Both of those sentences live in `app/index.html` with the rest of the standing copy, never
in `app/api.js`. The network client owns no screen copy.

### 2. Six kinds, three handlers, two fields

`ApiError` gains two fields:

* **`kind`**: the client's own classification, one of six strings, set before any handler
  runs and carried on the rejection the caller receives. `code` stays what the server said;
  `kind` is what this client decided it means.
* **`say`**: the sentence to put in front of the person, which is **either exactly
  `error.message` or exactly `''`**, and never anything else. `''` means "there is nothing
  here worth reading", either because the body carried no message or because the message
  describes a situation the person is not in. `api.js` chooses whether to speak. It never
  chooses the words.

A screen may branch on `kind`. **No screen may branch on `status` or on `code`.**

| Kind | What it means | Handler | `say` | `cached` |
|---|---|---|---|---|
| `offline` | No answer at all | `onOffline` | `''` | untouched |
| `signed-out` | Signing in is what fixes it | `onUnauthenticated` | `message`, except `''` for code `not_authenticated` | dropped first |
| `sign-in-not-kept` | The server accepted the sign-in and then refused the next request | `onOffline` | `''` | dropped first |
| `not-linked` | Signed in, no member row | `onNotLinked` | `''` | untouched |
| `unavailable` | The server answered and this app cannot go on | `onOffline` | `message` | untouched |
| `refused` | The server refused this one request and said why | none, see 4 | `message` | untouched |

`not_authenticated` is the only 401 code whose sentence is suppressed. It means "there was
no cookie at all", which is every first visit, and "this endpoint needs a signed-in
session" is written for a client, not for a flatmate. The gate already says what it is for.
`session_invalid` and `authentication_failed` both say something the person needs.

`not-linked` keeps the standing paragraph it has today, which is fuller than the server's
sentence and is what ships. Nothing about that screen changes.

### 3. The complete classification, against `web.py`

Read top to bottom. The last two rows are the default and they are reached by anything the
rows above did not claim, which is the whole point of this task.

| Status | Codes `web.py` can send | Kind |
|---|---|---|
| `0` | `offline`, or a response the browser will not let the client read | `offline` |
| 401 | `not_authenticated`, `session_invalid`, `authentication_failed` | `signed-out`, or `sign-in-not-kept` while armed (see 5) |
| 403 with code `member_not_linked` | `member_not_linked` | `not-linked` |
| 403, any other code | `csrf_failed` | `refused` |
| 400 | `malformed_request`, `invalid_email`, `invalid_password`, `invalid_amount`, `invalid_currency`, `currency_mismatch`, `invalid_split`, `invalid_record`, `amount_too_large` | `refused` |
| 404 | `record_not_found`, `not_found` | `refused` |
| 405 | `method_not_allowed` | `refused` |
| 409 | `email_already_registered`, `duplicate_record`, `constraint_violated`, `group_mismatch`, `member_already_linked`, `user_already_linked` | `refused` |
| 413 | `request_too_large` | `refused` |
| 429 | `too_many_attempts` | `refused` |
| 500 | `internal_error` | `unavailable` |
| 503 | `no_group_configured`, `ambiguous_group` | `unavailable` |
| Any other status at or above 500, or a status that is not a readable number | anything, including none | `unavailable` |
| Any other status below 500 | anything, including none | `refused` |

An unreadable status must never be `refused` and must never raise the gate, because if the
client cannot tell the request was refused, offering a password box is how the
password-into-nothing loop starts.

A 500 and a rejected `fetch` stay two different kinds. They are genuinely different: one is
an answer this app produced and logged, and it has a sentence, the other is no answer at
all. After this task they are two different paragraphs on screen.

### 4. `refused` is the caller's, with two named exceptions

A `refused` names something about the one request that was made, so the caller reports it:
the gate writes it into `#gate-error`, and the feed and balances screens have their own
failure states. **Raising a full frame curtain for a 409 on signup would take the gate's
own message away, which is this task causing the defect it exists to remove.**

Two requests have no caller that reports anything, because `app/app.js` swallows both
rejections by design:

* `session()`, whose rejection `refresh()` discards on the grounds that a handler has
  already spoken. When no handler speaks, the person gets an empty app frame. That is
  defect 3.
* `signOut()`, whose rejection the sign out button discards, leaving a dead button.

For those two, and only those two, a `refused` also calls `onOffline`, which now prints
what the server said rather than claiming the network is down.

### 5. A sign-in that did not stick is not a sign-in problem

When `POST /api/session` answers 200, the client arms a one shot check. It is disarmed by
the first response after it that is not a 401, and by signing out. A 401 arriving while it
is armed means the credentials were accepted and the session did not survive one round
trip, which is what a browser that will not keep the cookie looks like. Signing in again
cannot fix that, and offering the gate is how a person types their password into nothing,
repeatedly, which is the exact failure the offline rule was written to prevent. So the
cached view is dropped and its own notice goes up instead of the gate.

An ordinary expiry mid session is unaffected: by then the check has been disarmed by a
successful read, and the person gets the gate carrying the server's sentence, which is
right.

The recorded gap: a client that signed in and then made no request at all until its session
expired would report that expiry as `sign-in-not-kept`. The shipped app reads the session
immediately after signing in, so it cannot happen here.

### 6. The fourth on-screen state, and why it is needed

The notice curtain gains two paragraphs, so `#notice` holds four and exactly one of them is
ever visible:

| Paragraph | Shown for | Text |
|---|---|---|
| `#notice-unlinked` | `not-linked` | standing, unchanged |
| `#notice-offline` | `offline` | standing, unchanged |
| `#notice-not-kept` | `sign-in-not-kept` | standing, new |
| `#notice-problem` | `unavailable`, and an escalated `refused` | written from `error.say` |

`#notice-problem` is the fourth state, and it is what closes defect 1: a 503 prints the
sentence naming `setup_group.py`, or the one naming both group ids, in the server's words.
It is empty in the document and is the only paragraph whose text a screen writes.

No fourth handler is added. `onOffline` keeps its name and now covers "no usable answer";
which paragraph goes up is chosen from `kind`, in `app/app.js`, in one place.

## Acceptance criteria

**The classifier**

- `announce()` assigns a kind to every rejection it sees. Reading it shows a ladder or a
  table that ends in a default arm, not an `if` chain that can fall off the end.
- The kinds are spelled exactly `offline`, `signed-out`, `sign-in-not-kept`, `not-linked`,
  `unavailable` and `refused`, and `kind` is set on the `ApiError` before any handler is
  called.
- The mapping matches the table in section 3 row for row, and every status in `web.py`'s
  `ERROR_STATUS` appears in it: 400, 401, 403, 404, 405, 409, 413, 429, 500 and 503.
- A status nobody anticipated is classified rather than dropped: 502 and 504 are
  `unavailable`, 418 is `refused`, and a `status` that is missing or not a number is
  `unavailable`, never `refused` and never the gate.
- `status === 0` is `offline` whether `fetch` rejected or the browser returned a response
  the client may not read. Both mean no answer came back.
- A 503 is never `offline` and never `refused`: `no_group_configured` and `ambiguous_group`
  are `unavailable`.
- A 500 is `unavailable`, not `offline`.

**The message and the handoff**

- `app/api.js` never composes, prefixes, translates, shortens or substitutes a message the
  server sent. `error.message` is the server's sentence character for character, and `''`
  when the body carried none.
- `error.say` is, on every path, either exactly `error.message` or exactly `''`. Reading
  `api.js` shows no third possibility and no string literal that could become one.
- `say` is `''` for `offline`, `sign-in-not-kept`, `not-linked`, and for a `signed-out`
  whose code is `not_authenticated`. It is `error.message` for `unavailable`, `refused`,
  and for a `signed-out` whose code is anything else, `session_invalid` and
  `authentication_failed` included.
- Every handler is invoked as `handler(error)` with the whole error: `status`, `code`,
  `message`, `kind` and `say`.
- `signed-out` calls `onUnauthenticated` and `cached` is already null when it runs.
- `not-linked` calls `onNotLinked` and leaves `cached` alone.
- `offline`, `unavailable` and `sign-in-not-kept` call `onOffline`.
- `refused` calls no handler, except when it answers `session()` or `signOut()`, where it
  calls `onOffline`.
- A `refused` answering `signUp()`, `signIn()`, `members()`, `expenses()`, `addExpense()`
  or `balances()` raises no curtain at all: a 409 on signup and a 429 on sign-in still read
  on the gate, in the server's words, with the gate or the app frame left where it was.
- Every path still returns `Promise.reject(error)` carrying the original `ApiError`. A
  handler that throws does not change what the caller is rejected with and does not stop
  the rejection.
- The classifier never retries, re-sends, redirects or loops.
- `announce()` fires once per failed request and does not deduplicate, debounce or
  coalesce. Two failures in flight fire twice; when they are two different kinds, the last
  handler to run owns the screen, and `api.js` does not arbitrate between them. Recorded,
  not fixed.

**The sign-in that did not stick**

- A 200 from `POST /api/session` arms the check; the first response after it that is not a
  401 disarms it; signing out disarms it.
- A 401 while armed is `sign-in-not-kept`: `cached` is dropped, `onUnauthenticated` is not
  called, `onOffline` is.
- A 401 while disarmed is `signed-out` and raises the gate, so a session that expires mid
  session still returns the person to the gate.
- A 401 answering `POST /api/session` itself is always `signed-out`, never
  `sign-in-not-kept`: a wrong password shows the gate with the server's message on it.
- The armed flag holds nothing about the session, is not persisted, and never reaches
  browser storage.

**The screen**

- `app/index.html` gains exactly two paragraphs, both inside `#notice`, both starting
  `hidden`, both carrying `class="curtain-text"` so no rule is added to `app/styles.css`:
  `#notice-problem`, empty in the document, and `#notice-not-kept` carrying its standing
  sentence.
- `#notice-not-kept` says that the sign-in was accepted and then not recognised, names the
  likely cause, and tells the person what to try. It does not blame the network. The
  shipped wording, which may be reworded only if it still does those three things: "You
  signed in, and the app was not recognised on the very next request. That usually means
  this browser is not keeping the session cookie: check that cookies are allowed for this
  site, then try signing in again."
- The existing sentences in `#notice-unlinked` and `#notice-offline` are untouched, which
  `test_the_document_says_what_an_unlinked_account_sees` already pins.
- Exactly one of the four notice paragraphs is visible at any moment, and every state
  change goes through the one function that hides all four and shows one.
- `#notice-problem` is filled through `textContent`, never `innerHTML`, so a server message
  containing `<` renders as that character.
- `#notice-problem` is cleared when any other paragraph is shown, so a sentence from an
  earlier failure is never left sitting behind a later one.
- `wire()`'s `onUnauthenticated` handler passes what it is handed to `showGate`, so the
  gate carries the server's sentence for a `session_invalid` and stays blank for a
  `not_authenticated`. `showGate` itself is unchanged.
- `wire()`'s `onOffline` handler picks the paragraph from `kind` alone: `offline` to
  `#notice-offline`, `sign-in-not-kept` to `#notice-not-kept`, anything else to
  `#notice-problem`, falling back to `#notice-offline` when `say` is empty so a refusal
  with an unreadable body never shows a blank curtain.
- `submitted()`'s early return branches on `kind` and no longer contains
  `error.status === 0 || error.status >= 500`. It speaks for `signed-out` and `refused`,
  and stays quiet for every kind that already raised a curtain, so the gate is never pulled
  over a notice.
- **No file under `app/` other than `app/api.js` contains a comparison against
  `error.status`, `response.status` or an HTTP status number.** A reviewer can grep for it.
- `client.onerror` in `app/app.js` still shows the offline paragraph when `api.js` itself
  fails to load, so the one path with no error object at all still works.

**The harness**

- `a_403_that_is_not_member_not_linked_is_not_the_not_linked_screen` is rewritten and
  renamed: the boot 403 `csrf_failed` now raises the notice with the server's sentence
  printed in `#notice-problem`, and the gate hidden. The comment stops presenting a fall
  through as what ships.
- `a_session_that_dies_between_sign_in_and_session_read_returns_to_a_blank_gate` turns red
  and is **updated in this same change, never reverted**. Its replacement asserts: the
  notice is up, `#notice-not-kept` is the visible paragraph, the gate is hidden,
  `#gate-error` is empty and hidden, `#gate-submit` is enabled again, `cachedSession()` is
  null, and the request list is unchanged. The "KNOWN DEFECT, PINNED ON PURPOSE" comment is
  replaced with a description of what now ships and a pointer to this task.
- `a_server_error_is_the_same_screen_as_being_offline` turns red and is rewritten and
  renamed: a 500 now prints the server's generic sentence in `#notice-problem` rather than
  claiming the app cannot reach the server.
- `noticeIsUp` asserts the hidden state of all four notice paragraphs, not two, so a
  scenario that names the paragraph it expects leaves none of the others free to be wrong.
  Every scenario that calls it says which paragraph it expects.
- Scenarios whose fixture used `authentication_failed` for a session read with no cookie
  now use `not_authenticated`, and their assertions are unchanged: a first visit still
  shows a blank gate. `session_invalid` is used for a session that died, and
  `authentication_failed` only for `POST /api/session`.
- New scenarios exist for, each declaring its full `expectRequests` list: a 503
  `no_group_configured` on the session read, asserting the printed sentence names the setup
  command and is character for character what the fixture sent; a 503 `ambiguous_group`,
  asserting both group ids survive; a status at or above 500 that nobody anticipated; a
  status below 500 that nobody anticipated on the session read; a sign out the server
  refuses with 403 `csrf_failed`; a 429 sign-in whose message lands on the gate with no
  curtain over it; a `session_invalid` mid session putting the server's sentence on the
  gate; and a refusal a screen asked for that leaves the app frame up.
- One scenario asserts the handoff itself: it registers its own handler through the shipped
  `window.SplitwiseApi` after boot, drives one further request, and asserts `status`,
  `code`, `message`, `kind` and `say` arrive unchanged. Its comment states that it replaces
  `app/app.js`'s handler for the rest of that scenario and therefore asserts no screen
  state.
- `creating_an_account_that_already_exists_says_so_on_the_gate` and
  `a_refused_sign_in_tells_the_person_why` are still green, unedited. A fix that turns a 409
  or a 401 on `POST /api/session` into a curtain has taken the gate's own message away, and
  these two are what catch it.
- Every code the harness names still appears as a quoted string in `web.py`, which
  `test_every_error_code_the_harness_names_appears_in_web_py` already enforces.
- `SCENARIOS` in `tests/test_shell_behaviour.py` lists every scenario in harness order,
  renames included, and the harness exits 0 against the shipped files.
- `MUTANT_A` and `MUTANT_B` still match their anchors exactly once and still kill
  `a_refused_sign_in_tells_the_person_why` with a failure naming `gate-error`. If either
  anchor no longer matches exactly once after the edits, it is re-expressed in the same
  change to reintroduce the same defect, and its test still asserts exit 1 rather than
  merely non-zero.
- A third mutant is added that puts the fall through back, by making the default arm of the
  classifier do nothing, and the suite kills it: exit 1, at least one of the new scenarios
  failing by name, and `an_unknown_hash_is_replaced_not_pushed` still green.
- `uv run python -m pytest` is green, with nothing skipped and nothing xfailed. No test in
  `tests/test_web_shell.py` needs editing; if one breaks, stop and re-read it rather than
  loosening it.

**The file itself**

- The header comment of `app/api.js` carries the whole contract: the six kinds, the three
  handlers, `say` and its one invariant, the two situations where the words are the
  client's, the two requests whose refusals are escalated, and the classification table. It
  no longer says "Three failure paths" or "One message covers both".
- `app/api.js` still touches no DOM node other than reading `document.cookie`, still reads
  no response header, still does no money formatting or arithmetic, and still keeps nothing
  in browser storage.

## Out of scope

- `app/styles.css`. The two new paragraphs reuse `curtain-text`, so this file is not
  touched at all and one of the three files the sibling holds stays completely clear.
- Any change under `src/splitwise_lite/`, including new statuses, new codes and reworded
  messages. The classification is written to match `web.py`, not the other way round.
- Rewording `#notice-unlinked` or `#notice-offline`, and printing the server's sentence on
  the not-linked screen. The standing copy there is fuller than the server's and nobody has
  reported it.
- Reading response headers, `Retry-After` included, and any countdown built on one.
- Retries, backoff, request queueing, an offline write buffer, and any service worker
  fallback response for `/api`.
- Localising, shortening or rewriting server messages for display.
- A fourth handler registration such as `onProblem`. `onOffline` covers it and the
  paragraph is chosen from `kind`.
- The feed's and the balances screen's own failure states, and any of the three screens'
  own copy.
- Bumping `VERSION` in `app/sw.js`. An installed client keeps serving the cached shell
  until somebody does, so raise it at merge time with whichever of the concurrent changes
  lands last.
- Anything in the add screen's section of `app/app.js` or `app/index.html`. That is #11's.

## Constraints

- Edit exactly five files: `app/api.js`, `app/app.js`, `app/index.html`,
  `tests/shell_harness.mjs` and `tests/test_shell_behaviour.py`.
- **The edits to the two shell files are surgical and confined to named places**, because
  #11 (expense entry) is being built at the same time in those same files and #14 is also
  in flight. A reviewer checks the diff touches these and nothing else:
  * `app/index.html`: the `#notice` block only, gaining two paragraphs.
  * `app/app.js`: `showNotice()`, the `onUnauthenticated` and `onOffline` registrations
    inside `wire()`, and the early return condition in `submitted()`. Four places, all
    inside the gate block, none of them in the feed, balances or add regions.
- **`app/api.js` is the only place that classifies a response.** Widening the file list
  does not widen that rule. `app/app.js` gains a handler that displays what it is handed
  and picks a paragraph from `kind`; it must not gain an `if (error.status === ...)`, an
  `if (error.code === ...)`, or any comparison against an HTTP status number. The existing
  status check in `submitted()` goes, and no new one appears anywhere.
- No new dependency of any kind. No npm, no `package.json`, no `node_modules`. The harness
  keeps importing `node:vm`, `node:fs`, `node:path` and `node:url` and nothing else.
- `app/api.js` stays the only file under `app/` that calls `fetch` or names an API path,
  which `tests/test_web_shell.py::test_only_the_api_client_calls_the_back_end` enforces.
- `app/api.js` gains no access to the document beyond the existing `document.cookie` read,
  and holds no user-facing prose. Standing copy lives in `app/index.html`.
- The handler is called before the returned promise rejects, synchronously in the same
  turn, as it is today. `MUTANT_B` exists because deferring it by one macrotask lets a
  caller's message be written and then blanked.
- Every string a screen puts on the page goes in through `textContent`. No `innerHTML`
  anywhere under `app/`.
- No new copy contains a currency symbol, which
  `test_no_shell_file_prints_a_currency_symbol` enforces over `app/index.html` and
  `app/app.js`.
- No test is skipped or marked xfail to make the suite green, per
  `.claude/rules/testing.md`. Run it with `uv run python -m pytest`; plain `uv run pytest`
  fails on this machine.
- Money crosses `app/api.js` as a formatted string and is passed straight through,
  unchanged from task 9a.
