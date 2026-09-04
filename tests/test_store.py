"""Tests for the durable, append-only event store.

Task 6 of plans/backlog.md, sharpened in plans/tasks/06-persistence-and-event-store.md.

Every round-trip and constraint test runs twice, once against an in-memory store and
once against a file-backed store under ``tmp_path``, from the one ``store`` fixture and
the one test body, so nothing can pass only under memory semantics.

Several tests reach past the public API to ``store._connection`` and issue raw SQL.
That is deliberate and is the point of the append-only criteria: enforcement has to live
in the database, so it must hold for a statement the store's own methods never wrote.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from splitwise_lite.money import Currency, DomainError
from splitwise_lite.store import (
    BUSY_TIMEOUT_MS,
    IN_MEMORY,
    MIN_SQLITE_VERSION,
    SCHEMA_VERSION,
    CannotOpenStore,
    EventStore,
    Group,
    InvalidRecord,
    Member,
    StoreClosed,
    StoreError,
    UnsupportedSchemaVersion,
    UnsupportedSQLiteVersion,
    User,
    UserId,
    open_store,
)

AUD = Currency("AUD")
NZD = Currency("NZD")

T0 = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)


def at(seconds: int = 0, *, microsecond: int = 0) -> datetime:
    """A UTC timestamp ``seconds`` after the fixed base time."""
    return T0 + timedelta(seconds=seconds, microseconds=microsecond)


@pytest.fixture(params=["memory", "file"])
def store(request: pytest.FixtureRequest, tmp_path: Path):
    """An open store, once in memory and once backed by a file under ``tmp_path``."""
    target = IN_MEMORY if request.param == "memory" else tmp_path / "ledger.sqlite3"
    with open_store(target) as opened:
        yield opened


def raw(store: EventStore, sql: str, params: tuple[object, ...] = ()) -> list[tuple]:
    """Run a statement on the store's connection, going around the public API."""
    return store._connection.execute(sql, params).fetchall()


def count(store: EventStore, table: str) -> int:
    """Row count of ``table``, read with raw SQL."""
    return raw(store, f"SELECT count(*) FROM {table}")[0][0]


# --- Error family -----------------------------------------------------------


def test_store_error_is_a_domain_error() -> None:
    assert issubclass(StoreError, DomainError)


@pytest.mark.parametrize(
    "error",
    [
        CannotOpenStore,
        InvalidRecord,
        StoreClosed,
        UnsupportedSQLiteVersion,
        UnsupportedSchemaVersion,
    ],
)
def test_every_store_error_subclasses_store_error(error: type[Exception]) -> None:
    assert issubclass(error, StoreError)


# --- Records ----------------------------------------------------------------


def test_user_round_trips_its_fields() -> None:
    user = User(UserId("u1"), "sam@example.com", "Sam", at())
    assert user.id == "u1"
    assert user.email == "sam@example.com"
    assert user.display_name == "Sam"
    assert user.created_at == at()


@pytest.mark.parametrize("record", [User, Group, Member])
def test_records_are_frozen_and_slotted(record: type) -> None:
    assert record.__dataclass_params__.frozen is True
    assert record.__slots__


def test_user_email_must_be_lowercase() -> None:
    with pytest.raises(InvalidRecord):
        User(UserId("u1"), "Sam@Example.com", "Sam", at())


def test_user_email_must_not_be_empty() -> None:
    with pytest.raises(InvalidRecord):
        User(UserId("u1"), "", "Sam", at())


def test_user_display_name_is_capped_at_100_characters() -> None:
    User(UserId("u1"), "sam@example.com", "x" * 100, at())
    with pytest.raises(InvalidRecord):
        User(UserId("u1"), "sam@example.com", "x" * 101, at())


def test_user_display_name_must_not_be_blank() -> None:
    with pytest.raises(InvalidRecord):
        User(UserId("u1"), "sam@example.com", "   ", at())


def test_record_created_at_must_be_timezone_aware() -> None:
    with pytest.raises(InvalidRecord):
        User(UserId("u1"), "sam@example.com", "Sam", datetime(2026, 9, 3, 10, 0))


def test_record_created_at_is_normalised_to_utc() -> None:
    brisbane = timezone(timedelta(hours=10))
    user = User(
        UserId("u1"),
        "sam@example.com",
        "Sam",
        datetime(2026, 9, 3, 20, 0, tzinfo=brisbane),
    )
    assert user.created_at == at()
    assert user.created_at.utcoffset() == timedelta(0)


def test_group_currency_is_a_currency_not_a_string() -> None:
    group = Group("g1", "Flat", AUD, at())
    assert group.currency == AUD
    with pytest.raises(TypeError):
        Group("g1", "Flat", "AUD", at())


def test_member_user_id_may_be_none() -> None:
    member = Member("m1", "g1", "Sam", None, at())
    assert member.user_id is None


def test_member_rejects_an_empty_id() -> None:
    with pytest.raises(InvalidRecord):
        Member("", "g1", "Sam", None, at())


# --- Opening, pragmas and schema --------------------------------------------


def test_a_fresh_store_is_at_schema_version_1(store: EventStore) -> None:
    assert raw(store, "PRAGMA user_version")[0][0] == SCHEMA_VERSION == 1


def test_foreign_keys_pragma_is_on(store: EventStore) -> None:
    assert raw(store, "PRAGMA foreign_keys")[0][0] == 1


def test_busy_timeout_matches_the_stated_constant(store: EventStore) -> None:
    assert raw(store, "PRAGMA busy_timeout")[0][0] == BUSY_TIMEOUT_MS


def test_a_file_store_uses_write_ahead_logging(tmp_path: Path) -> None:
    with open_store(tmp_path / "ledger.sqlite3") as opened:
        assert raw(opened, "PRAGMA journal_mode")[0][0] == "wal"


def test_an_in_memory_store_opens_without_write_ahead_logging() -> None:
    with open_store(IN_MEMORY) as opened:
        assert raw(opened, "PRAGMA user_version")[0][0] == SCHEMA_VERSION


def test_every_table_is_strict(store: EventStore) -> None:
    tables = raw(
        store,
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'",
    )
    assert tables
    for name, sql in tables:
        assert sql.rstrip().rstrip(";").upper().endswith("STRICT"), name


@pytest.mark.parametrize("value", ["'12.50'", "'twelve'"])
def test_strict_tables_reject_text_in_an_integer_column(
    store: EventStore, value: str
) -> None:
    with pytest.raises(sqlite3.IntegrityError) as caught:
        raw(
            store,
            "INSERT INTO expense_allocations (expense_id, position, member_id, cents) "
            f"VALUES ('e1', 0, 'm1', {value})",
        )
    assert "INTEGER column expense_allocations.cents" in str(caught.value)


def test_opening_an_old_sqlite_library_raises_a_named_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 36, 0))
    monkeypatch.setattr(sqlite3, "sqlite_version", "3.36.0")
    with pytest.raises(UnsupportedSQLiteVersion) as caught:
        open_store(IN_MEMORY)
    message = str(caught.value)
    assert "3.36.0" in message
    assert ".".join(str(part) for part in MIN_SQLITE_VERSION) in message


def test_opening_a_newer_schema_version_raises_rather_than_reading_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    with open_store(path) as opened:
        raw(opened, f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(UnsupportedSchemaVersion) as caught:
        open_store(path)
    assert str(SCHEMA_VERSION + 1) in str(caught.value)


def test_opening_under_a_missing_directory_names_the_path(tmp_path: Path) -> None:
    path = tmp_path / "nope" / "ledger.sqlite3"
    with pytest.raises(CannotOpenStore) as caught:
        open_store(path)
    assert "ledger.sqlite3" in str(caught.value)


def test_opening_a_file_that_is_not_a_database_names_the_path(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("this is not a database", encoding="utf-8")
    with pytest.raises(CannotOpenStore) as caught:
        open_store(path)
    assert "notes.txt" in str(caught.value)


def test_opening_a_zero_byte_file_treats_it_as_a_fresh_database(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    path.touch()
    assert path.stat().st_size == 0
    with open_store(path) as opened:
        assert raw(opened, "PRAGMA user_version")[0][0] == SCHEMA_VERSION


def test_the_store_has_no_escape_hatch_on_its_public_surface() -> None:
    public = {name for name in dir(EventStore) if not name.startswith("_")}
    assert not public & {"execute", "executemany", "raw", "sql", "connection", "cursor"}


# --- Closing ----------------------------------------------------------------


def test_using_a_closed_store_raises_a_named_error(tmp_path: Path) -> None:
    opened = open_store(tmp_path / "ledger.sqlite3")
    opened.close()
    with pytest.raises(StoreClosed):
        opened.list_groups()


def test_close_is_idempotent(tmp_path: Path) -> None:
    opened = open_store(tmp_path / "ledger.sqlite3")
    opened.close()
    opened.close()


def test_the_context_manager_closes_on_an_exception(tmp_path: Path) -> None:
    opened = open_store(tmp_path / "ledger.sqlite3")
    with pytest.raises(ZeroDivisionError):
        with opened:
            raise ZeroDivisionError
    with pytest.raises(StoreClosed):
        opened.list_groups()
