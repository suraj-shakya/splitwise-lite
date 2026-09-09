# Issue #78: `split_by_weight` is a resolver capability with no product behind it

**Status:** the fork below is undecided. Nobody implements either branch until it is
decided. This document exists to make the decision cheap and to stop the question being
re-asked a fifth time.

> **Decided 2026-09-09: Branch A, remove.** The Status paragraph above is retracted. It
> read "the fork below is undecided. Nobody implements either branch until it is
> decided", and it was true when it was written and false from the moment the fork was
> answered. The fork was put to the user explicitly, with both branches and their costs
> as written below; the user chose **Branch A, remove**, on the pm's recommendation. It
> was implemented on PR #98, which closes issue #78.
>
> **This note exists because the alternative was a PR body.** Eight dated correction
> notes across seven documents point their readers at this file, so this file is the
> provenance record the whole change rests on, and section 4's closing bullet is explicit
> that "**The decision is recorded in the repository, not in a PR body**". A reader who
> arrives here from one of those notes must not be told the question is still open.
> `plans/spec.md`'s modelling notes carry the **reason**, which is the thing a reader of
> the product spec needs; this file carries the fact that a costed fork existed and which
> way it went, which is the thing a reader of the history needs.
>
> **Branch B is the road not taken.** Its criteria B1 to B15 are left standing, unedited,
> because they are the record of what was weighed and deleting them would leave the
> decision looking uncontested. None of them is a live requirement, none was implemented,
> and none is to be picked up from this file without a new decision. Section 4, "What is
> true either way", still describes both branches as live and is left standing for the
> same reason; every one of its bullets was in fact honoured by Branch A.
>
> The Status paragraph's own last clause is the one thing in it that still holds: this
> document existed to stop the question being re-asked a fifth time, and the answer now
> lives in three places a reader might start from, which are `plans/spec.md`,
> `plans/backlog.md` task 3 and this note.

**Measured on:** worktree at `master` `543bd0e`, 2026-09-09. Every count in this file was
taken with Read, Grep and Glob against that tree. Nothing here is repeated from the issue
without being re-measured, and where the issue and the tree disagree, the tree is quoted
and the disagreement is named.

---

## What the issue already established, so nobody re-reads it

Three things, all of which re-measure as true:

1. **`plans/spec.md` requires three split rules and no more.** Line 20 of the locked
   decisions table reads `| Split rules | Equal, equal across a subset, and uneven shares |`,
   and line 88, under "Version one, Ship", reads `* All three split modes`. Those are the
   only two places `plans/spec.md` mentions split rules at all.
2. **`split_equally` and `split_exact` cover all three.** `split_equally`'s own docstring
   at `src/splitwise_lite/split.py:80-82` says it "covers two of the three modes: pass
   every member for 'equal across all', or the chosen few for 'equal across a subset'".
   `split_exact` covers "uneven shares", and is what the add screen's `Uneven amounts`
   control sends.
3. **No screen can emit `mode: 'weight'`.** `addSplit()` at `app/app.js:964-994` has
   exactly two return statements, `{ mode: 'exact', amounts: amounts }` and
   `{ mode: 'equal', member_ids: memberIds }`. `app/index.html:179-187` offers three radio
   controls and none of them is a weight. The string `weight` does not occur in
   `app/app.js` at all, and `tests/test_add_screen.py:528-533` enforces that absence with
   `assert "weight" not in app_js()`.

One further claim of the issue's, re-measured and true: **exact mode cannot reach
`split.py::_ordered_from_mapping`'s negative guard.** `money.parse_amount`'s docstring at
`src/splitwise_lite/money.py:222-223` lists "Signs" among what it rejects on purpose, and
`web.py::_require_exact_amount` at `web.py:1612-1622` puts every exact share through
`parse_amount` before `split_exact` sees it. Weight mode is the only route by which an
HTTP request reaches `split.py:377-384`.

---

## 1. Recommendation: remove it

### The argument

**The fourth mode is drift, and its provenance is on disk.** `plans/spec.md:20` locks
three rules. `plans/backlog.md:39`, task 3, widens one of them without saying so: "Given a
total and a mode (equal across all, equal across a subset, or uneven by weight or exact
amount)". `plans/tasks/03-split-resolver.md:20-25` then turns that widening into a
four-row table and 19 further mentions, and `src/splitwise_lite/split.py:8-13` maps "the
three modes the backlog names" onto four functions. Nothing in `plans/spec.md` ratified
the fourth. That is not a taste judgement: it is a chain of four files in which the count
goes 3, 3-and-a-half, 4, 4, with no decision recorded anywhere in between.

**The product argument against it is already written down twice, and it is an argument
against the capability rather than against one screen.** `app/index.html:176-178` says
"There is no weight mode: it stays reachable through the API and unexposed here, because a
weight typo produces a wrong but valid split where a wrong exact share is refused with
both figures named." `plans/tasks/10-expense-entry-screen.md:94-99` says the same thing at
greater length. Neither reason is specific to the entry screen. `plans/spec.md:29-33`
names the product's largest risk as a ledger that "looks authoritative while being wrong",
and a split mode whose only failure mode is silent wrongness is the shape of that risk. A
reason that argues nobody should be given a control is not a reason to leave the control
wired to the API and unlabelled.

**"A published wire mode" overstates what exists.** Measured: there is no `CHANGELOG.md`,
no `docs/` directory and no OpenAPI or schema document anywhere in the tree. A Glob for
`**/*.{yaml,yml,json,toml}` returns five files, and they are `.claude/settings.json`,
`.github/workflows/tests.yml`, `app/manifest.json`, `group.example.toml` and
`pyproject.toml`, none of which describes the API. `/api` carries no version segment and
no version negotiation. The wire contract is written in exactly two places,
`plans/tasks/09a-application-server-and-http-api.md:432-437` and a comment at
`app/api.js:393-394`, and both are in this repo. `app/api.js` is the only file under
`app/` permitted to call the back end, enforced by
`test_only_the_api_client_calls_the_back_end`. So the population of callers is, by
measurement rather than by assumption, one client in this repository. Removal is a rename
inside a single-client system, not a breaking change to a public API.

**Keeping it costs live test surface that nothing in the product pays for.** Weight mode
is currently the only way an HTTP request reaches two 4xx raise sites in `split.py`
(`_allocate`'s weights-sum-to-zero guard and `_ordered_from_mapping`'s negative guard), so
two rows of `FOUR_HUNDRED_SITES` are driven, and stay driven, by a mode nobody sends. It is
also 32 lines of resolver, 25 lines of HTTP layer, 11 test functions, 8 parametrisation
sites and roughly 87 occurrences across thirteen planning documents, all maintained
against no user.

### The honest cost of removing, stated before the decision is taken

Two things get worse, and a reader deciding this fork should see them:

1. **`_allocate`'s largest-remainder ordering stops being exercised through any public
   surface.** With `split_by_weight` gone, `_allocate`'s only caller is `split_equally`,
   which passes `[1] * len(ordered)` (`split.py:113`). Every weight then being 1,
   `divmod(total_cents * 1, n)` yields an identical remainder for every member, so the
   `-remainders[index]` component of the sort key at `split.py:223-226` never
   discriminates and only the rotation tie-break decides anything. The proportional half
   of the remainder rule, which `plans/spec.md:65-69` singles out as the thing the whole
   collapse-to-one-shape decision exists to get right, would have no test driving it.
   Branch A's criteria below require this to be answered rather than absorbed.
2. **The end-to-end smoke test loses one of its three modes.** `tests/test_end_to_end.py:176`
   enters expense E2 through weight mode, and
   `plans/tasks/18-end-to-end-smoke-test.md:524` requires "Exactly three expenses are
   entered, one per wire mode, in the order `equal`, `weight`, `exact`". This is
   recoverable at zero arithmetic cost, see the blast radius below, but it is a committed
   criterion that stops being satisfiable.

Neither outweighs the argument, but both belong in front of whoever decides.

---

## 2. The blast radius of removal, measured

A Grep for `weight|Weight|WEIGHT` across the worktree returns **260 occurrences across 32
files**. **26 of those, across 3 files, are unrelated** and re-measured as such:
`app/styles.css` (23, every one of them `font-weight`), `scripts/make_icons.py` (2, a
colour blend factor at lines 53 and 56) and `tests/test_suite_integrity.py` (1, the phrase
"dead weight" at line 1974). That leaves **234 relevant occurrences across 29 files**,
which decompose as 42 in `src/`, 3 in `app/`, 85 in `tests/`, 3 in the three top-level
planning and instruction documents, 87 across 13 files in `plans/tasks/` and 14 across 3
files in `plans/mutations/`.

### 2a. Source

| File | Occurrences | What is there |
|---|---|---|
| `src/splitwise_lite/split.py` | 27 | `split_by_weight` (lines 116-147), the `__all__` entry (line 60), the module docstring's mode map (lines 8-13), `_allocate`'s docstring and parameters, the weights-sum-to-zero guard (lines 209-212), `_ordered_from_mapping`'s two-caller comment (lines 377-384) |
| `src/splitwise_lite/web.py` | 13 | `_resolve_split`'s docstring (line 1535), the `weight` arm (lines 1551-1561), the mode-list refusal (line 1576), `_require_weight` (lines 1596-1609), a cross-reference in `_require_exact_amount`'s docstring (line 1615) |
| `src/splitwise_lite/__init__.py` | 2 | the import at line 127 and the `__all__` entry at line 277 |

**Call sites of `split_by_weight` in shipped code: exactly one.** `web.py:1554`, inside
`_resolve_split`'s `weight` arm. There is no other. `scripts/` does not resolve splits;
`balances.py`, `simplify.py`, `staleness.py`, `store.py`, `groups.py` and `accounts.py`
contain the string `weight` zero times.

**Exports: three lines and one assertion.** `split.py:60`, `__init__.py:127`,
`__init__.py:277`, and the identity assertion at `tests/test_split.py:73`. No test pins
`split.__all__` against a literal list, so nothing else moves.

### 2b. The route table and the wire

**`_API_ROUTES` does not change.** No row is added, removed or edited. This is worth
saying explicitly because `create_app` audits `app.url_map` against `_API_ROUTES` and
`_SHELL_ROUTES` as its last act and refuses to return an app serving anything the tables do
not declare: that audit is about routes, and a split mode is a value inside a request body
on an existing route. The row that answers a weight request today and would answer it after
removal is the same one:

```
_ApiRoute("/api/expenses", "create_expense", _create_expense, ("POST",), _Access.MEMBER)
```

at `web.py:2313-2315`.

**What a request sending `mode: 'weight'` gets after removal, exactly.** It falls through
the two surviving arms of `_resolve_split` to the final `raise MalformedRequest` at
`web.py:1575-1577`. `ERROR_STATUS[MalformedRequest]` is `400` (`web.py:456`),
`ERROR_CODE[MalformedRequest]` is `"malformed_request"` (`web.py:502`), and `_error_body`
at `web.py:778-780` gives the one body shape. With `what = "a split"` (`web.py:1542`), the
answer is:

```
400 application/json
{"error": {"code": "malformed_request", "message": "a split mode must be one of 'equal' or 'exact', got 'weight'"}}
```

reached through `_Access.MEMBER`, so the session check, the member-link check and the CSRF
gate all still run first and a request failing any of them gets that refusal instead.

### 2c. Tests

| File | Occurrences | What moves |
|---|---|---|
| `tests/test_split.py` | 57 | **11 whole test functions deleted**, **8 parametrisation sites lose their `by_weight` arm**, feeding **14 further test functions**, plus the import at line 30 and the identity assertion at line 73 |
| `tests/test_web_api.py` | 11 | **2 whole test functions deleted**, 3 parametrisations lose an arm, 1 test renamed |
| `tests/test_error_messages.py` | 12 | **4 rows of `FOUR_HUNDRED_SITES` move**, see 2d |
| `tests/test_add_screen.py` | 4 | 1 test keeps passing but its comment becomes false |
| `tests/test_end_to_end.py` | 1 | the committed journey's expense E2 |

The 11 deleted functions in `tests/test_split.py`:
`test_split_by_weight_allocates_in_proportion` (6 params),
`test_split_by_weight_gives_the_leftover_to_the_largest_remainder`,
`test_double_the_weight_is_double_the_cents`,
`test_split_by_weight_accepts_a_zero_weight`,
`test_split_by_weight_rejects_a_negative_weight`,
`test_split_by_weight_rejects_weights_that_all_sum_to_zero`,
`test_split_by_weight_rejects_a_weight_that_is_not_an_int` (6 params),
`test_split_by_weight_rejects_an_empty_mapping`,
`test_split_by_weight_rejects_weights_that_are_not_a_mapping` (5 params),
`test_equal_weights_agree_with_the_equal_split` (5 params) and
`test_weighted_split_holds_across_random_weights`.

The 8 parametrisation sites: the three inline lists at lines 78-85, 93-100 and 107-114;
`MODES` at lines 365-374, which six tests consume (lines 379, 387, 398, 535, 547, 559);
the two `["by_weight", "exact"]` lists at lines 437-443 and 450-456; `WITHOUT_CURRENCY` at
lines 468-472; and `WITH_A_CURRENCY` at lines 474-489, which two tests consume.

The two `["by_weight", "exact"]` lists feed `test_the_mapping_modes_reject_an_empty_member_id`
and `test_the_mapping_modes_reject_a_member_id_that_is_not_a_str`. With one mapping mode
left, both names become false and both need renaming.

The 2 deleted functions in `tests/test_web_api.py`:
`test_a_weighted_split_stores_the_event_field_by_field` (line 2810) and
`test_weights_summing_to_zero_are_refused_by_the_resolver` (line 3022). The renaming is
`test_an_unknown_split_mode_names_the_three_that_exist` (line 3271), whose body loops over
`("'equal'", "'weight'", "'exact'")` at line 3286.

### 2d. `FOUR_HUNDRED_SITES`, precisely

The issue says this table "loses rows, including the one driven row that reaches
`split.py::_ordered_from_mapping`'s negative guard". That is right about the mechanism and
one word wrong about the count: **four rows are affected and only one is lost.**

| Row | Today | After removal |
|---|---|---|
| `web.py::_require_weight::every weight in a split must be a JSON integer` (line 1621-1638) | driven | **deleted**, because the raise site is deleted and `test_every_four_hundred_raise_site_is_declared` is an equality over raise sites in both directions |
| `split.py::_ordered_from_mapping::every  must be zero or positive` (line 1130-1149) | driven, through weight mode | **converts to `unreachable(...)`** with a reason |
| `split.py::_allocate::weights sum to zero, so there is no share to divide the total into` (line 1033-1048) | driven, through weight mode | **converts to `unreachable(...)`** with a reason, if the guard is kept |
| `web.py::_resolve_split:: mode must be one of 'equal', 'weight' or 'exact', got ` (line 1572-1587) | driven, through `mode: "percentage"` | **stays driven, skeleton changes**, because the skeleton is part of the declared key |

The issue does not mention the `_allocate` row at all. That is its one miss inside its own
list, and it matters, because that guard's reachability is not obvious: `split_equally`
reaches `_allocate` too, so a reader could reasonably assume the guard stays live. It does
not. `split_equally` passes `[1] * len(ordered)` (`split.py:113`) and
`_ordered_from_iterable` rejects an empty list (`split.py:338-339`), so the weight total is
always at least 1 and the guard at `split.py:209-212` can never fire.

Two mechanical consequences, both re-measured on this tree:

* `grep -c '^    unreachable(' tests/test_error_messages.py` returns **47** today. After
  removal with both guards kept it returns **49**. That number is quoted in
  `tests/conftest.py:6-8` and the docstring there must move with it.
* Each new `unreachable(...)` row needs a reason of at least `MIN_REASON` characters,
  which is **30** (`tests/test_error_messages.py:120`).
* The marker is no longer a claim nobody checks. Issue #82 landed at `d987b64` and
  `tests/conftest.py` now reds if a row marked `NO_REQUEST_REACHES_IT` answers a request
  the suite makes. The issue predates that and does not say so. In practice this works in
  the removal's favour: with weight mode gone, nothing can reach either guard, so the
  guard passes and the claim is checked rather than asserted.

### 2e. What the issue does not name

Ten items, all re-measured:

1. **`tests/test_end_to_end.py:176`.** The committed end-to-end journey enters expense E2
   as `{"mode": "weight", "weights": {Sam: 1, Ali: 3}}` on `"80.00"`. The replacement is
   arithmetically identical and one line: `{"mode": "exact", "amounts": {Sam: "20.00",
   Ali: "60.00"}}` resolves to the same `Sam "20.00", Ali "60.00"` the test asserts at
   lines 184-187, so the balance figures at lines 221-229 (Sam +50.00, Ali -10.00,
   Jo -40.00) and every assertion downstream of them hold unchanged.
2. **`plans/tasks/18-end-to-end-smoke-test.md`**, criterion 12 at line 524 ("one per wire
   mode, in the order `equal`, `weight`, `exact`"), the expense table at lines 264-273,
   and mutation **M3** at line 616, whose `find` is `return _allocate(total, ordered,
   values)`, a line inside `split_by_weight` (`split.py:147`). A recorded mutation outside
   `plans/mutations/` rots.
3. **`_allocate`'s weights-sum-to-zero guard becomes unreachable**, as measured in 2d.
4. **`_allocate`'s largest-remainder ordering loses all coverage through the public
   surface**, as argued in section 1.
5. **`web.py:1615`**, in `_require_exact_amount`'s docstring: "It takes no key either, for
   the reason `_require_weight` does not." A dangling cross-reference, and the reason it
   points at (issue #61: the key was a member id going straight into a mapped 400 body,
   and dropping the parameter is what makes the leak impossible to reintroduce without a
   reviewer seeing an added argument) has to survive somewhere.
6. **`split.py:377-384`**, the comment on the negative guard: "this function serves two
   callers: it is a weight for `split_by_weight` and cents for `split_exact`". False with
   one caller.
7. **`split.py:8-13`**, the module docstring's map of three backlog modes onto four
   functions.
8. **`app/index.html:176-178` and `app/api.js:393-394`.** Both carry comments asserting the
   weight mode is reachable through the API. Editing either changes the shell digest, so
   `SHELL_DIGEST` in `app/sw.js` has to be re-pasted from the failing test's output. The
   issue does not mention the digest, and it is the thing most likely to red a merge commit
   whose base has moved.
9. **`tests/test_add_screen.py:528-533`.** `test_the_screen_never_exposes_a_weight_split`
   keeps passing after removal, because it only asserts an absence. Its comment at lines
   529-532 says `split_by_weight` "stays in the domain layer and stays reachable through
   the API", which becomes false while the test stays green. A test whose comment is false
   is precisely what this repo reds on elsewhere, and nothing will red on this one.
10. **Thirteen documents under `plans/tasks/`** hold 87 occurrences between them:
    `03-split-resolver.md` (19), `61-no-4xx-body-carries-an-identifier.md` (31),
    `39-split-refusals-in-the-money-that-was-typed.md` (11), `10-expense-entry-screen.md`
    (8), `18-end-to-end-smoke-test.md` (6), `09a-application-server-and-http-api.md` (3),
    `58-...` (2), `60-65-67-...` (2), and one each in `12-balances-screen.md`,
    `15-receiver-confirmation.md`, `42-what-the-documents-claim.md`, `44-...` and `70-...`.
    Most of these are dated records of past work and must not be rewritten. The criteria
    below name the four that state the capability in the present tense.

### 2f. Mutation records whose anchor targets `split.py`

Checked, as asked, because PR #93 is landing a check that turns a rotted anchor into a
failing test. **Three anchors in two files target `split.py`, and one of them is already
rotted before this task touches anything.**

| Record | File and line | Anchor | State today |
|---|---|---|---|
| `g1-weights-sum-to-zero` | `plans/mutations/65-message-pins.md:18-30` | the three-line `raise InvalidSplit("weights sum to zero, ...")` at `split.py:210-212` | **matches** |
| `g2-repeated-member` | `plans/mutations/65-message-pins.md:50-62` | `raise InvalidSplit(\n f"member_ids names a member more than once: {list(ordered)}"\n )` | **already rotted.** `split.py:343` now reads `raise InvalidSplit("member_ids names a member more than once")`, one line with no interpolation, changed by issue #61 |
| `restore-the-member-id-and-the-figure` | `plans/mutations/61-identifiers-in-4xx-bodies.md:76-92` | `            raise InvalidSplit(f"every {field} must be zero or positive")` at `split.py:384` | **matches** |

Plus, outside `plans/mutations/`, **M3 in `plans/tasks/18-end-to-end-smoke-test.md:616`**,
whose `find` is inside `split_by_weight` and which removal destroys outright.

Three further records name pytest node ids that removal deletes, which is a second kind of
rot and one that PR #93's anchor check will not necessarily see:
`61-identifiers-in-4xx-bodies.md:82` and `:84`, `65-message-pins.md:24` and `:27`, and
`82-the-unreachability-claim.md:101`, `:125` and `:128`.

Note the standing conflict this walks into, and do not try to resolve it inside this task:
`plans/mutations/README.md:108-118` states that the suite deliberately does not re-verify
anchors and that "a record going stale is expected rather than a failure", with a stated
reason (ossification, issue #60). PR #93 reverses that position. The engineer who takes
this branch should read whichever of the two has landed at the time and follow it, and
should not edit `README.md` here to agree with either.

Also note the format constraint: `tests/test_suite_integrity.py` checks that every record
block parses and holds **exactly seven keys and no others**
(`plans/mutations/README.md:18-19`). A correction goes in prose beside the block, dated,
the way `plans/mutations/61-identifiers-in-4xx-bodies.md:16-43` already does it. Never as an
eighth key.

### 2g. The `CLAUDE.md` bullet, and what actually pins it

The bullet at `CLAUDE.md:18-20` currently ends: "The resolver's weight mode is reachable
through the API and no screen offers it." Its twin is `README.md:21-24`: "Those are the
spec's three modes. The resolver also takes weights, which the API accepts and no screen
offers."

**Read this before writing a criterion about it.** The literal in `tests/test_web_shell.py`
pins the **bold keys of the bullets**, not their prose. Measured:

* `WORKS_TODAY` at line 1355 holds `"Adding an expense": (("index.html", 'id="add-form"'),
  ("api.js", "addExpense:"))`. Neither evidence pair mentions weights.
* `test_both_documents_agree_on_what_works_today` (line 1603) extracts bullets, takes the
  bold key that opens each, and compares the **set of keys** in each document against
  `set(WORKS_TODAY)`.
* `test_every_capability_the_documents_claim_is_in_the_shell` (line 1667) checks the
  evidence substrings are present in `app/`.

So deleting or rewriting that sentence in `CLAUDE.md` and leaving `README.md` untouched
**leaves the suite green**. `CLAUDE.md:70-75`'s warning that "editing this file and leaving
`README.md` alone" turns the suite red is true at the granularity of bullet keys and not at
the granularity of sentences, and this task lives entirely at the sentence granularity.
Neither bullet key moves, in either branch: `Adding an expense` stays in `What works
today` in both documents and its entry stays in `WORKS_TODAY`. The pairing of the two
sentence edits is therefore on the engineer and on the reviewer, and the criteria below
name both files explicitly for that reason.

---

## Branch A: remove `split_by_weight`, the `weight` wire mode and `_require_weight`

### Goal

The resolver offers exactly the three split rules `plans/spec.md` locks, the API accepts
exactly the two wire shapes that express them, and `plans/spec.md` records that a fourth
was considered and dropped, so the question is not asked a sixth time.

### Acceptance criteria

**The resolver**

- A1. `src/splitwise_lite/split.py` defines exactly three public resolvers,
  `split_equally` and `split_exact` and no third. `split_by_weight` does not appear in the
  file.
- A2. `split.__all__` holds exactly `InvalidSplit`, `split_equally`, `split_exact`.
- A3. `src/splitwise_lite/__init__.py` neither imports nor re-exports `split_by_weight`,
  and `splitwise_lite.__all__` does not contain it.
- A4. `import splitwise_lite; splitwise_lite.split_by_weight` raises `AttributeError`.
- A5. `split.py`'s module docstring maps the spec's three rules onto the two functions that
  implement them, with no fourth row and no dangling sentence about weights. It cites
  `plans/spec.md`, not `plans/backlog.md`, as the source of the count.
- A6. **`_allocate` is unchanged, byte for byte, including its weights-sum-to-zero guard
  and its largest-remainder arithmetic.** Removing a wire mode does not change how
  remainder cents are assigned, and `plans/spec.md:65-69` makes that rule a locked
  modelling decision rather than an implementation detail. Checkable by diffing
  `split.py:195-233` against `543bd0e` and seeing no change.

  > **Resolution, 2026-09-09.** This criterion's region is a **superset of what its own
  > reason needs**, and honouring it literally shipped a false sentence in source. Both
  > halves are measured, not argued.
  >
  > A6 gives exactly two reasons for byte-identity: the remainder rule is a locked
  > modelling decision at `plans/spec.md:65-69`, and this line is what keeps two mutation
  > anchors matching. Neither reason reaches `_allocate`'s **docstring**. Where the two
  > anchors actually are, measured with `str.count` against `543bd0e`:
  >
  > * `g1-weights-sum-to-zero`, `plans/mutations/65-message-pins.md`: its `find` is the
  >   three-line `raise InvalidSplit(...)` of the weights-sum-to-zero guard, in
  >   `_allocate`'s **body**, at `543bd0e:split.py:210-212`.
  > * `restore-the-member-id-and-the-figure`,
  >   `plans/mutations/61-identifiers-in-4xx-bodies.md`: its `find` is one line in
  >   `_ordered_from_mapping`, which is **not in `_allocate` at all**. That line is A7's
  >   subject, not A6's.
  >
  > So the docstring lines, `543bd0e:split.py:198-206`, are covered by neither anchor and
  > carry no arithmetic. Meanwhile line 201 of that docstring read "``split_equally``
  > reaches it with every weight set to 1, so the two fair-share modes cannot drift
  > apart", which Branch A makes false: there is one fair-share mode. A6 as written made
  > that falsehood mandatory, in the docstring of the function a reader of `_allocate`
  > opens, while **A30 in this same list says a green test with a false comment "is not
  > acceptable here"**. The two criteria pulled opposite ways over one file.
  >
  > **Resolved by narrowing A6 to its stated reason, and the criterion text above is left
  > standing.** A6 now reads as: `_allocate`'s **signature, guard and largest-remainder
  > arithmetic** are byte for byte as they were at `543bd0e`; its docstring prose may be
  > corrected. Measured after the correction, with `str.count` over the file text, which
  > is the operation both appliers use:
  >
  > * `543bd0e:split.py:207-233`, the whole body, guard and sort key and rotation
  >   included: **1**.
  > * the signature, `543bd0e:split.py:195-197`: **1**.
  > * the weights-sum-to-zero guard alone: **1**. The sort key line alone: **1**. The
  >   `offset = (total_cents // count) % count` line alone: **1**.
  > * `g1-weights-sum-to-zero`'s `find`: **1**. `restore-the-member-id-and-the-figure`'s
  >   `find`: **1**.
  > * the old whole region, `543bd0e:split.py:195-233`: **0**, which is the docstring
  >   edit and is the only thing that moved.
  >
  > `test_every_recorded_anchor_matches_once_or_is_carried` was re-run after the edit and
  > is **green**, `CARRIED_STALE_ANCHORS` is unchanged and `CARRIED_STALE_TOTAL` is still
  > 1. Nothing under `plans/mutations/` rots. Found by the reviewer and by QA on PR #98,
  > both of whom measured the anchor positions independently; QA was right that obeying
  > A6 literally was a criterion breach and the reviewer was right that no anchor forced
  > it, and this note is the two findings reconciled rather than either one alone.
- A7. **`_ordered_from_mapping`'s `raise InvalidSplit(f"every {field} must be zero or
  positive")` line is unchanged, byte for byte**, and the `field` parameter survives even
  though it now has one caller. Same reason as A6, plus: this line is the live anchor of
  `restore-the-member-id-and-the-figure`, and keeping it intact is what stops this task
  rotting a mutation record. The comment above it (`split.py:377-383`), which says the
  function serves two callers, is corrected to say it serves one and to keep the reason the
  integer is dropped from the message.
- A8. The largest-remainder branch of `_allocate` gains direct coverage, or the loss is
  recorded. Concretely: `tests/test_split.py` holds at least one test that drives
  `_allocate` with unequal weights and asserts the exact cent allocation, **or** the PR
  body and a dated note in `plans/tasks/03-split-resolver.md` state that the branch is now
  untested and why that was accepted. One of the two, not neither. Checkable by opening
  `tests/test_split.py` and searching for `_allocate`.

**The HTTP layer**

- A9. `web.py::_resolve_split` has two arms, `equal` and `exact`, and its docstring says
  two.
- A10. `web.py::_require_weight` does not exist.
- A11. `web.py::_require_exact_amount`'s docstring no longer refers to `_require_weight`,
  and states in its own words why it takes no key: the key would be a member id of the
  current roster going into a mapped 400 body, and dropping the parameter rather than only
  the interpolation is what makes the leak impossible to reintroduce without a reviewer
  seeing an added argument. Issue #61 is cited.
- A12. `_API_ROUTES` is unchanged. The diff touches no line between `web.py:2288` and
  `web.py:2351`.
- A13. A `POST /api/expenses` from a signed-in, linked member with a valid CSRF token and a
  body whose `split` is `{"mode": "weight", "weights": {<a roster member id>: 1}}` answers
  **`400`** with content type `application/json` and body exactly
  `{"error": {"code": "malformed_request", "message": "a split mode must be one of 'equal' or 'exact', got 'weight'"}}`,
  and writes nothing: the expense count is unchanged. The row it is answered through is
  `_ApiRoute("/api/expenses", "create_expense", _create_expense, ("POST",), _Access.MEMBER)`.
  A test asserts the status, the code, the whole message by equality and the unchanged
  count.
- A14. **The awkward one.** That request carries a `weights` key, which is now
  unrecognised. The refusal is still about the mode and not about the key, because
  `_require_keys` is only reached inside a matched arm. The message names `'equal'` and
  `'exact'` and does not name `'weight'` as a mode that exists; the only occurrence of the
  word in the body is the echo of what the caller sent, after `got `. A test asserts that
  the message does not contain the substring `'weight'` in a position that reads as an
  offer, by asserting the whole message with `==` rather than with a substring check.
- A15. A body whose `split` is `{"mode": "weight"}` with no `weights` key gets the same
  400 and the same message. The mode is checked before the shape.
- A16. No 4xx body sent by this route names an identifier the store holds. Issue #61's
  property is unchanged and `test_no_four_hundred_body_names_an_identifier` covers the new
  and changed rows.

**The declared error surface**

- A17. `FOUR_HUNDRED_SITES` in `tests/test_error_messages.py` no longer holds a row for
  `web.py::_require_weight`.
- A18. The `web.py::_resolve_split` mode row's skeleton is updated to the new sentence and
  stays driven, through a mode that is neither `equal` nor `exact`.
- A19. `split.py::_ordered_from_mapping::every  must be zero or positive` is
  `unreachable(...)` with a reason of at least 30 characters that says what would have to be
  true for a request to reach it: that `money.parse_amount` refuses every signed string
  before `split_exact` sees one, so the only caller that could hand this guard a negative
  is inside the process.
- A20. `split.py::_allocate::weights sum to zero, ...` is `unreachable(...)` with a reason
  of at least 30 characters naming its own mechanism: `split_equally` is the only caller and
  passes `[1] * len(ordered)` over a list `_ordered_from_iterable` has already refused to
  leave empty, so the weight total is at least 1.
- A21. `grep -c '^    unreachable(' tests/test_error_messages.py` returns **49**, and the
  docstring at `tests/conftest.py:6-8` that quotes **47** is updated with the new figure and
  a new measurement date.
- A22. `tests/conftest.py`'s guard passes: neither newly marked row answers any request the
  suite makes. This is not a formality, it is the check that the two unreachability claims
  above are true rather than asserted.
- A23. `test_every_four_hundred_raise_site_is_declared` passes, which is the equality that
  catches a deleted row whose raise survives and a surviving row whose raise is deleted.

**Tests**

- A24. The 11 test functions named in section 2c are gone from `tests/test_split.py`, and no
  test in the suite calls `split_by_weight`.
- A25. The 8 parametrisation sites named in section 2c each lose exactly their `by_weight`
  arm and keep their others. No consuming test is deleted.
- A26. `test_the_mapping_modes_reject_an_empty_member_id` and
  `test_the_mapping_modes_reject_a_member_id_that_is_not_a_str` are renamed, because there
  is one mapping mode. The new names name `split_exact`.
- A27. `tests/test_split.py:69-75`'s re-export assertion covers the three surviving names
  and does not mention the fourth.
- A28. `tests/test_web_api.py` loses the two functions named in section 2c, and
  `test_an_unknown_split_mode_names_the_three_that_exist` is renamed to say two and loops
  over two.
- A29. `tests/test_end_to_end.py`'s expense E2 is entered through exact mode as
  `{"mode": "exact", "amounts": {Sam: "20.00", Ali: "60.00"}}`, keeping the payer, the
  `"80.00"` total, the description and every downstream figure identical. A comment on that
  line says the mode was changed by this issue and that the allocations are the same two
  figures the weight split produced, so a later reader does not think the journey's
  arithmetic was re-derived.
- A30. `tests/test_add_screen.py::test_the_screen_never_exposes_a_weight_split` keeps its
  assertion and gains a corrected comment: the ban now guards against re-introducing a mode
  the API no longer accepts, rather than against exposing one it does. A green test with a
  false comment is not acceptable here, and nothing will red on it, so this is on the
  reviewer.
- A31. `CARRIED_UNANCHORED_BLOCKS["tests/test_split.py"]` and `CARRIED_TOTAL` are unchanged.
  Measured: that entry holds `test_split_exact_rejects_amounts_that_fall_short` and
  `test_split_exact_rejects_amounts_that_overshoot`, neither of which is deleted, and
  `CARRIED_TOTAL` is **102** on this tree. If either moves, something was deleted that
  should not have been.
- A32. No new `pytest.raises(match=)` is written unanchored and no new
  `assert <needle> in str(exc.value)` block is added without one of the four accepted
  anchors. `tests/test_suite_integrity.py` enforces both.
- A33. `uv run python -m pytest` is green on both CI legs, from a branch brought up to date
  with `master`.

**The shell**

- A34. The comment at `app/index.html:176-178` is rewritten: the mode is gone rather than
  unexposed, and the reason it was never offered here (a weight typo produces a wrong but
  valid split where a wrong exact share is refused with both figures named) is preserved,
  because that reason is the argument for the removal and must not be deleted along with
  its subject.
- A35. The comment at `app/api.js:393-394` says two shapes.
- A36. `SHELL_DIGEST` in `app/sw.js` is re-pasted from the failing test's output. `VERSION`
  is not bumped: the worker's own behaviour has not changed.
- A37. No behaviour under `app/` changes. `addSplit()` is untouched, the three radio
  controls are untouched, `API_SURFACE` is untouched at sixteen keys.

**The documents**

- A38. `plans/spec.md` gains a sentence, in "Modelling notes" beside the collapse-to-one-shape
  paragraph, recording that a fourth resolver mode, weights, existed in the code from task 3
  until issue #78, answered no rule in the locked table, was never offered by any screen, and
  was removed. It says why, in one clause, so the next reader does not have to find this file.
  **This is the point of the whole task.** Three readers went to `plans/spec.md`, found it
  silent, and asked the question again; a fourth will do the same unless the answer is in the
  file they open.
- A39. `plans/backlog.md:39`, task 3, is corrected: "uneven by weight or exact amount" is
  where the fourth mode entered, and it currently reads as a spec requirement. The correction
  quotes the wording it retracts and carries a date, per this repo's convention.
- A40. `CLAUDE.md:18-20` and `README.md:21-24` are **both** edited in the same commit, and
  neither claims a weight mode. Neither bullet key moves and no literal in
  `tests/test_web_shell.py` changes. Nothing in the suite will pair these two edits for you,
  as measured in 2g.
- A41. Four `plans/tasks/` documents state the capability in the present tense and each gains
  a dated correction note quoting what it retracts, rather than being silently rewritten:
  `03-split-resolver.md` (the four-row table at lines 20-25 and the Weighted split section at
  lines 96-115), `09a-application-server-and-http-api.md` (the three shapes at lines 432-437,
  and lines 827, 836 and 839), `10-expense-entry-screen.md` (lines 78-99, 434, 693 and the Out
  of scope bullet at 761-763) and `18-end-to-end-smoke-test.md` (the table at lines 264-273,
  criterion 12 at line 524, and mutation M3 at line 616, which is retired with a note saying
  its anchor no longer exists). `42-what-the-documents-claim.md:189-190` is a record of a past
  audit and is left alone.
- A42. The three mutation records in `plans/mutations/` whose `kills` or `survives` name
  deleted node ids each gain a dated prose note beside the block, naming which node ids no
  longer exist and why. The seven JSON keys are not edited and no eighth key is added. The two
  live `split.py` anchors still match exactly once, which criteria A6 and A7 guarantee and
  which the engineer verifies with the exactly-once assertion from
  `plans/mutations/README.md:56-65`.
- A43. The already-rotted `g2-repeated-member` anchor (section 2f) is **noted, not fixed**,
  in the PR body, so the reviewer and whoever lands PR #93 can see it was found here and was
  not caused here.

### Out of scope

- Changing how remainder cents are assigned, or simplifying `_allocate` now that its only
  caller passes uniform weights. That is a second decision with its own blast radius and its
  own effect on `plans/spec.md:65-69`.
- Adding any new split mode, percentage included. `plans/tasks/10-expense-entry-screen.md:761-763`
  already rules percentages out and this task does not reopen that.
- Any change to `_API_ROUTES`, to access policy, to CSRF, to rate limiting or to what any
  other `DomainError` becomes on the wire.
- Any change to the entry screen's controls, layout or copy. The three radio controls stay
  as they are; only a comment changes.
- Fixing the already-rotted `g2-repeated-member` anchor, or reconciling
  `plans/mutations/README.md:108-118` with PR #93. Both are named here and neither is this
  task's.
- Rewriting dated historical records under `plans/tasks/` and `plans/reviews/` that describe
  what was true when they were written. Only the four documents in A41 make present-tense
  claims.
- Bumping `VERSION` in `app/sw.js`.
- Backfilling any ledger. No stored `ExpenseEvent` mentions a mode: `plans/spec.md:65-69`
  collapsed all rules to explicit `(person, cents)` at entry time, so expenses recorded
  through weight mode are indistinguishable from any other and need no migration. Say so in
  the PR body, because a reader will ask.

### Constraints

- Files that may change: `src/splitwise_lite/split.py`, `src/splitwise_lite/web.py`,
  `src/splitwise_lite/__init__.py`, `app/index.html`, `app/api.js`, `app/sw.js` (the
  `SHELL_DIGEST` line only), `tests/test_split.py`, `tests/test_web_api.py`,
  `tests/test_error_messages.py`, `tests/test_end_to_end.py`, `tests/test_add_screen.py`,
  `tests/conftest.py` (the docstring count only), `CLAUDE.md`, `README.md`,
  `plans/spec.md`, `plans/backlog.md`, the four `plans/tasks/` documents in A41, the three
  `plans/mutations/` records in A42, and this file. Nothing else.
- `split.py:195-233` and `split.py:384` are byte-identical to `543bd0e` at the end. Two
  mutation anchors depend on it.

  > **Resolution, 2026-09-09.** Narrowed with criterion A6, and this bullet is left
  > standing. Measured at the end, with `str.count` over the file text: `split.py:384` is
  > byte-identical, count **1**. The first region is **not**: `543bd0e:split.py:195-233`
  > counts **0**, because `_allocate`'s docstring carried a sentence Branch A made false,
  > "the two fair-share modes cannot drift apart", and it was corrected. What is
  > byte-identical is `_allocate`'s **signature**, `543bd0e:split.py:195-197`, count
  > **1**, and its whole **body**, `543bd0e:split.py:207-233`, count **1**, guard and
  > sort key and rotation included. Only the docstring block `198-206` moved, and it
  > counts **0**, which localises the change exactly. The reasoning, including why the
  > docstring lines are outside anything the anchors need, is in the dated resolution
  > under **A6** above; this note exists because a reader of Constraints should not have
  > to find that 200 lines earlier, and because the rule three bullets below this one
  > says a correction lives in the committed document beside what it retracts.
  >
  > **The second sentence was inaccurate before Branch A and is not something it
  > changed.** Only `g1-weights-sum-to-zero` anchors inside `195-233`.
  > `restore-the-member-id-and-the-figure` anchors into `_ordered_from_mapping`, which is
  > the `split.py:384` half of this bullet and criterion A7's subject, not A6's. So one
  > anchor depends on each region rather than two on the pair. Both still match exactly
  > once and `test_every_recorded_anchor_matches_once_or_is_carried` is green.
- Corrections quote what they retract and carry a date, and live in the committed document
  rather than in the PR body.
- Money stays integer cents. Nothing in this task computes or formats an amount.
- The domain layer stays framework free: `split.py` imports from `money` and `events` and
  nothing else, which `test_split_imports_only_money_and_events_from_the_package` holds it to.
- `uv run python -m pytest`, never `uv run pytest`. `node` 20 or later on `PATH`.
- Both CI legs green on a branch brought up to date with `master`, because a stale shell
  digest surfaces at the merge commit.

---

## Branch B: keep it, as a deliberate library capability with no product behind it

> **Not taken. Recorded 2026-09-09.** The fork was decided in favour of **Branch A,
> remove**, and B1 to B15 below were never implemented. They are left standing, unedited,
> as the record of what was weighed against Branch A, which is what stops the decision
> reading as uncontested. **Nothing below this line is a live requirement**, and none of
> it is to be picked up from this file without a new decision and a new issue. See the
> dated note under **Status** at the top of this document, and `plans/spec.md`'s
> modelling notes for the reason.

### Goal

The fourth mode stops being an unexplained artefact. It is recorded as a decision in the
file a reader opens to check what the product requires, the wire contract is unchanged, and
no code moves.

### Acceptance criteria

**Behaviour**

- B1. No file under `src/` changes behaviour. `split_by_weight`, the `weight` wire arm and
  `_require_weight` are all present and unchanged.
- B2. **What a request sending `mode: 'weight'` gets is unchanged**, and this is stated
  rather than assumed: a `POST /api/expenses` from a signed-in, linked member with a valid
  CSRF token and `{"mode": "weight", "weights": {...}}` answers **`201`** with
  `{"expense": {...}}`, having resolved the allocations through
  `split.split_by_weight`, through the route row
  `_ApiRoute("/api/expenses", "create_expense", _create_expense, ("POST",), _Access.MEMBER)`.
  `tests/test_web_api.py::test_a_weighted_split_stores_the_event_field_by_field` is the
  check and it is unchanged and green.
- B3. No file under `app/` changes, so `SHELL_DIGEST` in `app/sw.js` is untouched. Checkable
  by the diff naming no path under `app/`. This is a real difference from branch A and worth
  keeping: `app/index.html:176-178` already states this decision correctly and needs nothing.
- B4. `FOUR_HUNDRED_SITES` is unchanged, all four rows in section 2d stay as they are, and
  `grep -c '^    unreachable(' tests/test_error_messages.py` still returns **47**.
- B5. No test is added, deleted or renamed. `CARRIED_TOTAL` stays at **102**.

**Where the decision is written down**

- B6. **`plans/spec.md` gains the decision**, and this is the criterion the whole branch
  exists for. Under "Modelling notes", beside the collapse-to-one-shape paragraph, it records
  that `src/splitwise_lite/split.py` carries a fourth resolver, `split_by_weight`, which the
  locked table's three rules do not require, which the API accepts and which no screen offers;
  that it was considered for removal on issue #78 and kept deliberately; and, in one clause,
  why. A reader who opens `plans/spec.md` asking "why is there a fourth mode" finds the answer
  there. Checkable by opening `plans/spec.md` and finding the string `split_by_weight`, which
  occurs zero times in it today.
- B7. That sentence names the risk it is accepting, in its own words rather than by
  reference. `app/index.html:177-178` states it: a weight typo produces a wrong but valid split
  where a wrong exact share is refused with both figures named. `plans/spec.md:29-33` names the
  product's largest risk as a ledger that looks authoritative while being wrong. If the spec is
  keeping a mode whose only failure is silent wrongness, the spec says so out loud, in the spec,
  rather than leaving it in an HTML comment two directories away.
- B8. `plans/backlog.md:39`, task 3, is corrected the same way branch A corrects it: it is where
  the fourth mode entered, it currently reads as a spec requirement, and after this task it says
  the widening was ratified on this date by issue #78, with a pointer to `plans/spec.md`. Without
  this, the ratification is re-litigated from the backlog by the next reader.
- B9. `src/splitwise_lite/split.py`'s module docstring at lines 8-13 gains one sentence saying
  the fourth function answers no rule in `plans/spec.md` and is kept deliberately, with a
  pointer to where. That docstring is where a reader who got as far as the code will land, and
  it currently presents four functions as the natural shape of three modes.
- B10. `CLAUDE.md:18-20` and `README.md:21-24` are **both** edited in the same commit so that
  each says the weight mode is kept deliberately and points at `plans/spec.md`. Today they
  state the fact and not the decision, which is what let three readers treat it as an oversight.
  Neither bullet key moves and no literal in `tests/test_web_shell.py` changes. Nothing in the
  suite will pair these two edits for you, as measured in 2g.
- B11. `tests/test_add_screen.py:529-532`'s comment stays true and is left as it is.
- B12. Issue #78 is closed with a link to the committed sentence in `plans/spec.md`, not with
  a PR-body explanation. A decision that lives only in a PR body is the thing this issue was
  filed about.

**Awkward cases the criteria settle**

- B13. Nothing is said to any external caller, because measurably there is none: no
  `CHANGELOG.md`, no `docs/`, no OpenAPI document, no version segment on `/api`, and
  `app/api.js` is the only client. The written wire contract stays where it is, at
  `plans/tasks/09a-application-server-and-http-api.md:432-437` and `app/api.js:393-394`, and
  both already describe three shapes correctly.
- B14. Keeping the mode means keeping the two `split.py` guards reachable, which is the
  positive case for it on the test side and should be stated in the PR body so it is not
  re-derived: weight mode is the only route by which an HTTP request reaches
  `split.py::_allocate`'s weights-sum-to-zero guard and `split.py::_ordered_from_mapping`'s
  negative guard, and it is the only public surface exercising `_allocate`'s
  largest-remainder ordering with unequal weights.
- B15. The kept capability is not added to `CLAUDE.md`'s or `README.md`'s `What does not
  exist yet` list and does not become a `NOT_YET` entry. It is not a missing capability; it is
  a present one with no screen, and the two lists are about the shell.

### Out of scope

- Building a screen for it. If anyone ever asks for weights on the entry screen, that is a
  new backlog task with its own spec, and `plans/tasks/10-expense-entry-screen.md:94-99` is the
  argument it has to answer.
- Any code change at all. If this branch touches a file under `src/` other than `split.py`'s
  module docstring, it has gone wrong.
- Changing what the API accepts, refuses or returns.
- Adding a percentage mode, or any other mode.
- Rewriting dated historical records under `plans/tasks/` or `plans/mutations/`.

### Constraints

- Files that may change: `plans/spec.md`, `plans/backlog.md`, `CLAUDE.md`, `README.md`,
  `src/splitwise_lite/split.py` (module docstring only), and this file. Nothing else, and
  nothing under `app/` or `tests/`.
- Corrections quote what they retract and carry a date, and live in the committed document.
- `uv run python -m pytest`, never `uv run pytest`. Both CI legs green.

---

## 4. What is true either way

- **`plans/spec.md` gains a sentence.** This is the one thing neither branch may skip. Three
  readers went to `plans/spec.md`, found it silent on the fourth mode, and asked the question
  again; the issue exists precisely so a fourth does not. Removal without a sentence in the spec
  leaves the next reader of `plans/backlog.md:39` free to re-add it, and keeping without one
  leaves the situation exactly as it is now.
- **`plans/backlog.md:39` is corrected either way.** "uneven by weight or exact amount" is
  where the fourth mode entered the codebase and it currently reads as something the spec asked
  for. It did not.
- **`CLAUDE.md:18-20` and `README.md:21-24` move together, in one commit, with no test forcing
  it.** Measured in section 2g: the literal in `tests/test_web_shell.py` pins bullet keys, not
  sentences, and the bullet key `Adding an expense` does not move in either branch.
- **The three mutation records that name `split.py` are read before `split.py` is touched.**
  Two anchors match today (`g1-weights-sum-to-zero` and `restore-the-member-id-and-the-figure`)
  and one is already rotted (`g2-repeated-member`, broken by issue #61, not by this task). The
  already-rotted one is reported, not repaired, in either branch.
- **No test is marked skipped or xfail to make the suite green**, no new `match=` pin is
  written unanchored, and `CARRIED_TOTAL`, which is 102 on this tree, only ever goes down.
- **Nothing in this task touches money arithmetic**, the remainder rule, `_allocate`'s
  rotation, or any stored event. No ledger needs backfilling in either branch: an
  `ExpenseEvent` stores explicit `(member, cents)` and no mode, per `plans/spec.md:65-69`, so
  expenses already recorded through weight mode are indistinguishable from any other and stay
  readable whichever way the fork goes.
- **The decision is recorded in the repository, not in a PR body**, and issue #78 is closed
  pointing at it.
