# Task 49: continuous integration

**Depends on:** 9b (complete, on `master`), 46 (complete, on `master`, PR #47)
**Consumed by:** every task after this one, because every one of them merges

Closes GitHub issue #49. `plans/backlog.md` has no entry for this and this task does not
add one; the issue is the backlog entry and this file is the implementable version.

## Why this task exists

There is no `.github/` directory. Nothing runs `uv run python -m pytest` except a person
remembering to.

Task 46 put a digest of the nine precached shell files into the cache name in `app/sw.js`,
so a shell edit that ships behind a cache nobody retired is a failing test. It is a good
mechanism. Its entire enforcement is one command, typed by whoever happens to be looking.
That is a mechanism guarding a convention, guarded by a convention.

The concrete failure that permits: **the digest test fails on the merge commit, not on
either branch.** Two branches that touch different files under `app/` can each record a
correct digest, each be green, merge with no textual conflict, and produce a red `master`
that nobody ran. That is not hypothetical. It is the state this repo was in on the day #49
was filed, and it is why a merge order had to be worked out by hand in a scratchpad clone.

The same shape covers everything else the suite asserts and nobody remembers: that
`app/api.js` is the only file under `app/` that calls the back end, that the domain layer
imports with Flask absent, that `node` is present, that the icons regenerate byte for byte.
Every one is a test, and every one runs only if someone runs it.

## The decisions, and why

### Two runners, `ubuntu-latest` and `windows-latest`, both green before merge

Rejected: one Linux runner. Rejected: one Windows runner.

Linux is the platform this code has never once executed on. Every commit in this repo's
history was run on Windows, by a person or by the `Stop` hook in `.claude/settings.json`.
A Linux leg is therefore the single highest-information thing this task can buy, and it is
also the cheap one.

Windows is the platform every cross-platform accommodation in this repo is *about*:

* `shell_digest()` in `tests/test_web_shell.py` normalises `\r\n` to `\n` for text entries
  precisely so that a checkout under `core.autocrlf=true` and one under `false` compute the
  same digest. That claim cannot be proven by one checkout. It needs two, with different
  bytes on disk, agreeing on one number.
* `tests/test_shell_behaviour.py::node()` resolves the interpreter with `shutil.which` and
  passes the resolved path as `argv[0]`, with a comment saying this is so the subprocess
  does not depend on Windows resolving `node` through `PATHEXT`.
* `.gitattributes` pins `*.sh` to LF because CRLF breaks a shebang.
* `CLAUDE.md` records a Windows-specific access-denied spawn failure for `uv run pytest`.

Drop the Windows leg and every one of those goes back to being enforced by one developer's
machine, which is the exact arrangement this issue exists to end. Drop the Linux leg and the
digest's cross-platform claim, and the whole of Linux, stay untested.

The cost is bounded and known: the suite is 2061 tests with no `time.sleep`, no socket bind,
no thread and no network. `tests/test_dev_server.py` says in its own docstring that nothing
in it binds a socket or opens a port. The two legs run in parallel, so the wall clock is the
slower leg, not the sum.

`fail-fast: false`, because the interesting failures here are platform-specific by
construction and cancelling the other leg would hide exactly the comparison the pair exists
to make.

### `uv sync --locked`, not `uv sync` and not `uv sync --frozen`

`--frozen` installs the lockfile without checking it still agrees with `pyproject.toml`, so
a dependency added to `pyproject.toml` and never locked would install nothing and CI would
go green over a dependency that does not exist. `--locked` fails when the two disagree,
which is precisely the rule `CLAUDE.md` states in prose: dependencies are declared, then
installed, never resolved ad hoc. Plain `uv sync` would re-resolve and silently rewrite
`uv.lock` on the runner, which is the failure this task is supposed to make impossible.

The test command that follows is the literal `uv run python -m pytest`. `uv run` performs
its own implicit sync, but after a successful `uv sync --locked` there is nothing left for
it to do, so the environment `pytest` runs in is the locked one.

### `uv run python -m pytest`, on both legs, character for character

The constraint is not negotiable and it is not only about the Windows spawn error. `CLAUDE.md`,
`README.md` and `.claude/rules/testing.md` all name this exact spelling as the way this suite
is run. CI exists to say that the documented command is green, not that some other spelling
is. Using `uv run pytest` on the Linux leg because it happens to work there would mean CI and
every human ran different commands, which is a second convention to remember.

Whether the access-denied error is Windows-specific: it is documented as a property of the
developer's machine, and the plausible cause is the console-script shim `uv` spawns being
locked or blocked. This task does not attempt to reproduce it, diagnose it or work around it,
and CI must not branch on it.

### Python pinned to 3.12, the declared floor

`pyproject.toml` says `requires-python = ">=3.12"` and there is no `.python-version` file.
CI pins 3.12 through the `UV_PYTHON` environment variable at job level, so both legs run the
floor the project claims to support. A floor that nothing ever runs is not a floor. Pinning
in the workflow rather than adding `.python-version` keeps this task from changing what any
developer's `uv` does locally.

If the pin makes the suite red because the code needs something newer than 3.12, that is a
finding about `requires-python`, not a reason to raise the pin. See "If a leg is red for a
reason that predates this task".

### `node` 20, installed explicitly, never inherited from the runner image

`tests/test_shell_behaviour.py::test_node_is_installed_and_recent_enough` asserts major
version 20 or later and fails, loudly and without skipping, when `node` is missing. CI
installs node deliberately and pins the major to `20`, the floor the test asserts and the
floor `CLAUDE.md` names. Relying on whatever the runner image happens to preinstall would be
the same unpinned convention in a new place, and it would drift the day GitHub bumps an image.

No `.node-version` file, no `package.json`, no `node_modules`. Task 9b ruled those out and
this task does not reopen it. The version lives in the workflow because the workflow is the
only thing that reads it.

### No caching

The dependency set is Flask, pytest and their transitive wheels. Restoring a cache costs
about as much as fetching them. What a cache adds is a failure mode: a restored environment
built by a different interpreter or from a different lock is exactly the "CI ran something a
developer did not" defect this whole task is built to prevent, and it presents as a confusing
test failure rather than as a cache problem. The value of this CI is that it can be believed,
not that it is fast.

If a leg ever exceeds ten minutes, caching keyed on the runner OS, the pinned Python version
and the hash of `uv.lock` is the first thing to add, as its own task. Criterion 27 records
the durations so that decision has data behind it.

### Fork pull requests

The trigger is `pull_request`, never `pull_request_target`. `pull_request_target` runs the
base repository's workflow with the base repository's token against a fork's code, which is a
known privilege-escalation shape and buys nothing here.

The workflow reads no secret and writes nothing, so a fork PR run has everything it needs
with the read-only token a fork gets. Workflow-level `permissions: contents: read` states
that rather than inheriting whatever the repository default is.

GitHub's default is to require a maintainer to approve the first workflow run from a new
contributor. Nothing about that needs changing. A PR whose check has not started because
approval is pending is blocked from merging, which is the correct outcome, not a defect.

### Branch protection is behavioural, and admins are not included

The rule on `master` requires both check contexts and requires branches to be up to date
before merging. The second setting is the one that closes the issue's central hole: without
it, a green check computed against an older `master` stays green after another branch lands,
and the stale result is accepted at merge time.

"Include administrators" is left **off**, deliberately. The sole admin must keep a way to
unbreak `master` when CI itself is broken, for instance during a GitHub Actions incident or
after a bad workflow edit. This is a reversible choice, recorded here so nobody has to guess
whether it was an oversight.

## Goal

Every push to `master` and every pull request runs `uv sync --locked` and then the exact
command `uv run python -m pytest` on both `ubuntu-latest` and `windows-latest`, with `node`
20 and Python 3.12 pinned; `master` refuses a merge whose checks have not passed and whose
branch is not up to date with the base. The digest defect that fails only on the merge
commit is caught by the machine, on the merge commit, before anybody merges it.

## Acceptance criteria

Each is a yes or no a QA agent can reach by reading a file, reading a workflow run log, or
performing a named sequence against the repository. `REPO` is the worktree root. Criteria
28 to 33 are the ones that establish CI fails when the suite fails; criterion 30 is the one
that reproduces the issue's own scenario.

### The workflow file

1. `.github/workflows/tests.yml` exists on branch `task-49`, and it is the only file added
   anywhere under `.github/`.
2. Its `on:` block has a `push` trigger restricted by branch filter to the repository's
   default branch and nothing else, and a `pull_request` trigger with no branch filter. QA
   reads the repository's actual default branch name from GitHub rather than assuming, and
   confirms the push filter names that exact branch. It is expected to be `master`.
   A `workflow_dispatch` trigger is permitted and nothing else is.
3. The workflow declares `permissions:` at workflow level, granting `contents: read` and
   nothing else.
4. The string `pull_request_target` does not appear anywhere in the file.
5. No `run:` block interpolates any `${{ github.event.* }}`, `${{ github.head_ref }}` or
   `${{ github.actor }}` expression. The only expressions permitted inside a `run:` block
   are `matrix.*` and `runner.*`. This is script injection, and a workflow that runs on
   fork PRs is where it lands.
6. Every `uses:` names a 40 character commit SHA, with the human readable version in a
   trailing comment on the same line. No `@v4`, no `@main`, no floating tag anywhere.
7. There is exactly one job. Its id is `test`. Its `name:` is set explicitly to
   `test (${{ matrix.os }})`, so the two check contexts are `test (ubuntu-latest)` and
   `test (windows-latest)` and stay those names even if a matrix key is added later. A
   context that silently renames is a required check that never reports, and a required
   check that never reports blocks every pull request forever.
8. The job sets `timeout-minutes` to 20 or less.
9. The strategy sets `fail-fast: false` and a matrix that produces exactly two legs,
   `ubuntu-latest` and `windows-latest`. `runs-on` is `${{ matrix.os }}`.
10. The job sets `UV_PYTHON` to `"3.12"` at job level, and no step selects a different
    interpreter.
11. The install step's command is exactly `uv sync --locked`. The strings `uv sync --frozen`
    and a bare `uv sync` do not appear.
12. The test step's command is exactly `uv run python -m pytest`. That string appears exactly
    once in the file. The string `uv run pytest` appears nowhere in the file.
13. The test step is the last step in the job. No step in the job sets `continue-on-error`,
    and no step carries an `if:` that could let the job succeed while the test step failed
    or was skipped.
14. No `run:` command contains `|| true`, `; exit 0`, `-ErrorAction SilentlyContinue`, or any
    other construct that discards an exit status.
15. Every `run:` step contains exactly one command. This is not style. GitHub's default shell
    on `windows-latest` is `pwsh`, which propagates only the last command's exit code from a
    multi-line block, so a failing first line in a two-line step is swallowed.
16. No `shell:` key appears anywhere in the file. Each leg uses its runner's default, `bash`
    on Linux and `pwsh` on Windows, so the Windows leg exercises the shell the developer
    actually uses and a PowerShell quoting problem in a documented command is visible.
17. `node` is installed by an explicit setup step pinning the major version to `20`. The
    workflow does not rely on a preinstalled `node`.
18. The file contains no `actions/cache` step, no `enable-cache` input and no `cache:` input.
    Nothing under `.venv/` or `~/.cache/uv` is saved or restored.
19. `actions/checkout` is used at its default `fetch-depth`. No test in this repo reads git
    history, which task 46 decided deliberately, so a shallow checkout is correct and a full
    fetch would only be slower.
20. A step before checkout sets `core.autocrlf` explicitly and differently per leg: `true` on
    the Windows leg, `false` on the Linux leg. The value is stated by the workflow rather than
    inherited from a runner image default that can change without notice.
21. A step after checkout runs `git ls-files --eol app/` so the working tree's actual line
    endings are readable in the log.

### What the run log shows

22. On the Linux leg, the `git ls-files --eol app/` output shows `w/lf` for `app/app.js`. On
    the Windows leg it shows `w/crlf`. QA quotes both lines in the QA note. **This is the
    criterion that makes the cross-platform claim real rather than asserted.** If the Windows
    leg shows `w/lf`, the CRLF path is not being exercised, criterion 20 has not achieved its
    purpose, and the implementer fixes it before this task is called done.
23. Both legs are green, and both report `2061 passed`, with `0 failed`, `0 errors`,
    `0 skipped` and `0 xfailed` in the pytest summary line. The two counts are identical to
    each other. If they differ, a test is platform-dependent, and that is a finding to record
    and report, not to paper over.
24. The pytest header on both legs names Python `3.12.x`. QA quotes the two header lines.
25. The node version used on each leg is readable in the log, from the setup step's own
    output or from an explicit step, and is `v20.x` on both.
26. The `uv` version used is readable in the log on both legs and is the same exact version on
    both, not `latest` resolved twice.
27. QA records the wall-clock duration of each leg. This is data for the caching decision, not
    a pass or fail; a leg over ten minutes is recorded as a finding for a follow-up task.

### CI actually fails when the suite fails

Each of these creates a scratch branch off `task-49`, proves a red result, and deletes the
branch. None of them lands on `master`.

28. **A broken shell digest turns the checks red.** On a scratch branch, append one blank line
    to the end of `app/app.js`, commit, push and open a pull request. Both legs go red. The
    failure named in each log is
    `tests/test_web_shell.py::test_the_recorded_digest_matches_the_files_it_covers`. QA quotes
    the summary line from each leg. This is the mechanism from task 46 being enforced by a
    machine for the first time.
29. **A lockfile that does not match `pyproject.toml` fails before pytest runs.** On a scratch
    branch, change the Flask version constraint in `pyproject.toml` without running `uv lock`,
    commit and push. The `uv sync --locked` step fails, the test step never runs, and the
    error names the lockfile as out of date. QA quotes it. This is the proof that
    criterion 11 was implemented as `--locked` and not as a plain `uv sync` that would have
    quietly re-resolved.
30. **The merge commit failure the issue was filed about is caught.** Two branches off the
    same base, each individually green, whose merge is red:
    a. Branch X edits `app/app.js` (one added comment line is enough) **and** updates
       `SHELL_DIGEST` in `app/sw.js` to the value the suite computes for that edit. Its PR is
       green on both legs.
    b. Branch Y edits `app/styles.css` (one added comment line) **and** updates `SHELL_DIGEST`
       to the value the suite computes for *that* edit. Opened against the same base, its PR
       is green on both legs.
    c. Merge X.
    d. Y's checks are re-required because the branch is now out of date. Once re-run against
       the new base, Y's PR goes red on both legs on
       `test_the_recorded_digest_matches_the_files_it_covers`, because the digest over both
       edits together matches neither recorded value.
    e. Y cannot be merged. QA quotes the failure and the blocked merge state.
    f. Both branches are deleted and X's merge is reverted, so `master` ends where it started.
    QA records, in one sentence, that before this task both branch tips were green and step
    (d) would have produced a red `master` that nobody ran.
31. **The green case is genuinely green.** This task's own pull request, which adds only
    `.github/workflows/tests.yml`, this file and the documentation sentence from criterion 38,
    is green on both legs. A workflow added in a pull request from a branch in this repository
    runs on that pull request, so no separate proof run is needed.
32. **The check runs against the merge, not the branch tip.** In the run triggered by a
    `pull_request` event, the log shows `actions/checkout` resolving a merge commit, and its
    parents are the pull request head and the base tip. QA quotes the SHA and the parents.
    This is the property criterion 30 depends on, stated separately so it is verified rather
    than assumed.
33. No criterion above is satisfied by a run that was skipped, cancelled or neutral. A check
    that did not run is not a check that passed.

### Branch protection

34. A protection rule or ruleset on the default branch requires both contexts,
    `test (ubuntu-latest)` and `test (windows-latest)`, spelled exactly as criterion 7 fixes
    them. Classic branch protection and a repository ruleset are both acceptable; the settings
    below are what matter, not which mechanism produced them.
35. "Require branches to be up to date before merging" is enabled. Verified behaviourally:
    step 30(d) shows the pull request demanding an update before its merge button is available.
36. "Include administrators" / "Do not allow bypassing the above settings" is **off**, and the
    task file records that as deliberate with the reason from the decisions section above.
37. Verified behaviourally, not by reading settings: the red pull request from criterion 28
    shows its merge button disabled and names the failing required check. QA quotes the
    sentence GitHub shows.
38. Verified behaviourally: a direct `git push` of a commit to the default branch is rejected,
    and QA records the exact message. This is an expected consequence of requiring status
    checks and it changes how a human works, so it is written down rather than discovered.

### The documents

39. `CLAUDE.md` gains one short paragraph, and `README.md`'s `## Test` section gains one
    sentence, saying that `.github/workflows/tests.yml` runs `uv sync --locked` and
    `uv run python -m pytest` on Linux and on Windows for every push to the default branch and
    every pull request, that both must be green before a merge, and that a pull request whose
    base has moved must be brought up to date and re-run.
40. Neither addition contains the phrase `no build step`.
    `tests/test_web_shell.py::test_the_no_build_step_claim_carries_its_caveat_where_it_is_made`
    asserts that phrase appears in **exactly one** paragraph in each file, so a second
    paragraph containing it turns that test red.
41. All seven existing document tests pass unedited:
    `test_claude_md_names_the_real_run_command`,
    `test_claude_md_no_longer_says_the_front_end_is_missing`,
    `test_claude_md_says_where_the_shell_and_the_scripts_live`,
    `test_the_readme_documents_how_to_run_the_app`,
    `test_the_no_build_step_claim_carries_its_caveat_where_it_is_made`,
    `test_one_document_says_how_to_clear_a_stuck_service_worker`,
    `test_no_document_claims_the_shell_shows_real_data`.

### Nothing else moved

42. `pyproject.toml` and `uv.lock` are byte identical to the base commit. No dependency is
    added, in any group.
43. Nothing under `src/`, `app/`, `scripts/` or `tests/` is added, edited, renamed or deleted.
    `git diff --stat` against the base shows exactly `.github/workflows/tests.yml`,
    `plans/tasks/49-continuous-integration.md`, `CLAUDE.md` and `README.md`.
44. No test is added, edited, renamed, deleted, loosened, skipped or marked xfail.
    `.claude/rules/testing.md` forbids the last two and this task has no excuse to want them.
45. `uv run python -m pytest` on the developer's machine reports the same `2061 passed`,
    `0 skipped`, `0 xfailed` as before this task.

## If a leg is red for a reason that predates this task

Two failures are foreseeable, and neither is a licence to weaken anything.

**`test_icons_are_reproducible_from_the_generator`, with the message "pixels match but the
encoded bytes differ".** That test regenerates each PNG and compares bytes. PNG bytes come
out of `zlib`, and different zlib builds compress identically shaped input to different
bytes. A Linux leg is the first thing that could ever have exposed it. It is a real
cross-platform defect in a byte-equality assertion, it belongs to whoever owns that test, and
it is not fixed here.

**The Windows leg failing under CRLF on something other than the digest.** If the developer's
local git has `core.autocrlf` set to `false` or `input`, no checkout anywhere has ever had
CRLF on disk, and criterion 20 is the first one that does. Anything it turns up is a genuine
finding about this repo, exactly as issue #49 predicts.

In either case the implementer must **not**: edit the failing test, add a skip or an xfail,
set `continue-on-error`, relax `core.autocrlf`, or delete the leg. What they do instead:

1. Record the failure verbatim in this file under a `## Findings` heading, with the leg, the
   test id and the full message.
2. File it as its own GitHub issue, naming the test and quoting the message.
3. Leave the leg in the workflow, visibly failing, with a comment in the workflow naming the
   issue and saying that this leg is not yet a required check.
4. Require, in criterion 34, only the legs that are green. Record which ones, and why the
   other is missing.
5. Report back. The leg becomes a required check the day the follow-up issue closes.

A permanently red leg becomes wallpaper, so this is a days-long state, not a design. If both
legs are green, none of this applies and criterion 34 requires both.

## If the push or the settings change is refused

This is expected often enough to be written down. A workflow file needs the `workflow` scope
on a classic PAT, or `Workflows: write` on a fine-grained one. Branch protection needs
repository admin. This project has already met a token that lacked admin rights.

**If `git push` is refused** with `refusing to allow a Personal Access Token to create or
update workflow ... without 'workflow' scope`, or anything like it:

* Do not rename the file. Do not move it out of `.github/workflows/`. Do not commit it with a
  `.txt` suffix "for now". Do not replace it with a git hook, a `CODEOWNERS` file, a script in
  `scripts/`, or a paragraph in the README, and do not mark any criterion met on that basis.
* Leave the commit on the local branch. It is correct; only the push was refused.
* Record the error verbatim in this file under `## Blocked`, with the date and the command.
* Report back naming the missing scope, and the two ways to get past it: a token carrying
  `workflow` scope, or the repository owner adding the file through the GitHub web UI, which
  uses their session and needs no token scope at all. Hand over the file content so it can be
  pasted.

**If setting branch protection is refused** with a 403, `Resource not accessible by personal
access token`, or `Must have admin rights to Repository`:

* Mark criteria 34 to 38 **blocked**, which is neither passed nor failed. Say so plainly.
* Record the exact command and the exact error.
* Write down the settings to be applied, precisely enough that an admin can do it in a minute:
  the branch name, the two context strings from criterion 7, "require branches to be up to
  date before merging" on, required approvals 0, include administrators off.
* Everything from criteria 1 to 33 still stands on its own. A workflow that runs and reports
  is most of the value; the rule that refuses a merge is the rest, and it can be added later
  by someone with the rights.

**If GitHub Actions is disabled on the repository, or third-party actions are not permitted**,
say which, and report back. If only the third-party restriction applies, the documented
fallback is to install `uv` from Astral's standalone installer pinned to the same exact
version, one command per leg, and to record in the QA note that this path was taken and why.

## Out of scope

* **Anything beyond running the existing suite.** No linting, no formatter check, no type
  checker, no coverage gate, no coverage report, no release automation, no publishing, no
  container build, no deployment.
* **A Python version matrix or a node version matrix.** One pinned version of each. The OS
  matrix is the only matrix, and it exists because the line-ending claim needs two checkouts.
* **macOS.** No claim in this repo is about macOS, nobody develops on it, and it is the most
  expensive runner.
* **Caching.** Decided against above. Adding it later is a separate task with criterion 27's
  durations as its evidence.
* **Any change to `pyproject.toml` or `uv.lock`**, including adding a `dev` group tool that
  "CI would find useful".
* **Adding `.python-version`, `.node-version`, `package.json` or `node_modules`.**
* **Adding or changing `.gitattributes`.** Task 46 rejected a repo-wide `text=auto` because it
  would rewrite the working tree of anyone with CRLF checked out, and criterion 22 needs the
  CRLF working tree to exist, not to be normalised away.
* **Fixing anything CI turns up.** Findings are recorded and filed. This task adds the machine
  that looks; it does not fix what the machine sees.
* **Changing the `Stop` and `PostToolUse` hooks in `.claude/settings.json`.** They stay. CI is
  the backstop for what the hooks cannot see, which is the merge commit, not a replacement for
  them.
* **A status badge in `README.md`.** It is a picture of a fact, not the fact.
* **Requiring approvals, requiring conversation resolution, requiring signed commits, or any
  other protection setting** beyond the two in criterion 34 and 35.
* **Auto-merge, merge queues, or Dependabot.**
* **Reporting the suite as annotations, artifacts, JUnit XML or a summary table.** The log is
  the report.

## Constraints

* **Files added or edited: exactly four.** `.github/workflows/tests.yml`,
  `plans/tasks/49-continuous-integration.md` (this file, if it needs correcting), `CLAUDE.md`
  and `README.md`. Nothing else, anywhere.
* **No new dependency of any kind**, in `pyproject.toml`, in a workflow-installed tool, or as
  an npm package. This adds configuration, not packages.
* **The test command is the literal string `uv run python -m pytest`**, on both legs, unchanged
  and unwrapped.
* **The install command is the literal string `uv sync --locked`**, on both legs.
* **One command per `run:` step**, for the PowerShell reason in criterion 15.
* **Nothing under `tests/`, `src/`, `app/` or `scripts/` is touched.** If making CI green
  requires touching one of them, stop and report; that is a finding, and it is the finding this
  task exists to produce.
* **The workflow is not made to pass.** If it is red, the repository is red, and that is the
  answer the task was commissioned to get.
* Run the suite locally with `uv run python -m pytest` before pushing. Plain `uv run pytest`
  fails on this machine with an access-denied spawn error.
* A `concurrency:` block is permitted and optional. If present it must not cancel in-progress
  runs on the default branch, because those are the runs that say whether `master` is red.

## Size

One YAML file of roughly forty lines, one paragraph in `CLAUDE.md`, one sentence in
`README.md`, and this file. No Python, no JavaScript, no shell script, no test.

Most of the effort is not writing the file. It is the six proof sequences in criteria 28 to
33 and 35 to 38, which are performed against the real repository and quoted in the QA note.
If those are skipped, this task has produced a workflow that is believed to work, which is
the same category of thing as a convention.
