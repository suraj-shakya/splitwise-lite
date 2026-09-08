# Recorded mutations

## What this directory is for

Mutation testing is the main verification discipline in this repo, and until now nearly
every task's evidence that its tests bite was a set of mutations run once and then
described in a sentence. That is not evidence anybody else can check. Issue #60 is the
finding that a description standing in for the thing itself produced a different
mutation and a different result: the #14 engineer, re-verifying its own PR's five
mutations, reconstructed "choose the shape from something other than ids" as a
different mutation, which killed one scenario where QA had recorded two. A sentence
cannot be re-run. An anchor and a replacement can. So a mutation claimed anywhere in
this repo is written down here, one file per task or issue, in a form the next person
applies rather than reconstructs.

## The record format

One fenced ` ```json ` block per mutation, holding exactly these seven keys and no
others:

```json
{
  "id": "a name unique within this file",
  "file": "src/splitwise_lite/example.py",
  "find": "the exact source text to replace, matching exactly once",
  "replace": "the exact source text to put in its place",
  "kills": ["tests/test_example.py::test_that_goes_red"],
  "survives": ["tests/test_example.py::test_that_stays_green"],
  "result": "killed"
}
```

`find` and `replace` are exact source text, never a paraphrase and never a diff.
`kills` and `survives` are lists of pytest node ids, or of scenario names for a
JavaScript mutation run through the harness. `result` is one of `"killed"`,
`"survived"` or `"killed-for-the-wrong-reason"` — the third is its own answer because a
mutant that reds a test for a reason unrelated to the mutation is the defect this repo
keeps finding, not a pass.

`tests/test_suite_integrity.py` checks that every block here parses and is complete.

## Why these three keys

`file`, `find` and `replace` are deliberately the same three keys the JavaScript harness
already accepts in its `substitutions` list. A JavaScript record therefore pastes
straight into a harness config with no translation, and a Python one is applied by the
recipe below. One shape for both languages, chosen so that neither needs a converter.

## The recipe for a Python record

Standard library only, run from the repo root. There is deliberately **no new file
under `scripts/`**: that directory's contents are pinned by
`test_scripts_holds_exactly_the_promised_python_files`, and a mutation applier is not
part of the shipped product.

```
PYTHONDONTWRITEBYTECODE=1 python -c "
import json, pathlib, sys
record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
target = pathlib.Path(record['file'])
source = target.read_text(encoding='utf-8')
assert source.count(record['find']) == 1, 'anchor did not match exactly once'
target.write_text(source.replace(record['find'], record['replace']), encoding='utf-8')
" record.json
```

Then run the node ids in `kills`, alone, and revert with
`git checkout -- <file>`. Running alone matters: deleting a guard reds other tests too,
and those failures are noise.

The assertion that the anchor matches **exactly once** is the part not to skip. An
anchor that matches twice mutates two places, and an anchor that matches zero times
mutates nothing while the run still reports a result.

That assertion is also checked in the suite now, over every record in this directory, by
`test_every_recorded_anchor_matches_once_or_is_carried` in
`tests/test_suite_integrity.py`, so a committed record whose anchor will not apply is a
failing test rather than a surprise for whoever next tries to re-run it. The JavaScript
half asserts the same thing at run time: `tests/shell_harness.mjs` throws a harness
error, exit status 2, when a substitution matched anything other than exactly once. Both
appliers want the same precondition, which is why one check covers both.

## Always set PYTHONDONTWRITEBYTECODE=1

Every Python mutation run sets `PYTHONDONTWRITEBYTECODE=1`, or deletes `__pycache__`
between runs. CPython invalidates a cached `.pyc` on `(mtime, size)`, so two mutations
of the same size applied to one file within the same second run **stale bytecode**, and
the run reports the previous mutation's result. That happened on PR #62 and looked
exactly like a genuine finding.

The JavaScript harness is immune, because it substitutes into source text at run time
and caches nothing. That is a further argument for the harness shape wherever it is
available.

## When a mutation earns a committed mutant instead

Most mutations are recorded here. A few are worth committing as a permanent mutant that
the suite re-runs every time. All three of these have to hold:

1. It is the only evidence that some shipped test bites. If another committed mutant
   already kills that test for the same reason, this one does not get committed.
2. It survives against the code as it was **before** the test it measures existed, so it
   names a defect that could really have shipped rather than one invented to be killed.
3. It leaves a working system with one behaviour broken, and a named control that
   survives it.

Plus a cost cap, because committing all of them would be slow and would ossify: **at
most one committed mutant per defect class per task**, and the PR states the run cost
the new mutant adds.

`MUTANT_A` through `MUTANT_F` in `tests/test_shell_behaviour.py` are the working
example, with `UNRELATED` as the named surviving control, and `mutated()` there is what
makes an anchor self-checking — it asserts the anchor still matches exactly once and
tells you to re-express the mutant rather than weaken it.

## What the suite checks about these anchors, and what it does not

`tests/test_suite_integrity.py` checks four things about this directory. Each states one
guarantee and none of them restates another's, so read the boundaries rather than the
sum:

- **A record parses and is complete**, seven keys and no others:
  `test_every_recorded_mutation_is_machine_readable`.
- **A section records a mutation rather than describing one**:
  `test_a_mutation_record_holds_no_prose_only_section`.
- **A node id in a record's prose is one that record lists**:
  `test_every_node_id_a_record_names_is_one_it_lists`.
- **A record's `find` occurs exactly once in the file its own `file` key names, or the
  record is declared stale with a reason**:
  `test_every_recorded_anchor_matches_once_or_is_carried`, added for issue #87. Exactly
  once is the precondition of both appliers, so a green run of that check is the
  statement that the recipe above will apply the record. The declarations live in
  `CARRIED_STALE_ANCHORS`, keyed by record file and record id and never by a section
  heading, an ordinal or a line number, totalled in the declared integer
  `CARRIED_STALE_TOTAL`, and checked as a set equality in both directions so a
  declaration cannot outlive its subject. Every reason names the change that broke the
  anchor with a `#NN`, and every declared record also carries a dated note in its own
  section, so a reader of the record learns it there instead of from a test module.

**What none of them does.** No recorded mutation is re-run, and no `result` is verified.
A record whose anchor matches is proven **appliable**, meaning the recipe above will
apply it, and is not proven correct. Its recorded verdict is a measurement somebody took against a tree
that record names, and only re-running the mutation says whether that verdict still
holds. Do not finish this section believing the suite now proves a record correct: it
reads the anchors as text and counts them, and that is the whole of it.

**No repair is demanded of anybody, and the ossification argument is answered rather
than abandoned.** A rename in `src/` may rot a dozen historical anchors, and not one of
them has to be edited, re-derived or deleted. The answer is a declaration: one entry per
record file, plus a dated note in the record. So the baseline is expected to grow
whenever a correct change breaks an anchor, and what the check refuses is an
**undeclared** stale anchor rather than a stale one. A record going stale is still
expected rather than a defect; what has changed is that it is now recorded when it
happens rather than discovered years later by somebody trying to re-run it. What holds
that list honest is not another check: it is a reviewer reading a diff that includes a
bump to a declared integer, and the dated note the declaration costs in the record
itself.

**Re-deriving `find` against today's source is the wrong repair.** The worked example is
`g2-repeated-member` in `65-message-pins.md`, which matched zero times from the day #61
edited the guard it quotes. Editing its `find` would leave the message it recorded, its
result and its node ids standing beside an anchor they were never measured against.
It is retired in place with a dated note instead, and repair, for whoever wants it, is a
fresh run and a **new** record with a new id.

> **Retired 2026-09-08 for issue #87**, per
> `plans/tasks/87-a-mutation-records-anchor-matches-zero-times.md`. This section was
> headed "The suite does not re-verify these anchors" and said that
> `tests/test_suite_integrity.py` "deliberately does **not** check that a record's
> `find` still matches the live source file". That sentence is now false, and the
> heading with it. Its reasoning was: "Re-verifying would put every past mutation in the
> path of every future refactor, which is precisely the ossification #60 warns against:
> a rename in `src/` would red a dozen historical records that were correct when they
> were taken." That worry was right and is not retired; the declaration route is the
> answer to it, because a rotted anchor is declared once with a reason and never
> repaired under duress. The section also closed: "A committed mutant is re-run; a
> recorded one is re-runnable. That difference is the whole reason both exist, and it is
> why a record going stale is expected rather than a failure." That distinction stands
> word for word. What issue #87 found is that nothing was checking the re-runnable half,
> so a record could quietly stop being re-runnable and the suite stayed green over it
> for as long as nobody tried.
