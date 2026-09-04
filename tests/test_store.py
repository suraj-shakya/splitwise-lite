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
import re
import sqlite3
import tomllib
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
    assert [member.display_name for member in store.list_members("g1")] == ["Sam", "Sam"]


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
    "read", ["get_user", "get_group", "get_member", "list_members"]
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
    assert isinstance(store.get_group("g1"), Group)
    assert isinstance(store.get_member("g1m1"), Member)
    assert isinstance(store.get_expense("e1"), ExpenseEvent)
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
        tables = raw(
            writer, "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
        )[0][0]
    for _ in range(3):
        with open_store(path) as reopened:
            assert count(reopened, "expense_events") == 1
            assert (
                raw(reopened, "SELECT count(*) FROM sqlite_master WHERE type = 'table'")[
                    0
                ][0]
                == tables
            )
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
        tables = raw(
            two, "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
        )[0][0]
        assert tables == 7
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
        r"\bDELETE\s+FROM\b",
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
