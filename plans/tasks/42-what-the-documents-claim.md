# Task 42: what the documents claim

**Depends on:** 8, 10, 11, 12 (the three screens, all complete, on `master`), 32 (error
classification), 43 (the entry guard and the draft), 46 (the shell precache digest), 49
(CI). All of that is assumed present and none of it is re-opened here.
**Consumed by:** every agent that reads `CLAUDE.md` before touching this repo, which is
all of them.

Closes GitHub issue #42. `plans/backlog.md` has no entry for this and this task does not
add one; the issue is the backlog entry and this file is the implementable version.

## Why this task exists

Two documents tell a new reader that the app shows nothing, and a committed test keeps
them saying it.

`CLAUDE.md:3-4`:

> Shared expense ledger for small groups. A Python back end, plus an installable mobile
> web shell in `app/` **whose three screens are still placeholders**.

`README.md:6-9`:

> Status: the domain layer is under way, and one process now serves the mobile web shell
> and a JSON API on the same origin. You can sign up, sign in and be told who you are.
> **The three screens are still placeholders: they show no expenses, no members and no
> balances, because tasks 10, 11 and 12 fill them.**

Every emphasised clause is false. Task 10 filled the add screen, task 11 the feed and
task 12 the balances screen. Task 32 gave the shell an error contract, task 43 a session
gate that holds a draft across signing back in, task 46 a precache digest and task 49 a
CI that runs it all on two platforms. `README.md` also still says the domain layer is
"under way", which understates tasks 2 to 9a, all merged.

`tests/test_web_shell.py:1131` is what keeps it that way:

```python
def test_no_document_claims_the_shell_shows_real_data() -> None:
    combined = claude_md() + readme()
    assert "placeholder" in combined.lower()
```

That test was correct when it was written. The screens were empty, and it stopped the
documents promising data that did not exist. The screens are full now, so the same
assertion enforces an underclaim: the honest edit to either file fails the suite until
this test moves with it. Its name still describes an intent that inverted underneath it.

The cost is not cosmetic. `CLAUDE.md` is the file every agent reads before touching this
repo, so this claim has been in the context of every task for weeks, and three screen
tasks each declined to fix it because each was scoped to its own screen
(`plans/tasks/10-expense-entry-screen.md` names both documents under "Nothing else
changes either").

## What is actually true today

Verified against the shipped files on this branch, not from memory. This is the source
material for the prose the criteria below ask for.

**The gate.** `app/index.html` ships `#gate` with an email field, a password field, a
submit button and a "Create an account" toggle, plus `#notice` carrying four standing
paragraphs: not linked to a member, cannot reach the server, the sign-in was not kept,
and one empty paragraph that carries the server's own sentence. `app/app.js` wires them
to `api.signUp`, `api.signIn`, `api.signOut` and `api.session`. Signing up on its own
grants nothing: `refresh()` shows the unlinked notice for a session with no member row.

**The feed.** `#feed-list` is filled from `GET /api/expenses` and `GET /api/members` on
every entry to `#/feed`. Each row carries payer, amount, description and participants,
and expands in place to a detail listing every share, the total, a note when the payer is
not sharing, who recorded it, and the date and time. Four states, exactly one visible: in
flight, empty, failed, list. Read only.

**The add screen.** `#add-form` takes an amount (text with a decimal keypad, never a
number input), an optional description of at most 500 characters, a payer picked from the
roster, and one of three split modes: Equally, Some people, Uneven amounts. Those are the
spec's three modes. The resolver's weight mode is reachable through the API and is
deliberately not on the screen. Saving posts to `POST /api/expenses` and echoes the
server's own 201 body. The amount field is focused on entry, before the roster is asked
for. A draft survives a curtain and signing back in as the same person, and is cleared
for a different one (task 43).

**The balances screen.** `#balances-net` and `#balances-transfers` are filled from
`GET /api/balances` on every entry, from strings the server has already formatted.
Nothing is stored and nothing is tappable. A standing note says the figures come only
from what was recorded.

**Install and offline.** `app/manifest.json` plus `app/sw.js` precache the nine shell
files, so the app installs to the home screen and the shell opens offline. `/api` is
never cached, so offline the app opens and then says it cannot reach the server. Secure
context only, so `localhost` or `127.0.0.1`.

**What does not exist.** Backlog task 13 (transfer drill-down): `SplitwiseApi.debt` and
`GET /api/debts/{debtor}/{creditor}` both exist, from task 12a, and no screen calls
either; `app/app.js` contains no `.debt(`. Backlog tasks 14 and 15 (mark as paid,
receiver confirmation): no route in `src/splitwise_lite/web.py`, no method on the client,
no control. Backlog task 16 (the incompleteness signal): nothing reports staleness;
`app/index.html` says so in a comment and names the task. Backlog task 17 (expense
correction): expenses cannot be edited or voided from any screen.

Note the numbering. GitHub issue numbers and `plans/backlog.md` task numbers are not the
same in this range. The documents cite backlog task numbers only, and the criteria below
pin them.

## The decision: what replaces the inverted test

Deleting the test and putting nothing back leaves nothing guarding the documents, and the
hazard is real: five backlog features are open, and the natural next mistake is a
document that promises one of them. So something replaces it. The shape matters more than
the fact.

### Rejected: the same test facing the other way

A test asserting that `README.md` says "not built yet", or that neither document says
"mark as paid", is the identical trap re-armed. Two reasons, and the second is decisive.

First, it pins vocabulary rather than truth, which is exactly how one word outlived its
premise and started enforcing a lie.

Second, a forbidden phrase makes the honest sentence unwriteable. The truthful document
has to say "you cannot mark a payment as paid yet", and that sentence contains the phrase
a negative test would forbid. A guard that refuses the honest sentence is the defect in
this issue, reproduced.

### Rejected: a test that reads GitHub issue state

The suite binds no socket, opens no port and reaches no network, and
`tests/test_dev_server.py` says so in its own docstring. A test that asked GitHub which
issues are open would make the suite depend on a token, on the network and on CI having
credentials, to check a document. It would also go red for reasons that are not about
this repository's contents. `plans/backlog.md` is the in-repo statement of the plan and
is versioned alongside the claim; that is the anchor to use.

### Chosen: the documents declare their claims, and the claims are checked against `app/`

Both documents gain two short bullet lists under fixed headings: what works today, and
what does not exist yet. Each bullet begins with a bold key. The keys, and nothing else
about the prose, are pinned in `tests/test_web_shell.py`, alongside evidence drawn from
the shipped files:

* a **works today** key carries substrings that must be **present** in named files under
  `app/`, so a capability cannot be claimed while the machinery for it is absent;
* a **does not exist yet** key carries substrings that must be **absent**, or an empty
  rule with a written reason naming the mechanism that does cover it;
* the client's public surface, the keys of `window.SplitwiseApi` in `app/api.js`, is
  pinned as a set. `app/api.js` is the only file under `app/` allowed to call the back
  end, a rule `test_only_the_api_client_calls_the_back_end` already enforces, so any new
  server-backed capability must add a name to that object. The failure message for that
  test is what points the next person at the two lists.

Three properties make this different from the test it replaces. Its subject is the
relation between a claim and the code, not a word. It fails in both directions: a claim
without machinery, and machinery without a claim. And a prose rewrite does not touch it,
so the honest sentence is always writeable.

### What is lost, stated rather than dropped

`test_no_document_claims_the_shell_shows_real_data` is **deleted**, not renamed. What
goes with it is the requirement that the word `placeholder` appear somewhere across the
two files. Nothing else: the rule it was written for, that no document promises a ledger
the app cannot show, is carried by the replacement in a form that is checked against
`app/`. The word itself has no value now that no screen is a placeholder.

### What the replacement does not catch, stated plainly

The guard reads two delimited lists. A false sentence written in free prose elsewhere in
either document is not caught, and criterion 33 makes QA demonstrate that rather than
leave it as a comfortable assumption. Two mitigations, both partial and both honest: the
lists are where a reader looks for capability claims, and the test refuses a bullet in
either section that does not carry a bold key, so a claim cannot be smuggled in as an
unkeyed bullet.

One entry has no automatic tripwire at all. The incompleteness signal (backlog task 16)
could be computed on the client from data already in the feed payload, adding no API
method and needing no new client call. Other tests would go red (the section id sets are
pinned by set equality) but none of them would point anybody at the documents. That is
written into the entry's own reason rather than papered over.

## Goal

`CLAUDE.md` and `README.md` describe the app that exists: three screens that read the
live ledger behind a sign-in gate, what still needs `setup_group.py` and a linked account
before anything shows, and the five backlog capabilities that genuinely do not exist yet.
The test that required the word `placeholder` is gone, replaced by a guard whose subject
is the relation between what the documents claim and what is in `app/`, so a claim
without machinery and machinery without a claim are both red.

## Acceptance criteria

Each is a yes or no a QA agent can reach by reading a file or running a command. `REPO`
is the worktree root and the branch is `task-42`. Criteria 29 to 34 are the ones that
establish the replacement guard actually bites.

### `CLAUDE.md`

1. The opening sentence no longer says the screens are placeholders. The word
   `placeholder` does not appear in `CLAUDE.md` at all.
2. The opening paragraph states, truthfully and in one or two sentences: a Python back
   end, plus an installable mobile web shell in `app/` whose three screens read the ledger
   from the JSON API, behind a sign-in gate.
3. `CLAUDE.md` contains a heading whose text is exactly `What works today` and a heading
   whose text is exactly `What does not exist yet`, each at level 2, 3 or 4.
4. Under `What works today`, a bullet list of exactly these five bold keys, spelled
   exactly: `Sign in`, `The expense feed`, `Adding an expense`, `Balances`,
   `Install and open offline`. Each bullet is one or two lines of prose after the key.
   Between the first bullet and the next heading there is nothing but bullets, their
   continuation lines and blank lines. QA checks each bullet against the app, and each
   states at least this much:
   * `Sign in`: create an account, sign in, sign out. An account that no member row is
     linked to is told so and shown no ledger.
   * `The expense feed`: every expense the group has recorded, newest first, with payer,
     amount, description and who shared it, and a row expands in place to each person's
     share, the total, who recorded it and when. Read only.
   * `Adding an expense`: amount, optional description, payer and one of the spec's three
     split modes. It does not claim the resolver's weight mode, which the API takes and
     no screen offers.
   * `Balances`: each member's net position and the shortest list of payments that clears
     the group, worked out on every read and never stored. Nothing on that screen is
     tappable.
   * `Install and open offline`: it installs to the home screen and the shell opens
     offline, on `localhost` or `127.0.0.1` only, and it says that the API is never
     cached, so offline the app opens and then reports that it cannot reach the server.
     An offline expense cannot be recorded.
5. A lead-in sentence before that list says that all of it needs a group created by
   `scripts/setup_group.py apply` and an account linked with `setup_group.py link`, and
   that signing up on its own shows the "nobody has linked you" notice and no ledger.
6. Under `What does not exist yet`, a bullet list of exactly these five bold keys,
   spelled exactly: `Transfer drill-down`, `Mark as paid`, `Receiver confirmation`,
   `The incompleteness signal`, `Expense correction`. Same shape rule as criterion 4, and
   each bullet states at least this much:
   * `Transfer drill-down`: a suggested payment cannot be opened to see the debts and
     expenses behind it. See criterion 8 for the half that does exist.
   * `Mark as paid`: nothing records that a payment happened.
   * `Receiver confirmation`: and so nothing confirms one, which means a debt that has
     been settled in real life stays on the list until somebody records the expense side
     of it. The two bullets read as a pair, because one without the other would be worse
     than neither: the spec's rule is that a balance moves only when the receiver
     confirms.
   * `The incompleteness signal`: nothing says how stale the ledger is or who has logged
     nothing. The balances screen's standing note, that the figures come only from what
     was recorded, is the whole of what the app says about it today.
   * `Expense correction`: an expense cannot be edited or voided from any screen.
7. Each of those five bullets contains exactly one citation of the form
   `(backlog task N)`, with N being 13, 14, 15, 16 and 17 respectively. QA checks each
   number against the matching `## N.` heading in `plans/backlog.md` and confirms the
   heading is about the capability the key names. No GitHub issue number appears in
   either list, in either document.
8. The `Transfer drill-down` bullet says that the API can already answer what a debt is
   made of and that no screen asks it. That is the one entry whose back end half exists,
   and a bullet that omits it is inaccurate in the direction this task is about.
9. The `scripts/` bullet under `Where things live` names `watch-issues.sh` as well as the
   three Python commands, or says plainly that the enumeration covers the Python commands
   only. Today it names three files and four exist.
10. No paragraph added anywhere in `CLAUDE.md` contains the phrase `no build step`. See
    criterion 26.
11. Neither of these two exact lowercase strings appears anywhere in `CLAUDE.md`:
    `not built yet`, `nothing to run yet`. Both are asserted absent by tests written
    before this one. This is the trap most likely to bite: `Not built yet` is the obvious
    heading and `is not built yet` is the obvious bullet prose, and either one fails
    `test_claude_md_no_longer_says_the_front_end_is_missing`, whose name gives no hint
    that it is what broke. Criterion 3 fixes a heading that avoids it, and the bullets
    say "does not exist yet" or "no screen offers it" instead. Nothing narrower than
    those two exact strings is forbidden: prose must stay writeable, which is the whole
    complaint against the test this task deletes.
12. The `Run the app` command line is unchanged. The issue asked for it to be rewritten;
    it was already corrected before this task, and
    `test_claude_md_names_the_real_run_command` passes on it today. QA confirms it still
    reads `uv run python scripts/serve.py --store ledger.sqlite3` and still names
    `http://localhost:8000`.

### `README.md`

13. The `Status:` paragraph at lines 6 to 9 is gone. Nothing in `README.md` says the
    screens are placeholders, and the word `placeholder` does not appear in the file.
14. Nothing in `README.md` says the domain layer is "under way". What replaces it names
    what is built: the domain layer, the store, accounts and sessions, the group setup
    command, the HTTP API and all three screens.
15. `README.md` carries the same two headings as criterion 3 and the same two lists, with
    the same ten bold keys and the same five backlog citations. The prose differs from
    `CLAUDE.md` freely; the keys and the numbers do not.
16. `README.md`'s lists sit above `## Setup`, so a reader meets what the app does before
    how to install it.
17. The rest of `README.md` is unchanged: `## Setup`, `## Set up the group`,
    `## Run the app`, the stuck-worker paragraph, `## Test` and the CI paragraph all
    survive with their commands intact, including the positional port argument, which QA
    confirms against `scripts/serve.py`'s parser rather than assuming.
18. No paragraph added anywhere in `README.md` contains the phrase `no build step`, and
    the exact lowercase string `no product code yet` does not appear.

### The other documents

19. `plans/spec.md`'s `**Status:** Draft, pre-build` line is replaced with one that is
    true: the decisions are locked and the build is under way, with a pointer to
    `README.md` for what is built and `plans/backlog.md` for the plan. The `**Date:**`
    line and every other line of that file are untouched.
20. `plans/backlog.md` gains exactly one sentence in its preamble saying that the file is
    the plan and not a status report, and that `README.md` says what is built today. No
    task entry in it is edited, renumbered or given a status marker. QA confirms the diff
    over that file is one added sentence.
21. Nothing under `plans/tasks/` other than this file is edited. Those files are the
    record of a task as it was specified, and rewriting their tense would destroy that.

### The replacement guard

22. `tests/test_web_shell.py::test_no_document_claims_the_shell_shows_real_data` is
    deleted. It is not renamed, not commented out, not marked skip or xfail, and the
    word `placeholder` is asserted by nothing anywhere in the suite.
23. `tests/test_web_shell.py` gains exactly these five tests, in its `# --- Docs` section,
    whose comment is extended to say the section now also holds the capability claims:
    a. `test_the_api_client_offers_exactly_the_named_calls`: parses the keys of the
       `window.SplitwiseApi = { ... }` object literal in `app/api.js` and asserts they
       equal a literal set in the test. The parse takes the text from
       `window.SplitwiseApi = {` to the end of the file and matches keys by their
       indentation, `^    ([A-Za-z][A-Za-z0-9]*):` in multiline mode, because the values
       are functions and brace matching would need a JavaScript parser, which is a
       dependency. A regex that silently matched nothing would fail this test rather than
       pass it, because the literal it is compared against is not empty. That set is
       exactly `ApiError`,
       `onUnauthenticated`, `onNotLinked`, `onOffline`, `session`, `cachedSession`,
       `signUp`, `signIn`, `signOut`, `members`, `expenses`, `addExpense`, `balances`,
       `debt`, fourteen names, and QA confirms the list against `app/api.js`.
    b. `test_both_documents_agree_on_what_works_today`: parses the bold keys under the
       `What works today` heading in both files and asserts each file's set equals the
       other's and equals the keys of the `WORKS_TODAY` literal.
    c. `test_both_documents_agree_on_what_does_not_exist_yet`: the same for the second
       list, plus the backlog citation per bullet, which must agree between the two files,
       must match the number recorded in the literal, and must have a `## N.` heading in
       `plans/backlog.md`.
    d. `test_every_capability_the_documents_claim_is_in_the_shell`: every `WORKS_TODAY`
       entry's evidence substrings are present in the named files under `app/`.
    e. `test_nothing_the_documents_call_missing_is_in_the_shell`: every
       `NOT_YET` entry's evidence substrings are absent, and every entry carries a
       non-empty prose reason.
24. The two literals hold exactly this evidence, and QA confirms each pair by reading the
    named file:
    * `Sign in`: `id="gate-form"` in `app/index.html`, `signIn:` in `app/api.js`.
    * `The expense feed`: `id="feed-list"` in `app/index.html`, `expenses:` in
      `app/api.js`.
    * `Adding an expense`: `id="add-form"` in `app/index.html`, `addExpense:` in
      `app/api.js`.
    * `Balances`: `id="balances-transfers"` in `app/index.html`, `balances:` in
      `app/api.js`.
    * `Install and open offline`: `navigator.serviceWorker.register('sw.js')` in
      `app/app.js`, `var SHELL = [` in `app/sw.js`.
    * `Transfer drill-down`: `.debt(` absent from `app/app.js`.
    * `Mark as paid`, `Receiver confirmation`, `Expense correction`: no substring rule,
      and a reason naming `test_the_api_client_offers_exactly_the_named_calls` as the
      mechanism that covers them, because a client call is the only way any of them can
      reach the server.
    * `The incompleteness signal`: no substring rule, and a reason saying plainly that
      nothing in the suite would catch this one and why.
25. Each of the five tests fails with prose rather than a bare assertion. QA reads all
    five messages while performing criteria 29 to 32 and confirms each says which file is
    wrong, what was expected, and what to do next: if the capability landed, move its
    entry between the two lists in **both** documents and update the literal here; if it
    did not, the document is claiming something that does not exist. The surface test's
    message names the added or removed method and says to check both lists before
    changing the literal.
26. All six existing document tests pass unedited:
    `test_claude_md_names_the_real_run_command`,
    `test_claude_md_no_longer_says_the_front_end_is_missing`,
    `test_claude_md_says_where_the_shell_and_the_scripts_live`,
    `test_the_readme_documents_how_to_run_the_app`,
    `test_the_no_build_step_claim_carries_its_caveat_where_it_is_made`,
    `test_one_document_says_how_to_clear_a_stuck_service_worker`.
    The fifth is the fragile one: `paragraph_naming()` asserts that **exactly one**
    paragraph in each file contains `no build step`, and that paragraph must still
    contain `VERSION` and `app/sw.js`. It has already caught two tasks. QA confirms by
    reading the diff that no added paragraph repeats that phrase.
27. `paragraph_naming()`, `claude_md()`, `readme()` and `RUN_COMMAND` are unedited.
28. No test outside `tests/test_web_shell.py` is added, edited, renamed or deleted, and
    no test anywhere is loosened, skipped or marked xfail.

### The guard bites

Each probe below edits the working tree, proves a result, and reverts. None is committed.
QA runs `git status` after each and records that the tree is clean.

29. **An overclaim in a document turns the suite red.** In `README.md` only, move the
    `Mark as paid` bullet out of the second list and into the first, so the document now
    claims a capability that does not exist. `uv run python -m pytest` goes red on
    `test_both_documents_agree_on_what_works_today` and
    `test_both_documents_agree_on_what_does_not_exist_yet`. QA quotes both messages.
    Revert, and the suite is green again with the same passed count. **This is the
    criterion the task exists to satisfy: the guard catches a false claim.**
30. **An invented capability turns the suite red.** In `CLAUDE.md` only, add a sixth
    bullet to the first list, `- **Recurring expenses** are entered once and repeat.`
    The same two tests go red. Revert; green.
31. **A capability arriving without the documents moving turns the suite red.** In
    `app/api.js`, add one method to the `window.SplitwiseApi` object, for instance
    `markPaid: function () { return call('POST', '/settlements', {}); },`. The suite goes
    red on `test_the_api_client_offers_exactly_the_named_calls`, and QA reads the message
    and confirms it points at the two lists. It also goes red on
    `test_the_recorded_digest_matches_the_files_it_covers`, which is expected: `api.js`
    is precached, so any edit to it moves `SHELL_DIGEST`. QA records both failures, then
    `git checkout -- app/api.js` and confirms the suite is green and
    `git status app/` is clean.
32. **A screen reaching for the drill-down turns the suite red.** In `app/app.js`, add
    one line inside the balances block that calls `api.debt('a', 'b')`. The suite goes red
    on `test_nothing_the_documents_call_missing_is_in_the_shell` (and on the digest test,
    again expected). QA quotes the message, reverts, and confirms green and a clean tree.
33. **The limit of the guard, demonstrated rather than assumed.** Add one false sentence
    to `README.md`'s free prose, outside both lists, for example a line under
    `## Run the app` saying "You can mark a payment as paid from the balances screen."
    The suite stays **green**. QA records that this is the known and stated limit of the
    guard, then removes the sentence. A criterion that is expected to pass by staying
    green is recorded as such in the QA note, not skipped.
34. **The before state.** Every probe in 29 to 32 is run once against the tip of `master`
    as well, where each is green, since the guard does not exist there. QA records that in
    one sentence. That is the before and after that shows this task changed something.

### The suite and the diff

35. `uv run python -m pytest` on a clean tree reports `2176 passed`, `0 failed`,
    `0 skipped`, `0 xfailed`. That is master's 2172, minus the one deleted test, plus the
    five added. If the implementer merged or split a test and the count differs, the
    deviation and its count are recorded in this file under `## Deviations` and QA checks
    the recorded number instead.
36. `app/sw.js` is byte identical to `master`. `SHELL_DIGEST` does not move, because
    neither `CLAUDE.md` nor `README.md` is one of the nine precached files, and nothing
    under `app/` is changed by this task. Nobody needs to recompute anything, and
    `test_the_recorded_digest_matches_the_files_it_covers` passes unedited.
37. `git diff --stat` against the base shows exactly six paths: `CLAUDE.md`, `README.md`,
    `plans/spec.md`, `plans/backlog.md`, `tests/test_web_shell.py` and
    `plans/tasks/42-what-the-documents-claim.md`. Nothing under `app/`, `src/` or
    `scripts/`, and no new file under `tests/`.
38. `ISSUE-42.md` does not exist in the worktree and does not appear in the branch's
    final tree. It was scratch input to this spec and is not part of the change.
39. `pyproject.toml` and `uv.lock` are byte identical to `master`. No dependency is
    added, in any group.
40. Both CI legs, `test (ubuntu-latest)` and `test (windows-latest)`, are green on the
    pull request, and the branch is up to date with its base before merging. QA quotes
    the two summary lines.

## Out of scope

* **Anything under `app/`, `src/` or `scripts/`.** This task changes documents and the
  tests that pin them. The probes in criteria 31 and 32 edit `app/` in the working tree
  and revert; nothing lands.
* **The stale comments inside `app/`.** They are real and they are listed under
  `## Findings` below. Fixing them is a separate task because every edit to a precached
  file moves `SHELL_DIGEST` and forces a cache retirement, which is a strange thing to
  spend on a comment, and because two of the files are the ones sibling branches touch
  most.
* **A status column, checkboxes or a done marker in `plans/backlog.md`.** A second place
  that records what is built is a second place that goes stale, and this issue is what
  that costs. One sentence pointing at `README.md`, and no more.
* **Rewriting `plans/spec.md` beyond its status line.** Its "Version one" list, its
  out-of-scope cuts and its two open questions are statements of intent and are still
  accurate as intent. Open question 1 is still open. Question 2 is still flagged inside
  backlog task 17.
* **Rewriting the completed task files under `plans/tasks/`.**
* **A test that reads GitHub issue state, or any network access from the suite.**
* **A negative phrase test**, of the form "neither document contains the words X". Argued
  against above; it makes the honest sentence unwriteable.
* **A capability list for the back end or the CLI.** The two lists describe what a person
  gets from the app. `scripts/setup_group.py --help` documents itself.
* **A CHANGELOG, a version number, a status badge or a roadmap file.**
* **Bumping `VERSION` in `app/sw.js`**, or touching the digest. Criterion 36.
* **Fixing anything the probes turn up in `app/`.** If criterion 31 or 32 reveals a
  defect, it is recorded and filed, not fixed here.

## Constraints

* **Files edited: exactly six**, the ones in criterion 37, plus the deletion of
  `ISSUE-42.md`.
* **`tests/test_web_shell.py` keeps its own rules**: standard library only, nothing
  imports `splitwise_lite`, and every path is resolved from `REPO` rather than from the
  working directory. Reading `plans/backlog.md` from that file is new and is allowed; it
  sits in the `# --- Docs` section with `CLAUDE.md` and `README.md`.
* **No new dependency, of any kind**, and no new file under `tests/`. `re` and `pathlib`
  are already imported there.
* **No parser.** The list format is read with one regex per list. If the implementer
  finds themselves writing a Markdown parser, the format is wrong, not the parser.
* **The three forbidden lowercase strings in criterion 11**, plus `no product code yet`
  in `README.md`. They are asserted absent by tests written before this one, and the
  obvious heading wording collides with the first of them.
* **The `no build step` paragraph is not duplicated** in either file. Criterion 26.
* **No test is skipped or marked xfail**, per `.claude/rules/testing.md`.
* Run the suite with `uv run python -m pytest`. Plain `uv run pytest` fails on this
  machine with an access-denied spawn error.
* Every probe in criteria 29 to 34 is reverted, and `git status` is clean before the
  branch is pushed.

## Findings to file as follow-up issues

Found while writing this spec, out of scope here, and worth an issue each so they are not
rediscovered a third time.

1. **`app/` carries comments that describe merged branches as in flight.** `app/app.js:21`
   says "tasks 10 to 12 fill a screen by editing its section"; `app/app.js:169` says "the
   task 12 branch is adding its own block to this same file"; `app/app.js:680` and
   `app/app.js:684` say "two sibling branches are editing this same file" and "which both
   sibling branches also need"; `app/app.js:1259` repeats it; `app/sw.js:4` says "task
   10's data cannot go stale". All three tasks landed. The comments that name *open*
   tasks are accurate and stay: `app/app.js:150` (tasks 16 and 17), `app/app.js:1524`
   and `app/index.html:240` (tasks 13 and 16), `app/app.js:1654` (task 14). Any fix moves
   `SHELL_DIGEST`, so the issue should say so and expect the pasted line.
2. **`plans/tasks/49-continuous-integration.md` criterion 23 pins `2061 passed`** and
   criterion 45 pins the same number. The suite is at 2172. That file is a record and
   should not be rewritten, but a reader running its criteria today will get a false
   negative. Worth one line in that file saying the count was correct on the day, or
   worth leaving alone deliberately. Raised, not decided.

## Notes for whoever lands backlog task 13, 14, 15, 16 or 17

Part of your task is now three edits in one commit: move the entry from
`What does not exist yet` to `What works today` in **both** documents, and move it between
the two literals in `tests/test_web_shell.py`, giving it evidence that must now be present
rather than absent. The suite tells you when you have missed it, in every case except the
incompleteness signal, which is written up honestly under "What the replacement does not
catch" above.

If your feature makes one of the ten keys the wrong name, rename it in both documents and
in the literal. The keys are labels, not vocabulary anybody is defending; what the tests
are defending is that the label and the code agree.

## Size

Two lists of five bullets in each of two documents, one line in `plans/spec.md`, one
sentence in `plans/backlog.md`, one deleted test and five added ones, roughly ninety lines
of Python counting the two literals and the failure messages. If it grows a helper module,
a fixture, a second test file or a Markdown parser, it has gone wrong.

The work that is not typing is criteria 29 to 34: six probes run against the real tree,
each reverted, each quoted in the QA note. Without them this task has produced a guard
that is believed to work, which is the same category of thing as the test it replaced.

## Deviations

The suite count is not one of them: `uv run python -m pytest` reports `2176 passed`,
exactly the number criterion 35 predicts, with nothing skipped and nothing xfailed. What
follows is four places where a criterion's wording and the observed result differ. None
of the criteria were changed; this is the record of what running them produced.

1. **Criterion 30 turns one test red, not two.** The probe adds a sixth bullet,
   `**Recurring expenses**`, to `CLAUDE.md`'s first list only, so only
   `test_both_documents_agree_on_what_works_today` can see it; the second list is
   untouched and its test stays green. Criterion 29 does turn both red, because moving a
   bullet changes both lists. The point of criterion 30, that an invented capability
   turns the suite red, holds.

2. **Criterion 34's "each is green" holds for probes 29 and 30 only.** On `master`,
   probes 31 and 32 turn `test_the_recorded_digest_matches_the_files_it_covers` red,
   because it is task 46's guard and predates this task: any edit to a precached file
   moves the digest. Neither of this task's guards exists there, so nothing on `master`
   notices the new capability or the new call, which is the before state the criterion is
   after. Probes 29 and 30 are green on `master` outright.

3. **Criterion 4's "one or two lines of prose after the key" is not reachable** alongside
   the content its own sub-bullets require. `Install and open offline` alone has to carry
   the home screen, the offline shell, the `localhost` restriction, the uncached API, the
   message that follows and the expense that cannot be recorded. Every bullet in both
   documents is written as tightly as that content allows and runs to three or four
   wrapped lines. Nothing in the suite pins bullet length.

4. **Criterion 22's "the word `placeholder` is asserted by nothing anywhere in the
   suite"** is satisfied for the documents, which is what the criterion is about: no test
   asserts either document contains it. Two tests written earlier assert the word is
   *absent* from a screen, `tests/test_add_screen.py::test_the_placeholder_is_gone_from_the_document`
   and `tests/test_feed_screen.py::test_the_feed_screen_no_longer_carries_a_placeholder`,
   and criterion 28 forbids touching any test outside `tests/test_web_shell.py`. They are
   left alone.
