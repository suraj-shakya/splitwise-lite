# Task 18: End-to-end smoke test

**Depends on:** 10 (complete, on `master`), 12 (complete, on `master`), 15 (complete, on `master`),
and in practice also 3, 5, 6, 9, 9a, 13 and 14, all complete on `master`. Everything this task
reads exists today and is quoted from the shipped source below.

**Consumes:** `plans/tasks/15-receiver-confirmation.md`, section "What task 18 / issue #19 gets
from this". That section is the handoff and is taken as given here.

Sharpened from `plans/backlog.md` task 18, GitHub issue #19. The backlog entry stays as written;
this file is the implementable version. **This is the last numbered backlog task.**

---

## Findings you must read before you write a line

Four things were found while sharpening this task. Each one has silently destroyed work in this
repository before, or would have here.

### 1. `tests/test_smoke.py` already exists, and it is not this task

It is task 1's file. It is nine lines long and holds one test:

    def test_package_exposes_its_version() -> None:
        assert __version__ == "0.1.0"

`tests/test_simplify.py:1280` refers to it by name: *"``tests/test_smoke.py`` asserts it, so
adding a module must not move it."*

The obvious name for this task's file is therefore **taken**. Writing `tests/test_smoke.py` would
overwrite task 1's file, the suite would stay green, and one test would be gone. That is the same
failure as a duplicate test name, one level up. **The new module is `tests/test_end_to_end.py`**
and `tests/test_smoke.py` is left byte-identical to `master`.

### 2. There is no `tests/conftest.py`, anywhere in the repository

`pyproject.toml` sets `testpaths = ["tests"]` and nothing else. No `conftest.py`, no
`__init__.py` under `tests/`, no `pythonpath`. Seventeen test modules, zero shared fixture files.
That is deliberate, and this task does not change it. The helper question is decided below.

### 3. Member ids and group ids are random UUIDs, so ordering by id is not reproducible

`simplify._greedy` breaks ties by ascending `member_id`, `TransferPlan.transfers` is sorted by
`(from_member_id, to_member_id)`, `split._allocate` rotates leftover cents by position in the
id-sorted member list, and `simplify._fullest` breaks provenance ties by counterparty id. All four
depend on ids this test cannot predict.

Two consequences, both binding:

* **Every allocation in this test must divide exactly**, so no remainder rule is ever consulted.
  The amounts below are chosen so that every share is an exact integer number of cents. This is
  the same reasoning `seed_three_expenses` in `tests/test_web_api.py` already records: *"Every
  division is exact, so the figures below are arithmetic rather than a remainder rule."*
* **The `transfers` list must be compared as a name-keyed sorted list, never by index**, because
  its order is id order. The `net` list is safe to compare positionally, because it is
  `store.list_members` order, which is roster insertion order and is pinned by
  `test_the_roster_is_the_group_in_store_order_with_two_keys_each`.

`tests/test_groups.py::test_no_source_or_test_file_carries_a_literal_group_id` scans every `.py`
file under `tests/` for a UUID pattern and fails on one. So no id may be written down: every id in
this test comes from `GET /api/members`.

### 4. The shell harness cannot reach a real server, by construction

`tests/shell_harness.mjs` sets `sandbox.fetch = fetchStub` and answers every request from a
fixture. It runs the real `app/index.html`, `app/app.js` and `app/api.js`, but the network is a
stub and there is no mechanism, and no intention, for it to talk to a Flask test client. That
decides the scope question below.

---

## Goal

One test walks the product from an empty store to a cleared balance: seed a group, enter three
expenses covering all three split modes, read the simplified transfer plan, mark one of those
transfers as paid, have the receiver confirm it, and read the plan again with that debt gone and
that member at zero. When it passes, the ledger, the split resolver, the balance fold, debt
simplification, the HTTP layer, sessions, member linking and the two-person settlement rule have
all been exercised together, in one process, against one store.

When it fails, something in the product is broken rather than something in a unit's contract. That
is the whole value of it, and it is why this test asserts figures and not shapes.

---

## What "walks the whole product" means here, exactly

**Through the JSON API only.** The walk is: seed, enter, read, mark, confirm, read. Every one of
those verbs is an HTTP request except the seed, which is a call to the same function
`scripts/setup_group.py apply` calls. The backlog names no screen and no rendering.

**The shell is out of scope, and this is a decision rather than an omission.** The reason is
finding 4: the harness stubs `fetch`, so a walk that included the shell would have to invent a
bridge between Node and a Flask test client that does not exist today. Building one is a task of
its own, with a real cost (a second process per scenario, a serialisation format for requests and
responses, and a new way for a test to hang). The shell already has an end-to-end layer of its own
in `tests/shell_harness.mjs` and `tests/test_shell_behaviour.py`, driving the real shipped files
against fixtures that `tests/test_web_api.py` pins against the real API, for example
`test_the_shell_harness_refusal_fixture_is_the_sentence_the_api_sends`. That seam is the shell's
regression net; this task is the server's.

**Consequence, stated so nobody looks for it:** nothing under `app/` changes, so `SHELL_DIGEST` in
`app/sw.js` does not move, `VERSION` does not move, and
`test_the_recorded_digest_matches_the_files_it_covers` passes untouched. If you find yourself
editing `app/`, you have taken a wrong turn.

**The operator CLI is not shelled out to.** `scripts/setup_group.py apply` is an `argparse`
wrapper that calls `groups.apply_group_definition`, and `link` is a wrapper that calls
`groups.link_user_to_member`. `tests/test_setup_group_cli.py` owns the wrapper. This test seeds
through the same two functions, via the existing `seed_group` and `linked_client` helpers, so it
walks the code the CLI walks without spawning a process, writing a TOML file, or acquiring a
failure mode that has nothing to do with the ledger.

---

## The helper question, decided

`claim()` is at `tests/test_web_api.py:5443` and `decide()` at `:5434`. There is no
`tests/conftest.py`. The three options were weighed and the third was rejected along with the
second.

### The decision

**`tests/test_end_to_end.py` imports the helpers it needs from `tests/test_web_api.py`, by name,
in one explicit `from ... import (...)` statement, and imports no fixture.**

The import list is exactly these ten names and no others:

    from test_web_api import (
        CHEAP,
        add_expense,
        at,
        by_name,
        claim,
        debt_path,
        decide,
        equal_split,
        linked_client,
        seed_group,
    )

This works because pytest's default `prepend` import mode inserts `tests/` at the front of
`sys.path` before importing a test module from a directory with no `__init__.py`, which is the
arrangement this repository already has. `tests/test_end_to_end.py` sorts before
`tests/test_web_api.py`, and the path insertion happens at collection, before either import, so
collection order does not matter.

### Why this is not the duplication defect

Restating the helpers was rejected first, and it is worth being precise about why, because
"restating" sounds cheap and is not. `claim()` is four lines, but it calls `mark_paid`, which calls
`post`, which calls `send`, which calls `csrf_token`. `linked_client` calls `sign_up`, `log_in` and
`link_member`, and reads `PASSWORD` and `CHEAP`. A restated walk is roughly 150 lines of
scaffolding copied out of a 6,500 line file, and it is the exact shape of the defect family this
repository has spent days on (#57, #58, #60, #63, #65, #67, #70): two copies of one procedure with
nothing forcing them to agree.

The specific drift that would go uncaught is not the wire contract. A changed endpoint path or a
changed body key fails both copies at once, because both talk to the same server. The drift that
would go uncaught is in the **setup**: a change to how an account is signed up and linked, to the
scrypt parameters, to the CSRF dance, or to the order in which a client becomes a linked member.
The copy would keep passing while testing a differently-arranged flat, and a smoke test that
arranges the flat differently from every other test is a smoke test that proves less than it
claims.

Importing has the opposite failure mode, and it is the good one: **a rename in `test_web_api.py`
is an `ImportError` at collection**, loud, immediate, and impossible to miss. There is no state in
which the two files quietly disagree.

### Why not a `conftest.py`

Three reasons, in order of weight.

1. **It would not actually solve this problem without a refactor nobody asked for.** `conftest.py`
   shares *fixtures*. `claim`, `decide`, `post`, `add_expense` and `linked_client` are plain
   functions, not fixtures. Sharing them through a conftest means either turning them into factory
   fixtures and rewriting every call site in a 6,500 line file, or writing `import conftest`, which
   is the same cross-module coupling wearing a different filename. The refactor is a large, risky
   edit to the repository's central regression net, bought by one new test, on a branch running
   concurrently with two others that touch `tests/`.
2. **It is a new shared surface, and it changes where seventeen modules' future readers look.**
   The repository has been deliberate about not having one. Adding it for a single consumer moves
   the default answer to "where do fixtures live?" for every module, permanently.
3. **The coupling objection it answers is real but is a naming problem, not a correctness
   problem.** "Pytest modules are not a stable public surface" is true. It is made survivable by
   the two mitigations below, and it fails loudly rather than silently, which is the property that
   actually matters here.

### The two mitigations, both required

* The import is one explicit `from test_web_api import (...)` naming every name. No `import *`, no
  `import test_web_api` followed by attribute access, and no conditional import. A rename is an
  `ImportError` at collection and nothing else.
* `tests/test_web_api.py` gains **four comment lines and nothing else**, immediately under the
  existing banner at line 413, so a future renamer is told before they rename:

      # --- Helpers shared with the later sections ---------------------------------
      #
      # tests/test_end_to_end.py imports ten of the names in this file by name, in one
      # import statement at the top of that module. Renaming one of them is an
      # ImportError there at collection, not a silent loss of coverage. Rename both
      # or neither.

  That is the only change to any pre-existing file in the repository.

### Two things the import must not do

* **It must not import a fixture.** `store_path`, `seeded`, `app`, `client` and `secure_app` are
  pytest fixtures. Importing a fixture function into another module does work, and it is obscure
  enough to be a trap. `tests/test_end_to_end.py` builds its store and its app in its own fixture,
  in four lines, from `seed_group` and `CHEAP`.
* **It must not import any name beginning with `test_`.** A `test_` name imported into a module
  namespace is collected a second time, under a second node id, and the suite count changes for a
  reason nobody can find. None of the ten names begins with `test_`.

### One local helper is allowed, and only one

`tests/test_end_to_end.py` may define one reader:

    def read_balances(client) -> dict:
        response = client.get("/api/balances")
        assert response.status_code == 200, response.get_json()
        return response.get_json()

`test_web_api.py`'s `balances_of` throws the response away and so cannot assert the status. A
smoke test that read a 500 error body as a balances payload would report the wrong failure, in the
wrong place, at the end of a long walk. This is not the duplication question: there is nothing in
`client.get("/api/balances")` that can drift, because a changed path or method fails every reader
in the suite at once. What it adds is the assertion `balances_of` deliberately omits.

---

## The ledger, built by hand

**It does not share a seed or a fixture with the generated-ledger tests, and must not.**
`generate_ledger` and `LEDGER_SEED` exist so that
`test_a_pending_settlement_moves_no_balance_over_generated_ledgers` and its two task 15 siblings
can check an invariant over ledgers nobody hand-picked. That is a different job. A smoke test's
value is that a person can read it, follow the arithmetic, and see that the answer is right. A
random ledger cannot be read, and its expected figures would have to be computed by the same code
under test, which is not an assertion at all.

So: three expenses, chosen by hand, every division exact, every figure below arrived at by
addition.

### The group

Seeded with an explicit name, currency and roster rather than by relying on `test_web_api.py`'s
module constants, so a change to those constants cannot quietly change this test's ledger:

    seed_group(path, name="Flat 3", currency="AUD", members=("Sam", "Ali", "Jo"))

**Sam and Jo are linked to accounts. Ali is not.** Two linked accounts is the minimum the
two-person settlement rule requires: one person cannot both claim and answer a payment. Leaving Ali
unlinked is deliberate and is an awkward case worth walking: task 9 decided an unlinked member is a
full member that nothing filters or greys out, and every figure about Ali below renders exactly as
if Ali had signed up.

### The three expenses

All three are entered by **Sam's client**, so `created_by` is Sam on all three. `payer_id` names
Ali, Sam and Ali in turn, which is the shipped rule that recording a flatmate's spend is a normal
entry rather than an impersonation. The clock is pinned per expense by monkeypatching `web._now`.

| # | `mode` | `payer_id` | body | total | resolved allocations |
|---|---|---|---|---|---|
| E1 | `equal` | Ali | `member_ids` = Sam, Ali, Jo | `"30.00"` | Sam `"10.00"`, Ali `"10.00"`, Jo `"10.00"` |
| E2 | `weight` | Sam | `weights` = {Sam: 1, Ali: 3} | `"80.00"` | Sam `"20.00"`, Ali `"60.00"` |
| E3 | `exact` | Ali | `amounts` = {Ali: `"10.00"`, Jo: `"30.00"`} | `"40.00"` | Ali `"10.00"`, Jo `"30.00"` |

These are the three modes `src/splitwise_lite/split.py` implements, named as it names them:
`split_equally`, `split_by_weight` and `split_exact`, reached through `web._resolve_split`'s three
wire modes `equal`, `weight` and `exact`.

Every division is exact: 3000 / 3 = 1000 with nothing left; 8000 x 1 / 4 = 2000 and 8000 x 3 / 4 =
6000 with nothing left; an exact split has no remainder by construction. **No leftover cent is ever
assigned, so `split._allocate`'s rotation is never consulted and no figure below depends on a
member id.**

Descriptions are `"Groceries"`, `"Power bill"` and `"Takeaway"`, in that order. They change no
figure and make the walk readable.

### The arithmetic, in cents

Net position, `payer` credited the total and each allocation debited:

| | E1 | E2 | E3 | total |
|---|---|---|---|---|
| Sam | -1000 | +8000 -2000 = +6000 | 0 | **+5000** |
| Ali | +3000 -1000 = +2000 | -6000 | +4000 -1000 = +3000 | **-1000** |
| Jo | -1000 | 0 | -3000 | **-4000** |

The three sum to zero, which `derive_balances` requires and `simplify_debts` re-validates.

Pairwise debts, the payer's own share excluded and a zero share excluded:

| pair | from | cents |
|---|---|---|
| Sam owes Ali | E1 | 1000 |
| Jo owes Ali | E1 | 1000 |
| Ali owes Sam | E2 | 6000 |
| Jo owes Ali | E3 | 3000 |

Opposing debts on one pair cancel into one entry, so the fold holds exactly two:

* **Ali owes Sam 50.00** (6000 - 1000)
* **Jo owes Ali 40.00** (1000 + 3000)
* **Sam and Jo have no pairwise debt at all.** They are never on one expense with either as payer.

### The simplified plan, and why it is deterministic

`simplify._greedy` pays the largest remaining debtor's balance to the largest remaining creditor.
Debtors are Ali at 1000 and Jo at 4000; the only creditor is Sam at 5000.

1. Jo (4000) pays Sam (5000): 4000. Jo is retired, Sam has 1000 left.
2. Ali (1000) pays Sam (1000): 1000. Both retired.

    Jo pays Sam 40.00
    Ali pays Sam 10.00

There is **no tie anywhere**: one creditor, and two debtors of different sizes. The plan is forced
by the magnitudes alone, so it does not depend on any member id, on dict insertion order, or on a
per-process string hash. Only the *order of the two rows on the wire* depends on ids, which is why
they are compared name-keyed and sorted.

**Jo pays Sam 40.00, and Jo and Sam have no pairwise debt.** That is the "why am I paying someone
I never bought anything with" case `plans/spec.md` names as the known failure mode of debt
simplification, and it is the reason these amounts were chosen rather than something rounder. A
plan whose every transfer mirrors a direct debt would prove that simplification ran and not that it
simplified.

### Known gap in what this plan can detect, stated rather than discovered

Because there is exactly one creditor, the plan is the same whichever debtor the greedy picks
first. This test therefore **does not pin the greedy's pairing rule or its tie-break**;
`tests/test_simplify.py` does, over hand-written balances and a five-member fixture. Widening this
walk to four members to cover it would make the arithmetic harder to follow, which is the one thing
this test is for. Named here so a reviewer does not read a claim the test does not make.

### Marking and confirming

**Jo's client** marks 40.00 as paid to Sam, matching the suggested transfer. **Sam's client**
confirms it. Both parties are required: `POST /api/settlements` takes the payer from the session
and `POST /api/settlements/<id>/decision` takes the decider from the session, and the payer is
refused `403 not_the_receiver` on their own claim. A smoke test that reused one client would fail,
and the failure would be the rule working.

The claimed amount equals the suggested transfer because that is what a person would do, **not
because the server checks it.** `web._create_settlement` records what happened in the world and is
never checked against the plan, and `_decide_settlement` re-checks the amount against nothing. Do
not add an assertion implying otherwise.

### After the confirmation

The confirmed settlement credits Jo 4000 and debits Sam 4000, and adds a pairwise debt from the
receiver back to the payer:

| | before | after |
|---|---|---|
| Sam net | +5000 | **+1000** |
| Ali net | -1000 | **-1000** |
| Jo net | -4000 | **0** |

Pairwise afterwards: Ali owes Sam 50.00, Jo owes Ali 40.00, **Sam owes Jo 40.00**. Debtors are Ali
at 1000; the creditor is Sam at 1000; the plan is one transfer, **Ali pays Sam 10.00**.

**Jo's balance clears and Jo's pairwise debts do not.** `simplify.py` states this outright:
settling every transfer it returns gives a `net` of exactly zero for every member, and *"It does
not empty `pairwise`: simplification converts a chain into a residual cycle, and those live debts
cancelling to zero in `net` are the visible price of netting."* The test asserts it through
`GET /api/debts/<Jo>/<Ali>`, which still answers 40.00 `owes`. Anyone who reads Jo's `0.00`
`settled` row and then "fixes" the drill-down has broken the product.

---

## The walk, step by step, with the exact figures

Every read is made by **Jo's client**, because Jo is the person the product exists to answer.
The only acts by Sam's client are entering the three expenses and confirming the payment.

Ids are read once from `GET /api/members`; `names` below is that mapping inverted, id to display
name.

**Step 0. The seeded, empty group.**

* `list(by_name(sam)) == ["Sam", "Ali", "Jo"]`
* `read_balances(jo)` has keys exactly `{"currency", "net", "transfers", "pending", "rejected"}`
* `currency == "AUD"`
* net, positionally, is `[("Sam", "0.00", "settled"), ("Ali", "0.00", "settled"), ("Jo", "0.00", "settled")]`
* `transfers == []`, `pending == []`, `rejected == []`

**Step 1. The three expenses.** Each answers `201`. For each, the returned
`expense["allocations"]`, mapped to `{display_name: amount}`, equals the resolved column of the
table above, and `expense["amount"]`, `expense["payer_id"]` and `expense["created_by"]` are as
stated. `GET /api/expenses` then answers `200` with exactly three entries, newest first, with
descriptions `["Takeaway", "Power bill", "Groceries"]`.

**Step 2. The plan before any payment.**

* net is `[("Sam", "50.00", "owed"), ("Ali", "10.00", "owes"), ("Jo", "40.00", "owes")]`
* transfers, as a sorted list of `(payer name, receiver name, amount, awaiting_confirmation)`:

      [("Ali", "Sam", "10.00", False), ("Jo", "Sam", "40.00", False)]

* `pending == []` and `rejected == []`

**Step 3. Jo marks 40.00 as paid to Sam.** `claim(jo, to_member_id=..., amount="40.00")` answers
`201` and yields a settlement id.

**Step 4. The plan while the claim is unanswered. Nothing has moved.**

* net is **identical to step 2**, asserted against the same literal rather than against a variable
  captured earlier, so the two are two claims and not one
* transfers are the same three fields as step 2, with `awaiting_confirmation` now `True` on the
  `("Jo", "Sam", "40.00")` row and `False` on the other
* `len(pending) == 1`, and that row's `id` is the settlement id from step 3, its
  `from_member_id` is Jo, its `to_member_id` is Sam, its `amount` is `"40.00"`, its `state` is
  `"pending"`, its `created_by` is Jo, and its `created_at` is `at(12).isoformat(timespec="microseconds")`
* `rejected == []`

**Step 5. Sam confirms.** `decide(sam, settlement_id, "confirmed")` answers `200`, and the body's
`settlement["state"] == "confirmed"` with `settlement["id"]` equal to the settlement id.

**Step 6. The balance has cleared.**

* net is `[("Sam", "10.00", "owed"), ("Ali", "10.00", "owes"), ("Jo", "0.00", "settled")]`
* transfers is `[("Ali", "Sam", "10.00", False)]`, so **Jo appears in no transfer**
* `pending == []` and `rejected == []`

**Step 7. The debt that netting did not delete.** `GET /api/debts/<Jo>/<Ali>`, built with the
imported `debt_path`, answers `200` with `amount == "40.00"` and `direction == "owes"`. Jo is
square with the group and still owes Ali forty dollars, which is what simplification costs.

---

## Edge cases the backlog entry does not mention, and what this task does about each

| case | decision |
|---|---|
| Leftover cents from an inexact split land on a member chosen by id, and ids are random | Every amount divides exactly. No remainder is ever assigned. |
| `transfers` is ordered by member id | Compared as a name-keyed sorted list, never by index. |
| `net` is ordered by roster insertion, which is stable | Compared positionally, and the roster order is asserted at step 0. |
| Provenance rows (`payer_debts`, `receiver_credits`) can be attributed differently on a tie | Not asserted at all. Task 13 and `tests/test_simplify.py` own them. |
| `created_at` comes from the wall clock | `web._now` is monkeypatched to `at(9)`, `at(10)`, `at(11)` for the expenses, `at(12)` for the claim and `at(13)` for the decision, so every timestamp is exact. |
| Sessions expire 30 days after login, measured with the same patched clock | Consistent, because everything reads the one patched `_now`. Do not patch it to two eras. |
| Ali is not linked to an account | Deliberate. Ali is a full member with real figures throughout. |
| The final plan's `Ali -> Sam 10.00` can be marked as paid by nobody | The accepted gap tasks 14 and 15 both record. Not acted on, not asserted, not fixed here. |
| Jo's pairwise debts survive Jo's balance clearing | Asserted at step 7. This is correct behaviour, documented in `simplify.py`. |
| The claim amount matching the suggestion | A choice about realism. The server checks no such thing, and no assertion may imply it does. |
| One client cannot both claim and confirm | Two linked clients. A `403 not_the_receiver` here would be the rule working. |
| A pending claim must move no figure | Step 4 is the assertion, against the same literal as step 2. |
| Settlement ids may need percent-encoding in a path | Handled by the imported `decide` and `debt_path`, which both call `quote`. Not asserted; task 13 and task 15 own it. |
| The group starts empty | Step 0 walks it, so a broken seed fails at the first read rather than as a confusing figure later. |

---

## What this test deliberately does not assert

A smoke test that duplicates unit coverage becomes a second place to update, and the next person
loosens whichever copy is in their way. This one asserts figures on the happy path and nothing
else. It does **not** assert:

* **Any refusal, any error status, any error code, any error message.** No `4xx`, no `5xx`, no
  `pytest.raises`. `tests/test_web_api.py` holds every refusal in the API.
* **Cookies, CSRF, session lifetime, rate limiting, security headers, content types.** Task 9a and
  `tests/test_web_api.py`.
* **Route registration, `_API_ROUTES`, `_Access`, the audit.** Task 9a, tasks 14 and 15.
* **Transfer provenance:** `payer_debts`, `receiver_credits`, `covers_whole_debt`, `debt_total`,
  or the `entries` list on the drill-down. Task 13 and `tests/test_simplify.py`.
* **The key sets of a transfer row, an expense row or a settlement row.** Tasks 12, 12a, 14, 15.
* **Byte equality of the balances payload across readers.** Task 15, criteria 41 and 43.
* **The rejection path.** Task 15. One confirmation is what the backlog asks for.
* **The remainder rule, the rotation, or any inexact split.** `tests/test_split.py`.
* **Equal across a subset.** It is `split_equally` over a shorter list, and the walk covers
  `split_equally` over the whole roster, which is the entry screen's default and the commoner act.
  A fourth expense would make this a split-mode test, which `tests/test_split.py` already is.
* **Anything about the shell, the service worker, `app/api.js` or the harness.**
* **Anything read from the store directly.** Every figure comes through the API, so there is one
  code path and one opinion. The one apparent exception is the seed, which has no endpoint.

---

## Acceptance criteria

Numbered so a QA agent can tick each yes or no by reading the result or running one command.

### The file and its name

1. `tests/test_end_to_end.py` exists and holds **exactly one** test function, named
   `test_the_whole_product_walks_from_seeding_to_a_cleared_balance`. `grep -rn "def
   test_the_whole_product_walks_from_seeding_to_a_cleared_balance" tests/` returns exactly one
   line, and no other module defines a function of that name.
2. `tests/test_smoke.py` is byte-identical to `master`. `git diff master -- tests/test_smoke.py`
   is empty, and `test_package_exposes_its_version` still collects.
3. No `conftest.py` is created anywhere in the repository, and `pyproject.toml` is unchanged.
4. The module has a docstring naming task 18 of `plans/backlog.md` and this file, in the style of
   the other test modules' docstrings, and stating in one sentence why it imports from
   `tests/test_web_api.py`.

### The import

5. `tests/test_end_to_end.py` contains exactly one `from test_web_api import (...)` statement,
   naming exactly the ten names `CHEAP`, `add_expense`, `at`, `by_name`, `claim`, `debt_path`,
   `decide`, `equal_split`, `linked_client`, `seed_group`, and no other import from any test
   module. There is no `import *`, no bare `import test_web_api`, and no conditional import.
6. No imported name begins with `test_`, so no test is collected twice. `--collect-only` shows no
   node id under `tests/test_end_to_end.py` other than the one from criterion 1.
7. No pytest fixture is imported. `store_path`, `seeded`, `app`, `client` and `secure_app` do not
   appear in `tests/test_end_to_end.py`, which builds its own store and app from `seed_group` and
   `CHEAP`.
8. `tests/test_web_api.py` gains the four comment lines quoted in "The two mitigations, both
   required", under the existing banner, and **nothing else**: `git diff master --
   tests/test_web_api.py` shows only added comment lines and no changed, moved or deleted code.
9. `tests/test_end_to_end.py` defines at most one helper of its own, `read_balances`, exactly as
   quoted above. Every other act in the walk goes through an imported helper.

### The group and the three expenses

10. The group is seeded through `seed_group` with explicit arguments
    `name="Flat 3"`, `currency="AUD"`, `members=("Sam", "Ali", "Jo")`, and not by relying on
    `test_web_api.py`'s `GROUP_NAME`, `CURRENCY` or `ROSTER` defaults.
11. Exactly two accounts are created and linked, to `Sam` and to `Jo`, each through
    `linked_client`. Ali is left unlinked, and a comment on that line says why.
12. Exactly three expenses are entered, one per wire mode, in the order `equal`, `weight`,
    `exact`, with the payers, amounts, split bodies and descriptions of the table in "The three
    expenses". Each `POST /api/expenses` answers `201`.
13. For each of the three, the `201` body's `allocations`, mapped from member id to display name,
    equals exactly `{"Sam": "10.00", "Ali": "10.00", "Jo": "10.00"}`, then
    `{"Sam": "20.00", "Ali": "60.00"}`, then `{"Ali": "10.00", "Jo": "30.00"}`. This is what makes
    "covering all three split modes" a checked claim rather than a comment.
14. `GET /api/expenses` after step 1 answers `200` with exactly three entries whose descriptions,
    in order, are `["Takeaway", "Power bill", "Groceries"]`.
15. `web._now` is monkeypatched before each of the five acts, to `at(9)`, `at(10)`, `at(11)`,
    `at(12)` and `at(13)` respectively. The module reads the wall clock nowhere.

### The figures

16. Step 0 asserts `list(by_name(sam)) == ["Sam", "Ali", "Jo"]`, that the balances payload's keys
    are exactly `{"currency", "net", "transfers", "pending", "rejected"}`, that `currency` is
    `"AUD"`, that every net row is `"0.00"` / `"settled"` in roster order, and that `transfers`,
    `pending` and `rejected` are all `[]`.
17. Step 2 asserts net, positionally and translated to display names, equals
    `[("Sam", "50.00", "owed"), ("Ali", "10.00", "owes"), ("Jo", "40.00", "owes")]`.
18. Step 2 asserts the transfer plan as a **sorted, name-keyed** list:
    `[("Ali", "Sam", "10.00", False), ("Jo", "Sam", "40.00", False)]`. It is never compared by
    index against the raw `transfers` array, and no member id is written into the assertion.
19. Step 4 asserts the net list again, against the **same literal as criterion 17**, written out a
    second time rather than captured in a variable, so "a pending claim moves no figure" is a
    claim this test makes rather than a tautology.
20. Step 4 asserts the transfer plan is unchanged in payer, receiver and amount, with
    `awaiting_confirmation` now `True` on the `("Jo", "Sam", "40.00")` row and `False` on the
    other, and asserts `rejected == []`.
21. Step 4 asserts `len(pending) == 1` and that the row's `id`, `from_member_id`, `to_member_id`,
    `amount`, `state`, `created_by` and `created_at` are exactly as listed in "Step 4", with
    `created_at` equal to `at(12).isoformat(timespec="microseconds")`.
22. Step 5 asserts the decision answers `200` with `settlement["state"] == "confirmed"` and
    `settlement["id"]` equal to the id from step 3.
23. Step 6 asserts net equals
    `[("Sam", "10.00", "owed"), ("Ali", "10.00", "owes"), ("Jo", "0.00", "settled")]`, that the
    plan is exactly `[("Ali", "Sam", "10.00", False)]`, and that `pending` and `rejected` are both
    `[]`.
24. Step 7 asserts `GET /api/debts/<Jo>/<Ali>` answers `200` with `amount == "40.00"` and
    `direction == "owes"`, and asserts nothing about its `entries` list. A comment on it names
    `simplify.py`'s sentence about `pairwise` not emptying.
25. Every amount asserted anywhere in the module is a **string literal** in
    `money.format_amount` form. The module contains no float literal, does no arithmetic on any
    amount, and never parses an amount string.
26. No member id, group id, settlement id or expense id is written as a literal anywhere in the
    module. Every id comes from a response body.
    `tests/test_groups.py::test_no_source_or_test_file_carries_a_literal_group_id` passes.

### Scope

27. `git status` shows exactly two changed files and one new file:
    `tests/test_end_to_end.py` (new), `tests/test_web_api.py` (comment only, criterion 8) and
    `plans/tasks/18-end-to-end-smoke-test.md` (this file, new). Nothing under `src/`, `scripts/`,
    `app/` or `plans/` other than this file is touched, and `CLAUDE.md`, `README.md` and
    `pyproject.toml` are unchanged.
28. `app/sw.js` is unmodified, so `SHELL_DIGEST` and `VERSION` do not move and
    `test_the_recorded_digest_matches_the_files_it_covers`,
    `test_app_holds_exactly_the_promised_files` and `test_the_worker_precaches_exactly_the_shell`
    all pass untouched.
29. The module contains no `pytest.raises`, so no `match=` pin exists to anchor. If a later change
    ever adds one, it is anchored `\A...\Z` from the start, per the scan
    `tests/test_suite_integrity.py` performs on the concurrent `task-hygiene` branch.
30. The module binds no socket, opens no port, starts no thread and spawns no subprocess. It drives
    the app through `app.test_client()` only, exactly as `tests/test_web_api.py` does.
31. No new dependency in either language. `pyproject.toml` is unchanged, no `package.json` is
    created, and neither `pip install` nor `uv pip install` is run.

### The suite

32. `uv run python -m pytest` passes with nothing skipped and nothing xfailed. Plain
    `uv run pytest` fails on this machine with an access-denied spawn error and is not the command.
33. The count reconciles exactly: `master` collects **2431**; this branch collects **2432**, one
    more, and the difference is the single test from criterion 1. Diff the two `--collect-only` id
    sets and show that the `master` set is a strict subset of this branch's: **no node id
    disappears.**
34. Every pre-existing test still passes unchanged. In particular
    `test_a_pending_settlement_moves_no_balance_over_generated_ledgers`,
    `test_a_confirmed_settlement_moves_exactly_the_amount_over_generated_ledgers`,
    `test_a_rejected_settlement_moves_no_balance_over_generated_ledgers`,
    `test_the_roster_is_the_group_in_store_order_with_two_keys_each` and
    `test_no_source_or_test_file_carries_a_literal_group_id` are green.

### It would fail if the product broke

35. **Four one-line mutations are applied, each on its own, each run, each result recorded in the
    PR body, each reverted before the next.** A criterion that still passes under its own mutation
    has not been met. `git diff` must be empty again after each revert.

    | # | mutation | the walk must go red at |
    |---|---|---|
    | M1 | In `src/splitwise_lite/balances.py::derive_balances`, delete the two lines `if states[settlement.id] is not SettlementState.CONFIRMED:` / `continue`. | **Step 4.** The unanswered claim would fold in, and Jo would already read `"0.00"` / `"settled"` before anybody confirmed anything. |
    | M2 | In `src/splitwise_lite/web.py::_decide_settlement`, replace `decision = _SETTLEMENT_DECISION_WIRE[wire]` with `decision = events.SettlementState.REJECTED`. | **Step 5 or step 6.** Jo would still read `"40.00"` / `"owes"`, `transfers` would still hold two rows, and `rejected` would hold one. |
    | M3 | In `src/splitwise_lite/split.py::split_by_weight`, change `return _allocate(total, ordered, values)` to `return _allocate(total, ordered, [1] * len(values))`, making the weight mode behave as an equal split. | **Step 1, criterion 13.** E2's allocations would be `{"Sam": "40.00", "Ali": "40.00"}` instead of `20.00` and `60.00`. |
    | M4 | In `src/splitwise_lite/balances.py::_add_debt`, change the `else` branch's `signed` from `-cents` to `cents`, so opposing debts add instead of cancelling. | **Step 2.** The Sam and Ali pair would total 7000 rather than 5000, `simplify._require_agreement` would refuse the balances, and the read would be a 500 that `read_balances` catches on the status line. |

36. M1 must also turn `test_a_pending_settlement_moves_no_balance_over_generated_ledgers` red, and
    M2 must also turn `test_a_confirmed_settlement_moves_exactly_the_amount_over_generated_ledgers`
    red. Record both. If either stays green, the mutation was not applied where it was meant to be.
37. The PR body carries the four results as four lines, each naming the mutation, the first
    assertion that failed, and the file and line the failure was reported at.

### The record

38. Every non-obvious choice made here carries a one-line comment where it is implemented, so the
    next person does not undo it by tidying: why the module is named `test_end_to_end.py` and not
    `test_smoke.py`, why it imports from `test_web_api.py` rather than restating or adding a
    conftest, why no fixture and no `test_`-prefixed name is imported, why every division is
    exact, why the transfer list is compared name-keyed and sorted while the net list is compared
    positionally, why Ali is left unlinked, why the step 4 net literal is written out twice, why
    the claim amount matching the suggestion is a choice and not a rule, and why Jo's pairwise
    debt survives Jo's balance clearing.
39. `plans/backlog.md` is not edited. This task implements what it already says, and it is the
    last numbered entry in it.

---

## Out of scope

* **The shell, in any form.** No scenario in `tests/shell_harness.mjs`, no entry in `SCENARIOS`,
  no change to `tests/test_shell_behaviour.py` or `tests/test_web_shell.py`, and no file under
  `app/`. The reason is finding 4 and the scope section: the harness stubs `fetch` and cannot
  reach a server. Bridging Node and the Flask test client is a task of its own and is not this.
* **A browser, a headless browser, Playwright, Selenium, a WSGI server or a bound port.** No new
  dependency, and no test in this repository binds a socket.
* **Shelling out to `scripts/setup_group.py`.** `tests/test_setup_group_cli.py` owns the CLI.
* **A `conftest.py`, a shared fixture module, or any refactor of `tests/test_web_api.py` beyond
  the four comment lines of criterion 8.** If the import turns out to need more than the ten
  names, stop and raise it rather than widening the surface.
* **Renaming, moving, deleting or restructuring `tests/test_smoke.py`.**
* **Any change under `src/splitwise_lite/`.** This task adds a test to a finished product. If a
  criterion appears to need a source change, that is a defect and it is a separate issue: stop and
  raise it loudly. The only source edits permitted are the four mutations of criterion 35, each of
  which is reverted.
* **Widening the walk to the rejection path, a second claim, a second group, a fourth member or a
  fourth expense.** Each is covered where it belongs, and each makes the arithmetic harder to
  follow, which is the one thing this test cannot afford.
* **Asserting anything listed under "What this test deliberately does not assert".**
* **Property tests, generated ledgers, random seeds, `hypothesis`, or reuse of `generate_ledger`
  and `LEDGER_SEED`.** They exist for a different job and are named in "The ledger, built by hand".
* **Performance, timing, or a duration assertion.** The ten-second entry target is a product
  requirement about a person and a phone, not something a test client can measure.
* **`CLAUDE.md` and `README.md`.** A test is not a capability, and neither document's
  "what works today" list changes.
* **`plans/spec.md` and `plans/backlog.md`.**
* **CI configuration.** The command is unchanged, so nothing in `.github/` moves.

## Constraints

* Files to create or modify, and nothing else: `tests/test_end_to_end.py` (new),
  `tests/test_web_api.py` (four comment lines only), and this file.
* No file is deleted. Nothing is added to or removed from `app/`, `src/` or `scripts/`.
* The test command is exactly `uv run python -m pytest`. No test is skipped or xfailed, and every
  assertion is exact rather than approximate, per `.claude/rules/testing.md`.
* **Grep before naming.** `tests/test_web_api.py` is over 6,500 lines and a duplicate definition
  silently deletes the earlier one with the suite green. It has happened twice. The new module is
  new, so a collision is only possible with an existing file name; criterion 2 is the check that
  matters here.
* Money is integer cents in the domain and a `money.format_amount` string on the wire, always.
  This test writes amounts only as strings, in the exact form `format_amount` emits, and never
  computes with one.
* Every id comes from a response body. No UUID is written down, in a comment or in code.
* All ordering is the server's. The test sorts the transfer plan **only** to make an id-ordered
  list comparable by name, and sorts nothing else; it never reverses, filters or deduplicates a
  server list.
* `web._now` is monkeypatched with `monkeypatch.setattr(web, "_now", lambda: at(N))`, the pattern
  already in `tests/test_web_api.py`. The module contains no `datetime.now`, no `time.sleep` and
  no `freeze`.
* Python style follows the surrounding test modules: `from __future__ import annotations`, type
  hints on the test signature, a module docstring, and section comments in the `# --- ... ---`
  form.
* **No new dependency of any kind, in either language.** Nothing is added to `pyproject.toml`, no
  `package.json` is created, and `.claude/hooks/guard-deps.hs.sh` blocks the ad hoc route anyway.
  Per `CLAUDE.md`, a dependency is declared then installed with `uv sync`, never `pip install` or
  `uv pip install`.
* **This file must not be modified, with one exception: a statement in it that is provably wrong
  may be corrected**, following the precedent tasks 5, 9b, 11, 13, 14 and 15 set. Sharpening a
  criterion, re-scoping one, or softening one to suit an implementation is not covered and stays
  forbidden. Every correction carries a dated marker saying what the file used to say, what it
  says now, and why.
