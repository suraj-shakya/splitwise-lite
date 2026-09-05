"""The operator command: `scripts/setup_group.py`.

The script is loaded from its path, the way `tests/test_dev_server.py` loads
`scripts/serve.py`, because `scripts/` is not a package. Every test calls `main`
directly with an argument list, so nothing here spawns a process: the exit status is
the returned int, and argparse's own exits surface as `SystemExit`.

Every store is a real file under `tmp_path`, never `:memory:`, because two of the
criteria are about the file: that the path reaches `open_store` unchanged, and that a
run leaves no handle on it, which on Windows is what blocks the next run from removing
it.
"""

from __future__ import annotations

import ast
import importlib.util
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest

from splitwise_lite import (
    Currency,
    Group,
    GroupId,
    Member,
    MemberId,
    ScryptParams,
    User,
    new_id,
    open_store,
    sign_up,
)

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "setup_group.py"

PASSWORD = "a long enough passphrase"
ADDRESS = "sam@example.com"

ROSTER = ("Sam", "Ali", "Jo", "Kit")

DEFINITION = """
name = "Flat 3"
currency = "AUD"
members = ["Sam", "Ali", "Jo", "Kit"]
"""


def load_script() -> ModuleType:
    """Import `scripts/setup_group.py` from its path. It is not in a package."""
    spec = importlib.util.spec_from_file_location("_script_setup_group", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def script_source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return load_script()


@pytest.fixture
def params() -> ScryptParams:
    """Cheap scrypt parameters. No test here is about the key derivation function."""
    return ScryptParams(n=16, r=1, p=1)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A path to a store that does not exist yet, inside a directory that does."""
    return tmp_path / "ledger.sqlite3"


@pytest.fixture
def definition_path(tmp_path: Path) -> Path:
    path = tmp_path / "group.toml"
    path.write_text(DEFINITION, encoding="utf-8")
    return path


def apply_argv(store_path: Path, definition_path: Path, *rest: str) -> list[str]:
    return [
        "apply",
        "--store",
        str(store_path),
        "--definition",
        str(definition_path),
        *rest,
    ]


def seed(script: ModuleType, store_path: Path, definition_path: Path) -> None:
    """Apply the roster through the command itself, so the tests share one route in."""
    assert script.main(apply_argv(store_path, definition_path)) == 0


def an_account(
    store_path: Path,
    params: ScryptParams,
    *,
    email: str = ADDRESS,
    display_name: str = "Sam",
) -> User:
    """Sign an account up and close the store again, leaving no handle on the file."""
    with open_store(store_path) as store:
        return sign_up(
            store,
            email=email,
            display_name=display_name,
            password=PASSWORD,
            now=datetime.now(timezone.utc),
            params=params,
        )


def roster(store_path: Path) -> tuple[Member, ...]:
    with open_store(store_path) as store:
        return store.list_members(store.list_groups()[0].id)


def sole_group_id(store_path: Path) -> str:
    with open_store(store_path) as store:
        return store.list_groups()[0].id


# --- The shape of the script -------------------------------------------------


def test_the_script_exists_and_defines_main(script: ModuleType) -> None:
    import inspect

    assert SCRIPT.is_file()
    signature = inspect.signature(script.main)
    assert list(signature.parameters) == ["argv"]
    assert signature.parameters["argv"].default is None
    assert script.main.__doc__


def test_nothing_runs_at_import_time_beyond_definitions() -> None:
    """A test imports this file and calls ``main``, so importing must do nothing."""
    tree = ast.parse(script_source())
    for node in tree.body:
        assert isinstance(
            node,
            (
                ast.Expr,
                ast.Import,
                ast.ImportFrom,
                ast.Assign,
                ast.AnnAssign,
                ast.FunctionDef,
                ast.ClassDef,
                ast.If,
            ),
        ), ast.dump(node)[:80]
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant), "only docstrings execute"
        if isinstance(node, ast.If):
            assert "__main__" in ast.unparse(node.test)


def test_the_script_imports_only_the_standard_library_and_the_package() -> None:
    """It binds no socket, starts no server and imports nothing from ``app/``."""
    tree = ast.parse(script_source())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a script is not in a package"
            assert node.module is not None
            roots.add(node.module.split(".")[0])
    assert roots <= {
        "__future__",
        "argparse",
        "collections",
        "datetime",
        "splitwise_lite",
        "sys",
        "unicodedata",
    }, roots
    assert "socket" not in roots
    assert "http" not in roots
    assert "app" not in roots


def test_the_three_subcommands_are_apply_link_and_show(script: ModuleType) -> None:
    parser = script.build_parser()
    actions = [
        action
        for action in parser._subparsers._group_actions  # type: ignore[union-attr]
        if hasattr(action, "choices")
    ]
    assert len(actions) == 1
    assert set(actions[0].choices) == {"apply", "link", "show"}


def test_no_subcommand_has_a_default_store_and_none_reads_the_env(
    script: ModuleType,
) -> None:
    parser = script.build_parser()
    subcommands = next(
        action
        for action in parser._subparsers._group_actions  # type: ignore[union-attr]
        if hasattr(action, "choices")
    ).choices
    assert set(subcommands) == {"apply", "link", "show"}
    for name, subparser in subcommands.items():
        store = next(
            action for action in subparser._actions if action.dest == "store"
        )
        assert store.required is True, name
        assert store.default is None, name
    source = script_source()
    assert "environ" not in source
    assert "getenv" not in source
    assert "mkdir" not in source
    assert "makedirs" not in source


# --- apply -------------------------------------------------------------------


def test_apply_creates_the_group_and_names_every_member_it_added(
    script: ModuleType, store_path: Path, definition_path: Path, capsys
) -> None:
    assert script.main(apply_argv(store_path, definition_path)) == 0
    out = capsys.readouterr().out
    assert "Created" in out
    assert "Flat 3" in out
    assert sole_group_id(store_path) in out
    for member in roster(store_path):
        assert member.display_name in out
        assert member.id in out
    assert tuple(member.display_name for member in roster(store_path)) == ROSTER


def test_a_second_apply_says_nothing_changed_and_exits_zero(
    script: ModuleType, store_path: Path, definition_path: Path, capsys
) -> None:
    seed(script, store_path, definition_path)
    before = roster(store_path)
    capsys.readouterr()
    assert script.main(apply_argv(store_path, definition_path)) == 0
    out = capsys.readouterr().out
    assert "Nothing changed" in out
    assert "Created" not in out
    assert roster(store_path) == before


def test_apply_adds_a_name_the_file_gained_and_reports_only_that_one(
    script: ModuleType, store_path: Path, definition_path: Path, capsys
) -> None:
    seed(script, store_path, definition_path)
    definition_path.write_text(
        DEFINITION.replace('"Kit"]', '"Kit", "Max"]'), encoding="utf-8"
    )
    capsys.readouterr()
    assert script.main(apply_argv(store_path, definition_path)) == 0
    out = capsys.readouterr().out
    assert "Max" in out
    assert "Added 1 member(s):" in out
    assert "Sam" not in out
    assert tuple(member.display_name for member in roster(store_path)) == ROSTER + (
        "Max",
    )


def test_apply_refuses_a_dropped_name_with_a_message_and_no_traceback(
    script: ModuleType, store_path: Path, definition_path: Path, capsys
) -> None:
    seed(script, store_path, definition_path)
    before = roster(store_path)
    definition_path.write_text(
        DEFINITION.replace('"Jo", ', ""), encoding="utf-8"
    )
    capsys.readouterr()
    assert script.main(apply_argv(store_path, definition_path)) == 1
    captured = capsys.readouterr()
    assert "Jo" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert roster(store_path) == before


def test_apply_reports_an_unreadable_definition_rather_than_raising(
    script: ModuleType, store_path: Path, tmp_path: Path, capsys
) -> None:
    absent = tmp_path / "absent.toml"
    assert script.main(apply_argv(store_path, absent)) == 1
    captured = capsys.readouterr()
    assert str(absent) in captured.err
    assert "Traceback" not in captured.err


def test_apply_creates_no_directory_for_a_store_path_that_has_none(
    script: ModuleType, tmp_path: Path, definition_path: Path, capsys
) -> None:
    nowhere = tmp_path / "not-made" / "ledger.sqlite3"
    assert script.main(apply_argv(nowhere, definition_path)) == 1
    assert not nowhere.parent.exists()
    assert "Traceback" not in capsys.readouterr().err


# --- show --------------------------------------------------------------------


def test_show_prints_the_group_and_every_member_in_roster_order(
    script: ModuleType, store_path: Path, definition_path: Path, capsys
) -> None:
    seed(script, store_path, definition_path)
    capsys.readouterr()
    assert script.main(["show", "--store", str(store_path)]) == 0
    out = capsys.readouterr().out
    assert "Flat 3" in out
    assert "AUD" in out
    with open_store(store_path) as store:
        group = store.list_groups()[0]
    assert group.created_at.isoformat() in out
    members = roster(store_path)
    positions = [out.index(member.id) for member in members]
    assert positions == sorted(positions)
    for member in members:
        assert member.display_name in out
        assert "no account yet" in out


def test_show_writes_nothing(
    script: ModuleType, store_path: Path, definition_path: Path
) -> None:
    seed(script, store_path, definition_path)
    with open_store(store_path) as store:
        before = store._connection.execute(
            "SELECT * FROM members ORDER BY id"
        ).fetchall()
    assert script.main(["show", "--store", str(store_path)]) == 0
    with open_store(store_path) as store:
        after = store._connection.execute(
            "SELECT * FROM members ORDER BY id"
        ).fetchall()
    assert after == before


def test_show_prints_no_address_and_no_user_id(
    script: ModuleType,
    store_path: Path,
    definition_path: Path,
    params: ScryptParams,
    capsys,
) -> None:
    """A screenshot of the roster must not be an address list."""
    seed(script, store_path, definition_path)
    user = an_account(store_path, params)
    sam = roster(store_path)[0]
    assert (
        script.main(
            [
                "link",
                "--store",
                str(store_path),
                "--email",
                ADDRESS,
                "--member-id",
                sam.id,
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert script.main(["show", "--store", str(store_path)]) == 0
    out = capsys.readouterr().out
    assert ADDRESS not in out
    assert user.id not in out
    assert "linked" in out


def test_show_on_a_store_with_no_group_names_the_setup_command(
    script: ModuleType, store_path: Path, capsys
) -> None:
    with open_store(store_path):
        pass
    assert script.main(["show", "--store", str(store_path)]) == 1
    captured = capsys.readouterr()
    assert "setup_group.py" in captured.err
    assert "Traceback" not in captured.err


# --- link --------------------------------------------------------------------


def test_link_resolves_the_account_by_address_and_prints_the_pair(
    script: ModuleType,
    store_path: Path,
    definition_path: Path,
    params: ScryptParams,
    capsys,
) -> None:
    seed(script, store_path, definition_path)
    user = an_account(store_path, params)
    sam = roster(store_path)[0]
    capsys.readouterr()
    assert (
        script.main(
            [
                "link",
                "--store",
                str(store_path),
                "--email",
                ADDRESS.upper(),
                "--member-name",
                "Sam",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert sam.display_name in out
    assert sam.id in out
    assert user.id in out
    with open_store(store_path) as store:
        assert store.get_member(sam.id).user_id == user.id
        assert [
            member.user_id
            for member in store.list_members(sam.group_id)
            if member.id != sam.id
        ] == [None, None, None]


def test_link_by_member_name_matches_after_normalisation_and_casefolding(
    script: ModuleType,
    store_path: Path,
    tmp_path: Path,
    params: ScryptParams,
) -> None:
    composed = unicodedata.normalize("NFC", "Zoë")
    decomposed = unicodedata.normalize("NFD", "Zoë")
    assert composed != decomposed
    definition = tmp_path / "group.toml"
    definition.write_text(
        f'name = "Flat 3"\ncurrency = "AUD"\nmembers = ["{composed}", "Ali"]\n',
        encoding="utf-8",
    )
    assert script.main(apply_argv(store_path, definition)) == 0
    user = an_account(store_path, params, display_name="Zoe")
    assert (
        script.main(
            [
                "link",
                "--store",
                str(store_path),
                "--email",
                ADDRESS,
                "--member-name",
                decomposed.lower(),
            ]
        )
        == 0
    )
    with open_store(store_path) as store:
        zoe = store.list_members(store.list_groups()[0].id)[0]
        assert zoe.display_name == composed
        assert zoe.user_id == user.id


@pytest.mark.parametrize(
    "chosen",
    [
        [],
        ["--member-id", "whatever", "--member-name", "Sam"],
    ],
)
def test_link_needs_exactly_one_of_member_id_and_member_name(
    script: ModuleType, store_path: Path, chosen: list[str]
) -> None:
    """argparse owns usage errors and its own exit status 2."""
    with pytest.raises(SystemExit) as caught:
        script.main(
            ["link", "--store", str(store_path), "--email", ADDRESS, *chosen]
        )
    assert caught.value.code == 2


def test_link_with_a_name_that_matches_nothing_is_an_error(
    script: ModuleType,
    store_path: Path,
    definition_path: Path,
    params: ScryptParams,
    capsys,
) -> None:
    seed(script, store_path, definition_path)
    an_account(store_path, params)
    capsys.readouterr()
    assert (
        script.main(
            [
                "link",
                "--store",
                str(store_path),
                "--email",
                ADDRESS,
                "--member-name",
                "Nobody",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "Nobody" in captured.err
    assert "Traceback" not in captured.err
    assert all(member.user_id is None for member in roster(store_path))


def test_link_with_a_name_that_matches_two_members_names_every_candidate(
    script: ModuleType,
    store_path: Path,
    definition_path: Path,
    params: ScryptParams,
    capsys,
) -> None:
    """The store permits two members called Sam, so the command must not guess."""
    seed(script, store_path, definition_path)
    sam = roster(store_path)[0]
    with open_store(store_path) as store:
        twin = Member(
            MemberId(new_id()),
            sam.group_id,
            "sam",
            None,
            datetime.now(timezone.utc),
        )
        store.add_member(twin)
    an_account(store_path, params)
    capsys.readouterr()
    assert (
        script.main(
            [
                "link",
                "--store",
                str(store_path),
                "--email",
                ADDRESS,
                "--member-name",
                "Sam",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert sam.id in captured.err
    assert twin.id in captured.err
    assert "--member-id" in captured.err
    assert "Traceback" not in captured.err
    assert all(member.user_id is None for member in roster(store_path))


def test_link_refuses_an_address_no_account_holds(
    script: ModuleType, store_path: Path, definition_path: Path, capsys
) -> None:
    seed(script, store_path, definition_path)
    sam = roster(store_path)[0]
    assert (
        script.main(
            [
                "link",
                "--store",
                str(store_path),
                "--email",
                "ghost@example.com",
                "--member-id",
                sam.id,
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "ghost@example.com" in captured.err
    assert "Traceback" not in captured.err
    assert roster(store_path)[0].user_id is None


def test_no_subcommand_prints_a_password_a_hash_or_a_token(
    script: ModuleType,
    store_path: Path,
    definition_path: Path,
    params: ScryptParams,
    capsys,
) -> None:
    seed(script, store_path, definition_path)
    an_account(store_path, params)
    with open_store(store_path) as store:
        user = store.get_user_by_email(ADDRESS)
        stored_hash = store.get_password_hash(user.id)
    sam = roster(store_path)[0]
    capsys.readouterr()
    for argv in (
        apply_argv(store_path, definition_path),
        [
            "link",
            "--store",
            str(store_path),
            "--email",
            ADDRESS,
            "--member-id",
            sam.id,
        ],
        ["show", "--store", str(store_path)],
    ):
        assert script.main(argv) == 0
        captured = capsys.readouterr()
        for secret in (PASSWORD, stored_hash, "scrypt"):
            assert secret not in captured.out, argv
            assert secret not in captured.err, argv


# --- The store handle and an explicit group ----------------------------------


def test_a_run_leaves_no_handle_on_the_store_file(
    script: ModuleType, store_path: Path, definition_path: Path, capsys
) -> None:
    """On Windows an open handle blocks the next run's rename or delete."""
    seed(script, store_path, definition_path)
    moved = store_path.with_name("moved.sqlite3")
    store_path.rename(moved)
    moved.rename(store_path)

    definition_path.write_text(DEFINITION.replace('"Jo", ', ""), encoding="utf-8")
    assert script.main(apply_argv(store_path, definition_path)) == 1
    capsys.readouterr()
    store_path.rename(moved)
    moved.unlink()
    assert not store_path.exists()


def test_an_explicit_group_id_is_how_an_ambiguous_store_is_worked(
    script: ModuleType, store_path: Path, definition_path: Path, tmp_path: Path, capsys
) -> None:
    """Two groups is a recorded, undefended-against state, and --group-id is the fix."""
    seed(script, store_path, definition_path)
    first = sole_group_id(store_path)
    with open_store(store_path) as store:
        second = Group(
            GroupId(new_id()), "Flat 4", Currency("NZD"), datetime.now(timezone.utc)
        )
        store.add_group(second)
    capsys.readouterr()

    assert script.main(["show", "--store", str(store_path)]) == 1
    captured = capsys.readouterr()
    assert first in captured.err and second.id in captured.err
    assert "Traceback" not in captured.err

    assert script.main(apply_argv(store_path, definition_path)) == 1
    captured = capsys.readouterr()
    assert first in captured.err and second.id in captured.err

    assert (
        script.main(apply_argv(store_path, definition_path, "--group-id", first)) == 0
    )
    assert "Nothing changed" in capsys.readouterr().out
    assert script.main(["show", "--store", str(store_path), "--group-id", first]) == 0
    out = capsys.readouterr().out
    assert first in out and second.id not in out

    absent = new_id()
    assert script.main(["show", "--store", str(store_path), "--group-id", absent]) == 1
    captured = capsys.readouterr()
    assert absent in captured.err
    assert "Traceback" not in captured.err
