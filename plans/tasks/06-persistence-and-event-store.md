# Task 6: Persistence and event store

**Depends on:** 2 (complete, landed on `master`)
**Consumed by:** 7 (accounts and sessions), 9 (group and member setup), 10 (expense
entry), 11 (expense feed), 14 (mark as paid), 17 (expense correction)

Sharpened from `plans/backlog.md` task 6. The backlog entry stays as written; this file
is the implementable version.

## Goal

The ledger survives a process restart. One module owns a durable, append-only store for
users, groups, members, expense events, settlement events and settlement decisions,
where an event that goes in comes back out equal to the one that went in, expenses and
settlements can never be updated or deleted, and a group's currency can never change.
Tasks 7, 9, 10, 11, 14 and 17 read and append through this module and never write SQL of
their own.

## The storage decision

**SQLite, through the standard library `sqlite3` module. No new dependency.** This is
decided here, not left to the engineer.

The reasoning, so nobody reopens it mid-build:

* Every module in this repo so far is standard library only, and `pyproject.toml` still
  has `dependencies = []`. CLAUDE.md is explicit that dependencies are added
  deliberately and installed with `uv sync`. `sqlite3` ships with Python, so this task
  adds nothing to the lockfile and nothing to the install story.
* SQLite gives what append-only actually needs and a file format cannot: transactions,
  foreign keys, `CHECK` constraints, triggers that reject an `UPDATE` no matter who
  issues it, indexes for ordered reads, and a `busy_timeout` for two writers.
* Its `INTEGER` column is a signed 64-bit integer, which is exactly the bound
  `MAX_CENTS = 2**63 - 1` in `money.py` already enforces. Cents go in as an `int` and
  come out as an `int`, with no serialisation step that could introduce a float.
* It is one file, which suits a flat-sized ledger, and it has an in-memory mode so the
  test suite needs no fixture teardown.

Considered and rejected:

* **A JSON or JSON-lines append file.** Appending is trivially easy and everything else
  is hard: no referential integrity, no way to stop a rewrite, a full re-read to answer
  any question, and hand-rolled locking.
* **PostgreSQL.** Needs a driver dependency and a running server for the test suite. The
  product is one flat; there is nothing here SQLite cannot hold.
* **SQLAlchemy, an ORM, or Alembic.** Three dependencies to generate SQL that this task
  can write in one screen, plus a mapping layer between rows and the frozen dataclasses
  task 2 already defined. The dataclasses are the model.
* **`pickle` or `shelve`.** Stdlib, but they store Python objects rather than data: a
  refactor of `events.py` silently invalidates the archive, and there is no query.

**If implementation reveals a genuine need for a third-party package, stop and raise it
with the user before writing code.** A new dependency is the user's decision, not the
engineer's, and per CLAUDE.md it is declared in `pyproject.toml` and installed with
`uv sync`, never with `pip install` or `uv pip install`.

## The schema

Version 1, recorded in `PRAGMA user_version`. Column order mirrors the field order of
the matching type in `events.py`, so a reviewer can read the two side by side.

**`users`** (identity only; task 7 adds credentials and sessions as schema version 2)

| column | type | notes |
|---|---|---|
| `id` | TEXT | primary key |
| `email` | TEXT | not null, unique, `CHECK (email = lower(email))` |
| `display_name` | TEXT | not null, 1 to 100 characters |
| `created_at` | TEXT | not null, ISO 8601 UTC (see below) |

**`groups`**

| column | type | notes |
|---|---|---|
| `id` | TEXT | primary key |
| `name` | TEXT | not null, 1 to 100 characters |
| `currency_code` | TEXT | not null, `CHECK (currency_code GLOB '[A-Z][A-Z][A-Z]')` |
| `created_at` | TEXT | not null |

Plus `UNIQUE (id, currency_code)`, which exists solely so event tables can point a
composite foreign key at it.

**`members`**

| column | type | notes |
|---|---|---|
| `id` | TEXT | primary key |
| `group_id` | TEXT | not null, references `groups(id)` |
| `display_name` | TEXT | not null, 1 to 100 characters |
| `user_id` | TEXT | nullable, references `users(id)` |
| `created_at` | TEXT | not null |

Plus `UNIQUE (group_id, id)` for composite foreign keys, and a partial unique index on
`(group_id, user_id) WHERE user_id IS NOT NULL` so one user maps to at most one member
per group. There is no `joined_at`, no `left_at` and no `is_active`.

**`expense_events`**

| column | type | notes |
|---|---|---|
| `id` | TEXT | primary key |
| `group_id` | TEXT | not null |
| `currency_code` | TEXT | not null |
| `payer_id` | TEXT | not null |
| `total_cents` | INTEGER | not null, `CHECK (total_cents > 0)` |
| `description` | TEXT | not null, `CHECK (length(description) <= 500)` |
| `created_at` | TEXT | not null |
| `created_by` | TEXT | not null |

Foreign keys: `(group_id, currency_code)` to `groups(id, currency_code)`;
`(group_id, payer_id)` and `(group_id, created_by)` to `members(group_id, id)`.

**`expense_allocations`**

| column | type | notes |
|---|---|---|
| `expense_id` | TEXT | not null, references `expense_events(id)` |
| `position` | INTEGER | not null, `CHECK (position >= 0)` |
| `member_id` | TEXT | not null |
| `cents` | INTEGER | not null, `CHECK (cents >= 0)` |

Primary key `(expense_id, position)`, plus `UNIQUE (expense_id, member_id)`.

**`settlement_events`**

| column | type | notes |
|---|---|---|
| `id` | TEXT | primary key |
| `group_id` | TEXT | not null |
| `currency_code` | TEXT | not null |
| `from_member_id` | TEXT | not null |
| `to_member_id` | TEXT | not null, `CHECK (from_member_id <> to_member_id)` |
| `amount_cents` | INTEGER | not null, `CHECK (amount_cents > 0)` |
| `created_at` | TEXT | not null |
| `created_by` | TEXT | not null |

Same composite foreign keys as `expense_events`, plus both members.

**`settlement_decision_events`**

| column | type | notes |
|---|---|---|
| `id` | TEXT | primary key |
| `settlement_id` | TEXT | not null, references `settlement_events(id)` |
| `decision` | TEXT | not null, `CHECK (decision IN ('CONFIRMED', 'REJECTED'))` |
| `decided_by` | TEXT | not null, references `members(id)` |
| `created_at` | TEXT | not null |

`settlement_id` is **not** unique. `events.py` documents that a log may hold two
decisions for one settlement and that the earliest wins; a unique constraint would turn
that documented race into a crash and lose the second answer.

**Timestamps.** Every `created_at` is TEXT, written as
`value.isoformat(timespec="microseconds")` on a datetime the event type has already
normalised to UTC: `2026-09-03T10:00:00.000000+00:00`, always 32 characters, always
`+00:00`. Fixed width plus fixed offset is what makes byte order equal chronological
order, so `ORDER BY created_at, id` in SQL is the same total order as `ordering_key` in
Python. A `CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00')` holds that
shape.

**No upper `CHECK` on cents.** The signed 64-bit `INTEGER` column *is* the upper bound,
and it is the same bound as `MAX_CENTS`. A `CHECK (total_cents <= 9223372036854775807)`
would be a no-op. The real work is on the Python side, where a value above `MAX_CENTS`
must be rejected with a domain error instead of escaping as `OverflowError`.

## Acceptance criteria

**Storage engine and connection**

- The store is SQLite via the standard library `sqlite3`. `pyproject.toml` gains no new
  entry under `dependencies` or the `dev` group, and `uv.lock` is unchanged.
- Every table is declared `STRICT`. Without it, SQLite's type affinity will store the
  text `"12.50"` in a cents column rather than rejecting it, which is a money bug the
  database should catch rather than pass on.
- `STRICT` needs SQLite 3.37. Opening a store on an older library raises a named error
  naming `sqlite3.sqlite_version` and the required version, rather than falling back to
  loosely typed tables.
- Every connection sets `PRAGMA foreign_keys = ON` immediately after connecting and
  before any transaction, because SQLite defaults it off and it cannot be changed inside
  a transaction. A test asserts the pragma reads back as 1 on a freshly opened store.
- A file-backed store sets `PRAGMA journal_mode = WAL` so a reader is never blocked by
  the writer, and `PRAGMA busy_timeout` to a stated number of milliseconds so a second
  writer waits instead of raising immediately. An in-memory database cannot use WAL and
  must still open cleanly, so nothing asserts WAL on the in-memory store.
- `PRAGMA user_version` is 1 after a fresh store is created. Opening a database whose
  `user_version` is higher than this code knows raises a named error rather than
  reading it, so a newer schema is never half-understood.
- No `sqlite3` type adapters or converters are registered and `detect_types` is not
  used. Python 3.12 deprecated the default datetime adapters; this store converts
  datetimes itself. The suite raises no `DeprecationWarning` from `sqlite3`.
- Only `str`, `int` and `None` are ever bound to a query parameter. A `float` reaching
  the store raises `TypeError` rather than being silently accepted by SQLite's lossless
  float-to-integer conversion.
- Every statement uses bound parameters. No value is ever interpolated into SQL with an
  f-string or `%`.

**Records and API surface**

- `store.py` defines `User`, `Group` and `Member` as frozen slotted dataclasses, matching
  the schema above. Task 2 deliberately left these aggregates to tasks 6, 7 and 9.
- `UserId` is declared in `store.py` as a `NewType` over `str`, alongside the id types
  `events.py` already exports. `events.py` is not edited to add it.
- `Group.currency` is a `Currency`, not a string. A stored code is always three
  uppercase letters, so `Currency` construction on read can never fail.
- Writes are `add_user`, `add_group`, `add_member`, `append_expense`,
  `append_settlement` and `append_settlement_decision`. The naming split is deliberate:
  `add_` for the reference tables, `append_` for the log that can only grow.
- Reads are `get_user`, `get_group`, `list_groups`, `get_member`, `list_members`,
  `get_expense`, `list_expenses`, `list_settlements`, `list_settlement_decisions` and
  `list_events`.
- `list_events(group_id)` returns every expense, settlement and decision for that group
  as a `tuple[LedgerEvent, ...]` in `ordering_key` order. Decision events reach their
  group through the settlement they reference, since they carry no `group_id` of their
  own.
- Every read returns a domain object or a tuple of them. No public method returns a row,
  a tuple of columns, a dict or a `sqlite3.Row`.
- There is no `execute`, `raw`, `sql` or `connection` on the public surface. A caller
  cannot reach past the store to write its own statement.
- The store never reads the clock. `created_at` always comes from the object being
  written, and no column carries a `DEFAULT CURRENT_TIMESTAMP`, so two identical test
  runs produce byte-identical databases.
- The store never chooses a path. `open_store` takes one, and there is no default
  filename, no environment variable and no implicit working-directory file.

**Append-only**

- `expense_events`, `expense_allocations`, `settlement_events` and
  `settlement_decision_events` each carry a `BEFORE UPDATE` and a `BEFORE DELETE`
  trigger that calls `RAISE(ABORT, ...)` with a message naming the table. Enforcement
  lives in the database, so a raw statement from any tool or any future task fails too.
- A test issues a raw `UPDATE` and a raw `DELETE` against each of the four tables and
  asserts `sqlite3.IntegrityError` is raised and the row count is unchanged. This is the
  criterion that fails if append-only is only a naming convention on the Python methods.
- No public method updates or deletes an event, and the module contains no `UPDATE`,
  `DELETE`, `INSERT OR REPLACE`, `INSERT OR IGNORE` or `ON CONFLICT DO UPDATE` statement
  against those four tables.
- Appending an event whose id already exists raises a named duplicate error, leaves the
  existing row byte-identical, and creates no second row. An upsert here would be a
  silent edit of history.
- No event table has an `updated_at`, `version`, `is_deleted`, `is_void` or `revision`
  column. Correction is task 17 appending a new event, and it must be able to do that by
  adding a table rather than by altering one.
- No table stores a balance, a net position or a running total. The spec's resolution to
  the netting-versus-audit conflict is that balances are always derived.

**Currency immutability**

- A group's `currency_code` is set at creation and can never change. A `BEFORE UPDATE OF
  currency_code ON groups` trigger aborts every attempt, whether or not the group has
  expenses yet.
- This is stricter than the spec's "immutable once the first expense lands" and matches
  the spec's locked decision, "one currency per group, fixed at creation". The stricter
  rule satisfies both and removes a conditional from the trigger.
- A test updates `groups.currency_code` with raw SQL and asserts it is rejected, then
  asserts the group still reads back with its original currency.
- Appending an expense or settlement whose `currency` differs from its group's raises
  `CurrencyMismatch` from `money.py`, and the message names both codes.
- The same disagreement is impossible at the schema level, not only in Python: a raw
  `INSERT` of an event row with a foreign currency code is rejected by the composite
  foreign key to `groups(id, currency_code)`. A test proves the raw path is rejected too.
- A group's name may be changed by a later task; only the currency is trigger-locked.

**Multi-group and flat membership**

- Every event table carries `group_id` and every read is scoped by it. There is no
  singleton group table, no hardcoded group id, no `get_the_group()` and no column or
  code path that assumes exactly one group exists.
- A test creates two groups with different currencies, appends expenses to both, and
  asserts each group's reads return only its own events and its own members.
- An expense whose `payer_id`, `created_by` or any allocation member belongs to a
  different group is rejected, and the rejection is enforced by the database rather than
  by a Python check alone. Cross-group contamination is the failure mode that would make
  every balance in both groups wrong.
- Members are a flat list. There is no `joined_at`, `left_at`, `is_active` or membership
  interval table, and no event is scoped to who was present at the time. **This is a
  locked constraint**, from assumption 2 in the backlog and open question 1 in the spec:
  the spec cuts member departure from v1. Do not add dated membership "while we are in
  here"; it changes every read in tasks 4, 5, 11 and 12.
- A member row may exist with `user_id` NULL, because task 9 populates members from a
  manual list before those people have accounts.
- Two member rows in the same group cannot point at the same user. A test asserts the
  second link is rejected.
- A member may share a display name with another member in the same group. Two flatmates
  called Sam is a real situation, and ids are what distinguish them.
- A group with no members yet is legal, and `list_members` returns an empty tuple for it.

**Round trip**

- An `ExpenseEvent` written with `append_expense` and read back with `get_expense`
  compares equal to the original with `==`, including its allocations tuple. The same
  holds for `SettlementEvent` and `SettlementDecisionEvent`.
- Allocations come back in the exact order they were written, not re-sorted. `ExpenseEvent`
  does not require sorted allocations, so tuple order is part of the value, and the
  `position` column is what preserves it. A test writes allocations in descending member
  id order and asserts the loaded tuple is in that same descending order.
- A zero-cent allocation round trips and is never dropped. Task 3 produces `1, 1, 0` for
  2 cents across 3 people, and a `WHERE cents > 0` anywhere would silently lose a
  participant.
- An expense whose payer is not among the allocations round trips. Task 4 tests that
  case, so no constraint may link payer to participants.
- An empty description round trips as `""`, never as `None`. The column is `NOT NULL`,
  and nothing coerces empty text to NULL on the way in or out.
- A description containing emoji, non-Latin script and a newline round trips byte for
  byte. The 500-character cap counts characters, which is what SQLite's `length()` does
  on TEXT.
- An expense with a single allocation equal to the total round trips.
- `total_cents = MAX_CENTS` with one allocation of `MAX_CENTS` round trips exactly equal,
  proving the cents column is a true 64-bit integer and nothing along the path narrows or
  converts it.
- An event whose `total_cents`, allocation `cents` or `amount_cents` exceeds `MAX_CENTS`
  is rejected with a named store error naming the field and the bound. `OverflowError`
  from `sqlite3` never escapes the store, and the failed append leaves no rows behind.
- `created_at` round trips as an equal timezone-aware datetime. A test builds an event
  with a `+10:00` timestamp, notes that the event type normalises it to UTC, and asserts
  the loaded value equals the constructed one and that the stored text ends `+00:00`.
- A timestamp whose microsecond is 0 stores as `...T10:00:00.000000+00:00`, six digits
  and all. Variable-width fractional seconds would break byte ordering, so the stored
  text is asserted against a fixed pattern in a test.
- Loading constructs real domain objects, so every task 2 invariant is re-checked on
  read. A hand-edited database whose allocations no longer sum to `total_cents` surfaces
  as `InvalidEvent` at load time rather than as a quietly wrong balance.
- Allocations are rows in a child table, not a JSON column, a pickled blob or a
  delimited string. Task 4 folds by member and task 13 drills down by member, and both
  need to query them.

**Ordering**

- `list_expenses`, `list_settlements`, `list_settlement_decisions` and `list_events`
  return events in ascending `(created_at, id)` order, matching `ordering_key`.
- A test writes several events that share one identical `created_at`, in shuffled id
  order, and asserts the read order equals `sorted(events, key=ordering_key)`. This is
  the criterion that fails if timestamps are stored in a variable-width format.
- Named indexes exist: `idx_expense_events_group_order` on
  `expense_events(group_id, created_at, id)`,
  `idx_settlement_events_group_order` on `settlement_events(group_id, created_at, id)`,
  `idx_settlement_decisions_settlement_order` on
  `settlement_decision_events(settlement_id, created_at, id)`,
  `idx_expense_allocations_member` on `expense_allocations(member_id)`, and
  `idx_members_group` on `members(group_id)`.
- A test runs `EXPLAIN QUERY PLAN` for the ordered expense read and the ordered
  settlement read and asserts the plan names the index and contains no
  `USE TEMP B-TREE FOR ORDER BY`. An index that does not actually serve the sort is not
  an index.
- Reads are ascending. Task 11's reverse-chronological feed reverses in Python; the store
  has one order.

**Settlements and decisions**

- Two decision events for the same settlement can both be appended and both come back,
  in ordering-key order. The store applies no earliest-wins rule and rejects no
  duplicate: resolving conflicting decisions is a read-model concern owned by tasks 4
  and 15, and the log's job is to keep both.
- A decision event whose `settlement_id` names no settlement is rejected.
- A decision whose `created_at` is earlier than its settlement's is accepted. Phone
  clocks disagree, and refusing a real recorded payment because of skew is worse than
  storing it. This is a decision, not an oversight.
- A decision with `SettlementState.PENDING` cannot be constructed by `events.py` and is
  additionally impossible in the schema by `CHECK`.
- The store checks nothing about who is entitled to confirm. That rule belongs to task 15.

**Errors and the empty database**

- Every store error subclasses a `StoreError`, which subclasses `DomainError` from
  `money.py`, so task 10 still maps one exception family to one HTTP response.
- No `sqlite3` exception escapes a public method. Each is caught and re-raised as a
  `StoreError` subclass with the original attached as `__cause__` via `raise ... from`.
  The exceptions are the raw-SQL tests above, which deliberately go around the API.
- A read for an id that does not exist raises a not-found error naming the id, rather
  than returning `None`. A `None` folded into a balance is a wrong number; an exception
  is a bug report.
- A list read scoped to a group id that does not exist raises the same not-found error
  rather than returning an empty tuple. A typo in a group id must not read as "this
  group has spent nothing".
- A list read for a group that exists and has no events returns an empty tuple. Empty is
  a legitimate state, not an error, and this is the first thing task 12 renders.
- Opening a store on a path whose parent directory does not exist raises a store error
  naming the path. The store does not create directories.
- Opening a path that exists but is not a SQLite database raises a store error naming the
  path, not a bare `sqlite3.DatabaseError`.
- Opening a pre-existing zero-byte file succeeds and treats it as a fresh database, which
  is what SQLite does. A test covers it, because `touch`ing a file is a normal thing for
  a deployment script to do.
- Using a closed store raises a named error. `close()` is idempotent, and the store works
  as a context manager that closes on exit, including on an exception.

**Transactions, durability and concurrency**

- Appending an expense writes the parent row and every allocation row in one
  transaction, opened with `BEGIN IMMEDIATE` and rolled back on any exception.
- A failed append leaves nothing behind. A test appends an expense that violates a
  constraint part-way through and asserts both `expense_events` and `expense_allocations`
  hold zero rows for that id.
- A file store's data survives close and reopen. A test writes events, closes the store,
  opens a new store on the same path and asserts the events read back equal.
- Two stores opened on the same file can both append, and every event from both is
  readable afterwards in one total order. A test proves it with two live connections.
- Opening the same fresh file from two stores ends with one valid schema and no error
  from either.
- Reopening an existing store does not re-run destructive DDL, does not duplicate a
  table and does not wipe data.

**Suite**

- New tests live in `tests/test_store.py` and cover every criterion above.
- The round-trip and constraint tests run against both an in-memory store and a
  file-backed store under `tmp_path`, from one parametrized fixture and one test body, so
  no behaviour can pass only under memory semantics.
- Assertions on cents are exact integer comparisons, never approximate, per
  `.claude/rules/testing.md`. No test is skipped or xfailed.
- `uv run python -m pytest` passes. Every test already on `master` keeps passing
  unchanged.

## Out of scope

- Balance derivation, the earliest-decision-wins fold, and debt simplification. Tasks 4
  and 5 read events out of this store and fold them; the store never interprets them.
- Password hashing, session tokens, login lookups such as `get_user_by_email`, and
  linking a signed-in user to a member. Task 7 owns all of it and adds its own tables as
  schema version 2. Task 6 creates the `users` table's identity columns and stops there.
- Creating the real group, seeding real members, and any group or member management flow.
  Task 9.
- Correction and void events. Task 17 adds a new table; it must not need a column change
  here, and this task must not add one in anticipation.
- Pagination, filtering, search, date-range reads and full-text indexing. A flat's ledger
  is small enough to read whole, and task 11 reverses in Python. If a later task needs a
  limit, it adds one then.
- Any HTTP, CLI or UI surface, and any request-scoped session or connection pool.
- A repository interface, an abstract base class, a swappable backend or dependency
  injection. One concrete class over one concrete database.
- A migration framework or a versioned migration directory. `PRAGMA user_version` plus
  one schema string is the whole mechanism at version 1. Task 7 extends it.
- Async, threading and multiprocessing support. See the constraint below.
- Backups, replication, encryption at rest, and any right-to-erasure story. Deleting a
  person from an append-only ledger is a real question and it is not this task's.
- Durability tuning beyond WAL and `busy_timeout`, benchmarking, and any performance work
  beyond the named indexes.
- Multi-currency, exchange rates, or a currency-exponent table. One group, one currency,
  two minor units, per `MINOR_UNITS` in `money.py`.
- Storing `Money` as a single value. Amounts are a cents column plus the group's currency;
  there is no serialised money type and `format_amount` never touches the store.
- Storing balances, net positions or any cached total. The spec forbids it outright.

## Constraints

- Files to create: `src/splitwise_lite/store.py` (records, errors, schema SQL and the
  store class) and `tests/test_store.py`. `src/splitwise_lite/__init__.py` may re-export
  the new public names, following the precedent tasks 2 and 3 set, but `__version__` must
  keep its current value because `tests/test_smoke.py` asserts it.
- **`src/splitwise_lite/events.py` and `src/splitwise_lite/money.py` must not be
  modified.** Their types are mirrored into the schema, never reshaped to suit it. If a
  criterion here seems to need a field added, a validation relaxed or a private helper
  exported, stop and raise it. The same goes for `split.py`, `plans/backlog.md`,
  `plans/spec.md`, `CLAUDE.md` and this file.
- `store.py` imports only public names from `events.py` and `money.py`. The
  underscore-prefixed validators in those modules are not part of the contract, so
  `store.py` writes its own small validators for the record types it defines.
- Dependency direction stays one way: `store.py` imports from `events.py` and `money.py`,
  and neither of them learns that a store exists.
- **No new dependency.** `sqlite3`, `dataclasses`, `datetime`, `pathlib`, `typing` and,
  in the tests, `pytest` cover everything described here. Do not add SQLAlchemy, Alembic,
  a database driver, `pydantic` or an id library. If implementation genuinely needs one,
  stop and get the user's approval first, then declare it in `pyproject.toml` and run
  `uv sync`, never `pip install` or `uv pip install`.
- Python 3.12 target. Frozen slotted dataclasses for the record types, validating in
  `__post_init__`, matching task 2's shape exactly.
- Integer cents everywhere. No `float` in the store path: no `float()`, no `/` true
  division, no `round()`, and no float bound to a parameter. Per CLAUDE.md, money is
  parsed at the input edge and formatted only for display, and neither happens here.
- All DDL lives in one module-level SQL string in `store.py`, applied with
  `executescript` at open. No `.sql` data file, no schema spread across functions.
- The store is not thread-safe and does not claim to be. One `EventStore` owns one
  connection; concurrent use means one store per thread or per process. State it in the
  class docstring, and do not add a lock, a pool or a module-level singleton.
- Every public class and method gets a docstring stating the invariant it enforces and,
  where it mirrors one, naming the task 2 rule it mirrors. Tasks 7, 9, 10, 11, 14 and 17
  are written against these docstrings.
- Tests run with `uv run python -m pytest`. Plain `uv run pytest` fails on this machine
  with an access-denied spawn error.
