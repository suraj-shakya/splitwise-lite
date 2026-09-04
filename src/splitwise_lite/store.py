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

from .events import GroupId, MemberId
from .money import Currency, DomainError

__all__ = [
    "BUSY_TIMEOUT_MS",
    "IN_MEMORY",
    "MIN_SQLITE_VERSION",
    "SCHEMA_VERSION",
    "CannotOpenStore",
    "EventStore",
    "Group",
    "InvalidRecord",
    "Member",
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

_SELECT_GROUP: Final[str] = (
    "SELECT id, name, currency_code, created_at FROM groups WHERE id = ?"
)

_SELECT_GROUPS: Final[str] = (
    "SELECT id, name, currency_code, created_at FROM groups ORDER BY created_at, id"
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
        except sqlite3.Error as error:
            raise StoreError(f"{what} failed: {error}") from error

    # --- Reads --------------------------------------------------------------

    def list_groups(self) -> tuple[Group, ...]:
        """Every group, in ``(created_at, id)`` order.

        The store has no singleton group and no hardcoded group id: the product is
        multi-group, so every other read is scoped by one of the ids this returns.
        """
        with self._reading("listing groups") as connection:
            rows = connection.execute(_SELECT_GROUPS).fetchall()
        return tuple(_group_from_row(row) for row in rows)


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
