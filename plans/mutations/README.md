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

## The suite does not re-verify these anchors

`tests/test_suite_integrity.py` checks that a record is machine readable and complete.
It deliberately does **not** check that a record's `find` still matches the live source
file.

Re-verifying would put every past mutation in the path of every future refactor, which
is precisely the ossification #60 warns against: a rename in `src/` would red a dozen
historical records that were correct when they were taken. A committed mutant is
re-run; a recorded one is re-runnable. That difference is the whole reason both exist,
and it is why a record going stale is expected rather than a failure.
