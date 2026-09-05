"""Tests for group and member setup.

Task 9 of plans/backlog.md, sharpened in plans/tasks/09-group-and-member-setup.md.

Everything here calls Python functions. There is no HTTP layer in this repo and this
task does not add one: the operator command that wraps these functions is tested in
tests/test_setup_group_cli.py.

The reconcile and link tests run twice, once against an in-memory store and once
against a file-backed store under ``tmp_path``, from the one ``store`` fixture and the
one test body, matching task 6. Nothing in this file hardcodes a group id: every id
comes back from ``apply_group_definition`` or ``new_id()``.
"""

from __future__ import annotations

import ast
import tomllib
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from splitwise_lite import accounts as accounts_module
from splitwise_lite import events as events_module
from splitwise_lite import groups as groups_module
from splitwise_lite import money as money_module
from splitwise_lite import store as store_module
from splitwise_lite.accounts import ScryptParams, sign_up
from splitwise_lite.events import GroupId, MemberId, new_id
from splitwise_lite.groups import (
    MAX_MEMBERS,
    AmbiguousGroup,
    GroupDefinition,
    GroupMismatch,
    GroupSetupError,
    InvalidGroupDefinition,
    MemberAlreadyLinked,
    MemberNotLinked,
    NoGroupConfigured,
    SetupResult,
    UserAlreadyLinked,
    acting_member,
    apply_group_definition,
    link_user_to_member,
    load_group_definition,
    parse_group_definition,
    resolve_sole_group,
)
from splitwise_lite.money import Currency, DomainError
from splitwise_lite.store import (
    IN_MEMORY,
    EventStore,
    Group,
    InvalidRecord,
    Member,
    RecordNotFound,
    User,
    UserId,
    open_store,
)

REPO = Path(__file__).resolve().parents[1]

AUD = Currency("AUD")
NZD = Currency("NZD")

T0 = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)

ROSTER = ("Sam", "Ali", "Jo", "Kit")

PUBLIC = {
    "MAX_MEMBERS",
    "AmbiguousGroup",
    "GroupDefinition",
    "GroupMismatch",
    "GroupSetupError",
    "InvalidGroupDefinition",
    "MemberAlreadyLinked",
    "MemberNotLinked",
    "NoGroupConfigured",
    "SetupResult",
    "UserAlreadyLinked",
    "acting_member",
    "apply_group_definition",
    "link_user_to_member",
    "load_group_definition",
    "parse_group_definition",
    "resolve_sole_group",
}

EXAMPLE_TOML = """
name = "Flat 3"
currency = "AUD"
members = ["Sam", "Ali", "Jo", "Kit"]
"""


def at(seconds: int = 0, *, microseconds: int = 0) -> datetime:
    """A UTC timestamp ``seconds`` after the fixed base time."""
    return T0 + timedelta(seconds=seconds, microseconds=microseconds)


def groups_source() -> str:
    return Path(groups_module.__file__).read_text(encoding="utf-8")


@pytest.fixture(params=["memory", "file"])
def store(request: pytest.FixtureRequest, tmp_path: Path):
    """An open store, once in memory and once backed by a file under ``tmp_path``."""
    target = IN_MEMORY if request.param == "memory" else tmp_path / "ledger.sqlite3"
    with open_store(target) as opened:
        yield opened


@pytest.fixture
def params() -> ScryptParams:
    """Deliberately cheap scrypt parameters, matching task 7's fixture.

    No test in this task is about the key derivation function, and paying the real
    cost here would add minutes to the suite without covering anything.
    """
    return ScryptParams(n=16, r=1, p=1)


def a_definition(
    members: tuple[str, ...] = ROSTER,
    name: str = "Flat 3",
    currency: Currency = AUD,
) -> GroupDefinition:
    """The roster the tests apply, built without touching the filesystem."""
    return GroupDefinition(name, currency, members)


def names(members: tuple[Member, ...]) -> tuple[str, ...]:
    """The display names of ``members``, in the order they were given."""
    return tuple(member.display_name for member in members)


# --- The shape of the module -------------------------------------------------


def test_the_public_surface_is_exactly_the_named_names() -> None:
    assert set(groups_module.__all__) == PUBLIC
    assert len(groups_module.__all__) == len(PUBLIC)
    for name in PUBLIC:
        assert hasattr(groups_module, name), name


def test_everything_else_the_module_defines_is_underscored() -> None:
    tree = ast.parse(groups_source())
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
    assert {name for name in defined if not name.startswith("_")} == PUBLIC


def test_every_public_name_has_a_docstring() -> None:
    """Tasks 10, 11, 12, 14 and 15 are written against these."""
    tree = ast.parse(groups_source())
    documented: set[str] = set()
    previous: ast.stmt | None = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and ast.get_docstring(
            node
        ):
            documented.add(node.name)
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            if isinstance(previous, ast.AnnAssign) and isinstance(
                previous.target, ast.Name
            ):
                documented.add(previous.target.id)
            elif isinstance(previous, ast.Assign):
                documented.update(
                    target.id
                    for target in previous.targets
                    if isinstance(target, ast.Name)
                )
        previous = node
    assert PUBLIC <= documented
    assert groups_module.__doc__


@pytest.mark.parametrize(
    "stated",
    ["TOML", "idempot", "one group", "links nothing automatically"],
)
def test_the_module_docstring_states_the_rules_it_is_read_for(stated: str) -> None:
    assert groups_module.__doc__ is not None
    assert stated in groups_module.__doc__


@pytest.mark.parametrize(
    "forbidden",
    [
        "sqlite3",
        "SELECT ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "CREATE TABLE",
        "PRAGMA",
        "execute(",
        "user_credentials",
        "sessions",
        "expense_events",
        "expense_allocations",
        "settlement_events",
        "settlement_decision_events",
    ],
)
def test_the_module_writes_no_sql_and_names_no_table(forbidden: str) -> None:
    assert forbidden not in groups_source()


@pytest.mark.parametrize(
    "forbidden",
    [
        "argparse",
        "print(",
        "sys.stdout",
        "sys.stderr",
        "import http",
        "wsgi",
        "asgi",
        "cookie",
        "Cookie",
        "flask",
        "django",
        "fastapi",
        "route",
        "socket",
        "request",
    ],
)
def test_the_module_has_no_command_line_or_http_surface(forbidden: str) -> None:
    """A library. The command is scripts/setup_group.py and no screen calls it."""
    assert forbidden not in groups_source()


@pytest.mark.parametrize("forbidden", ["now(", "utcnow(", "time.time", "today("])
def test_the_module_never_reads_the_clock(forbidden: str) -> None:
    assert forbidden not in groups_source()


def test_the_dependency_direction_stays_one_way() -> None:
    tree = ast.parse(groups_source())
    within_the_package = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 1
    }
    assert within_the_package == {"events", "money", "store"}
    for module in (store_module, events_module, money_module, accounts_module):
        other = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(other):
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or "groups" not in node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert "groups" not in alias.name


def test_the_module_never_imports_accounts() -> None:
    assert "accounts" not in groups_source()


def test_nothing_is_read_at_import_time() -> None:
    """No default path, no environment variable and no search of the directory."""
    source = groups_source()
    assert "environ" not in source
    assert "getenv" not in source
    assert "cwd(" not in source
    assert "glob" not in source


def test_every_storage_function_takes_the_store_first() -> None:
    import inspect

    for name in (
        "apply_group_definition",
        "resolve_sole_group",
        "link_user_to_member",
        "acting_member",
    ):
        parameters = list(
            inspect.signature(getattr(groups_module, name)).parameters
        )
        assert parameters[0] == "store", name


def test_the_errors_are_one_family_under_domain_error() -> None:
    assert issubclass(GroupSetupError, DomainError)
    for error in (
        InvalidGroupDefinition,
        NoGroupConfigured,
        AmbiguousGroup,
        GroupMismatch,
        MemberAlreadyLinked,
        UserAlreadyLinked,
        MemberNotLinked,
    ):
        assert issubclass(error, GroupSetupError), error


def test_the_module_is_re_exported_from_the_package_root() -> None:
    import splitwise_lite

    for name in PUBLIC:
        assert name in splitwise_lite.__all__, name
        assert getattr(splitwise_lite, name) is getattr(groups_module, name), name
    assert splitwise_lite.__version__ == "0.1.0"
    assert splitwise_lite.__doc__ is not None
    assert "groups" in splitwise_lite.__doc__


# --- The definition value ----------------------------------------------------


def test_the_definition_is_frozen_slotted_and_compares_by_value() -> None:
    assert GroupDefinition.__dataclass_params__.frozen is True
    assert GroupDefinition.__slots__
    assert a_definition() == a_definition()
    assert a_definition() != a_definition(("Sam", "Ali"))


def test_the_definition_holds_names_a_currency_and_nothing_else() -> None:
    """No id, no email address, no password, no date, no role and no flag."""
    assert [field for field in GroupDefinition.__dataclass_fields__] == [
        "name",
        "currency",
        "members",
    ]


def test_the_definition_keeps_its_members_in_file_order() -> None:
    assert a_definition().members == ROSTER


def test_a_member_name_is_stripped() -> None:
    assert a_definition((" Sam ", "Ali")).members == ("Sam", "Ali")


def test_a_blank_group_name_is_refused() -> None:
    with pytest.raises(InvalidGroupDefinition):
        a_definition(name="   ")


def test_a_group_name_over_a_hundred_characters_is_refused() -> None:
    with pytest.raises(InvalidGroupDefinition):
        a_definition(name="F" * 101)
    assert a_definition(name="F" * 100).name == "F" * 100


def test_a_blank_member_name_is_refused() -> None:
    with pytest.raises(InvalidGroupDefinition):
        a_definition(("Sam", " "))


def test_a_member_name_over_a_hundred_characters_is_refused() -> None:
    with pytest.raises(InvalidGroupDefinition):
        a_definition(("Sam", "A" * 101))
    assert a_definition(("Sam", "A" * 100)).members == ("Sam", "A" * 100)


def test_a_definition_with_no_members_is_refused() -> None:
    """An empty roster is a file someone forgot to finish."""
    with pytest.raises(InvalidGroupDefinition):
        a_definition(())


def test_max_members_is_fifty_and_is_enforced() -> None:
    assert MAX_MEMBERS == 50
    just_enough = tuple(f"Name {index}" for index in range(MAX_MEMBERS))
    assert len(a_definition(just_enough).members) == MAX_MEMBERS
    with pytest.raises(InvalidGroupDefinition) as caught:
        a_definition(just_enough + ("One too many",))
    assert str(MAX_MEMBERS) in str(caught.value)


def test_two_names_that_casefold_equal_are_refused_and_the_message_says_what_to_do(
) -> None:
    with pytest.raises(InvalidGroupDefinition) as caught:
        a_definition(("Sam", "sam"))
    message = str(caught.value)
    assert "Sam" in message
    assert "Sam K" in message and "Sam T" in message


def test_two_names_that_differ_only_by_unicode_normalisation_are_refused() -> None:
    composed = unicodedata.normalize("NFC", "Zoë")
    decomposed = unicodedata.normalize("NFD", "Zoë")
    assert composed != decomposed
    with pytest.raises(InvalidGroupDefinition) as caught:
        a_definition((composed, decomposed))
    assert "Zo" in str(caught.value)


def test_a_wrong_python_type_raises_type_error() -> None:
    with pytest.raises(TypeError):
        GroupDefinition(3, AUD, ROSTER)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        GroupDefinition("Flat 3", "AUD", ROSTER)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        GroupDefinition("Flat 3", AUD, ["Sam"])  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        GroupDefinition("Flat 3", AUD, (1, 2))  # type: ignore[arg-type]


# --- Reading a definition file -----------------------------------------------


def test_parse_returns_the_same_value_a_file_does(tmp_path: Path) -> None:
    path = tmp_path / "group.toml"
    path.write_text(EXAMPLE_TOML, encoding="utf-8")
    assert parse_group_definition(EXAMPLE_TOML) == a_definition()
    assert load_group_definition(path) == a_definition()
    assert load_group_definition(str(path)) == a_definition()


def test_a_comment_and_a_trailing_comma_are_accepted() -> None:
    text = """
    # Kit moved in April
    name = "Flat 3"
    currency = "AUD"
    members = [
        "Sam",
        "Ali",
    ]
    """
    assert parse_group_definition(text).members == ("Sam", "Ali")


@pytest.mark.parametrize("missing", ["name", "currency", "members"])
def test_a_missing_key_is_named(missing: str) -> None:
    lines = [
        line
        for line in EXAMPLE_TOML.strip().splitlines()
        if not line.startswith(missing)
    ]
    with pytest.raises(InvalidGroupDefinition) as caught:
        parse_group_definition("\n".join(lines))
    assert missing in str(caught.value)


def test_an_unknown_key_is_named_rather_than_ignored() -> None:
    """``currancy = "AUD"`` is an error, not a silent default."""
    with pytest.raises(InvalidGroupDefinition) as caught:
        parse_group_definition('name = "Flat 3"\ncurrancy = "AUD"\nmembers = ["Sam"]')
    assert "currancy" in str(caught.value)


def test_a_lowercase_currency_is_refused_and_the_message_names_the_fix() -> None:
    with pytest.raises(InvalidGroupDefinition) as caught:
        parse_group_definition('name = "Flat 3"\ncurrency = "aud"\nmembers = ["Sam"]')
    assert "AUD" in str(caught.value)


@pytest.mark.parametrize(
    "currency",
    ['"AUDD"', '"AU"', '"A1D"', "3", "true", '["AUD"]'],
)
def test_a_currency_that_is_not_three_uppercase_letters_is_refused(
    currency: str,
) -> None:
    with pytest.raises(InvalidGroupDefinition):
        parse_group_definition(
            f'name = "Flat 3"\ncurrency = {currency}\nmembers = ["Sam"]'
        )


@pytest.mark.parametrize(
    "members",
    ['"Sam"', "3", "{ one = 1 }", '["Sam", 3]', '[["Sam"]]', "[]"],
)
def test_members_must_be_an_array_of_strings(members: str) -> None:
    with pytest.raises(InvalidGroupDefinition) as caught:
        parse_group_definition(
            f'name = "Flat 3"\ncurrency = "AUD"\nmembers = {members}'
        )
    assert "members" in str(caught.value)


def test_a_group_name_that_is_not_a_string_is_refused() -> None:
    with pytest.raises(InvalidGroupDefinition) as caught:
        parse_group_definition('name = 3\ncurrency = "AUD"\nmembers = ["Sam"]')
    assert "name" in str(caught.value)


def test_malformed_toml_carries_the_decode_error_as_its_cause(tmp_path: Path) -> None:
    path = tmp_path / "group.toml"
    path.write_text('name = "Flat 3\n', encoding="utf-8")
    with pytest.raises(InvalidGroupDefinition) as caught:
        load_group_definition(path)
    assert str(path) in str(caught.value)
    assert isinstance(caught.value.__cause__, tomllib.TOMLDecodeError)


def test_no_tomllib_exception_escapes_parse() -> None:
    with pytest.raises(InvalidGroupDefinition) as caught:
        parse_group_definition('name = "Flat 3')
    assert not isinstance(caught.value, tomllib.TOMLDecodeError)
    assert isinstance(caught.value.__cause__, tomllib.TOMLDecodeError)


def test_a_path_that_does_not_exist_is_named(tmp_path: Path) -> None:
    path = tmp_path / "absent.toml"
    with pytest.raises(InvalidGroupDefinition) as caught:
        load_group_definition(path)
    assert str(path) in str(caught.value)
    assert not isinstance(caught.value, OSError)


def test_a_directory_is_named_rather_than_raising_an_os_error(tmp_path: Path) -> None:
    with pytest.raises(InvalidGroupDefinition) as caught:
        load_group_definition(tmp_path)
    assert str(tmp_path) in str(caught.value)
    assert not isinstance(caught.value, OSError)


def test_a_path_of_the_wrong_type_raises_type_error() -> None:
    with pytest.raises(TypeError):
        load_group_definition(3)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        parse_group_definition(3)  # type: ignore[arg-type]


def test_a_byte_order_mark_is_tolerated(tmp_path: Path) -> None:
    """A plain Windows editor writes one, and tomllib's message names no fix."""
    path = tmp_path / "group.toml"
    path.write_text(EXAMPLE_TOML, encoding="utf-8-sig")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert load_group_definition(path) == a_definition()
    assert parse_group_definition("﻿" + EXAMPLE_TOML) == a_definition()


def test_neither_reader_has_a_default_path() -> None:
    import inspect

    for function in (parse_group_definition, load_group_definition):
        parameters = list(inspect.signature(function).parameters.values())
        assert len(parameters) == 1
        assert parameters[0].default is inspect.Parameter.empty


def test_the_committed_example_file_parses_and_has_at_least_two_members() -> None:
    definition = load_group_definition(REPO / "group.example.toml")
    assert len(definition.members) >= 2
    assert definition.currency == AUD


def test_a_file_that_is_not_utf_8_is_named_rather_than_raising_a_decode_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "group.toml"
    path.write_bytes(b'name = "Flat \xff3"\n')
    with pytest.raises(InvalidGroupDefinition) as caught:
        load_group_definition(path)
    assert str(path) in str(caught.value)
    assert not isinstance(caught.value, UnicodeDecodeError)


# --- Applying a definition ---------------------------------------------------


TABLES_APPLY_NEVER_WRITES = (
    "users",
    "user_credentials",
    "sessions",
    "expense_events",
    "expense_allocations",
    "settlement_events",
    "settlement_decision_events",
)


def count(store: EventStore, table: str) -> int:
    """Row count of ``table``, read with raw SQL past the public API."""
    return store._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def rows(store: EventStore, table: str) -> list[tuple]:
    """Every row of ``table`` exactly as stored, for a byte-for-byte comparison."""
    return store._connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()


def a_second_group(
    store: EventStore, name: str = "Flat 4", currency: Currency = NZD
) -> Group:
    """Add an empty group with an id from ``new_id()`` and return it."""
    group = Group(GroupId(new_id()), name, currency, at())
    store.add_group(group)
    return group


def test_apply_creates_one_group_and_one_member_per_name(store: EventStore) -> None:
    result = apply_group_definition(store, a_definition(), now=at())
    assert isinstance(result, SetupResult)
    assert result.group.name == "Flat 3"
    assert result.group.currency == AUD
    assert result.group.created_at == at()
    assert len(store.list_groups()) == 1
    assert names(store.list_members(result.group.id)) == ROSTER


def test_a_first_apply_reports_everything_as_added(store: EventStore) -> None:
    result = apply_group_definition(store, a_definition(), now=at())
    assert result.group_created is True
    assert names(result.members_added) == ROSTER
    assert result.members_existing == ()


def test_every_id_comes_from_new_id_and_carries_no_name(store: EventStore) -> None:
    result = apply_group_definition(store, a_definition(), now=at())
    ids = [result.group.id] + [
        member.id for member in store.list_members(result.group.id)
    ]
    for value in ids:
        assert uuid.UUID(value)
        for name in ROSTER:
            assert name.lower() not in value.lower()
    assert len(set(ids)) == len(ids)


def test_every_member_is_created_with_no_user(store: EventStore) -> None:
    """Four member rows, zero users: the state of a fresh flat."""
    result = apply_group_definition(store, a_definition(), now=at())
    for member in store.list_members(result.group.id):
        assert member.user_id is None


@pytest.mark.parametrize("table", TABLES_APPLY_NEVER_WRITES)
def test_apply_writes_to_no_other_table(store: EventStore, table: str) -> None:
    apply_group_definition(store, a_definition(), now=at())
    assert count(store, table) == 0


def test_members_are_written_one_microsecond_apart_in_file_order(
    store: EventStore,
) -> None:
    """``(created_at, id)`` ordering then equals file order, with no new column."""
    result = apply_group_definition(store, a_definition(), now=at())
    members = store.list_members(result.group.id)
    assert names(members) == ROSTER
    assert tuple(member.created_at for member in members) == tuple(
        at(microseconds=position) for position in range(len(ROSTER))
    )


def test_ordering_adds_no_column_to_the_schema(store: EventStore) -> None:
    apply_group_definition(store, a_definition(), now=at())
    columns = {
        row[1]
        for row in store._connection.execute("PRAGMA table_info(members)").fetchall()
    }
    assert columns == {"id", "group_id", "display_name", "user_id", "created_at"}
    assert not columns & {"position", "sort_order", "ordinal", "rank"}


def test_setup_result_is_frozen_slotted_with_exactly_these_fields() -> None:
    assert SetupResult.__dataclass_params__.frozen is True
    assert SetupResult.__slots__
    assert list(SetupResult.__dataclass_fields__) == [
        "group",
        "group_created",
        "members_added",
        "members_existing",
    ]


def test_now_must_be_a_timezone_aware_datetime(store: EventStore) -> None:
    with pytest.raises(TypeError):
        apply_group_definition(store, a_definition(), now="2026-09-03")
    with pytest.raises(InvalidRecord):
        apply_group_definition(store, a_definition(), now=datetime(2026, 9, 3, 10, 0))
    assert store.list_groups() == ()


def test_now_is_converted_to_utc(store: EventStore) -> None:
    elsewhere = at().astimezone(timezone(timedelta(hours=10)))
    result = apply_group_definition(store, a_definition(), now=elsewhere)
    assert result.group.created_at == at()
    assert result.group.created_at.tzinfo == timezone.utc


def test_a_definition_of_the_wrong_type_raises_type_error(store: EventStore) -> None:
    with pytest.raises(TypeError):
        apply_group_definition(store, "Flat 3", now=at())  # type: ignore[arg-type]


# --- Applying twice ----------------------------------------------------------


def test_a_second_identical_apply_writes_nothing(store: EventStore) -> None:
    """The criterion that fails if apply is a plain insert."""
    first = apply_group_definition(store, a_definition(), now=at())
    before_groups = rows(store, "groups")
    before_members = rows(store, "members")
    second = apply_group_definition(store, a_definition(), now=at(60))
    assert second.group_created is False
    assert second.members_added == ()
    assert names(second.members_existing) == ROSTER
    assert second.group == first.group
    assert rows(store, "groups") == before_groups
    assert rows(store, "members") == before_members


def test_a_second_apply_with_one_extra_name_adds_only_that_member(
    store: EventStore,
) -> None:
    first = apply_group_definition(store, a_definition(), now=at())
    before = store.list_members(first.group.id)
    second = apply_group_definition(
        store, a_definition(ROSTER + ("Max",)), now=at(60)
    )
    assert second.group_created is False
    assert names(second.members_added) == ("Max",)
    assert names(second.members_existing) == ROSTER
    after = store.list_members(first.group.id)
    assert after[: len(ROSTER)] == before
    assert names(after) == ROSTER + ("Max",)


def test_an_omitted_name_is_refused_and_writes_nothing(store: EventStore) -> None:
    """One file that both adds Max and drops Jo writes nothing at all."""
    first = apply_group_definition(store, a_definition(), now=at())
    before_members = rows(store, "members")
    with pytest.raises(GroupMismatch) as caught:
        apply_group_definition(
            store, a_definition(("Sam", "Ali", "Kit", "Max")), now=at(60)
        )
    assert "Jo" in str(caught.value)
    assert rows(store, "members") == before_members
    assert names(store.list_members(first.group.id)) == ROSTER


def test_a_different_currency_is_refused_naming_both_codes(store: EventStore) -> None:
    first = apply_group_definition(store, a_definition(), now=at())
    with pytest.raises(GroupMismatch) as caught:
        apply_group_definition(store, a_definition(currency=NZD), now=at(60))
    message = str(caught.value)
    assert "AUD" in message and "NZD" in message
    assert store.get_group(first.group.id).currency == AUD


def test_a_different_group_name_is_refused_naming_both(store: EventStore) -> None:
    first = apply_group_definition(store, a_definition(), now=at())
    with pytest.raises(GroupMismatch) as caught:
        apply_group_definition(store, a_definition(name="Flat 4"), now=at(60))
    message = str(caught.value)
    assert "Flat 3" in message and "Flat 4" in message
    assert store.get_group(first.group.id).name == "Flat 3"


def test_a_name_differing_only_by_case_is_the_same_member(store: EventStore) -> None:
    first = apply_group_definition(store, a_definition(), now=at())
    before = store.list_members(first.group.id)
    second = apply_group_definition(
        store, a_definition(("sam", "Ali", "Jo", "Kit")), now=at(60)
    )
    assert second.members_added == ()
    assert store.list_members(first.group.id) == before
    assert names(store.list_members(first.group.id))[0] == "Sam"


def test_a_name_differing_only_by_normalisation_is_the_same_member(
    store: EventStore,
) -> None:
    composed = unicodedata.normalize("NFC", "Zoë")
    decomposed = unicodedata.normalize("NFD", "Zoë")
    first = apply_group_definition(store, a_definition((composed, "Ali")), now=at())
    before = store.list_members(first.group.id)
    second = apply_group_definition(
        store, a_definition((decomposed, "Ali")), now=at(60)
    )
    assert second.members_added == ()
    assert store.list_members(first.group.id) == before
    assert names(before)[0] == composed


def test_reordering_the_file_changes_nothing(store: EventStore) -> None:
    first = apply_group_definition(store, a_definition(), now=at())
    before = store.list_members(first.group.id)
    second = apply_group_definition(
        store, a_definition(tuple(reversed(ROSTER))), now=at(60)
    )
    assert second.members_added == ()
    assert store.list_members(first.group.id) == before
    assert names(store.list_members(first.group.id)) == ROSTER


def test_two_stored_members_of_one_name_refuse_a_reconcile(store: EventStore) -> None:
    """The store permits two members called Sam; this task will not guess."""
    first = apply_group_definition(store, a_definition(("Sam", "Ali")), now=at())
    store.add_member(Member(MemberId(new_id()), first.group.id, "sam", None, at(60)))
    before = rows(store, "members")
    with pytest.raises(GroupMismatch) as caught:
        apply_group_definition(store, a_definition(("Sam", "Ali")), now=at(120))
    assert "Sam" in str(caught.value)
    assert rows(store, "members") == before


def test_a_refused_apply_leaves_every_id_and_timestamp_untouched(
    store: EventStore,
) -> None:
    apply_group_definition(store, a_definition(), now=at())
    before_groups = rows(store, "groups")
    before_members = rows(store, "members")
    for definition in (
        a_definition(currency=NZD),
        a_definition(name="Flat 4"),
        a_definition(("Sam", "Ali")),
    ):
        with pytest.raises(GroupMismatch):
            apply_group_definition(store, definition, now=at(60))
    assert rows(store, "groups") == before_groups
    assert rows(store, "members") == before_members


# --- Identifying the group ---------------------------------------------------


def test_resolve_returns_the_only_group(store: EventStore) -> None:
    result = apply_group_definition(store, a_definition(), now=at())
    assert resolve_sole_group(store) == result.group


def test_resolve_on_an_empty_store_names_the_setup_command(store: EventStore) -> None:
    with pytest.raises(NoGroupConfigured) as caught:
        resolve_sole_group(store)
    assert "setup_group.py" in str(caught.value)
    assert store.list_groups() == ()
    assert count(store, "groups") == 0


def test_resolve_with_two_groups_names_every_id(store: EventStore) -> None:
    first = apply_group_definition(store, a_definition(), now=at())
    second = a_second_group(store)
    with pytest.raises(AmbiguousGroup) as caught:
        resolve_sole_group(store)
    message = str(caught.value)
    assert first.group.id in message
    assert second.id in message


def test_apply_with_two_groups_and_no_id_raises_ambiguous(store: EventStore) -> None:
    first = apply_group_definition(store, a_definition(), now=at())
    second = a_second_group(store)
    before = rows(store, "members")
    with pytest.raises(AmbiguousGroup) as caught:
        apply_group_definition(store, a_definition(), now=at(60))
    message = str(caught.value)
    assert first.group.id in message and second.id in message
    assert rows(store, "members") == before


def test_apply_by_explicit_id_touches_only_that_groups_members(
    store: EventStore,
) -> None:
    one = a_second_group(store, "Flat 3", AUD)
    two = a_second_group(store, "Flat 4", NZD)
    first = apply_group_definition(
        store, a_definition(("Sam", "Ali")), now=at(), group_id=one.id
    )
    second = apply_group_definition(
        store,
        a_definition(("Jo", "Kit"), name="Flat 4", currency=NZD),
        now=at(60),
        group_id=two.id,
    )
    assert first.group_created is False
    assert second.group_created is False
    assert names(store.list_members(one.id)) == ("Sam", "Ali")
    assert names(store.list_members(two.id)) == ("Jo", "Kit")


def test_apply_with_an_unknown_group_id_raises_record_not_found(
    store: EventStore,
) -> None:
    absent = new_id()
    with pytest.raises(RecordNotFound) as caught:
        apply_group_definition(store, a_definition(), now=at(), group_id=absent)
    assert absent in str(caught.value)
    assert store.list_groups() == ()


def test_apply_never_creates_a_group_under_a_caller_supplied_id(
    store: EventStore,
) -> None:
    """A group id in a config file or on a command line is the hardcoded id this
    rule exists to prevent."""
    with pytest.raises(RecordNotFound):
        apply_group_definition(store, a_definition(), now=at(), group_id=new_id())
    assert count(store, "groups") == 0
    assert count(store, "members") == 0


def test_no_source_or_test_file_carries_a_literal_group_id() -> None:
    """Ids are random UUIDs, so a literal one could only be a hardcoded group."""
    import re

    pattern = re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    )
    for directory in ("src", "scripts", "tests"):
        for path in sorted((REPO / directory).rglob("*.py")):
            assert pattern.search(path.read_text(encoding="utf-8")) is None, path
    assert (
        pattern.search((REPO / "group.example.toml").read_text(encoding="utf-8"))
        is None
    )
