# Task 42: what the documents claim

**Depends on:** 8, 10, 11, 12 (the three screens, all complete, on `master`), 32 (error
classification), 43 (the entry guard and the draft), 46 (the shell precache digest), 49
(CI). All of that is assumed present and none of it is re-opened here.
**Consumed by:** every agent that reads `CLAUDE.md` before touching this repo, which is
all of them.

Closes GitHub issue #42. `plans/backlog.md` has no entry for this and this task does not
add one; the issue is the backlog entry and this file is the implementable version.

## The rule this task learned the hard way

**The guarantee is stated once, where the guard is implemented, and prose refers to it
rather than repeating it.** For this task that one place is the vocabulary block and the
two literals in `tests/test_web_shell.py`. Every sentence in this file that would describe
what the guard catches points there instead of paraphrasing it, and where a paraphrase
existed it has been deleted rather than corrected.

Four review rounds established the need. Round one found a hard-coded count above the
lists; round two amended six criteria; round three swept and found six more, two of them
inside round two's own correction notes; round four found three more, one of which
falsified round three's closing claim that no copy of the guarantee survived. Each round
corrected the copies it was shown and left the others standing. A guarantee restated in
four places is four things that can go stale, and prose has no digest to notice when one
of them does.

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

**Deleted 2026-09-07, after the fifth review of PR #59.** This section held a
forty-eight-line inventory of what each screen does, introduced as verified against the
shipped files. It was a third copy of the two lists in `CLAUDE.md` and `README.md`, and
by the end two of its sentences were the negation of what this file's own criteria
require: it said nothing on the balances screen is tappable, and that `app/app.js`
contains no `.debt(`, while criterion 4 requires the first to be contradicted and
criterion 24 requires `api.debt(` present. Nothing depended on it.

What the app does is in those two lists. What the suite holds them to is
`tests/test_web_shell.py`. What each bullet must state is criteria 4 and 6 below, and
criterion 4 already has QA check every bullet against the running app. This is the rule
at the top of this file applied to the one section that predates it.

## The decision: what replaces the inverted test

Deleting the test and putting nothing back leaves nothing guarding the documents, and the
hazard is real: backlog features are open, and the natural next mistake is a
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
  `app/`;
* a **does not exist yet** key carries substrings that must be **absent**, or an empty
  rule with a written reason;
* the client's public surface, the keys of `window.SplitwiseApi` in `app/api.js`, is
  pinned as a set, and its failure message points the next person at the two lists. What
  that pin does and does not catch is stated above `NOT_YET` in `tests/test_web_shell.py`
  and is deliberately not restated here.

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

Which entries get a tripwire when the capability lands, and which get nothing, varies and
is recorded per entry in `NOT_YET`. It is deliberately not summarised here.

## Goal

`CLAUDE.md` and `README.md` describe the app that exists: three screens that read the
live ledger behind a sign-in gate, what still needs `setup_group.py` and a linked account
before anything shows, and the backlog capabilities that genuinely do not exist yet.
The test that required the word `placeholder` is gone, replaced by a guard whose subject
is the relation between what the documents claim and what is in `app/`.

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
4. Under `What works today`, a bullet list of exactly these six bold keys, spelled
   exactly: `Sign in`, `The expense feed`, `Adding an expense`, `Balances`,
   `Transfer drill-down`, `Install and open offline`. Each bullet is one or two lines of
   prose after the key. Between the first bullet and the next heading there is nothing
   but bullets, their continuation lines and blank lines. QA checks each bullet against
   the app, and each states at least this much:
   * `Sign in`: create an account, sign in, sign out. An account that no member row is
     linked to is told so and shown no ledger.
   * `The expense feed`: every expense the group has recorded, newest first, with payer,
     amount, description and who shared it, and a row expands in place to each person's
     share, the total, who recorded it and when. Read only.
   * `Adding an expense`: amount, optional description, payer and one of the spec's three
     split modes. It does not claim the resolver's weight mode, which the API takes and
     no screen offers.
   * `Balances`: each member's net position and the shortest list of payments that clears
     the group, worked out on every read and never stored. The net figures are read only;
     the suggested payments are not, which the next bullet covers.

     > **Amended 2026-09-07, after the first review of PR #59.** This sub-bullet
     > previously ended "Nothing on that screen is tappable." True against `8651b9d`, and
     > made false by #56, which turns a suggested payment carrying usable provenance into
     > a disclosure button. The net rows are still inert, checked against
     > `balancesNetRow` in `app/app.js`. Nothing in the suite would have prompted this
     > edit: the guard fired on the `Transfer drill-down` bullet only, and this sentence
     > sits in a different bullet, under a capability the guard still reads as working.
     > It was found by reading the screen, and is fixed in both documents. It is a fair
     > example of what these guards do not reach: they pin which capabilities are
     > claimed, never what a bullet says about one.
   * `Transfer drill-down`: a suggested payment opens on the debts it absorbs, from both
     ends, and each of those debts opens in turn on the expenses and settlements behind
     it. The debts arrive with the balances read; what is behind a debt is fetched on
     that row's first expansion, over `GET /api/debts/{debtor}/{creditor}`. A payment
     whose payload carries no usable provenance is drawn inert.

     > **Added 2026-09-07, after the first review of PR #59.** This sub-bullet did not
     > exist: the capability was criterion 6's, where it read "a suggested payment cannot
     > be opened to see the debts and expenses behind it". See the amendment at the end
     > of this criterion for why it moved.
   * `Install and open offline`: it installs to the home screen and the shell opens
     offline, on `localhost` or `127.0.0.1` only, and it says that the API is never
     cached, so offline the app opens and then reports that it cannot reach the server.
     An offline expense cannot be recorded.

   > **Amended 2026-09-07, after the first review of PR #59.** This criterion previously
   > named five keys and omitted `Transfer drill-down`, which criterion 6 placed in the
   > second list. PR #56 shipped the drill-down while this branch was open, and this
   > task's own guard, `test_nothing_the_documents_call_missing_is_in_the_shell`, is what
   > caught both documents still saying it did not exist. The criterion was accurate
   > against `8651b9d`; the world moved underneath it, which is the situation the guard
   > exists to detect. That is the mechanism working, not a defect in the spec. The
   > `Transfer drill-down` sub-bullet and the amended `Balances` sub-bullet above come
   > with the key; criterion 6 loses it, criterion 7 loses its citation, and criterion 24
   > inverts its evidence. The shape rule and the count of prose lines are untouched,
   > and so are four of the six sub-bullets: `Sign in`, `The expense feed`,
   > `Adding an expense` and `Install and open offline`. `Balances` is amended in place
   > above, and `Transfer drill-down` is new.
   >
   > **Corrected 2026-09-07, after the second review of PR #59.** This sentence said
   > "the other five sub-bullets are untouched". Six sub-bullets, one added and one
   > amended, leaves four untouched, not five.
5. A lead-in sentence before that list says that all of it needs a group created by
   `scripts/setup_group.py apply` and an account linked with `setup_group.py link`, and
   that signing up on its own shows the "nobody has linked you" notice and no ledger.
6. Under `What does not exist yet`, a bullet list of exactly these four bold keys,
   spelled exactly: `Mark as paid`, `Receiver confirmation`,
   `The incompleteness signal`, `Expense correction`. Same shape rule as criterion 4, and
   each bullet states at least this much:

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

   > **Amended 2026-09-07, after the first review of PR #59.** This criterion previously
   > named five keys, opening with `Transfer drill-down`, whose sub-bullet read "a
   > suggested payment cannot be opened to see the debts and expenses behind it. See
   > criterion 8 for the half that does exist." Both are gone; the key and its bullet are
   > criterion 4's now. PR #56 shipped the transfer drill-down while this branch was
   > open, and this task's own guard,
   > `test_nothing_the_documents_call_missing_is_in_the_shell`, is what caught both
   > documents still saying it did not exist. The criterion was accurate against
   > `8651b9d`; the world moved underneath it, which is the situation the guard exists to
   > detect. That is the mechanism working, not a defect in the spec.
7. Each of those four bullets contains exactly one citation of the form
   `(backlog task N)`, with N being 14, 15, 16 and 17 respectively. QA checks each
   number against the matching `## N.` heading in `plans/backlog.md` and confirms the
   heading is about the capability the key names. No GitHub issue number appears in
   either list, in either document.

   > **Amended 2026-09-07, after the first review of PR #59.** This criterion previously
   > covered five bullets citing 13, 14, 15, 16 and 17. PR #56 shipped the transfer
   > drill-down while this branch was open, and this task's own guard,
   > `test_nothing_the_documents_call_missing_is_in_the_shell`, is what caught both
   > documents still saying it did not exist; the criterion was accurate against
   > `8651b9d`, and the world moved underneath it, which is the situation the guard
   > exists to detect. That is the mechanism working, not a defect in the spec.
   >
   > Backlog task 13's citation was **dropped**, not moved. Only the second list is
   > citation-checked, by `test_both_documents_agree_on_what_does_not_exist_yet`, so a
   > citation in the first list is neither required nor read, and both `Transfer
   > drill-down` bullets were written without one. `## 13.` still stands in
   > `plans/backlog.md`, and is now the record of a task that shipped.
   >
   > **Corrected 2026-09-07, after the second review of PR #59.** This paragraph said
   > the citation "goes with its bullet into `What works today`". It does not: no
   > citation exists in either file's first list, which `grep -n "backlog task 13"`
   > confirms. The requirement in the criterion above was right; only this account of
   > what happened to task 13's citation was wrong, and being wrong it concealed
   > criterion 15's stale count of five, which is now amended too. A marker written to
   > explain a correction is exactly as capable of being an unchecked claim as the
   > thing it corrects.

8. The `Transfer drill-down` bullet says that a screen asks the debts route, naming
   `GET /api/debts/{debtor}/{creditor}`, and says when: the debts behind a payment arrive
   with the balances read, and the entries behind a debt are fetched on that row's first
   expansion. A bullet that leaves the route unnamed is inaccurate in the direction this
   task is about, and so is one that still calls the capability missing.

   > **Amended 2026-09-07, after the first review of PR #59.** PR #56 shipped the
   > transfer drill-down while this branch was open, and this task's own guard,
   > `test_nothing_the_documents_call_missing_is_in_the_shell`, is what caught both
   > documents still saying it did not exist. The criterion was accurate against
   > `8651b9d`; the world moved underneath it, which is the situation the guard exists to
   > detect. That is the mechanism working, not a defect in the spec.
   >
   > This criterion previously read: "The `Transfer drill-down` bullet says that the API
   > can already answer what a debt is made of and that no
   > screen asks it. That is the one entry whose back end half exists, and a bullet that
   > omits it is inaccurate in the direction this task is about." A screen asks it now,
   > so the criterion is inverted rather than dropped: the route is still the thing the
   > bullet has to name, and what changed is which half of the capability is missing,
   > which is none of it.

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
    the same ten bold keys and the same four backlog citations. The prose differs from
    `CLAUDE.md` freely; the keys and the numbers do not.

    > **Amended 2026-09-07, after the second review of PR #59.** This criterion read
    > "the same five backlog citations". Checked: both files carry `14`, `15`, `16`,
    > `17` under `What does not exist yet` and no citation under `What works today`, and
    > `grep -n "backlog task 13" CLAUDE.md README.md` returns nothing. Four, not five.
    > Falsified by the same merge as criteria 4, 6, 7, 8, 24 and 35, by the same
    > mechanism, and missed by the pass that amended those six. The ten keys are
    > unaffected and were re-counted: six under the first heading, four under the
    > second, in both files.
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
    * `Transfer drill-down`: `api.debt(` present in `app/app.js`, and
      `id="balances-drill-hint"` present in `app/index.html`.
    * `Mark as paid`, `Receiver confirmation`, `Expense correction`: no substring rule,
      and a reason naming `test_the_api_client_offers_exactly_the_named_calls` as the
      mechanism that covers them, because a client call is the only way any of them can
      reach the server. Each reason names which of the strengths defined above
      `NOT_YET` it has, and does not claim a capability cannot arrive without a new
      name. Those definitions live there and are not repeated in this file.
    * `The incompleteness signal`: no substring rule, and a reason saying plainly that
      nothing in the suite would catch this one and why.

    > **Amended 2026-09-07, after the first review of PR #59.** The `Transfer drill-down`
    > line previously read "`.debt(` absent from `app/app.js`", the one absence rule in
    > this task with real teeth. PR #56 shipped the drill-down while this branch was
    > open, that rule fired, and the pair inverts to a presence rule in `WORKS_TODAY`.
    > The reviewer's suggestion is followed: the `app/app.js` needle inverts cleanly, and
    > it is paired with the `app/index.html` id #56 added.
    >
    > The requirement on the three reasons is new too. It said what each reason had to
    > claim; it now says each must name a strength from the definitions above `NOT_YET`
    > and must not claim a capability cannot arrive without a new name.
    >
    > **Amended again 2026-09-07, after the third review.** This marker also carried a
    > summary of the whole interlock, prompt and silence taxonomy, ending "Restoring an
    > interlock needs a substring a capability cannot arrive without, and for the four
    > that remain no such substring is knowable in advance." QA disproved that by
    > building the capability rather than arguing about it: a void route reached through
    > the existing `addExpense` key left
    > `test_the_api_client_offers_exactly_the_named_calls` silent, and re-run here
    > against this suite's own parse the key set stayed at fourteen, unchanged. The
    > summary is **deleted rather than corrected**, under the rule at the top of this
    > file. The taxonomy, and what it means for each entry, is above `NOT_YET` in
    > `tests/test_web_shell.py` and nowhere else.
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
30. **An invented capability turns the suite red.** In `CLAUDE.md` only, add one more
    bullet to the end of the first list, `- **Recurring expenses** are entered once and
    repeat.` `test_both_documents_agree_on_what_works_today` goes red. Revert; green.

    > **Amended 2026-09-07, after the second review of PR #59.** Two corrections, both
    > to the description and neither to the probe. It read "add a sixth bullet", which
    > was right when the first list held five and wrong once criterion 4 took it to six.
    > The ordinal is dropped rather than corrected to "seventh", because nothing in the
    > probe depends on how many bullets are already there and any number written here
    > goes stale the next time the list moves. Deviation 1 was corrected the same way in
    > the same round. Second, "the same two tests go red" was already known to be wrong
    > when this file was written: deviation 1 records that the probe touches the first
    > list only, so the second list's test has nothing to see. The criterion now says
    > what deviation 1 has said since the first run, so the two no longer contradict
    > each other.
31. **A capability arriving without the documents moving turns the suite red.** In
    `app/api.js`, add one method to the `window.SplitwiseApi` object, for instance
    `markPaid: function () { return call('POST', '/settlements', {}); },`. The suite goes
    red on `test_the_api_client_offers_exactly_the_named_calls`, and QA reads the message
    and confirms it points at the two lists. It also goes red on
    `test_the_recorded_digest_matches_the_files_it_covers`, which is expected: `api.js`
    is precached, so any edit to it moves `SHELL_DIGEST`. QA records both failures, then
    `git checkout -- app/api.js` and confirms the suite is green and
    `git status app/` is clean.
32. **A capability vanishing from the shell while the documents still promise it turns
    the suite red.** In `app/app.js`, neutralise the one `api.debt(` call site in the
    balances block. The suite goes red on
    `test_every_capability_the_documents_claim_is_in_the_shell` (and on the digest test,
    expected, because `app.js` is precached). QA quotes the message, reverts, and
    confirms green and a clean tree.

    > **Amended 2026-09-07, after the second review of PR #59.** This criterion read: "A
    > screen reaching for the drill-down turns the suite red. In `app/app.js`, add one
    > line inside the balances block that calls `api.debt('a', 'b')`. The suite goes red
    > on `test_nothing_the_documents_call_missing_is_in_the_shell`." That probe can no
    > longer produce that result. QA ran the old probe and reported that adding the call
    > leaves the named test green and fires only the digest guard, which is what has to
    > happen now that criterion 24 requires `api.debt(` to be **present**. The rule
    > survives inverted, and the inverted probe is what this criterion now describes. I
    > ran that one here before writing this: neutralising the single call site turns
    > `test_every_capability_the_documents_claim_is_in_the_shell` and the digest test
    > red, 2 failed and 133 passed in the doc suite, and the message names the
    > capability, both documents and the missing substring. Reverted, tree clean,
    > `SHELL_DIGEST` unmoved.
    >
    > This is the same falsification as criteria 4, 6, 7, 8, 15, 24 and 35, and reaches
    > the criterion through this task's own amendment rather than through #56 directly:
    > inverting criterion 24 is what made criterion 32 unrunnable.
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

35. `uv run python -m pytest` on a clean tree reports `2262 passed`, `0 failed`,
    `0 skipped`, `0 xfailed`. That is master's 2258 at `369a02a`, minus the one deleted
    test, plus the five added. If the implementer merged or split a test and the count
    differs, the deviation and its count are recorded in this file under
    `## Deviations` and QA checks the recorded number instead.

    > **Amended 2026-09-07, after the first review of PR #59.** This criterion previously
    > read `2176 passed`, "master's 2172, minus the one deleted test, plus the five
    > added", which was correct against `8651b9d`. The base has moved twice since, by #55
    > and #56, and this branch was rebased onto `70f41d3` so that #56's drill-down would
    > meet this task's guard. The arithmetic is unchanged; only the base is. No test was
    > merged or split.
    >
    > **Amended again 2026-09-07, after the fifth review.** `2227` and "master's 2223 at
    > `70f41d3`" were correct against that base. #62 merged and the branch was rebased
    > onto `369a02a`, which criterion 40 requires before merging. Both figures were
    > measured here rather than carried over: `369a02a` in a throwaway worktree reports
    > `2258 passed`, this branch reports `2262 passed`, and the worktree was removed.
    > The arithmetic is unchanged for the third time; only the base is. No test was
    > merged or split in this round either.
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

* **Files edited: the ones criterion 37 names**, plus the deletion of `ISSUE-42.md`.
* **`tests/test_web_shell.py` keeps its own rules**: standard library only, nothing
  imports `splitwise_lite`, and every path is resolved from `REPO` rather than from the
  working directory. Reading `plans/backlog.md` from that file is new and is allowed; it
  sits in the `# --- Docs` section with `CLAUDE.md` and `README.md`.
* **No new dependency, of any kind**, and no new file under `tests/`. `re` and `pathlib`
  are already imported there.
* **No parser.** The list format is read with one regex per list. If the implementer
  finds themselves writing a Markdown parser, the format is wrong, not the parser.
* **The forbidden lowercase strings in criterion 11**, plus `no product code yet` in
  `README.md`. They are asserted absent by tests written before this one, and the obvious
  heading wording collides with one of them. Criterion 11 lists them; this line does not.
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
   10's data cannot go stale". All three tasks landed. Every line number in that list
   was re-checked on 2026-09-07 against `70f41d3` and each still points at the comment
   named.

   The comments that name *open* tasks are accurate and stay. Re-checked the same day,
   because #56 moved most of this file: `app/app.js:150` (tasks 16 and 17),
   `app/index.html:240` (task 16), `app/app.js:376` and `:377` (task 16),
   `app/app.js:2198` (task 16), and `app/app.js:2077`, `:2086` and `:2144` (task 14).
   `app/app.js:1524` and `app/index.html:255` describe task 13 in the past tense, which
   is accurate now that it has shipped. Any fix moves `SHELL_DIGEST`, so the issue should
   say so and expect the pasted line.

   > **Corrected 2026-09-07, after the second review of PR #59.** The open-task list read
   > "`app/app.js:150` (tasks 16 and 17), `app/app.js:1524` and `app/index.html:240`
   > (tasks 13 and 16), `app/app.js:1654` (task 14)". Two things were wrong after #56.
   > Task 13 is not open, and the comment at `app/app.js:1524` now describes it as
   > landed. And `app/app.js:1654` is `balancesNetRow`, not a task 14 comment; the task
   > 14 comments moved to 2077, 2086 and 2144. The first half of this finding, the
   > merged-branch comments, was checked line by line and needed no change.
2. **`plans/tasks/49-continuous-integration.md` criterion 23 pins `2061 passed`** and
   criterion 45 pins the same number, and `plans/tasks/49-continuous-integration.md:57`
   says "the suite is 2061 tests"; all three were re-checked on 2026-09-07. The suite is
   far larger now, and criterion 35 is where that figure lives. That file is a record and
   should not be rewritten, but a reader running its criteria today will get a false
   negative. Worth one line in that file saying the count was correct on the day, or
   worth leaving alone deliberately. Raised, not decided.

## Notes for whoever lands backlog task 14, 15, 16 or 17

Part of your task is three edits in one commit: move the entry from
`What does not exist yet` to `What works today` in **both** documents, and move it between
the two literals in `tests/test_web_shell.py`, giving it evidence that must now be present
rather than absent.

How hard the suite pushes you into those edits varies by capability. Read your entry's
own `reason` in `NOT_YET` before you start: it names which of the three strengths defined
above that literal applies to you, and it is the only place that says so. Do not assume a
red will arrive.

Backlog task 13 is the worked example, because it is the case that actually fired; what
happened is recorded in criterion 4's and criterion 24's markers. The part worth carrying
into your own task: the guard named three edits, and a fourth was needed that nothing
prompted, in a neighbouring bullet the guard reads as correct. Budget for it.

If your feature makes one of the keys the wrong name, rename it in both documents and
in the literal. The keys are labels, not vocabulary anybody is defending; what the tests
are defending is that the label and the code agree.

## Size

Two capability lists in each of two documents, a line in `plans/spec.md`, a sentence in
`plans/backlog.md`, one test deleted and a few added, roughly ninety lines of Python
counting the two literals and the failure messages. The exact shape is criteria 4, 6 and
23 and is not restated here. If it grows a helper module, a fixture, a second test file
or a Markdown parser, it has gone wrong.

The work that is not typing is criteria 29 to 34: six probes run against the real tree,
each reverted, each quoted in the QA note. Without them this task has produced a guard
that is believed to work, which is the same category of thing as the test it replaced.

## Deviations

The suite count is not one of them: the observed run matches criterion 35, which is the
one place the figure is written and which has been amended each time the base moved. What
follows is five places where a
criterion's wording and the observed result differ. Four of them changed no criterion and
are the record of what running them produced. The fifth changed nine, across two rounds,
each under an explicit instruction, and says so.

> **Corrected 2026-09-07, after the second review of PR #59.** This paragraph said "The
> suite count is one of them now" and "criterion 35 predicts `2176`". It was written
> while 35 still said 2176 and was not revisited when 35 was amended to 2227 in the same
> round. With 35 amended the count matches the observed run, so it is not a deviation at
> all.

1. **Criterion 30 turns one test red, not two.** The probe adds a bullet,
   `**Recurring expenses**`, to `CLAUDE.md`'s first list only, so only
   `test_both_documents_agree_on_what_works_today` can see it; the second list is
   untouched and its test stays green. Criterion 29 does turn both red, because moving a
   bullet changes both lists. The point of criterion 30, that an invented capability
   turns the suite red, holds.

   > **Corrected 2026-09-07, after the second review of PR #59.** This said "a sixth
   > bullet", which was right when the first list held five and is wrong now that
   > criterion 4 holds six. The ordinal is dropped rather than moved to "seventh",
   > because nothing here depends on how many bullets the list already has and a count
   > in this sentence would only go stale again. Criterion 30 itself, which does name
   > the position, was amended in the same round.

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
   documents is written as tightly as its own content allows, and the lengths that
   produces were counted on 2026-09-07 rather than estimated: one line at the shortest
   (`Mark as paid` in `CLAUDE.md`) and six at the longest (`Transfer drill-down`, six in
   each file), with most at three or four. Nothing in the suite pins bullet length.

   > **Corrected 2026-09-07, after the second review of PR #59.** This deviation said
   > every bullet "runs to three or four wrapped lines". That was true of the ten bullets
   > it was written against and is not true now: `Transfer drill-down` arrived at six
   > lines with criterion 4's amendment, and `Mark as paid` is one. The deviation's
   > substance, that criterion 4's "one or two lines" is unreachable, is unaffected and
   > is in fact made stronger by the six-line bullet.

4. **Criterion 22's "the word `placeholder` is asserted by nothing anywhere in the
   suite"** is satisfied for the documents, which is what the criterion is about: no test
   asserts either document contains it. As literally worded it is unsatisfiable, and the
   count first recorded here was wrong. There are **four** surviving sites, not two:

   * `tests/test_add_screen.py::test_the_placeholder_is_gone_from_the_document`
   * `tests/test_add_screen.py::test_the_committed_add_markup_invents_no_data`, which
     bans a `placeholder` attribute on any element of the add screen, the amount field
     being the one that would carry a plausible fake `0.00`
   * `tests/test_feed_screen.py::test_the_feed_screen_no_longer_carries_a_placeholder`
   * `tests/test_web_shell.py::test_the_balances_placeholder_is_gone`

   All four assert the word is absent from a *screen*. That is a live and useful
   assertion with nothing to do with what the documents claim, so criterion 22's
   substance is unaffected and leaving them alone is right. The justification first
   recorded here was not, though: "criterion 28 forbids touching any test outside
   `tests/test_web_shell.py`" covers the first three and does **not** cover the fourth,
   which lives in the one file criterion 28 permits editing. It is kept because deleting
   a true assertion about markup would be a loss, not because a criterion protects it.
   (`tests/test_balances.py:1648` uses the word in a comment and asserts nothing.)

5. **Nine criteria were overtaken by a merge, and the branch was rebased onto it.**
   Criteria 4, 6, 7, 8, 24 and 35 in the first amendment round; 15, 30 and 32 in the
   second, after a review and a QA pass each found more of the same. They were written
   against `8651b9d`, where `.debt(` was genuinely absent from `app/app.js`. #56 landed
   backlog task 13 and put it there. Rebasing onto `70f41d3` turned
   `test_nothing_the_documents_call_missing_is_in_the_shell` red, which is this task's
   guard doing the exact thing this task exists to make it do, so the capability was
   moved rather than the rule weakened or deleted.

   **What each amendment changed, and why, is in that criterion's own dated marker.** It
   was itemised here as well, and the second copy drifted: this entry went on asserting
   that backlog task 13's citation moved with its bullet for a full round after criterion
   7's marker had been corrected to say it was dropped. Under the rule at the top of this
   file the itemisation is deleted rather than corrected.

   Two markers written in the first round were themselves wrong and are corrected in
   place, criterion 7's and criterion 4's. A marker is not exempt from the standard it
   enforces.

   All nine were amended in place, each with a dated marker quoting the wording it
   replaced. That was escalated first and not done unilaterally: the task file for a
   branch is authored on that branch, so an engineer editing the criteria their own work
   is judged against removes the only independence the process has, and the right default
   is to flag a false criterion and stop. Each amendment was made only after an explicit
   instruction to make it.

   One result of these rounds is not bookkeeping, and it is recorded where the guard is
   implemented rather than here: QA disproved the claim that a server-backed capability
   must add a name to `API_SURFACE`, by building one that did not. The vocabulary block
   above `NOT_YET` in `tests/test_web_shell.py` carries what that means, entry by entry.
