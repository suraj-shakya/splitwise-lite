"""Persistence: a durable, append-only store for the ledger and the records it needs.

The ledger is the product, so the store's whole job is to hand back exactly what was
written. An event that goes in comes back out equal to the one that went in, an event
can never be updated or deleted, and a group's currency can never change.

**SQLite, through the standard library.** Nothing here is a dependency. SQLite gives
what append-only actually needs and a flat file cannot: transactions, foreign keys,
``CHECK`` constraints, triggers that reject an ``UPDATE`` no matter who issued it,
indexes that serve an ordered read, and a busy timeout so a second writer waits instead
of failing. Its ``INTEGER`` column is a signed 64-bit integer, which is exactly the
``MAX_CENTS`` bound ``money.py`` already enforces, so cents go in as an ``int`` and come
back as an ``int`` with no serialisation step in between that could introduce a float.

**Append-only is enforced by the database, not by naming.** Every event table carries a
``BEFORE UPDATE`` and a ``BEFORE DELETE`` trigger that aborts, so a statement from a
future task, a migration script or a database shell fails the same way a mistake in this
module would. The Python API simply has no method that could ask for either.

**Every table is ``STRICT``.** Without it SQLite's type affinity happily stores the text
``"12.50"`` in a cents column. That is a money bug, and the database is the right place
to catch it rather than pass it on.

**Timestamps are fixed-width UTC text.** Every ``created_at`` is written as
``value.isoformat(timespec="microseconds")`` on a UTC datetime:
``2026-09-03T10:00:00.000000+00:00``, always 32 characters, always ``+00:00``. Fixed
width plus a fixed offset is what makes byte order equal chronological order, so
``ORDER BY created_at, id`` in SQL is the same total order as ``ordering_key`` in
``events.py``. A ``CHECK`` on every such column holds that shape.

**Nothing derived is stored.** No balance, no net position, no running total, and no
state column on a settlement. Those are folded out of the events by later tasks, which
is the spec's resolution to the netting-versus-audit conflict.

The schema is version 1, recorded in ``PRAGMA user_version``. Column order mirrors the
field order of the matching type in ``events.py`` so the two can be read side by side.
The ``CHECK`` constraints are a superset of the ones the task spec tabulates: ids and
emails are additionally required to be non-empty, which strengthens the schema and
weakens nothing.

Dependency direction: this module imports from ``events`` and ``money``; neither of them
knows a store exists.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Iterator, NewType

from .events import (
    Allocation,
    ExpenseEvent,
    ExpenseId,
    GroupId,
    LedgerEvent,
    MemberId,
    SettlementDecisionEvent,
    SettlementEvent,
    SettlementId,
    SettlementState,
    ordering_key,
)
from .money import MAX_CENTS, Currency, CurrencyMismatch, DomainError

__all__ = [
    "BUSY_TIMEOUT_MS",
    "IN_MEMORY",
    "MIN_SQLITE_VERSION",
    "SCHEMA_VERSION",
    "AmountTooLarge",
    "CannotOpenStore",
    "ConstraintViolated",
    "DuplicateRecord",
    "EventStore",
    "Group",
    "InvalidRecord",
    "Member",
    "RecordNotFound",
    "StorageFailed",
    "StoreClosed",
    "StoreError",
    "UnsupportedSQLiteVersion",
    "UnsupportedSchemaVersion",
    "User",
    "UserId",
    "open_store",
]

UserId = NewType("UserId", str)
"""Identifies a user account. Declared here rather than in ``events.py`` because no
event references a user: events are between members, and a member may exist with no
account at all. Like the id types in ``events.py`` it is a ``str`` at runtime."""

SCHEMA_VERSION: Final[int] = 1
"""The schema this module writes and understands, held in ``PRAGMA user_version``.

Task 7 raises it to 2 when it adds credentials and sessions. A database at a higher
version is refused rather than half-understood.
"""

MIN_SQLITE_VERSION: Final[tuple[int, int, int]] = (3, 37, 0)
"""First SQLite release with ``STRICT`` tables. Below it the store refuses to open."""

BUSY_TIMEOUT_MS: Final[int] = 5000
"""Milliseconds a second writer waits for the lock before giving up.

The value is spelled out again as a literal in ``_CONNECTION_PRAGMAS`` because a
``PRAGMA`` takes no bound parameter and this module interpolates nothing into SQL. A
test asserts the pragma reads back equal to this constant, so the two cannot drift.
"""

IN_MEMORY: Final[str] = ":memory:"
"""Path value for a private in-memory database. Used by the test suite, which needs no
fixture teardown, and never by the application, which always names a real file."""

_TIMESTAMP_LENGTH: Final[int] = 32
"""Characters in an encoded timestamp: ``2026-09-03T10:00:00.000000+00:00``."""

_MAX_NAME_LENGTH: Final[int] = 100
"""Cap on ``display_name`` and group ``name``, matching the schema's ``CHECK``."""


class StoreError(DomainError):
    """Base class for every error the store raises.

    A subclass of ``DomainError`` so the HTTP layer in task 10 still maps one exception
    family to one response. No ``sqlite3`` exception escapes a public method: each is
    caught and re-raised as one of these with the original attached as ``__cause__``.
    """


class CannotOpenStore(StoreError):
    """Raised when a path cannot be opened as a store, naming the path.

    Covers a missing parent directory, which the store will not create, and a file that
    exists but is not a SQLite database. A bare ``sqlite3.DatabaseError`` never reaches
    the caller.
    """


class UnsupportedSQLiteVersion(StoreError):
    """Raised when the linked SQLite library is older than ``MIN_SQLITE_VERSION``.

    ``STRICT`` tables are the reason for the floor. Falling back to loosely typed tables
    would silently give up the type checking the money columns depend on, so the store
    refuses to open instead.
    """


class UnsupportedSchemaVersion(StoreError):
    """Raised when a database's ``user_version`` is newer than this code understands."""


class StoreClosed(StoreError):
    """Raised when a method is called on a store whose connection has been closed."""


class InvalidRecord(StoreError):
    """Raised when a ``User``, ``Group`` or ``Member`` would break an invariant.

    The record equivalent of ``InvalidEvent``. A wrong Python type raises ``TypeError``
    instead: that is a programming error, not rejected input.
    """


class RecordNotFound(StoreError):
    """Raised when a read names an id the store does not hold, naming that id.

    A read never returns ``None``. A ``None`` folded into a balance is a wrong number
    and travels a long way before anyone notices; an exception is a bug report. A list
    read scoped to an unknown id raises this too, rather than returning an empty tuple,
    so a typo cannot read as "this group has spent nothing".
    """


class DuplicateRecord(StoreError):
    """Raised when a write would reuse an id, an email or a group's link to a user.

    Appending an event whose id already exists lands here, and the existing row is left
    exactly as it was. Nothing in this module upserts: an upsert on an event table is a
    silent edit of history.
    """


class ConstraintViolated(StoreError):
    """Raised when the database rejects a write, wrapping ``sqlite3.IntegrityError``.

    A foreign key to another group's member, a cross-currency event, a description over
    the column's cap, an attempt to update or delete an event: the database is what
    catches these, and this is how the caller sees them.
    """


class AmountTooLarge(StoreError):
    """Raised when a cent value would not fit the signed 64-bit column, naming both.

    ``events.py`` puts no upper bound on an amount, and ``parse_amount`` only guards the
    values that arrive as text, so an event built from cents directly can carry more
    than ``MAX_CENTS``. SQLite answers that with ``OverflowError``, which says nothing
    about which field was wrong; this says the field and the bound, and the append that
    raised it leaves no rows behind.
    """


class StorageFailed(StoreError):
    """Raised when SQLite fails for any other reason, wrapping ``sqlite3.Error``.

    The catch-all that keeps the promise that no ``sqlite3`` exception escapes a public
    method. The original is always attached as ``__cause__``.
    """


# --- Validation -------------------------------------------------------------
#
# store.py imports only public names from events.py and money.py, so the record types
# below carry their own validators rather than reaching for the underscore-prefixed
# ones next door. The rules are the same rules, deliberately.


def _require_id(value: object, field: str) -> str:
    """Return ``value`` if it is a non-empty ``str``, else raise."""
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a str, got {type(value).__name__}: {value!r}")
    if not value:
        raise InvalidRecord(f"{field} must be a non-empty id")
    return value


def _require_name(value: object, field: str) -> str:
    """Return ``value`` stripped, if it is 1 to 100 characters once stripped.

    Stripped rather than rejected for surrounding whitespace, matching how
    ``ExpenseEvent`` treats a description, so ``" Sam "`` and ``"Sam"`` cannot coexist
    as two different-looking members.
    """
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a str, got {type(value).__name__}: {value!r}")
    stripped = value.strip()
    if not stripped:
        raise InvalidRecord(f"{field} must not be blank")
    if len(stripped) > _MAX_NAME_LENGTH:
        raise InvalidRecord(
            f"{field} must be at most {_MAX_NAME_LENGTH} characters, got "
            f"{len(stripped)}"
        )
    return stripped


def _require_email(value: object, field: str) -> str:
    """Return ``value`` if it is a non-empty, already-lowercase ``str``.

    Lowercase is required rather than applied, for the reason ``Currency`` rejects a
    lowercase code: one canonical spelling in the store means the unique index actually
    means "one account per address". Nothing beyond case and emptiness is checked here;
    task 7 owns what a valid address is.
    """
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a str, got {type(value).__name__}: {value!r}")
    if not value:
        raise InvalidRecord(f"{field} must not be empty")
    if value != value.lower():
        raise InvalidRecord(f"{field} must be lowercase, got {value!r}")
    return value


def _require_utc(value: object, field: str) -> datetime:
    """Return ``value`` converted to UTC, else raise.

    Mirrors the rule in ``events.py``: a naive datetime is rejected rather than assumed
    to be local or UTC, because guessing silently reorders the log for anyone in another
    timezone.
    """
    if not isinstance(value, datetime):
        raise TypeError(
            f"{field} must be a datetime, got {type(value).__name__}: {value!r}"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidRecord(f"{field} must be timezone-aware, got naive {value!r}")
    return value.astimezone(timezone.utc)


def _encode_timestamp(value: datetime) -> str:
    """Render a timezone-aware datetime as fixed-width UTC text.

    Always 32 characters and always ``+00:00``, so byte order equals chronological
    order and ``ORDER BY created_at, id`` matches ``ordering_key``. Six fractional
    digits are always written, even when the microsecond is zero, because a
    variable-width fraction would break that ordering.
    """
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _decode_timestamp(text: str) -> datetime:
    """Parse stored timestamp text back into a timezone-aware UTC datetime."""
    return datetime.fromisoformat(text)


def _require_storable_cents(value: object, field: str) -> int:
    """Return ``value`` if it is an ``int`` that fits the cents column, else raise.

    The column is a signed 64-bit ``INTEGER``, which is the same bound ``MAX_CENTS``
    names, so this check and the database agree by construction. It runs before the
    transaction opens, so a rejected amount never starts a write.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an int, got {type(value).__name__}: {value!r}")
    if value > MAX_CENTS:
        raise AmountTooLarge(
            f"{field} is {value}, above MAX_CENTS ({MAX_CENTS}), the largest value the "
            f"cents column can hold"
        )
    return value


def _params(*values: object) -> tuple[str | int | None, ...]:
    """Return ``values`` if every one of them is bindable, else raise ``TypeError``.

    Only ``str``, ``int`` and ``None`` are ever bound. A ``float`` is refused here
    rather than handed to SQLite, which would accept ``12.0`` into an ``INTEGER``
    column by lossless conversion and turn a float that should never have existed into
    a plausible-looking cent value. ``bool`` is refused for the same reason
    ``Money`` refuses it: no column in this schema is a flag.
    """
    for value in values:
        if value is None or isinstance(value, str):
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            continue
        raise TypeError(
            f"only str, int and None may be bound to a statement, got "
            f"{type(value).__name__}: {value!r}"
        )
    return values  # type: ignore[return-value]


# --- Records ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class User:
    """A person with an account, as far as this task is concerned: identity only.

    Invariants:

    * ``id`` is a non-empty ``str``.
    * ``email`` is non-empty and already lowercase, and is unique across the store.
    * ``display_name`` is 1 to 100 characters once surrounding whitespace is stripped.
    * ``created_at`` is timezone-aware and normalised to UTC.

    Credentials, sessions and login lookups are task 7's, which adds them as schema
    version 2. Nothing here hashes or stores a password.
    """

    id: UserId
    email: str
    display_name: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_id(self.id, "User id")
        object.__setattr__(self, "email", _require_email(self.email, "User email"))
        object.__setattr__(
            self, "display_name", _require_name(self.display_name, "User display_name")
        )
        object.__setattr__(
            self, "created_at", _require_utc(self.created_at, "User created_at")
        )


@dataclass(frozen=True, slots=True)
class Group:
    """A group whose members share expenses in exactly one currency.

    Invariants:

    * ``id`` is a non-empty ``str``.
    * ``name`` is 1 to 100 characters once stripped.
    * ``currency`` is a ``Currency``, not a code string, so a stored group hands back
      the same type an event carries and the two can be compared directly.
    * ``created_at`` is timezone-aware and normalised to UTC.

    The currency is fixed at creation and a database trigger refuses every attempt to
    change it, expenses or no expenses. That is stricter than the spec's "immutable
    once the first expense lands" and matches its locked decision, "one currency per
    group, fixed at creation".
    """

    id: GroupId
    name: str
    currency: Currency
    created_at: datetime

    def __post_init__(self) -> None:
        _require_id(self.id, "Group id")
        object.__setattr__(self, "name", _require_name(self.name, "Group name"))
        if not isinstance(self.currency, Currency):
            raise TypeError(
                f"Group currency must be a Currency, got "
                f"{type(self.currency).__name__}: {self.currency!r}"
            )
        object.__setattr__(
            self, "created_at", _require_utc(self.created_at, "Group created_at")
        )


@dataclass(frozen=True, slots=True)
class Member:
    """One participant in one group. Events name members, never users.

    Invariants:

    * ``id`` and ``group_id`` are non-empty strings.
    * ``display_name`` is 1 to 100 characters once stripped. Two members of one group
      may share a display name: two flatmates called Sam is a real situation, and the
      ids are what tell them apart.
    * ``user_id`` is ``None`` or a non-empty ``str``. ``None`` is normal, because task 9
      seeds members from a manual list before those people have accounts. At most one
      member per group may point at any given user.
    * ``created_at`` is timezone-aware and normalised to UTC.

    Membership is a flat list. There is no ``joined_at``, ``left_at`` or ``is_active``
    and no membership interval: the spec cuts member departure from v1, and dating
    membership would change every read in tasks 4, 5, 11 and 12.
    """

    id: MemberId
    group_id: GroupId
    display_name: str
    user_id: UserId | None
    created_at: datetime

    def __post_init__(self) -> None:
        _require_id(self.id, "Member id")
        _require_id(self.group_id, "Member group_id")
        object.__setattr__(
            self,
            "display_name",
            _require_name(self.display_name, "Member display_name"),
        )
        if self.user_id is not None:
            _require_id(self.user_id, "Member user_id")
        object.__setattr__(
            self, "created_at", _require_utc(self.created_at, "Member created_at")
        )


# --- Schema -----------------------------------------------------------------

_SCHEMA_SQL: Final[str] = """
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS users (
    id           TEXT NOT NULL PRIMARY KEY,
    email        TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    CHECK (length(id) > 0),
    CHECK (length(email) > 0),
    CHECK (email = lower(email)),
    CHECK (length(display_name) BETWEEN 1 AND 100),
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00')
) STRICT;

CREATE TABLE IF NOT EXISTS groups (
    id            TEXT NOT NULL PRIMARY KEY,
    name          TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE (id, currency_code),
    CHECK (length(id) > 0),
    CHECK (length(name) BETWEEN 1 AND 100),
    CHECK (currency_code GLOB '[A-Z][A-Z][A-Z]'),
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00')
) STRICT;

CREATE TABLE IF NOT EXISTS members (
    id           TEXT NOT NULL PRIMARY KEY,
    group_id     TEXT NOT NULL REFERENCES groups (id),
    display_name TEXT NOT NULL,
    user_id      TEXT REFERENCES users (id),
    created_at   TEXT NOT NULL,
    UNIQUE (group_id, id),
    CHECK (length(id) > 0),
    CHECK (length(group_id) > 0),
    CHECK (length(display_name) BETWEEN 1 AND 100),
    CHECK (user_id IS NULL OR length(user_id) > 0),
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00')
) STRICT;

CREATE TABLE IF NOT EXISTS expense_events (
    id            TEXT NOT NULL PRIMARY KEY,
    group_id      TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    payer_id      TEXT NOT NULL,
    total_cents   INTEGER NOT NULL,
    description   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    CHECK (length(id) > 0),
    CHECK (total_cents > 0),
    CHECK (length(description) <= 500),
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00'),
    FOREIGN KEY (group_id, currency_code) REFERENCES groups (id, currency_code),
    FOREIGN KEY (group_id, payer_id) REFERENCES members (group_id, id),
    FOREIGN KEY (group_id, created_by) REFERENCES members (group_id, id)
) STRICT;

CREATE TABLE IF NOT EXISTS expense_allocations (
    expense_id TEXT NOT NULL REFERENCES expense_events (id),
    position   INTEGER NOT NULL,
    member_id  TEXT NOT NULL REFERENCES members (id),
    cents      INTEGER NOT NULL,
    PRIMARY KEY (expense_id, position),
    UNIQUE (expense_id, member_id),
    CHECK (position >= 0),
    CHECK (cents >= 0)
) STRICT;

CREATE TABLE IF NOT EXISTS settlement_events (
    id             TEXT NOT NULL PRIMARY KEY,
    group_id       TEXT NOT NULL,
    currency_code  TEXT NOT NULL,
    from_member_id TEXT NOT NULL,
    to_member_id   TEXT NOT NULL,
    amount_cents   INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    created_by     TEXT NOT NULL,
    CHECK (length(id) > 0),
    CHECK (from_member_id <> to_member_id),
    CHECK (amount_cents > 0),
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00'),
    FOREIGN KEY (group_id, currency_code) REFERENCES groups (id, currency_code),
    FOREIGN KEY (group_id, from_member_id) REFERENCES members (group_id, id),
    FOREIGN KEY (group_id, to_member_id) REFERENCES members (group_id, id),
    FOREIGN KEY (group_id, created_by) REFERENCES members (group_id, id)
) STRICT;

CREATE TABLE IF NOT EXISTS settlement_decision_events (
    id            TEXT NOT NULL PRIMARY KEY,
    settlement_id TEXT NOT NULL REFERENCES settlement_events (id),
    decision      TEXT NOT NULL,
    decided_by    TEXT NOT NULL REFERENCES members (id),
    created_at    TEXT NOT NULL,
    CHECK (length(id) > 0),
    CHECK (decision IN ('CONFIRMED', 'REJECTED')),
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00')
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_members_group_user
    ON members (group_id, user_id) WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_members_group
    ON members (group_id);

CREATE INDEX IF NOT EXISTS idx_expense_events_group_order
    ON expense_events (group_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_expense_allocations_member
    ON expense_allocations (member_id);

CREATE INDEX IF NOT EXISTS idx_settlement_events_group_order
    ON settlement_events (group_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_settlement_decisions_settlement_order
    ON settlement_decision_events (settlement_id, created_at, id);

CREATE TRIGGER IF NOT EXISTS groups_currency_code_is_immutable
BEFORE UPDATE OF currency_code ON groups
BEGIN
    SELECT RAISE(
        ABORT,
        'groups.currency_code is fixed at creation and cannot be changed'
    );
END;

CREATE TRIGGER IF NOT EXISTS expense_events_no_update
BEFORE UPDATE ON expense_events
BEGIN
    SELECT RAISE(ABORT, 'expense_events is append-only: no row may be updated');
END;

CREATE TRIGGER IF NOT EXISTS expense_events_no_delete
BEFORE DELETE ON expense_events
BEGIN
    SELECT RAISE(ABORT, 'expense_events is append-only: no row may be deleted');
END;

CREATE TRIGGER IF NOT EXISTS expense_allocations_no_update
BEFORE UPDATE ON expense_allocations
BEGIN
    SELECT RAISE(ABORT, 'expense_allocations is append-only: no row may be updated');
END;

CREATE TRIGGER IF NOT EXISTS expense_allocations_no_delete
BEFORE DELETE ON expense_allocations
BEGIN
    SELECT RAISE(ABORT, 'expense_allocations is append-only: no row may be deleted');
END;

CREATE TRIGGER IF NOT EXISTS settlement_events_no_update
BEFORE UPDATE ON settlement_events
BEGIN
    SELECT RAISE(ABORT, 'settlement_events is append-only: no row may be updated');
END;

CREATE TRIGGER IF NOT EXISTS settlement_events_no_delete
BEFORE DELETE ON settlement_events
BEGIN
    SELECT RAISE(ABORT, 'settlement_events is append-only: no row may be deleted');
END;

CREATE TRIGGER IF NOT EXISTS settlement_decision_events_no_update
BEFORE UPDATE ON settlement_decision_events
BEGIN
    SELECT RAISE(
        ABORT,
        'settlement_decision_events is append-only: no row may be updated'
    );
END;

CREATE TRIGGER IF NOT EXISTS settlement_decision_events_no_delete
BEFORE DELETE ON settlement_decision_events
BEGIN
    SELECT RAISE(
        ABORT,
        'settlement_decision_events is append-only: no row may be deleted'
    );
END;

CREATE TRIGGER IF NOT EXISTS expense_allocations_member_is_in_the_expense_group
BEFORE INSERT ON expense_allocations
BEGIN
    SELECT RAISE(
        ABORT,
        'expense_allocations member must belong to the group the expense belongs to'
    )
    WHERE NOT EXISTS (
        SELECT 1
        FROM expense_events AS e
        JOIN members AS m ON m.id = NEW.member_id
        WHERE e.id = NEW.expense_id AND m.group_id = e.group_id
    );
END;

PRAGMA user_version = 1;

COMMIT;
"""
"""The whole schema, applied with ``executescript`` at open.

One string, no ``.sql`` data file and no DDL scattered across functions, so the shape of
the database is readable in one place. Every statement is ``IF NOT EXISTS``: reopening a
store re-runs the script harmlessly, and two processes opening the same fresh file end
with one schema rather than an error. The script carries its own ``BEGIN IMMEDIATE`` and
``COMMIT`` because ``executescript`` commits any transaction already in flight.

The composite foreign keys are what make a cross-group or cross-currency event
impossible at the storage layer rather than merely unlikely in Python:
``(group_id, currency_code)`` points at ``groups (id, currency_code)``, and each member
column points at ``members (group_id, id)``. Allocations carry no ``group_id`` of their
own, so a ``BEFORE INSERT`` trigger enforces the same rule for them by joining through
the expense.
"""

_CONNECTION_PRAGMAS: Final[tuple[str, ...]] = (
    # Off by default in SQLite, and it cannot be changed inside a transaction, so it is
    # set immediately after connecting and before anything else runs.
    "PRAGMA foreign_keys = ON",
    # A PRAGMA takes no bound parameter, so the value is a literal rather than an
    # interpolation. BUSY_TIMEOUT_MS restates it and a test asserts they agree.
    "PRAGMA busy_timeout = 5000",
)

_FILE_PRAGMAS: Final[tuple[str, ...]] = (
    # A reader is never blocked by the writer under WAL. An in-memory database cannot
    # use it, and silently stays in its own journal mode.
    "PRAGMA journal_mode = WAL",
)

# Every statement the store issues, spelled out in full. No identifier and no value is
# ever interpolated into one: the parameters are always bound, and always through
# _params, which refuses anything that is not a str, an int or None.

_INSERT_USER: Final[str] = (
    "INSERT INTO users (id, email, display_name, created_at) VALUES (?, ?, ?, ?)"
)

_INSERT_GROUP: Final[str] = (
    "INSERT INTO groups (id, name, currency_code, created_at) VALUES (?, ?, ?, ?)"
)

_INSERT_MEMBER: Final[str] = (
    "INSERT INTO members (id, group_id, display_name, user_id, created_at) "
    "VALUES (?, ?, ?, ?, ?)"
)

_EXISTS_USER: Final[str] = "SELECT 1 FROM users WHERE id = ?"
_EXISTS_USER_EMAIL: Final[str] = "SELECT 1 FROM users WHERE email = ?"
_EXISTS_GROUP: Final[str] = "SELECT 1 FROM groups WHERE id = ?"
_EXISTS_MEMBER: Final[str] = "SELECT 1 FROM members WHERE id = ?"
_EXISTS_MEMBER_FOR_USER: Final[str] = (
    "SELECT 1 FROM members WHERE group_id = ? AND user_id = ?"
)

_SELECT_USER: Final[str] = (
    "SELECT id, email, display_name, created_at FROM users WHERE id = ?"
)

_SELECT_GROUP: Final[str] = (
    "SELECT id, name, currency_code, created_at FROM groups WHERE id = ?"
)

_SELECT_GROUPS: Final[str] = (
    "SELECT id, name, currency_code, created_at FROM groups ORDER BY created_at, id"
)

_SELECT_MEMBER: Final[str] = (
    "SELECT id, group_id, display_name, user_id, created_at FROM members WHERE id = ?"
)

_SELECT_MEMBERS_BY_GROUP: Final[str] = (
    "SELECT id, group_id, display_name, user_id, created_at FROM members "
    "WHERE group_id = ? ORDER BY created_at, id"
)

_SELECT_GROUP_CURRENCY: Final[str] = "SELECT currency_code FROM groups WHERE id = ?"

_INSERT_EXPENSE: Final[str] = (
    "INSERT INTO expense_events (id, group_id, currency_code, payer_id, total_cents, "
    "description, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)

_INSERT_ALLOCATION: Final[str] = (
    "INSERT INTO expense_allocations (expense_id, position, member_id, cents) "
    "VALUES (?, ?, ?, ?)"
)

_EXISTS_EXPENSE: Final[str] = "SELECT 1 FROM expense_events WHERE id = ?"

_SELECT_EXPENSE: Final[str] = (
    "SELECT id, group_id, currency_code, payer_id, total_cents, description, "
    "created_at, created_by FROM expense_events WHERE id = ?"
)

# The ordered reads below are the ones EXPLAIN QUERY PLAN is asserted against: the
# (group_id, created_at, id) index has to serve both the filter and the sort, with no
# temp B-tree, or the ledger sorts itself in memory on every read.
_SELECT_EXPENSES_BY_GROUP: Final[str] = (
    "SELECT id, group_id, currency_code, payer_id, total_cents, description, "
    "created_at, created_by FROM expense_events WHERE group_id = ? "
    "ORDER BY created_at, id"
)

_SELECT_ALLOCATIONS_BY_EXPENSE: Final[str] = (
    "SELECT member_id, cents FROM expense_allocations WHERE expense_id = ? "
    "ORDER BY position"
)

_SELECT_ALLOCATIONS_BY_GROUP: Final[str] = (
    "SELECT a.expense_id, a.member_id, a.cents FROM expense_allocations AS a "
    "JOIN expense_events AS e ON e.id = a.expense_id WHERE e.group_id = ? "
    "ORDER BY a.expense_id, a.position"
)

_INSERT_SETTLEMENT: Final[str] = (
    "INSERT INTO settlement_events (id, group_id, currency_code, from_member_id, "
    "to_member_id, amount_cents, created_at, created_by) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)

_EXISTS_SETTLEMENT: Final[str] = "SELECT 1 FROM settlement_events WHERE id = ?"

_SELECT_SETTLEMENTS_BY_GROUP: Final[str] = (
    "SELECT id, group_id, currency_code, from_member_id, to_member_id, amount_cents, "
    "created_at, created_by FROM settlement_events WHERE group_id = ? "
    "ORDER BY created_at, id"
)

_INSERT_DECISION: Final[str] = (
    "INSERT INTO settlement_decision_events (id, settlement_id, decision, decided_by, "
    "created_at) VALUES (?, ?, ?, ?, ?)"
)

_EXISTS_DECISION: Final[str] = "SELECT 1 FROM settlement_decision_events WHERE id = ?"

_SELECT_DECISIONS_BY_SETTLEMENT: Final[str] = (
    "SELECT id, settlement_id, decision, decided_by, created_at "
    "FROM settlement_decision_events WHERE settlement_id = ? ORDER BY created_at, id"
)

# A decision carries no group_id of its own, so it reaches its group through the
# settlement it references. That join is the reason settlement ids are unique.
_SELECT_DECISIONS_BY_GROUP: Final[str] = (
    "SELECT d.id, d.settlement_id, d.decision, d.decided_by, d.created_at "
    "FROM settlement_decision_events AS d "
    "JOIN settlement_events AS s ON s.id = d.settlement_id "
    "WHERE s.group_id = ? ORDER BY d.created_at, d.id"
)


def open_store(path: str | Path) -> EventStore:
    """Open, and create if necessary, the store at ``path``.

    The store never chooses a path: there is no default filename, no environment
    variable and no implicit file in the working directory. Pass ``IN_MEMORY`` for a
    private in-memory database.

    On the way up this checks the SQLite library is new enough for ``STRICT`` tables,
    turns foreign keys on, sets the busy timeout, puts a file-backed database into WAL
    mode, and applies the schema if the database is empty. A database at a newer
    ``user_version`` is refused rather than read.

    Raises:
        TypeError: if ``path`` is not a ``str`` or ``Path``.
        UnsupportedSQLiteVersion: if the linked library predates ``STRICT`` tables.
        UnsupportedSchemaVersion: if the database is newer than this code.
        CannotOpenStore: if the parent directory does not exist, the file is not a
            SQLite database, or SQLite cannot open it for any other reason.
    """
    if isinstance(path, Path):
        in_memory = False
        target: str | Path = path
    elif isinstance(path, str):
        in_memory = path == IN_MEMORY
        target = path if in_memory else Path(path)
    else:
        raise TypeError(
            f"open_store takes a str or Path, got {type(path).__name__}: {path!r}"
        )

    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        required = ".".join(str(part) for part in MIN_SQLITE_VERSION)
        raise UnsupportedSQLiteVersion(
            f"STRICT tables need SQLite {required} or newer, but this Python is "
            f"linked against {sqlite3.sqlite_version}"
        )

    if not in_memory and not Path(target).parent.is_dir():
        raise CannotOpenStore(
            f"cannot open the store at {target}: its directory does not exist, and "
            f"the store does not create directories"
        )

    try:
        connection = sqlite3.connect(target, isolation_level=None)
    except sqlite3.Error as error:
        raise CannotOpenStore(f"cannot open the store at {target}: {error}") from error

    try:
        for pragma in _CONNECTION_PRAGMAS:
            connection.execute(pragma)
        if not in_memory:
            for pragma in _FILE_PRAGMAS:
                connection.execute(pragma)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise UnsupportedSchemaVersion(
                f"the database at {target} is at schema version {version}, and this "
                f"code understands version {SCHEMA_VERSION}"
            )
        if version < SCHEMA_VERSION:
            connection.executescript(_SCHEMA_SQL)
    except sqlite3.Error as error:
        connection.close()
        raise CannotOpenStore(f"cannot open the store at {target}: {error}") from error
    except BaseException:
        connection.close()
        raise

    return EventStore(connection, str(target))


class EventStore:
    """A durable, append-only ledger store over one SQLite connection.

    Construct it with ``open_store``. Every read returns a domain object or a tuple of
    them, never a row, a dict or a ``sqlite3.Row``, and there is no way to reach the
    connection and write a statement of your own: the append-only guarantee is only
    worth something if nothing can go around it.

    The store never reads the clock. Every ``created_at`` comes from the object being
    written and no column carries a default, so two identical runs produce identical
    databases.

    **Not thread-safe, and it does not claim to be.** One store owns one connection.
    Concurrent use means one store per thread or per process; two stores on the same
    file is a supported arrangement and is what ``busy_timeout`` and WAL are for.
    """

    __slots__ = ("_connection", "_path")

    def __init__(self, connection: sqlite3.Connection, path: str) -> None:
        """Wrap an already-configured connection. Call ``open_store`` instead."""
        self._connection = connection
        self._path = path

    def __enter__(self) -> EventStore:
        """Return the store, so it can be used as a context manager."""
        return self

    def __exit__(self, *exception: object) -> None:
        """Close the store, on the way out of the block and on an exception alike."""
        self.close()

    def close(self) -> None:
        """Close the connection. Idempotent: closing a closed store does nothing."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None  # type: ignore[assignment]

    # --- Internals ----------------------------------------------------------

    def _require_open(self) -> sqlite3.Connection:
        """Return the connection, or raise ``StoreClosed``."""
        if self._connection is None:
            raise StoreClosed(f"the store at {self._path} is closed")
        return self._connection

    @contextmanager
    def _reading(self, what: str) -> Iterator[sqlite3.Connection]:
        """Yield the connection, translating any ``sqlite3`` failure into a store error."""
        connection = self._require_open()
        try:
            yield connection
        except sqlite3.IntegrityError as error:
            raise ConstraintViolated(f"{what} failed: {error}") from error
        except sqlite3.Error as error:
            raise StorageFailed(f"{what} failed: {error}") from error

    @contextmanager
    def _writing(self, what: str) -> Iterator[sqlite3.Connection]:
        """Yield the connection inside one ``BEGIN IMMEDIATE`` transaction.

        ``IMMEDIATE`` rather than the default deferred start, so the write lock is taken
        before the first statement rather than part-way through: a duplicate check and
        the insert it guards then see the same database, and a second writer waits out
        its ``busy_timeout`` instead of failing at the moment it tries to upgrade.

        Any exception rolls the whole transaction back, so a failed append leaves
        nothing behind, and every ``sqlite3`` failure leaves as a ``StoreError``.
        """
        connection = self._require_open()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except sqlite3.IntegrityError as error:
            connection.execute("ROLLBACK")
            raise ConstraintViolated(f"{what} failed: {error}") from error
        except sqlite3.Error as error:
            connection.execute("ROLLBACK")
            raise StorageFailed(f"{what} failed: {error}") from error
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")

    @staticmethod
    def _require_free(
        connection: sqlite3.Connection, statement: str, values: tuple, message: str
    ) -> None:
        """Raise ``DuplicateRecord`` if ``statement`` already matches a row.

        Called inside the write transaction, so between this check and the insert it
        guards nothing else can write. The ``UNIQUE`` constraints in the schema are the
        backstop; this is what turns them into a named error instead of a raw
        ``IntegrityError``.
        """
        if connection.execute(statement, _params(*values)).fetchone() is not None:
            raise DuplicateRecord(message)

    @staticmethod
    def _require_group(connection: sqlite3.Connection, group_id: str) -> None:
        """Raise ``RecordNotFound`` unless ``group_id`` names a stored group."""
        row = connection.execute(_EXISTS_GROUP, _params(group_id)).fetchone()
        if row is None:
            raise RecordNotFound(f"no group with id {group_id!r}")

    @staticmethod
    def _require_group_currency(
        connection: sqlite3.Connection, group_id: str, currency: Currency
    ) -> None:
        """Raise unless ``group_id`` exists and is denominated in ``currency``.

        The same disagreement is impossible at the schema level too: an event's
        ``(group_id, currency_code)`` is a composite foreign key into
        ``groups (id, currency_code)``, so a raw ``INSERT`` in the wrong currency is
        refused as well. This check exists so a caller gets ``CurrencyMismatch`` from
        ``money.py``, naming both codes, rather than a foreign key message.
        """
        row = connection.execute(_SELECT_GROUP_CURRENCY, _params(group_id)).fetchone()
        if row is None:
            raise RecordNotFound(f"no group with id {group_id!r}")
        stored = row[0]
        if stored != currency.code:
            raise CurrencyMismatch(
                f"group {group_id!r} is denominated in {stored}, so it cannot hold an "
                f"event in {currency.code}"
            )

    # --- Writes: the reference tables ---------------------------------------

    def add_user(self, user: User) -> None:
        """Store a new user. Ids and email addresses are unique across the store.

        Identity only, per task 6's scope: task 7 adds credentials, sessions and the
        lookups that go with them as schema version 2.

        Raises:
            TypeError: if ``user`` is not a ``User``.
            DuplicateRecord: if the id or the email address is already taken.
        """
        if not isinstance(user, User):
            raise TypeError(f"add_user takes a User, got {type(user).__name__}")
        with self._writing("adding a user") as connection:
            self._require_free(
                connection,
                _EXISTS_USER,
                (user.id,),
                f"a user with id {user.id!r} already exists",
            )
            self._require_free(
                connection,
                _EXISTS_USER_EMAIL,
                (user.email,),
                f"a user with email {user.email!r} already exists",
            )
            connection.execute(
                _INSERT_USER,
                _params(
                    user.id,
                    user.email,
                    user.display_name,
                    _encode_timestamp(user.created_at),
                ),
            )

    def add_group(self, group: Group) -> None:
        """Store a new group, fixing its currency for the life of the group.

        The currency is written once here and a trigger refuses every later change to
        it, so an amount in the log can never quietly change meaning.

        Raises:
            TypeError: if ``group`` is not a ``Group``.
            DuplicateRecord: if the id is already taken.
        """
        if not isinstance(group, Group):
            raise TypeError(f"add_group takes a Group, got {type(group).__name__}")
        with self._writing("adding a group") as connection:
            self._require_free(
                connection,
                _EXISTS_GROUP,
                (group.id,),
                f"a group with id {group.id!r} already exists",
            )
            connection.execute(
                _INSERT_GROUP,
                _params(
                    group.id,
                    group.name,
                    group.currency.code,
                    _encode_timestamp(group.created_at),
                ),
            )

    def add_member(self, member: Member) -> None:
        """Store a new member of an existing group.

        ``user_id`` may be ``None``, because task 9 seeds a member list before those
        people have accounts. At most one member per group may point at a given user,
        which a partial unique index enforces in the database as well as here. Two
        members of one group may share a display name.

        Raises:
            TypeError: if ``member`` is not a ``Member``.
            DuplicateRecord: if the id is taken, or the group already has a member
                linked to that user.
            ConstraintViolated: if the group or the linked user does not exist.
        """
        if not isinstance(member, Member):
            raise TypeError(f"add_member takes a Member, got {type(member).__name__}")
        with self._writing("adding a member") as connection:
            self._require_free(
                connection,
                _EXISTS_MEMBER,
                (member.id,),
                f"a member with id {member.id!r} already exists",
            )
            if member.user_id is not None:
                self._require_free(
                    connection,
                    _EXISTS_MEMBER_FOR_USER,
                    (member.group_id, member.user_id),
                    f"group {member.group_id!r} already has a member linked to user "
                    f"{member.user_id!r}",
                )
            connection.execute(
                _INSERT_MEMBER,
                _params(
                    member.id,
                    member.group_id,
                    member.display_name,
                    member.user_id,
                    _encode_timestamp(member.created_at),
                ),
            )

    # --- Writes: the log ----------------------------------------------------

    def append_expense(self, expense: ExpenseEvent) -> None:
        """Append one expense and all of its allocations, in a single transaction.

        ``append_`` rather than ``add_`` because this table can only grow. There is no
        method that updates or deletes an event, and a ``BEFORE UPDATE`` and
        ``BEFORE DELETE`` trigger on both tables refuses to do it for anyone who tries
        another way. Correcting an expense is task 17 appending a new event.

        Allocations are written with their tuple position, because ``ExpenseEvent``
        does not require them sorted and the order they were built in is part of the
        value. A zero-cent allocation is written like any other: 2 cents across 3 people
        is ``1, 1, 0``, and dropping the third share would drop a participant.

        Nothing about the payer is checked against the allocations: someone can pay for
        a meal they did not eat.

        Raises:
            TypeError: if ``expense`` is not an ``ExpenseEvent``, or if a field that
                should be an ``int`` is not one.
            AmountTooLarge: if the total or any allocation is above ``MAX_CENTS``.
            RecordNotFound: if the group does not exist.
            CurrencyMismatch: if the event's currency is not the group's currency.
            DuplicateRecord: if an expense with this id has already been appended.
            ConstraintViolated: if the payer, the author or an allocation member
                belongs to another group, or any other database constraint refuses it.
        """
        if not isinstance(expense, ExpenseEvent):
            raise TypeError(
                f"append_expense takes an ExpenseEvent, got {type(expense).__name__}"
            )
        for allocation in expense.allocations:
            _require_storable_cents(allocation.cents, "allocation cents")
        _require_storable_cents(expense.total_cents, "expense total_cents")

        with self._writing("appending an expense") as connection:
            self._require_group_currency(
                connection, expense.group_id, expense.currency
            )
            self._require_free(
                connection,
                _EXISTS_EXPENSE,
                (expense.id,),
                f"an expense with id {expense.id!r} has already been appended",
            )
            connection.execute(
                _INSERT_EXPENSE,
                _params(
                    expense.id,
                    expense.group_id,
                    expense.currency.code,
                    expense.payer_id,
                    expense.total_cents,
                    expense.description,
                    _encode_timestamp(expense.created_at),
                    expense.created_by,
                ),
            )
            for position, allocation in enumerate(expense.allocations):
                connection.execute(
                    _INSERT_ALLOCATION,
                    _params(
                        expense.id, position, allocation.member_id, allocation.cents
                    ),
                )

    def append_settlement(self, settlement: SettlementEvent) -> None:
        """Append one claimed payment from one member of a group to another.

        A settlement is born pending and carries no state column, because a mutable
        state on an immutable event is a contradiction. Its state is derived from the
        decision events that reference it, by tasks 4 and 15.

        Raises:
            TypeError: if ``settlement`` is not a ``SettlementEvent``.
            AmountTooLarge: if the amount is above ``MAX_CENTS``.
            RecordNotFound: if the group does not exist.
            CurrencyMismatch: if the event's currency is not the group's currency.
            DuplicateRecord: if a settlement with this id has already been appended.
            ConstraintViolated: if either member or the author belongs to another
                group, or any other database constraint refuses it.
        """
        if not isinstance(settlement, SettlementEvent):
            raise TypeError(
                f"append_settlement takes a SettlementEvent, got "
                f"{type(settlement).__name__}"
            )
        _require_storable_cents(settlement.amount_cents, "settlement amount_cents")

        with self._writing("appending a settlement") as connection:
            self._require_group_currency(
                connection, settlement.group_id, settlement.currency
            )
            self._require_free(
                connection,
                _EXISTS_SETTLEMENT,
                (settlement.id,),
                f"a settlement with id {settlement.id!r} has already been appended",
            )
            connection.execute(
                _INSERT_SETTLEMENT,
                _params(
                    settlement.id,
                    settlement.group_id,
                    settlement.currency.code,
                    settlement.from_member_id,
                    settlement.to_member_id,
                    settlement.amount_cents,
                    _encode_timestamp(settlement.created_at),
                    settlement.created_by,
                ),
            )

    def append_settlement_decision(self, decision: SettlementDecisionEvent) -> None:
        """Append one answer to one settlement. The log keeps every answer it is given.

        Two decisions for the same settlement are both stored and both come back:
        ``events.py`` documents that the earliest wins, and applying that rule is a
        read-model concern owned by tasks 4 and 15. A unique constraint here would turn
        a documented race into a crash and lose the second answer.

        ``created_at`` earlier than the settlement's is accepted. Phone clocks disagree,
        and refusing a payment that really happened because of clock skew is worse than
        storing it. That is a decision, not an oversight.

        Who is entitled to confirm is not checked here either. A decision event cannot
        see the settlement it references, and the receiver-only rule belongs to task 15,
        which can load both.

        Raises:
            TypeError: if ``decision`` is not a ``SettlementDecisionEvent``.
            DuplicateRecord: if a decision with this id has already been appended.
            ConstraintViolated: if the settlement or the deciding member does not exist.
        """
        if not isinstance(decision, SettlementDecisionEvent):
            raise TypeError(
                f"append_settlement_decision takes a SettlementDecisionEvent, got "
                f"{type(decision).__name__}"
            )
        with self._writing("appending a settlement decision") as connection:
            self._require_free(
                connection,
                _EXISTS_DECISION,
                (decision.id,),
                f"a decision with id {decision.id!r} has already been appended",
            )
            connection.execute(
                _INSERT_DECISION,
                _params(
                    decision.id,
                    decision.settlement_id,
                    decision.decision.value,
                    decision.decided_by,
                    _encode_timestamp(decision.created_at),
                ),
            )

    # --- Reads: the reference tables ----------------------------------------

    def get_user(self, user_id: str) -> User:
        """Return the user with ``user_id``, or raise ``RecordNotFound`` naming it."""
        with self._reading("reading a user") as connection:
            row = connection.execute(_SELECT_USER, _params(user_id)).fetchone()
        if row is None:
            raise RecordNotFound(f"no user with id {user_id!r}")
        return _user_from_row(row)

    def get_group(self, group_id: str) -> Group:
        """Return the group with ``group_id``, or raise ``RecordNotFound`` naming it.

        The returned ``currency`` is a ``Currency``, so it compares directly against the
        currency on an event without either side reaching for a code string.
        """
        with self._reading("reading a group") as connection:
            row = connection.execute(_SELECT_GROUP, _params(group_id)).fetchone()
        if row is None:
            raise RecordNotFound(f"no group with id {group_id!r}")
        return _group_from_row(row)

    def list_groups(self) -> tuple[Group, ...]:
        """Every group, in ``(created_at, id)`` order.

        The store has no singleton group and no hardcoded group id: the product is
        multi-group, so every other read is scoped by one of the ids this returns.
        """
        with self._reading("listing groups") as connection:
            rows = connection.execute(_SELECT_GROUPS).fetchall()
        return tuple(_group_from_row(row) for row in rows)

    def get_member(self, member_id: str) -> Member:
        """Return the member with ``member_id``, or raise ``RecordNotFound`` naming it.

        Member ids are unique across the store, not only within a group, so no group id
        is needed to resolve one.
        """
        with self._reading("reading a member") as connection:
            row = connection.execute(_SELECT_MEMBER, _params(member_id)).fetchone()
        if row is None:
            raise RecordNotFound(f"no member with id {member_id!r}")
        return _member_from_row(row)

    def list_members(self, group_id: str) -> tuple[Member, ...]:
        """Every member of ``group_id``, in ``(created_at, id)`` order.

        A group with no members yet is legal and returns an empty tuple. An unknown
        group id raises instead, so a typo is never read as an empty flat.
        """
        with self._reading("listing members") as connection:
            self._require_group(connection, group_id)
            rows = connection.execute(
                _SELECT_MEMBERS_BY_GROUP, _params(group_id)
            ).fetchall()
        return tuple(_member_from_row(row) for row in rows)

    # --- Reads: the log -----------------------------------------------------

    def get_expense(self, expense_id: str) -> ExpenseEvent:
        """Return the expense with ``expense_id``, allocations and all.

        The loaded event is a real ``ExpenseEvent``, so every task 2 invariant is
        re-checked here: a hand-edited database whose allocations no longer sum to
        ``total_cents`` surfaces as ``InvalidEvent`` at load time rather than as a
        quietly wrong balance.

        Raises:
            RecordNotFound: if no expense has that id.
            InvalidEvent: if the stored rows no longer satisfy the event's invariants.
        """
        with self._reading("reading an expense") as connection:
            row = connection.execute(_SELECT_EXPENSE, _params(expense_id)).fetchone()
            if row is None:
                raise RecordNotFound(f"no expense with id {expense_id!r}")
            allocations = connection.execute(
                _SELECT_ALLOCATIONS_BY_EXPENSE, _params(expense_id)
            ).fetchall()
        return _expense_from_rows(row, allocations)

    def list_expenses(self, group_id: str) -> tuple[ExpenseEvent, ...]:
        """Every expense in ``group_id``, in ascending ``ordering_key`` order.

        Ascending is the only order the store has. Task 11's reverse-chronological feed
        reverses in Python, which keeps one ordering rule in one place.

        Raises:
            RecordNotFound: if the group does not exist. A group that exists and has no
                expenses returns an empty tuple: empty is a legitimate state, and a
                typo in a group id must not read as "this group has spent nothing".
        """
        with self._reading("listing expenses") as connection:
            self._require_group(connection, group_id)
            rows = connection.execute(
                _SELECT_EXPENSES_BY_GROUP, _params(group_id)
            ).fetchall()
            allocation_rows = connection.execute(
                _SELECT_ALLOCATIONS_BY_GROUP, _params(group_id)
            ).fetchall()
        by_expense: dict[str, list[tuple[str, int]]] = {}
        for expense_id, member_id, cents in allocation_rows:
            by_expense.setdefault(expense_id, []).append((member_id, cents))
        return tuple(
            _expense_from_rows(row, by_expense.get(row[0], [])) for row in rows
        )

    def list_settlements(self, group_id: str) -> tuple[SettlementEvent, ...]:
        """Every settlement in ``group_id``, in ascending ``ordering_key`` order.

        Raises:
            RecordNotFound: if the group does not exist. A group with no settlements
                returns an empty tuple.
        """
        with self._reading("listing settlements") as connection:
            self._require_group(connection, group_id)
            rows = connection.execute(
                _SELECT_SETTLEMENTS_BY_GROUP, _params(group_id)
            ).fetchall()
        return tuple(_settlement_from_row(row) for row in rows)

    def list_settlement_decisions(
        self, settlement_id: str
    ) -> tuple[SettlementDecisionEvent, ...]:
        """Every decision on ``settlement_id``, in ascending ``ordering_key`` order.

        All of them, in order, with no rule applied: if the log holds two answers it
        hands back two answers, and the earliest-wins fold happens in the read model.

        Raises:
            RecordNotFound: if the settlement does not exist. A settlement nobody has
                answered yet returns an empty tuple, which is the pending state.
        """
        with self._reading("listing settlement decisions") as connection:
            if (
                connection.execute(
                    _EXISTS_SETTLEMENT, _params(settlement_id)
                ).fetchone()
                is None
            ):
                raise RecordNotFound(f"no settlement with id {settlement_id!r}")
            rows = connection.execute(
                _SELECT_DECISIONS_BY_SETTLEMENT, _params(settlement_id)
            ).fetchall()
        return tuple(_decision_from_row(row) for row in rows)

    def list_events(self, group_id: str) -> tuple[LedgerEvent, ...]:
        """Every event in ``group_id`` in one sequence, in ``ordering_key`` order.

        Expenses, settlements and decisions in the one total order, which is what a
        replay and a feed both need. The three reads are already ordered by
        ``(created_at, id)`` in SQL; merging them uses ``ordering_key`` itself rather
        than a re-derived rule, so the store cannot drift from ``events.py``.

        Decisions reach this group through the settlement they reference, since they
        carry no group of their own.

        Raises:
            RecordNotFound: if the group does not exist.
        """
        with self._reading("listing events") as connection:
            self._require_group(connection, group_id)
            decision_rows = connection.execute(
                _SELECT_DECISIONS_BY_GROUP, _params(group_id)
            ).fetchall()
        events: list[LedgerEvent] = [
            *self.list_expenses(group_id),
            *self.list_settlements(group_id),
            *(_decision_from_row(row) for row in decision_rows),
        ]
        return tuple(sorted(events, key=ordering_key))


def _expense_from_rows(
    row: tuple[str, str, str, str, int, str, str, str],
    allocation_rows: list[tuple[str, int]] | tuple[tuple[str, int], ...],
) -> ExpenseEvent:
    """Build an ``ExpenseEvent`` from its row and its allocation rows.

    The allocation rows arrive in ``position`` order, which is the order they were
    written in, so the tuple that comes out is the tuple that went in rather than a
    re-sorted one.
    """
    (
        expense_id,
        group_id,
        currency_code,
        payer_id,
        total_cents,
        description,
        created_at,
        created_by,
    ) = row
    return ExpenseEvent(
        ExpenseId(expense_id),
        GroupId(group_id),
        Currency(currency_code),
        MemberId(payer_id),
        total_cents,
        tuple(
            Allocation(MemberId(member_id), cents)
            for member_id, cents in allocation_rows
        ),
        description,
        _decode_timestamp(created_at),
        MemberId(created_by),
    )


def _settlement_from_row(
    row: tuple[str, str, str, str, str, int, str, str],
) -> SettlementEvent:
    """Build a ``SettlementEvent`` from its row, re-checking every invariant."""
    (
        settlement_id,
        group_id,
        currency_code,
        from_member_id,
        to_member_id,
        amount_cents,
        created_at,
        created_by,
    ) = row
    return SettlementEvent(
        SettlementId(settlement_id),
        GroupId(group_id),
        Currency(currency_code),
        MemberId(from_member_id),
        MemberId(to_member_id),
        amount_cents,
        _decode_timestamp(created_at),
        MemberId(created_by),
    )


def _decision_from_row(
    row: tuple[str, str, str, str, str],
) -> SettlementDecisionEvent:
    """Build a ``SettlementDecisionEvent`` from its row.

    ``SettlementState(decision)`` cannot fail on stored data, because the column has a
    ``CHECK`` that admits only ``CONFIRMED`` and ``REJECTED``. ``PENDING`` is the
    absence of a decision, so it is unconstructible in ``events.py`` and unstorable
    here.
    """
    decision_id, settlement_id, decision, decided_by, created_at = row
    return SettlementDecisionEvent(
        decision_id,
        SettlementId(settlement_id),
        SettlementState(decision),
        MemberId(decided_by),
        _decode_timestamp(created_at),
    )


def _user_from_row(row: tuple[str, str, str, str]) -> User:
    """Build a ``User`` from its row, re-checking every invariant on the way out."""
    user_id, email, display_name, created_at = row
    return User(UserId(user_id), email, display_name, _decode_timestamp(created_at))


def _member_from_row(row: tuple[str, str, str, str | None, str]) -> Member:
    """Build a ``Member`` from its row, re-checking every invariant on the way out."""
    member_id, group_id, display_name, user_id, created_at = row
    return Member(
        MemberId(member_id),
        GroupId(group_id),
        display_name,
        None if user_id is None else UserId(user_id),
        _decode_timestamp(created_at),
    )


def _group_from_row(row: tuple[str, str, str, str]) -> Group:
    """Build a ``Group`` from its row, re-checking every invariant on the way out.

    A stored ``currency_code`` is always three uppercase letters, because the column has
    a ``CHECK`` that says so, which is what makes ``Currency`` construction on read
    unable to fail on data this module wrote.
    """
    group_id, name, currency_code, created_at = row
    return Group(
        GroupId(group_id), name, Currency(currency_code), _decode_timestamp(created_at)
    )
