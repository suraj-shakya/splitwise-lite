# Task 46: the shell precache digest

**Depends on:** 8 (complete, on `master`), 9b (complete, on `master`), 32 (complete, on
`master`)
**Consumed by:** every later task that edits a file under `app/`

Closes GitHub issue #46. `plans/backlog.md` has no entry for this and this task does not
add one; the issue is the backlog entry and this file is the implementable version.

## Why this task exists

`app/sw.js` precaches nine files under a cache named `'splitwise-lite-shell-' + VERSION`.
The worker answers those nine from Cache Storage and never revalidates them. So a change to
any precached file is invisible to every already-installed client until the cache **name**
changes, and the only thing that changes the name today is a human remembering to edit
`var VERSION`.

Nothing enforces that. It is a convention doing a mechanism's job, and it has failed twice:

* Tasks 11 and 12 shipped the feed and the balances screens while `VERSION` was still
  `v2`. Nobody who had already opened the app ever saw either screen.
* Task 32 (PR #41) rewrote `api.js`, `app.js` and `index.html`, all three precached, and
  left `VERSION` at `v3`. It was caught by a reviewer reading the diff by eye, and fixed by
  a one-line follow-up (PR #45, now `v4`).

Both failures looked exactly like success. The app loads, behaves as it did before, and
reports no error anywhere. There is no symptom to notice and no log line to read. That is
what makes it worth a mechanism rather than a louder comment.

`tests/test_add_screen.py::test_the_worker_version_has_been_bumped_past_the_two_screens_it_missed`
is the scar tissue from the first failure: it pins `VERSION` at 3 or more. It pins a floor,
not a relationship, so it went green the moment somebody typed `v3` and it could not have
caught the second failure.

## The decision, and why

**The cache name gains a second component, recorded in `app/sw.js` and derived from the
content of the precached files. A pytest test recomputes it and fails when it is stale.**

```js
var VERSION = 'v4';
var SHELL_DIGEST = '0123456789ab';
var CACHE = 'splitwise-lite-shell-' + VERSION + '-' + SHELL_DIGEST;
```

The issue offers two shapes. This is the first one, a recorded digest with a test, with the
one change that makes it actually bite. Both alternatives were considered and rejected, and
the reasoning is written down here so nobody re-opens it in review.

### Why not derive `VERSION` in the worker at run time

Rejected outright. To compute its own cache name the worker would have to fetch and hash all
nine shell files before it could open the cache, on every worker start, not just on install,
because `CACHE` is read by the `fetch` handler too. Offline, those fetches fail, the worker
cannot name its own cache, and the shell stops opening offline. That is the one thing the
worker exists for. A worker that must reach the network to serve its cache is not a cache.

### Why not derive `VERSION` in a build step

There is no build step and there is not going to be one. `CLAUDE.md` says the files in
`app/` are what the browser runs, and task 9b already ruled out npm, `package.json` and
`node_modules`. A code generator that rewrites `sw.js` is a build step by another name, and
it moves the "remember to run it" problem rather than removing it, unless a test enforces
that it was run, which is this task with extra machinery in front of it.

### Why the digest must live in the cache name, not only in the test

This is the load-bearing part. A test that records the expected digest in
`tests/test_web_shell.py` and asserts it matches the files can be satisfied **without
fixing the bug**: the engineer changes `app.js`, the test goes red, they paste the new
digest into the test file, and the suite goes green with `VERSION` still at `v4` and the
cache name unchanged. The mechanism would then certify exactly the failure it was built to
catch.

Putting the digest inside the cache name closes that. The only edit that turns the test
green is an edit to `app/sw.js`, and that edit necessarily changes the cache name, which
necessarily retires the old cache at `activate`. It also changes the bytes of `sw.js`
itself, which is what makes the browser notice there is a new worker at all. There is no
green-but-broken state left.

The alternative of asserting "`VERSION` differs from the value on `master`" needs git
history inside a unit test, which is fragile in a worktree and in a shallow CI clone.
Rejected.

### Why `VERSION` survives

`VERSION` is not made redundant, and removing it would cost more than it saves:

* **`sw.js` is not itself precached**, and cannot be: the browser fetches and byte-compares
  the worker script, and a worker serving its own stale self from Cache Storage is a trap.
  So a change to the worker's *logic* moves no digest at all. `VERSION` is the knob for
  "the shell files are the same but the worker treats them differently", and there is
  nothing else that could be.
* Cache Storage in DevTools reads `splitwise-lite-shell-v4-9c1f3a7b2e04`. The generation is
  legible at a glance and the digest is the detail. A bare hash tells a person nothing.
* `CLAUDE.md`, `README.md` and
  `tests/test_web_shell.py::test_the_no_build_step_claim_carries_its_caveat_where_it_is_made`
  all name `VERSION` as the local-iteration knob, and it still is one: bumping it still
  changes the cache name and still picks up an edit on reload.

The test never asks anyone to bump `VERSION`. It asks for one line, and tells them exactly
what to type on it.

### Churn, and why it is the right trade

Any byte change to a precached file changes the digest, including a whitespace-only edit or
a comment. Every installed client then redownloads the nine-file shell once. That is the
correct trade: over-invalidating costs one shell download and is self-correcting, while
under-invalidating is invisible, permanent, and has already happened twice here. A rule with
no judgement in it is also a rule nobody argues about in review.

Normalising further, so that a reformat does not churn, would need a JavaScript, CSS, HTML
and PNG aware normaliser. That is a parser, which is a dependency. Out of the question.

The one normalisation that is done is line endings, and it is not about churn. This repo has
no `.gitattributes` rule for `.js`, `.html`, `.css` or `.json`, so a checkout with
`core.autocrlf=true` has different bytes on disk from one without. A raw-byte digest would
therefore be machine-dependent and could never be green on Windows and Linux at once.
Normalising `\r\n` to `\n` for text entries makes the digest a property of the committed
content instead of the checkout. Binary entries (the four PNGs) are hashed raw.

### The same bug, one level out

A file added to `app/` and not to `SHELL` is not precached, does not work offline, and is
not covered by the digest either. Today `test_app_holds_exactly_the_promised_files` forces
the new file into the `APP_FILES` literal and `test_the_worker_precaches_exactly_the_shell`
compares `SHELL` against the `SHELL_PRECACHE` literal, but **nothing relates the two**. Both
literals can be edited consistently while `SHELL` is left short, and the suite stays green.
So this task also derives the precache list from the directory and requires any deliberate
omission to be named with its reason. `sw.js` is the only current omission.

## Goal

The cache name in `app/sw.js` is derived from the content of the files it precaches, so a
change to a precached file that ships without retiring the old cache is a red test rather
than a silent regression; and the precache list is checked against `app/` itself, so a file
added to the shell and left out of `SHELL` is a red test too. The failure message tells a
person who has never heard of a precache manifest what went wrong, why it matters, and the
one line to change.

## Acceptance criteria

Each is a yes or no a QA agent can reach by reading a file or running a command. `REPO` is
the worktree root.

### The worker

1. `app/sw.js` declares `var SHELL_DIGEST = '<twelve lowercase hex characters>';` on its own
   line, and the regex `var SHELL_DIGEST = '([0-9a-f]{12})';` matches it exactly once in the
   file.
2. `app/sw.js` builds the cache name from both parts. The literal
   `var CACHE = 'splitwise-lite-shell-' + VERSION + '-' + SHELL_DIGEST;` appears in the
   file, and no other assignment to `CACHE` does. **A test asserts this**, because a
   `SHELL_DIGEST` that the cache name does not use is an inert constant and the whole
   mechanism would be decorative.
3. `var VERSION = 'v4';` is unchanged. This task does not bump it: adding `SHELL_DIGEST` to
   the cache name already changes the name, and `activate` already deletes every cache whose
   name is not the current one.
4. `SHELL` is unchanged: the same nine entries, in the same order, in the same style of
   quotes. `tests/test_web_shell.py::precache_entries` still parses exactly those nine, and
   `test_the_worker_precaches_exactly_the_shell` passes unedited.
5. `SHELL_DIGEST` is not a member of `SHELL` and `sw.js` is not hashed into the digest. The
   digest covers the nine precached files and nothing else.
6. The header comment of `app/sw.js` still contains the words `SHELL` and `revalidate`, so
   `tests/test_add_screen.py::test_the_worker_says_when_to_bump_it` passes unedited, and it
   now also states, in prose, that `SHELL_DIGEST` is recorded rather than computed, that a
   test enforces it, and that `sw.js` is deliberately not in `SHELL`.
7. Nothing else in `app/` is edited. `git diff --stat` over `app/` shows `sw.js` and no other
   path.

### The digest rule

8. The digest is defined once, in `tests/test_web_shell.py`, as a function of the entry list
   and the file bytes, with no other input. Reading it shows this exact rule:
   * entries are the strings `precache_entries()` returns, sorted with Python's default
     string ordering;
   * for each entry in that order, one `hashlib.sha256` is fed
     `entry.encode("utf-8")`, then `b"\0"`, then the decimal length of the content bytes as
     ASCII, then `b"\0"`, then the content bytes;
   * content bytes are the file's bytes with `b"\r\n"` replaced by `b"\n"` for entries
     ending `.html`, `.css`, `.js` or `.json`, and the raw bytes for entries ending `.png`;
   * the result is `hexdigest()[:12]`.
9. An entry whose extension is in neither the text nor the binary list fails with a message
   naming the entry and saying that somebody has to decide whether it is text or binary. It
   does not silently default to either.
10. The docstring or comment on that function says why twelve characters is enough: this
    detects change, it does not resist tampering, and anyone who can edit `app/` can edit
    `sw.js` too.
11. The function accepts an override of the entry list and an override of individual entries'
    bytes, so the tests below can hash a hypothetical `app/` without writing anything to
    disk. Nothing under `app/` is written, copied or renamed by any test in this task.

### The enforcing test

12. `tests/test_web_shell.py` gains a test that computes the digest over the shipped files
    and asserts it equals the `SHELL_DIGEST` recorded in `app/sw.js`. It is green on the
    branch as delivered.
13. When it fails, its message contains, in this order and as readable prose rather than a
    repr dump: the recorded value; the computed value; a sentence saying that installed
    browsers keep their own copy of the shell keyed by the cache name and will keep serving
    the old files until that name changes; the literal line
    `var SHELL_DIGEST = '<computed>';` to paste into `app/sw.js`; and a sentence saying that
    `VERSION` needs bumping only if the worker's own behaviour changed. QA reads the message
    while performing criterion 20.
14. The message names `app/sw.js` by path and does not use the words "manifest", "hash",
    "digest mismatch" or "invalidate" as the only explanation of what to do. A person who
    has just changed `app/app.js` and has never read `sw.js` can act on it without opening
    anything else.
15. The message does not claim to name which files changed. It may point at
    `git status app/`. The digest is a single aggregate and recording per-file hashes is out
    of scope.

### The self-tests, which prove the digest actually moves

16. A test asserts that appending a single `b"\n"` to `app/app.js`'s content changes the
    digest, using the byte override from criterion 11 and touching no file. Its comment says
    that a whitespace-only edit churning the cache is the accepted trade, not an oversight.
17. A test asserts that changing one byte of `app/icons/icon-192.png` changes the digest, so
    the icons are demonstrably covered and not just listed.
18. A test asserts that hashing a text entry with `\r\n` line endings gives the same digest
    as hashing it with `\n`, so a checkout under `core.autocrlf=true` and one under
    `core.autocrlf=false` agree.
19. A test asserts that reversing the entry list leaves the digest unchanged, pinning the
    sorted rule, so reordering `SHELL` never demands a needless cache retirement.

### The demonstration, run by hand

20. **The mechanism catches the failure it exists for.** From a clean tree:
    a. `uv run python -m pytest` reports 0 failed, 0 skipped, 0 xfailed.
    b. Append one blank line to the end of `app/app.js`.
    c. `uv run python -m pytest` now reports exactly one failure, and it is the test from
       criterion 12. Its message satisfies criteria 13 and 14, verbatim.
    d. `git checkout -- app/app.js`.
    e. `uv run python -m pytest` reports 0 failed, 0 skipped, 0 xfailed again, with the same
       passed count as (a).
    QA records the failure message from (c) in full in the QA note.
21. The same sequence run against the tip of `master` (before this task) produces a green
    suite at step (c). The QA note says so. That is the before-and-after that shows the task
    changed something.

### The precache list against the directory

22. `tests/test_web_shell.py` gains a mapping of files under `app/` that are deliberately not
    precached, keyed by path, valued with the reason in prose. It contains exactly one entry
    today, `sw.js`, whose reason says that the browser fetches and byte-compares the worker
    script itself and that a worker served from its own cache could not be replaced.
23. A test asserts `set(precache_entries()) == APP_FILES - set(NOT_PRECACHED)` and that every
    key of that mapping is in `APP_FILES`. A file present in `app/` and absent from both
    `SHELL` and the mapping fails it.
24. That test's failure message names the offending path and says the two ways to fix it: add
    it to `SHELL` in `app/sw.js`, or add it to the mapping with a reason.
25. QA proves criterion 23 bites: create `app/probe.txt`, run the suite, confirm it goes red
    naming `probe.txt`, delete the file, confirm green. (It also trips
    `test_app_holds_exactly_the_promised_files`, which is expected; the new test must be
    among the failures.)

### The documents

26. The `no build step` paragraph in `CLAUDE.md` and the `no build step` paragraph in
    `README.md` each gain a sentence saying that `app/sw.js` also records a digest of the
    precached files, that the cache name is built from `VERSION` and that digest, and that a
    test fails when it is stale and prints the line to paste.
27. Each of those files still contains the phrase `no build step` in **exactly one**
    paragraph, and that paragraph still contains `VERSION` and `app/sw.js`, so
    `test_the_no_build_step_claim_carries_its_caveat_where_it_is_made` passes unedited. A new
    paragraph that repeats the phrase breaks it; the sentence goes inside the existing one.

### The suite

28. `uv run python -m pytest` is green with nothing skipped and nothing xfailed. The passed
    count is `2052` plus the number of tests this task adds, and no test that existed before
    this task has been edited, renamed, deleted, loosened or parameterised differently.
29. No new file is added under `tests/`, `scripts/`, `src/` or `app/`. The whole change is
    `app/sw.js`, `tests/test_web_shell.py`, `CLAUDE.md`, `README.md` and this spec.
30. `pyproject.toml` and `uv.lock` are byte-identical to `master`.

## Out of scope

* **Bumping `VERSION`.** It stays `v4`. Criterion 3.
* **Any change to `app/index.html`, `app/app.js`, `app/api.js`, `app/styles.css` or the
  icons.** Two sibling branches are in flight in those files right now. This task's whole
  value is that it does not need to touch them, and touching them would make the very first
  merge conflict be with the mechanism itself.
* **Automatically writing the digest back into `app/sw.js`.** No fixer, no `--update` flag,
  no `scripts/` entry, no pre-commit hook. The failure message hands over one line and a
  person pastes it. A fixer that runs silently is how a mechanism becomes a convention
  again.
* **Per-file digests, a manifest file, or naming which entries changed.** One aggregate.
* **Hashing `sw.js` itself, or anything outside `SHELL`.**
* **Content normalisation beyond `\r\n` to `\n`.** No minification, no whitespace
  collapsing, no comment stripping, no PNG re-encoding.
* **Changing what the worker caches, when it caches it, its fetch strategy, the `/api`
  bypass, `skipWaiting`, `clients.claim`, or the 503 empty-cache response.**
* **Adding `.gitattributes` rules.** Criterion 18 removes the need without touching git
  configuration, and a repo-wide `text=auto` would rewrite the working tree of anyone with
  CRLF checked out.
* **`tests/shell_harness.mjs` and `tests/test_shell_behaviour.py`.** The harness states in
  its own header that service workers and Cache Storage are browser-only and outside it.
  That is still true. This task is entirely Python-side.
* **Making `test_the_worker_version_has_been_bumped_past_the_two_screens_it_missed` smarter.**
  It stays as it is, a floor of 3, unedited.
* **A cache size budget, a staleness report, or telling a user their shell was updated.**

## Constraints

* **Files edited: exactly five.** `app/sw.js`, `tests/test_web_shell.py`, `CLAUDE.md`,
  `README.md`, and this file if it needs correcting. Nothing else.
* **`app/sw.js` gains one constant and one changed line**, plus the header sentences from
  criterion 6. It does not gain a function, a loop, or anything that runs. `SHELL_DIGEST` is
  a literal string that participates in the cache name; that is shipped behaviour, not a
  test hook, which is what keeps it inside the rule that nothing is added to `app/` merely to
  make it testable.
* **No new dependency, of any kind.** `hashlib` and `re` are standard library and already
  imported or importable in `tests/test_web_shell.py`. No npm, no `package.json`, no
  `node_modules`, per task 9b. `pyproject.toml` is not opened.
* **`tests/test_web_shell.py` keeps its own rule**: standard library only, nothing imports
  `splitwise_lite`, and every path is resolved from `REPO`, never from the working
  directory.
* **No test writes to `app/`.** Every hypothetical shell is built from byte overrides in
  memory, the way `tests/test_shell_behaviour.py` applies its mutants without committing a
  copy. Criterion 11.
* **No test is skipped or marked xfail**, per `.claude/rules/testing.md`.
* Run the suite with `uv run python -m pytest`. Plain `uv run pytest` fails on this machine
  with an access-denied spawn error.
* **Bootstrapping the value:** write `var SHELL_DIGEST = '000000000000';`, run the suite
  once, read the computed value out of the failure message, paste it. If that loop is
  awkward, the message in criterion 13 is not good enough yet, and that is a finding worth
  acting on rather than working around.

## Size

This is small on purpose. One constant and one changed line in `app/sw.js`, roughly eighty
lines in `tests/test_web_shell.py` counting the failure messages and the comments that
explain the trade, one sentence each in two documents. Eight new tests:

1. the cache name is built from `VERSION` and `SHELL_DIGEST` (criterion 2);
2. the recorded digest matches the files on disk (criterion 12);
3. an unknown extension in `SHELL` fails loudly (criterion 9);
4. one appended byte in `app.js` moves the digest (criterion 16);
5. one changed byte in an icon moves the digest (criterion 17);
6. line endings do not move the digest (criterion 18);
7. reordering the entries does not move the digest (criterion 19);
8. `SHELL` covers `app/` minus the named omissions (criterion 23).

If it grows a helper module, a script, a fixture directory or a second file under `app/`,
it has gone wrong.

## Notes for whoever merges the siblings

After this lands, the coordination note in
`plans/tasks/32-client-error-classification.md` ("raise `VERSION` at merge time with
whichever of the concurrent changes lands last") is obsolete. The suite now says it. A merge
that combines two branches touching precached files goes red on the merge commit until the
digest is recomputed, which is exactly when a human should be looking at it. Nobody needs to
remember, and nobody needs to review a diff by eye for it.
