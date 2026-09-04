"""Tests for accounts and sessions.

Task 7 of plans/backlog.md, sharpened in plans/tasks/07-accounts-and-sessions.md.

Almost every test here passes deliberately cheap scrypt parameters through the
``params`` fixture. The real ones cost roughly a third of a second per hash, and a
suite that paid that everywhere would add minutes without covering anything the cheap
ones miss. Four tests, marked in their names, do run at ``DEFAULT_SCRYPT_PARAMS``: they
are what stops the cheap fixture from hiding a broken default.

Nothing here asserts an elapsed time. The claim that a failed login costs the same work
whether or not the address exists is tested by counting calls to the module's derive
helper, because a timing assertion on a shared machine is a flaky test.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import inspect
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from splitwise_lite import accounts as accounts_module
from splitwise_lite import events as events_module
from splitwise_lite import money as money_module
from splitwise_lite import store as store_module
from splitwise_lite.accounts import (
    DEFAULT_SCRYPT_PARAMS,
    HASH_ALGORITHM,
    MAX_EMAIL_LENGTH,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    SALT_BYTES,
    SESSION_LIFETIME,
    TOKEN_BYTES,
    AccountError,
    AuthenticationFailed,
    EmailAlreadyRegistered,
    InvalidEmail,
    InvalidPassword,
    IssuedSession,
    PasswordHashInvalid,
    ScryptParams,
    SessionInvalid,
    authenticate,
    change_password,
    hash_password,
    log_in,
    log_out,
    log_out_everywhere,
    normalise_email,
    sign_up,
    verify_password,
)
from splitwise_lite.money import Currency, DomainError
from splitwise_lite.store import (
    IN_MEMORY,
    DuplicateRecord,
    EventStore,
    Group,
    InvalidRecord,
    Member,
    RecordNotFound,
    Session,
    User,
    UserId,
    open_store,
)

T0 = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)

SALT_B64 = base64.b64encode(b"s" * 16).decode()
KEY_B64 = base64.b64encode(b"k" * 32).decode()

PASSWORD = "correct horse battery staple"
OTHER_PASSWORD = "a quite different passphrase"
AUD = Currency("AUD")

PUBLIC = {
    "DEFAULT_SCRYPT_PARAMS",
    "HASH_ALGORITHM",
    "MAX_EMAIL_LENGTH",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "SALT_BYTES",
    "SESSION_LIFETIME",
    "TOKEN_BYTES",
    "AccountError",
    "AuthenticationFailed",
    "EmailAlreadyRegistered",
    "InvalidEmail",
    "InvalidPassword",
    "IssuedSession",
    "PasswordHashInvalid",
    "ScryptParams",
    "SessionInvalid",
    "authenticate",
    "change_password",
    "hash_password",
    "log_in",
    "log_out",
    "log_out_everywhere",
    "normalise_email",
    "sign_up",
    "verify_password",
}


def at(seconds: int = 0, *, microseconds: int = 0) -> datetime:
    """A UTC timestamp ``seconds`` after the fixed base time."""
    return T0 + timedelta(seconds=seconds, microseconds=microseconds)


def accounts_source() -> str:
    return Path(accounts_module.__file__).read_text(encoding="utf-8")


@pytest.fixture
def store():
    """An open, empty store. Task 6's own tests cover the file-backed half."""
    with open_store(IN_MEMORY) as opened:
        yield opened


@pytest.fixture
def params() -> ScryptParams:
    """Deliberately cheap parameters, for every test that is not about the KDF.

    Real ones cost about a third of a second per hash. These cost microseconds and
    exercise exactly the same code path, so only the four tests that are about the
    defaults pay for them.
    """
    return ScryptParams(n=16, r=1, p=1)


def an_account(
    store: EventStore,
    params: ScryptParams,
    email: str = "sam@example.com",
    password: str = PASSWORD,
    display_name: str = "Sam",
    at_time: datetime | None = None,
) -> User:
    """Sign up one account and return the stored user."""
    return sign_up(
        store,
        email=email,
        display_name=display_name,
        password=password,
        now=at() if at_time is None else at_time,
        params=params,
    )


# --- The shape of the module ------------------------------------------------


def test_the_public_surface_is_exactly_the_named_names() -> None:
    assert set(accounts_module.__all__) == PUBLIC
    assert len(accounts_module.__all__) == len(PUBLIC)
    for name in PUBLIC:
        assert hasattr(accounts_module, name), name


def test_everything_else_the_module_defines_is_underscored() -> None:
    tree = ast.parse(accounts_source())
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
    """Tasks 9, 10, 14 and 15 are written against these, so none may be undocumented."""
    tree = ast.parse(accounts_source())
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
    assert accounts_module.__doc__


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
        "user_credentials",
        "expense_events",
        "expense_allocations",
        "settlement_events",
        "settlement_decision_events",
        "users",
        "groups",
        "execute(",
    ],
)
def test_the_module_writes_no_sql_and_names_no_table(forbidden: str) -> None:
    assert forbidden not in accounts_source()


def test_the_only_mention_of_a_session_table_is_the_store_method_it_calls() -> None:
    """``sessions`` is a table name, so the module may not use the word for anything
    other than calling the one store method whose name contains it."""
    source = accounts_source()
    assert source.count("sessions") == source.count("delete_sessions_for_user")
    assert source.count("delete_sessions_for_user") == 1


@pytest.mark.parametrize(
    "forbidden",
    [
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
def test_the_module_has_no_http_surface(forbidden: str) -> None:
    """A library, not a web server. Task 10 owns every part of carrying a token."""
    assert forbidden not in accounts_source()


@pytest.mark.parametrize("forbidden", ["now(", "utcnow(", "time.time", "today("])
def test_the_module_never_reads_the_clock(forbidden: str) -> None:
    assert forbidden not in accounts_source()


@pytest.mark.parametrize("forbidden", ["import random", "random.", "uuid"])
def test_the_module_uses_secrets_and_never_random(forbidden: str) -> None:
    assert forbidden not in accounts_source()
    assert "import secrets" in accounts_source()


def test_the_module_names_neither_add_member_nor_the_table_it_writes() -> None:
    """Task 9 owns writing the link. Task 7 only reads it."""
    source = accounts_source()
    assert "add_member" not in source
    assert "members" not in source


def test_the_dependency_direction_stays_one_way() -> None:
    tree = ast.parse(accounts_source())
    within_the_package = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 1
    }
    assert within_the_package == {"events", "money", "store"}
    for module in (store_module, events_module, money_module):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or "accounts" not in node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert "accounts" not in alias.name


@pytest.mark.parametrize(
    "function",
    [sign_up, log_in, authenticate, log_out, log_out_everywhere, change_password],
)
def test_every_function_that_touches_storage_takes_the_store_first(function) -> None:
    parameters = list(inspect.signature(function).parameters.values())
    assert parameters[0].name == "store"
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_the_module_holds_no_store_and_no_current_user() -> None:
    public_values = {
        name: getattr(accounts_module, name) for name in accounts_module.__all__
    }
    for name, value in public_values.items():
        assert not isinstance(value, EventStore), name
    assert not hasattr(accounts_module, "current_user")
    assert not hasattr(accounts_module, "store")


def test_no_value_type_in_the_module_holds_a_password() -> None:
    """A field would put one in a repr, a log line and a traceback."""
    for value_type in (ScryptParams, IssuedSession, Session):
        for name in value_type.__slots__:
            assert "password" not in name, (value_type, name)
            assert "secret" not in name, (value_type, name)


def test_the_error_family_is_one_family() -> None:
    assert issubclass(AccountError, DomainError)
    for error in (
        AuthenticationFailed,
        EmailAlreadyRegistered,
        InvalidEmail,
        InvalidPassword,
        PasswordHashInvalid,
        SessionInvalid,
    ):
        assert issubclass(error, AccountError), error


def test_the_package_re_exports_the_new_names() -> None:
    import splitwise_lite

    assert splitwise_lite.sign_up is sign_up
    assert splitwise_lite.__version__ == "0.1.0"
    for name in PUBLIC | {"Session"}:
        assert name in splitwise_lite.__all__, name


# --- Timestamps -------------------------------------------------------------


def calls_taking_now(store: EventStore, params: ScryptParams, moment: object) -> list:
    """Every public call that takes ``now``, ready to be run with a bad one."""
    return [
        lambda: sign_up(
            store,
            email="new@example.com",
            display_name="New",
            password=PASSWORD,
            now=moment,
            params=params,
        ),
        lambda: log_in(
            store, email="sam@example.com", password=PASSWORD, now=moment
        ),
        lambda: authenticate(store, "a" * 43, now=moment),
        lambda: change_password(
            store,
            user_id="u1",
            current_password=PASSWORD,
            new_password=OTHER_PASSWORD,
            now=moment,
            params=params,
        ),
    ]


def test_a_now_that_is_not_a_datetime_raises_type_error(
    store: EventStore, params: ScryptParams
) -> None:
    for call in calls_taking_now(store, params, "2026-09-03T10:00:00+00:00"):
        with pytest.raises(TypeError):
            call()


def test_a_naive_now_is_rejected_rather_than_assumed_to_be_utc(
    store: EventStore, params: ScryptParams
) -> None:
    for call in calls_taking_now(store, params, datetime(2026, 9, 3, 10, 0)):
        with pytest.raises(InvalidRecord):
            call()


def test_a_now_in_another_offset_is_converted_to_utc(
    store: EventStore, params: ScryptParams
) -> None:
    brisbane = timezone(timedelta(hours=10))
    user = an_account(
        store, params, at_time=datetime(2026, 9, 3, 20, 0, tzinfo=brisbane)
    )
    assert user.created_at == at()
    issued = log_in(
        store,
        email="sam@example.com",
        password=PASSWORD,
        now=datetime(2026, 9, 3, 20, 0, tzinfo=brisbane),
    )
    assert issued.session.created_at == at()
    assert issued.session.created_at.utcoffset() == timedelta(0)


# --- Password hashing -------------------------------------------------------


def test_hash_password_returns_the_documented_shape(params: ScryptParams) -> None:
    encoded = hash_password(PASSWORD, params=params)
    fields = encoded.split("$")
    assert len(fields) == 4
    assert fields[0] == HASH_ALGORITHM == "scrypt"
    assert fields[1] == "n=16,r=1,p=1"


def test_the_default_parameters_are_the_documented_numbers() -> None:
    """At DEFAULT_SCRYPT_PARAMS: raising the cost has to be a visible edit."""
    assert DEFAULT_SCRYPT_PARAMS == ScryptParams(n=65536, r=8, p=2)
    assert DEFAULT_SCRYPT_PARAMS.n == 65536
    assert DEFAULT_SCRYPT_PARAMS.r == 8
    assert DEFAULT_SCRYPT_PARAMS.p == 2
    assert DEFAULT_SCRYPT_PARAMS.dklen == 32
    assert SALT_BYTES == 16
    assert TOKEN_BYTES == 32
    assert MIN_PASSWORD_LENGTH == 12
    assert MAX_PASSWORD_LENGTH == 1024
    assert MAX_EMAIL_LENGTH == 254
    assert SESSION_LIFETIME == timedelta(days=30)


def test_hashing_with_the_defaults_succeeds() -> None:
    """At DEFAULT_SCRYPT_PARAMS: this is the test that fails without maxmem.

    OpenSSL's default maxmem is 32 MiB and these parameters need 64, so a call that
    left it out would raise ValueError here rather than return a hash.
    """
    encoded = hash_password(PASSWORD)
    assert encoded.split("$")[1] == "n=65536,r=8,p=2"
    assert verify_password(PASSWORD, encoded) is True


def test_maxmem_is_computed_from_the_parameters_in_hand(
    monkeypatch: pytest.MonkeyPatch, params: ScryptParams
) -> None:
    seen: list[dict] = []
    real = hashlib.scrypt

    def spy(*args: object, **kwargs: object) -> bytes:
        seen.append(dict(kwargs))
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(accounts_module.hashlib, "scrypt", spy)
    hash_password(PASSWORD, params=params)
    assert seen[0]["maxmem"] == 128 * 1 * (16 + 1 + 2)
    seen.clear()
    bigger = ScryptParams(n=1024, r=2, p=1)
    hash_password(PASSWORD, params=bigger)
    assert seen[0]["maxmem"] == 128 * 2 * (1024 + 1 + 2)


def test_a_fresh_salt_is_drawn_for_every_hash(params: ScryptParams) -> None:
    first = hash_password(PASSWORD, params=params)
    second = hash_password(PASSWORD, params=params)
    assert first != second
    assert verify_password(PASSWORD, first) is True
    assert verify_password(PASSWORD, second) is True
    salt = base64.b64decode(first.split("$")[2], validate=True)
    assert len(salt) == SALT_BYTES == 16
    assert len(base64.b64decode(first.split("$")[3], validate=True)) == 32


def test_verification_reads_the_parameters_out_of_the_stored_hash(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both directions: a hash outlives a change to the defaults either way."""
    larger = ScryptParams(n=131072, r=8, p=1)
    smaller = ScryptParams(n=16, r=1, p=1)
    from_larger = hash_password(PASSWORD, params=larger)
    from_smaller = hash_password(PASSWORD, params=smaller)

    seen: list[dict] = []
    real = hashlib.scrypt

    def spy(*args: object, **kwargs: object) -> bytes:
        seen.append(dict(kwargs))
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(accounts_module.hashlib, "scrypt", spy)
    assert verify_password(PASSWORD, from_larger) is True
    assert seen[-1]["n"] == 131072
    assert seen[-1]["maxmem"] == 128 * 8 * (131072 + 1 + 2)
    assert verify_password(PASSWORD, from_smaller) is True
    assert seen[-1]["n"] == 16
    assert seen[-1]["maxmem"] == 128 * 1 * (16 + 1 + 2)


def test_verification_compares_with_compare_digest_and_never_with_equality() -> None:
    tree = ast.parse(accounts_source())
    verify = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "verify_password"
    )
    for node in ast.walk(verify):
        assert not isinstance(node, ast.Compare), ast.dump(node)
    assert "hmac.compare_digest" in accounts_source()


def test_verify_password_is_true_only_for_the_password_that_made_the_hash(
    params: ScryptParams,
) -> None:
    encoded = hash_password(PASSWORD, params=params)
    another = hash_password(OTHER_PASSWORD, params=params)
    assert verify_password(PASSWORD, encoded) is True
    assert verify_password("the wrong password", encoded) is False
    assert verify_password(PASSWORD, another) is False
    assert verify_password(PASSWORD + " ", encoded) is False
    assert verify_password(" " + PASSWORD, encoded) is False


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        f"scrypt$n=16,r=1,p=1${SALT_B64}",
        f"scrypt$n=16,r=1,p=1${SALT_B64}${KEY_B64}$extra",
        f"pbkdf2$n=16,r=1,p=1${SALT_B64}${KEY_B64}",
        f"scrypt$r=1,n=16,p=1${SALT_B64}${KEY_B64}",
        f"scrypt$n=16,p=1,r=1${SALT_B64}${KEY_B64}",
        f"scrypt$n=sixteen,r=1,p=1${SALT_B64}${KEY_B64}",
        f"scrypt$n=16,r=1${SALT_B64}${KEY_B64}",
        f"scrypt$n=16,r=1,p=1$not base64!${KEY_B64}",
        f"scrypt$n=16,r=1,p=1${SALT_B64}$not base64!",
        f"scrypt$n=16,r=1,p=1$${KEY_B64}",
        f"scrypt$n=16.0,r=1,p=1${SALT_B64}${KEY_B64}",
        f"scrypt$n=-16,r=1,p=1${SALT_B64}${KEY_B64}",
        f"scrypt$ n=16,r=1,p=1 ${SALT_B64}${KEY_B64}",
    ],
)
def test_a_corrupt_stored_hash_raises_rather_than_reporting_a_wrong_password(
    encoded: str,
) -> None:
    """A corrupt row is a bug report. Reporting it as a wrong password would hide
    database damage behind a support ticket about a forgotten one."""
    with pytest.raises(PasswordHashInvalid):
        verify_password(PASSWORD, encoded)


@pytest.mark.parametrize(
    "parameters",
    [
        "n=1099511627776,r=8,p=2",
        "n=1,r=8,p=2",
        "n=65535,r=8,p=2",
        "n=65536,r=0,p=2",
        "n=65536,r=33,p=2",
        "n=65536,r=8,p=0",
        "n=65536,r=8,p=17",
    ],
)
def test_parameters_out_of_bounds_in_a_stored_hash_are_refused(
    parameters: str,
) -> None:
    """A hand-edited row claiming n = 2**40 must not allocate a terabyte."""
    with pytest.raises(PasswordHashInvalid):
        verify_password(PASSWORD, f"scrypt${parameters}${SALT_B64}${KEY_B64}")


def test_a_derived_key_length_outside_the_bounds_is_refused() -> None:
    for size in (15, 65):
        key = base64.b64encode(b"k" * size).decode()
        with pytest.raises(PasswordHashInvalid):
            verify_password(PASSWORD, f"scrypt$n=16,r=1,p=1${SALT_B64}${key}")


@pytest.mark.parametrize(
    "arguments",
    [
        {"n": 2**40, "r": 8, "p": 2},
        {"n": 1, "r": 8, "p": 2},
        {"n": 65535, "r": 8, "p": 2},
        {"n": 65536, "r": 0, "p": 2},
        {"n": 65536, "r": 33, "p": 2},
        {"n": 65536, "r": 8, "p": 0},
        {"n": 65536, "r": 8, "p": 17},
        {"n": 65536, "r": 8, "p": 2, "dklen": 15},
        {"n": 65536, "r": 8, "p": 2, "dklen": 65},
    ],
)
def test_scrypt_params_cannot_be_constructed_out_of_bounds(arguments: dict) -> None:
    with pytest.raises(PasswordHashInvalid):
        ScryptParams(**arguments)


def test_scrypt_params_rejects_a_non_integer() -> None:
    with pytest.raises(TypeError):
        ScryptParams(n="16", r=1, p=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ScryptParams(n=16, r=True, p=1)  # type: ignore[arg-type]


def test_scrypt_params_is_frozen_slotted_and_compares_by_value() -> None:
    assert ScryptParams.__dataclass_params__.frozen is True
    assert ScryptParams.__slots__
    assert ScryptParams(n=16, r=1, p=1) == ScryptParams(n=16, r=1, p=1)
    assert ScryptParams(n=16, r=1, p=1) != ScryptParams(n=32, r=1, p=1)


def test_a_password_or_a_hash_of_the_wrong_type_raises_type_error(
    params: ScryptParams,
) -> None:
    encoded = hash_password(PASSWORD, params=params)
    with pytest.raises(TypeError):
        hash_password(b"bytes are not a password", params=params)  # type: ignore
    with pytest.raises(TypeError):
        verify_password(1234, encoded)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        verify_password(PASSWORD, 1234)  # type: ignore[arg-type]


# --- Password policy and normalisation --------------------------------------


def test_a_password_normalises_before_it_is_hashed_and_before_it_verifies(
    params: ScryptParams,
) -> None:
    composed = unicodedata.normalize("NFC", "pa\u00dfphrase caf\u00e9 stra\u00dfe")
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    encoded = hash_password(composed, params=params)
    assert verify_password(decomposed, encoded) is True
    assert verify_password(composed, hash_password(decomposed, params=params)) is True


def test_a_password_is_measured_after_normalisation(
    store: EventStore, params: ScryptParams
) -> None:
    """Twelve code points decomposed, eleven composed, and eleven is too short."""
    too_short = unicodedata.normalize("NFD", "caf\u00e9 secret")
    assert len(too_short) == 12
    assert len(unicodedata.normalize("NFKC", too_short)) == 11
    with pytest.raises(InvalidPassword):
        an_account(store, params, password=too_short)
    long_enough = unicodedata.normalize("NFD", "caf\u00e9 secrets")
    assert len(unicodedata.normalize("NFKC", long_enough)) == MIN_PASSWORD_LENGTH
    an_account(store, params, password=long_enough)
    assert log_in(store, email="sam@example.com", password=long_enough, now=at())


@pytest.mark.parametrize("password", ["short", "x" * 11, "x" * 1025])
def test_a_password_outside_the_length_bounds_is_refused(
    store: EventStore, params: ScryptParams, password: str
) -> None:
    with pytest.raises(InvalidPassword):
        an_account(store, params, password=password)
    an_account(store, params, email="other@example.com")
    user = store.get_user_by_email("other@example.com")
    with pytest.raises(InvalidPassword):
        change_password(
            store,
            user_id=user.id,
            current_password=PASSWORD,
            new_password=password,
            now=at(),
            params=params,
        )


def test_a_password_is_never_stripped(
    store: EventStore, params: ScryptParams
) -> None:
    an_account(store, params, password=" secret phrase!")
    with pytest.raises(AuthenticationFailed):
        log_in(store, email="sam@example.com", password="secret phrase!", now=at())
    assert log_in(store, email="sam@example.com", password=" secret phrase!", now=at())


def test_a_password_of_whitespace_alone_is_refused(
    store: EventStore, params: ScryptParams
) -> None:
    """Long enough, and still not something anybody could retype."""
    with pytest.raises(InvalidPassword):
        an_account(store, params, password=" " * 20)


@pytest.mark.parametrize(
    "password",
    [
        "a passphrase with spaces",
        "\U0001f600\U0001f601\U0001f602\U0001f603\U0001f604\U0001f605"
        "\U0001f606\U0001f607\U0001f608\U0001f609\U0001f60a\U0001f60b",
        "\U0001d400\U0001d401\U0001d402 astral plane letters",
        "12345678901234567890",
        "................",
    ],
)
def test_there_are_no_composition_rules(
    store: EventStore, params: ScryptParams, password: str
) -> None:
    an_account(store, params, password=password)
    assert log_in(store, email="sam@example.com", password=password, now=at())


def test_log_in_applies_no_password_policy(
    store: EventStore, params: ScryptParams
) -> None:
    """A password legal under an earlier minimum keeps working after it is raised."""
    an_account(store, params)
    user = store.get_user_by_email("sam@example.com")
    store.set_password_hash(user.id, hash_password("four", params=params), at())
    issued = log_in(store, email="sam@example.com", password="four", now=at())
    assert issued.session.user_id == user.id


def test_an_empty_or_over_long_password_fails_login_without_running_the_kdf(
    store: EventStore, params: ScryptParams, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feeding unbounded input to a memory-hard function is the denial of service
    the cap exists to prevent."""
    an_account(store, params)
    accounts_module._dummy_hash()
    calls: list[int] = []
    real = accounts_module._derive

    def counting(password: str, salt: bytes, parameters: ScryptParams) -> bytes:
        calls.append(1)
        return real(password, salt, parameters)

    monkeypatch.setattr(accounts_module, "_derive", counting)
    for password in ("", "x" * (MAX_PASSWORD_LENGTH + 1)):
        with pytest.raises(AuthenticationFailed):
            log_in(store, email="sam@example.com", password=password, now=at())
    assert calls == []


# --- Email normalisation and signup -----------------------------------------


def test_normalise_email_strips_and_lowercases() -> None:
    assert normalise_email("  Sam@Example.COM ") == "sam@example.com"
    assert normalise_email("sam@example.com") == "sam@example.com"
    with pytest.raises(TypeError):
        normalise_email(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "email",
    [
        "",
        "   ",
        "\t",
        "sam",
        "sam@",
        "@example.com",
        "sam@@example.com",
        "sam@example",
        "sam @example.com",
        "sam@exa mple.com",
        "sam@example..com",
        "sam@.com",
        "sam@exam\nple.com",
        "s\u00e4m@example.com",
        "x" * 300,
        "sam@" + "x" * 300 + ".com",
    ],
)
def test_an_unusable_address_is_refused(
    store: EventStore, params: ScryptParams, email: str
) -> None:
    with pytest.raises(InvalidEmail):
        an_account(store, params, email=email)


def test_a_non_string_address_raises_type_error(
    store: EventStore, params: ScryptParams
) -> None:
    with pytest.raises(TypeError):
        an_account(store, params, email=None)  # type: ignore[arg-type]


def test_sign_up_returns_the_stored_user(
    store: EventStore, params: ScryptParams
) -> None:
    user = an_account(store, params, email=" Sam@Example.COM ", display_name=" Sam ")
    assert user.email == "sam@example.com"
    assert user.display_name == "Sam"
    assert user.created_at == at()
    assert store.get_user(user.id) == user
    assert store.get_user_by_email("sam@example.com") == user
    assert verify_password(PASSWORD, store.get_password_hash(user.id)) is True


def test_a_signup_that_fails_on_the_credential_write_leaves_nothing(
    store: EventStore, params: ScryptParams, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One store call, so one transaction: a half-written signup would hold the
    address against the second attempt."""
    monkeypatch.setattr(accounts_module, "hash_password", lambda *a, **k: "not a hash")
    with pytest.raises(DomainError):
        an_account(store, params)
    with pytest.raises(RecordNotFound):
        store.get_user_by_email("sam@example.com")
    monkeypatch.undo()
    user = an_account(store, params)
    assert store.get_user_by_email("sam@example.com") == user


def test_signing_up_twice_leaves_the_first_account_byte_identical(
    store: EventStore, params: ScryptParams
) -> None:
    first = an_account(store, params)
    stored = store.get_password_hash(first.id)
    with pytest.raises(EmailAlreadyRegistered):
        an_account(store, params, password=OTHER_PASSWORD, display_name="Impostor")
    assert store.get_user_by_email("sam@example.com") == first
    assert store.get_password_hash(first.id) == stored


def test_a_differently_spelled_address_still_collides(
    store: EventStore, params: ScryptParams
) -> None:
    an_account(store, params, email="sam@example.com")
    with pytest.raises(EmailAlreadyRegistered):
        an_account(store, params, email="Sam@Example.COM ")


def test_sign_up_creates_no_session(
    store: EventStore, params: ScryptParams
) -> None:
    user = an_account(store, params)
    assert store.delete_sessions_for_user(user.id) == 0


def test_sign_up_links_nothing_and_writes_no_group_or_member(
    store: EventStore, params: ScryptParams
) -> None:
    """Matching a new account to a seeded row by address would let anyone who knows a
    flatmate's address take over their position in the ledger."""
    user = an_account(store, params)
    assert store.list_groups() == ()
    assert store._connection.execute("SELECT count(*) FROM members").fetchone() == (0,)
    log_in(store, email="sam@example.com", password=PASSWORD, now=at())
    assert store._connection.execute("SELECT count(*) FROM members").fetchone() == (0,)
    store.add_group(Group("g1", "Flat", AUD, at()))
    with pytest.raises(RecordNotFound):
        store.get_member_for_user("g1", user.id)


def test_a_blank_display_name_is_the_stores_own_error(
    store: EventStore, params: ScryptParams
) -> None:
    """accounts.py does not re-wrap task 6's validation."""
    with pytest.raises(InvalidRecord):
        an_account(store, params, display_name="   ")


# --- Login ------------------------------------------------------------------


def test_a_successful_login_issues_one_session(
    store: EventStore, params: ScryptParams
) -> None:
    user = an_account(store, params)
    issued = log_in(store, email="sam@example.com", password=PASSWORD, now=at())
    assert isinstance(issued, IssuedSession)
    assert isinstance(issued.session, Session)
    assert issued.session.user_id == user.id
    assert store.get_session(issued.session.token_hash) == issued.session
    assert authenticate(store, issued.token, now=at(1)) == issued.session


def test_two_logins_give_two_distinct_live_sessions(
    store: EventStore, params: ScryptParams
) -> None:
    an_account(store, params)
    first = log_in(store, email="sam@example.com", password=PASSWORD, now=at())
    second = log_in(store, email="sam@example.com", password=PASSWORD, now=at(1))
    assert first.token != second.token
    assert first.session.token_hash != second.session.token_hash
    assert authenticate(store, first.token, now=at(2))
    assert authenticate(store, second.token, now=at(2))


def test_a_login_normalises_the_address_it_is_given(
    store: EventStore, params: ScryptParams
) -> None:
    an_account(store, params)
    assert log_in(store, email=" SAM@Example.com ", password=PASSWORD, now=at())


def test_every_login_failure_is_the_same_type_with_the_same_message(
    store: EventStore, params: ScryptParams
) -> None:
    an_account(store, params)
    store.add_user(User(UserId("u9"), "nopassword@example.com", "No Password", at()))
    messages = []
    for email, password in [
        ("ghost@example.com", PASSWORD),
        ("sam@example.com", "the wrong password"),
        ("nopassword@example.com", PASSWORD),
        ("not an address", PASSWORD),
    ]:
        with pytest.raises(AuthenticationFailed) as caught:
            log_in(store, email=email, password=password, now=at())
        messages.append(str(caught.value))
    assert len(set(messages)) == 1
    assert "sam@example.com" not in messages[0]
    assert "ghost" not in messages[0]


def test_an_unknown_address_and_a_wrong_password_cost_the_same_work(
    store: EventStore, params: ScryptParams, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counted calls, not a clock: a timing assertion on a shared machine is flaky."""
    an_account(store, params)
    store.add_user(User(UserId("u9"), "nopassword@example.com", "No Password", at()))
    accounts_module._dummy_hash()
    calls: list[int] = []
    real = accounts_module._derive

    def counting(password: str, salt: bytes, parameters: ScryptParams) -> bytes:
        calls.append(1)
        return real(password, salt, parameters)

    monkeypatch.setattr(accounts_module, "_derive", counting)
    counted = []
    for email, password in [
        ("ghost@example.com", PASSWORD),
        ("sam@example.com", "the wrong password"),
        ("nopassword@example.com", PASSWORD),
        ("not an address", PASSWORD),
    ]:
        calls.clear()
        with pytest.raises(AuthenticationFailed):
            log_in(store, email=email, password=password, now=at())
        counted.append(len(calls))
    assert counted == [1, 1, 1, 1]


def test_a_user_with_no_credential_row_cannot_log_in(
    store: EventStore, params: ScryptParams
) -> None:
    """Task 6's add_user stays on the surface, so this state is reachable."""
    store.add_user(User(UserId("u9"), "nopassword@example.com", "No Password", at()))
    with pytest.raises(AuthenticationFailed):
        log_in(store, email="nopassword@example.com", password=PASSWORD, now=at())


def test_the_issued_token_never_appears_in_a_repr(
    store: EventStore, params: ScryptParams
) -> None:
    """Credentials reach logs through a repr more often than through a print."""
    an_account(store, params)
    issued = log_in(store, email="sam@example.com", password=PASSWORD, now=at())
    assert issued.token not in repr(issued)
    assert issued.token not in str(issued)
    assert issued.token not in repr(issued.session)


def test_a_token_is_43_characters_and_never_repeats(
    store: EventStore, params: ScryptParams
) -> None:
    an_account(store, params)
    tokens = {
        log_in(
            store, email="sam@example.com", password=PASSWORD, now=at(seconds=index)
        ).token
        for index in range(100)
    }
    assert len(tokens) == 100
    assert {len(token) for token in tokens} == {43}


def test_the_stored_row_holds_the_hash_of_the_token(
    store: EventStore, params: ScryptParams
) -> None:
    an_account(store, params)
    issued = log_in(store, email="sam@example.com", password=PASSWORD, now=at())
    digest = hashlib.sha256(issued.token.encode("utf-8")).hexdigest()
    assert issued.session.token_hash == digest
    assert len(digest) == 64
    assert digest == digest.lower()


def test_the_raw_token_is_nowhere_in_the_database_file(
    tmp_path: Path, params: ScryptParams
) -> None:
    """A stolen file, or a backup, then contains no credential anyone can present."""
    path = tmp_path / "ledger.sqlite3"
    with open_store(path) as opened:
        sign_up(
            opened,
            email="sam@example.com",
            display_name="Sam",
            password=PASSWORD,
            now=at(),
            params=params,
        )
        issued = log_in(opened, email="sam@example.com", password=PASSWORD, now=at())
    written = b"".join(
        candidate.read_bytes()
        for candidate in tmp_path.iterdir()
        if candidate.is_file()
    )
    assert issued.token.encode("utf-8") not in written
    assert PASSWORD.encode("utf-8") not in written
    assert issued.session.token_hash.encode("utf-8") in written


def test_a_session_expires_thirty_days_after_it_was_created(
    store: EventStore, params: ScryptParams
) -> None:
    an_account(store, params)
    issued = log_in(store, email="sam@example.com", password=PASSWORD, now=at())
    assert issued.session.created_at == at()
    assert issued.session.expires_at == at() + SESSION_LIFETIME
    assert SESSION_LIFETIME == timedelta(days=30)


def test_a_token_hash_collision_raises_and_overwrites_nothing(
    store: EventStore, params: ScryptParams, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At 256 bits a collision means the random source is broken. Do not retry it."""
    an_account(store, params)
    monkeypatch.setattr(
        accounts_module.secrets, "token_urlsafe", lambda size: "a" * 43
    )
    first = log_in(store, email="sam@example.com", password=PASSWORD, now=at())
    with pytest.raises(DuplicateRecord):
        log_in(store, email="sam@example.com", password=PASSWORD, now=at(60))
    assert store.get_session(first.session.token_hash) == first.session


def test_a_signup_and_login_round_trip_at_the_default_parameters(
    store: EventStore,
) -> None:
    """At DEFAULT_SCRYPT_PARAMS."""
    user = sign_up(
        store,
        email="sam@example.com",
        display_name="Sam",
        password=PASSWORD,
        now=at(),
    )
    issued = log_in(store, email="sam@example.com", password=PASSWORD, now=at())
    assert issued.session.user_id == user.id
    assert authenticate(store, issued.token, now=at(1)).user_id == user.id
    assert store.get_password_hash(user.id).split("$")[1] == "n=65536,r=8,p=2"


def test_a_wrong_password_is_refused_at_the_default_parameters(
    store: EventStore,
) -> None:
    """At DEFAULT_SCRYPT_PARAMS."""
    sign_up(
        store,
        email="sam@example.com",
        display_name="Sam",
        password=PASSWORD,
        now=at(),
    )
    with pytest.raises(AuthenticationFailed):
        log_in(store, email="sam@example.com", password="the wrong password", now=at())


def test_the_dummy_hash_carries_the_default_parameters() -> None:
    """At DEFAULT_SCRYPT_PARAMS: it is built lazily, so it can never go stale."""
    encoded = accounts_module._dummy_hash()
    assert encoded.split("$")[1] == "n=65536,r=8,p=2"
    assert encoded is accounts_module._dummy_hash()


def test_no_error_message_from_a_failed_call_carries_the_password(
    store: EventStore, params: ScryptParams
) -> None:
    secret = "unmistakable-password-2026"
    an_account(store, params, password=secret)
    user = store.get_user_by_email("sam@example.com")
    failures: list[Exception] = []
    for call in (
        lambda: an_account(store, params, password=secret),
        lambda: an_account(store, params, email="new@example.com", password="short"),
        lambda: log_in(store, email="ghost@example.com", password=secret, now=at()),
        lambda: log_in(store, email="sam@example.com", password=secret + "!", now=at()),
        lambda: change_password(
            store,
            user_id=user.id,
            current_password=secret + "!",
            new_password=OTHER_PASSWORD,
            now=at(),
            params=params,
        ),
        lambda: change_password(
            store,
            user_id=user.id,
            current_password=secret,
            new_password=secret,
            now=at(),
            params=params,
        ),
    ):
        with pytest.raises(AccountError) as caught:
            call()
        failures.append(caught.value)
    for failure in failures:
        assert secret not in str(failure), failure
        assert "short" not in str(failure), failure


# --- Sessions and logout ----------------------------------------------------


def a_signed_in_user(
    store: EventStore, params: ScryptParams, email: str = "sam@example.com"
) -> IssuedSession:
    """One account and one live session for it."""
    an_account(store, params, email=email)
    return log_in(store, email=email, password=PASSWORD, now=at())


def test_authenticate_returns_the_session_for_a_live_token(
    store: EventStore, params: ScryptParams
) -> None:
    issued = a_signed_in_user(store, params)
    assert authenticate(store, issued.token, now=at(60)) == issued.session


@pytest.mark.parametrize(
    "token", ["", "not-a-real-token", "a" * 43, "a" * 5000, "!" * 43]
)
def test_authenticate_refuses_a_token_it_does_not_hold(
    store: EventStore, params: ScryptParams, token: str
) -> None:
    a_signed_in_user(store, params)
    with pytest.raises(SessionInvalid) as caught:
        authenticate(store, token, now=at())
    assert not token or token not in str(caught.value)


def test_a_token_that_is_not_a_string_raises_type_error(store: EventStore) -> None:
    with pytest.raises(TypeError):
        authenticate(store, 1234, now=at())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        log_out(store, None)  # type: ignore[arg-type]


def test_expiry_is_exclusive_to_the_microsecond(
    store: EventStore, params: ScryptParams
) -> None:
    issued = a_signed_in_user(store, params)
    expires_at = issued.session.expires_at
    assert authenticate(store, issued.token, now=expires_at - timedelta(microseconds=1))
    for moment in (expires_at, expires_at + timedelta(microseconds=1)):
        with pytest.raises(SessionInvalid):
            authenticate(store, issued.token, now=moment)


def test_authenticate_never_writes(
    store: EventStore, params: ScryptParams
) -> None:
    """A read that writes is lock contention waiting for the first two people."""
    issued = a_signed_in_user(store, params)
    traced: list[str] = []
    store._connection.set_trace_callback(traced.append)
    try:
        authenticate(store, issued.token, now=at(60))
        with pytest.raises(SessionInvalid):
            authenticate(store, "b" * 43, now=at(60))
    finally:
        store._connection.set_trace_callback(None)
    assert traced
    for statement in traced:
        assert statement.strip().upper().startswith("SELECT"), statement


def test_an_expired_row_is_left_in_place_and_never_honoured(
    store: EventStore, params: ScryptParams
) -> None:
    issued = a_signed_in_user(store, params)
    later = issued.session.expires_at + timedelta(days=1)
    with pytest.raises(SessionInvalid):
        authenticate(store, issued.token, now=later)
    assert store.get_session(issued.session.token_hash) == issued.session
    with pytest.raises(SessionInvalid):
        authenticate(store, issued.token, now=later)
    assert store.delete_expired_sessions(later) == 1


def test_log_out_is_idempotent_and_leaves_the_rest_alone(
    store: EventStore, params: ScryptParams
) -> None:
    an_account(store, params)
    first = log_in(store, email="sam@example.com", password=PASSWORD, now=at())
    second = log_in(store, email="sam@example.com", password=PASSWORD, now=at(1))
    log_out(store, first.token)
    log_out(store, first.token)
    log_out(store, "a token that never existed")
    with pytest.raises(SessionInvalid):
        authenticate(store, first.token, now=at(2))
    assert authenticate(store, second.token, now=at(2)) == second.session


def test_logging_out_an_expired_session_raises_nothing(
    store: EventStore, params: ScryptParams
) -> None:
    issued = a_signed_in_user(store, params)
    log_out(store, issued.token)
    with pytest.raises(RecordNotFound):
        store.get_session(issued.session.token_hash)


def test_log_out_asks_for_no_ownership(
    store: EventStore, params: ScryptParams
) -> None:
    """Possession of the token is the authority, which is what a bearer token means."""
    mine = a_signed_in_user(store, params)
    theirs = a_signed_in_user(store, params, email="other@example.com")
    log_out(store, theirs.token)
    with pytest.raises(SessionInvalid):
        authenticate(store, theirs.token, now=at(1))
    assert authenticate(store, mine.token, now=at(1)) == mine.session


def test_log_out_everywhere_counts_and_touches_no_other_user(
    store: EventStore, params: ScryptParams
) -> None:
    mine = a_signed_in_user(store, params)
    also_mine = log_in(store, email="sam@example.com", password=PASSWORD, now=at(1))
    theirs = a_signed_in_user(store, params, email="other@example.com")
    also_theirs = log_in(
        store, email="other@example.com", password=PASSWORD, now=at(1)
    )
    assert log_out_everywhere(store, mine.session.user_id) == 2
    for token in (mine.token, also_mine.token):
        with pytest.raises(SessionInvalid):
            authenticate(store, token, now=at(2))
    for token in (theirs.token, also_theirs.token):
        assert authenticate(store, token, now=at(2))
    assert log_out_everywhere(store, mine.session.user_id) == 0


def test_log_out_everywhere_raises_for_a_user_that_does_not_exist(
    store: EventStore,
) -> None:
    with pytest.raises(RecordNotFound):
        log_out_everywhere(store, UserId("ghost"))


# --- Password change --------------------------------------------------------


def test_change_password_replaces_the_hash_with_a_freshly_salted_one(
    store: EventStore, params: ScryptParams
) -> None:
    an_account(store, params)
    user = store.get_user_by_email("sam@example.com")
    before = store.get_password_hash(user.id)
    change_password(
        store,
        user_id=user.id,
        current_password=PASSWORD,
        new_password=OTHER_PASSWORD,
        now=at(60),
        params=params,
    )
    after = store.get_password_hash(user.id)
    assert after != before
    assert after.split("$")[2] != before.split("$")[2]
    assert verify_password(OTHER_PASSWORD, after) is True
    assert verify_password(PASSWORD, after) is False


def test_after_a_change_the_new_password_logs_in_and_the_old_one_does_not(
    store: EventStore, params: ScryptParams
) -> None:
    an_account(store, params)
    user = store.get_user_by_email("sam@example.com")
    change_password(
        store,
        user_id=user.id,
        current_password=PASSWORD,
        new_password=OTHER_PASSWORD,
        now=at(60),
        params=params,
    )
    assert log_in(store, email="sam@example.com", password=OTHER_PASSWORD, now=at(61))
    with pytest.raises(AuthenticationFailed):
        log_in(store, email="sam@example.com", password=PASSWORD, now=at(61))


def test_a_change_revokes_every_session_including_the_one_that_made_it(
    store: EventStore, params: ScryptParams
) -> None:
    """Leaving a session alive after a credential change is the exact hole that makes
    changing a leaked password pointless."""
    issued = a_signed_in_user(store, params)
    other_device = log_in(store, email="sam@example.com", password=PASSWORD, now=at(1))
    change_password(
        store,
        user_id=issued.session.user_id,
        current_password=PASSWORD,
        new_password=OTHER_PASSWORD,
        now=at(60),
        params=params,
    )
    for token in (issued.token, other_device.token):
        with pytest.raises(SessionInvalid):
            authenticate(store, token, now=at(61))


def test_a_wrong_current_password_changes_nothing(
    store: EventStore, params: ScryptParams
) -> None:
    issued = a_signed_in_user(store, params)
    before = store.get_password_hash(issued.session.user_id)
    with pytest.raises(AuthenticationFailed):
        change_password(
            store,
            user_id=issued.session.user_id,
            current_password="the wrong password",
            new_password=OTHER_PASSWORD,
            now=at(60),
            params=params,
        )
    assert store.get_password_hash(issued.session.user_id) == before
    assert authenticate(store, issued.token, now=at(61)) == issued.session


def test_a_new_password_that_fails_the_policy_changes_nothing(
    store: EventStore, params: ScryptParams
) -> None:
    issued = a_signed_in_user(store, params)
    before = store.get_password_hash(issued.session.user_id)
    with pytest.raises(InvalidPassword):
        change_password(
            store,
            user_id=issued.session.user_id,
            current_password=PASSWORD,
            new_password="short",
            now=at(60),
            params=params,
        )
    assert store.get_password_hash(issued.session.user_id) == before
    assert authenticate(store, issued.token, now=at(61)) == issued.session


def test_a_new_password_equal_to_the_current_one_is_refused(
    store: EventStore, params: ScryptParams
) -> None:
    """Rewriting the same secret buys nothing and costs every session they hold."""
    issued = a_signed_in_user(store, params)
    with pytest.raises(InvalidPassword):
        change_password(
            store,
            user_id=issued.session.user_id,
            current_password=PASSWORD,
            new_password=PASSWORD,
            now=at(60),
            params=params,
        )
    assert authenticate(store, issued.token, now=at(61)) == issued.session


def test_the_hash_and_the_revocation_cannot_half_happen(
    store: EventStore, params: ScryptParams, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forced to fail between the two writes: both are still as they were."""
    issued = a_signed_in_user(store, params)
    before = store.get_password_hash(issued.session.user_id)
    monkeypatch.setattr(accounts_module, "hash_password", lambda *a, **k: "not a hash")
    with pytest.raises(DomainError):
        change_password(
            store,
            user_id=issued.session.user_id,
            current_password=PASSWORD,
            new_password=OTHER_PASSWORD,
            now=at(60),
            params=params,
        )
    assert store.get_password_hash(issued.session.user_id) == before
    assert authenticate(store, issued.token, now=at(61)) == issued.session


def test_a_change_touches_no_other_account(
    store: EventStore, params: ScryptParams
) -> None:
    mine = a_signed_in_user(store, params)
    theirs = a_signed_in_user(store, params, email="other@example.com")
    their_hash = store.get_password_hash(theirs.session.user_id)
    change_password(
        store,
        user_id=mine.session.user_id,
        current_password=PASSWORD,
        new_password=OTHER_PASSWORD,
        now=at(60),
        params=params,
    )
    assert store.get_password_hash(theirs.session.user_id) == their_hash
    assert authenticate(store, theirs.token, now=at(61)) == theirs.session


# --- The user-to-member link ------------------------------------------------


def test_a_signed_in_user_resolves_to_the_member_acting_in_a_group(
    store: EventStore, params: ScryptParams
) -> None:
    """The whole of what task 7 owns about the link: reading it."""
    issued = a_signed_in_user(store, params)
    session = authenticate(store, issued.token, now=at(60))
    store.add_group(Group("g1", "Flat", AUD, at()))
    store.add_member(Member("m1", "g1", "Sam", session.user_id, at()))
    store.add_member(Member("m2", "g1", "Alex", None, at()))
    assert store.get_member_for_user("g1", session.user_id).id == "m1"


def test_a_brand_new_account_is_a_member_of_nothing(
    store: EventStore, params: ScryptParams
) -> None:
    user = an_account(store, params)
    store.add_group(Group("g1", "Flat", AUD, at()))
    store.add_member(Member("m1", "g1", "Sam", None, at()))
    with pytest.raises(RecordNotFound):
        store.get_member_for_user("g1", user.id)
