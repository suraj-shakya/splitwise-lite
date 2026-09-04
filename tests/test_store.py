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

import ast
import inspect
import re
import sqlite3
import tomllib
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from splitwise_lite import events as events_module
from splitwise_lite import store as store_module
from splitwise_lite.events import (
    Allocation,
    ExpenseEvent,
    ExpenseId,
    GroupId,
    InvalidEvent,
    MemberId,
    SettlementDecisionEvent,
    SettlementEvent,
    SettlementId,
    SettlementState,
    ordering_key,
)
from splitwise_lite.money import MAX_CENTS, Currency, CurrencyMismatch, DomainError
from splitwise_lite.store import (
    BUSY_TIMEOUT_MS,
    IN_MEMORY,
    MIN_SQLITE_VERSION,
    SCHEMA_VERSION,
    AmountTooLarge,
    CannotOpenStore,
    ConstraintViolated,
    DuplicateRecord,
    EventStore,
    Group,
    InvalidRecord,
    Member,
    RecordNotFound,
    Session,
    StorageFailed,
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
_STAMP = "2026-09-03T10:00:00.000000+00:00"


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


def count_tables(store: EventStore) -> int:
    """How many tables the schema holds, read with raw SQL."""
    return raw(store, "SELECT count(*) FROM sqlite_master WHERE type = 'table'")[0][0]


# --- Error family -----------------------------------------------------------


def test_store_error_is_a_domain_error() -> None:
    assert issubclass(StoreError, DomainError)


@pytest.mark.parametrize(
    "error",
    [
        AmountTooLarge,
        CannotOpenStore,
        ConstraintViolated,
        DuplicateRecord,
        InvalidRecord,
        RecordNotFound,
        StorageFailed,
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


def test_a_fresh_store_is_at_schema_version_2(store: EventStore) -> None:
    """Task 7 raised the version when it added credentials and sessions."""
    assert raw(store, "PRAGMA user_version")[0][0] == SCHEMA_VERSION == 2


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


# --- Users, groups and members ----------------------------------------------


def a_group(store: EventStore, group_id: str = "g1", currency: Currency = AUD) -> Group:
    """Add and return a group."""
    group = Group(group_id, f"Flat {group_id}", currency, at())
    store.add_group(group)
    return group


def a_member(
    store: EventStore,
    member_id: str = "m1",
    group_id: str = "g1",
    user_id: str | None = None,
) -> Member:
    """Add and return a member of ``group_id``."""
    member = Member(member_id, group_id, f"Name {member_id}", user_id, at())
    store.add_member(member)
    return member


def test_a_user_round_trips(store: EventStore) -> None:
    user = User(UserId("u1"), "sam@example.com", "Sam", at())
    store.add_user(user)
    assert store.get_user(UserId("u1")) == user


def test_a_group_round_trips(store: EventStore) -> None:
    group = a_group(store)
    assert store.get_group("g1") == group
    assert store.get_group("g1").currency == AUD


def test_a_member_round_trips_with_and_without_a_user(store: EventStore) -> None:
    a_group(store)
    store.add_user(User(UserId("u1"), "sam@example.com", "Sam", at()))
    unlinked = a_member(store, "m1")
    linked = a_member(store, "m2", user_id="u1")
    assert store.get_member("m1") == unlinked
    assert store.get_member("m1").user_id is None
    assert store.get_member("m2") == linked


def test_list_groups_is_in_created_at_then_id_order(store: EventStore) -> None:
    store.add_group(Group("g2", "Later", AUD, at(1)))
    store.add_group(Group("g1", "Same time b", AUD, at()))
    store.add_group(Group("g0", "Same time a", AUD, at()))
    assert [group.id for group in store.list_groups()] == ["g0", "g1", "g2"]


def test_list_members_is_empty_for_a_group_with_no_members(store: EventStore) -> None:
    a_group(store)
    assert store.list_members("g1") == ()


def test_list_members_returns_only_that_groups_members(store: EventStore) -> None:
    a_group(store, "g1")
    a_group(store, "g2", NZD)
    a_member(store, "m1", "g1")
    a_member(store, "m2", "g2")
    assert [member.id for member in store.list_members("g1")] == ["m1"]
    assert [member.id for member in store.list_members("g2")] == ["m2"]


def test_two_members_of_one_group_may_share_a_display_name(store: EventStore) -> None:
    a_group(store)
    store.add_member(Member("m1", "g1", "Sam", None, at()))
    store.add_member(Member("m2", "g1", "Sam", None, at()))
    names = [member.display_name for member in store.list_members("g1")]
    assert names == ["Sam", "Sam"]


def test_one_user_maps_to_at_most_one_member_per_group(store: EventStore) -> None:
    a_group(store)
    store.add_user(User(UserId("u1"), "sam@example.com", "Sam", at()))
    a_member(store, "m1", "g1", "u1")
    with pytest.raises(DuplicateRecord):
        a_member(store, "m2", "g1", "u1")
    assert len(store.list_members("g1")) == 1


def test_the_same_user_may_be_a_member_of_two_groups(store: EventStore) -> None:
    a_group(store, "g1")
    a_group(store, "g2", NZD)
    store.add_user(User(UserId("u1"), "sam@example.com", "Sam", at()))
    a_member(store, "m1", "g1", "u1")
    a_member(store, "m2", "g2", "u1")
    assert store.get_member("m2").user_id == "u1"


def test_a_raw_second_link_to_one_user_is_rejected_by_the_index(
    store: EventStore,
) -> None:
    a_group(store)
    store.add_user(User(UserId("u1"), "sam@example.com", "Sam", at()))
    a_member(store, "m1", "g1", "u1")
    with pytest.raises(sqlite3.IntegrityError):
        raw(
            store,
            "INSERT INTO members (id, group_id, display_name, user_id, created_at) "
            "VALUES ('m2', 'g1', 'Sam', 'u1', ?)",
            (_STAMP,),
        )


# --- Duplicates and missing rows --------------------------------------------


def test_a_duplicate_user_id_is_rejected_and_leaves_the_row_alone(
    store: EventStore,
) -> None:
    original = User(UserId("u1"), "sam@example.com", "Sam", at())
    store.add_user(original)
    with pytest.raises(DuplicateRecord) as caught:
        store.add_user(User(UserId("u1"), "other@example.com", "Other", at(5)))
    assert "u1" in str(caught.value)
    assert store.get_user(UserId("u1")) == original
    assert count(store, "users") == 1


def test_a_duplicate_email_is_rejected(store: EventStore) -> None:
    store.add_user(User(UserId("u1"), "sam@example.com", "Sam", at()))
    with pytest.raises(DuplicateRecord) as caught:
        store.add_user(User(UserId("u2"), "sam@example.com", "Sam Again", at()))
    assert "sam@example.com" in str(caught.value)
    assert count(store, "users") == 1


def test_a_duplicate_group_id_is_rejected(store: EventStore) -> None:
    a_group(store)
    with pytest.raises(DuplicateRecord):
        store.add_group(Group("g1", "Another flat", NZD, at()))
    assert store.get_group("g1").currency == AUD


def test_a_duplicate_member_id_is_rejected(store: EventStore) -> None:
    a_group(store)
    a_member(store, "m1")
    with pytest.raises(DuplicateRecord):
        a_member(store, "m1")
    assert count(store, "members") == 1


@pytest.mark.parametrize(
    "read",
    [
        "get_user",
        "get_group",
        "get_member",
        "list_members",
        "get_expense",
        "list_expenses",
        "list_settlements",
        "list_settlement_decisions",
        "list_events",
    ],
)
def test_reading_an_unknown_id_raises_not_found_naming_it(
    store: EventStore, read: str
) -> None:
    with pytest.raises(RecordNotFound) as caught:
        getattr(store, read)("nope")
    assert "nope" in str(caught.value)


def test_a_member_of_an_unknown_group_is_rejected_as_a_store_error(
    store: EventStore,
) -> None:
    with pytest.raises(StoreError) as caught:
        a_member(store, "m1", "ghost")
    assert not isinstance(caught.value, sqlite3.Error)


def test_a_member_linked_to_an_unknown_user_is_rejected(store: EventStore) -> None:
    a_group(store)
    with pytest.raises(StoreError):
        a_member(store, "m1", "g1", "ghost")
    assert count(store, "members") == 0


# --- Currency immutability --------------------------------------------------


def test_a_raw_update_of_a_groups_currency_is_rejected(store: EventStore) -> None:
    a_group(store, "g1", AUD)
    with pytest.raises(sqlite3.IntegrityError) as caught:
        raw(store, "UPDATE groups SET currency_code = 'NZD' WHERE id = 'g1'")
    assert "currency" in str(caught.value)
    assert store.get_group("g1").currency == AUD


def test_the_currency_trigger_fires_even_for_a_group_with_no_expenses(
    store: EventStore,
) -> None:
    a_group(store, "g1", AUD)
    assert count(store, "expense_events") == 0
    with pytest.raises(sqlite3.IntegrityError):
        raw(store, "UPDATE groups SET currency_code = 'AUD' WHERE id = 'g1'")


def test_a_groups_name_is_not_trigger_locked(store: EventStore) -> None:
    a_group(store, "g1")
    raw(store, "UPDATE groups SET name = 'Renamed' WHERE id = 'g1'")
    assert store.get_group("g1").name == "Renamed"


# --- Expenses ---------------------------------------------------------------


def a_flat(store: EventStore, group_id: str = "g1", currency: Currency = AUD) -> None:
    """A group with three members, ``<group_id>m1`` through ``<group_id>m3``."""
    a_group(store, group_id, currency)
    for index in (1, 2, 3):
        a_member(store, f"{group_id}m{index}", group_id)


def an_expense(
    expense_id: str = "e1",
    group_id: str = "g1",
    currency: Currency = AUD,
    payer_id: str = "g1m1",
    total_cents: int = 1000,
    allocations: tuple[Allocation, ...] | None = None,
    description: str = "Dinner",
    created_at: datetime | None = None,
    created_by: str = "g1m1",
) -> ExpenseEvent:
    """An expense event, defaulting to $10 split evenly between two members."""
    if allocations is None:
        allocations = (
            Allocation(MemberId(f"{group_id}m1"), total_cents // 2),
            Allocation(MemberId(f"{group_id}m2"), total_cents - total_cents // 2),
        )
    return ExpenseEvent(
        ExpenseId(expense_id),
        GroupId(group_id),
        currency,
        MemberId(payer_id),
        total_cents,
        allocations,
        description,
        created_at if created_at is not None else at(),
        MemberId(created_by),
    )


def test_an_expense_round_trips_equal(store: EventStore) -> None:
    a_flat(store)
    expense = an_expense()
    store.append_expense(expense)
    assert store.get_expense("e1") == expense


def test_allocations_come_back_in_the_order_they_were_written(
    store: EventStore,
) -> None:
    a_flat(store)
    descending = (
        Allocation(MemberId("g1m3"), 500),
        Allocation(MemberId("g1m2"), 300),
        Allocation(MemberId("g1m1"), 200),
    )
    store.append_expense(an_expense(allocations=descending))
    assert store.get_expense("e1").allocations == descending


def test_a_zero_cent_allocation_round_trips(store: EventStore) -> None:
    a_flat(store)
    shares = (
        Allocation(MemberId("g1m1"), 1),
        Allocation(MemberId("g1m2"), 1),
        Allocation(MemberId("g1m3"), 0),
    )
    store.append_expense(an_expense(total_cents=2, allocations=shares))
    assert store.get_expense("e1").allocations == shares


def test_an_expense_whose_payer_is_not_a_participant_round_trips(
    store: EventStore,
) -> None:
    a_flat(store)
    shares = (Allocation(MemberId("g1m2"), 1000),)
    expense = an_expense(payer_id="g1m1", allocations=shares)
    store.append_expense(expense)
    assert store.get_expense("e1") == expense


def test_a_single_allocation_equal_to_the_total_round_trips(store: EventStore) -> None:
    a_flat(store)
    expense = an_expense(allocations=(Allocation(MemberId("g1m1"), 1000),))
    store.append_expense(expense)
    assert store.get_expense("e1") == expense


def test_an_empty_description_round_trips_as_empty_text(store: EventStore) -> None:
    a_flat(store)
    store.append_expense(an_expense(description=""))
    assert store.get_expense("e1").description == ""
    assert raw(store, "SELECT description FROM expense_events") == [("",)]


def test_a_description_of_emoji_and_scripts_round_trips(store: EventStore) -> None:
    a_flat(store)
    description = "Pizza \U0001f355 with 日本語 and\na newline"
    store.append_expense(an_expense(description=description))
    assert store.get_expense("e1").description == description
    # The cap on the column counts characters, not bytes: SQLite's length() on TEXT
    # agrees with Python's len() even though this string is 42 bytes of UTF-8.
    assert raw(store, "SELECT length(description) FROM expense_events") == [
        (len(description),)
    ]
    assert len(description.encode("utf-8")) > len(description)


def test_the_largest_storable_amount_round_trips_exactly(store: EventStore) -> None:
    a_flat(store)
    expense = an_expense(
        total_cents=MAX_CENTS,
        allocations=(Allocation(MemberId("g1m1"), MAX_CENTS),),
    )
    store.append_expense(expense)
    loaded = store.get_expense("e1")
    assert loaded.total_cents == MAX_CENTS
    assert loaded.allocations[0].cents == MAX_CENTS
    assert loaded == expense


def test_a_total_above_the_bound_is_rejected_naming_the_field(
    store: EventStore,
) -> None:
    a_flat(store)
    over = an_expense(
        total_cents=MAX_CENTS + 1,
        allocations=(
            Allocation(MemberId("g1m1"), MAX_CENTS),
            Allocation(MemberId("g1m2"), 1),
        ),
    )
    with pytest.raises(AmountTooLarge) as caught:
        store.append_expense(over)
    assert "total_cents" in str(caught.value)
    assert str(MAX_CENTS) in str(caught.value)
    assert count(store, "expense_events") == 0
    assert count(store, "expense_allocations") == 0


def test_an_allocation_above_the_bound_is_rejected_naming_the_field(
    store: EventStore,
) -> None:
    a_flat(store)
    over = an_expense(
        total_cents=MAX_CENTS + 1,
        allocations=(Allocation(MemberId("g1m1"), MAX_CENTS + 1),),
    )
    with pytest.raises(AmountTooLarge) as caught:
        store.append_expense(over)
    assert "cents" in str(caught.value)
    assert str(MAX_CENTS) in str(caught.value)
    assert count(store, "expense_events") == 0


def test_a_float_reaching_the_store_raises_type_error(store: EventStore) -> None:
    a_flat(store)
    corrupted = an_expense()
    object.__setattr__(corrupted, "total_cents", 1000.0)
    with pytest.raises(TypeError):
        store.append_expense(corrupted)
    assert count(store, "expense_events") == 0


def test_a_timestamp_from_another_offset_round_trips_as_utc(store: EventStore) -> None:
    a_flat(store)
    brisbane = timezone(timedelta(hours=10))
    constructed = an_expense(created_at=datetime(2026, 9, 3, 20, 0, tzinfo=brisbane))
    store.append_expense(constructed)
    loaded = store.get_expense("e1")
    assert loaded.created_at == constructed.created_at
    assert loaded.created_at == at()
    assert raw(store, "SELECT created_at FROM expense_events")[0][0].endswith("+00:00")


def test_a_whole_second_timestamp_stores_six_fractional_digits(
    store: EventStore,
) -> None:
    a_flat(store)
    store.append_expense(an_expense(created_at=at()))
    stored = raw(store, "SELECT created_at FROM expense_events")[0][0]
    assert stored == "2026-09-03T10:00:00.000000+00:00"
    assert len(stored) == 32


def test_loading_re_checks_the_task_2_invariants(store: EventStore) -> None:
    a_flat(store)
    store.append_expense(an_expense())
    raw(
        store,
        "INSERT INTO expense_allocations (expense_id, position, member_id, cents) "
        "VALUES ('e1', 2, 'g1m3', 700)",
    )
    with pytest.raises(InvalidEvent):
        store.get_expense("e1")


def test_allocations_live_in_their_own_table_not_a_blob(store: EventStore) -> None:
    a_flat(store)
    store.append_expense(an_expense())
    columns = {row[1] for row in raw(store, "PRAGMA table_info(expense_allocations)")}
    assert columns == {"expense_id", "position", "member_id", "cents"}
    assert count(store, "expense_allocations") == 2


# --- Expense rejections -----------------------------------------------------


def test_a_duplicate_expense_id_leaves_the_stored_row_untouched(
    store: EventStore,
) -> None:
    a_flat(store)
    store.append_expense(an_expense(description="First"))
    before = raw(store, "SELECT * FROM expense_events")
    with pytest.raises(DuplicateRecord) as caught:
        store.append_expense(an_expense(description="Second", total_cents=4000))
    assert "e1" in str(caught.value)
    assert raw(store, "SELECT * FROM expense_events") == before
    assert count(store, "expense_events") == 1
    assert count(store, "expense_allocations") == 2


def test_an_expense_in_the_wrong_currency_raises_currency_mismatch(
    store: EventStore,
) -> None:
    a_flat(store, "g1", AUD)
    with pytest.raises(CurrencyMismatch) as caught:
        store.append_expense(an_expense(currency=NZD))
    assert "AUD" in str(caught.value)
    assert "NZD" in str(caught.value)
    assert count(store, "expense_events") == 0


def test_a_raw_insert_in_the_wrong_currency_is_rejected_by_the_foreign_key(
    store: EventStore,
) -> None:
    a_flat(store, "g1", AUD)
    with pytest.raises(sqlite3.IntegrityError):
        raw(
            store,
            "INSERT INTO expense_events (id, group_id, currency_code, payer_id, "
            "total_cents, description, created_at, created_by) "
            "VALUES ('e9', 'g1', 'NZD', 'g1m1', 1000, 'Sneaky', ?, 'g1m1')",
            (_STAMP,),
        )


def test_an_expense_for_an_unknown_group_is_rejected(store: EventStore) -> None:
    with pytest.raises(RecordNotFound):
        store.append_expense(an_expense(group_id="ghost"))


@pytest.mark.parametrize("field", ["payer_id", "created_by"])
def test_a_payer_or_author_from_another_group_is_rejected(
    store: EventStore, field: str
) -> None:
    a_flat(store, "g1", AUD)
    a_flat(store, "g2", NZD)
    with pytest.raises(ConstraintViolated):
        store.append_expense(an_expense(**{field: "g2m1"}))
    assert count(store, "expense_events") == 0


def test_an_allocation_member_from_another_group_is_rejected(store: EventStore) -> None:
    a_flat(store, "g1", AUD)
    a_flat(store, "g2", NZD)
    intruder = (
        Allocation(MemberId("g1m1"), 500),
        Allocation(MemberId("g2m1"), 500),
    )
    with pytest.raises(ConstraintViolated):
        store.append_expense(an_expense(allocations=intruder))
    assert count(store, "expense_events") == 0
    assert count(store, "expense_allocations") == 0


def test_a_raw_cross_group_allocation_is_rejected_by_the_database(
    store: EventStore,
) -> None:
    a_flat(store, "g1", AUD)
    a_flat(store, "g2", NZD)
    store.append_expense(an_expense())
    with pytest.raises(sqlite3.IntegrityError):
        raw(
            store,
            "INSERT INTO expense_allocations (expense_id, position, member_id, cents) "
            "VALUES ('e1', 7, 'g2m1', 0)",
        )


def test_a_failed_append_leaves_nothing_behind(store: EventStore) -> None:
    a_flat(store, "g1", AUD)
    a_flat(store, "g2", NZD)
    with pytest.raises(StoreError):
        store.append_expense(
            an_expense(
                allocations=(
                    Allocation(MemberId("g1m1"), 999),
                    Allocation(MemberId("g2m1"), 1),
                )
            )
        )
    assert raw(store, "SELECT * FROM expense_events WHERE id = 'e1'") == []
    assert raw(store, "SELECT * FROM expense_allocations WHERE expense_id = 'e1'") == []


# --- Append-only ------------------------------------------------------------


APPEND_ONLY_TABLES = [
    "expense_events",
    "expense_allocations",
    "settlement_events",
    "settlement_decision_events",
]


def test_a_raw_update_of_an_expense_is_rejected(store: EventStore) -> None:
    a_flat(store)
    store.append_expense(an_expense())
    before = raw(store, "SELECT * FROM expense_events")
    with pytest.raises(sqlite3.IntegrityError) as caught:
        raw(store, "UPDATE expense_events SET total_cents = 1 WHERE id = 'e1'")
    assert "expense_events" in str(caught.value)
    assert raw(store, "SELECT * FROM expense_events") == before


def test_a_raw_delete_of_an_expense_is_rejected(store: EventStore) -> None:
    a_flat(store)
    store.append_expense(an_expense())
    with pytest.raises(sqlite3.IntegrityError) as caught:
        raw(store, "DELETE FROM expense_events WHERE id = 'e1'")
    assert "expense_events" in str(caught.value)
    assert count(store, "expense_events") == 1


def test_a_raw_update_of_an_allocation_is_rejected(store: EventStore) -> None:
    a_flat(store)
    store.append_expense(an_expense())
    before = raw(store, "SELECT * FROM expense_allocations ORDER BY position")
    with pytest.raises(sqlite3.IntegrityError) as caught:
        raw(store, "UPDATE expense_allocations SET cents = 0")
    assert "expense_allocations" in str(caught.value)
    assert raw(store, "SELECT * FROM expense_allocations ORDER BY position") == before


def test_a_raw_delete_of_an_allocation_is_rejected(store: EventStore) -> None:
    a_flat(store)
    store.append_expense(an_expense())
    with pytest.raises(sqlite3.IntegrityError) as caught:
        raw(store, "DELETE FROM expense_allocations")
    assert "expense_allocations" in str(caught.value)
    assert count(store, "expense_allocations") == 2


def test_no_event_table_carries_a_mutable_bookkeeping_column(store: EventStore) -> None:
    forbidden = {"updated_at", "version", "is_deleted", "is_void", "revision"}
    for table in APPEND_ONLY_TABLES:
        columns = {row[1] for row in raw(store, f"PRAGMA table_info({table})")}
        assert not columns & forbidden, table


def test_no_table_stores_a_balance_or_a_running_total(store: EventStore) -> None:
    tables = raw(
        store,
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'",
    )
    for (table,) in tables:
        for row in raw(store, f"PRAGMA table_info({table})"):
            column = row[1]
            assert "balance" not in column, f"{table}.{column}"
            assert "running" not in column, f"{table}.{column}"
            assert not column.startswith("net_"), f"{table}.{column}"


# --- Listing and ordering ---------------------------------------------------


def test_list_expenses_is_empty_for_a_group_with_no_events(store: EventStore) -> None:
    a_flat(store)
    assert store.list_expenses("g1") == ()


def test_list_expenses_for_an_unknown_group_raises_not_found(store: EventStore) -> None:
    with pytest.raises(RecordNotFound) as caught:
        store.list_expenses("ghost")
    assert "ghost" in str(caught.value)


def test_list_expenses_is_in_ordering_key_order(store: EventStore) -> None:
    a_flat(store)
    written = [
        an_expense("e5", created_at=at(1)),
        an_expense("e1", created_at=at()),
        an_expense("e3", created_at=at()),
        an_expense("e2", created_at=at()),
        an_expense("e4", created_at=at(0, microsecond=1)),
    ]
    for expense in written:
        store.append_expense(expense)
    assert list(store.list_expenses("g1")) == sorted(written, key=ordering_key)


def test_each_group_reads_back_only_its_own_expenses(store: EventStore) -> None:
    a_flat(store, "g1", AUD)
    a_flat(store, "g2", NZD)
    store.append_expense(an_expense("e1", "g1", AUD, "g1m1", created_by="g1m1"))
    store.append_expense(an_expense("e2", "g2", NZD, "g2m1", created_by="g2m1"))
    assert [expense.id for expense in store.list_expenses("g1")] == ["e1"]
    assert [expense.id for expense in store.list_expenses("g2")] == ["e2"]
    assert store.list_expenses("g2")[0].currency == NZD


# --- Settlements and decisions ----------------------------------------------


def a_settlement(
    settlement_id: str = "s1",
    group_id: str = "g1",
    currency: Currency = AUD,
    from_member_id: str = "g1m1",
    to_member_id: str = "g1m2",
    amount_cents: int = 4000,
    created_at: datetime | None = None,
    created_by: str = "g1m1",
) -> SettlementEvent:
    """A settlement event, defaulting to $40 from the first member to the second."""
    return SettlementEvent(
        SettlementId(settlement_id),
        GroupId(group_id),
        currency,
        MemberId(from_member_id),
        MemberId(to_member_id),
        amount_cents,
        created_at if created_at is not None else at(),
        MemberId(created_by),
    )


def a_decision(
    decision_id: str = "d1",
    settlement_id: str = "s1",
    decision: SettlementState = SettlementState.CONFIRMED,
    decided_by: str = "g1m2",
    created_at: datetime | None = None,
) -> SettlementDecisionEvent:
    """A decision event, defaulting to the receiver confirming."""
    return SettlementDecisionEvent(
        decision_id,
        SettlementId(settlement_id),
        decision,
        MemberId(decided_by),
        created_at if created_at is not None else at(1),
    )


def test_a_settlement_round_trips_equal(store: EventStore) -> None:
    a_flat(store)
    settlement = a_settlement()
    store.append_settlement(settlement)
    assert store.list_settlements("g1") == (settlement,)


def test_a_settlement_in_the_wrong_currency_raises_currency_mismatch(
    store: EventStore,
) -> None:
    a_flat(store, "g1", AUD)
    with pytest.raises(CurrencyMismatch) as caught:
        store.append_settlement(a_settlement(currency=NZD))
    assert "AUD" in str(caught.value)
    assert "NZD" in str(caught.value)
    assert count(store, "settlement_events") == 0


@pytest.mark.parametrize("field", ["from_member_id", "to_member_id", "created_by"])
def test_a_settlement_naming_another_groups_member_is_rejected(
    store: EventStore, field: str
) -> None:
    a_flat(store, "g1", AUD)
    a_flat(store, "g2", NZD)
    with pytest.raises(ConstraintViolated):
        store.append_settlement(a_settlement(**{field: "g2m1"}))
    assert count(store, "settlement_events") == 0


def test_a_duplicate_settlement_id_leaves_the_stored_row_untouched(
    store: EventStore,
) -> None:
    a_flat(store)
    store.append_settlement(a_settlement())
    before = raw(store, "SELECT * FROM settlement_events")
    with pytest.raises(DuplicateRecord) as caught:
        store.append_settlement(a_settlement(amount_cents=9999))
    assert "s1" in str(caught.value)
    assert raw(store, "SELECT * FROM settlement_events") == before


def test_a_settlement_amount_above_the_bound_is_rejected(store: EventStore) -> None:
    a_flat(store)
    with pytest.raises(AmountTooLarge) as caught:
        store.append_settlement(a_settlement(amount_cents=MAX_CENTS + 1))
    assert "amount_cents" in str(caught.value)
    assert str(MAX_CENTS) in str(caught.value)
    assert count(store, "settlement_events") == 0


def test_the_largest_storable_settlement_round_trips(store: EventStore) -> None:
    a_flat(store)
    settlement = a_settlement(amount_cents=MAX_CENTS)
    store.append_settlement(settlement)
    assert store.list_settlements("g1")[0].amount_cents == MAX_CENTS


def test_list_settlements_is_scoped_and_ordered(store: EventStore) -> None:
    a_flat(store, "g1", AUD)
    a_flat(store, "g2", NZD)
    written = [
        a_settlement("s3", created_at=at(1)),
        a_settlement("s2", created_at=at()),
        a_settlement("s1", created_at=at()),
    ]
    for settlement in written:
        store.append_settlement(settlement)
    store.append_settlement(
        a_settlement("s9", "g2", NZD, "g2m1", "g2m2", created_by="g2m1")
    )
    assert list(store.list_settlements("g1")) == sorted(written, key=ordering_key)
    assert [event.id for event in store.list_settlements("g2")] == ["s9"]


def test_list_settlements_is_empty_for_a_group_with_none(store: EventStore) -> None:
    a_flat(store)
    assert store.list_settlements("g1") == ()


def test_list_settlements_for_an_unknown_group_raises_not_found(
    store: EventStore,
) -> None:
    with pytest.raises(RecordNotFound) as caught:
        store.list_settlements("ghost")
    assert "ghost" in str(caught.value)


def test_a_decision_round_trips_equal(store: EventStore) -> None:
    a_flat(store)
    store.append_settlement(a_settlement())
    decision = a_decision()
    store.append_settlement_decision(decision)
    assert store.list_settlement_decisions("s1") == (decision,)


def test_two_decisions_for_one_settlement_both_come_back_in_order(
    store: EventStore,
) -> None:
    a_flat(store)
    store.append_settlement(a_settlement())
    second = a_decision("d2", decision=SettlementState.REJECTED, created_at=at(3))
    first = a_decision("d1", decision=SettlementState.CONFIRMED, created_at=at(2))
    store.append_settlement_decision(second)
    store.append_settlement_decision(first)
    assert store.list_settlement_decisions("s1") == (first, second)


def test_a_decision_for_an_unknown_settlement_is_rejected(store: EventStore) -> None:
    a_flat(store)
    with pytest.raises(StoreError):
        store.append_settlement_decision(a_decision(settlement_id="ghost"))
    assert count(store, "settlement_decision_events") == 0


def test_a_decision_earlier_than_its_settlement_is_accepted(store: EventStore) -> None:
    a_flat(store)
    store.append_settlement(a_settlement(created_at=at(10)))
    early = a_decision(created_at=at())
    store.append_settlement_decision(early)
    assert store.list_settlement_decisions("s1") == (early,)


def test_a_pending_decision_cannot_be_constructed_or_stored(store: EventStore) -> None:
    a_flat(store)
    store.append_settlement(a_settlement())
    with pytest.raises(InvalidEvent):
        a_decision(decision=SettlementState.PENDING)
    with pytest.raises(sqlite3.IntegrityError):
        raw(
            store,
            "INSERT INTO settlement_decision_events (id, settlement_id, decision, "
            "decided_by, created_at) VALUES ('d9', 's1', 'PENDING', 'g1m2', ?)",
            (_STAMP,),
        )


def test_the_store_does_not_police_who_may_decide(store: EventStore) -> None:
    a_flat(store)
    store.append_settlement(a_settlement(from_member_id="g1m1", to_member_id="g1m2"))
    by_a_bystander = a_decision(decided_by="g1m3")
    store.append_settlement_decision(by_a_bystander)
    assert store.list_settlement_decisions("s1") == (by_a_bystander,)


def test_a_duplicate_decision_id_is_rejected(store: EventStore) -> None:
    a_flat(store)
    store.append_settlement(a_settlement())
    store.append_settlement_decision(a_decision())
    with pytest.raises(DuplicateRecord):
        store.append_settlement_decision(a_decision(decision=SettlementState.REJECTED))
    assert count(store, "settlement_decision_events") == 1


def test_list_settlement_decisions_is_empty_for_an_undecided_settlement(
    store: EventStore,
) -> None:
    a_flat(store)
    store.append_settlement(a_settlement())
    assert store.list_settlement_decisions("s1") == ()


def test_list_settlement_decisions_for_an_unknown_settlement_raises_not_found(
    store: EventStore,
) -> None:
    with pytest.raises(RecordNotFound) as caught:
        store.list_settlement_decisions("ghost")
    assert "ghost" in str(caught.value)


def test_a_raw_update_or_delete_of_a_settlement_is_rejected(store: EventStore) -> None:
    a_flat(store)
    store.append_settlement(a_settlement())
    with pytest.raises(sqlite3.IntegrityError) as updated:
        raw(store, "UPDATE settlement_events SET amount_cents = 1 WHERE id = 's1'")
    assert "settlement_events" in str(updated.value)
    with pytest.raises(sqlite3.IntegrityError) as deleted:
        raw(store, "DELETE FROM settlement_events WHERE id = 's1'")
    assert "settlement_events" in str(deleted.value)
    assert count(store, "settlement_events") == 1


def test_a_raw_update_or_delete_of_a_decision_is_rejected(store: EventStore) -> None:
    a_flat(store)
    store.append_settlement(a_settlement())
    store.append_settlement_decision(a_decision())
    with pytest.raises(sqlite3.IntegrityError) as updated:
        raw(store, "UPDATE settlement_decision_events SET decision = 'REJECTED'")
    assert "settlement_decision_events" in str(updated.value)
    with pytest.raises(sqlite3.IntegrityError) as deleted:
        raw(store, "DELETE FROM settlement_decision_events")
    assert "settlement_decision_events" in str(deleted.value)
    assert count(store, "settlement_decision_events") == 1


# --- The whole log ----------------------------------------------------------


def test_list_events_returns_all_three_kinds_in_ordering_key_order(
    store: EventStore,
) -> None:
    a_flat(store)
    expense = an_expense("e1", created_at=at(4))
    settlement = a_settlement("s1", created_at=at(2))
    decision = a_decision("d1", created_at=at(3))
    later_expense = an_expense("e2", created_at=at(4))
    store.append_expense(expense)
    store.append_settlement(settlement)
    store.append_settlement_decision(decision)
    store.append_expense(later_expense)
    written = [expense, settlement, decision, later_expense]
    assert list(store.list_events("g1")) == sorted(written, key=ordering_key)


def test_list_events_orders_a_shared_timestamp_by_id(store: EventStore) -> None:
    a_flat(store)
    store.append_settlement(a_settlement("s5", created_at=at()))
    store.append_expense(an_expense("e3", created_at=at()))
    store.append_settlement_decision(a_decision("d7", "s5", created_at=at()))
    assert [event.id for event in store.list_events("g1")] == ["d7", "e3", "s5"]


def test_list_events_reaches_decisions_through_their_settlement(
    store: EventStore,
) -> None:
    a_flat(store, "g1", AUD)
    a_flat(store, "g2", NZD)
    store.append_settlement(a_settlement("s1", "g1", AUD))
    store.append_settlement(
        a_settlement("s2", "g2", NZD, "g2m1", "g2m2", created_by="g2m1")
    )
    store.append_settlement_decision(a_decision("d1", "s1", decided_by="g1m2"))
    store.append_settlement_decision(a_decision("d2", "s2", decided_by="g2m2"))
    assert [event.id for event in store.list_events("g1")] == ["s1", "d1"]
    assert [event.id for event in store.list_events("g2")] == ["s2", "d2"]


def test_list_events_is_empty_for_a_group_with_no_events(store: EventStore) -> None:
    a_flat(store)
    assert store.list_events("g1") == ()


def test_list_events_for_an_unknown_group_raises_not_found(store: EventStore) -> None:
    with pytest.raises(RecordNotFound) as caught:
        store.list_events("ghost")
    assert "ghost" in str(caught.value)


def test_two_groups_keep_their_events_and_members_apart(store: EventStore) -> None:
    a_flat(store, "g1", AUD)
    a_flat(store, "g2", NZD)
    store.append_expense(an_expense("e1", "g1", AUD))
    store.append_expense(an_expense("e2", "g2", NZD, "g2m1", created_by="g2m1"))
    store.append_settlement(a_settlement("s1", "g1", AUD))
    store.append_settlement(
        a_settlement("s2", "g2", NZD, "g2m1", "g2m2", created_by="g2m1")
    )
    assert [event.id for event in store.list_events("g1")] == ["e1", "s1"]
    assert [event.id for event in store.list_events("g2")] == ["e2", "s2"]
    assert [member.id for member in store.list_members("g1")] == [
        "g1m1",
        "g1m2",
        "g1m3",
    ]
    assert store.get_group("g1").currency == AUD
    assert store.get_group("g2").currency == NZD


def test_every_read_returns_domain_objects_not_rows(store: EventStore) -> None:
    a_flat(store)
    store.append_expense(an_expense())
    store.append_settlement(a_settlement())
    store.append_settlement_decision(a_decision())
    store.add_user(User(UserId("u1"), "sam@example.com", "Sam", at()))
    assert isinstance(store.get_user(UserId("u1")), User)
    assert isinstance(store.get_group("g1"), Group)
    assert isinstance(store.get_member("g1m1"), Member)
    assert isinstance(store.get_expense("e1"), ExpenseEvent)
    for reader, expected in [
        (store.list_groups(), Group),
        (store.list_members("g1"), Member),
        (store.list_expenses("g1"), ExpenseEvent),
        (store.list_settlements("g1"), SettlementEvent),
        (store.list_settlement_decisions("s1"), SettlementDecisionEvent),
    ]:
        assert isinstance(reader, tuple)
        assert reader
        for item in reader:
            assert isinstance(item, expected)
            assert not isinstance(item, (tuple, dict, list, sqlite3.Row))
    for event in store.list_events("g1"):
        assert isinstance(
            event, (ExpenseEvent, SettlementEvent, SettlementDecisionEvent)
        )
        assert not isinstance(event, (tuple, dict, sqlite3.Row))


# --- Indexes and query plans ------------------------------------------------


def plan(store: EventStore, sql: str, params: tuple[object, ...]) -> str:
    """The EXPLAIN QUERY PLAN detail lines for ``sql``, joined into one string."""
    return "\n".join(row[3] for row in raw(store, "EXPLAIN QUERY PLAN " + sql, params))


def test_the_named_indexes_all_exist(store: EventStore) -> None:
    names = {
        row[0]
        for row in raw(store, "SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    assert {
        "idx_expense_events_group_order",
        "idx_settlement_events_group_order",
        "idx_settlement_decisions_settlement_order",
        "idx_expense_allocations_member",
        "idx_members_group",
    } <= names


def test_the_ordered_expense_read_is_served_by_its_index(store: EventStore) -> None:
    a_flat(store)
    detail = plan(store, store_module._SELECT_EXPENSES_BY_GROUP, ("g1",))
    assert "idx_expense_events_group_order" in detail
    assert "USE TEMP B-TREE FOR ORDER BY" not in detail


def test_the_ordered_settlement_read_is_served_by_its_index(store: EventStore) -> None:
    a_flat(store)
    detail = plan(store, store_module._SELECT_SETTLEMENTS_BY_GROUP, ("g1",))
    assert "idx_settlement_events_group_order" in detail
    assert "USE TEMP B-TREE FOR ORDER BY" not in detail


def test_the_ordered_decision_read_is_served_by_its_index(store: EventStore) -> None:
    a_flat(store)
    detail = plan(store, store_module._SELECT_DECISIONS_BY_SETTLEMENT, ("s1",))
    assert "idx_settlement_decisions_settlement_order" in detail
    assert "USE TEMP B-TREE FOR ORDER BY" not in detail


# --- Durability and concurrency ---------------------------------------------


def test_data_survives_close_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    expense = an_expense()
    settlement = a_settlement()
    decision = a_decision()
    with open_store(path) as writer:
        a_flat(writer)
        writer.append_expense(expense)
        writer.append_settlement(settlement)
        writer.append_settlement_decision(decision)
    with open_store(path) as reader:
        assert reader.get_expense("e1") == expense
        assert reader.list_events("g1") == (expense, settlement, decision)
        assert [member.id for member in reader.list_members("g1")] == [
            "g1m1",
            "g1m2",
            "g1m3",
        ]


def test_reopening_does_not_re_run_destructive_ddl(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    with open_store(path) as writer:
        a_flat(writer)
        writer.append_expense(an_expense())
        tables = count_tables(writer)
    for _ in range(3):
        with open_store(path) as reopened:
            assert count(reopened, "expense_events") == 1
            assert count_tables(reopened) == tables
            assert raw(reopened, "PRAGMA user_version")[0][0] == SCHEMA_VERSION


def test_two_stores_on_one_file_can_both_append(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    with open_store(path) as one, open_store(path) as two:
        a_flat(one)
        one.append_expense(an_expense("e1", created_at=at()))
        two.append_expense(an_expense("e2", created_at=at(1)))
        two.append_settlement(a_settlement("s1", created_at=at(2)))
        assert [event.id for event in one.list_events("g1")] == ["e1", "e2", "s1"]
        assert [event.id for event in two.list_events("g1")] == ["e1", "e2", "s1"]


def test_opening_one_fresh_file_from_two_stores_leaves_one_valid_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    with open_store(path) as one, open_store(path) as two:
        assert raw(one, "PRAGMA integrity_check")[0][0] == "ok"
        assert raw(two, "PRAGMA user_version")[0][0] == SCHEMA_VERSION
        # Seven from task 6, plus user_credentials and sessions from task 7.
        assert count_tables(two) == 9
        a_flat(two)
        assert [member.id for member in one.list_members("g1")] == [
            "g1m1",
            "g1m2",
            "g1m3",
        ]


def test_two_identical_runs_produce_byte_identical_databases(tmp_path: Path) -> None:
    def build(name: str) -> Path:
        path = tmp_path / name
        with open_store(path) as writer:
            a_flat(writer)
            writer.append_expense(an_expense())
            writer.append_settlement(a_settlement())
            writer.append_settlement_decision(a_decision())
        return path

    assert build("one.sqlite3").read_bytes() == build("two.sqlite3").read_bytes()


def test_no_column_takes_its_value_from_the_clock(store: EventStore) -> None:
    schema = " ".join(
        row[0] for row in raw(store, "SELECT sql FROM sqlite_master WHERE sql NOT NULL")
    ).upper()
    assert "DEFAULT" not in schema
    assert "CURRENT_TIMESTAMP" not in schema


# --- What the module itself may contain -------------------------------------


def store_source() -> str:
    return Path(store_module.__file__).read_text(encoding="utf-8")


def sql_literals() -> list[str]:
    """Every string literal in store.py that is not a docstring.

    Docstrings are the string constants that stand alone as an expression statement,
    which is also how the module documents its constants. Everything else is either a
    statement the store issues or a message it raises, and those are what the rules
    below are about.
    """
    tree = ast.parse(store_source())
    documentation = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in documentation
    ]


@pytest.mark.parametrize(
    "forbidden",
    [
        r"\bUPDATE\s+(expense_events|expense_allocations|settlement_events"
        r"|settlement_decision_events)\b",
        # Narrowed by task 7 from a blanket ban on DELETE FROM to the four event
        # tables. A session is operational state, not history: logging out deletes
        # the row, and that is correct behaviour rather than a rewrite of history.
        r"\bDELETE\s+FROM\s+(expense_events|expense_allocations"
        r"|settlement_events|settlement_decision_events)\b",
        r"\bINSERT\s+OR\s+(REPLACE|IGNORE)\b",
        r"\bREPLACE\s+INTO\b",
        r"\bON\s+CONFLICT\b",
    ],
)
def test_the_module_issues_no_statement_that_could_rewrite_history(
    forbidden: str,
) -> None:
    for literal in sql_literals():
        assert re.search(forbidden, literal, re.IGNORECASE) is None, literal


def test_the_narrowed_delete_rule_still_bites_on_the_event_tables() -> None:
    """The only table any DELETE FROM in this module names is ``sessions``.

    The companion to the narrowing above. Relaxing a blanket ban has to leave the
    append-only guarantee exactly where it was, so this reads back every table a
    DELETE names rather than trusting one pattern to have caught the right ones.
    """
    deleted: set[str] = set()
    for literal in sql_literals():
        deleted.update(
            match.group(1)
            for match in re.finditer(
                r"\bDELETE\s+FROM\s+(\w+)", literal, re.IGNORECASE
            )
        )
    assert deleted == {"sessions"}
    tables = "|".join(APPEND_ONLY_TABLES)
    for literal in sql_literals():
        for forbidden in (
            rf"\bDELETE\s+FROM\s+({tables})\b",
            rf"\bREPLACE\s+INTO\s+({tables})\b",
            rf"\bINSERT\s+OR\s+(REPLACE|IGNORE)\s+INTO\s+({tables})\b",
            rf"\bUPDATE\s+({tables})\b",
            r"\bON\s+CONFLICT\b",
        ):
            assert re.search(forbidden, literal, re.IGNORECASE) is None, literal


@pytest.mark.parametrize(
    "forbidden",
    ["register_adapter", "register_converter", "detect_types", "PARSE_DECLTYPES"],
)
def test_the_module_registers_no_type_adapters(forbidden: str) -> None:
    assert forbidden not in store_source()


@pytest.mark.parametrize("forbidden", ["now(", "utcnow(", "time.time", "today("])
def test_the_module_never_reads_the_clock(forbidden: str) -> None:
    assert forbidden not in store_source()


def test_the_module_does_no_floating_point_arithmetic() -> None:
    tree = ast.parse(store_source())
    for node in ast.walk(tree):
        assert not isinstance(node, ast.Constant) or not isinstance(
            node.value, float
        ), ast.dump(node)
        if isinstance(node, ast.BinOp):
            assert not isinstance(node.op, ast.Div), ast.dump(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"float", "round"}, ast.dump(node)


def test_a_round_trip_raises_no_deprecation_warning(tmp_path: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with open_store(tmp_path / "ledger.sqlite3") as opened:
            a_flat(opened)
            opened.append_expense(an_expense())
            opened.append_settlement(a_settlement())
            opened.append_settlement_decision(a_decision())
            opened.get_expense("e1")
            opened.list_events("g1")


def test_the_project_still_declares_no_runtime_dependency() -> None:
    root = Path(store_module.__file__).parents[2]
    manifest = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest["project"]["dependencies"] == []
    assert manifest["dependency-groups"] == {"dev": ["pytest>=8.0"]}


def test_the_store_is_re_exported_from_the_package_root() -> None:
    import splitwise_lite

    assert splitwise_lite.open_store is open_store
    assert splitwise_lite.EventStore is EventStore
    assert splitwise_lite.__version__ == "0.1.0"
    for name in ("User", "Group", "Member", "UserId", "StoreError"):
        assert name in splitwise_lite.__all__


# --- The shape of the public surface ----------------------------------------


WRITES = [
    "add_user",
    "add_group",
    "add_member",
    "append_expense",
    "append_settlement",
    "append_settlement_decision",
    # Task 7.
    "add_user_with_credential",
    "set_password_hash",
    "add_session",
    "delete_session",
    "delete_sessions_for_user",
    "delete_expired_sessions",
]

READS = [
    "get_user",
    "get_group",
    "list_groups",
    "get_member",
    "list_members",
    "get_expense",
    "list_expenses",
    "list_settlements",
    "list_settlement_decisions",
    "list_events",
    # Task 7.
    "get_user_by_email",
    "get_password_hash",
    "get_session",
    "get_member_for_user",
]


def test_the_public_surface_is_exactly_the_named_methods() -> None:
    public = {name for name in dir(EventStore) if not name.startswith("_")}
    assert public == set(WRITES) | set(READS) | {"close"}


def test_every_public_method_has_a_docstring() -> None:
    for name in WRITES + READS + ["close"]:
        assert getattr(EventStore, name).__doc__, name
    assert EventStore.__doc__
    assert open_store.__doc__


def test_open_store_has_no_default_path() -> None:
    parameters = inspect.signature(open_store).parameters
    assert list(parameters) == ["path"]
    assert parameters["path"].default is inspect.Parameter.empty


def test_every_public_method_refuses_a_closed_store(tmp_path: Path) -> None:
    """Every method with its own arguments, so the list stays exhaustive.

    Task 7's methods do not all take one record or one group id, so the old
    one-argument-for-everything shape could not reach them. Widened rather than
    narrowed: each name below is called the way a caller would call it.
    """
    opened = open_store(tmp_path / "ledger.sqlite3")
    a_flat(opened)
    arguments: dict[str, tuple[object, ...]] = {
        "add_user": (User(UserId("u1"), "sam@example.com", "Sam", at()),),
        "add_group": (Group("g9", "Flat", AUD, at()),),
        "add_member": (Member("m9", "g1", "Sam", None, at()),),
        "append_expense": (an_expense(),),
        "append_settlement": (a_settlement(),),
        "append_settlement_decision": (a_decision(),),
        "add_user_with_credential": (
            User(UserId("u2"), "other@example.com", "Other", at()),
            A_HASH,
            at(),
        ),
        "set_password_hash": (UserId("u1"), A_HASH, at()),
        "add_session": (a_session(),),
        "delete_session": (TOKEN_HASH,),
        "delete_sessions_for_user": (UserId("u1"),),
        "delete_expired_sessions": (at(),),
        "get_user": (UserId("u1"),),
        "get_group": ("g1",),
        "list_groups": (),
        "get_member": ("g1m1",),
        "list_members": ("g1",),
        "get_expense": ("e1",),
        "list_expenses": ("g1",),
        "list_settlements": ("g1",),
        "list_settlement_decisions": ("s1",),
        "list_events": ("g1",),
        "get_user_by_email": ("sam@example.com",),
        "get_password_hash": (UserId("u1"),),
        "get_session": (TOKEN_HASH,),
        "get_member_for_user": ("g1", UserId("u1")),
    }
    assert set(arguments) == set(WRITES) | set(READS)
    opened.close()
    for name, values in arguments.items():
        with pytest.raises(StoreClosed):
            getattr(opened, name)(*values)


def test_every_statement_the_store_issues_is_a_constant_with_bound_parameters() -> None:
    """No SQL is assembled at the call site, so no value can be interpolated into it."""
    tree = ast.parse(store_source())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executescript", "executemany"}
    ]
    assert calls
    for call in calls:
        statement = call.args[0]
        assert isinstance(statement, (ast.Name, ast.Constant)), ast.dump(call)
        if isinstance(statement, ast.Constant):
            assert isinstance(statement.value, str)
        for argument in call.args[1:]:
            assert isinstance(argument, ast.Call), ast.dump(call)
            assert isinstance(argument.func, ast.Name)
            assert argument.func.id == "_params", ast.dump(call)


def test_the_user_id_type_lives_here_and_not_in_events() -> None:
    assert not hasattr(events_module, "UserId")
    assert "UserId" not in events_module.__all__
    assert UserId("u1") == "u1"


def test_membership_is_a_flat_list_with_no_dates(store: EventStore) -> None:
    columns = {row[1] for row in raw(store, "PRAGMA table_info(members)")}
    assert columns == {"id", "group_id", "display_name", "user_id", "created_at"}
    assert not columns & {"joined_at", "left_at", "is_active", "until", "since"}
    tables = {
        row[0]
        for row in raw(
            store,
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'",
        )
    }
    assert tables == {
        "users",
        "groups",
        "members",
        "expense_events",
        "expense_allocations",
        "settlement_events",
        "settlement_decision_events",
        # Task 7's two tables. The members columns above are unchanged by it:
        # the membership list stays flat, with no joined_at, left_at or is_active.
        "user_credentials",
        "sessions",
    }


def test_a_sqlite_failure_leaves_a_public_method_as_a_store_error(
    store: EventStore,
) -> None:
    a_flat(store)
    raw(store, "DROP TABLE expense_events")
    with pytest.raises(StorageFailed) as caught:
        store.list_expenses("g1")
    assert isinstance(caught.value.__cause__, sqlite3.Error)
    assert not isinstance(caught.value, sqlite3.Error)


def test_open_store_rejects_a_path_that_is_not_a_path(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        open_store(1)


def test_a_busy_database_surfaces_as_a_store_error(tmp_path: Path) -> None:
    """A second writer that cannot get the lock still leaves through StoreError."""
    path = tmp_path / "ledger.sqlite3"
    with open_store(path) as holder, open_store(path) as blocked:
        a_flat(holder)
        raw(blocked, "PRAGMA busy_timeout = 0")
        raw(holder, "BEGIN IMMEDIATE")
        raw(
            holder,
            "INSERT INTO groups (id, name, currency_code, created_at) "
            "VALUES ('g2', 'Trip', 'NZD', ?)",
            (_STAMP,),
        )
        try:
            with pytest.raises(StorageFailed) as caught:
                blocked.append_expense(an_expense())
            assert isinstance(caught.value.__cause__, sqlite3.Error)
        finally:
            raw(holder, "ROLLBACK")
        blocked.append_expense(an_expense())
        assert blocked.get_expense("e1").total_cents == 1000


def test_a_float_in_any_field_is_refused_before_it_is_bound(store: EventStore) -> None:
    """The bind guard, not the cents check: description is never checked as a number."""
    a_flat(store)
    corrupted = an_expense()
    object.__setattr__(corrupted, "description", 12.5)
    with pytest.raises(TypeError):
        store.append_expense(corrupted)
    assert count(store, "expense_events") == 0


@pytest.mark.parametrize(
    "value", [12.5, 12.0, b"bytes", at(), SettlementState.CONFIRMED]
)
def test_only_text_integers_and_null_may_be_bound(value: object) -> None:
    with pytest.raises(TypeError):
        store_module._params("ok", 1, None, value)
    assert store_module._params("ok", 1, None) == ("ok", 1, None)


def test_a_bool_is_not_bound_as_an_integer() -> None:
    with pytest.raises(TypeError):
        store_module._params(True)


# --- Gaps the audit found ---------------------------------------------------


class _FailingConnection:
    """A connection stand-in whose close() fails, which a real one rarely does."""

    def close(self) -> None:
        raise sqlite3.OperationalError("unable to close due to unfinalized statements")


def test_a_failure_to_close_is_a_store_error_and_still_closes(tmp_path: Path) -> None:
    opened = open_store(tmp_path / "ledger.sqlite3")
    opened._connection = _FailingConnection()
    with pytest.raises(StorageFailed) as caught:
        opened.close()
    assert isinstance(caught.value.__cause__, sqlite3.Error)
    with pytest.raises(StoreClosed):
        opened.list_groups()
    opened.close()


def test_an_append_runs_inside_one_immediate_transaction(store: EventStore) -> None:
    """Traced statements, not a grep: the append really opens BEGIN IMMEDIATE."""
    a_flat(store)
    traced: list[str] = []
    store._connection.set_trace_callback(traced.append)
    try:
        store.append_expense(an_expense(total_cents=999))
    finally:
        store._connection.set_trace_callback(None)
    assert traced[0] == "BEGIN IMMEDIATE"
    assert traced[-1] == "COMMIT"
    assert traced.count("BEGIN IMMEDIATE") == 1
    assert traced.count("COMMIT") == 1
    assert any("INSERT INTO expense_events" in line for line in traced)
    assert any("INSERT INTO expense_allocations" in line for line in traced)
    assert count(store, "expense_allocations") == 2


def test_a_rolled_back_append_traces_a_rollback_and_no_commit(
    store: EventStore,
) -> None:
    a_flat(store, "g1", AUD)
    a_flat(store, "g2", NZD)
    traced: list[str] = []
    store._connection.set_trace_callback(traced.append)
    try:
        with pytest.raises(StoreError):
            store.append_expense(
                an_expense(
                    allocations=(
                        Allocation(MemberId("g1m1"), 999),
                        Allocation(MemberId("g2m1"), 1),
                    )
                )
            )
    finally:
        store._connection.set_trace_callback(None)
    assert traced[0] == "BEGIN IMMEDIATE"
    assert traced[-1] == "ROLLBACK"
    assert "COMMIT" not in traced


def test_the_currency_trigger_fires_for_a_group_that_has_expenses(
    store: EventStore,
) -> None:
    a_flat(store, "g1", AUD)
    store.append_expense(an_expense())
    assert count(store, "expense_events") == 1
    with pytest.raises(sqlite3.IntegrityError):
        raw(store, "UPDATE groups SET currency_code = 'NZD' WHERE id = 'g1'")
    assert store.get_group("g1").currency == AUD
    assert store.get_expense("e1").currency == AUD


def test_a_raw_settlement_in_the_wrong_currency_is_rejected_by_the_foreign_key(
    store: EventStore,
) -> None:
    a_flat(store, "g1", AUD)
    with pytest.raises(sqlite3.IntegrityError) as caught:
        raw(
            store,
            "INSERT INTO settlement_events (id, group_id, currency_code, "
            "from_member_id, to_member_id, amount_cents, created_at, created_by) "
            "VALUES ('s9', 'g1', 'NZD', 'g1m1', 'g1m2', 4000, ?, 'g1m1')",
            (_STAMP,),
        )
    assert "FOREIGN KEY" in str(caught.value)


def test_a_duplicate_decision_leaves_the_stored_row_untouched(
    store: EventStore,
) -> None:
    a_flat(store)
    store.append_settlement(a_settlement())
    store.append_settlement_decision(a_decision(decision=SettlementState.CONFIRMED))
    before = raw(store, "SELECT * FROM settlement_decision_events")
    with pytest.raises(DuplicateRecord) as caught:
        store.append_settlement_decision(
            a_decision(decision=SettlementState.REJECTED, decided_by="g1m3")
        )
    assert "d1" in str(caught.value)
    assert raw(store, "SELECT * FROM settlement_decision_events") == before
    stored = store.list_settlement_decisions("s1")
    assert stored[0].decision is SettlementState.CONFIRMED


EXPECTED_COLUMNS = {
    "users": ["id", "email", "display_name", "created_at"],
    "groups": ["id", "name", "currency_code", "created_at"],
    "members": ["id", "group_id", "display_name", "user_id", "created_at"],
    "expense_events": [
        "id",
        "group_id",
        "currency_code",
        "payer_id",
        "total_cents",
        "description",
        "created_at",
        "created_by",
    ],
    "expense_allocations": ["expense_id", "position", "member_id", "cents"],
    "settlement_events": [
        "id",
        "group_id",
        "currency_code",
        "from_member_id",
        "to_member_id",
        "amount_cents",
        "created_at",
        "created_by",
    ],
    "settlement_decision_events": [
        "id",
        "settlement_id",
        "decision",
        "decided_by",
        "created_at",
    ],
    "user_credentials": ["user_id", "password_hash", "updated_at"],
    "sessions": ["token_hash", "user_id", "created_at", "expires_at"],
}


@pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS))
def test_each_table_holds_exactly_the_columns_the_schema_names(
    store: EventStore, table: str
) -> None:
    """Exact columns, in order, so any added column fails rather than any named one.

    This is what keeps "no stored balance", "no updated_at" and "no dated membership"
    honest: a column called total_owed or cached_sum would slip past a substring scan.
    """
    columns = [row[1] for row in raw(store, f"PRAGMA table_info({table})")]
    assert columns == EXPECTED_COLUMNS[table]


BADLY_SHAPED_TIMESTAMPS = [
    "2026-09-03T10:00:00+00:00",
    "2026-09-03T10:00:00.000000+10:00",
    "2026-09-03T10:00:00.00+00:00",
    "2026-09-03 10:00:00.000000+00:00",
]


@pytest.mark.parametrize("bad", BADLY_SHAPED_TIMESTAMPS)
def test_the_timestamp_check_rejects_a_shape_that_would_not_sort(
    store: EventStore, bad: str
) -> None:
    a_group(store, "g1")
    with pytest.raises(sqlite3.IntegrityError):
        raw(
            store,
            "INSERT INTO members (id, group_id, display_name, user_id, created_at) "
            "VALUES ('mx', 'g1', 'Sam', NULL, ?)",
            (bad,),
        )
    assert count(store, "members") == 0


def test_no_deprecation_warning_from_any_public_method(tmp_path: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with open_store(tmp_path / "ledger.sqlite3") as opened:
            a_flat(opened)
            opened.add_user(User(UserId("u1"), "sam@example.com", "Sam", at()))
            opened.append_expense(an_expense())
            opened.append_settlement(a_settlement())
            opened.append_settlement_decision(a_decision())
            opened.get_user(UserId("u1"))
            opened.get_group("g1")
            opened.list_groups()
            opened.get_member("g1m1")
            opened.list_members("g1")
            opened.get_expense("e1")
            opened.list_expenses("g1")
            opened.list_settlements("g1")
            opened.list_settlement_decisions("s1")
            opened.list_events("g1")


def test_the_store_does_not_create_the_directory_it_was_pointed_at(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nope" / "ledger.sqlite3"
    with pytest.raises(CannotOpenStore):
        open_store(path)
    assert not path.parent.exists()
    assert not path.exists()


@pytest.mark.parametrize(
    "documented",
    [
        User,
        Group,
        Member,
        Session,
        StoreError,
        CannotOpenStore,
        UnsupportedSQLiteVersion,
        UnsupportedSchemaVersion,
        StoreClosed,
        InvalidRecord,
        RecordNotFound,
        DuplicateRecord,
        ConstraintViolated,
        StorageFailed,
        AmountTooLarge,
    ],
)
def test_every_public_class_has_a_docstring(documented: type) -> None:
    assert documented.__doc__


# --- Task 7: credentials, sessions and the user-to-member link ---------------
#
# The schema at version 2, the ten methods it adds, and the read that turns a
# signed-in user into the member acting in a group. Hashing, tokens and password
# policy are tested in tests/test_accounts.py: no value below is a password, and
# the hashes here are shaped like real ones only so the column CHECK admits them.

A_HASH = "scrypt$n=65536,r=8,p=2$" + "A" * 24 + "$" + "B" * 44
ANOTHER_HASH = "scrypt$n=65536,r=8,p=2$" + "C" * 24 + "$" + "D" * 44
TOKEN_HASH = "a" * 64
OTHER_TOKEN_HASH = "b" * 64
THIRD_TOKEN_HASH = "c" * 64
_LATER_STAMP = "2026-09-03T10:01:00.000000+00:00"

_INSERT_CREDENTIAL_SQL = (
    "INSERT INTO user_credentials (user_id, password_hash, updated_at) "
    "VALUES (?, ?, ?)"
)
_INSERT_SESSION_SQL = (
    "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
    "VALUES (?, ?, ?, ?)"
)


def a_user(
    store: EventStore, user_id: str = "u1", email: str = "sam@example.com"
) -> User:
    """Add and return a user that has no credential row."""
    user = User(UserId(user_id), email, f"Name {user_id}", at())
    store.add_user(user)
    return user


def a_session(
    token_hash: str = TOKEN_HASH,
    user_id: str = "u1",
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> Session:
    """A session for ``user_id``, live from the base time for one minute."""
    return Session(
        token_hash,
        UserId(user_id),
        at() if created_at is None else created_at,
        at(60) if expires_at is None else expires_at,
    )


def test_session_is_frozen_slotted_and_compares_by_value() -> None:
    assert Session.__dataclass_params__.frozen is True
    assert Session.__slots__
    assert a_session() == a_session()
    assert a_session() != a_session(OTHER_TOKEN_HASH)


def test_session_holds_the_hash_and_never_the_raw_token() -> None:
    assert tuple(Session.__slots__) == (
        "token_hash",
        "user_id",
        "created_at",
        "expires_at",
    )


@pytest.mark.parametrize("bad", ["", "a" * 63, "a" * 65, "A" * 64, "z" * 64])
def test_session_rejects_a_token_hash_that_is_not_64_lowercase_hex(bad: str) -> None:
    with pytest.raises(InvalidRecord):
        a_session(token_hash=bad)


def test_session_rejects_a_token_hash_that_is_not_a_string() -> None:
    with pytest.raises(TypeError):
        a_session(token_hash=1)  # type: ignore[arg-type]


def test_session_timestamps_are_normalised_to_utc() -> None:
    brisbane = timezone(timedelta(hours=10))
    session = a_session(
        created_at=datetime(2026, 9, 3, 20, 0, tzinfo=brisbane),
        expires_at=datetime(2026, 10, 3, 20, 0, tzinfo=brisbane),
    )
    assert session.created_at == at()
    assert session.created_at.utcoffset() == timedelta(0)
    assert session.expires_at.utcoffset() == timedelta(0)


def test_session_rejects_a_naive_timestamp() -> None:
    with pytest.raises(InvalidRecord):
        a_session(created_at=datetime(2026, 9, 3, 10, 0))
    with pytest.raises(InvalidRecord):
        a_session(expires_at=datetime(2026, 9, 3, 11, 0))


@pytest.mark.parametrize("expires_at", [at(), at(-1)])
def test_session_must_expire_after_it_was_created(expires_at: datetime) -> None:
    with pytest.raises(InvalidRecord):
        a_session(created_at=at(), expires_at=expires_at)


# --- The schema at version 2 -------------------------------------------------


@pytest.mark.parametrize("table", ["user_credentials", "sessions"])
def test_the_new_tables_are_strict_and_carry_no_default(
    store: EventStore, table: str
) -> None:
    sql = raw(store, "SELECT sql FROM sqlite_master WHERE name = ?", (table,))[0][0]
    assert sql.rstrip().rstrip(";").upper().endswith("STRICT")
    assert "DEFAULT" not in sql.upper()


@pytest.mark.parametrize("plaintext", ["correct horse battery staple", "p" * 80])
def test_the_password_column_refuses_a_plaintext_password(
    store: EventStore, plaintext: str
) -> None:
    """The tripwire against the worst bug in task 7, enforced by the database.

    A plaintext password is either shorter than 60 characters or has no ``$`` in
    it, and the CHECK wants both, so no plausible one can be stored as a hash.
    """
    a_user(store)
    with pytest.raises(sqlite3.IntegrityError):
        raw(store, _INSERT_CREDENTIAL_SQL, ("u1", plaintext, _STAMP))
    assert count(store, "user_credentials") == 0


def test_a_token_hash_of_the_wrong_length_is_rejected(store: EventStore) -> None:
    a_user(store)
    for bad in ("short", "a" * 63, "a" * 65):
        with pytest.raises(sqlite3.IntegrityError):
            raw(store, _INSERT_SESSION_SQL, (bad, "u1", _STAMP, _LATER_STAMP))
    assert count(store, "sessions") == 0


def test_a_session_that_expires_before_it_starts_is_rejected(
    store: EventStore,
) -> None:
    a_user(store)
    with pytest.raises(sqlite3.IntegrityError):
        raw(store, _INSERT_SESSION_SQL, (TOKEN_HASH, "u1", _LATER_STAMP, _STAMP))
    with pytest.raises(sqlite3.IntegrityError):
        raw(store, _INSERT_SESSION_SQL, (TOKEN_HASH, "u1", _STAMP, _STAMP))
    assert count(store, "sessions") == 0


def test_a_credential_or_session_for_an_unknown_user_is_refused_by_the_database(
    store: EventStore,
) -> None:
    """Not only by Python: the foreign key is what makes an orphan impossible."""
    with pytest.raises(sqlite3.IntegrityError):
        raw(store, _INSERT_CREDENTIAL_SQL, ("ghost", A_HASH, _STAMP))
    with pytest.raises(sqlite3.IntegrityError):
        raw(store, _INSERT_SESSION_SQL, (TOKEN_HASH, "ghost", _STAMP, _LATER_STAMP))


@pytest.mark.parametrize("bad", BADLY_SHAPED_TIMESTAMPS)
def test_the_new_tables_reject_a_timestamp_shape_that_would_not_sort(
    store: EventStore, bad: str
) -> None:
    a_user(store)
    with pytest.raises(sqlite3.IntegrityError):
        raw(store, _INSERT_CREDENTIAL_SQL, ("u1", A_HASH, bad))
    with pytest.raises(sqlite3.IntegrityError):
        raw(store, _INSERT_SESSION_SQL, (TOKEN_HASH, "u1", _STAMP, bad))
    assert count(store, "user_credentials") == 0
    assert count(store, "sessions") == 0


def test_the_session_indexes_exist(store: EventStore) -> None:
    names = {
        row[0]
        for row in raw(store, "SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    assert {"idx_sessions_user", "idx_sessions_expires_at"} <= names


def test_opening_a_version_3_database_still_raises(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    with open_store(path) as opened:
        raw(opened, "PRAGMA user_version = 3")
    with pytest.raises(UnsupportedSchemaVersion) as caught:
        open_store(path)
    assert "3" in str(caught.value)


V1_SCHEMA_SQL = """
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
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00'
           AND substr(created_at, 11, 1) = 'T')
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
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00'
           AND substr(created_at, 11, 1) = 'T')
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
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00'
           AND substr(created_at, 11, 1) = 'T')
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
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00'
           AND substr(created_at, 11, 1) = 'T'),
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
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00'
           AND substr(created_at, 11, 1) = 'T'),
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
    CHECK (length(created_at) = 32 AND created_at LIKE '%+00:00'
           AND substr(created_at, 11, 1) = 'T')
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
"""Task 6's schema text, verbatim, as it stood when it wrote version 1.

Embedded rather than imported, because the point of the upgrade test is to build a
database this code did not create. The test below asserts every statement of it is
still present in the current schema, so a drift in the copy is caught rather than
quietly weakening the upgrade it is meant to prove.
"""


def creates(script: str) -> list[str]:
    """Every CREATE statement in ``script``, in order, as written.

    Split on the semicolon, which shreds a trigger body into its parts; only the
    fragment that starts with CREATE is kept, so what is compared is a whole table,
    index or trigger head rather than a stray END or a bare RAISE.
    """
    return [
        statement.strip()
        for statement in script.split(";")
        if statement.strip().upper().startswith("CREATE")
    ]


def test_version_2_only_adds_to_task_sixs_schema() -> None:
    """Every statement task 6 wrote is still here, and version 2 adds exactly four.

    Two tables and two indexes. If this fails, the embedded v1 text has drifted from
    what task 6 actually wrote, and the upgrade test below is proving nothing.
    """
    current = store_module._SCHEMA_SQL
    before = creates(V1_SCHEMA_SQL)
    assert len(creates(current)) == len(before) + 4
    for statement in before:
        assert statement in current, statement
    for statement in V1_SCHEMA_SQL.split(";"):
        statement = statement.strip()
        if statement and not statement.startswith("PRAGMA user_version"):
            assert statement in current, statement


def test_a_version_1_database_upgrades_in_place_and_keeps_every_row(
    tmp_path: Path,
) -> None:
    """The upgrade path, proven on a database task 6's code wrote, not a fresh one.

    Every statement in the schema is IF NOT EXISTS and open_store re-runs the whole
    script whenever the stored user_version is behind, so bumping the trailing
    PRAGMA is the migration. This is the test that fails if it were written as a
    fresh-database-only path.
    """
    path = tmp_path / "ledger.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(V1_SCHEMA_SQL)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        connection.execute(
            "INSERT INTO users (id, email, display_name, created_at) "
            "VALUES ('u1', 'sam@example.com', 'Sam', ?)",
            (_STAMP,),
        )
        connection.execute(
            "INSERT INTO groups (id, name, currency_code, created_at) "
            "VALUES ('g1', 'Flat g1', 'AUD', ?)",
            (_STAMP,),
        )
        for member_id, user_id in (("g1m1", "u1"), ("g1m2", None), ("g1m3", None)):
            connection.execute(
                "INSERT INTO members (id, group_id, display_name, user_id, created_at) "
                "VALUES (?, 'g1', ?, ?, ?)",
                (member_id, f"Name {member_id}", user_id, _STAMP),
            )
        connection.execute(
            "INSERT INTO expense_events (id, group_id, currency_code, payer_id, "
            "total_cents, description, created_at, created_by) "
            "VALUES ('e1', 'g1', 'AUD', 'g1m1', 1000, 'Dinner', ?, 'g1m1')",
            (_STAMP,),
        )
        for position, member_id in enumerate(("g1m1", "g1m2")):
            connection.execute(
                "INSERT INTO expense_allocations (expense_id, position, member_id, "
                "cents) VALUES ('e1', ?, ?, 500)",
                (position, member_id),
            )
        connection.execute(
            "INSERT INTO settlement_events (id, group_id, currency_code, "
            "from_member_id, to_member_id, amount_cents, created_at, created_by) "
            "VALUES ('s1', 'g1', 'AUD', 'g1m1', 'g1m2', 4000, ?, 'g1m1')",
            (_LATER_STAMP,),
        )
        connection.execute(
            "INSERT INTO settlement_decision_events (id, settlement_id, decision, "
            "decided_by, created_at) VALUES ('d1', 's1', 'CONFIRMED', 'g1m2', ?)",
            (_LATER_STAMP,),
        )
    finally:
        connection.close()

    with open_store(path) as upgraded:
        assert raw(upgraded, "PRAGMA user_version")[0][0] == SCHEMA_VERSION == 2
        tables = {
            row[0]
            for row in raw(
                upgraded,
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'",
            )
        }
        assert {"user_credentials", "sessions"} <= tables
        assert upgraded.get_user(UserId("u1")) == User(
            UserId("u1"), "sam@example.com", "Sam", at()
        )
        assert upgraded.get_user_by_email("sam@example.com").id == "u1"
        assert upgraded.get_group("g1") == Group("g1", "Flat g1", AUD, at())
        assert [member.id for member in upgraded.list_members("g1")] == [
            "g1m1",
            "g1m2",
            "g1m3",
        ]
        assert upgraded.get_member("g1m1").user_id == "u1"
        assert upgraded.get_member_for_user("g1", UserId("u1")).id == "g1m1"
        expense = upgraded.get_expense("e1")
        assert expense.total_cents == 1000
        assert expense.allocations == (
            Allocation(MemberId("g1m1"), 500),
            Allocation(MemberId("g1m2"), 500),
        )
        # The settlement and its decision share a timestamp: the id breaks the tie.
        assert [event.id for event in upgraded.list_events("g1")] == ["e1", "d1", "s1"]
        assert upgraded.list_settlements("g1")[0].amount_cents == 4000
        assert upgraded.list_settlement_decisions("s1")[0].decision is (
            SettlementState.CONFIRMED
        )
        assert count(upgraded, "user_credentials") == 0
        assert count(upgraded, "sessions") == 0
        upgraded.set_password_hash(UserId("u1"), A_HASH, at())
        upgraded.add_session(a_session())
        assert upgraded.get_session(TOKEN_HASH).user_id == "u1"


# --- Credentials -------------------------------------------------------------


def test_a_user_and_a_credential_are_written_in_one_call(store: EventStore) -> None:
    user = User(UserId("u1"), "sam@example.com", "Sam", at())
    store.add_user_with_credential(user, A_HASH, at())
    assert store.get_user(UserId("u1")) == user
    assert store.get_user_by_email("sam@example.com") == user
    assert store.get_password_hash(UserId("u1")) == A_HASH
    assert raw(store, "SELECT updated_at FROM user_credentials") == [(_STAMP,)]


def test_a_failed_credential_write_leaves_no_user_and_no_taken_address(
    store: EventStore,
) -> None:
    user = User(UserId("u1"), "sam@example.com", "Sam", at())
    with pytest.raises(ConstraintViolated):
        store.add_user_with_credential(user, "not a hash", at())
    assert count(store, "users") == 0
    assert count(store, "user_credentials") == 0
    store.add_user_with_credential(user, A_HASH, at())
    assert store.get_user_by_email("sam@example.com") == user


def test_add_user_with_credential_rejects_a_taken_id_or_address(
    store: EventStore,
) -> None:
    first = User(UserId("u1"), "sam@example.com", "Sam", at())
    store.add_user_with_credential(first, A_HASH, at())
    with pytest.raises(DuplicateRecord) as by_id:
        store.add_user_with_credential(
            User(UserId("u1"), "other@example.com", "Other", at()), ANOTHER_HASH, at()
        )
    assert "u1" in str(by_id.value)
    with pytest.raises(DuplicateRecord) as by_email:
        store.add_user_with_credential(
            User(UserId("u2"), "sam@example.com", "Other", at()), ANOTHER_HASH, at()
        )
    assert "sam@example.com" in str(by_email.value)
    assert store.get_password_hash(UserId("u1")) == A_HASH
    assert count(store, "users") == 1
    assert count(store, "user_credentials") == 1


def test_add_user_with_credential_takes_a_user(store: EventStore) -> None:
    with pytest.raises(TypeError):
        store.add_user_with_credential("u1", A_HASH, at())  # type: ignore[arg-type]


def test_get_user_by_email_raises_not_found_naming_the_address(
    store: EventStore,
) -> None:
    with pytest.raises(RecordNotFound) as caught:
        store.get_user_by_email("ghost@example.com")
    assert "ghost@example.com" in str(caught.value)


def test_get_password_hash_raises_not_found_for_a_user_with_no_credential(
    store: EventStore,
) -> None:
    """Task 6's add_user is still on the surface, so this state is reachable."""
    a_user(store)
    with pytest.raises(RecordNotFound) as caught:
        store.get_password_hash(UserId("u1"))
    assert "u1" in str(caught.value)
    with pytest.raises(RecordNotFound):
        store.get_password_hash(UserId("ghost"))


def test_get_password_hash_returns_the_string_it_was_given(store: EventStore) -> None:
    a_user(store)
    store.set_password_hash(UserId("u1"), A_HASH, at())
    stored = store.get_password_hash(UserId("u1"))
    assert isinstance(stored, str)
    assert stored == A_HASH


def test_set_password_hash_inserts_on_first_use_and_updates_after(
    store: EventStore,
) -> None:
    a_user(store)
    store.set_password_hash(UserId("u1"), A_HASH, at())
    assert store.get_password_hash(UserId("u1")) == A_HASH
    store.set_password_hash(UserId("u1"), ANOTHER_HASH, at(60))
    assert store.get_password_hash(UserId("u1")) == ANOTHER_HASH
    assert count(store, "user_credentials") == 1
    assert raw(store, "SELECT updated_at FROM user_credentials") == [(_LATER_STAMP,)]


def test_set_password_hash_deletes_every_session_that_user_holds(
    store: EventStore,
) -> None:
    a_user(store)
    a_user(store, "u2", "other@example.com")
    store.add_user_with_credential(
        User(UserId("u3"), "third@example.com", "Third", at()), A_HASH, at()
    )
    store.add_session(a_session(TOKEN_HASH, "u1"))
    store.add_session(a_session(OTHER_TOKEN_HASH, "u1"))
    store.add_session(a_session(THIRD_TOKEN_HASH, "u2"))
    store.set_password_hash(UserId("u1"), A_HASH, at())
    assert count(store, "sessions") == 1
    assert store.get_session(THIRD_TOKEN_HASH).user_id == "u2"
    assert store.get_password_hash(UserId("u3")) == A_HASH


def test_setting_a_hash_and_revoking_a_session_is_one_transaction(
    store: EventStore,
) -> None:
    """Traced statements, not a grep: both writes are inside one BEGIN IMMEDIATE."""
    a_user(store)
    store.add_session(a_session())
    traced: list[str] = []
    store._connection.set_trace_callback(traced.append)
    try:
        store.set_password_hash(UserId("u1"), A_HASH, at())
    finally:
        store._connection.set_trace_callback(None)
    assert traced[0] == "BEGIN IMMEDIATE"
    assert traced[-1] == "COMMIT"
    assert traced.count("BEGIN IMMEDIATE") == 1
    assert traced.count("COMMIT") == 1
    assert any("INSERT INTO user_credentials" in line for line in traced)
    assert any("DELETE FROM sessions" in line for line in traced)


def test_a_failure_on_the_second_write_rolls_the_first_one_back(
    store: EventStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction of the same transaction.

    The test below forces the failure on the credential write. This one points the
    revocation at a table that is not there, so the credential write has already
    succeeded when the transaction fails and the rollback has something to undo.
    """
    a_user(store)
    store.set_password_hash(UserId("u1"), A_HASH, at())
    store.add_session(a_session())
    monkeypatch.setattr(
        store_module,
        "_DELETE_SESSIONS_FOR_USER",
        "DELETE FROM a_table_that_is_not_there WHERE user_id = ?",
    )
    with pytest.raises(StorageFailed):
        store.set_password_hash(UserId("u1"), ANOTHER_HASH, at(60))
    monkeypatch.undo()
    assert store.get_password_hash(UserId("u1")) == A_HASH
    assert raw(store, "SELECT updated_at FROM user_credentials") == [(_STAMP,)]
    assert store.get_session(TOKEN_HASH) == a_session()


def test_set_password_hash_for_an_unknown_user_is_refused(store: EventStore) -> None:
    with pytest.raises(StoreError) as caught:
        store.set_password_hash(UserId("ghost"), A_HASH, at())
    assert not isinstance(caught.value, sqlite3.Error)
    assert count(store, "user_credentials") == 0


def test_a_refused_hash_leaves_the_stored_hash_and_the_sessions_alone(
    store: EventStore,
) -> None:
    """The rollback covers both halves: a failed update revokes nothing."""
    a_user(store)
    store.set_password_hash(UserId("u1"), A_HASH, at())
    store.add_session(a_session())
    with pytest.raises(ConstraintViolated):
        store.set_password_hash(UserId("u1"), "not a hash", at(60))
    assert store.get_password_hash(UserId("u1")) == A_HASH
    assert store.get_session(TOKEN_HASH) == a_session()


# --- Sessions ----------------------------------------------------------------


def test_a_session_round_trips(store: EventStore) -> None:
    a_user(store)
    session = a_session()
    store.add_session(session)
    assert store.get_session(TOKEN_HASH) == session


def test_a_duplicate_token_hash_is_rejected_and_overwrites_nothing(
    store: EventStore,
) -> None:
    """At 256 bits a collision means the random source is broken. Do not retry it."""
    a_user(store)
    a_user(store, "u2", "other@example.com")
    store.add_session(a_session())
    with pytest.raises(DuplicateRecord) as caught:
        store.add_session(a_session(TOKEN_HASH, "u2", at(1), at(120)))
    assert TOKEN_HASH in str(caught.value)
    assert store.get_session(TOKEN_HASH) == a_session()
    assert count(store, "sessions") == 1


def test_a_session_for_an_unknown_user_is_rejected(store: EventStore) -> None:
    with pytest.raises(StoreError) as caught:
        store.add_session(a_session())
    assert not isinstance(caught.value, sqlite3.Error)
    assert count(store, "sessions") == 0


def test_add_session_takes_a_session(store: EventStore) -> None:
    with pytest.raises(TypeError):
        store.add_session(TOKEN_HASH)  # type: ignore[arg-type]


def test_get_session_raises_not_found_naming_the_hash(store: EventStore) -> None:
    with pytest.raises(RecordNotFound) as caught:
        store.get_session(TOKEN_HASH)
    assert TOKEN_HASH in str(caught.value)


def test_several_live_sessions_for_one_user_are_normal(store: EventStore) -> None:
    a_user(store)
    store.add_session(a_session(TOKEN_HASH))
    store.add_session(a_session(OTHER_TOKEN_HASH))
    assert store.get_session(TOKEN_HASH).user_id == "u1"
    assert store.get_session(OTHER_TOKEN_HASH).user_id == "u1"
    assert count(store, "sessions") == 2


def test_delete_session_is_idempotent_and_reports_what_it_deleted(
    store: EventStore,
) -> None:
    a_user(store)
    store.add_session(a_session(TOKEN_HASH))
    store.add_session(a_session(OTHER_TOKEN_HASH))
    assert store.delete_session(TOKEN_HASH) == 1
    assert store.delete_session(TOKEN_HASH) == 0
    assert store.delete_session("f" * 64) == 0
    with pytest.raises(RecordNotFound):
        store.get_session(TOKEN_HASH)
    assert store.get_session(OTHER_TOKEN_HASH).user_id == "u1"


def test_delete_sessions_for_user_counts_and_leaves_other_users_alone(
    store: EventStore,
) -> None:
    a_user(store)
    a_user(store, "u2", "other@example.com")
    store.add_session(a_session(TOKEN_HASH, "u1"))
    store.add_session(a_session(OTHER_TOKEN_HASH, "u1"))
    store.add_session(a_session(THIRD_TOKEN_HASH, "u2"))
    assert store.delete_sessions_for_user(UserId("u1")) == 2
    assert store.delete_sessions_for_user(UserId("u1")) == 0
    assert store.get_session(THIRD_TOKEN_HASH).user_id == "u2"
    assert count(store, "sessions") == 1


def test_delete_sessions_for_an_unknown_user_raises_not_found(
    store: EventStore,
) -> None:
    with pytest.raises(RecordNotFound) as caught:
        store.delete_sessions_for_user(UserId("ghost"))
    assert "ghost" in str(caught.value)


def test_delete_expired_sessions_removes_rows_at_or_before_now(
    store: EventStore,
) -> None:
    a_user(store)
    store.add_session(a_session(TOKEN_HASH, expires_at=at(60)))
    store.add_session(a_session(OTHER_TOKEN_HASH, expires_at=at(120)))
    assert store.delete_expired_sessions(at(30)) == 0
    assert store.delete_expired_sessions(at(60)) == 1
    with pytest.raises(RecordNotFound):
        store.get_session(TOKEN_HASH)
    assert store.get_session(OTHER_TOKEN_HASH).expires_at == at(120)
    assert store.delete_expired_sessions(at(600)) == 1
    assert count(store, "sessions") == 0


def test_delete_expired_sessions_takes_a_timezone_aware_datetime(
    store: EventStore,
) -> None:
    with pytest.raises(TypeError):
        store.delete_expired_sessions("2026-09-03")  # type: ignore[arg-type]
    with pytest.raises(InvalidRecord):
        store.delete_expired_sessions(datetime(2026, 9, 3, 10, 0))


# --- The user-to-member link -------------------------------------------------


def test_get_member_for_user_returns_the_linked_member(store: EventStore) -> None:
    a_group(store)
    a_user(store)
    linked = a_member(store, "m1", "g1", "u1")
    assert store.get_member_for_user("g1", UserId("u1")) == linked


def test_get_member_for_user_never_returns_another_groups_member(
    store: EventStore,
) -> None:
    a_group(store, "g1")
    a_group(store, "g2", NZD)
    a_user(store)
    a_member(store, "m1", "g1", "u1")
    a_member(store, "m2", "g2", "u1")
    assert store.get_member_for_user("g1", UserId("u1")).id == "m1"
    assert store.get_member_for_user("g2", UserId("u1")).id == "m2"


def test_get_member_for_user_never_returns_an_unlinked_member(
    store: EventStore,
) -> None:
    a_group(store)
    a_user(store)
    a_member(store, "m1", "g1", None)
    with pytest.raises(RecordNotFound):
        store.get_member_for_user("g1", UserId("u1"))


def test_get_member_for_user_raises_not_found_naming_both_ids(
    store: EventStore,
) -> None:
    """A signed-in user who is not in this group is a legitimate state, not a bug."""
    a_group(store)
    a_user(store)
    with pytest.raises(RecordNotFound) as caught:
        store.get_member_for_user("g1", UserId("u1"))
    assert "g1" in str(caught.value)
    assert "u1" in str(caught.value)


def test_get_member_for_user_for_an_unknown_group_raises_not_found(
    store: EventStore,
) -> None:
    a_user(store)
    with pytest.raises(RecordNotFound) as caught:
        store.get_member_for_user("ghost", UserId("u1"))
    assert "ghost" in str(caught.value)
