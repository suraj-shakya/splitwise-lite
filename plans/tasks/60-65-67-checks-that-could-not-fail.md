# Task 60/65/67: three checks that could not fail

**Depends on:** nothing unlanded. Issues #60, #65 and #67 are all reports against `master`
as it stands, and the code each one names is already there.
**Runs beside:** the branch for issue #16, which is editing `tests/test_web_api.py` and
`tests/test_web_shell.py`. **This task edits neither of those files**, so the two branches
do not overlap in any file. See "The concurrent #16 branch" below for the one interaction
that is possible.
**Consumed by:** every later task, because two of the three deliverables are mechanisms the
suite runs on every commit.

Closes GitHub issues **#60**, **#65** and **#67**. `plans/backlog.md` has no entry for any
of them and this task does not add one; the issues are the backlog entries and this file is
the implementable version.

## Why these three are one task

Each of the three is a way a check reports success without exercising the thing it names,
and all three land in or beside `.claude/rules/testing.md`.

* **#67, a test that stopped existing.** `tests/test_web_api.py` came to define
  `test_an_amount_that_is_a_json_number_is_refused` twice. Python rebinds a module-level
  name silently, so pytest collected only the second, and four parametrised cases stopped
  running with no error, no warning and a green suite. It has happened twice, both times in
  one day: one instance deleted four cases on a branch, and the other had been live on
  `master` since that morning, shipped by the most heavily verified PR of the day. It was
  found only because a task carried a criterion demanding the pass count reconcile
  arithmetically.
* **#65, a pin that pinned nothing.** `pytest.raises(match=)` is an `re.search`, not a full
  match. `src/splitwise_lite/money.py` prefixes several of its `TypeError`s with the type
  name, so `Money currency must be a Currency, got str: 'AUD'` *contains*
  `currency must be a Currency` from index 6. On PR #62 a test written to prove that
  `split_exact` validates its currency **before** its total stayed green with the guard
  deleted, and the first proposed repair had exactly the same defect: it too ran
  `9 passed` with the guard gone. The suite holds 13 more unanchored pins and, before PR
  #62, held no anchored one.
* **#60, a mutation nobody can re-run.** Mutation testing is the main verification
  discipline in this repo, and nearly every task's evidence that its tests bite is a set of
  mutations run once and then described in a sentence. The #14 engineer had to re-verify
  its own PR's five mutations, and its first reconstruction of "choose the shape from
  something other than ids" was a different mutation with a different result: it killed one
  scenario where QA had recorded two. A description standing in for the thing itself.

The common shape is that in all three the failure is silence. Nothing goes red, nothing
logs, and the only thing that ever objected was one person doing arithmetic. So two of the
three answers here are mechanisms rather than rules, and the rules that remain are written
with the defect that produced them attached, because a rule without its scar is one nobody
believes.

## The decisions, and why

### #67 is a check, not a rule, and it reads every module-level definition

A rule against duplicate names is the one kind of rule nobody can follow, because the whole
difficulty is that neither author can see the other's definition. #67's own "Related"
section says so. So: a few lines of `ast` over every `.py` file under `tests/`, gathering
the names bound by module-level `def`, `async def` and `class` statements, and refusing any
name bound twice in one file.

**Fixtures and helpers are in, not just `test_*`.** A shadowed fixture is the same failure
with a wider blast radius, the same walk already sees it, and restricting to `test_*` is an
extra condition that buys nothing. A shadowed helper is likewise always a bug.

**Cross-module is out.** Two modules may legitimately define the same name; they are
separate namespaces and pytest reports them by path. `tests/` is flat, so two modules cannot
share a basename and cannot collide on import either.

**Module-level assignments are out.** A rebound constant is visible where it is written and
does not silently delete collected cases; a rebound `def` does. Including assignments would
add false positives (a name legitimately reassigned) for a failure of a different kind.

**No exemption mechanism at all.** No allowlist, no marker comment, no per-file skip. A
duplicate module-level definition in a test file is always a bug, and an exemption is how a
check stops being one. This is deliberately different from the pin check below, which does
have a marker, because a deliberate substring pin is a real thing and a deliberate duplicate
definition is not.

### #65 gets an audit, a rule, **and** a check

The audit is the part reading cannot substitute for: for each of the 13 pins, delete the
guard the test exists to pin and confirm the test goes red for the stated reason. PR #62 is
the proof that reading a pin, or reading a fix for one, settles nothing.

The rule is: message pins are anchored by default.

**And the rule is also a check**, which is the question #65 leaves open. The worry is false
positives on deliberate substring pins. That worry is answered by an escape hatch with a
reason attached, which is a shape this repo already uses: `NOT_PRECACHED` in
`tests/test_web_shell.py` lets a file be left out of the precache list only if it carries a
reason, and `test_an_omission_with_no_reason_is_refused` enforces it. Here the same shape is
a `# unanchored: <why>` comment on the `pytest.raises` call. A deliberate substring pin
stays legal and becomes visible; an accidental one goes red. Without the check the rule
lasts exactly as long as the next author who has not read it, which is the failure mode
`plans/tasks/46-shell-precache-digest.md` records for `VERSION`.

The check is written so it can prove it bites, in the shape of
`test_the_narrowed_status_rule_still_bites` in `tests/test_shell_behaviour.py`: it is fed
synthetic sources containing every spelling it must catch and every near miss it must not,
including the real `match = re.match(r"\*\*(.+?)\*\*", bullet)` line that
`tests/test_web_shell.py:1352` contains today.

### #60 gets a format and a home, and no framework

**Which mutations earn a committed mutant.** All three of these have to hold:

1. It is the only evidence that some shipped test bites. If another committed mutant already
   kills that test for the same reason, this one does not get committed.
2. It survives against the code as it was **before** the test it measures existed, so it
   names a defect that could really have shipped rather than one invented to be killed.
3. It leaves a working system with one behaviour broken, and a named control that survives
   it. `UNRELATED` in `tests/test_shell_behaviour.py` is that control today.

Plus a cost cap, because committing all of them would be slow and would ossify: **at most
one committed mutant per defect class per task**, and the PR states the run cost the new
mutant adds. Everything else is recorded, not committed.

**Where the rest live.** A new directory, `plans/mutations/`, one file per task or issue,
holding fenced JSON records. `plans/mutations/README.md` states the format and the recipe.
The record shape is deliberately **the same object the JavaScript harness already accepts in
its `substitutions` list** (`file`, `find`, `replace`), so a JavaScript mutation pastes
straight into a harness config and a Python one is applied by a three-line stdlib recipe.

The alternative considered and rejected was a file next to each task spec inside
`plans/tasks/`. Rejected because `plans/tasks/` has a filename convention that a sibling file
would muddy, and because a mutation record is often about a fix rather than a task.

**The records are not re-verified against live source by the suite.** The suite checks that a
record is machine readable and complete; it does not check that its anchor still matches. Re-
verifying would put every past mutation in the path of every future refactor, which is the
ossification #60 warns against. A committed mutant is re-run; a recorded one is re-runnable.
That is the whole difference between the two, and it is why both exist.

**No Python mutation runner, and no committed Python mutant.** A Python equivalent of the
`MUTANT_*` machinery would have to re-enter pytest from inside pytest, and #60 is explicit
that a mutation-testing framework is out of scope because it would be a dependency. What #60
asks for is that a mutation can be re-run by the next person, and a record plus a recipe is
that.

### The bytecode trap, which is the fourth thing this task writes down

CPython invalidates a cached `.pyc` on `(mtime, size)`. Two mutations of the same size
applied to one file within the same second can therefore run **stale bytecode**, and the run
reports the previous mutation's result. That happened on PR #62 and looked exactly like a
genuine finding. Every Python mutation run in this task and every one recorded in
`plans/mutations/` sets `PYTHONDONTWRITEBYTECODE=1`, or deletes `__pycache__` between runs.

The JavaScript harness is immune, because it substitutes into source text at run time and
caches nothing, which is a further argument for that shape wherever it is available.

### The concurrent #16 branch

All 13 unanchored pins live in `tests/test_split.py` and `tests/test_balances.py`. Neither is
touched by #16, and this task does not open `tests/test_web_api.py` or
`tests/test_web_shell.py` at all, so there is no file-level conflict and no rebase is expected
for the edits themselves.

One interaction is possible and is not a conflict: the new duplicate-definition check runs
over every file under `tests/`, including the two #16 is editing. If it goes red on
`tests/test_web_api.py` after a merge or rebase, **that is the mechanism working**, and #67
says that file is where it happened before. The duplicate is renamed on the branch that
introduced it, reported as a comment on that PR. Under no circumstance is the check narrowed,
given an allowlist, or made to skip a file to get a merge through.

## Goal

Three failures that reported success are each answered by something that runs: a test module
cannot silently lose a test to a duplicate name, an exception-message pin cannot silently
match somebody else's exception, and a mutation claimed in a PR is recorded in a form the
next person can re-run rather than a sentence they have to reconstruct. The four rules learned
today are written down in `.claude/rules/testing.md` with the defect that produced each one,
and the two new checks demonstrably go red on the failures they exist for.

## Acceptance criteria

Each is a yes or no a QA agent can reach by reading a file or running a command. `REPO` is the
worktree root and every path is relative to it. Every path in a message or a test id is
POSIX-form (`tests/test_balances.py`), so the same string reads the same on both platforms.

### The new module

1. `tests/test_suite_integrity.py` exists and is the only test module this task creates. Its
   module docstring says it is the suite's check on itself, names the three issues, and states
   in one sentence each what the two checks refuse and why neither could be a rule.
2. It imports from the standard library and `pytest` only: `ast`, `io`, `json`, `pathlib`,
   `re`, `tokenize` and `pytest` are the permitted names. It imports nothing from
   `splitwise_lite`, so it runs even when the package will not import.
3. `TEST_SOURCES` is derived from the filesystem, not written out: it is
   `sorted(TESTS.rglob("*.py"))` where `TESTS` is `REPO / "tests"`. A test asserts it is
   non-empty, that it contains `tests/test_suite_integrity.py` itself, and that its set of
   POSIX paths equals the set of `*.py` files under `tests/`. A test module added later is
   covered without anybody remembering to add it.

### The duplicate-definition check (#67)

4. `module_definitions(source, where)` returns, for one module's source text, every name bound
   by a **direct child** of the module body that is an `ast.FunctionDef`, `ast.AsyncFunctionDef`
   or `ast.ClassDef`, paired with its line number, in source order. A definition nested inside a
   function, a class body, an `if`, a `try` or a `with` is not a direct child of the module body
   and is not returned.
5. `duplicate_definitions(source, where)` returns one finding per name bound more than once,
   each carrying the name and **every** line number that binds it, sorted by first line number.
   A name bound three times is one finding with three line numbers, not two findings.
6. `duplicate_definition_message(where, name, lines)` builds the failure text and contains, as
   readable prose rather than a repr dump: the POSIX path; the duplicated name; **every** line
   number as a decimal integer; the sentence that Python rebinds a module-level name silently so
   only the last definition is collected and the earlier one is indistinguishable from a test
   that was never written; the sentence that if the earlier one was parametrised its cases are
   gone and nothing anywhere reports an error; that this happened twice in this repo in one day,
   once deleting four parametrised cases on PR #64; and the fix, which is to rename one of them
   to what it actually tests, and never to delete either before checking they are not two
   different tests. A test asserts each of those elements is in the message, feeding it a
   synthetic name and three line numbers.
7. `test_no_test_module_defines_a_name_twice` is parametrised over `TEST_SOURCES`, with the
   POSIX path as the parameter id, so a failure reads
   `test_no_test_module_defines_a_name_twice[tests/test_balances.py]`. It reports **every**
   duplicate in that file in one failure, one block per name, not only the first.
8. The check has no exemption mechanism: `grep -n "allow\|exempt\|skip\|ignore"` over the
   duplicate-check region of `tests/test_suite_integrity.py` finds nothing that lets a file or a
   name out. A comment at the check says why, in one line: a duplicate module-level definition is
   always a bug, and an exemption is how a check stops being one.
9. A comment records that fixtures, helpers and classes are covered as well as `test_*`, and why:
   a shadowed fixture is the same failure with a wider blast radius and the same walk sees it.
10. A comment records that cross-module duplicates are **not** checked, and why: separate
    namespaces, pytest reports by path, and `tests/` is flat so two modules cannot share a
    basename.
11. A comment records that module-level assignments are **not** checked, and why: a rebound
    constant is visible where it is written and deletes no collected case.
12. `test_the_duplicate_check_catches_a_duplicate_test` feeds a synthetic source defining
    `test_x` twice and asserts exactly one finding, naming `test_x` and both line numbers, with
    the line numbers matching where the synthetic source really puts them.
13. `test_the_duplicate_check_catches_a_duplicate_fixture` does the same for two functions named
    `store` each decorated `@pytest.fixture`, proving the check is not restricted to `test_*`.
14. `test_the_duplicate_check_leaves_a_nested_definition_alone` feeds a synthetic source holding:
    two classes that each define a method `helper`; a function containing an inner `def helper`;
    and a `def helper` inside an `if` block that also appears at module level once. It asserts no
    finding. This is the criterion that stops the check flagging ordinary code.
15. `test_the_duplicate_check_looks_at_one_module_at_a_time` feeds two synthetic sources that
    both define `test_x` and asserts neither produces a finding, pinning the cross-module
    decision as behaviour rather than as a comment.
16. `test_the_duplicate_check_reads_async_and_class_definitions` feeds a synthetic source with
    `async def test_x` twice and `class Thing` twice and asserts two findings.
17. A test module that will not parse is a failure naming the file and quoting the `SyntaxError`,
    not a collection error or a traceback from `ast.parse`. A test proves it, by feeding
    `duplicate_definitions` a source that is not valid Python and asserting the raised message
    names the `where` it was given.

### The anchored-pin check (#65, the mechanism)

18. `message_pins(source, where)` returns every keyword argument named `match` belonging to a
    call whose callee name is `raises` or `warns`, whether written `pytest.raises(...)` or
    `raises(...)`, with the call's first and last line numbers and, when the value is a plain
    `str` constant, its pattern. `re.match(...)` is not such a call and is never returned; nor is
    an assignment to a variable named `match`.
19. `unanchored_pins(source, where)` returns the pins that are neither anchored nor marked.
    **Anchored** means the pattern is a `str` constant whose first character is `^`. **Marked**
    means some physical line in `range(call.lineno, call.end_lineno + 1)` carries a comment
    matching `#\s*unanchored:\s*(.+)` whose reason, stripped, is at least 20 characters. Comments
    are found with `tokenize`, because the AST does not hold them.
20. A `match=` whose value is not a `str` constant (a variable, an f-string, a concatenation) is
    returned by `unanchored_pins` too, with its own explanation: the pattern has to be a literal
    for this check to read it, or the call has to carry the marker. A test proves it with a
    synthetic `pytest.raises(TypeError, match=PATTERN)`.
21. `unanchored_pin_message(where, line, pattern)` contains: the POSIX path; the line number; the
    pattern as written; the sentence that `match=` is an `re.search` and not a full match, so a
    pattern matching a superstring pins nothing; the concrete collision, that `Money` says
    `Money currency must be a Currency, ...` which contains `currency must be a Currency` from
    index 6, so on PR #62 both the broken test and its first proposed repair passed with the
    guard deleted; the fix, which is a leading `^` plus enough of the message that no other
    exception the same call can raise would match it; and the escape hatch, that a deliberate
    substring pin carries `# unanchored: <why>` on the `pytest.raises` call. A test asserts each
    element.
22. `test_every_message_pin_is_anchored_or_says_why` is parametrised over `TEST_SOURCES` with the
    POSIX path as the id, and reports every offending pin in that file in one failure.
23. `test_the_pin_check_still_bites` is written in the shape of
    `test_the_narrowed_status_rule_still_bites` in `tests/test_shell_behaviour.py`, and asserts on
    synthetic sources that the check:
    a. flags `with pytest.raises(TypeError, match="currency must be a Currency"):`;
    b. accepts `with pytest.raises(TypeError, match=r"^currency must be a Currency"):`;
    c. accepts an unanchored pin whose line carries
       `# unanchored: the id is all this refuses to name` (a reason over 20 characters);
    d. flags the same unanchored pin when the marker is `# unanchored:` with nothing after it,
       and when the reason is under 20 characters;
    e. accepts a marker written on the last line of a call wrapped over three lines;
    f. flags `pytest.raises(TypeError, match=PATTERN)`, where the pattern is a name;
    g. does **not** flag `if re.match(r"#{1,6} ", line):` nor
       `match = re.match(r"\*\*(.+?)\*\*", bullet)`, both of which
       `tests/test_web_shell.py` really contains at lines 1325 and 1352;
    h. does **not** flag a bare `pytest.raises(TypeError)` with no `match=` at all.
24. Both new checks read files with `Path.read_text(encoding="utf-8")`, so a checkout with CRLF
    line endings gives the same line numbers and the same result as one with LF. A comment says
    so.

### The audit of the 13 (#65, the part reading cannot replace)

25. Every one of the 13 unanchored pins below is audited. For each: the guard the test exists to
    pin is deleted from `src/`, the test is run **alone by node id** with
    `PYTHONDONTWRITEBYTECODE=1`, the outcome is recorded, and the guard is restored with
    `git checkout --` before the next deletion. Running alone matters because deleting a guard
    reds other tests too, and those failures are noise here.

    | # | file | line today | test | pattern |
    |---|---|---|---|---|
    | 1 | `tests/test_split.py` | 265 | `test_split_by_weight_rejects_weights_that_all_sum_to_zero` | `"zero"` |
    | 2 | `tests/test_split.py` | 401 | `test_split_equally_rejects_a_repeated_member` | `"more than once"` |
    | 3 | `tests/test_balances.py` | 290 | `test_an_element_that_is_not_a_ledger_event_raises_type_error_naming_it` | `"dict"` |
    | 4 | `tests/test_balances.py` | 292 | the same test, second block | `"NoneType"` |
    | 5 | `tests/test_balances.py` | 297 | `test_a_group_id_that_is_not_a_str_raises_type_error` | `"int"` |
    | 6 | `tests/test_balances.py` | 307 | `test_a_currency_that_is_not_a_currency_raises_type_error` | `"str"` |
    | 7 | `tests/test_balances.py` | 331 | `test_a_foreign_settlement_is_rejected_too` | `"s-foreign"` |
    | 8 | `tests/test_balances.py` | 375 | `test_a_repeated_expense_id_is_a_domain_error_naming_the_id` | `"e1"` |
    | 9 | `tests/test_balances.py` | 384 | `test_a_repeated_settlement_id_is_a_domain_error_naming_the_id` | `"s1"` |
    | 10 | `tests/test_balances.py` | 386 | the same test, `settlement_states` block | `"s1"` |
    | 11 | `tests/test_balances.py` | 396 | `test_a_repeated_decision_id_is_a_domain_error_naming_the_id` | `"d1"` |
    | 12 | `tests/test_balances.py` | 412 | `test_both_public_functions_refuse_a_log_that_double_counts_an_expense` | `"e1"` |
    | 13 | `tests/test_balances.py` | 414 | the same test, `settlement_states` block | `"e1"` |

    Line numbers are today's locators and will move; the test name and the pattern identify the
    pin. Several pins share one guard (3 and 4; 8, 9, 10, 11, 12 and 13 all reach
    `_sorted_unique`), so the number of guard deletions is smaller than 13 and is whatever the
    audit finds, not a target.
26. Two pins are flagged in advance as the highest suspicion, and the audit must state
    explicitly what it found for each rather than letting them pass in a list:
    * **#6**, `match="str"` on `test_a_currency_that_is_not_a_currency_raises_type_error`. This is
      the PR #62 shape in another file: `Money currency must be a Currency, got str: 'AUD'`
      contains `str`, so if deleting `balances._require_currency`'s raise lets the call reach
      `Money`, the pin pins nothing.
    * **#13**, `match="e1"` on the `settlement_states` block. That test's docstring says
      `settlement_states` refuses this ledger for the repeated **expense** id, and `"e1"` cannot
      tell "the same expense id appears twice" from any other message naming `e1`.
27. Each pin ends the task either anchored with a leading `^` or carrying
    `# unanchored: <reason over 20 characters>`. The anchored replacement is **derived from the
    message the run actually printed**, and that message is quoted verbatim in the record. A
    pattern written from reading the source, without a run behind it, is the defect this task
    exists to remove and is not acceptable evidence.
28. Every anchored pattern is a raw string, escapes any regex metacharacter that appears
    literally in the message (`[`, `(`, `.`, `?`, `+`, `*`, `\`), and stops before an awkward tail
    rather than spelling a fragile one. `$` is used only where the message provably ends there.
29. `uv run python -m pytest --collect-only -q tests/test_split.py tests/test_balances.py`
    produces the identical list of test ids before and after the pin work, unless the Findings
    section records a rung 2 fix (criterion 30), in which case the diff is exactly what Findings
    says and nothing else. No test in either file is added, deleted, renamed, reordered, loosened
    or reparametrised by the anchoring itself.
30. **A pin that pins nothing is a finding, not a failure.** The resolution ladder is followed and
    the rung reached is recorded for every pin that is not rung 1:
    * **Rung 1.** The pin was loose, the guard is real and fires first. Anchor it; the test stays
      green. Ordinary, and no Findings entry beyond the record.
    * **Rung 2.** The pin was loose and the test passed only on somebody else's refusal. Anchoring
      turns it red. Change the test's **arrangement** (a different argument, a different call) so
      it reaches the guard its name claims, keeping the name and the claim. Test only, in scope,
      and recorded in Findings with the before and after.
    * **Rung 3.** The guard the test names does not exist, and no arrangement makes the anchored
      test green. **Stop.** Do not weaken the pattern, do not mark it `unanchored`, do not delete
      the test, do not skip or xfail it (`.claude/rules/testing.md` forbids the last), and do not
      add the guard: `src/` is out of scope for this task. Record the exact evidence in Findings,
      open a GitHub issue naming the missing guard and quoting the run, and ask the user how to
      proceed before doing anything else.
31. No test anywhere is deleted, renamed to something that claims less, loosened, or marked
    `skip` or `xfail`. Any test whose shape changes at all is listed in Findings with its before
    and after.
32. Nothing under `src/` is edited. Every guard deleted during the audit is restored, and
    `git diff src/` is empty at the end.

### The mutation record (#60)

33. `plans/mutations/README.md` exists and states, each as its own short section:
    a. what the directory is for, in one paragraph, quoting #60's finding that a description
       standing in for the thing itself produced a different mutation and a different result;
    b. the record format: a fenced ` ```json ` block per mutation, with exactly the keys `id`,
       `file`, `find`, `replace`, `kills`, `survives` and `result`; `find` and `replace` are exact
       source text; `kills` and `survives` are lists of pytest node ids or harness scenario names;
       `result` is one of `"killed"`, `"survived"` or `"killed-for-the-wrong-reason"`;
    c. that `file`, `find` and `replace` are deliberately the same three keys the JavaScript
       harness accepts in `substitutions`, so a JavaScript record pastes straight into a harness
       config with no translation;
    d. the recipe for a Python record: read the file, assert the anchor occurs **exactly once**,
       replace, run the node ids in `kills`, revert with `git checkout -- <file>`. Stdlib only,
       run from the repo root, and **no new file under `scripts/`** (that directory's contents are
       pinned by `test_scripts_holds_exactly_the_promised_python_files`);
    e. `PYTHONDONTWRITEBYTECODE=1` on every Python mutation run, with the reason: CPython
       invalidates a cached `.pyc` on `(mtime, size)`, so two same-size mutations of one file
       inside one second run stale bytecode, which happened on PR #62 and looked exactly like a
       genuine finding. Deleting `__pycache__` between runs is the alternative. The JavaScript
       harness is immune because it substitutes into source text at run time and caches nothing;
    f. the three-part test for when a mutation earns a **committed** mutant instead of a record
       (only evidence that a test bites; survives against the pre-test code; leaves a working
       system with a named surviving control), the one-per-defect-class-per-task cap, and a
       pointer to `MUTANT_A` through `MUTANT_F` in `tests/test_shell_behaviour.py` as the working
       example and to `mutated()` there as what makes an anchor self-checking;
    g. that the suite does **not** re-verify a record's anchor against live source, and why:
       re-verifying would put every past mutation in the path of every future refactor, which is
       the ossification #60 warns against. A committed mutant is re-run; a recorded one is
       re-runnable.
34. `plans/mutations/65-message-pins.md` exists and holds one section per guard deleted in the
    audit. Each section carries: the JSON record; the **exact message the run printed**, quoted;
    the pins from criterion 25 that guard covers, by test name; and the verdict in one sentence.
    Every one of the 13 pins appears in exactly one section.
35. `test_every_recorded_mutation_is_machine_readable`, in `tests/test_suite_integrity.py`, walks
    `plans/mutations/*.md` except `README.md` and asserts for every fenced ` ```json ` block: it
    parses; its keys are exactly the seven required; `id` is a non-empty string unique within the
    file; `file` is a non-empty relative POSIX path with no `..` and no drive letter; `find` is
    non-empty; `find != replace`; `kills` and `survives` are lists of strings; `result` is one of
    the three permitted words; and `kills` is non-empty when `result` is `"killed"`.
36. `test_a_mutation_record_holds_no_prose_only_section` asserts every `##` section of every
    record file (README excluded) contains at least one fenced JSON block. This is the criterion
    that stops sentences creeping back in, which is the whole of #60.
37. `test_the_mutation_records_are_not_re_verified_against_source` is not written. Instead a
    comment beside the two tests above states that the anchor is deliberately not checked against
    the live file, giving the ossification reason, so the next reader does not "improve" the check
    into the thing #60 argued against.
38. No committed Python mutant is added, no mutation runner is added, no file under `scripts/` is
    created, and `tests/test_shell_behaviour.py` is not edited. `git diff` shows no change to that
    file at all.

### The rules, which is the destination all three share

39. `.claude/rules/testing.md` keeps its three existing bullets **verbatim and in their existing
    order**, and its front matter `paths` list gains `"plans/mutations/**"` alongside the two
    entries it has.

    > **Corrected 2026-09-07, during implementation.** This criterion used to say "its four
    > existing bullets". The file holds three. It was written from a line count rather than a
    > bullet count: the first bullet wraps across two physical lines, so lines 7 to 10 of the
    > file are four lines and three bullets. Measured on the commit this task branches from,
    > `72b86c0`: the file is 317 bytes and `grep -c '^- ' .claude/rules/testing.md` returns 3.
    > The three are the `uv run python -m pytest` bullet, the exact-integer settle-up bullet
    > and the never-skip-or-xfail bullet. Nothing else about the criterion changes: every
    > existing bullet is still kept verbatim and in its existing order.
40. It gains a section holding six rules, each stated as the rule in bold followed by the defect
    that produced it, because a rule without its scar is one nobody believes:
    a. **Message pins are anchored.** `pytest.raises(match=)` is an `re.search`, not a full match.
       Lead with `^` and spell enough of the message that no other exception the same call can
       raise would match it. Scar: on PR #62 a test written to prove the currency is validated
       before the total stayed green with the guard deleted, and the first proposed repair,
       `match="currency must be a Currency"`, had the same defect, because `Money` says
       `Money currency must be a Currency, ...`. A deliberate substring pin carries
       `# unanchored: <why>`, and `tests/test_suite_integrity.py` refuses one without a reason.
    b. **A test function defined twice in one module deletes the first one.** Python rebinds
       silently and pytest collects only what the module ends up holding. Scar: on PR #64 four
       parametrised cases stopped running with the suite green, found only because somebody
       reconciled a pass count arithmetically. `tests/test_suite_integrity.py` refuses it now.
    c. **If a test's name mentions concurrency, staleness or a guard, its body has a second
       actor.** Scar: a 409 described as a race guard whose test only ever ran the sequential
       case, so it could not have failed for the reason its name gave.
    d. **A fixture that is both the stubbed response and the expected value cannot detect its own
       drift.** Scar: a harness constant set to nonsense while all three scenarios stayed green;
       only a cross-language pin against a live response caught it.
    e. **A mutation is recorded as an anchor and a replacement, never as a sentence.** Scar:
       reconstructing "choose the shape from something other than ids" from a PR body produced a
       different mutation and a different result, killing one scenario where QA had recorded two.
       Records go in `plans/mutations/`; `plans/mutations/README.md` says when one earns a
       committed mutant instead.
    f. **A Python mutation run sets `PYTHONDONTWRITEBYTECODE=1`.** CPython invalidates bytecode on
       `(mtime, size)`, so two same-size mutations within one second run stale bytecode. Scar: a
       false mutation result on PR #62 that looked exactly like a genuine finding. The JavaScript
       harness is immune, because it substitutes into source text at run time and caches nothing.
41. `test_the_testing_rules_keep_the_three_they_had` asserts the three existing bullets are
    present as three exact strings. Nothing is removed from that file by this task or a later one
    without this test going red.

    > **Corrected 2026-09-07, during implementation.** This criterion used to name the test
    > `test_the_testing_rules_keep_the_four_they_had` and to ask for "four exact strings", for
    > the same line-versus-bullet reason recorded under criterion 39. The name is corrected
    > along with the count rather than kept for continuity, because a test named
    > `..._keep_the_four_they_had` whose body asserts three strings is a test whose name
    > overclaims its body, and it would have sat inside the very module this task adds to stop
    > tests whose names overclaim their bodies. It would also have been invisible: three exact
    > strings all present, the suite green, and the only tell a word in a function name. That
    > is the defect of #67 in miniature, so the name moves.
42. `test_the_testing_rules_name_the_mechanisms_that_enforce_them` asserts the file contains the
    strings `tests/test_suite_integrity.py`, `plans/mutations/`, `# unanchored:`,
    `PYTHONDONTWRITEBYTECODE`, `re.search` and `match=r"^`. A rule whose mechanism was renamed or
    deleted goes red rather than sitting there naming something that is gone.
43. `CLAUDE.md` gains, under "Where things live", one bullet for `plans/mutations/` (recorded
    mutations, anchor and replacement, re-runnable; the committed ones live in
    `tests/test_shell_behaviour.py`) and one clause on the existing `tests/` bullet naming
    `tests/test_suite_integrity.py` as the suite's check on itself. Nothing else in `CLAUDE.md`
    changes, the paragraph containing "no build step" is untouched, and every document test in
    `tests/test_web_shell.py` passes unedited.

### The demonstrations, which are the point

44. **A duplicate test name reds the suite and names both lines.** QA performs this and records
    every output in the QA note.
    a. On a clean tree, `uv run python -m pytest` reports 0 failed, 0 skipped, 0 xfailed. Record
       the passed count. Record `uv run python -m pytest -q tests/test_balances.py` separately and
       record that count too.
    b. Append to `tests/test_balances.py` a second
       `def test_a_repeated_expense_id_is_a_domain_error_naming_the_id() -> None:` whose body is
       `assert True`.
    c. `uv run python -m pytest -q tests/test_balances.py` is **green**, and its passed count is
       **unchanged** from (a). This is the silence the whole issue is about, and it is quieter
       than this criterion first claimed: the module that just lost a test reports success, and
       the count does not even move.

       > **Corrected 2026-09-07, during implementation.** This criterion used to read "and its
       > passed count is exactly one lower than in (a)". Measured on this branch: **152 passed
       > before, 152 passed after — unchanged**. The prediction was wrong because
       > `test_a_repeated_expense_id_is_a_domain_error_naming_the_id` is a single,
       > non-parametrised test, so shadowing it removes one collected test and adds one, and the
       > arithmetic is invariant. The count does move when the shadowed test is **parametrised**,
       > which was verified rather than assumed: appending a single
       > `def test_an_empty_member_id_is_a_domain_error` over the two-case parametrised test of
       > that name takes `tests/test_balances.py` from 152 to 151, green both times. That is what
       > makes the distinction real rather than inferred.
       >
       > The consequence is larger than the correction, and is recorded in rule (b) of
       > `.claude/rules/testing.md`: reconciling a test count catches a duplicate that shadows a
       > parametrised test and does not catch one that shadows a single test. **The PR #64
       > collision was only ever caught because the shadowed test happened to be parametrised.**
       > Had those four cases been one, nobody would have noticed, the suite would have been
       > green, and the test would simply have stopped existing. That is the argument for
       > criterion 7's check rather than for the discipline, and it exists because a prediction
       > was measured instead of trusted.
    d. `uv run python -m pytest` is **red**, with the failure coming from
       `tests/test_suite_integrity.py::test_no_test_module_defines_a_name_twice[tests/test_balances.py]`,
       and its message names `tests/test_balances.py`, the duplicated name and **both** line
       numbers. Record the message in full and check it against criterion 6 element by element.
    e. Remove the duplicate. `uv run python -m pytest` reports 0 failed, 0 skipped, 0 xfailed with
       the same passed count as (a).
45. **An unanchored pin cannot fail, and anchoring it makes it able to.** QA performs this on
    `tests/test_split.py:519`, which is the pin PR #62 already fixed, and records all four
    outputs. Every run in this criterion sets `PYTHONDONTWRITEBYTECODE=1`.
    a. Delete the `^` from `match=r"^currency must be a Currency"`, leaving
       `match=r"currency must be a Currency"`.
    b. Delete the guard the test names: `_require_currency`'s `raise TypeError` in
       `src/splitwise_lite/split.py`.
    c. Run the test alone by node id. It is **green**. Record the count. This is a test that
       cannot fail, running against code whose guard has been removed.
    d. Restore the `^`, leaving the guard still deleted. Run the same node id. It is **red**, and
       the failure is a regex mismatch quoting `Money currency must be a Currency`, not
       `DID NOT RAISE`. Record it. The leading `^` is the whole of the difference between (c) and
       (d).
    e. Restore the guard with `git checkout -- src/splitwise_lite/split.py`. The node id is green
       and `git diff src/` is empty.
46. **A recorded mutation can be re-run by somebody who did not write it.** QA picks one record
    from `plans/mutations/65-message-pins.md`, applies it using only what
    `plans/mutations/README.md` says (including asserting the anchor matches exactly once and
    setting `PYTHONDONTWRITEBYTECODE=1`), runs the node ids in `kills`, and confirms the recorded
    `result` reproduces. Reverts with `git checkout --`. Records which record it chose, the
    commands it ran and what it saw. If the record cannot be re-run from the file alone, that is a
    FAIL against #60, whatever else passes.
47. `uv run python -m pytest` passes with 0 failed, 0 skipped and 0 xfailed. The passed count is
    2343 plus the number of tests this task adds; the pin work adds none and removes none
    (criterion 29). QA records the exact number and the arithmetic that reaches it, because
    reconciling a count arithmetically is the only thing that caught #67 in the first place.

### The files

48. The files this task creates or edits are exactly these eight, and no others in either
    direction:
    * `tests/test_suite_integrity.py` (new)
    * `tests/test_split.py` (pins only)
    * `tests/test_balances.py` (pins only)
    * `.claude/rules/testing.md`
    * `plans/mutations/README.md` (new)
    * `plans/mutations/65-message-pins.md` (new)
    * `CLAUDE.md` (one bullet and one clause)
    * this spec, if it needs correcting
49. `git diff --stat` shows **no** path under `src/`, `app/` or `scripts/`, and does not show
    `tests/test_web_api.py`, `tests/test_web_shell.py` or `tests/test_shell_behaviour.py`.
50. Because no file under `app/` changes, `SHELL_DIGEST` in `app/sw.js` **must not move** and
    `VERSION` must not be bumped. If
    `tests/test_web_shell.py::test_the_recorded_digest_matches_the_files_it_covers` fails, this
    task has touched something it must not, and the fix is to put the file back, never to paste a
    new digest.
51. `pyproject.toml` and `uv.lock` are byte-identical to `master`. No new dependency, no mutation
    framework, in either language.
52. The Findings section of this file is filled in before the PR is opened: every rung 2 or rung 3
    outcome from criterion 30, every test whose shape changed, the count of `# unanchored:`
    markers now in the suite with the reason for each, and the arithmetic from criterion 47. An
    empty Findings section with a non-trivial audit behind it is itself a prose record standing in
    for the thing, which is the defect this task exists to remove.

## Findings

**Audit results.** All thirteen pins reached **rung 1**. In every case the guard the test names
is real, fires first, and is the only thing that refuses the arrangement: with it deleted the
call either raised nothing at all or died somewhere unrelated, and never produced a different
exception that the loose pattern would have accepted. Nothing reached rung 2 or rung 3, so no
test's arrangement was changed and nothing was escalated. Seven guard deletions covered the
thirteen pins, each recorded with its anchor, its replacement and the message it printed in
`plans/mutations/65-message-pins.md`.

| # | test | guard deleted | rung | what the deletion produced |
|---|---|---|---|---|
| 1 | `test_split_by_weight_rejects_weights_that_all_sum_to_zero` | `split._allocate` | 1 | `ZeroDivisionError: integer division or modulo by zero` |
| 2 | `test_split_equally_rejects_a_repeated_member` | `split._ordered_from_iterable` | 1 | `DID NOT RAISE InvalidSplit` |
| 3 | `test_an_element_that_is_not_a_ledger_event_raises_type_error_naming_it` | `balances._partition` | 1 | `DID NOT RAISE TypeError` |
| 4 | the same test, second block | `balances._partition` | 1 | nothing raised (see note below) |
| 5 | `test_a_group_id_that_is_not_a_str_raises_type_error` | `balances._require_group_id` | 1 | `DID NOT RAISE TypeError` |
| 6 | `test_a_currency_that_is_not_a_currency_raises_type_error` | `balances._require_currency` | 1 | `DID NOT RAISE TypeError` |
| 7 | `test_a_foreign_settlement_is_rejected_too` | `balances._require_group` | 1 | `DID NOT RAISE InvalidLedger` |
| 8 | `test_a_repeated_expense_id_is_a_domain_error_naming_the_id` | `balances._sorted_unique` | 1 | `DID NOT RAISE InvalidLedger` |
| 9 | `test_a_repeated_settlement_id_is_a_domain_error_naming_the_id` | `balances._sorted_unique` | 1 | `DID NOT RAISE InvalidLedger` |
| 10 | the same test, `settlement_states` block | `balances._sorted_unique` | 1 | nothing raised (see note below) |
| 11 | `test_a_repeated_decision_id_is_a_domain_error_naming_the_id` | `balances._sorted_unique` | 1 | `DID NOT RAISE InvalidLedger` |
| 12 | `test_both_public_functions_refuse_a_log_that_double_counts_an_expense` | `balances._sorted_unique` | 1 | `DID NOT RAISE InvalidLedger` |
| 13 | the same test, `settlement_states` block | `balances._sorted_unique` | 1 | nothing raised (see note below) |

*Pins 4, 10 and 13 are second blocks of tests whose first block reds first, so the node-id run
cannot show them failing on their own. Each was audited by performing its exact call under the
same guard deletion — `settlement_states([None])`, `settlement_states` over the repeated
settlement ledger, and `settlement_states` over the double-counted expense ledger — and each
raised nothing at all. A masked pin is not an audited pin, so these were run rather than
inferred from the guard they share.*

**The two pins criterion 26 flagged in advance.**

*Pin 6, `match="str"`, `test_a_currency_that_is_not_a_currency_raises_type_error`.* **Not** the
PR #62 shape, although the collision it warns about is real in the abstract:
`balances._require_currency` says `currency must be a Currency, got str: 'AUD'` and `Money` would
say `Money currency must be a Currency, got str: 'AUD'`, which contains `str` just as readily.
What saves this pin is the arrangement rather than the pattern. The test calls
`derive_balances([], group_id=GROUP, currency="AUD")` with an **empty** event list, so nothing
downstream ever constructs a `Money` with the bad currency. With the guard deleted the call
raised nothing at all rather than raising `Money`'s superstring, so the pin did depend on the
guard its name claims. Rung 1. The pattern was nevertheless weak enough that the same test over a
non-empty ledger would have gone green on `Money`'s refusal, which is exactly why it is now
`match=r"^currency must be a Currency, got str"`.

*Pin 13, `match="e1"` on the `settlement_states` block.* Holds, for a similar reason. The worry
was that `"e1"` cannot tell "the same expense id appears twice" from any other message naming
`e1`. With `_sorted_unique`'s refusal deleted, `settlement_states` over that ledger raised
**nothing at all**, so there was no other message naming `e1` standing in for it. Rung 1. The
anchored pattern now names the label as well as the id
(`^the same expense id appears twice in the ledger: 'e1'$`), so an expense collision can no longer
be satisfied by a settlement or a decision one.

**Tests whose shape changed.** None. Thirteen `match=` pattern strings changed and nothing else:
no test added, deleted, renamed, reordered, loosened, skipped, xfailed or reparametrised.
`uv run python -m pytest --collect-only -q tests/test_split.py tests/test_balances.py` reports the
identical 332 ids before and after; the two listings were diffed and are byte-identical.

**Unanchored markers now in the suite.** **None.** Zero `# unanchored:` markers. Every one of the
thirteen pins was anchorable against the message its guard really prints, so no pin needed the
escape hatch. The marker mechanism is exercised only by the synthetic sources in
`test_the_pin_check_still_bites`, which is where its accept and refuse cases are pinned.

**Count arithmetic.** 2343 on master, plus 49 added by `tests/test_suite_integrity.py`, equals
**2392**, which is what the suite reports with 0 failed, 0 skipped and 0 xfailed. The pin work
adds none and removes none. The 49 are **15 single tests plus 2 checks parametrised over 17 test
modules** (2 x 17 = 34; 15 + 34 = 49):

* Parametrised, 17 cases each, one per `*.py` file under `tests/` (16 modules on master plus
  `tests/test_suite_integrity.py` itself): `test_no_test_module_defines_a_name_twice`,
  `test_every_message_pin_is_anchored_or_says_why`.
* Single: `test_test_sources_is_every_test_module`,
  `test_the_duplicate_check_catches_a_duplicate_test`,
  `test_the_duplicate_check_catches_a_duplicate_fixture`,
  `test_the_duplicate_check_leaves_a_nested_definition_alone`,
  `test_the_duplicate_check_looks_at_one_module_at_a_time`,
  `test_the_duplicate_check_reads_async_and_class_definitions`,
  `test_a_module_that_will_not_parse_names_the_file_and_quotes_the_error`,
  `test_the_duplicate_definition_message_says_what_happened`,
  `test_the_pin_check_still_bites`,
  `test_a_pin_whose_pattern_is_not_a_literal_is_flagged`,
  `test_the_unanchored_pin_message_says_what_happened`,
  `test_every_recorded_mutation_is_machine_readable`,
  `test_a_mutation_record_holds_no_prose_only_section`,
  `test_the_testing_rules_keep_the_three_they_had`,
  `test_the_testing_rules_name_the_mechanisms_that_enforce_them`.

Because both parametrised checks are driven by `TESTS.rglob("*.py")`, this number moves on its
own: a later task that adds one test module adds three tests, its own plus one case in each check.

**A criterion that did not hold as written: 44c.** Criterion 44c predicts that after appending a
second `def test_a_repeated_expense_id_is_a_domain_error_naming_the_id`, the count from
`uv run python -m pytest -q tests/test_balances.py` is "exactly one lower" than in 44a. It is
**not**. Measured: **152 passed before, 152 passed after** — unchanged. The test the criterion
names is a single, non-parametrised test, so shadowing it removes one test and adds one test and
the arithmetic is invariant. Shadowing a **parametrised** test does move the count, which is
presumably the shape the criterion was written from: appending a single
`def test_an_empty_member_id_is_a_domain_error` over the two-case parametrised test of that name
takes the module from 152 to 151, green both times.

Everything else in demonstration 44 holds, and the substance of it holds more strongly than the
criterion claims: the damaged module reports success, and the deleted test really is gone. With
the duplicate in place, deleting `balances._sorted_unique`'s guard — the very guard
`test_a_repeated_expense_id_is_a_domain_error_naming_the_id` exists to pin — leaves that node id
**green**, because the name now resolves to `assert True`.

This is worth recording rather than filing as a nit, because it qualifies the discipline #67 was
found by. Reconciling a pass count arithmetically catches a duplicate that shadows a parametrised
test; it does **not** catch one that shadows a single test, where the count never moves. That is
an argument for the mechanism over the discipline, which is what this task builds.

Put at its sharpest: **the PR #64 collision was only ever caught because the shadowed test
happened to be parametrised.** Had those four cases been one, nobody would have noticed, the
suite would have been green, and the test would simply have stopped existing. "It happened
twice" is the weaker justification for criterion 7's check; this is the strong one.

Criterion 44c has been amended in place to what was measured, with a dated marker, and the
consequence is recorded in rule (b) of `.claude/rules/testing.md`, where somebody deciding
whether the check earns its place will read it rather than having to find it in a spec.

## Out of scope

* **Anything under `src/`.** No guard is added, removed or reworded, no domain message changes,
  and no product behaviour moves. #65 is explicit that the type prefixes in `money.py` are useful
  and the defect is in the pin, not the message. A rung 3 finding stops and asks rather than
  editing `src/`.
* **Anything under `app/` or `scripts/`.** No shell file, no icon, no dev server, no setup
  command, no new script for applying a mutation. `SHELL_DIGEST` does not move.
* **`tests/test_web_api.py` and `tests/test_web_shell.py`.** Not opened for editing. They are on
  the concurrent #16 branch and this task has no reason to touch either.
* **`tests/test_shell_behaviour.py`.** The six committed mutants are the working example this task
  points at; it does not add a seventh, re-express an existing one, or reorganise the file.
* **A mutation-testing framework, a Python mutation runner, or any new dependency.** This repo
  deliberately has none, and #60 says the anchored-substitution approach exists precisely because
  a framework would be a dependency.
* **Cross-module duplicate-name checking**, and duplicate-name checking over `src/` or `scripts/`.
  Decided against above, with reasons, in the check's own comments.
* **Coverage measurement.** #67 observes that coverage is not measured and nothing reports a drop.
  Measuring it is a separate argument with a separate cost, and a duplicate-name check is not a
  down payment on one.
* **CI, a workflow file, a pre-commit hook, or anything that runs the suite for you.** That is
  issue #49, and this task neither does it nor waits for it.
* **Re-measuring the mutations recorded in prose on earlier tasks**, including the ten in #37 and
  the five in the task 14 PR. This task creates the format those would be re-recorded in and does
  not back-fill the archive. #60's own "Related" section frames re-measuring #37 as the work this
  makes possible, which makes it a follow-up and not a part of this.
* **Tidying either audited test file.** No reordering, no renaming, no reformatting of untouched
  lines, no new tests in `tests/test_split.py` or `tests/test_balances.py`. The pin patterns and
  a rung 2 arrangement fix are the whole of the diff in those two files.
* **`plans/backlog.md`, `plans/spec.md` and `README.md`.** Nothing about what the product is, how
  it is run, installed or tested changes. `CLAUDE.md` gains one bullet and one clause and that is
  the whole of the documentation change outside `.claude/rules/testing.md` and `plans/`.

## Constraints

* **Files edited: exactly the eight in criterion 48.** Nothing else, in either direction.
* **No new dependency of any kind.** `pyproject.toml` is not opened and `uv sync` is not needed.
  Per `CLAUDE.md`, a dependency is declared and then installed with `uv sync`, never
  `pip install` or `uv pip install`, and `.claude/hooks/guard-deps.hs.sh` blocks the ad hoc route
  anyway. If something here genuinely cannot be built without a package, stop and get the user's
  approval first.
* **The new module is standard library plus pytest only**, per criterion 2, and imports nothing
  from `splitwise_lite`. Both checks are static: neither imports a test module, neither executes
  anything it reads, and neither runs pytest.
* **Both checks must prove they bite on synthetic input**, following
  `test_the_narrowed_status_rule_still_bites` in `tests/test_shell_behaviour.py`. A green run of a
  lint means nothing on its own; what makes it worth having is a test that the pattern still
  matches the shapes it claims to.
* **Every deliberate omission carries its reason in the file**, following `NOT_PRECACHED` and
  `test_an_omission_with_no_reason_is_refused` in `tests/test_web_shell.py`. That is why the
  `# unanchored:` marker requires 20 characters of reason and why the duplicate check has no
  marker at all.
* **Every failure message is built by a named helper and tested directly**, following
  `stale_digest_message` and `unlisted_shell_file_message` in `tests/test_web_shell.py`, so the
  message cannot rot without a test noticing.
* **Paths in messages and parameter ids are POSIX**, via `Path.relative_to(REPO).as_posix()`, and
  files are read with `encoding="utf-8"`, so line numbers and strings are identical on Windows and
  on Linux.
* **Every Python mutation run in this task sets `PYTHONDONTWRITEBYTECODE=1`**, including the ones
  behind criteria 25, 45 and 46, and every guard deletion is reverted with `git checkout --`
  before the next one.
* **Existing tests are not weakened.** A pin that turns out to pin nothing is a finding, handled by
  the ladder in criterion 30. Nothing is skipped, xfailed, deleted, renamed to claim less, or
  loosened to keep the suite green, and `.claude/rules/testing.md` already forbids the first two.
* Tests run with `uv run python -m pytest`. Plain `uv run pytest` fails on this machine with an
  access-denied spawn error. `node` 20 or later is still a test-time requirement and the
  JavaScript half still runs.
* **Python 3.12 target.** Type annotations on every new function, a docstring on every new name
  stating the invariant it enforces, and a one line comment at each decision recorded in criteria
  8 to 11, 24, 33g and 37, so the next person does not undo one by tidying.
* No test binds a socket, spawns a shell, or writes anywhere but `tmp_path`. The demonstrations in
  criteria 44 to 46 are run by hand, by QA, and are not automated.

## Size

Small, and almost all of it is one new file. `tests/test_suite_integrity.py` is roughly 250 lines:
two `ast` walks of about fifteen lines each, three message helpers, four parametrised checks over
`TEST_SOURCES`, and about a dozen tests over synthetic sources. `tests/test_split.py` and
`tests/test_balances.py` change on 13 lines and no others. `.claude/rules/testing.md` roughly
triples, from four lines to about thirty. `plans/mutations/` is two new markdown files.
`CLAUDE.md` gains a bullet and a clause.

The expensive part is not the code, it is criterion 25: seven or so guard deletions, each with a
run and a recorded message, plus the three demonstrations. Budget for that rather than for the
implementation, and do not shorten it by reading the guards instead of deleting them. Reading is
what let PR #62 ship a repair with the same defect as the bug.

If this task grows a mutation runner, a coverage gate, a cross-module namespace check, a new
dependency, a file under `scripts/`, or an edit to `tests/test_web_api.py`, it has gone wrong.
