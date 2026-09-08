# Task 44: the empty roster message

**Closes GitHub issue #44.** The branch is `task-44` and this file is named by issue number.
There is no backlog task behind it: `plans/backlog.md` names no task 44, checked by searching
that file for `44` and finding nothing.

**Depends on:** task 10 (the expense entry screen), landed. Task 16 (the incompleteness
signal) landed in `a595330` and is not a dependency, but its decision 4 is the precedent this
task is measured against, so it is argued with below rather than cited.

**On measurement, and what is a read rather than a run.** Bash was not available to the agent
that wrote this file, and neither was `gh`, so **no command was run**: the issue text was not
fetched, and no `pytest`, `git` or `rg` invocation produced any number here. Everything
numeric or symbolic below was read out of the working tree with file reads and content
searches, and every such fact carries the `path:line` it was read from so the engineer can
re-run the check rather than trust it. Where a property would do instead of a number, a
property is stated. Two numbers that matter are given with their source and must be
re-measured before being relied on: see "Numbers that were read, not run" in Constraints.

**On duplicated guarantees.** `plans/tasks/60-65-67-checks-that-could-not-fail.md` records what
happens when one claim is written into four documents and pinned by none. Each guarantee below
is stated **once**, where it is implemented, and a criterion that wants to restate one points
at it by number. If review adds a duplicate, delete the duplicate rather than correcting both.

---

## The defect, restated from the code

Read from `app/app.js:1145`-`:1175`, `app/app.js:782`-`:797` and `app/index.html:202`-`:239`.

The add screen holds three roster-state sentences, at most one visible, toggled by
`addRosterState(which)` (`app/app.js:799`):

| element | text as committed | source |
| --- | --- | --- |
| `add-roster-busy` | `Fetching the people in this group.` | `app/index.html:202` |
| `add-roster-error` | `The people in this group did not arrive. Nothing you have typed is lost.` | `app/index.html:207` |
| `add-empty-roster` | `This group has no members yet, so there is nothing to record.` | `app/index.html:213` |

and three save-refusal sentences, at most one visible, toggled by `addShowError(which)`
(`app/app.js:771`). One of them is `add-error-roster` (`app/index.html:236`):

> `The people in this group have not arrived yet, so this cannot be saved.`

`addSubmitted` shows it whenever `addRoster === null || addRoster.length === 0`
(`app/app.js:1094`). The two togglers are independent, so the pair
(`add-empty-roster`, `add-error-roster`) can both be up, and one reachable path puts them
there: a Save tapped while the roster read is in flight, followed by a roster that arrives
**empty**. `addLoadRoster`'s success handler returns at `app/app.js:1159` before reaching
`addRosterArrived()` at `app/app.js:1162`, so the refusal is never withdrawn and the screen
reads:

> This group has no members yet, so there is nothing to record.
> The people in this group have not arrived yet, so this cannot be saved.

The first is true. The second is false and contradicts it.

**The issue's analysis is adopted and not relitigated:** moving `addRosterArrived()` above the
early return delays the contradiction by one tap, because the next Save re-enters
`app/app.js:1094` with `addRoster.length === 0` and shows the same stale sentence again. The
copy is wrong, not the placement.

**Which combinations are actually reachable, checked rather than assumed.** Of the four
pairings of the two flags, three are already correct and only one is the defect:

* Roster in flight, Save tapped: `add-roster-busy` plus the refusal. Both true.
* Roster read failed, Save tapped: `add-roster-error` plus the refusal. Both true, because
  `addRosterState('error')` at `app/app.js:1151` and `:1173` also skips `addRosterArrived()`
  and the sentence is still true there.
* Roster arrived non-empty: `addRosterState('')` then `addRosterArrived()`
  (`app/app.js:1161`-`:1162`) takes the refusal down. Correct today.
* **Roster arrived empty, Save already tapped: the defect.**

So the fix must not disturb the first three.

---

## The decision on the state model, and the argument

**Decision: the precedent applies, and its transportable half is that the contradiction is
made impossible rather than avoided by ordering. Here that is done by removing the cause from
the refusal, not by adding a fourth state or a third element.** `add-error-roster` becomes one
sentence that is true in every state where the roster is unusable and that asserts nothing
about which state that is. The cause continues to be stated in exactly one place, the roster
panel, which is already single-valued.

Task 16's decision 4 chose a three-valued `state` over a boolean plus a nullable count because
the pair can express `stale, and I do not know how stale`, and a feature whose job is to stop
the app sounding confident must not have a state that sounds confident about nothing. What
that decision made unrepresentable was the **incoherent** combination, not co-occurrence. Its
own criterion 28 is explicit about the difference, read from
`plans/tasks/16-incompleteness-signal.md:550`: at most one of `balances-stale` and
`balances-never` is ever shown, because those two contradict, while `balances-quiet-block`
carries an independent `hidden` flag and co-shows with either. Task 16 shipped a screen that
shows two of its three new elements at once, deliberately.

Applied here, the test is not "are two elements visible" but "do two claims contradict".
`add-empty-roster` and `add-error-roster` answer different questions: what the screen knows
about the roster, and what the tap just did. Both answers belong, and the alert is the only
one of the two that a screen reader announces on the tap, because `add-error` carries
`role="alert"` (`app/index.html:233`) and `add-empty-roster` is a plain `.add-note`. Removing
the alert in the empty case would answer a tap with silence.

**Why not one refusal sentence per roster state.** That is the other option the issue names,
and it is rejected. Three refusals would put the cause in two places: `add-roster-busy` and a
waiting refusal both saying the read is in flight, `add-empty-roster` and an empty refusal both
saying the group has nobody. Two copies of one claim with nothing forcing them to agree is the
defect family this repository has already paid for, recorded under "Four copies, not three" in
`plans/tasks/60-65-67-checks-that-could-not-fail.md` and cited as the reason for the
one-guarantee-one-place rule at `plans/tasks/16-incompleteness-signal.md:11`. It also costs
three new ids, three new `hidden` flags and a fourth thing every call site has to remember,
where the present design already has exactly two togglers each of which is single-valued.

**Why not a single unified roster state variable in `app/app.js`.** Tempting, and it would be
the literal transposition of task 16's `state` enum. It is rejected because it buys nothing
here: `addRosterState` (`app/app.js:799`) and `addShowError` (`app/app.js:771`) are each
already single-valued, and the refusal is raised from exactly one call site
(`app/app.js:1095`) under exactly one condition (`app/app.js:1094`). There is no second writer
to bring into line. Merging them would be a refactor of a working screen in service of a copy
bug, and it would change behaviour on the two paths that are correct today.

**What this costs, stated honestly.** In the empty case the screen shows two sentences that
overlap in meaning: the group has nobody, and the tap could not be saved. That redundancy is
accepted. The alternative is a tap answered by silence, and on a screen whose whole job is to
record something, a Save that appears to do nothing is worse than a sentence somebody has
already read.

---

## The copy

**`add-error-roster` reads exactly:**

> `The app has nobody to record this expense against, so it cannot be saved.`

Why this sentence and not another:

* **It scopes the claim to the app, not to the group.** "There is nobody to record this
  against" would be false while the roster is in flight, because the group does have people
  and only the app does not know them yet. That is the same class of error as "have not
  arrived yet" in the empty case, one state over, and it is the reason the shorter wording was
  rejected.
* **It names no cause,** so it cannot be wrong about one. Waiting, failed and empty are three
  different situations and the sentence distinguishes none of them, because the sentence above
  it already does.
* **`record an expense against somebody` is established vocabulary in this codebase,** read at
  `app/app.js:1262`: "one tap on Save records Sam's expense against Ali."
* **`The app ...` is established voice on this screen and its siblings,** read at
  `app/index.html:65` ("The app cannot reach the server right now"), `:85` ("This app needs
  JavaScript") and `:108` ("The app only knows what people enter").
* **`this expense` rather than `this`,** because `add-error` is a live region and an alert may
  be announced with no surrounding context.
* It contains no digit, no `$`, `£`, `€` or `%`, and none of `Loading`, `loading`, `skeleton`
  or `spinner`, so `test_the_committed_add_markup_invents_no_data`
  (`tests/test_add_screen.py:399`) passes unedited. It contains none of `settled`, `balanced`,
  `square`, `owes`, `owed`, `debt`, `up to date` or `all clear`, so
  `test_no_copy_on_this_screen_says_anything_about_balances` (`tests/test_add_screen.py:472`)
  passes unedited.

**The one alternate considered, recorded so review does not re-derive it:**
`Nobody is available to record this expense against, so it cannot be saved.` Shorter and less
self-referential, and rejected for the first bullet above: with `The app` dropped, the
sentence reads as a claim about the flat rather than about what the screen holds, and that
claim is false for as long as the roster is in the air.

The other three roster sentences are unchanged, verbatim.

---

## Goal

A person who taps Save before the roster is usable is told that the save did not happen, in a
sentence that is true whichever of the three reasons applies, so the add screen can no longer
show a message saying the roster has not arrived beside a message saying the roster arrived
empty. The cause is stated in exactly one element, and the refusal states only the consequence.

---

## Acceptance criteria

Each is a yes or no reachable by reading a file or running one command. `REPO` is the worktree
root and every path is relative to it, in POSIX form.

### The sentence

1. `app/index.html`'s `add-error-roster` reads exactly
   `The app has nobody to record this expense against, so it cannot be saved.`, as fixed prose
   in markup, with no `<span>` and no text composed in JavaScript.
2. The other three sentences in the table under "The defect, restated from the code" are
   byte-identical to what is committed today. `test_the_three_roster_states_read_exactly_as_promised`
   (`tests/test_add_screen.py:438`) passes unedited, and any red there means the wrong element
   was edited.
3. `test_the_screens_own_two_refusals_read_exactly_as_promised`
   (`tests/test_add_screen.py:449`) is updated to the new sentence **in the same commit**. It
   keeps `==` against a single string literal: it is not loosened to `in`, to a substring, to
   a regex, to `startswith`, or to a comparison with case or whitespace normalised. Loosening
   it is a FAIL even if the suite is green.

### The ban that says why the sentence is what it is

4. A new test in `tests/test_add_screen.py` asserts that `add-error-roster`'s text contains
   none of these four substrings, compared case-insensitively: `arriv`, `yet`, `fetch`,
   `empty`. Each names one of the three causes, and a refusal that names a cause is a refusal
   that can be wrong about one, which is this issue.
5. **That ban is scoped to `add-error-roster` alone and is never widened to the add section or
   to the document.** Three of its four substrings are required verbatim by a sibling
   sentence, checked by reading them: `add-roster-busy` contains `Fetch`
   (`app/index.html:202`), `add-roster-error` contains `arrive` (`app/index.html:207`), and
   `add-empty-roster` contains `yet` (`app/index.html:213`). A section-scoped version of this
   ban would forbid three strings the screen requires, and would be red the moment it was
   written. The test's own comment says this, with the three elements named.
6. `loading` is **not** in the ban list, and the criterion says why rather than leaving a
   reader to wonder: it is already banned across the whole add section by
   `test_the_committed_add_markup_invents_no_data` (`tests/test_add_screen.py:408`), and one
   guarantee is stated once.
7. **What this check can and cannot do, stated in its own comment.** Under a single-file
   source mutation it can never fire alone, because any change to the sentence also reds the
   exact-text pin in criterion 3. Its value is the two-file edit: a future engineer who
   reworks the copy and updates the pin in the same commit meets this test and has to argue
   with it. The comment says both halves. Criterion 17 is the demonstration.

### What does not move

8. **`addRosterArrived()` (`app/app.js:782`) stays exactly where it is**, after the
   `addRoster.length === 0` early return, and no call to it is added on the empty path or the
   error path. Under the new copy the sentence is still true in both of those states, so
   withdrawing it would answer a tap with silence. This is the fix the issue rejects and
   criterion 18 is what keeps it out permanently.
9. No id is added or removed. `ADD_IDS` (`tests/test_add_screen.py:38`) and `HIDDEN_AT_REST`
   (`tests/test_add_screen.py:71`) are unedited, and the tests driven by them pass unedited.
10. `addShowError` and `addRosterState` keep their current signatures, their current arms and
    their current call sites. No fourth arm, no new state string, no new variable holding a
    roster state. The `if (addRoster === null || addRoster.length === 0)` condition at
    `app/app.js:1094` is unchanged, so a Save with an unusable roster still shows the alert in
    all three states, which the three existing scenarios in criterion 13 already pin.
11. `app/styles.css` is not edited. No class, element or rule is added, so nothing about layout
    changes and no CSS test is touched.

### The comments that quote the retracted sentence

12. Two comments in `app/app.js` are rewritten, and both are load-bearing rather than tidying:
    a. The comment opening `addRosterArrived()` (`app/app.js:783`) currently quotes the
       retracted sentence verbatim: `"The people in this group have not arrived yet" stops
       being true the moment they do`. It is rewritten to quote the new sentence and to say
       what makes it stop being true, which is a roster arriving with somebody in it. Its
       second paragraph, on the clear being scoped to the one child this path owns
       (`app/app.js:789`-`:793`), is kept: it is a separate guarantee and still correct.
    b. A comment is added at the empty early return (`app/app.js:1156`-`:1159`) saying that
       `addRosterArrived()` is deliberately not called there, that the refusal is still true
       with nobody in the roster, and naming issue #44 and the committed mutant, so the
       omission reads as a decision rather than as the bug it used to be.
13. The HTML comment above the three refusals (`app/index.html:231`-`:232`) gains one clause
    saying that `add-error-roster` names no cause because the roster panel above already
    states it, and that the two therefore cannot contradict. Its existing claim, that at most
    one of the three is ever visible, is kept.
14. No rewritten or added comment introduces a token banned over `app/app.js`. The two bans in
    this task's own test file are `weight` (`tests/test_add_screen.py:497`) and
    `valueAsNumber`, `selectedIndex`, `defaultValue` (`tests/test_add_screen.py:505`); others
    are enforced from `tests/test_feed_screen.py`. Running the two add-screen modules is the
    check, not reading this list.

### The behaviour, driven through the shipped files

15. One new scenario is added to `tests/shell_harness.mjs`, named
    `a_save_refused_while_the_roster_loads_still_reads_true_when_the_roster_is_empty`, placed
    immediately after `a_save_refused_while_the_roster_loads_stops_saying_so_once_it_arrives`
    (`tests/shell_harness.mjs:3362`), whose in-flight-submit technique it reuses. It is the
    path the defect lives on, and no existing scenario covers it: the three add-screen
    scenarios that tap Save with an unusable roster each do so in one settled state and none
    of them lands an empty roster on top of a refusal. It does all of this:
    a. boots at `#/add` with a session, answers `GET /api/members` with `EMPTY_ROSTER`
       (`tests/shell_harness.mjs:1181`), and while that read is in flight types an amount and
       dispatches `submit` on `add-form`;
    b. asserts that during the read the three error children are `[false, true, false]`
       through `addErrorsShown` (`tests/shell_harness.mjs:1543`);
    c. asserts that once the empty roster has landed the roster states are
       `[false, false, true]` through `addRosterStates` (`tests/shell_harness.mjs:1537`);
    d. **asserts the three error children are still `[false, true, false]`**, which is the
       assertion criterion 8 exists for and the one MUTANT_I kills;
    e. asserts `add-error-roster`'s `textContent` is the sentence in criterion 1 and
       `add-empty-roster`'s is `This group has no members yet, so there is nothing to record.`,
       so the pair that used to contradict is pinned as the pair that now does not;
    f. asserts the typed amount is still in `add-amount`, and that `add-payer` has no options;
    g. asserts through `expectRequests` that the request list is the session read and one
       members read, with **no** `POST /expenses`.
16. `SCENARIOS` in `tests/test_shell_behaviour.py` (`:42`) gains exactly that one name, in the
    same position, with **every existing entry kept verbatim and in its existing order**, so
    `test_the_harness_reports_exactly_the_declared_scenarios` (`tests/test_shell_behaviour.py:471`)
    stays a pin on the whole list rather than a count anybody maintains.

### That the checks can fail

17. **Every check this task adds is demonstrated capable of failing, and the demonstration is
    recorded** in `plans/mutations/44-the-empty-roster-message.md`, in the seven-key format
    `plans/mutations/README.md` states, with `PYTHONDONTWRITEBYTECODE=1` set on every Python
    run. Three records, and one disclosed deviation:
    a. `app/index.html`, the new sentence replaced by the retracted one. Kills the exact-text
       pin of criterion 3, the ban of criterion 4, and the new scenario's text assertion. The
       verdict states, in order, which checks went red.
    b. `app/index.html`, the new sentence replaced by a different cause-naming sentence that is
       not the retracted one, so the record shows the pin and the ban are not two names for
       one check on one string.
    c. `app/app.js`, the anchor of criterion 18, recorded even though it is also committed,
       because a committed mutant and a recorded one are read by different people.
    d. **The deviation, disclosed rather than smuggled:** the demonstration that criterion 4's
       ban fires *alone* needs the sentence and the pin changed together, and the record format
       admits exactly one `file`. That run is therefore written into this task's Findings
       instead, quoting both edits and the run output, with this criterion named as the reason
       it is not in the mutations file. Recording it as though it fitted the format is a FAIL.
18. **One committed mutant, `MUTANT_I`**, added to `tests/test_shell_behaviour.py` beside
    `MUTANT_A` through `MUTANT_H` (`tests/test_shell_behaviour.py:227`-`:342`), and it is the
    wrong fix made permanent-red: `addRosterArrived()` is called before
    `addRosterState('empty')`, so the empty roster withdraws a refusal that is still true and
    the tap is answered and then silently un-answered.
    * The anchor is the **single line** containing `addRosterState('empty');`, with its leading
      whitespace exactly as committed, and the replacement inserts `addRosterArrived();` and a
      newline before it. One line, not three: `MUTANT_F`'s note
      (`tests/test_shell_behaviour.py:286`-`:293`) and `MUTANT_H`'s
      (`tests/test_shell_behaviour.py:333`-`:337`) both record that a multi-line anchor rots on
      a CRLF checkout, and this working tree is CRLF. `mutated()`
      (`tests/test_shell_behaviour.py:480`) asserts the anchor matches exactly once; if it does
      not, re-express the mutant and never weaken it.
    * It qualifies under all three of `plans/mutations/README.md`'s tests, and the mutant's
      comment says so in the shape `MUTANT_H`'s does. It is the only evidence criterion 15d
      bites, because that assertion passes the moment it is written. It survives against the
      code as it was before this task, being the fix the issue analysed and rejected. And it
      leaves a working app with one behaviour broken: `a_group_with_no_members_says_so_and_saves_nothing`
      (`tests/shell_harness.mjs:3058`) taps Save after the roster has landed, so it is
      unaffected and stays green under the mutant, and that is asserted.
    * `UNRELATED` (`tests/test_shell_behaviour.py:347`) survives it, and is asserted to, which
      is the named control every other mutant test uses.
    * The mutant's test asserts the **right** failure and not merely a failure, in the shape
      `test_mutant_a_...` uses (`tests/test_shell_behaviour.py:523`): a substring of the failing
      assertion's own label. That substring is taken from the run's output, not invented ahead
      of it, because the label is chosen by whoever writes the scenario.
    * At most one committed mutant, per that file's cap, and the PR states the run cost it adds.
19. The section header `# --- The six mutants ---` (`tests/test_shell_behaviour.py:477`) is
    already wrong before this task, since `MUTANT_A` through `MUTANT_H` is eight. It is changed
    to a form that carries **no number**, so it cannot go stale again. Not "nine".

### The documents

20. `plans/tasks/10-expense-entry-screen.md` carries a dated correction that **quotes what it
    retracts**, in the shape the corrections in `plans/tasks/16-incompleteness-signal.md`
    already use. Two of its lines are now false and both are named: the copy criterion at
    `plans/tasks/10-expense-entry-screen.md:340`-`:341`, which requires the retracted sentence
    verbatim, and the sentence at `:437`-`:438` describing that refusal as covering "a save
    before the roster has arrived or with an empty roster", which is the two-cause reading this
    task removes. The correction quotes both, states the new sentence, and names issue #44. The
    old text is not deleted.
21. `plans/mutations/44-the-empty-roster-message.md` is the one new file outside
    `plans/tasks/`, and `tests/test_suite_integrity.py`'s parametrised checks over
    `TESTS.rglob("*.py")` gain **no** case, because this task adds no file under `tests/`. QA's
    arithmetic in criterion 23 says so explicitly rather than leaving it to be inferred.
22. **`SHELL_DIGEST` in `app/sw.js:35` is set to the twelve hex characters
    `test_the_recorded_digest_matches_the_files_it_covers` prints when it fails, pasted
    verbatim.** `VERSION` stays `'v4'` (`app/sw.js:34`) and `SHELL` keeps its nine entries
    (`app/sw.js:41`-`:49`, read one path per line: `index.html`, `styles.css`, `app.js`,
    `api.js`, `manifest.json`, and four under `icons/`). Exactly two of those nine change,
    `index.html` and `app.js`, so that test fails once and its message is the whole fix. Never
    invent the digest and never bump `VERSION` to clear it. The digest as committed today is
    `26859757a810`; if it is still that after the change, nothing was edited.
23. QA records, and the PR states: the passed count on the branch, the count on the base it
    reconciles against, and the arithmetic between them, which is `+1` scenario from criterion
    16 and `+1` mutant test from criterion 18 and `+1` ban test from criterion 4, and nothing
    else. `0 failed, 0 skipped, 0 xfailed`.

---

## The browser gap

**Nothing in this project has ever been verified in a browser.** `tests/shell_harness.mjs`
runs the real `app/index.html`, `app/app.js` and `app/api.js` under Node's `vm` against a
stubbed DOM and a stubbed `fetch`. This issue is about **what a person reads on a screen**, so
the split matters more here than usual.

**What the suite really judges.** Which of the six elements are hidden at each point on the
path, the exact text each holds, that the alert survives the empty roster landing, that no
`POST` goes out, that the typed amount is kept, and that the committed markup holds the
sentence character for character. That is the whole of criteria 1 to 23 and it is enough to
close the defect as reported.

**What no check here can judge, and what therefore has no criterion above.** Whether two
sentences at once read as complementary or as noise. Whether the alert and the standing note
are visually distinguishable, one being `.add-error-text` and the other `.add-note`. Whether
the sentence still leaves Save within one short scroll at 320px with the keypad up. Whether a
screen reader announces a live region whose text is unhidden rather than newly written.
Whether "The app has nobody to record this expense against" reads, to a flatmate who has never
seen this file, as a statement about the app rather than about the flat.

**These are recorded as NOT RUN.** No verdict in this task depends on any of them, and
**recording an unrun browser check as "pass" is a FAIL**, as is writing a criterion whose only
honest verdict is "looked at the code and it seemed fine".

The mechanism already exists and is not reinvented: **the five questions above are added to
issue #80**, which is open for one dated manual sweep and already carries six such items. This
task adds to it, opens no second mechanism, writes no hand checklist of its own, and does not
block on it.

---

## Out of scope

* **Any change to `src/`.** No domain code, no `web.py`, no wire field. The Flask-absent
  guarantee is untouched because nothing under `src/` is opened.
* **Any change to `app/api.js`.** No call is added or removed, so `API_SURFACE`
  (`tests/test_web_shell.py:1328`) is unedited and
  `test_the_api_client_offers_exactly_the_named_calls` (`:1575`) passes unedited.
* **Any change to `app/styles.css`, `app/manifest.json` or the worker's logic.** Only
  `SHELL_DIGEST` moves in `app/sw.js`.
* **Merging `addShowError` and `addRosterState`, or introducing a roster-state variable.**
  Argued against in "The decision on the state model".
* **A refusal sentence per roster state, and any new id under `#screen-add`.** Argued against
  in the same place.
* **Disabling `add-submit` when the roster is unusable.** Every refusal on this screen is shown
  rather than prevented, which is the decision `app/index.html:152` records for `novalidate`,
  and a disabled control announces nothing to the person who tapped it.
* **A retry control in the empty state.** `add-roster-retry` sits inside `add-roster-error`
  (`app/index.html:206`-`:210`), so an empty roster offers no retry today. Leaving the screen
  and returning re-reads. Changing that is a different argument about a different element.
* **Rewriting the three roster-state sentences,** including `add-empty-roster`, which is
  correct as it stands and is the sentence the fixed screen leans on.
* **`CLAUDE.md` and `README.md`.** No capability arrives or leaves, so no bullet moves between
  `What works today` and `What does not exist yet`, and `WORKS_TODAY` and `NOT_YET`
  (`tests/test_web_shell.py:1355` and `:1488`) are unedited.
* **`src/splitwise_lite/staleness.py:162` and `tests/test_shell_behaviour.py:318`,** which both
  describe issue #44's shape as the reason task 16 chose a three-valued state. Both are already
  written about what the issue *reported*, in the past, so neither becomes false when the issue
  is fixed, and rewriting them would put a `src/` file in a task that otherwise never opens one.
* **Issue #70's unanchored `pytest.raises(match=)` pins,** and **re-verifying `MUTANT_A`
  through `MUTANT_H`.** One mutant is added; the existing ones are left alone.
* **A new dependency, in either language.** `pyproject.toml` and `uv.lock` are byte-identical
  to the base.

## Would be a separate issue

Written down here rather than smuggled into a criterion. None of these is built.

* **Telling the person what to do about an empty roster.** The screen says the group has no
  members and stops; it never names `setup_group.py`, and whether an end-user screen should is
  a product question nobody has asked.
* **Re-reading the roster from the empty state,** so a group that gains its first member while
  somebody is looking at the add screen recovers without a navigation.
* **The same audit on the balances screen,** which has its own empty-roster sentence at
  `app/index.html:353` and its own failure message, and has not been checked for a pair that
  can contradict.
* **A shared helper for the two screens' empty-roster copy,** deliberately not built: task 10
  records at `app/app.js:715` that names in that block are prefixed because sibling branches
  edit the same file, and a shared helper is a shared edit.

---

## Constraints

* **Files edited: exactly these.** Nothing else, in either direction.
  * `app/index.html` (one sentence, one comment clause)
  * `app/app.js` (two comments, no executable line)
  * `app/sw.js` (one line, `SHELL_DIGEST`)
  * `tests/test_add_screen.py` (one pin updated, one test added)
  * `tests/shell_harness.mjs` (one scenario)
  * `tests/test_shell_behaviour.py` (one `SCENARIOS` entry, `MUTANT_I` and its test, one
    header)
  * `plans/mutations/44-the-empty-roster-message.md` (new)
  * `plans/tasks/10-expense-entry-screen.md` (the correction in criterion 20)
  * this file, if it needs correcting
* **The two sentences this issue is about are pinned by exact-text tests in
  `tests/test_add_screen.py`.** Changing either means changing its test in the same commit,
  deliberately, and never loosening it to a substring. Criterion 3 carries this for the one
  sentence that changes; criterion 2 carries it for the three that do not.
* **`tests/test_add_screen.py` may not claim a rendering behaviour.** Its own docstring
  (`tests/test_add_screen.py:10`-`:17`) records that PR #30 shipped such a test passing two
  mutants that reintroduced the bug it claimed to cover, and confines the file to facts about
  committed markup and bans over source text. Criteria 1, 4 and 9 are markup facts and belong
  there. Criteria 8 and 15 are behaviour and belong in the harness, which drives the shipped
  files. **A check about a module that never opens that module is not a check about that
  module**, and a test that reads `app/app.js` as text and concludes the empty path is fixed
  would be exactly that.
* **No test binds a socket, spawns a shell, or writes anywhere but `tmp_path`.**
* Tests run with `uv run python -m pytest`, never plain `uv run pytest`, which fails on this
  machine with an access-denied spawn error. `PYTHONDONTWRITEBYTECODE=1` on every run.
  `node` 20 or later is a test-time requirement and the JavaScript half still runs.
* **Do not run the full suite in one go while iterating.** It exceeds the ten-minute agent
  watchdog under contention. Chunk by module, get counts from `--collect-only -q`, and let CI
  be the full-suite oracle. Both legs, `ubuntu-latest` and `windows-latest`, must be green, and
  a PR whose base has moved is brought up to date and re-run, because a stale shell digest
  surfaces at the merge commit.
* **Numbers that were read, not run.** Bash and `gh` were both unavailable to the agent that
  wrote this file, so re-measure these two before relying on either:
  * **`API_SURFACE` holds sixteen names.** Counted from the literal at
    `tests/test_web_shell.py:1328` to `:1348`, one quoted string per line, none wrapped:
    `ApiError`, `onUnauthenticated`, `onNotLinked`, `onOffline`, `session`, `cachedSession`,
    `signUp`, `signIn`, `signOut`, `members`, `expenses`, `addExpense`, `balances`, `debt`,
    `addSettlement`, `decideSettlement`. That file's own dated correction at `:1477`-`:1483`
    agrees, and records that the same literal has been reported as fourteen in one brief and
    fifteen in an in-file comment, which is three figures for one list and is the whole
    argument for measuring. This task changes `app/api.js` not at all, so the number only
    matters if somebody tries to reconcile it; confirm with
    `uv run python -m pytest tests/test_web_shell.py -k api_client` before trusting any figure,
    including this one.
  * **`SHELL` holds nine entries and `SHELL_DIGEST` is `'26859757a810'`,** read at
    `app/sw.js:41`-`:49` and `app/sw.js:35`. The digest is expected to change; the count is not.
* **The whole suite total is not stated anywhere in this document,** deliberately. Criterion 23
  asks QA to measure it and show the arithmetic, which is the only form this repo trusts.

## Size

**Small, with an evidence tail that is the larger half.** No number below was produced by a
command, because none was available; each is a property or a count of items this document
itself enumerates, and the commands to confirm them are named.

* **The product change is two lines and three comments.** One sentence in `app/index.html`, one
  digest line in `app/sw.js`, and no executable line of `app/app.js` changes at all. That last
  point is the estimate: this is a copy fix with a behavioural pin around it, not a refactor.
* **The test change is one updated pin, one new ban test, one new harness scenario and one new
  mutant test.** Four items, three files.
* **The expensive part is criteria 17 and 18:** three recorded mutation runs, one disclosed
  two-file run in Findings, and one committed mutant that has to be shown to kill the right
  assertion and to leave the named control green. Budget for that rather than for the edit, and
  do not shorten it by reading the code instead of breaking it.
* **Commands behind the estimate, for the engineer to run rather than for this document to
  quote:** `uv run python -m pytest tests/test_add_screen.py --collect-only -q` and the same for
  `tests/test_shell_behaviour.py`, for the before-and-after counts criterion 23 reconciles;
  `uv run python -m pytest tests/test_web_shell.py -k digest` for the one line criterion 22
  needs; and `git diff --stat` against the base for the edit's real size.

---

## Findings

Filled in before the PR was opened. Bash and `gh` were both available to the engineer, so
**every figure below was produced by a command on this branch**, and the two numbers this
document flagged as read-not-run were re-measured before being relied on. The task
specification's own line references were re-checked too, one at a time.

### The re-measurement, and what it found

`Bash` and `gh` worked throughout and neither went away mid-task.

* **The issue text was fetched** with `gh issue view 44` and matches the account in "The
  defect, restated from the code" in every particular, including the two sentences quoted
  and the analysis that moving `addRosterArrived()` above the early return only delays the
  contradiction by one tap.
* **`API_SURFACE` holds sixteen names**, confirmed rather than trusted:
  `sed -n '1328,1348p' tests/test_web_shell.py | grep -c '"'` prints `16`, and
  `uv run python -m pytest tests/test_web_shell.py -k api_client` is green with
  `app/api.js` unedited. The figure in Constraints was right; the fourteen and the fifteen
  reported elsewhere were not.
* **`SHELL` holds nine entries and `SHELL_DIGEST` was `'26859757a810'`**, both as read,
  at `app/sw.js:41`-`:49` and `app/sw.js:35`. `VERSION` was `'v4'` at `:34` and is
  `'v4'` still.
* **Every `path:line` this document cites was re-read and every one was correct.** The
  three roster sentences at `app/index.html:202`, `:207` and `:213`; the refusal at `:236`;
  the comment above the three refusals at `:231`-`:232`; `addShowError` at `app/app.js:771`,
  `addRosterArrived` at `:782` with its quoted comment at `:783` and its scoping paragraph
  at `:789`-`:793`; `addRosterState` at `:799`; the submit condition at `:1094` and its call
  site at `:1095`; the empty early return at `:1155`-`:1159` and the two lines it skips at
  `:1161`-`:1162`; the error arm at `:1173`. In the tests: `ADD_IDS` at
  `tests/test_add_screen.py:38`, `HIDDEN_AT_REST` at `:71`, the invents-no-data check at
  `:399` with its `loading` ban at `:408`, the three-roster pin at `:438`, the two-refusal
  pin at `:449`, the balances-copy ban at `:472`, and the two token bans at `:497` and
  `:505`; `EMPTY_ROSTER` at `tests/shell_harness.mjs:1181`, `addRosterStates` at `:1537`,
  `addErrorsShown` at `:1543`, the sibling scenario at `:3362` and the settled empty-roster
  scenario at `:3058`; `SCENARIOS` at `tests/test_shell_behaviour.py:42`, the mutants at
  `:227`-`:342`, `UNRELATED` at `:347`, the stale header at `:477`, `mutated()` at `:480`
  and mutant A's substring assertion at `:523`. **No difference was found between any figure
  in this document and the working tree**, which is the answer to the instruction to report
  any difference as itself a finding: there was none.
* **`plans/backlog.md` names no task 44**, confirmed with `grep -n "44" plans/backlog.md`,
  which prints nothing at all.

### The new digest

`SHELL_DIGEST` is `'f8453329c392'`, pasted verbatim from the line
`test_the_recorded_digest_matches_the_files_it_covers` printed when it failed. It was never
computed by hand and `VERSION` was not bumped. Exactly two of the nine precached files
changed, `index.html` and `app.js`; `app/styles.css` was not edited and neither was
`app/api.js`.

### The count, and the arithmetic

`uv run python -m pytest --collect-only -q`, whole suite, both measured with a command:

| | master (`a595330`) | branch | delta |
|---|---|---|---|
| whole suite | 2673 | 2676 | **+3** |
| `tests/test_add_screen.py` | 27 | 28 | +1 |
| `tests/test_shell_behaviour.py` | 186 | 188 | +2 |
| `tests/test_suite_integrity.py` | 58 | 58 | 0 |
| `tests/test_web_shell.py` | 153 | 153 | 0 |

Master's figure was taken in a throwaway detached worktree at `a595330`, removed
afterwards, rather than read out of a sibling worktree or taken on trust. The `+3`
reconciles exactly as criterion 23 requires: `+1` scenario (criterion 16), `+1` mutant test
(criterion 18), `+1` ban test (criterion 4), and nothing else. `tests/test_suite_integrity.py`
gains no case, because this task adds no file under `tests/`.

Run whole and unfiltered on the branch: `tests/test_add_screen.py` **`28 passed`**,
`tests/test_shell_behaviour.py` **`188 passed`**, `tests/test_suite_integrity.py`
**`58 passed`**, `tests/test_web_shell.py` and `tests/test_feed_screen.py` green. **The
whole suite was deliberately not run locally**, per the standing instruction that it exceeds
the agent watchdog under contention; CI is the full-suite oracle and both legs were read on
the head SHA.

**The full-suite figure, from CI on `d678519`** (run `34190615082`, whose `headSha` was
checked against `git rev-parse HEAD` rather than assumed), both legs green:

* `ubuntu-latest`: `2676 passed in 141.63s`
* `windows-latest`: `2676 passed in 265.53s`

`0 failed, 0 skipped, 0 xfailed` on both, and 2676 is master's 2673 plus this task's three,
which closes criterion 23's arithmetic against a measured number rather than a predicted
one. This paragraph was added in the commit after `d678519`, so it quotes the run on its
parent; the run on the head that carries it changes only a document under `plans/`.

`MUTANT_I` costs **1.20s**, measured with
`uv run python -m pytest tests/test_shell_behaviour.py -k mutant_i --durations=3`. The
module went from 15.7s to 19.4s across this task's three additions.

### The demonstration that could not fit the record format (criterion 17d)

Criterion 4's ban can never fire **alone** under a single-file mutation, because any edit to
the sentence also reds the exact-text pin of criterion 3. Showing it fire alone needs both
files changed together, and `plans/mutations/README.md`'s format admits exactly one `file`
per record. So this run is here rather than there, named as a deviation, exactly as
criterion 17d requires. Recording it as though it fitted the format would have been a FAIL.

The two edits, applied together on a committed tree:

`app/index.html`

```
-      <p class="add-error-text" id="add-error-roster" hidden>The app has nobody to
-        record this expense against, so it cannot be saved.</p>
+      <p class="add-error-text" id="add-error-roster" hidden>The group is empty, so
+        this cannot be saved.</p>
```

`tests/test_add_screen.py`, inside `test_the_screens_own_two_refusals_read_exactly_as_promised`

```
-        "The app has nobody to record this expense against, so it cannot be saved."
+        "The group is empty, so this cannot be saved."
```

`PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_add_screen.py -q` then
reported, whole module and unfiltered:

```
FAILED tests/test_add_screen.py::test_the_roster_refusal_names_none_of_the_three_reasons_it_covers
1 failed, 27 passed
```

One failure out of 28, and it is the ban. The pin is green, because it was updated in the
same edit — which is precisely the two-file commit this check exists for. The failure text:

```
E           AssertionError: empty
E             'empty' is contained here:
E               the group is empty, so this cannot be saved.
```

Both files were reverted with `git checkout --` afterwards and the module returned to
`28 passed`. Every mutation on this task was applied to a **committed** tree, so no revert
could discard work.

### Collateral in the mutation runs, disclosed

Every red scenario also reds two whole-harness exit-code checks in
`tests/test_shell_behaviour.py`, `test_the_harness_exits_zero_against_the_shipped_files`
(`:486`) and `test_the_harness_finds_app_from_its_own_location` (`:1032`), because both run
every scenario and assert the process exited 0. They are listed in each record's `kills`,
since a record that omitted two of three failures would not reproduce, and the record says
plainly that they are collateral rather than evidence: neither names the defect.

### The browser gap: five items, NOT RUN

The five questions in "The browser gap" were **not run**, cannot be run by this suite, and
no verdict in this task depends on any of them. They are added to issue #80, which is open
for one dated manual sweep. Recording any of them as a pass would have been a FAIL, and none
is recorded as one. In particular, whether "The app has nobody to record this expense
against" reads as a claim about the app rather than about the flat is the load-bearing
question behind the chosen copy, and it is unverified by anything here.
