# Task 70: substring assertions on exception messages

**Closes:** GitHub issue **#70**. `plans/backlog.md` has no entry for it and this task does
not add one; the issue is the backlog entry and this file is the implementable version.

**Depends on:** nothing unlanded. Everything named here is on `master` at `bea0da7`.

**Split:** this is **not one task**. This file specifies **70a**, the mechanism, in full,
and then specifies the **seven audit slices 70b to 70h** through one shared criteria set
plus a sized slice table. The argument for the split is in "One task or several" below.
Do not implement 70a and call the issue closed.

---

## How the numbers in this document were obtained

**Bash was unavailable to the author of this document.** No `gh`, no `pytest`, no
`--collect-only`, no `python`. Everything below was measured with **ripgrep**, run through
the agent `Grep` tool, over the worktree at `bea0da7`. Each number carries the pattern that
produced it. Two consequences a reader must hold on to:

* **The issue body was never read.** `gh issue view 70` could not be run and the body is
  mirrored nowhere in this repo. Every characterisation of #70 below is inferred from the
  brief that commissioned this document and from the state of the code. Where this document
  says the issue is wrong, treat that as a claim to check against the issue, not as a
  finding. The same applies to issue **#82**, which could not be read either.
* **No collected-test count appears anywhere in this document**, because none could be
  taken. A criterion that needs one says so and names the command.

Every count below is a count of **matching lines**, which is not always a count of
occurrences: a line holding two matches counts once. Where that distinction could change a
decision it is called out.

---

## What moved since #70 was filed

The issue's counts predate two merges. Re-measured:

| What | Pattern run over `tests/` | Result |
| --- | --- | --- |
| `match=` pins | `match=` | 41 lines: 11 in `tests/test_balances.py`, 5 in `tests/test_split.py`, 25 in `tests/test_suite_integrity.py` |
| ...of which are real pins | the same, read | **16.** The 25 in `tests/test_suite_integrity.py` are that module's own synthetic source constants, regexes and prose |
| ...of which are anchored | the same, read | **16 of 16.** Every one begins `match=r"^` |
| `# unanchored:` markers | `# unanchored:` | 13 lines: 11 in `tests/test_suite_integrity.py`, 2 in `tests/test_error_messages.py`, all of them machinery, synthetic constants or docstrings. **No pin in the suite claims the hatch** |
| direct-form message assertions | `in str\([A-Za-z_]+\.value\)` | **100 lines** across 7 modules |
| message bound to a local first | `=\s*str\([A-Za-z_]+\.value\)` | **27 lines** across 8 modules, each followed by one or more assertions against that local |
| negative substring assertions | `not in str\([A-Za-z_]+\.value\)\|not in message\b` | **17 lines**: 12 in `tests/test_split.py`, 5 in `tests/test_web_api.py` |
| `excinfo.match(` | `\.match\(` | **0.** Still zero, as `message_pins`' docstring claims |

Per-module, the direct form (`in str\([A-Za-z_]+\.value\)`) and the bound form
(`=\s*str\([A-Za-z_]+\.value\)`):

| Test module | direct | bound |
| --- | --- | --- |
| `tests/test_store.py` | 51 | 1 |
| `tests/test_groups.py` | 19 | 8 |
| `tests/test_web_api.py` | 12 | 5 |
| `tests/test_balances.py` | 7 | 2 |
| `tests/test_split.py` | 5 | 4 |
| `tests/test_simplify.py` | 4 | 4 |
| `tests/test_money.py` | 2 | 0 |
| `tests/test_web_shell.py` | 0 | 2 |
| `tests/test_suite_integrity.py` | 0 | 1 |
| **total** | **100** | **27** |

`tests/test_money.py` is the one module with direct-form assertions and no bound form; the
zero is measured, not an omission.

**So: 14 has become 16, and 94 has become at least 100.** Read the second of those with the
caveat it needs: the issue's definition of "substring assertion" could not be read, so 100 is
comparable to 94 only if the issue counted the direct form the same way. The pin count is the
solid one, because there is only one way to count a `match=`. If the issue's 94 included the
bound form, then the population it named was already larger than 94 and is larger still now.
Either way the direction is the same, and the deltas fall inside the days between the issue
being filed and this document. That is
the first finding, and it is a finding about the shape of the fix rather than about the
size: **any number this task writes down will be wrong by the time somebody reads it.** The
mechanism below therefore computes the population and prints it, and no criterion here
hardcodes it.

The issue's third figure, 4, could not be re-measured, because the issue body could not be
read and nothing in the repo says what it counted. It is not used anywhere below.

---

## The thing the issue could not know: `tests/test_error_messages.py`

`tests/test_error_messages.py` landed on `master` after #70 was filed, in PR #81. Measured
with `^    (Site|unreachable)\(` and `^    unreachable\(` over that file: **106 rows, 50 of
them marked `NO_REQUEST_REACHES_IT`, 56 driven.** `test_every_four_hundred_raise_site_is_declared`
holds it to a two-way set equality against an `ast` walk of the package's raise sites, keyed
`(module file name, enclosing def name, message skeleton)`, so an undeclared raise reds and
names the key, and a stale row reds and names the key.

The brief asks whether an assertion could pin **the declared table key** rather than a
substring. It is the right question: it would anchor by construction, it would tie every test
to one source of truth, and it is the `_API_ROUTES` shape #51 established. **The answer is
no, and the blocker is coverage, measured.**

`four_hundred_raise_sites()` admits a raise only when `four_hundred_status(klass)` is not
`None`, which walks the raised class's MRO through `web.ERROR_STATUS` and keeps the result
only when `400 <= status < 500`. So:

* **`TypeError` and `ValueError` are not in `web.ERROR_STATUS` and have no mapped base**, so
  no raise of either is in the table. Measured with `^\s*raise ` over
  `src/splitwise_lite/`: **245 raise statements**. Measured with
  `^\s*raise (TypeError|ValueError)`: **78 of them**.
* **`balances.InvalidLedger` is not in the table either.** Read at
  `src/splitwise_lite/balances.py:106`, it is `class InvalidLedger(DomainError)`, and
  `class DomainError(Exception)` at `src/splitwise_lite/money.py:65` is not a key of
  `ERROR_STATUS`. Same for `groups.GroupSetupError` and `groups.InvalidGroupDefinition`
  (`src/splitwise_lite/groups.py:139` and `:147`). Same for `web._RouteNotDeclared`, which
  `tests/test_web_api.py:2255` raises and then asserts nine fragments about.
* **The scar that produced this whole rule is outside the table.** `.claude/rules/testing.md`
  rule 1 and `unanchored_pin_message` both quote `money.py:148`, `Money currency must be a
  Currency, ...`. That is a `TypeError`. The one message the anchoring rule exists because of
  is a message the table cannot see.
* **The assertions that most need anchoring are the ones the table cannot see.** Measured
  with `raises\(\s*TypeError` over `tests/*.py`: **105 lines**, 10 of them inside
  `tests/test_suite_integrity.py`'s synthetic constants, so **95 real ones**.

Two further costs, both real but neither decisive on its own:

* **Import weight.** `tests/test_error_messages.py` imports `splitwise_lite.web`, and
  therefore Flask. Making `tests/test_money.py`, `tests/test_split.py` and
  `tests/test_balances.py` depend on it would put the web layer in the import graph of every
  domain test. Nothing goes red if that happens: the Flask-absence check at
  `tests/test_web_api.py:119` to `:127` spawns a fresh interpreter and asserts about
  `import splitwise_lite`, not about `tests/`. So this is a design cost, not a blocker, and
  it is recorded as a cost and not claimed as more.
* **#82.** Fifty of the 106 rows are `NO_REQUEST_REACHES_IT`, a claim the module records and
  does not verify, and #82 is open on exactly those fifty. Hanging a second load-bearing
  guarantee off the table before #82 has settled what those rows are worth would couple two
  open questions. **This task does not absorb #82 and does not touch
  `tests/test_error_messages.py`.** Where the two touch: an audit slice that deletes a guard
  in `store.py` or `groups.py` will be deleting a guard whose row in that table is one of the
  fifty, and the deletion run is direct evidence about reachability. A slice that learns
  something about a row's reachability claim **records it in its own mutation record and
  comments on #82**; it does not edit the table.

**What would make the table the right answer later**, recorded so nobody re-derives it:
`four_hundred_raise_sites()` becomes an every-raise-site walk by deleting one filter. Widening
it from 4xx to every raise in the package, and rekeying it so a test can name a key, is a
coherent future task. It is a rewrite of #61's module and its stated scope, and #82 is open
against it. Not this task.

---

## The mechanism decision

**Chosen: a check, in `tests/test_suite_integrity.py`, plus a rule amendment, plus a carried
baseline that only shrinks.** The argument, and specifically the argument against the shape
the issue proposes.

### The asymmetry is real and is itself the family defect

`.claude/rules/testing.md` opens its seven rules with **"Message pins are anchored"**, spells
the anchored form as `match=r"^currency must be a Currency"`, and says
`tests/test_suite_integrity.py` refuses an unanchored one. A reader finishes that rule
believing the repo has this covered. Measured: the mechanism reads **16** pins, against a
substring-assertion population of **at least 100** direct-form lines plus everything asserted
through the 27 bound locals. A document claiming coverage it does not have is the same defect
as a check reporting success without exercising what it names, one level up, and it belongs
in the same module as the other three.

### But the `^` remedy does not port, and this is the load-bearing correction

The issue's framing, "the same superstring defect as the `match=` pins", is **right about the
defect and wrong about the unit**. `"x" in str(exc.value)` is exactly the operation
`match="x"` performs for a pattern with no metacharacters, so the PR #62 collision applies
unchanged. But the fix that worked there cannot be applied assertion by assertion:

* **A block routinely asserts several fragments about one message.**
  `tests/test_store.py:2983` and `:2984` assert `"u1"` and `"u2"`; `:762` and `:763` assert
  `"AUD"` and `"NZD"`; `tests/test_web_api.py:2258` to `:2265` assert nine. At most one
  fragment can be at the start of a message, so "put `^` on each" is unsatisfiable.
* **17 of them are negative** (`assert ALI not in str(raised.value)` at
  `tests/test_split.py:264`; `assert "750" not in message` at `:323`). Anchoring is
  meaningless for a negative, and its defect is the mirror image and worse: a negative
  substring assertion is satisfied by **any** message lacking the string, including one from
  an entirely different guard, so it is weaker than a positive one rather than stronger.
* **Some left operands are not literals at all**: `assert str(MAX_CENTS) in str(caught.value)`
  (`tests/test_store.py:669`), `assert TOKEN_HASH in str(caught.value)` (`:2779`),
  `assert format_amount(Money(750, AUD)) in message` (`tests/test_split.py:321`). A textual
  rule cannot read them.

So the unit is the **`pytest.raises` block**, not the assertion. Once one anchor in a block
has established **which guard raised**, every fragment assertion in that block stops being a
pin and becomes documentation, and none of them needs to change. That reframing is what makes
the job finite and is the single most important sentence in this document.

### The delta this buys is unusually small

The existing `test_every_message_pin_is_anchored_or_says_why` already guarantees: *any
`match=` that exists is anchored or carries a reason.* The new check's only job is the
converse: *a `match=` (or an equivalent whole-message comparison) exists wherever a block
reads the message.* Two checks, one guarantee each, neither restating the other. That is what
"fits the file rather than fighting it" means here, and it is why this is a section in
`tests/test_suite_integrity.py` rather than a new module.

### Why not the other two answers

* **A rule alone.** That is the option #67's own reasoning already refuses for its sibling:
  "a rule lasts exactly as long as the next author who has not read it", which is the failure
  mode `plans/tasks/46-shell-precache-digest.md` records for `VERSION`. The current rule is
  the proof: it has been in force since #65 and the count went from 94 to 100.
* **No mechanism, audit only.** Legitimate if argued, and it is argued away by the same
  measurement: an audit fixes the 100 that exist and nothing stops the 101st. #51's precedent
  is the standing answer in this repo, and #69's is that the rarer form already got rule plus
  mechanism plus audit. Giving the commoner form less would leave the asymmetry pointing the
  other way.

---

## One task or several

**Several. One mechanism task and seven audit slices.** The judgement, and the seam.

### Why the issue's own scoping over-counts the work

The issue asks for a guard deletion per assertion. `plans/mutations/65-message-pins.md` is the
counter-example: **seven guard deletions covered all thirteen pins**, because one guard backs
several assertions (`g7-repeated-id` alone covers six). The unit of audit work is a **guard**,
not an assertion. The measured bound: 245 raise statements exist in `src/splitwise_lite/`, and
the assertions do not reach all of them. At #65's observed ratio of 13 pins to 7 guards the
100-plus assertions sit behind roughly 50 guards, and `tests/test_store.py`'s clustering (the
literal `"ghost"` asserted at `:921`, `:1075`, `:1157`, `:1235`, `:2844`, `:2921`, `:2962` and
`:2970`, eight lines against existence checks) suggests better than that. How many guards
those eight actually sit behind is not known here and is the first thing slice 70g measures. So the real
number is smaller than 94 and larger than #65's seven, by several times. That is still a
task-sized amount of work several times over.

### Why the mechanism cannot land with the conversions, and why a conversion cannot be split from its audit

Two constraints pull against each other, and the seam is where they meet.

1. **A conversion cannot precede its audit.** `plans/mutations/65-message-pins.md` states the
   discipline: "The message quoted in each section is what the guard really prints, captured
   from a run against the unmutated tree, and it is what each anchored pattern was derived
   from." An anchor written from reading the guard is the thing PR #62 proved settles nothing.
   So converting a block and auditing it are **one act**, and no slice may do one without the
   other.
2. **The mechanism cannot wait for all seven slices.** Landing the check last means the count
   keeps growing while the work is in flight, which is what it did between the issue and this
   document.

The seam is therefore: **land the check first, refusing everything new and carrying
everything old in a declared baseline, then retire the baseline module by module.**

### Is the baseline just an allowlist, which "is how a check stops being one"?

That objection is `tests/test_suite_integrity.py`'s own words about the duplicate-definition
check, a reviewer will quote it, and it deserves a straight answer. The duplicate check has no
exemption because a duplicate definition is always a bug **and there were zero to carry**.
Here there are 100-plus, and the only ways to land a check with no exemption are to fix them
all in one merge (unauditable at that size) or to convert them unaudited (the worse defect).
Four properties distinguish the baseline from an allowlist, and all four are checkable:

* It is checked in **both directions**. A carried entry that is no longer unanchored is a
  failure naming it, so the baseline cannot outlive its subject.
* Its entries carry **counts**, not just names, so anchoring one of two blocks in a test
  function moves the count and reds.
* Its total is a **single declared integer**, so growing it is a one-line diff a reviewer
  cannot miss.
* Each module's entry carries a **reason naming the slice that will retire it**, under the
  same character floor `MINIMUM_REASON` already puts under `# unanchored:`.

**Stated exactly, and not claimed as more:** a determined author can still legalise a new
unanchored block by editing three places, and that costs a placement plus a bump to a visible
integer, not a written justification per block. That is weaker than `# unanchored:` demands
and stronger than a bare allowlist, and it is temporary by construction, because the last
slice deletes it. Do not describe it as the equal of the `# unanchored:` hatch;
`test_suite_integrity.py`'s note on the `>` exemption is the precedent for saying so plainly.

### What 70a delivers on its own

* The suite can no longer gain a new unanchored message assertion silently.
* The population becomes a number the suite computes and prints, so nobody derives it by grep
  again. That is the #61 scar: the same premise re-derived by hand four times produced four
  answers, two, three, six and twelve.
* `.claude/rules/testing.md` stops claiming coverage it does not have.

**What 70a explicitly does not do: it makes no existing assertion able to fail.** Every one of
the 100-plus is exactly as loose after 70a as before. Anybody reading 70a's merge as closing
#70 has misread it.

### The slices, sized

Ordered smallest first, so the record format is proven at #65's size before it is asked to
hold the largest module. Direct and bound figures are from the per-module table above.

| Slice | Test module(s) | Source module(s) | direct | bound |
| --- | --- | --- | --- | --- |
| 70b | `tests/test_money.py`, `tests/test_simplify.py`, `tests/test_split.py` | `money.py`, `simplify.py`, `split.py` | 11 | 8 |
| 70c | `tests/test_balances.py` | `balances.py` | 7 | 2 |
| 70d | `tests/test_web_api.py` | `web.py` | 12 | 5 |
| 70e | `tests/test_groups.py` | `groups.py` | 19 | 8 |
| 70f | `tests/test_web_shell.py`, `tests/test_suite_integrity.py` | the test suite's own helpers | 0 | 3 |
| 70g | `tests/test_store.py`, first half | `store.py` | part of 51 | part of 1 |
| 70h | `tests/test_store.py`, second half | `store.py` | part of 51 | part of 1 |

70f is its own slice because its guards are not in `src/` at all: `tests/test_web_shell.py:1068`
raises out of `shell_digest` and `:1235` out of `omissions_carry_their_reasons`, and
`tests/test_suite_integrity.py:342` out of `duplicate_definitions`. The mutation targets a file
under `tests/`, which the record format already permits, and the audit is otherwise identical.

70g and 70h split `tests/test_store.py` because 51 direct-form lines is over half the
population in one module. The split point is decided by the engineer from the block census the
check prints, not from this table, and each half must be independently green.

---

## The record format at this size

`plans/mutations/65-message-pins.md` is the precedent: seven sections, each a JSON block plus
the message the guard really prints, plus what the run printed with the guard deleted, plus
the pins the guard covers, plus a verdict. **The format holds. Two things about it do not hold
at 50 guards, and both are the failure the brief describes, a correct number attached to the
wrong subject.**

1. **The cross-section ordinal numbering must go.** #65 numbers its pins 1 to 13 across
   sections, so an entry reads `- 10. the same test, settlement_states block, pattern "s1"`.
   The number is bound to its subject only by position in a list that lives in a different
   section from the guard it describes. At 13 that is survivable. At 100 it is a defect
   generator. **Replacement:** every entry names the **pytest node id** and the anchored
   pattern it produced, on the same line. A node id is unique, is already the vocabulary of
   `kills` and `survives`, and carries its own subject.
2. **Nothing ties the prose to the JSON.** `mutation_record_problems` type-checks `kills` and
   `survives` and never reads the "Pins this guard covers" list beside them, so a wrong entry
   there is invisible to the suite. **Replacement:** the covered node ids live in `kills`,
   which the suite already checks, and **criterion 13** below makes any node id appearing in
   a record's prose have to appear in that record's `kills` or `survives`.

One further change, which is scale and not correctness: **one record file per slice**, not one
per issue. `plans/mutations/README.md` already sanctions "one file per task or issue". Seven
files of roughly seven records each is exactly the size #65 proved.

`REQUIRED_KEYS` is an exact set and `mutation_record_problems` refuses extras, so **no new JSON
key is added.** Everything above fits the seven keys that exist.

---

## Goal

Every `pytest.raises` block in the suite that reads the exception's message establishes which
guard raised it, so that no assertion about a message can be satisfied by a different
exception's message unnoticed; and the mechanism that guarantees this covers the common `in`
form as well as the rare `match=` form, so `.claude/rules/testing.md` stops claiming more than
the repo has.

70a on its own reaches half of that: nothing new can be written loose, the existing loose
blocks are enumerated by the suite rather than by anybody's grep, and the rules file is
accurate. The other half is 70b to 70h, which make each existing block able to fail, one
audited guard at a time.

---

## Acceptance criteria

### 70a: where the check lives

1. `tests/test_suite_integrity.py` gains one new section, headed the way its three existing
   sections are, for #70. **No new test module is created.**
2. That module's imports do not grow beyond the standard library and `pytest`. Its module
   docstring's existing claim, that nothing from `splitwise_lite` is imported "so these checks
   still run on a checkout where the package will not import", is still true after this task.
3. The new code reuses `parsed`, `read`, `posix`, `callee_name`, `marked_lines`, `MARKER`,
   `MINIMUM_REASON` and `TEST_SOURCES`. **No second escape hatch is introduced**: the
   deliberate-exception marker is `# unanchored:`, unchanged, at the same floor.
4. Every file is read through `read()`, so a CRLF checkout and an LF checkout yield the same
   findings and the same line numbers, and both CI legs agree.

### 70a: what the check sees

5. A new `message_blocks(source, where)` returns one entry per **candidate block**: a `with`
   statement one of whose items is a call whose `callee_name` is `raises`, which binds a name
   with `as`, and whose body **reads that name's message**.
6. "Reads the message" is exactly two shapes, and the criterion states both because the second
   is 27 lines of the population and a walk that misses it misses a quarter of the job:
   (a) a call to `str` whose single argument is `NAME.value`; (b) a load of a local that an
   assignment **in the same block** bound to such a call.
7. One level of local binding, not two, and not across a function boundary. A comment records
   the shapes therefore **not** seen, with the occurrence count each has on the branch, in the
   manner `message_pins`' docstring already lists its exclusions. Measured at `bea0da7` with
   `\.value\.args|repr\([A-Za-z_]+\.value\)|\{[A-Za-z_]+\.value\}` over `tests/*.py`: **zero
   matches for all three.** The comment states that number and states that a future occurrence
   of any of them is invisible to this check.
8. A `with pytest.raises(X):` that binds no name is **not** a candidate, and neither is a block
   that binds a name and never reads its message. A block that asserts nothing about a message
   has nothing to anchor.
9. A `match=` keyword on a call that is not `raises` or `warns` is not a candidate, for the same
   reason `NOT_A_PIN_OTHER_CALL` exists.

### 70a: what counts as anchored

10. A candidate block is **anchored** if any one of these holds, and the accepted set is exactly
    these four:
    a. the `raises` call carries a `match=` keyword. This check does **not** re-decide whether
       that pattern starts with `^`, because `test_every_message_pin_is_anchored_or_says_why`
       already guarantees it. Neither check restates the other's guarantee.
    b. the block body holds a comparison with `==` where one side is the message expression of
       criterion 6. An equality has no superstring defect at all, so it needs no literal and
       works for a message computed from a parametrised case.
    c. the block body calls `.startswith` on that message expression.
    d. some physical line of the `with` statement carries `# unanchored:` with a reason of at
       least `MINIMUM_REASON` characters.
11. Anything else is a finding. `unanchored_message_blocks(source, where)` returns the findings,
    each carrying the block's first and last line numbers and the enclosing definition's name,
    taken as `stack[-1] if stack else "<module>"` in the manner `four_hundred_raise_sites` uses.

### 70a: what a failure says

12. A message helper, tested by its own test in the shape of
    `test_the_unanchored_pin_message_says_what_happened`, produces the failure text. That test
    asserts each of these elements is present, given a synthetic path, line and name:
    * the POSIX path and the line number, and the name the block binds;
    * that `in` is the same operation `re.search` performs for a pattern with no
      metacharacters, so the PR #62 collision applies to it unchanged;
    * that the anchor goes on the **block** and not on each assertion, **and why**: a block
      routinely asserts several fragments and at most one can start the message;
    * that a negative assertion is weaker still, because any message lacking the string
      satisfies it;
    * all four accepted anchors of criterion 10, spelled;
    * the marker and its floor.
13. The mutation-record checks gain one criterion, and it lands in 70a rather than after the
    first audit because it is the seven audit records that need it: **every pytest node id
    appearing anywhere in a record's prose also appears in that record's `kills` or
    `survives`.** A node id is recognised by containing `::`. `REQUIRED_KEYS` does not change
    and no new JSON key is added. The check has its own positive control: a synthetic record
    whose prose names a node id absent from both lists is a finding, and one whose prose names
    only ids that are present is not.

### 70a: the carried baseline

14. `CARRIED_UNANCHORED_BLOCKS` maps a POSIX test-module path to two things: a frozenset of
    `(enclosing definition name, number of unanchored candidate blocks in it)` pairs, and one
    reason of at least `MINIMUM_REASON` characters **naming the slice that will retire it**
    (70b to 70h).
15. The key is a name and a count, never a line number and never an ordinal. Line numbers churn
    on every edit above them and would make the baseline a merge-conflict generator; an ordinal
    is the positional binding this document refuses for the mutation records. A count moves when
    one of two blocks in a function is anchored, which is the case a name alone would miss.
16. `test_every_message_block_is_anchored_or_carried` is parametrised over `TEST_SOURCES` with
    `ids=SOURCE_IDS`, exactly as the two existing parametrised checks are, and asserts **set
    equality** per module between what the walk finds and what the baseline carries. Both
    directions fail with the offending entries named: an unanchored block that is not carried,
    and a carried entry that is no longer unanchored.
17. `CARRIED_TOTAL` is a declared integer asserted equal to the sum of the counts, so growing
    the baseline is a one-line diff in a place a reviewer reads.
18. **The failure prints the exact literal to paste back.** When the walk and the baseline
    disagree, the failure text ends with the `CARRIED_UNANCHORED_BLOCKS` entry and the
    `CARRIED_TOTAL` line as they should now read, following `stale_digest_message` in
    `tests/test_web_shell.py`, which the repo already treats as the way a computed constant is
    maintained. **No number in the shipped code or in this document's descendants is a hand
    count.**
19. The PR body states `CARRIED_TOTAL` as the check computed it, and states that it is the first
    machine-produced count of this population.

### 70a: proof that the check can fail

20. `test_the_message_block_check_still_bites` is written in the shape of
    `test_the_pin_check_still_bites`: synthetic source strings, one per shape, each labelled.
    The shapes it must cover, at minimum:
    a. a bare `assert "x" in str(raised.value)` block is flagged;
    b. the same block with `match=r"^..."` on the `raises` call is accepted;
    c. the same block with `assert str(raised.value) == "..."` is accepted;
    d. the same block with `assert str(raised.value).startswith("...")` is accepted;
    e. the bound form, `message = str(raised.value)` then `assert "x" in message`, is flagged;
    f. the marker with a reason over `MINIMUM_REASON` characters is accepted, and with an empty
       or too-short reason is flagged;
    g. the marker may sit on the last line of a `raises` call wrapped over several lines;
    h. a `with pytest.raises(X):` with no `as` is not a candidate;
    i. a block that binds `as` and never reads the message is not a candidate;
    j. a block holding only a **negative** assertion, `assert X not in str(raised.value)`, is
       still a candidate and is still flagged, because reading the message is what makes it one;
    k. a block with several fragment assertions and one anchor is accepted **once**, and reports
       no finding per unanchored fragment.
21. Every accepted case in criterion 20 is one that goes red if the branch that accepts it is
    removed, and the test says which assertion is the positive control for which branch. A case
    that holds **by construction** under any mutation of the implementation is labelled as such
    in a comment saying what it does guard against, exactly as the `NOT_A_PIN_RE_MATCH` comment
    does. **A section of self-tests that cannot fail is the defect this module exists to
    refuse.**
22. `plans/mutations/70a-message-block-check.md` records at least two mutations, in the format of
    `plans/mutations/65-message-pins.md` as amended by criteria 13 and by "The record format at
    this size":
    a. one that deletes a branch of criterion 10's accepted set and names the self-test that
       reds;
    b. one that anchors a **real** carried block in `tests/` without updating the baseline, and
       names the stale-direction failure that reds and the entry it names. This is the proof
       that the second direction of criterion 16 is not decorative.
    Each has a named surviving control.

### 70a: the rules file

23. `.claude/rules/testing.md` keeps `THE_THREE_BULLETS` **verbatim**, so
    `test_the_testing_rules_keep_the_three_they_had` stays green untouched.
24. Rule 1, "Message pins are anchored", keeps its PR #62 scar verbatim and gains: that the `in`
    form is the same defect; that the anchor goes on the block; the four accepted anchors; the
    new check's name; and the carried baseline with the statement that it may only shrink and
    that the last slice deletes it.
25. **The amendment is a correction, not an edit-away.** The reading being retired, that
    anchoring `match=` is the whole of this rule, is quoted in place in this repo's dated
    correction-note form rather than deleted, with the measurement that retires it: 16 pins
    against at least 100 substring assertions.
26. `ENFORCING_MECHANISMS` in `tests/test_suite_integrity.py` gains the literals that name the
    new mechanism, so `test_the_testing_rules_name_the_mechanisms_that_enforce_them` covers it
    and a later rename of the check reds rather than leaving the rule naming something gone.
27. `CLAUDE.md` and `README.md` do not change. This task adds no capability, retires none, and
    creates no directory, so neither document's claim list moves and neither the literal in
    `tests/test_web_shell.py` nor the parity between the two documents is touched.

### 70b to 70h: the shared criteria for every audit slice

Each of these applies **to each slice**, and a slice is not done until all of them hold for it.

28. The slice names its test module or modules and its source module or modules, matching one
    row of the slice table, and touches no test module outside that row.
29. For **each** carried block the slice retires: the guard the block exists to pin is deleted,
    the block's node id is run **alone** with `PYTHONDONTWRITEBYTECODE=1`, the result is
    observed, and the tree is reverted with `git checkout -- <file>` before the next deletion.
    `plans/mutations/README.md`'s recipe is followed as written, including the assertion that
    the anchor matches **exactly once**.
30. Where deleting a guard reds an **earlier** block first and masks the one under audit, the
    masked block is audited by calling the function directly under the same deletion, and the
    record says so and says what the direct call raised. `g3-not-a-ledger-event` in
    `plans/mutations/65-message-pins.md` is the worked precedent, and at this scale it will
    recur often.
31. The anchor written for a block is derived from the message **captured from a run against
    the unmutated tree**, never from reading the guard's source. The record quotes that captured
    message. This is #65's discipline and PR #62 is the proof that reading settles nothing.
32. A guard whose deletion changes nothing is a **finding, not a failure**, and #65's resolution
    ladder governs it. That ladder is referenced, not restated here, so there is one copy of it.
33. `plans/mutations/70x-<slice>.md` exists, one `##` section per guard deleted, each carrying a
    JSON block with the seven required keys, whose `kills` lists **every** node id that guard
    covers. No entry is numbered by position; every entry names its node id. Criterion 13's
    check is green over the file.
34. The slice removes its module's entry from `CARRIED_UNANCHORED_BLOCKS` and lowers
    `CARRIED_TOTAL` by exactly the number of blocks it retired. Both numbers come from the
    check's own printed literal, not from a count.
35. **No test is deleted, renamed to something that claims less, loosened, or marked `skip` or
    `xfail`.** Fragment assertions are kept as they are; the slice adds an anchor beside them.
36. Nothing under `src/` ends the slice changed. Every guard deleted during the audit is
    restored, and `git diff --stat` shows no path under `src/`, `app/` or `scripts/`.
37. A slice that learns something about an `NO_REQUEST_REACHES_IT` row's reachability claim in
    `tests/test_error_messages.py` records it in its own mutation record and comments on **#82**.
    It does not edit that table.
38. **70h, whichever slice runs last, deletes `CARRIED_UNANCHORED_BLOCKS`, `CARRIED_TOTAL` and
    the carried direction of criterion 16**, leaving the check with `# unanchored:` as its only
    exemption. The final PR states that the baseline is gone.

### Verification, for every PR in this family

39. The modules a branch touches are run in full by name. The rest of the suite is run in
    chunks by module and the PR states the chunk boundaries and the summed counts. Collection
    counts come from `uv run python -m pytest --collect-only -q`. The command is
    `uv run python -m pytest`, never `uv run pytest`.
40. The whole-suite gate is CI, not a local run: `.github/workflows/tests.yml` runs both legs
    and both must be green, and a PR whose base has moved is brought up to date and re-run.
41. **No criterion in this task requires a browser.** The whole population is Python source read
    by `ast`, and the audits are pytest runs. Nothing here routes to issue **#80**, and no
    verdict in this family may rest on an unrun manual check.

---

## Out of scope

* **Rewording any message under `src/`.** That was #61. This task is test-side, and criterion
  36 makes it enforceable.
* **HTTP response-body message assertions.** Measured with `\["error"\]\["message"\]` and
  `\["error"\]\["code"\]` over `tests/*.py`: **131 lines, 128 of them in
  `tests/test_web_api.py`.** They are out for a reason, not by omission: the identity of an
  HTTP refusal is carried by `body["error"]["code"]`, which `web.ERROR_CODE` makes a contract
  and which those tests already assert, so the message assertion beside it is not the thing
  establishing which guard fired. If that ever stops being true it is a new issue.
* **CLI stderr assertions** in `tests/test_setup_group_cli.py` and `tests/test_dev_server.py`
  (measured: 2 lines matching `raises\(\s*SystemExit`). Same reasoning: the exit status carries
  the identity.
* **The JavaScript half.** `tests/shell_harness.mjs` has no `pytest.raises` and is not scanned.
* **`excinfo.match(`.** Measured: zero occurrences. The existing pin check does not see it
  either, which is #69's residual and stays #69's.
* **Widening `tests/test_error_messages.py`'s table beyond 4xx**, rekeying it, or making any
  test pin a table key. Argued against above, and recorded there so it is not re-proposed
  blind.
* **Issue #82** and the fifty `NO_REQUEST_REACHES_IT` rows. Criterion 37 is the whole of the
  contact between the two.
* **A mutation runner, or any new file under `scripts/`.** `plans/mutations/README.md` already
  refuses one and `test_scripts_holds_exactly_the_promised_python_files` pins that directory.
* **Any change under `app/`**, and therefore `SHELL_DIGEST` in `app/sw.js` must not move.
* **Deleting or loosening any test**, in any slice, for any reason.

---

## Constraints

* **Files 70a may touch, and no others in either direction:** `tests/test_suite_integrity.py`,
  `.claude/rules/testing.md`, `plans/mutations/70a-message-block-check.md`, and this file.
* **Files an audit slice may touch:** the test modules in its row of the slice table, its own
  `plans/mutations/70x-*.md`, and the baseline constants in `tests/test_suite_integrity.py`.
  Nothing else.
* `tests/test_suite_integrity.py` imports the standard library and `pytest` only, and nothing
  from `splitwise_lite`. This is why the mechanism does not live near
  `tests/test_error_messages.py`, which imports Flask.
* One hatch, not two: `# unanchored:` at `MINIMUM_REASON`, reused. Do not add a second marker,
  a per-file skip, or a decorator.
* The two checks in this family state one guarantee each and neither restates the other's.
  `test_every_message_pin_is_anchored_or_says_why` owns "any `match=` is anchored";
  the new check owns "a `match=` exists where a message is read".
* Every mutation run sets `PYTHONDONTWRITEBYTECODE=1`, per `.claude/rules/testing.md`. Every
  mutation is recorded as an anchor and a replacement, never as a sentence.
* No number in the shipped code is a hand count. Criterion 18 makes the check print the literal
  to paste back, and that is the only sanctioned way the baseline is maintained.
* No record entry is numbered by position. Every claim names its pytest node id.
* Test runs are chunked by module; the full suite is CI's job.
* `uv run python -m pytest`, never `uv run pytest`.

---

## Size

70a is one module section, one rules amendment, one record file and one new check on the
mutation records. It is comparable to the #65 half of
`plans/tasks/60-65-67-checks-that-could-not-fail.md`.

The seven audit slices together are the larger half of the work by a wide margin. At #65's
measured ratio of seven guard deletions to thirteen pins, the 100-plus assertions sit behind
roughly fifty guards, each needing a mutation, a solo run, a revert, a captured message, an
anchor derived from it and a record. **That is the honest size of #70, and no part of this
document should be read as reducing it.**

---

## What this document claims about #70 itself

Recorded so a reader can check it against the issue body, which the author of this document
could not read:

1. The defect claim is **right**: `"x" in str(exc.value)` is the same operation
   `match="x"` performs, and PR #62's collision applies to it unchanged.
2. The remedy, if it is "anchor each assertion", is **wrong**, for the three measured reasons
   in "The mechanism decision": multi-fragment blocks, 17 negative assertions, and non-literal
   left operands. The anchor belongs to the block.
3. The audit scoping, if it is "one guard deletion per assertion", **over-counts**, by the
   assertion-to-guard ratio that `plans/mutations/65-message-pins.md` measured at 13 to 7.
4. The counts have **moved**, 14 to 16 and 94 to at least 100, and would have kept moving. A
   spec that hardcodes them is wrong on the day it is read.
5. The complaint about `.claude/rules/testing.md` is **correct**, and is itself an instance of
   the family the rules file is about: a document reporting coverage it does not have.
