"""Tests for the application server and the JSON API.

Task 9a of plans/backlog.md, sharpened in
plans/tasks/09a-application-server-and-http-api.md.

Everything here drives the app through ``app.test_client()``. **No test binds a socket
or opens a port**, so nothing in this file can collide with a port already in use.

One test starts one thread, and only one:
``test_two_marks_at_once_record_one_settlement_and_refuse_the_other``, because the rule
it checks is about two requests at once and no single-threaded test can be about that.
It forces the interleaving rather than racing for it, every wait it makes carries a
timeout, and it joins the thread it started, so it cannot hang the suite either. That
sentence used to read "no test binds a socket, starts a thread or opens a port"; the
half of it that still holds is the half above.

Every account is made with cheap scrypt parameters, injected into ``create_app`` the
same way tasks 7 and 9 inject them into ``sign_up``: no test runs the memory-hard KDF
at production cost.

Paths are resolved from this file, never from the current working directory.
"""

from __future__ import annotations

import itertools
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pytest

from splitwise_lite import web
from splitwise_lite.accounts import ScryptParams
from splitwise_lite.groups import GroupDefinition, apply_group_definition
from splitwise_lite.money import Currency
from splitwise_lite.store import open_store

REPO = Path(__file__).resolve().parents[1]
APP_DIR = REPO / "app"

CHEAP = ScryptParams(n=16, r=1, p=1)
"""scrypt at 16 KiB and one round: the same shape tasks 7 and 9 use, so the suite
exercises the code path without spending 64 MiB and a third of a second per call."""

PASSWORD = "correct horse battery staple"
OTHER_PASSWORD = "a different long enough passphrase"

GROUP_NAME = "Flat 3"
CURRENCY = "AUD"
ROSTER = ("Sam", "Ali", "Jo")


def at(hour: int = 9, minute: int = 0) -> datetime:
    """A fixed, timezone-aware instant, so nothing here depends on the wall clock."""
    return datetime(2026, 9, 5, hour, minute, tzinfo=timezone.utc)


def seed_group(
    path: Path,
    *,
    name: str = GROUP_NAME,
    currency: str = CURRENCY,
    members: tuple[str, ...] = ROSTER,
) -> None:
    """Apply one roster to the store at ``path``, the way the operator command does."""
    definition = GroupDefinition(name, Currency(currency), members)
    with open_store(path) as store:
        apply_group_definition(store, definition, now=at())


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A file-backed store under ``tmp_path``. Never ``IN_MEMORY``: the app opens one
    store per request, and a private in-memory database would be empty every time."""
    return tmp_path / "ledger.sqlite3"


@pytest.fixture
def seeded(store_path: Path) -> Path:
    """A store holding exactly one group and its roster."""
    seed_group(store_path)
    return store_path


@pytest.fixture
def app(seeded: Path):
    """The application under test, with cookies sent without ``Secure``."""
    return web.create_app(
        store_path=seeded, secure_cookies=False, scrypt_params=CHEAP
    )


@pytest.fixture
def secure_app(seeded: Path):
    """The same application with ``secure_cookies=True``, for the cookie criteria."""
    return web.create_app(store_path=seeded, secure_cookies=True, scrypt_params=CHEAP)


@pytest.fixture
def empty_app(store_path: Path):
    """An app over a store with no group at all, so 503 and 401 can be told apart."""
    return web.create_app(
        store_path=store_path, secure_cookies=False, scrypt_params=CHEAP
    )


@pytest.fixture
def client(app):
    return app.test_client()


# --- The dependency ---------------------------------------------------------


def test_importing_the_package_does_not_import_the_framework() -> None:
    # The domain layer stays importable, testable and reusable with Flask absent.
    # That is the property that keeps the framework decision reversible, so it is
    # asserted in a fresh interpreter rather than against this one, which has
    # already imported web.
    finished = subprocess.run(
        [
            sys.executable,
            "-c",
            "import splitwise_lite, sys; assert 'flask' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert finished.returncode == 0, finished.stderr


def test_the_package_root_does_not_re_export_the_http_layer() -> None:
    import splitwise_lite

    assert "web" not in splitwise_lite.__all__
    assert "create_app" not in splitwise_lite.__all__
    assert not hasattr(splitwise_lite, "create_app")
    assert splitwise_lite.__version__ == "0.1.0"
    assert "splitwise_lite.web" in (splitwise_lite.__doc__ or "")


# --- The application factory and the store ----------------------------------


def test_create_app_returns_a_flask_application(app) -> None:
    import flask

    assert isinstance(app, flask.Flask)


def test_store_path_and_secure_cookies_are_required_keyword_arguments() -> None:
    import inspect

    signature = inspect.signature(web.create_app)
    for name in ("store_path", "secure_cookies"):
        parameter = signature.parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameter.default is inspect.Parameter.empty, name
    for name in ("app_dir", "scrypt_params"):
        parameter = signature.parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameter.default is None, name


def test_an_in_memory_store_is_refused_with_a_reason(tmp_path: Path) -> None:
    # A per-request connection to a private in-memory database is a fresh, empty
    # ledger every request, which would look like data loss rather than a mistake.
    from splitwise_lite.store import IN_MEMORY

    with pytest.raises(ValueError) as raised:
        web.create_app(store_path=IN_MEMORY, secure_cookies=False)
    assert "in-memory" in str(raised.value)
    assert "per request" in str(raised.value)


def test_the_app_directory_is_resolved_from_the_module_not_the_working_directory(
    app,
) -> None:
    assert app.config["APP_DIR"] == APP_DIR
    assert (app.config["APP_DIR"] / "index.html").is_file()


def test_a_given_app_directory_is_used_instead(seeded: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "shell"
    elsewhere.mkdir()
    (elsewhere / "index.html").write_bytes(b"<!doctype html>\n")
    other = web.create_app(
        store_path=seeded, secure_cookies=False, app_dir=elsewhere
    )
    assert other.config["APP_DIR"] == elsewhere
    assert other.test_client().get("/").data == b"<!doctype html>\n"


def test_the_store_is_opened_per_request_and_closed_afterwards(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = []
    real = web.open_store

    def recording(path):
        store = real(path)
        opened.append(store)
        return store

    monkeypatch.setattr(web, "open_store", recording)
    client = app.test_client()
    for _ in range(2):
        # A token that has to be looked up, so the request genuinely reaches the
        # store. It is set again each time because the 401 clears it.
        client.set_cookie(web.SESSION_COOKIE, "not-a-live-token")
        assert client.get("/api/session").status_code == 401
    assert len(opened) == 2
    for store in opened:
        # ``close`` clears the connection, so this is the store's own record of it.
        assert store._connection is None


def test_a_request_that_raised_still_closes_its_store(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = []
    real = web.open_store

    def recording(path):
        store = real(path)
        opened.append(store)
        return store

    monkeypatch.setattr(web, "open_store", recording)
    client = app.test_client()
    signed_in(client, app)

    def explode(*arguments, **keywords):
        raise RuntimeError("the handler blew up")

    monkeypatch.setattr(web.groups, "resolve_sole_group", explode)
    assert client.get("/api/session").status_code == 500
    assert opened
    for store in opened:
        assert store._connection is None


def test_the_test_can_open_the_same_file_alongside_the_apps_connection(
    app, seeded: Path
) -> None:
    # "Two stores on the same file is a supported arrangement", which is what makes
    # a store per request safe under a threaded server.
    with open_store(seeded) as mine:
        assert len(mine.list_groups()) == 1
        assert app.test_client().get("/").status_code == 200
        assert len(mine.list_groups()) == 1


def test_creating_the_app_binds_no_socket_and_starts_no_server(app) -> None:
    # There is no server object, no port and no thread anywhere on the app.
    assert not hasattr(app, "server")
    assert app.config["STORE_PATH"] is not None


def test_two_apps_share_no_rate_limiter(seeded: Path) -> None:
    first = web.create_app(
        store_path=seeded, secure_cookies=False, scrypt_params=CHEAP
    )
    second = web.create_app(
        store_path=seeded, secure_cookies=False, scrypt_params=CHEAP
    )
    limiter = first.extensions["splitwise_lite"].limiter
    assert limiter is not second.extensions["splitwise_lite"].limiter
    exhaust_address_bucket(first)
    assert failed_login(first.test_client()).status_code == 429
    assert failed_login(second.test_client()).status_code == 401


# --- Serving the shell ------------------------------------------------------


def test_the_root_serves_the_shell_document(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.data.startswith(b"<!doctype html>")


@pytest.mark.parametrize(
    "path, content_type",
    [
        ("/app.js", "text/javascript; charset=utf-8"),
        ("/api.js", "text/javascript; charset=utf-8"),
        ("/sw.js", "text/javascript; charset=utf-8"),
        ("/styles.css", "text/css; charset=utf-8"),
        ("/manifest.json", "application/json"),
        ("/icons/icon-192.png", "image/png"),
    ],
)
def test_static_content_types_come_from_the_explicit_map(
    client, path: str, content_type: str
) -> None:
    # Python's mimetypes reads the Windows registry, where .js is commonly mapped to
    # text/plain, and a browser enforces a JavaScript type on a worker script
    # strictly. Guessing here would leave the app uninstallable on this machine.
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == content_type


def test_an_icon_keeps_its_png_signature(client) -> None:
    response = client.get("/icons/icon-192.png")
    assert response.status_code == 200
    assert response.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_extension_map_covers_every_type_the_shell_needs() -> None:
    assert set(web.EXTENSIONS) >= {
        ".html",
        ".css",
        ".js",
        ".json",
        ".webmanifest",
        ".png",
        ".ico",
    }
    assert web.EXTENSIONS[".js"] == "text/javascript; charset=utf-8"
    assert web.EXTENSIONS[".webmanifest"] == "application/manifest+json"


def test_an_unmapped_extension_is_served_as_an_opaque_stream(
    seeded: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "shell"
    elsewhere.mkdir()
    (elsewhere / "notes.txt").write_text("plain", encoding="utf-8")
    other = web.create_app(
        store_path=seeded, secure_cookies=False, app_dir=elsewhere
    )
    response = other.test_client().get("/notes.txt")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/octet-stream"


def test_there_is_no_static_route(app, client) -> None:
    assert app.static_folder is None
    assert client.get("/static/anything").status_code == 404
    assert "static" not in {rule.endpoint for rule in app.url_map.iter_rules()}


@pytest.mark.parametrize(
    "path",
    [
        "/../pyproject.toml",
        "/%2e%2e/pyproject.toml",
        "/..%2fpyproject.toml",
        "/a/../../pyproject.toml",
        "/..%5cpyproject.toml",
    ],
)
def test_path_traversal_never_reaches_a_file_outside_the_app_directory(
    client, path: str
) -> None:
    response = client.get(path)
    assert response.status_code == 404, path
    assert b"hatchling" not in response.data, path
    assert b"splitwise-lite" not in response.data, path


def test_a_missing_static_path_does_not_fall_back_to_the_shell(client) -> None:
    # Hash routing means every route asks for the same document, so a catch-all
    # would only hide typos.
    response = client.get("/nothing-here.txt")
    assert response.status_code == 404
    assert b"<!doctype html>" not in response.data


# --- Response headers -------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/app.js",
        "/api.js",
        "/sw.js",
        "/styles.css",
        "/manifest.json",
        "/icons/icon-192.png",
        "/nothing-here.txt",
        "/api/session",
        "/api/nope",
    ],
)
def test_every_response_forbids_caching_and_sniffing(client, path: str) -> None:
    # A stale balance is exactly the "looks authoritative while being wrong" failure
    # the spec names as the product's largest risk.
    response = client.get(path)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert response.headers["X-Frame-Options"] == "DENY"


@pytest.mark.parametrize("path", ["/", "/api/session", "/api/nope"])
def test_no_response_carries_a_cors_header(client, path: str) -> None:
    # There is no CORS support and no CORS library, which is part of why the CSRF
    # gates hold: a cross-site page cannot read what it is not allowed to send.
    response = client.get(path)
    for name in response.headers.keys():
        assert not name.lower().startswith("access-control-"), name


# --- Helpers shared with the later sections ---------------------------------


def csrf_token(client) -> str:
    """Load the shell once, the way a browser does, and read the issued token."""
    client.get("/")
    cookie = client.get_cookie(web.CSRF_COOKIE)
    assert cookie is not None
    return cookie.value


def post(client, path: str, payload: dict | None = None, **keywords):
    """A state-changing request with the three CSRF gates met."""
    return send(client, "POST", path, payload, **keywords)


def send(client, method: str, path: str, payload: dict | None = None, **keywords):
    headers = {web.CSRF_HEADER: csrf_token(client)}
    headers.update(keywords.pop("headers", {}))
    return client.open(
        path,
        method=method,
        json={} if payload is None else payload,
        headers=headers,
        **keywords,
    )


def failed_login(client_or_app, email: str = "nobody@example.com"):
    """One login that cannot succeed, with the CSRF gates met."""
    client = (
        client_or_app
        if hasattr(client_or_app, "get_cookie")
        else client_or_app.test_client()
    )
    return post(client, "/api/session", {"email": email, "password": PASSWORD})


def exhaust_address_bucket(app) -> None:
    """Spend the per-address failure budget, spread over enough email addresses that
    no single email bucket fills first."""
    client = app.test_client()
    for index in range(web.LOGIN_LIMIT_PER_ADDRESS):
        address = f"nobody{index // 5}@example.com"
        assert failed_login(client, address).status_code == 401


def signed_in(client, app, *, email: str = "sam@example.com") -> None:
    """Sign a fresh account up and in, leaving the client holding both cookies."""
    assert (
        post(
            client,
            "/api/signup",
            {"email": email, "display_name": "Sam", "password": PASSWORD},
        ).status_code
        == 201
    )
    assert (
        post(client, "/api/session", {"email": email, "password": PASSWORD}).status_code
        == 200
    )


def sign_up(
    client,
    *,
    email: str = "sam@example.com",
    display_name: str = "Sam",
    password: str = PASSWORD,
):
    """One signup with the CSRF gates met."""
    return post(
        client,
        "/api/signup",
        {"email": email, "display_name": display_name, "password": password},
    )


def log_in(client, *, email: str = "sam@example.com", password: str = PASSWORD):
    """One sign-in with the CSRF gates met."""
    return post(client, "/api/session", {"email": email, "password": password})


def set_cookies(response) -> dict[str, dict[str, str]]:
    """Every ``Set-Cookie`` header on ``response``, parsed name by field.

    Parsed rather than string-matched, so the assertions below name each attribute
    they care about and notice one that quietly disappears.
    """
    parsed: dict[str, dict[str, str]] = {}
    for header in response.headers.getlist("Set-Cookie"):
        first, *rest = (part.strip() for part in header.split(";"))
        name, _, value = first.partition("=")
        attributes = {"value": value}
        for part in rest:
            key, _, attribute = part.partition("=")
            attributes[key.lower()] = attribute
        parsed[name] = attributes
    return parsed


def link_member(path: Path, email: str, display_name: str) -> str:
    """Link the account at ``email`` to the member named ``display_name``.

    Exactly what ``setup_group.py link`` does, which is the only thing in the
    repository that links a user to a member.
    """
    from splitwise_lite.groups import link_user_to_member, resolve_sole_group

    with open_store(path) as store:
        group = resolve_sole_group(store)
        user = store.get_user_by_email(email)
        member = next(
            found
            for found in store.list_members(group.id)
            if found.display_name == display_name
        )
        link_user_to_member(
            store, group_id=group.id, member_id=member.id, user_id=user.id
        )
        return member.id


def linked_client(app, path: Path, *, display_name: str = "Sam"):
    """A client signed in as an account linked to ``display_name``."""
    client = app.test_client()
    email = f"{display_name.lower()}@example.com"
    assert sign_up(client, email=email, display_name=display_name).status_code == 201
    link_member(path, email, display_name)
    assert log_in(client, email=email).status_code == 200
    return client


# --- The shape of the module ------------------------------------------------


def web_source() -> str:
    return Path(web.__file__).read_text(encoding="utf-8")


PUBLIC = {
    "WebError",
    "NotAuthenticated",
    "CsrfFailed",
    "MalformedRequest",
    "SettlementAlreadyPending",
    "TooManyAttempts",
    "RateLimiter",
    "create_app",
    "ERROR_STATUS",
    "ERROR_CODE",
    "SESSION_COOKIE",
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "EXTENSIONS",
    "LOGIN_WINDOW",
    "LOGIN_LIMIT_PER_EMAIL",
    "LOGIN_LIMIT_PER_ADDRESS",
    "MAX_BODY_BYTES",
}


def top_level_definitions(source: str) -> set[str]:
    """Every name the module defines at the top level, from its AST."""
    import ast

    defined: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
    return defined


def test_the_public_surface_is_exactly_the_named_names() -> None:
    assert set(web.__all__) == PUBLIC
    assert len(web.__all__) == len(PUBLIC)
    for name in PUBLIC:
        assert hasattr(web, name), name


def test_everything_else_the_module_defines_is_underscored() -> None:
    defined = top_level_definitions(web_source())
    assert {name for name in defined if not name.startswith("_")} == PUBLIC


def test_every_public_name_has_a_docstring() -> None:
    """Tasks 10, 11 and 12 are written against these, so none may be undocumented."""
    import ast

    tree = ast.parse(web_source())
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


def test_the_module_docstring_records_every_decision_it_makes() -> None:
    text = " ".join((web.__doc__ or "").split())
    for stated in (
        "The framework is Flask",
        "A store is opened per request",
        "The session cookie",
        "CSRF is three cheap gates",
        "Login rate limiting",
        "walking the raised exception's MRO",
        "Reading the ledger requires a member link",
        "A route is registered with its access policy",
    ):
        assert stated in text, stated


def test_there_is_no_second_http_module_and_no_web_package() -> None:
    package = Path(web.__file__).parent
    assert not (package / "web").exists()
    assert {path.name for path in package.glob("*.py")} == {
        "__init__.py",
        "accounts.py",
        "balances.py",
        "events.py",
        "groups.py",
        "money.py",
        "simplify.py",
        "split.py",
        "store.py",
        "web.py",
    }


@pytest.mark.parametrize(
    "forbidden",
    [
        "SELECT ",
        "INSERT ",
        "UPDATE ",
        "DELETE FROM",
        "CREATE TABLE",
        "PRAGMA",
        "execute(",
        "user_credentials",
        "expense_events",
        "expense_allocations",
        "settlement_events",
        "settlement_decision_events",
    ],
)
def test_the_module_writes_no_sql_and_names_no_table(forbidden: str) -> None:
    # Task 6's rule for every consumer: all storage goes through ``EventStore``.
    assert forbidden not in web_source()


def imported_packages(source: str) -> set[str]:
    """Top-level package names imported absolutely, from the AST."""
    import ast

    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.partition(".")[0])
    return found


def test_the_module_imports_flask_and_the_standard_library_only() -> None:
    assert imported_packages(web_source()) == {
        "__future__",
        "enum",
        "hmac",
        "json",
        "secrets",
        "threading",
        "dataclasses",
        "datetime",
        "pathlib",
        "typing",
        "flask",
    }


@pytest.mark.parametrize(
    "forbidden",
    [
        "werkzeug",
        "jinja2",
        "itsdangerous",
        "markupsafe",
        "click",
        "blinker",
        "mimetypes",
        "random",
        "sqlite3",
        "flask_wtf",
        "flask_cors",
        "flask_login",
        "flask_limiter",
        "flask_seasurf",
        "marshmallow",
        "pydantic",
    ],
)
def test_the_module_imports_no_transitive_package_and_no_second_library(
    forbidden: str,
) -> None:
    # The one declared dependency has to tell the whole truth, and a CSRF, CORS or
    # serialisation library would be a second dependency nobody chose.
    assert forbidden not in imported_packages(web_source())


def test_the_module_never_reaches_for_flasks_own_session_machinery() -> None:
    # Task 7's design is an opaque random token in a server-side table. A signed
    # client-held cookie, a SECRET_KEY or a rendered template would each be a second
    # mechanism doing the same job differently.
    import ast

    tree = ast.parse(web_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "flask":
            for alias in node.names:
                assert alias.name not in {"session", "flash", "render_template"}
        if isinstance(node, ast.Attribute):
            reaching = isinstance(node.value, ast.Name) and node.value.id == "flask"
            assert not reaching or node.attr not in {"session", "flash", "secret_key"}
        if isinstance(node, ast.Call):
            name = node.func
            if isinstance(name, ast.Name):
                called = name.id
            elif isinstance(name, ast.Attribute):
                called = name.attr
            else:
                called = ""
            assert called not in {"render_template", "render_template_string"}
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value != "SECRET_KEY"


def test_no_module_in_the_package_imports_the_web_layer() -> None:
    # Dependency direction stays one way, which is what keeps the domain layer
    # importable with Flask uninstalled.
    import ast

    package = Path(web.__file__).parent
    for path in sorted(package.glob("*.py")):
        if path.name == "web.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "web", path.name
                if node.level:
                    assert all(alias.name != "web" for alias in node.names), path.name
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.endswith(".web"), path.name


def test_the_csrf_comparison_is_constant_time_and_never_an_equals() -> None:
    import ast

    tree = ast.parse(web_source())
    gate = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_check_csrf"
    )
    calls = {
        node.func.attr
        for node in ast.walk(gate)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "compare_digest" in calls
    for node in ast.walk(gate):
        if isinstance(node, ast.Compare) and any(
            isinstance(operator, (ast.Eq, ast.NotEq)) for operator in node.ops
        ):
            names = {
                inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)
            }
            assert not names & {"submitted", "stored"}, ast.dump(node)


def test_the_clock_is_read_once_and_only_in_one_place() -> None:
    import ast

    source = web_source()
    tree = ast.parse(source)
    reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "now"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "datetime"
    ]
    assert len(reads) == 1
    holder = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_now"
    )
    assert reads[0] in list(ast.walk(holder))
    assert "utcnow(" not in source
    assert "time.time" not in source


def test_no_endpoint_accepts_a_client_supplied_time(app, seeded: Path) -> None:
    signed = linked_client(app, seeded)
    response = post(
        signed,
        "/api/expenses",
        {
            "description": "Milk",
            "amount": "12.50",
            "payer_id": "whoever",
            "split": {"mode": "equal", "member_ids": []},
            "now": "2020-01-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    assert "'now'" in body["error"]["message"]


# --- CSRF -------------------------------------------------------------------


def test_a_safe_request_without_the_cookie_is_answered_with_one(client) -> None:
    response = client.get("/")
    cookie = set_cookies(response)[web.CSRF_COOKIE]
    assert cookie["value"]
    assert cookie["path"] == "/"
    assert cookie["samesite"] == "Lax"
    # Not HttpOnly, because the client has to read it back into a header.
    assert "httponly" not in cookie
    assert "secure" not in cookie
    assert "domain" not in cookie


def test_the_csrf_cookie_is_secure_when_the_app_was_built_that_way(secure_app) -> None:
    cookie = set_cookies(secure_app.test_client().get("/"))[web.CSRF_COOKIE]
    assert "secure" in cookie


def test_a_safe_request_that_already_has_the_cookie_is_not_issued_another(
    client,
) -> None:
    first = client.get("/")
    assert web.CSRF_COOKIE in set_cookies(first)
    second = client.get("/")
    assert web.CSRF_COOKIE not in set_cookies(second)


def fresh_csrf_token(client) -> str:
    """Force a fresh CSRF cookie by discarding the one the client holds."""
    client.delete_cookie(web.CSRF_COOKIE)
    client.get("/")
    return client.get_cookie(web.CSRF_COOKIE).value


def test_the_csrf_token_is_thirty_two_bytes_of_url_safe_randomness(client) -> None:
    tokens = {fresh_csrf_token(client) for _ in range(5)}
    assert len(tokens) == 5
    for token in tokens:
        assert len(token) == 43
        assert set(token) <= set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )


@pytest.mark.parametrize(
    "content_type",
    [
        "text/plain",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        None,
    ],
)
def test_a_state_changing_request_must_be_json(client, content_type) -> None:
    # A cross-site HTML form can only send one of the first three, and anything else
    # forces a preflight this app never answers.
    token = csrf_token(client)
    response = client.post(
        "/api/signup",
        data=b'{"email": "sam@example.com"}',
        content_type=content_type,
        headers={web.CSRF_HEADER: token},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"


def test_a_json_content_type_with_a_charset_parameter_is_accepted(client) -> None:
    token = csrf_token(client)
    response = client.post(
        "/api/signup",
        data=b"{}",
        content_type="application/json; charset=utf-8",
        headers={web.CSRF_HEADER: token},
    )
    # Past the gate: the refusal is about the body, not about where it came from.
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "malformed_request"


def test_a_missing_csrf_header_is_refused(client) -> None:
    csrf_token(client)
    response = client.post("/api/signup", json={})
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"


def test_a_csrf_header_that_does_not_match_the_cookie_is_refused(client) -> None:
    csrf_token(client)
    response = client.post(
        "/api/signup", json={}, headers={web.CSRF_HEADER: "a different token"}
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"


def test_a_missing_csrf_cookie_is_refused(client) -> None:
    token = csrf_token(client)
    client.delete_cookie(web.CSRF_COOKIE)
    response = client.post("/api/signup", json={}, headers={web.CSRF_HEADER: token})
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"


def test_a_request_from_another_origin_is_refused(client) -> None:
    token = csrf_token(client)
    response = client.post(
        "/api/signup",
        json={},
        headers={web.CSRF_HEADER: token, "Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"


def test_a_request_from_this_origin_passes_the_origin_gate(client) -> None:
    token = csrf_token(client)
    response = client.post(
        "/api/signup",
        json={},
        headers={web.CSRF_HEADER: token, "Origin": "http://localhost"},
    )
    assert response.status_code == 400


def test_a_request_with_no_origin_header_is_not_refused_on_that_ground(client) -> None:
    # Some same-origin requests omit it, and gates 1 and 2 already stand.
    token = csrf_token(client)
    response = client.post("/api/signup", json={}, headers={web.CSRF_HEADER: token})
    assert response.status_code == 400


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_safe_methods_are_never_gated(client, method: str) -> None:
    response = client.open("/api/session", method=method)
    assert response.status_code != 403


def test_options_is_answered_without_any_cross_origin_permission(client) -> None:
    response = client.options("/api/session")
    assert response.status_code == 200
    assert response.headers["Allow"]
    for name in response.headers.keys():
        assert not name.lower().startswith("access-control-"), name


# --- Session transport ------------------------------------------------------


def test_a_successful_login_sets_the_session_cookie_field_by_field(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from splitwise_lite.accounts import SESSION_LIFETIME

    assert sign_up(client).status_code == 201
    monkeypatch.setattr(web, "_now", lambda: at())
    response = log_in(client)
    assert response.status_code == 200
    cookie = set_cookies(response)[web.SESSION_COOKIE]
    assert set(cookie) == {
        "value",
        "expires",
        "max-age",
        "httponly",
        "path",
        "samesite",
    }
    assert cookie["max-age"] == str(int(SESSION_LIFETIME.total_seconds()))
    assert cookie["max-age"] == "2592000"
    assert cookie["path"] == "/"
    assert cookie["samesite"] == "Lax"
    assert cookie["httponly"] == ""
    assert "domain" not in cookie
    assert "secure" not in cookie
    # The raw token, unsigned, unencrypted and not encoded again: 43 characters.
    assert len(cookie["value"]) == 43


def test_the_session_cookie_is_secure_when_the_app_was_built_that_way(
    secure_app,
) -> None:
    client = secure_app.test_client()
    assert sign_up(client).status_code == 201
    cookie = set_cookies(log_in(client))[web.SESSION_COOKIE]
    assert "secure" in cookie
    assert "httponly" in cookie


def test_the_raw_token_appears_only_in_the_set_cookie_header(client, caplog) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    assert sign_up(client).status_code == 201
    response = log_in(client)
    token = set_cookies(response)[web.SESSION_COOKIE]["value"]
    assert token not in response.get_data(as_text=True)
    assert token not in caplog.text
    following = client.get("/api/session")
    assert token not in following.get_data(as_text=True)


def test_reading_the_session_extends_nothing(app, seeded: Path) -> None:
    signed = linked_client(app, seeded)
    response = signed.get("/api/session")
    assert response.status_code == 200
    assert web.SESSION_COOKIE not in set_cookies(response)


def test_the_session_view_names_the_user_the_group_and_the_member(
    app, seeded: Path
) -> None:
    signed = linked_client(app, seeded)
    body = signed.get("/api/session").get_json()
    assert set(body) == {"user", "group", "member"}
    assert set(body["user"]) == {"id", "email", "display_name"}
    assert body["user"]["email"] == "sam@example.com"
    assert set(body["group"]) == {"id", "name", "currency"}
    assert body["group"]["name"] == GROUP_NAME
    assert body["group"]["currency"] == CURRENCY
    assert set(body["member"]) == {"id", "display_name"}
    assert body["member"]["display_name"] == "Sam"


def test_a_session_issued_before_the_link_resolves_to_the_member_afterwards(
    app, seeded: Path
) -> None:
    # Nothing about the member is cached in the session or the cookie.
    client = app.test_client()
    assert sign_up(client).status_code == 201
    assert log_in(client).status_code == 200
    assert client.get("/api/session").get_json()["member"] is None
    member_id = link_member(seeded, "sam@example.com", "Sam")
    assert client.get("/api/session").get_json()["member"]["id"] == member_id


def test_a_request_with_no_session_cookie_clears_nothing(client) -> None:
    response = client.get("/api/session")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "not_authenticated"
    assert web.SESSION_COOKIE not in set_cookies(response)


def assert_refused_and_cleared(response) -> None:
    """A 401 ``session_invalid`` whose response clears the cookie it refused.

    Without the clearing, a stale token sits in the browser producing a 401 on every
    request forever, and the user has no way to get rid of it.
    """
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "session_invalid"
    cleared = set_cookies(response)[web.SESSION_COOKIE]
    assert cleared["max-age"] == "0"
    assert cleared["path"] == "/"
    assert cleared["samesite"] == "Lax"
    assert "httponly" in cleared
    assert "secure" not in cleared


def test_an_unknown_token_is_refused_and_cleared(client) -> None:
    client.set_cookie(web.SESSION_COOKIE, "Ux3vHqk8Zt2LmQpRwYsNbCdFgHjKlPoIuYtReWqAsDf")
    assert_refused_and_cleared(client.get("/api/session"))


def test_a_malformed_token_is_refused_and_cleared(client) -> None:
    client.set_cookie(web.SESSION_COOKIE, "not a token at all!")
    assert_refused_and_cleared(client.get("/api/session"))


@pytest.mark.filterwarnings("ignore:The .* cookie is too large")
def test_an_over_long_token_is_refused_and_cleared(client) -> None:
    # Refused unread, above accounts.py's 4096 character cap: a token is 43
    # characters, and anything of this size is somebody probing.
    client.set_cookie(web.SESSION_COOKIE, "a" * 5000)
    assert_refused_and_cleared(client.get("/api/session"))


def test_an_expired_token_is_refused_and_cleared(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from splitwise_lite.accounts import SESSION_LIFETIME

    assert sign_up(client).status_code == 201
    monkeypatch.setattr(web, "_now", lambda: at())
    assert log_in(client).status_code == 200
    monkeypatch.setattr(web, "_now", lambda: at() + SESSION_LIFETIME)
    assert_refused_and_cleared(client.get("/api/session"))


def test_a_logged_out_token_is_refused_and_cleared(client) -> None:
    assert sign_up(client).status_code == 201
    token = set_cookies(log_in(client))[web.SESSION_COOKIE]["value"]
    assert send(client, "DELETE", "/api/session").status_code == 204
    client.set_cookie(web.SESSION_COOKIE, token)
    assert_refused_and_cleared(client.get("/api/session"))


def test_expiry_is_honoured_exactly_at_the_boundary(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import timedelta

    from splitwise_lite.accounts import SESSION_LIFETIME

    assert sign_up(client).status_code == 201
    monkeypatch.setattr(web, "_now", lambda: at())
    assert log_in(client).status_code == 200
    monkeypatch.setattr(
        web, "_now", lambda: at() + SESSION_LIFETIME - timedelta(microseconds=1)
    )
    assert client.get("/api/session").status_code == 200
    monkeypatch.setattr(web, "_now", lambda: at() + SESSION_LIFETIME)
    assert client.get("/api/session").status_code == 401


def test_signing_in_twice_yields_two_live_sessions(app) -> None:
    first = app.test_client()
    assert sign_up(first).status_code == 201
    one = set_cookies(log_in(first))[web.SESSION_COOKIE]["value"]
    second = app.test_client()
    two = set_cookies(log_in(second))[web.SESSION_COOKIE]["value"]
    assert one != two
    assert first.get("/api/session").status_code == 200
    assert second.get("/api/session").status_code == 200


def test_signing_out_deletes_exactly_that_session(app) -> None:
    first = app.test_client()
    assert sign_up(first).status_code == 201
    assert log_in(first).status_code == 200
    second = app.test_client()
    assert log_in(second).status_code == 200
    assert send(first, "DELETE", "/api/session").status_code == 204
    assert first.get("/api/session").status_code == 401
    assert second.get("/api/session").status_code == 200


@pytest.mark.parametrize("state", ["live", "expired", "already_deleted", "absent"])
def test_signing_out_always_succeeds_and_clears_both_cookies(
    app, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    from splitwise_lite.accounts import SESSION_LIFETIME

    client = app.test_client()
    if state != "absent":
        assert sign_up(client).status_code == 201
        monkeypatch.setattr(web, "_now", lambda: at())
        assert log_in(client).status_code == 200
    if state == "expired":
        monkeypatch.setattr(web, "_now", lambda: at() + SESSION_LIFETIME)
    if state == "already_deleted":
        assert send(client, "DELETE", "/api/session").status_code == 204
        client.set_cookie(web.SESSION_COOKIE, "a" * 43)

    response = send(client, "DELETE", "/api/session")
    assert response.status_code == 204
    assert response.data == b""
    written = set_cookies(response)
    assert written[web.SESSION_COOKIE]["max-age"] == "0"
    assert "httponly" in written[web.SESSION_COOKIE]
    assert written[web.SESSION_COOKIE]["samesite"] == "Lax"
    assert written[web.SESSION_COOKIE]["path"] == "/"
    assert written[web.CSRF_COOKIE]["max-age"] == "0"
    assert "httponly" not in written[web.CSRF_COOKIE]
    assert written[web.CSRF_COOKIE]["samesite"] == "Lax"
    assert written[web.CSRF_COOKIE]["path"] == "/"


def test_logging_in_rotates_the_csrf_token(client) -> None:
    before = csrf_token(client)
    assert sign_up(client).status_code == 201
    response = log_in(client)
    assert response.status_code == 200
    after = set_cookies(response)[web.CSRF_COOKIE]["value"]
    assert after != before
    # A request using the pre-login token is refused, and re-reading the cookie is
    # how the client recovers.
    stale = send(client, "DELETE", "/api/session", headers={web.CSRF_HEADER: before})
    assert stale.status_code == 403
    assert send(client, "DELETE", "/api/session").status_code == 204


# --- The rate limiter, on its own -------------------------------------------


def test_the_published_limits_are_exactly_these_numbers() -> None:
    # Asserted so changing one is a visible edit rather than a quiet drift.
    from datetime import timedelta

    assert web.LOGIN_WINDOW == timedelta(minutes=15)
    assert web.LOGIN_LIMIT_PER_EMAIL == 10
    assert web.LOGIN_LIMIT_PER_ADDRESS == 30
    assert web.MAX_BODY_BYTES == 65536


def test_the_limiter_is_guarded_by_a_lock() -> None:
    import threading

    limiter = web.RateLimiter()
    assert isinstance(limiter._lock, type(threading.Lock()))


def test_the_limiter_counts_only_failures_and_refuses_at_the_limit() -> None:
    limiter = web.RateLimiter()
    moment = at()
    for _ in range(web.LOGIN_LIMIT_PER_EMAIL):
        limiter.check("login_email", "sam@example.com", now=moment)
        limiter.record_failure("login_email", "sam@example.com", now=moment)
    with pytest.raises(web.TooManyAttempts):
        limiter.check("login_email", "sam@example.com", now=moment)


def test_the_window_is_fixed_and_expires_by_itself() -> None:
    # Never a lockout: a sticky one, in a product with no password reset flow, locks a
    # flatmate out permanently.
    from datetime import timedelta

    limiter = web.RateLimiter()
    moment = at()
    for _ in range(web.LOGIN_LIMIT_PER_EMAIL):
        limiter.record_failure("login_email", "sam@example.com", now=moment)
    with pytest.raises(web.TooManyAttempts):
        limiter.check("login_email", "sam@example.com", now=moment)
    just_inside = moment + web.LOGIN_WINDOW - timedelta(microseconds=1)
    with pytest.raises(web.TooManyAttempts):
        limiter.check("login_email", "sam@example.com", now=just_inside)
    limiter.check("login_email", "sam@example.com", now=moment + web.LOGIN_WINDOW)
    assert (
        limiter.count("login_email", "sam@example.com", now=moment + web.LOGIN_WINDOW)
        == 0
    )


def test_refusing_reports_whole_seconds_rounded_up() -> None:
    from datetime import timedelta

    limiter = web.RateLimiter()
    moment = at()
    for _ in range(web.LOGIN_LIMIT_PER_EMAIL):
        limiter.record_failure("login_email", "sam@example.com", now=moment)
    with pytest.raises(web.TooManyAttempts) as raised:
        limiter.check(
            "login_email", "sam@example.com", now=moment + timedelta(seconds=1)
        )
    assert raised.value.retry_after == 899
    with pytest.raises(web.TooManyAttempts) as raised:
        limiter.check(
            "login_email",
            "sam@example.com",
            now=moment + timedelta(seconds=1, microseconds=1),
        )
    # Rounded up, because coming back at the instant the window is still closed is
    # not an answer.
    assert raised.value.retry_after == 899


def test_a_success_clears_one_key_and_leaves_the_others() -> None:
    limiter = web.RateLimiter()
    moment = at()
    limiter.record_failure("login_email", "sam@example.com", now=moment)
    limiter.record_failure("login_address", "127.0.0.1", now=moment)
    limiter.clear("login_email", "sam@example.com")
    assert limiter.count("login_email", "sam@example.com", now=moment) == 0
    assert limiter.count("login_address", "127.0.0.1", now=moment) == 1


def test_each_map_is_capped_and_evicts_its_own_oldest_entry() -> None:
    from datetime import timedelta

    limiter = web.RateLimiter()
    moment = at()
    # All inside one window, so nothing is expired and the cap is what does the
    # evicting rather than the clock.
    for index in range(1024):
        limiter.record_failure(
            "login_email",
            f"{index}@example.com",
            now=moment + timedelta(milliseconds=index),
        )
    assert limiter.size("login_email") == 1024
    later = moment + timedelta(milliseconds=1024)
    limiter.record_failure("login_email", "one-too-many@example.com", now=later)
    assert limiter.size("login_email") == 1024
    assert limiter.count("login_email", "one-too-many@example.com", now=later) == 1
    # The oldest window went, and only that one.
    assert limiter.count("login_email", "0@example.com", now=later) == 0
    assert limiter.count("login_email", "1@example.com", now=later) == 1


def test_a_full_map_drops_its_expired_windows_before_it_evicts_a_live_one() -> None:
    from datetime import timedelta

    limiter = web.RateLimiter()
    moment = at()
    for index in range(1024):
        limiter.record_failure(
            "login_email",
            f"{index}@example.com",
            now=moment + timedelta(milliseconds=index),
        )
    # Every window above has fallen out of the fixed window by now, and a dead entry
    # costs nothing to drop, so the cap never has to reach a live one.
    later = moment + web.LOGIN_WINDOW + timedelta(seconds=10)
    limiter.record_failure("login_email", "one-too-many@example.com", now=later)
    assert limiter.size("login_email") == 1
    assert limiter.count("login_email", "one-too-many@example.com", now=later) == 1


def test_the_address_map_is_capped_separately_from_the_email_map() -> None:
    from datetime import timedelta

    # Address churn must not evict the email entry for the address being attacked.
    limiter = web.RateLimiter()
    moment = at()
    limiter.record_failure("login_email", "sam@example.com", now=moment)
    for index in range(4096 + 10):
        limiter.record_failure(
            "login_address",
            f"10.0.{index // 256}.{index % 256}",
            now=moment + timedelta(milliseconds=index),
        )
    assert limiter.size("login_address") == 4096
    assert limiter.size("login_email") == 1
    assert limiter.count("login_email", "sam@example.com", now=moment) == 1


# --- Rate limiting through the API ------------------------------------------


def test_the_tenth_failed_login_runs_and_the_eleventh_is_refused(client) -> None:
    for _ in range(web.LOGIN_LIMIT_PER_EMAIL):
        assert failed_login(client).status_code == 401
    response = failed_login(client)
    assert response.status_code == 429
    assert response.get_json()["error"]["code"] == "too_many_attempts"
    assert response.headers["Retry-After"].isdigit()
    assert 0 < int(response.headers["Retry-After"]) <= 15 * 60


def test_a_refused_login_never_runs_the_key_derivation(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The whole point of the limiter: scrypt costs 64 MiB and hundreds of
    # milliseconds, so an unlimited login endpoint is a denial-of-service amplifier
    # before it is a password oracle.
    for _ in range(web.LOGIN_LIMIT_PER_EMAIL):
        assert failed_login(client).status_code == 401

    def must_not_run(*arguments, **keywords):
        raise AssertionError("the KDF ran on a request the limiter had refused")

    monkeypatch.setattr(web.accounts, "log_in", must_not_run)
    assert failed_login(client).status_code == 429


def test_a_successful_login_clears_that_email_and_leaves_the_address_alone(
    app,
) -> None:
    client = app.test_client()
    assert sign_up(client).status_code == 201
    for _ in range(web.LOGIN_LIMIT_PER_EMAIL - 1):
        assert log_in(client, password=OTHER_PASSWORD).status_code == 401
    assert log_in(client).status_code == 200
    # The email bucket was cleared, so the budget is whole again.
    for _ in range(web.LOGIN_LIMIT_PER_EMAIL):
        assert log_in(client, password=OTHER_PASSWORD).status_code == 401
    assert log_in(client, password=OTHER_PASSWORD).status_code == 429


def test_holding_one_valid_account_does_not_reset_the_address_budget(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = app.test_client()
    exhaust_address_bucket(app)
    assert sign_up(client, email="fresh@example.com").status_code == 201

    def must_not_run(*arguments, **keywords):
        raise AssertionError("the KDF ran on a request the limiter had refused")

    monkeypatch.setattr(web.accounts, "log_in", must_not_run)
    assert log_in(client, email="fresh@example.com").status_code == 429


def test_fifty_correct_logins_in_one_window_are_never_limited(client) -> None:
    assert sign_up(client).status_code == 201
    for _ in range(50):
        assert log_in(client).status_code == 200


def test_the_refusal_says_the_same_thing_for_a_known_and_an_unknown_address(
    app,
) -> None:
    known = app.test_client()
    assert sign_up(known, email="known@example.com").status_code == 201
    for _ in range(web.LOGIN_LIMIT_PER_EMAIL):
        refused = log_in(known, email="known@example.com", password=OTHER_PASSWORD)
        assert refused.status_code == 401
    refused_known = log_in(known, email="known@example.com", password=OTHER_PASSWORD)

    unknown = app.test_client()
    for _ in range(web.LOGIN_LIMIT_PER_EMAIL):
        assert log_in(unknown, email="unknown@example.com").status_code == 401
    refused_unknown = log_in(unknown, email="unknown@example.com")

    assert refused_known.status_code == 429
    assert refused_unknown.status_code == 429
    assert refused_known.data == refused_unknown.data
    assert "known@example.com" not in refused_known.get_data(as_text=True)


def test_signup_has_its_own_address_bucket(app) -> None:
    client = app.test_client()
    exhaust_address_bucket(app)
    assert failed_login(client).status_code == 429
    # The signup bucket is untouched by the login failures.
    assert sign_up(client, email="fresh@example.com").status_code == 201


def test_signup_is_limited_per_address_on_the_same_terms(app) -> None:
    client = app.test_client()
    for index in range(web.LOGIN_LIMIT_PER_ADDRESS):
        # A blank display name is refused by the domain layer, so every one fails.
        refused = sign_up(
            client, email=f"person{index}@example.com", display_name=" "
        )
        assert refused.status_code == 400
    response = sign_up(client, email="one-more@example.com")
    assert response.status_code == 429
    assert response.get_json()["error"]["code"] == "too_many_attempts"


def code_string_constants(source: str) -> set[str]:
    """Every string literal in the module that is not a docstring.

    Read from the tree so a header named in prose, explaining why it is not trusted,
    is not mistaken for code that reads it.
    """
    import ast

    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
        # A bare string statement documents the assignment above it, the way every
        # module in this package documents its constants.
        body = getattr(node, "body", [])
        for statement in body if isinstance(body, list) else []:
            if (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                docstrings.add(id(statement.value))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


def test_the_client_key_is_the_remote_address_and_never_a_header(app) -> None:
    source = web_source()
    literals = code_string_constants(source)
    for header in ("X-Forwarded-For", "X-Real-IP", "Forwarded"):
        assert header not in literals
    assert "ProxyFix" not in source
    assert "remote_addr" in source
    # A second address has a second budget, which is what makes the key the address.
    first = app.test_client()
    for _ in range(web.LOGIN_LIMIT_PER_ADDRESS):
        assert failed_login(first, "nobody@example.com").status_code in (401, 429)
    other = app.test_client()
    response = post(
        other,
        "/api/session",
        {"email": "someone-else@example.com", "password": PASSWORD},
        environ_base={"REMOTE_ADDR": "10.1.2.3"},
    )
    assert response.status_code == 401


def test_the_limiter_needs_no_table_and_no_schema_change() -> None:
    from splitwise_lite import store as store_module

    assert store_module.SCHEMA_VERSION == 2
    schema = store_module._SCHEMA_SQL.lower()
    for word in ("attempt", "rate_limit", "throttle", "login_failure"):
        assert word not in schema


# --- The error contract -----------------------------------------------------


ERROR_ROWS = [
    (web.NotAuthenticated, 401, "not_authenticated"),
    (web.accounts.SessionInvalid, 401, "session_invalid"),
    (web.accounts.AuthenticationFailed, 401, "authentication_failed"),
    (web.CsrfFailed, 403, "csrf_failed"),
    (web.groups.MemberNotLinked, 403, "member_not_linked"),
    (web.store.RecordNotFound, 404, "record_not_found"),
    (web.accounts.EmailAlreadyRegistered, 409, "email_already_registered"),
    (web.store.DuplicateRecord, 409, "duplicate_record"),
    (web.store.ConstraintViolated, 409, "constraint_violated"),
    (web.groups.GroupMismatch, 409, "group_mismatch"),
    (web.groups.MemberAlreadyLinked, 409, "member_already_linked"),
    (web.groups.UserAlreadyLinked, 409, "user_already_linked"),
    (web.SettlementAlreadyPending, 409, "settlement_already_pending"),
    (web.TooManyAttempts, 429, "too_many_attempts"),
    (web.MalformedRequest, 400, "malformed_request"),
    (web.accounts.InvalidEmail, 400, "invalid_email"),
    (web.accounts.InvalidPassword, 400, "invalid_password"),
    (web.money.InvalidAmount, 400, "invalid_amount"),
    (web.money.InvalidCurrency, 400, "invalid_currency"),
    (web.money.CurrencyMismatch, 400, "currency_mismatch"),
    (web.split.InvalidSplit, 400, "invalid_split"),
    (web.store.InvalidRecord, 400, "invalid_record"),
    (web.store.AmountTooLarge, 400, "amount_too_large"),
    (web.groups.NoGroupConfigured, 503, "no_group_configured"),
    (web.groups.AmbiguousGroup, 503, "ambiguous_group"),
    (web.accounts.PasswordHashInvalid, 500, "internal_error"),
]


@pytest.mark.parametrize(
    "error, status, code", ERROR_ROWS, ids=[row[0].__name__ for row in ERROR_ROWS]
)
def test_every_mapped_error_carries_its_status_and_its_code(
    error, status: int, code: str
) -> None:
    assert web.ERROR_STATUS[error] == status
    assert web.ERROR_CODE[error] == code


def test_the_two_tables_are_keyed_the_same_way_and_hold_exactly_these_rows() -> None:
    assert set(web.ERROR_STATUS) == set(web.ERROR_CODE)
    assert set(web.ERROR_STATUS) == {row[0] for row in ERROR_ROWS}


DELIBERATELY_UNMAPPED = {
    # Abstract bases. Every refusal is one of their concrete children, and giving a
    # base a status would give one to something nothing raises.
    "DomainError",
    "AccountError",
    "StoreError",
    "GroupSetupError",
    "WebError",
    # Operational failures. One reaching the request layer means the deployment is
    # broken, not the request, so the fallback 500 with a logged traceback is honest.
    "CannotOpenStore",
    "StoreClosed",
    "StorageFailed",
    "UnsupportedSQLiteVersion",
    "UnsupportedSchemaVersion",
    # Nothing a client body can provoke: every event this layer builds is checked
    # against the roster and the resolver first, so reaching one is a bug here.
    "InvalidEvent",
    "InvalidAllocation",
    "InvalidLedger",
    "InvalidBalances",
    # Raised only while reading an operator's roster file, which no endpoint does.
    "InvalidGroupDefinition",
}


def test_no_domain_error_becomes_a_five_hundred_without_this_test_seeing_it() -> None:
    from splitwise_lite import accounts as accounts_module
    from splitwise_lite import balances as balances_module
    from splitwise_lite import events as events_module
    from splitwise_lite import groups as groups_module
    from splitwise_lite import money as money_module
    from splitwise_lite import simplify as simplify_module
    from splitwise_lite import split as split_module
    from splitwise_lite import store as store_module

    modules = [
        money_module,
        events_module,
        store_module,
        accounts_module,
        groups_module,
        split_module,
        balances_module,
        simplify_module,
        web,
    ]
    exported: set[str] = set()
    for module in modules:
        for name in module.__all__:
            candidate = getattr(module, name)
            if isinstance(candidate, type) and issubclass(
                candidate, money_module.DomainError
            ):
                exported.add(name)
    mapped = {error.__name__ for error in web.ERROR_STATUS}
    assert mapped | DELIBERATELY_UNMAPPED == exported
    assert not mapped & DELIBERATELY_UNMAPPED


def test_a_subclass_of_a_mapped_error_inherits_its_row() -> None:
    class SomethingMoreSpecific(web.store.RecordNotFound):
        """A domain error a later task might add."""

    assert web._status_and_code(SomethingMoreSpecific("gone")) == (
        404,
        "record_not_found",
    )
    assert web._status_and_code(RuntimeError("no idea")) == (500, "internal_error")


@pytest.mark.parametrize(
    "method, path, status",
    [
        ("GET", "/api/nope", 404),
        ("PUT", "/api/session", 405),
        ("GET", "/nothing-here.txt", 404),
    ],
)
def test_every_error_body_is_the_one_json_shape(
    client, method: str, path: str, status: int
) -> None:
    response = client.open(path, method=method)
    assert response.status_code == status
    assert response.headers["Content-Type"] == "application/json"
    body = response.get_json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert isinstance(body["error"]["code"], str)
    assert isinstance(body["error"]["message"], str)


def test_a_method_not_allowed_names_the_methods_that_are(client) -> None:
    response = client.put("/api/session")
    assert response.status_code == 405
    allowed = {part.strip() for part in response.headers["Allow"].split(",")}
    assert {"GET", "POST", "DELETE"} <= allowed
    assert "PUT" not in allowed
    assert response.get_json()["error"]["code"] == "method_not_allowed"


def test_an_unknown_api_path_is_json_and_not_the_shell(client) -> None:
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert b"<!doctype html>" not in response.data
    assert response.get_json()["error"]["code"] == "not_found"


def test_a_body_over_the_cap_is_a_413_in_the_same_shape(client) -> None:
    token = csrf_token(client)
    oversized = b'{"email": "' + b"a" * (web.MAX_BODY_BYTES + 1) + b'"}'
    response = client.post(
        "/api/signup",
        data=oversized,
        content_type="application/json",
        headers={web.CSRF_HEADER: token},
    )
    assert response.status_code == 413
    body = response.get_json()
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == "request_too_large"


def test_a_body_under_the_cap_is_not_refused_for_its_size(app, seeded: Path) -> None:
    signed = linked_client(app, seeded)
    padding = "a" * (web.MAX_BODY_BYTES - 500)
    response = post(
        signed,
        "/api/expenses",
        {
            "description": padding,
            "amount": "12.50",
            "payer_id": "whoever",
            "split": {"mode": "equal", "member_ids": []},
        },
    )
    # Refused on its content, not on its size.
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "malformed_request"


def test_a_five_hundred_hides_the_real_message_and_logs_it(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    import logging

    signed = linked_client(app, seeded)
    telling = "a frame naming C:/somewhere/private and a SELECT of its own"

    def explode(*arguments, **keywords):
        raise RuntimeError(telling)

    monkeypatch.setattr(web.groups, "resolve_sole_group", explode)
    with caplog.at_level(logging.ERROR):
        response = signed.get("/api/session")
    assert response.status_code == 500
    assert response.headers["Content-Type"] == "application/json"
    body = response.get_json()
    assert body["error"]["code"] == "internal_error"
    assert telling not in body["error"]["message"]
    assert body["error"]["message"] == web._GENERIC_500_MESSAGE
    assert telling in caplog.text
    assert "Traceback" in caplog.text


def test_an_unhandled_exception_is_not_werkzeugs_html_page(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)

    def explode(*arguments, **keywords):
        raise ZeroDivisionError("nowhere near a domain error")

    monkeypatch.setattr(web.groups, "resolve_sole_group", explode)
    response = signed.get("/api/session")
    assert response.status_code == 500
    assert b"<!doctype" not in response.data.lower()
    assert b"<html" not in response.data.lower()
    assert response.get_json()["error"]["code"] == "internal_error"


@pytest.mark.parametrize(
    "body, expected",
    [
        (b"not json at all", "not valid JSON"),
        (b"[1, 2, 3]", "must be a JSON object"),
        (b'"a string"', "must be a JSON object"),
        (b"null", "must be a JSON object"),
    ],
)
def test_a_body_that_is_not_a_json_object_is_refused(
    client, body: bytes, expected: str
) -> None:
    token = csrf_token(client)
    response = client.post(
        "/api/signup",
        data=body,
        content_type="application/json",
        headers={web.CSRF_HEADER: token},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "malformed_request"
    assert expected in response.get_json()["error"]["message"]


@pytest.mark.parametrize(
    "payload, named",
    [
        ({"display_name": "Sam", "password": PASSWORD}, "'email'"),
        ({"email": "sam@example.com", "password": PASSWORD}, "'display_name'"),
        ({"email": "sam@example.com", "display_name": "Sam"}, "'password'"),
        ({"email": 12, "display_name": "Sam", "password": PASSWORD}, "'email'"),
        (
            {
                "email": "sam@example.com",
                "display_name": "Sam",
                "password": PASSWORD,
                "role": "admin",
            },
            "'role'",
        ),
    ],
)
def test_a_body_of_the_wrong_shape_names_the_key(client, payload, named: str) -> None:
    response = post(client, "/api/signup", payload)
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    assert named in body["error"]["message"]


@pytest.mark.parametrize("key", ["currency", "created_by", "created_at", "id", "now"])
def test_an_expense_body_may_not_name_what_the_server_decides(
    app, seeded: Path, key: str
) -> None:
    signed = linked_client(app, seeded)
    members = signed.get("/api/members").get_json()["members"]
    payload = {
        "description": "Milk",
        "amount": "12.50",
        "payer_id": members[0]["id"],
        "split": {"mode": "equal", "member_ids": [members[0]["id"]]},
        key: "anything",
    }
    response = post(signed, "/api/expenses", payload)
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    assert repr(key) in body["error"]["message"]


def test_no_message_or_log_record_ever_carries_a_password(app, caplog) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    secret = "a passphrase nobody should ever see again"
    client = app.test_client()
    responses = [
        sign_up(client, email="not an address", password=secret),
        sign_up(client, email="sam@example.com", password="short"),
        post(
            client,
            "/api/signup",
            {
                "email": "sam@example.com",
                "display_name": "Sam",
                "password": secret,
                "confirm_password": secret,
            },
        ),
        post(client, "/api/session", {"email": "sam@example.com", "password": secret}),
    ]
    for response in responses:
        assert response.status_code >= 400
        text = response.get_data(as_text=True)
        assert secret not in text
        assert "scrypt$" not in text
        assert ".sqlite3" not in text
        assert "C:" not in text
    assert secret not in caplog.text


# --- Authentication and the member link -------------------------------------


SIGNUP_BODY = {
    "email": "stranger@example.com",
    "display_name": "Stranger",
    "password": PASSWORD,
}
LOGIN_BODY = {"email": "stranger@example.com", "password": PASSWORD}
EXPENSE_BODY = {
    "description": "Milk",
    "amount": "12.50",
    "payer_id": "whoever",
    "split": {"mode": "equal", "member_ids": []},
}
# The payer is never named here: the endpoint takes it from the acting member, so a
# settlement body is exactly two keys.
SETTLEMENT_BODY = {"to_member_id": "whoever", "amount": "12.50"}

# (method, path, body, the status with no cookies at all, the status with only the
# CSRF gates met). The CSRF token is not a credential, so the second column is the
# unauthenticated case the endpoints are specified against; the first is what a
# request that proves nothing at all gets.
ENDPOINT_ROWS = [
    ("POST", "/api/signup", SIGNUP_BODY, 403, 201),
    ("POST", "/api/session", LOGIN_BODY, 403, 401),
    ("GET", "/api/session", None, 401, 401),
    ("DELETE", "/api/session", None, 403, 204),
    ("GET", "/api/members", None, 401, 401),
    ("GET", "/api/expenses", None, 401, 401),
    ("POST", "/api/expenses", EXPENSE_BODY, 403, 401),
    ("GET", "/api/balances", None, 401, 401),
    ("POST", "/api/settlements", SETTLEMENT_BODY, 403, 401),
    ("GET", "/api/debts/<debtor_id>/<creditor_id>", None, 401, 401),
]


def test_the_endpoint_table_names_every_route_the_app_serves(app) -> None:
    # Adding a route without adding a row fails here.
    listed = {(method, path) for method, path, *_ in ENDPOINT_ROWS}
    served = set()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api"):
            continue
        for method in (rule.methods or set()) - {"HEAD", "OPTIONS"}:
            served.add((method, rule.rule))
    assert listed == served


@pytest.mark.parametrize(
    "method, path, body, bare, gated",
    ENDPOINT_ROWS,
    ids=[f"{row[0]} {row[1]}" for row in ENDPOINT_ROWS],
)
def test_every_endpoint_refuses_an_unauthenticated_caller(
    app, method: str, path: str, body, bare: int, gated: int
) -> None:
    bare_client = app.test_client()
    response = bare_client.open(path, method=method, json={} if body is None else body)
    assert response.status_code == bare, (method, path)

    gated_client = app.test_client()
    assert send(gated_client, method, path, body).status_code == gated, (method, path)


UNLINKED_ROWS = [
    (
        "POST",
        "/api/signup",
        {
            "email": "other@example.com",
            "display_name": "Other",
            "password": PASSWORD,
        },
        201,
    ),
    ("POST", "/api/session", {"email": "sam@example.com", "password": PASSWORD}, 200),
    ("GET", "/api/session", None, 200),
    ("DELETE", "/api/session", None, 204),
    ("GET", "/api/members", None, 403),
    ("GET", "/api/expenses", None, 403),
    ("POST", "/api/expenses", EXPENSE_BODY, 403),
    ("GET", "/api/balances", None, 403),
    ("POST", "/api/settlements", SETTLEMENT_BODY, 403),
    ("GET", "/api/debts/<debtor_id>/<creditor_id>", None, 403),
]


@pytest.mark.parametrize(
    "method, path, body, status",
    UNLINKED_ROWS,
    ids=[f"{row[0]} {row[1]}" for row in UNLINKED_ROWS],
)
def test_a_signed_in_user_with_no_member_row_may_not_read_the_ledger(
    app, method: str, path: str, body, status: int
) -> None:
    # Signup grants nothing at all: no group, no member link, no data. If an unlinked
    # account could read the feed, any stranger who signed up could read the flat's
    # spending.
    client = app.test_client()
    assert sign_up(client).status_code == 201
    assert log_in(client).status_code == 200
    response = send(client, method, path, body)
    assert response.status_code == status, (method, path)
    if status == 403:
        assert response.get_json()["error"]["code"] == "member_not_linked"
    if path == "/api/session" and method == "GET":
        assert response.get_json()["member"] is None


def test_the_member_requirement_is_the_default_and_the_exemptions_are_named() -> None:
    # The exemptions are named per route, in the same row as everything else about
    # that route, so all three partitions are asserted by value rather than as an
    # absence from a literal somewhere else.
    anonymous = {
        endpoint
        for endpoint, access in web._API_ACCESS.items()
        if access is web._Access.ANONYMOUS
    }
    session = {
        endpoint
        for endpoint, access in web._API_ACCESS.items()
        if access is web._Access.SESSION
    }
    member = {
        endpoint
        for endpoint, access in web._API_ACCESS.items()
        if access is web._Access.MEMBER
    }
    assert anonymous == {"signup", "create_session", "delete_session"}
    assert session == {"read_session"}
    assert member == {
        "list_members",
        "list_expenses",
        "create_expense",
        "read_balances",
        "create_settlement",
        "read_debt",
    }
    assert set(web._API_ACCESS) == anonymous | session | member
    assert set(web._API_ACCESS) == {row.endpoint for row in web._API_ROUTES}


def test_authentication_is_checked_before_the_group_is_resolved(empty_app) -> None:
    # An unauthenticated caller must not learn how the server is configured.
    response = empty_app.test_client().get("/api/session")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "not_authenticated"


def test_a_signed_in_user_against_an_unconfigured_store_is_told_to_run_setup(
    empty_app,
) -> None:
    client = empty_app.test_client()
    assert sign_up(client).status_code == 201
    # Signing in writes the session row and then cannot render the view, so the same
    # 503 comes back. The cookie is still set, because the session genuinely exists
    # and a live row the browser was never told about is a leak, not a tidy failure.
    signing_in = log_in(client)
    assert signing_in.status_code == 503
    assert signing_in.get_json()["error"]["code"] == "no_group_configured"
    assert set_cookies(signing_in)[web.SESSION_COOKIE]["max-age"] == "2592000"

    response = client.get("/api/session")
    assert response.status_code == 503
    body = response.get_json()
    assert body["error"]["code"] == "no_group_configured"
    assert "setup_group.py" in body["error"]["message"]


def test_two_groups_are_refused_with_both_ids_named(seeded: Path) -> None:
    from splitwise_lite.events import GroupId, new_id
    from splitwise_lite.store import Group

    with open_store(seeded) as store:
        first = store.list_groups()[0]
        second = Group(GroupId(new_id()), "Flat 4", Currency("AUD"), at(10))
        store.add_group(second)
        ids = sorted([first.id, second.id])

    app = web.create_app(
        store_path=seeded, secure_cookies=False, scrypt_params=CHEAP
    )
    client = app.test_client()
    assert sign_up(client).status_code == 201
    assert log_in(client).status_code == 503
    response = client.get("/api/session")
    assert response.status_code == 503
    body = response.get_json()
    assert body["error"]["code"] == "ambiguous_group"
    for group_id in ids:
        assert group_id in body["error"]["message"]


def probe_view():
    """A view a real task might write, which answers 200 on its own.

    It is deliberately not a view that raises: a test whose probe crashes cannot tell
    a working guard from a broken view, and the point of the guard is that a route
    which *would* have answered is refused instead.
    """
    return web.flask.Response(
        web.json.dumps({"leaked": "roster"}),
        status=200,
        mimetype="application/json",
    )


def test_the_access_levels_are_three_names_that_are_their_own_values() -> None:
    # Following ``SettlementState`` in events.py: the name is the whole of the
    # meaning, so a separate value would be a second thing to keep in step.
    assert [member.name for member in web._Access] == [
        "ANONYMOUS",
        "SESSION",
        "MEMBER",
    ]
    assert all(member.value == member.name for member in web._Access)


def test_a_route_row_cannot_be_written_without_an_access_policy() -> None:
    # The heart of task 51: a row that does not state what it requires is not a row,
    # so "forgot to say" is not a state this table can be in.
    import dataclasses

    with pytest.raises(TypeError):
        web._ApiRoute("/api/x", "x", probe_view, ("GET",))

    declared = dataclasses.fields(web._ApiRoute)
    assert [field.name for field in declared] == [
        "rule",
        "endpoint",
        "view",
        "methods",
        "access",
    ]
    for field in declared:
        assert field.default is dataclasses.MISSING, field.name
        assert field.default_factory is dataclasses.MISSING, field.name
    assert web._ApiRoute.__dataclass_params__.frozen
    assert hasattr(web._ApiRoute, "__slots__")

    row = web._ApiRoute("/api/x", "x", probe_view, ("GET",), web._Access.MEMBER)
    assert (row.rule, row.endpoint, row.view, row.methods, row.access) == (
        "/api/x",
        "x",
        probe_view,
        ("GET",),
        web._Access.MEMBER,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        row.access = web._Access.ANONYMOUS


BAD_ROUTE_ROWS = [
    ((123, "x", probe_view, ("GET",)), TypeError, "rule", "123"),
    (("/nope", "x", probe_view, ("GET",)), ValueError, "rule", "'/nope'"),
    (("/api/x", 5, probe_view, ("GET",)), TypeError, "endpoint", "5"),
    (("/api/x", "", probe_view, ("GET",)), ValueError, "endpoint", "''"),
    (("/api/x", "x", probe_view, ["GET"]), TypeError, "methods", "['GET']"),
    (("/api/x", "x", probe_view, ()), ValueError, "methods", "()"),
    (("/api/x", "x", probe_view, (1,)), TypeError, "methods", "(1,)"),
    (("/api/x", "x", probe_view, ("get",)), ValueError, "methods", "('get',)"),
]


@pytest.mark.parametrize(
    "arguments, raised, named, offending",
    BAD_ROUTE_ROWS,
    ids=[f"{row[2]} {row[3]}" for row in BAD_ROUTE_ROWS],
)
def test_a_route_row_refuses_a_field_it_cannot_use(
    arguments: tuple, raised: type[Exception], named: str, offending: str
) -> None:
    # Eagerly, in ``__post_init__``, in the style ``_Settings`` already uses, and each
    # message names the offending field and the value it got.
    with pytest.raises(raised) as error:
        web._ApiRoute(*arguments, web._Access.MEMBER)
    assert named in str(error.value)
    assert offending in str(error.value)


def test_a_route_row_refuses_an_access_that_is_not_an_access_level() -> None:
    with pytest.raises(TypeError) as error:
        web._ApiRoute("/api/x", "x", probe_view, ("GET",), "MEMBER")
    assert "access" in str(error.value)
    assert "'MEMBER'" in str(error.value)


def test_the_route_tables_hold_exactly_the_routes_the_app_serves(app) -> None:
    # Three rows share the rule ``/api/session`` and differ by endpoint and method:
    # the table is keyed by row, not by path.
    assert [
        (row.rule, row.endpoint, row.methods, row.access) for row in web._API_ROUTES
    ] == [
        ("/api/signup", "signup", ("POST",), web._Access.ANONYMOUS),
        ("/api/session", "create_session", ("POST",), web._Access.ANONYMOUS),
        ("/api/session", "read_session", ("GET",), web._Access.SESSION),
        ("/api/session", "delete_session", ("DELETE",), web._Access.ANONYMOUS),
        ("/api/members", "list_members", ("GET",), web._Access.MEMBER),
        ("/api/expenses", "list_expenses", ("GET",), web._Access.MEMBER),
        ("/api/expenses", "create_expense", ("POST",), web._Access.MEMBER),
        ("/api/balances", "read_balances", ("GET",), web._Access.MEMBER),
        (
            "/api/debts/<debtor_id>/<creditor_id>",
            "read_debt",
            ("GET",),
            web._Access.MEMBER,
        ),
        ("/api/settlements", "create_settlement", ("POST",), web._Access.MEMBER),
    ]
    assert [
        (rule, endpoint, methods)
        for rule, endpoint, _view, methods in web._SHELL_ROUTES
    ] == [
        ("/", "shell_document", ("GET",)),
        ("/<path:filename>", "static_path", ("GET",)),
    ]
    # The view named in the row is the view the app actually calls for that endpoint,
    # so the table describes what is served rather than what somebody meant to serve.
    for row in web._API_ROUTES:
        assert app.view_functions[row.endpoint] is row.view
    for _rule, endpoint, view, _methods in web._SHELL_ROUTES:
        assert app.view_functions[endpoint] is view


def test_every_api_rule_the_app_serves_has_a_declared_access_policy(app) -> None:
    # The issue's third option, kept deliberately: a red test names the failure in
    # the file where the fix is read, and it costs four lines.
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith(web._API_PREFIX):
            assert rule.endpoint in web._API_ACCESS, rule.rule


def test_an_api_route_added_after_the_factory_is_refused_by_the_audit(app) -> None:
    app.add_url_rule("/api/probe", "probe", probe_view, methods=["GET"])
    with pytest.raises(web._RouteNotDeclared) as error:
        web._audit_routes(app)
    message = str(error.value)
    assert "/api/probe" in message
    assert "probe" in message
    assert "_API_ROUTES" in message
    assert "_SHELL_ROUTES" in message
    assert "src/splitwise_lite/web.py" in message
    assert "no session check, no CSRF check and no member check" in message
    for level in ("ANONYMOUS", "SESSION", "MEMBER"):
        assert level in message


def test_a_route_outside_the_api_prefix_is_refused_by_the_audit_too(app) -> None:
    # The audit covers every rule in the map, not only those under ``/api``, so an
    # API route registered at some other prefix cannot slip past it at construction.
    app.add_url_rule("/probe", "probe", probe_view, methods=["GET"])
    with pytest.raises(web._RouteNotDeclared) as error:
        web._audit_routes(app)
    assert "/probe" in str(error.value)


def test_a_declared_route_the_app_does_not_serve_is_refused() -> None:
    # An equality in both directions: a table claiming a route nobody registered is
    # as much a failure as a route no table declares.
    #
    # The withheld row is chosen by endpoint, not by position. It used to be
    # ``_API_ROUTES[:-1]``, which made this test's subject whichever row happened to
    # sit last. Appending a route repointed it at the new endpoint, and the two
    # assertions below then failed on a message naming that endpoint: red about list
    # position, in a test whose subject is route declaration. That is the whole defect,
    # and it handed everyone who adds a route an obligation nothing enforced, to keep
    # the debts row last. Selecting by name retires both. It was never a silent pass,
    # and an earlier version of this comment said it was.
    withheld = "read_debt"
    declared = [row for row in web._API_ROUTES if row.endpoint != withheld]
    assert len(declared) == len(web._API_ROUTES) - 1, withheld
    bare = web.flask.Flask(__name__, static_folder=None)
    for row in declared:
        bare.add_url_rule(row.rule, row.endpoint, row.view, methods=list(row.methods))
    for rule, endpoint, view, methods in web._SHELL_ROUTES:
        bare.add_url_rule(rule, endpoint, view, methods=list(methods))
    with pytest.raises(web._RouteNotDeclared) as error:
        web._audit_routes(bare)
    message = str(error.value)
    assert "/api/debts/<debtor_id>/<creditor_id>" in message
    assert "read_debt" in message
    assert "does not serve" in message


def test_two_rows_sharing_an_endpoint_name_are_refused_by_the_access_map() -> None:
    # The policy is looked up by endpoint, so a duplicate would silently hand one row
    # the other's policy, and the quieter of the two failures is the dangerous one.
    rows = (
        web._ApiRoute("/api/one", "same", probe_view, ("GET",), web._Access.MEMBER),
        web._ApiRoute("/api/two", "same", probe_view, ("GET",), web._Access.SESSION),
    )
    with pytest.raises(ValueError) as error:
        web._access_map(rows)
    assert "same" in str(error.value)


def test_a_route_registered_after_construction_is_refused_at_request_time(
    app, caplog
) -> None:
    # The second line, for the case the audit cannot see. If the ``_before_request``
    # branch is deleted this test fails, because the view would answer 200 with a
    # roster to a caller holding no cookie at all.
    import logging

    assert probe_view().status_code == 200
    app.add_url_rule("/api/probe", "probe", probe_view, methods=["GET"])
    with caplog.at_level(logging.ERROR):
        response = app.test_client().get("/api/probe")
    assert response.status_code == 500
    body = response.get_json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == web._GENERIC_500_MESSAGE
    assert "leaked" not in response.get_data(as_text=True)
    assert "roster" not in response.get_data(as_text=True)
    assert "/api/probe" not in response.get_data(as_text=True)
    assert "Traceback" in caplog.text


def test_an_undeclared_rule_is_classified_by_the_matched_rule_not_the_path(
    app,
) -> None:
    # ``/<path:filename>`` matches ``/api/nope``, so the naive implementation, which
    # tests ``flask.request.path``, turns every unknown ``/api`` path into a 500.
    with app.test_request_context("/api/nope"):
        assert web.flask.request.path.startswith(web._API_PREFIX)
        assert web.flask.request.url_rule is not None
        assert web.flask.request.url_rule.rule == "/<path:filename>"


def test_a_shell_row_under_the_api_prefix_is_refused_at_build_time(
    seeded: Path, monkeypatch
) -> None:
    # The two tables have to be disjoint for the audit to mean what it says.
    # ``_ApiRoute`` refuses a rule outside the prefix; without the converse check a
    # row appended to the ungated table under ``/api`` audits clean, ``create_app``
    # returns an app that serves it, and the failure moves to the one request in the
    # one process that happens to reach ``_before_request``.
    monkeypatch.setattr(
        web,
        "_SHELL_ROUTES",
        web._SHELL_ROUTES + (("/api/dump", "dump", probe_view, ("GET",)),),
    )
    with pytest.raises(web._RouteNotDeclared) as error:
        web.create_app(store_path=seeded, secure_cookies=False, scrypt_params=CHEAP)
    message = str(error.value)
    assert "/api/dump" in message
    assert "_SHELL_ROUTES" in message
    assert "_API_ROUTES" in message
    assert "src/splitwise_lite/web.py" in message
    assert "no session check, no CSRF check and no member check" in message


def test_the_request_time_refusal_claims_no_provenance_it_cannot_see(app) -> None:
    # ``_before_request`` sees a rule carrying no policy and nothing whatever about
    # how it got there. Naming one cause as a fact sends the reader to the wrong
    # file, so the message states what the audit guarantees and leaves open the two
    # possibilities that guarantee allows.
    app.add_url_rule("/api/probe", "probe", probe_view, methods=["GET"])
    with pytest.raises(web._RouteNotDeclared) as error:
        with app.test_request_context("/api/probe"):
            web._before_request()
    message = str(error.value)
    assert "/api/probe" in message
    assert "probe" in message
    assert "_API_ROUTES" in message
    assert "src/splitwise_lite/web.py" in message
    assert "registered after create_app audited this app's route map" not in message
    assert "was not built by create_app" in message
    assert "after that audit ran" in message


def test_the_api_prefix_is_a_path_segment_and_not_a_string_prefix(
    app, seeded: Path, monkeypatch
) -> None:
    # ``/apiary`` is not under ``/api``. All three guards ask this one question, so
    # they agree with each other by construction; without the segment boundary they
    # would agree on a boundary one character wide instead.
    web._ApiRoute(web._API_PREFIX, "bare", probe_view, ("GET",), web._Access.MEMBER)
    web._ApiRoute("/api/x", "x", probe_view, ("GET",), web._Access.MEMBER)
    with pytest.raises(ValueError) as error:
        web._ApiRoute("/apiary", "apiary", probe_view, ("GET",), web._Access.MEMBER)
    assert "rule" in str(error.value)
    assert "'/apiary'" in str(error.value)

    # At request time the same boundary. A rule outside the prefix is not an API rule
    # and is not refused as one, so this lands in the gap the spec already records
    # for a route registered after the factory returned, rather than a second one.
    app.add_url_rule("/apiary", "apiary", probe_view, methods=["GET"])
    assert app.test_client().get("/apiary").status_code == 200

    # And the audit's converse check reads it the same way: a shell row at
    # ``/apiary`` is an ordinary ungated shell route, not a misfiled API one.
    monkeypatch.setattr(
        web,
        "_SHELL_ROUTES",
        web._SHELL_ROUTES + (("/apiary", "apiary", probe_view, ("GET",)),),
    )
    built = web.create_app(
        store_path=seeded, secure_cookies=False, scrypt_params=CHEAP
    )
    assert built.test_client().get("/apiary").status_code == 200


def test_a_route_outside_the_prefix_added_after_the_factory_is_still_ungated(
    app,
) -> None:
    # The gap the spec records at "What this deliberately does not catch", pinned
    # rather than left to be rediscovered. ``_before_request`` can only classify by
    # the rule it matched, and this one is not under ``/api``, so it is served. The
    # audit still refuses it at construction, so reaching this needs somebody to
    # register a route outside the factory *and* outside the prefix. If that ever
    # stops being true, in either direction, this test says so.
    app.add_url_rule("/probe", "probe", probe_view, methods=["GET"])
    response = app.test_client().get("/probe")
    assert response.status_code == 200
    assert response.get_json() == {"leaked": "roster"}


def test_an_undeclared_rule_is_refused_before_the_csrf_gate_runs(app, caplog) -> None:
    # Criterion 21's order, driven on a state-changing method: the rule with no
    # declared policy is refused before any gate runs, so a POST carrying no CSRF
    # header is the 500 and not a 403 ``csrf_failed``. Nothing else would notice
    # those two branches being swapped.
    import logging

    app.add_url_rule("/api/probe", "probe", probe_view, methods=["POST"])
    with caplog.at_level(logging.ERROR):
        response = app.test_client().post("/api/probe")
    assert response.status_code == 500
    body = response.get_json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == web._GENERIC_500_MESSAGE
    assert "leaked" not in response.get_data(as_text=True)
    assert "Traceback" in caplog.text


def test_nothing_in_the_module_ever_writes_to_the_access_map() -> None:
    # Criterion 8 says nothing writes to ``_API_ACCESS`` after import, and a plain
    # dict does not enforce that. ``MappingProxyType`` would, but it needs ``types``,
    # and ``test_the_module_imports_flask_and_the_standard_library_only`` pins that
    # import set exactly, so enforcement lives here instead: a rebinding, a
    # subscripted assignment, a deletion or a mutating method call on the name is a
    # failure, and the name is bound exactly once.
    import ast

    writes: list[str] = []
    bindings = 0
    for node in ast.walk(ast.parse(web_source())):
        targets: list[ast.expr] = []
        if isinstance(node, (ast.Assign, ast.Delete)):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "_API_ACCESS":
                if isinstance(node, ast.AnnAssign):
                    bindings += 1
                else:
                    writes.append(ast.dump(node))
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "_API_ACCESS"
            ):
                writes.append(ast.dump(node))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "_API_ACCESS"
            and node.func.attr not in {"get", "items", "keys", "values", "copy"}
        ):
            writes.append(ast.dump(node))
    assert writes == []
    assert bindings == 1


def test_a_declared_shell_route_the_app_does_not_serve_is_refused() -> None:
    # Criterion 15 from the other table. A missing shell row goes down the same code
    # path as a missing API one, and the path is only worth having if both directions
    # are known to reach it.
    bare = web.flask.Flask(__name__, static_folder=None)
    for row in web._API_ROUTES:
        bare.add_url_rule(row.rule, row.endpoint, row.view, methods=list(row.methods))
    for rule, endpoint, view, methods in web._SHELL_ROUTES[:-1]:
        bare.add_url_rule(rule, endpoint, view, methods=list(methods))
    with pytest.raises(web._RouteNotDeclared) as error:
        web._audit_routes(bare)
    message = str(error.value)
    assert "/<path:filename>" in message
    assert "static_path" in message
    assert "does not serve" in message


# --- Members ----------------------------------------------------------------


def roster(client) -> list[dict]:
    """The roster as the API reports it, which is the only source of member ids."""
    body = client.get("/api/members").get_json()
    return body["members"]


def by_name(client) -> dict[str, str]:
    return {member["display_name"]: member["id"] for member in roster(client)}


def test_the_roster_is_the_group_in_store_order_with_two_keys_each(
    app, seeded: Path
) -> None:
    signed = linked_client(app, seeded)
    response = signed.get("/api/members")
    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"members"}
    assert [member["display_name"] for member in body["members"]] == list(ROSTER)
    for member in body["members"]:
        assert set(member) == {"id", "display_name"}

    with open_store(seeded) as store:
        from splitwise_lite.groups import resolve_sole_group

        group = resolve_sole_group(store)
        stored = [member.id for member in store.list_members(group.id)]
    assert [member["id"] for member in body["members"]] == stored


def test_the_roster_carries_no_account_information(app, seeded: Path) -> None:
    # Task 9 decided an unlinked member is a full member that nothing filters, greys
    # out or marks pending, and a screenshot of the roster is not an account list.
    signed = linked_client(app, seeded)
    text = signed.get("/api/members").get_data(as_text=True)
    for forbidden in ("user_id", "email", "linked", "example.com"):
        assert forbidden not in text


# --- Expenses ---------------------------------------------------------------


def add_expense(
    client,
    *,
    payer_id: str,
    amount: str,
    split: dict,
    description: str = "Milk",
):
    return post(
        client,
        "/api/expenses",
        {
            "description": description,
            "amount": amount,
            "payer_id": payer_id,
            "split": split,
        },
    )


def equal_split(*member_ids: str) -> dict:
    return {"mode": "equal", "member_ids": list(member_ids)}


def expense_count(path: Path) -> int:
    from splitwise_lite.groups import resolve_sole_group

    with open_store(path) as store:
        return len(store.list_expenses(resolve_sole_group(store).id))


def test_a_group_with_no_expenses_is_an_empty_list_and_not_a_404(
    app, seeded: Path
) -> None:
    signed = linked_client(app, seeded)
    response = signed.get("/api/expenses")
    assert response.status_code == 200
    assert response.get_json() == {"currency": CURRENCY, "expenses": []}


def test_the_feed_is_newest_first_with_ties_broken_by_id_descending(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    everyone = equal_split(*sorted(members.values()))

    monkeypatch.setattr(web, "_now", lambda: at(9))
    first = add_expense(
        signed, payer_id=members["Sam"], amount="30.00", split=everyone
    ).get_json()["expense"]["id"]
    second = add_expense(
        signed, payer_id=members["Ali"], amount="15.00", split=everyone
    ).get_json()["expense"]["id"]
    monkeypatch.setattr(web, "_now", lambda: at(10))
    third = add_expense(
        signed, payer_id=members["Jo"], amount="9.00", split=everyone
    ).get_json()["expense"]["id"]

    listed = [entry["id"] for entry in signed.get("/api/expenses").get_json()["expenses"]]
    assert listed == [third] + sorted([first, second], reverse=True)


def test_a_feed_entry_carries_its_allocations_and_no_display_names(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    add_expense(
        signed,
        payer_id=members["Sam"],
        amount="30.00",
        split=equal_split(*sorted(members.values())),
    )
    entry = signed.get("/api/expenses").get_json()["expenses"][0]
    assert set(entry) == {
        "id",
        "description",
        "amount",
        "payer_id",
        "created_by",
        "created_at",
        "allocations",
        }
    assert entry["amount"] == "30.00"
    assert entry["payer_id"] == members["Sam"]
    assert entry["created_by"] == members["Sam"]
    assert entry["created_at"] == "2026-09-05T09:00:00.000000+00:00"
    assert len(entry["created_at"]) == 32
    assert entry["allocations"] == [
        {"member_id": member_id, "amount": "10.00"}
        for member_id in sorted(members.values())
    ]
    for allocation in entry["allocations"]:
        assert set(allocation) == {"member_id", "amount"}
    assert "display_name" not in signed.get("/api/expenses").get_data(as_text=True)


def test_an_empty_description_round_trips_as_an_empty_string(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Task 2 made the description optional so that entry can happen in under ten
    # seconds. The feed renders the fixed literal "No description" for one of these,
    # which needs the key present and its value the empty string: null or an absent
    # key would be a different shape and a different screen.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    created = add_expense(
        signed,
        payer_id=members["Sam"],
        amount="12.50",
        split=equal_split(*sorted(members.values())),
        description="",
    )
    assert created.status_code == 201
    entry = signed.get("/api/expenses").get_json()["expenses"][0]
    assert "description" in entry
    assert entry["description"] == ""
    assert entry["description"] is not None


def test_a_payer_who_is_not_a_participant_stays_out_of_the_allocations(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Task 4 supports paying for a meal you did not eat. The feed lists only the
    # allocation members on its "Split across" line and says so in the detail, which
    # only works if the payer really is absent from allocations.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    sharing = sorted([members["Ali"], members["Jo"]])
    monkeypatch.setattr(web, "_now", lambda: at(9))
    add_expense(
        signed,
        payer_id=members["Sam"],
        amount="20.00",
        split=equal_split(*sharing),
    )
    entry = signed.get("/api/expenses").get_json()["expenses"][0]
    assert entry["payer_id"] == members["Sam"]
    assert entry["allocations"] == [
        {"member_id": sharing[0], "amount": "10.00"},
        {"member_id": sharing[1], "amount": "10.00"},
    ]


def test_two_cents_across_three_members_keeps_the_zero_share_in_the_array(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Task 3's remainder rule gives 1, 1, 0, and a zero share is a real participant
    # rather than a member to drop. The feed counts them into "and N others" and
    # shows their 0.00 in the detail, so the array must carry all three.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    ordered = sorted(members.values())
    monkeypatch.setattr(web, "_now", lambda: at(9))
    add_expense(
        signed, payer_id=members["Sam"], amount="0.02", split=equal_split(*ordered)
    )
    entry = signed.get("/api/expenses").get_json()["expenses"][0]
    assert entry["amount"] == "0.02"
    assert entry["allocations"] == [
        {"member_id": ordered[0], "amount": "0.01"},
        {"member_id": ordered[1], "amount": "0.01"},
        {"member_id": ordered[2], "amount": "0.00"},
    ]


def test_an_expense_split_across_one_member_has_one_allocation_of_the_total(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The single share equals the total, and the feed renders both without adding
    # anything up. Nothing about the payload marks this case as special.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    add_expense(
        signed,
        payer_id=members["Sam"],
        amount="7.35",
        split=equal_split(members["Sam"]),
    )
    entry = signed.get("/api/expenses").get_json()["expenses"][0]
    assert entry["amount"] == "7.35"
    assert entry["allocations"] == [{"member_id": members["Sam"], "amount": "7.35"}]


def test_an_equal_split_stores_the_event_field_by_field(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from splitwise_lite.events import Allocation
    from splitwise_lite.groups import resolve_sole_group
    from splitwise_lite.money import Currency as CurrencyType

    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    response = add_expense(
        signed,
        payer_id=members["Ali"],
        amount="10.00",
        split=equal_split(members["Sam"], members["Ali"], members["Jo"]),
        description="  Milk  ",
    )
    assert response.status_code == 201
    created = response.get_json()["expense"]

    with open_store(seeded) as store:
        group = resolve_sole_group(store)
        stored = store.list_expenses(group.id)
    assert len(stored) == 1
    expense = stored[0]
    assert expense.id == created["id"]
    assert expense.group_id == group.id
    assert expense.currency == CurrencyType(CURRENCY)
    assert expense.payer_id == members["Ali"]
    assert expense.total_cents == 1000
    assert expense.description == "Milk"
    assert expense.created_at == at(9)
    # The acting member, never a name in the body.
    assert expense.created_by == members["Sam"]
    # 1000 cents across three people is 333, 333, 334. Which member absorbs the
    # extra cent is the resolver's rotation, not this layer's: at a base share of
    # 333 the walk starts at index (1000 // 3) % 3 == 0, so it is the member who
    # sorts first by id. Asserted exactly, never approximately.
    ordered = sorted(members.values())
    assert expense.allocations == (
        Allocation(ordered[0], 334),
        Allocation(ordered[1], 333),
        Allocation(ordered[2], 333),
    )
    assert sum(allocation.cents for allocation in expense.allocations) == 1000


def test_a_weighted_split_stores_the_event_field_by_field(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from splitwise_lite.groups import resolve_sole_group

    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    response = add_expense(
        signed,
        payer_id=members["Sam"],
        amount="10.00",
        split={
            "mode": "weight",
            "weights": {members["Sam"]: 1, members["Ali"]: 4},
        },
    )
    assert response.status_code == 201

    with open_store(seeded) as store:
        expense = store.list_expenses(resolve_sole_group(store).id)[0]
    assert expense.total_cents == 1000
    assert expense.created_at == at(9)
    shares = {
        allocation.member_id: allocation.cents for allocation in expense.allocations
    }
    assert shares == {members["Sam"]: 200, members["Ali"]: 800}


def test_an_exact_split_parses_its_amounts_from_strings(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from splitwise_lite.groups import resolve_sole_group

    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    response = add_expense(
        signed,
        payer_id=members["Jo"],
        amount="10.00",
        split={
            "mode": "exact",
            "amounts": {members["Sam"]: "8.00", members["Jo"]: "2.00"},
        },
    )
    assert response.status_code == 201

    with open_store(seeded) as store:
        expense = store.list_expenses(resolve_sole_group(store).id)[0]
    shares = {
        allocation.member_id: allocation.cents for allocation in expense.allocations
    }
    assert shares == {members["Sam"]: 800, members["Jo"]: 200}
    assert expense.total_cents == 1000


def test_the_created_expense_comes_back_in_the_same_shape_as_a_feed_entry(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    created = add_expense(
        signed,
        payer_id=members["Sam"],
        amount="30.00",
        split=equal_split(*sorted(members.values())),
    ).get_json()["expense"]
    listed = signed.get("/api/expenses").get_json()["expenses"][0]
    assert created == listed


@pytest.mark.parametrize("amount", [12.50, 1250, 0, True])
def test_an_amount_that_is_a_json_number_is_refused(
    app, seeded: Path, amount
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed,
        payer_id=members["Sam"],
        amount=amount,
        split=equal_split(members["Sam"]),
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    assert "amounts are strings" in body["error"]["message"]
    assert expense_count(seeded) == 0


@pytest.mark.parametrize(
    "amount, code, fragment",
    [
        ("0.00", "invalid_split", "more than zero"),
        ("-5.00", "invalid_amount", "not a valid amount"),
        ("12.505", "invalid_amount", "fractional digits"),
        ("92233720368547758.08", "invalid_amount", "too large to store"),
    ],
)
def test_an_unusable_amount_carries_the_domain_layers_own_message(
    app, seeded: Path, amount: str, code: str, fragment: str
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed,
        payer_id=members["Sam"],
        amount=amount,
        split=equal_split(members["Sam"]),
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == code
    assert fragment in body["error"]["message"]
    assert expense_count(seeded) == 0


def test_a_payer_who_is_not_a_member_is_refused_by_name(app, seeded: Path) -> None:
    # Decided from the roster before any write, so no foreign key violation is
    # ever reached.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed,
        payer_id="a-stranger",
        amount="10.00",
        split=equal_split(members["Sam"]),
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    assert "'a-stranger'" in body["error"]["message"]
    assert expense_count(seeded) == 0


@pytest.mark.parametrize("mode", ["equal", "weight", "exact"])
def test_a_split_naming_someone_outside_the_group_is_refused_by_name(
    app, seeded: Path, mode: str
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    splits = {
        "equal": {"mode": "equal", "member_ids": [members["Sam"], "a-stranger"]},
        "weight": {"mode": "weight", "weights": {members["Sam"]: 1, "a-stranger": 1}},
        "exact": {
            "mode": "exact",
            "amounts": {members["Sam"]: "5.00", "a-stranger": "5.00"},
        },
    }
    response = add_expense(
        signed, payer_id=members["Sam"], amount="10.00", split=splits[mode]
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    assert "'a-stranger'" in body["error"]["message"]
    assert expense_count(seeded) == 0


def test_a_split_naming_a_member_twice_is_refused_by_the_resolver(
    app, seeded: Path
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed,
        payer_id=members["Sam"],
        amount="10.00",
        split=equal_split(members["Sam"], members["Sam"]),
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "invalid_split"
    assert "more than once" in body["error"]["message"]
    assert expense_count(seeded) == 0


@pytest.mark.parametrize(
    "split, fragment",
    [
        ({"mode": "equal", "member_ids": []}, "at least one member"),
        ({"mode": "weight", "weights": {}}, "at least one member"),
        ({"mode": "exact", "amounts": {}}, "at least one member"),
    ],
)
def test_an_empty_split_is_refused_by_the_resolver(
    app, seeded: Path, split: dict, fragment: str
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed, payer_id=members["Sam"], amount="10.00", split=split
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "invalid_split"
    assert fragment in body["error"]["message"]
    assert expense_count(seeded) == 0


def test_weights_summing_to_zero_are_refused_by_the_resolver(
    app, seeded: Path
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed,
        payer_id=members["Sam"],
        amount="10.00",
        split={"mode": "weight", "weights": {members["Sam"]: 0, members["Ali"]: 0}},
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "invalid_split"
    assert "sum to zero" in body["error"]["message"]
    assert expense_count(seeded) == 0


def group_money(cents: int) -> str:
    """The seeded group's own currency rendered through the one display edge.

    Every expected figure in the refusal tests below is built by calling this rather
    than typed as a literal, so they assert that a message spells its figures the way
    ``format_amount`` spells them, not that it matches a rendering frozen on the day
    they were written.
    """
    from splitwise_lite import money

    return money.format_amount(money.Money(cents, Currency(CURRENCY)))


def test_exact_amounts_that_do_not_add_up_report_both_figures(
    app, seeded: Path
) -> None:
    # The resolver's own message carries what the shares came to and what the total
    # was, which is what lets an entry screen say by how much the user is out. Both
    # figures are in the money the user typed: the screen prints this sentence word
    # for word, and 950 is not something anybody typed.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed,
        payer_id=members["Sam"],
        amount="10.00",
        split={
            "mode": "exact",
            "amounts": {members["Sam"]: "8.00", members["Ali"]: "1.50"},
        },
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "invalid_split"
    message = body["error"]["message"]
    assert message == (
        f"the shares add up to {group_money(950)}, "
        f"but the total is {group_money(1000)}"
    )
    # The raw cent spellings cannot occur inside 9.50 and 10.00, which is why these
    # are the figures to test the defect's absence with.
    assert "950" not in message
    assert "1000" not in message
    assert expense_count(seeded) == 0


def test_a_zero_amount_is_refused_in_the_money_and_not_in_a_parameter_name(
    app, seeded: Path
) -> None:
    # The other refusal the add screen can provoke out of the resolver. "Amount" is
    # the label on the field; "total_cents" is a parameter in split.py.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed,
        payer_id=members["Sam"],
        amount="0.00",
        split=equal_split(members["Sam"], members["Ali"]),
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "invalid_split"
    message = body["error"]["message"]
    assert group_money(0) in message
    assert "total_cents" not in message
    assert "cents" not in message
    assert expense_count(seeded) == 0


def test_the_shell_harness_refusal_fixture_is_the_sentence_the_api_sends(
    app, seeded: Path
) -> None:
    """The JavaScript half's fixture cannot drift from the Python half's sentence.

    ``tests/shell_harness.mjs`` shows ``ADD_SUM_REFUSED`` to a person through the
    shipped ``app/api.js`` and ``app/app.js``, and asserts it lands in
    ``#add-error-server`` character for character. Nothing over there knows whether
    the server still says it. This reads the literal out of the fixture and compares
    it against a live 400 with the harness scenario's own figures, so a reword of
    ``split.py``'s refusal goes red here pointing at the fixture that has gone stale.
    """
    import re

    source = (REPO / "tests" / "shell_harness.mjs").read_text(encoding="utf-8")
    declared = re.search(
        r"^const ADD_SUM_REFUSED = '([^']*)';$", source, re.MULTILINE
    )
    assert declared is not None, "shell_harness.mjs declares no ADD_SUM_REFUSED"

    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed,
        payer_id=members["Sam"],
        amount="10.00",
        split={
            "mode": "exact",
            "amounts": {members["Sam"]: "8.00", members["Ali"]: "1.50"},
        },
    )
    assert response.status_code == 400
    assert declared.group(1) == response.get_json()["error"]["message"]


def test_the_shell_harness_zero_amount_fixture_is_the_sentence_the_api_sends(
    app, seeded: Path
) -> None:
    """The harness's other refusal fixture, held to the standard criterion 19 set.

    ``ADD_ZERO_REFUSED`` is both the body the harness's stubbed ``fetch`` hands back
    and the value its scenario expects in ``#add-error-server``, so the JavaScript
    half is self-consistent by construction: set it to nonsense and the scenario
    still passes. Rendering the sentence proves the shell shows what it is given; it
    cannot prove the server still gives it. This reads the literal out of the fixture
    and compares it against a live 400 with the characters that scenario types, so a
    reword of ``_require_total``'s refusal reds here rather than going unnoticed.
    """
    import re

    source = (REPO / "tests" / "shell_harness.mjs").read_text(encoding="utf-8")
    declared = re.search(
        r"^const ADD_ZERO_REFUSED = '([^']*)';$", source, re.MULTILINE
    )
    assert declared is not None, "shell_harness.mjs declares no ADD_ZERO_REFUSED"

    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed,
        payer_id=members["Sam"],
        # "0" and not "0.00": the screen sends the field's characters untouched, so
        # the fixture and the live request have to agree about that as well.
        amount="0",
        split=equal_split(members["Sam"], members["Ali"]),
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_split"
    assert declared.group(1) == response.get_json()["error"]["message"]
    assert expense_count(seeded) == 0


@pytest.mark.parametrize("mode", ["percentage", "", "EQUAL", 7])
def test_an_unknown_split_mode_names_the_three_that_exist(
    app, seeded: Path, mode
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed,
        payer_id=members["Sam"],
        amount="10.00",
        split={"mode": mode},
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    if isinstance(mode, str):
        for named in ("'equal'", "'weight'", "'exact'"):
            assert named in body["error"]["message"]
    assert expense_count(seeded) == 0


@pytest.mark.parametrize(
    "split",
    [
        {"mode": "equal"},
        {"mode": "equal", "member_ids": "not-a-list"},
        {"mode": "weight", "weights": "not-an-object"},
        {"mode": "weight", "weights": {"whoever": "two"}},
        {"mode": "exact", "amounts": {"whoever": 8.0}},
        {"mode": "equal", "member_ids": [], "extra": 1},
        {},
    ],
)
def test_a_split_of_the_wrong_shape_is_refused(app, seeded: Path, split) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = add_expense(
        signed, payer_id=members["Sam"], amount="10.00", split=split
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "malformed_request"
    assert expense_count(seeded) == 0


def test_the_currency_is_the_groups_and_cannot_be_named(app, seeded: Path) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    assert (
        add_expense(
            signed,
            payer_id=members["Sam"],
            amount="10.00",
            split=equal_split(members["Sam"]),
        ).status_code
        == 201
    )
    assert signed.get("/api/expenses").get_json()["currency"] == CURRENCY


# --- Balances ---------------------------------------------------------------


def seed_three_expenses(client, members: dict[str, str], monkeypatch) -> None:
    """Sam pays 30 for all three, Ali pays 15 for all three, Jo pays 9 for two.

    Every division is exact, so the figures below are arithmetic rather than a
    remainder rule: Sam ends up owed 10.50, Jo owes 10.50 and Ali is square.
    """
    everyone = equal_split(*sorted(members.values()))
    monkeypatch.setattr(web, "_now", lambda: at(9))
    assert (
        add_expense(
            client, payer_id=members["Sam"], amount="30.00", split=everyone
        ).status_code
        == 201
    )
    monkeypatch.setattr(web, "_now", lambda: at(10))
    assert (
        add_expense(
            client, payer_id=members["Ali"], amount="15.00", split=everyone
        ).status_code
        == 201
    )
    monkeypatch.setattr(web, "_now", lambda: at(11))
    assert (
        add_expense(
            client,
            payer_id=members["Jo"],
            amount="9.00",
            split=equal_split(members["Sam"], members["Jo"]),
        ).status_code
        == 201
    )


def test_a_settled_group_is_every_member_at_zero_and_no_transfers(
    app, seeded: Path
) -> None:
    signed = linked_client(app, seeded)
    members = roster(signed)
    response = signed.get("/api/balances")
    assert response.status_code == 200
    assert response.get_json() == {
        "currency": CURRENCY,
        "net": [
            {"member_id": member["id"], "amount": "0.00", "direction": "settled"}
            for member in members
        ],
        "transfers": [],
        # Task 14. Nobody has claimed a payment, so nothing is awaiting anybody.
        "pending": [],
    }


def test_balances_report_the_exact_figures_and_the_exact_transfer_list(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)

    body = signed.get("/api/balances").get_json()
    assert body["currency"] == CURRENCY
    # Roster order, which is the order GET /api/members reports.
    assert body["net"] == [
        {"member_id": members["Sam"], "amount": "10.50", "direction": "owed"},
        {"member_id": members["Ali"], "amount": "0.00", "direction": "settled"},
        {"member_id": members["Jo"], "amount": "10.50", "direction": "owes"},
    ]
    # Both provenance arrays keep simplify.py's order, ascending by
    # (debtor, creditor), and member ids are UUIDs, so the expectation is written out
    # in full and ordered by that same documented rule rather than loosened.
    def by_pair(rows: list[dict]) -> list[dict]:
        return sorted(rows, key=lambda row: (row["debtor_id"], row["creditor_id"]))

    jo_owes_sam = {
        "debtor_id": members["Jo"],
        "creditor_id": members["Sam"],
        "amount": "5.50",
        "debt_total": "5.50",
        "covers_whole_debt": True,
    }
    assert body["transfers"] == [
        {
            "from_member_id": members["Jo"],
            "to_member_id": members["Sam"],
            "amount": "10.50",
            "payer_debts": by_pair(
                [
                    jo_owes_sam,
                    {
                        "debtor_id": members["Jo"],
                        "creditor_id": members["Ali"],
                        "amount": "5.00",
                        "debt_total": "5.00",
                        "covers_whole_debt": True,
                    },
                ]
            ),
            "receiver_credits": by_pair(
                [
                    jo_owes_sam,
                    {
                        "debtor_id": members["Ali"],
                        "creditor_id": members["Sam"],
                        "amount": "5.00",
                        "debt_total": "5.00",
                        "covers_whole_debt": True,
                    },
                ]
            ),
            # Task 14. Nobody has marked this payment as paid.
            "awaiting_confirmation": False,
        }
    ]


def test_a_member_the_ledger_has_never_seen_is_settled_at_zero(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``Balances.net_for`` is total by design, so a member in no expense at all is
    # square with the group rather than missing from the payload.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    assert (
        add_expense(
            signed,
            payer_id=members["Sam"],
            amount="10.00",
            split=equal_split(members["Sam"], members["Ali"]),
        ).status_code
        == 201
    )
    body = signed.get("/api/balances").get_json()
    entries = {entry["member_id"]: entry for entry in body["net"]}
    assert entries[members["Jo"]] == {
        "member_id": members["Jo"],
        "amount": "0.00",
        "direction": "settled",
    }
    assert len(body["net"]) == len(ROSTER)


def test_a_transfer_carries_both_ends_of_its_provenance(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Task 12a. Task 5 built two-ended provenance and called it the deliverable; this
    # is where it reaches the browser. ``covers_whole_debt`` is the server's answer,
    # computed from cents, for the same reason ``direction`` exists on a net row: the
    # screen must never compare two amount strings.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    body = signed.get("/api/balances").get_json()
    assert len(body["transfers"]) == 1
    for transfer in body["transfers"]:
        assert set(transfer) == {
            "from_member_id",
            "to_member_id",
            "amount",
            "payer_debts",
            "receiver_credits",
            # Task 14, computed on the server from ids, so the screen compares no
            # amounts to decide whether a payment is already claimed.
            "awaiting_confirmation",
        }
        # Task 5 guarantees both lists are non-empty for a strictly positive
        # transfer, so this server never sends the empty ones task 13 falls back on.
        assert transfer["payer_debts"] != []
        assert transfer["receiver_credits"] != []
        for row in transfer["payer_debts"] + transfer["receiver_credits"]:
            assert set(row) == {
                "debtor_id",
                "creditor_id",
                "amount",
                "debt_total",
                "covers_whole_debt",
            }
            assert isinstance(row["covers_whole_debt"], bool)
            assert not row["amount"].startswith("-")
            assert not row["debt_total"].startswith("-")
        assert {row["debtor_id"] for row in transfer["payer_debts"]} == {
            transfer["from_member_id"]
        }
        assert {row["creditor_id"] for row in transfer["receiver_credits"]} == {
            transfer["to_member_id"]
        }
        for rows in (transfer["payer_debts"], transfer["receiver_credits"]):
            assert rows == sorted(
                rows, key=lambda row: (row["debtor_id"], row["creditor_id"])
            )
    text = signed.get("/api/balances").get_data(as_text=True)
    for forbidden in ("pair", "absorbed", "cents"):
        assert forbidden not in text


def test_every_direction_is_one_of_the_three_and_the_amount_is_never_negative(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``direction`` carries the sign, so ``amount`` is always the non-negative
    # magnitude and no client ever has to parse or render a minus sign.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    body = signed.get("/api/balances").get_json()
    assert {entry["direction"] for entry in body["net"]} == {
        "owed",
        "owes",
        "settled",
    }
    for entry in body["net"]:
        assert not entry["amount"].startswith("-")


# --- Money on the wire ------------------------------------------------------


AMOUNT_KEYS = ("amount", "debt_total")
"""Every key an amount lives at on the wire. ``debt_total`` joined ``amount`` with
task 12a's transfer provenance, so both are held to the two-decimal string rule."""


def every_amount_key(payload) -> list:
    """Every value under a key an amount lives at, anywhere in a payload."""
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in AMOUNT_KEYS:
                found.append(value)
            found.extend(every_amount_key(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(every_amount_key(item))
    return found


def test_no_amount_is_ever_a_json_number_and_no_payload_names_cents(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    paths = [
        "/api/session",
        "/api/members",
        "/api/expenses",
        "/api/balances",
        f"/api/debts/{members['Jo']}/{members['Sam']}",
    ]
    for path in paths:
        response = signed.get(path)
        assert response.status_code == 200
        payload = response.get_json()
        for amount in every_amount_key(payload):
            assert isinstance(amount, str), (path, amount)
            # Exactly what format_amount produces: two decimal places, never a float.
            assert amount.count(".") == 1
            assert len(amount.partition(".")[2]) == 2
        assert "cents" not in response.get_data(as_text=True), path


def test_an_amount_is_rendered_the_way_format_amount_renders_it(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from splitwise_lite.money import Currency as CurrencyType
    from splitwise_lite.money import Money, format_amount

    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    assert (
        add_expense(
            signed,
            payer_id=members["Sam"],
            amount="1,234.50",
            split=equal_split(members["Sam"]),
        ).status_code
        == 201
    )
    entry = signed.get("/api/expenses").get_json()["expenses"][0]
    assert entry["amount"] == format_amount(Money(123450, CurrencyType(CURRENCY)))
    assert entry["amount"] == "1,234.50"


# --- Signing up -------------------------------------------------------------


def test_a_signup_returns_the_user_and_no_password_field_of_any_kind(client) -> None:
    response = sign_up(client)
    assert response.status_code == 201
    body = response.get_json()
    assert set(body) == {"user"}
    assert set(body["user"]) == {"id", "email", "display_name"}
    assert body["user"]["email"] == "sam@example.com"
    assert body["user"]["display_name"] == "Sam"
    assert body["user"]["id"]
    text = response.get_data(as_text=True)
    for forbidden in ("password", "hash", "scrypt", "salt", "credential"):
        assert forbidden not in text.lower()


def test_a_signup_creates_no_session(client) -> None:
    # Task 7 decided signup issues none, and keeping one place that mints a session
    # is worth the client's second request.
    response = sign_up(client)
    assert response.status_code == 201
    assert web.SESSION_COOKIE not in set_cookies(response)
    assert client.get("/api/session").status_code == 401


def test_a_signup_links_nothing(app, seeded: Path) -> None:
    from splitwise_lite.groups import resolve_sole_group

    client = app.test_client()
    assert sign_up(client).status_code == 201
    with open_store(seeded) as store:
        group = resolve_sole_group(store)
        assert all(
            member.user_id is None for member in store.list_members(group.id)
        )


def test_a_duplicate_address_is_a_conflict(client) -> None:
    assert sign_up(client).status_code == 201
    response = sign_up(client, display_name="Someone Else")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "email_already_registered"


def test_a_losing_racer_gets_the_same_answer_as_a_plain_duplicate(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The address was free when it was checked and taken by the time the row was
    # written. For the person typing that is the same situation.
    client = app.test_client()
    plain = app.test_client()
    assert sign_up(plain).status_code == 201
    expected = sign_up(plain, display_name="Someone Else")

    fresh = app.test_client()
    real = web.accounts.sign_up

    def racing(*arguments, **keywords):
        raise web.store.DuplicateRecord("a user with that email already exists")

    monkeypatch.setattr(web.accounts, "sign_up", racing)
    raced = sign_up(fresh, email="racer@example.com")
    monkeypatch.setattr(web.accounts, "sign_up", real)

    assert raced.status_code == expected.status_code == 409
    assert (
        raced.get_json()["error"]["code"]
        == expected.get_json()["error"]["code"]
        == "email_already_registered"
    )
    assert client.get("/api/session").status_code == 401


@pytest.mark.parametrize(
    "payload, code, fragment",
    [
        (
            {"email": "not-an-address", "display_name": "Sam", "password": PASSWORD},
            "invalid_email",
            "exactly one @",
        ),
        (
            {"email": "sam@example.com", "display_name": "Sam", "password": "short"},
            "invalid_password",
            "characters",
        ),
        (
            {"email": "sam@example.com", "display_name": "   ", "password": PASSWORD},
            "invalid_record",
            "display_name",
        ),
    ],
)
def test_a_rejected_signup_carries_the_domain_layers_own_message(
    client, payload: dict, code: str, fragment: str
) -> None:
    response = post(client, "/api/signup", payload)
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == code
    assert fragment in body["error"]["message"]


# --- Signing in -------------------------------------------------------------


def test_a_correct_password_returns_the_session_view(app, seeded: Path) -> None:
    signed = linked_client(app, seeded)
    body = signed.get("/api/session").get_json()
    assert body["member"]["display_name"] == "Sam"


def test_every_failure_says_exactly_the_same_thing(app, seeded: Path) -> None:
    # Task 7's guarantee: the response reveals nothing about which field was wrong.
    from splitwise_lite.events import new_id
    from splitwise_lite.store import User, UserId

    client = app.test_client()
    assert sign_up(client).status_code == 201

    with open_store(seeded) as store:
        # An account with no credential row at all: add_user can make one, and it
        # simply cannot sign in.
        store.add_user(
            User(UserId(new_id()), "nopassword@example.com", "No Password", at())
        )

    wrong_password = log_in(client, password=OTHER_PASSWORD)
    unknown_address = log_in(client, email="nobody@example.com")
    no_credential = log_in(client, email="nopassword@example.com")

    for response in (wrong_password, unknown_address, no_credential):
        assert response.status_code == 401
        assert response.get_json()["error"]["code"] == "authentication_failed"
    assert wrong_password.data == unknown_address.data == no_credential.data


# --- The CSRF gate is total over every string a header can carry ---------------

# Werkzeug decodes request headers as latin-1, so any byte from 0x80 up arrives as a
# str with a codepoint above 0x7F. `hmac.compare_digest` refuses those outright, so a
# gate that hands it two `str` objects turns a refusal into a 500 with a logged
# traceback: not a bypass, but an unauthenticated caller with unbounded traceback
# logging, and a `DELETE /api/session` that this task documents as never failing.
NON_ASCII_TOKENS = [
    "tokén",  # latin-1, one byte above 0x7f
    "ÿ" * 43,  # every character above 0x7f, the right length
    "abc def",  # a non-breaking space, which reads as ASCII and is not
]


@pytest.mark.parametrize("submitted", NON_ASCII_TOKENS)
def test_a_non_ascii_csrf_header_is_refused_and_never_a_five_hundred(
    client, caplog, submitted: str
) -> None:
    import logging

    csrf_token(client)
    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/api/signup", json={}, headers={web.CSRF_HEADER: submitted}
        )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"
    # Nothing was logged, so an unauthenticated caller cannot spend the log on this.
    assert "Traceback" not in caplog.text


@pytest.mark.parametrize("submitted", NON_ASCII_TOKENS)
def test_signing_out_is_never_a_five_hundred_whatever_the_header_carries(
    client, submitted: str
) -> None:
    # DELETE /api/session is documented as never failing. It may refuse an untrusted
    # request, but it may not fall over on one.
    csrf_token(client)
    response = client.delete(
        "/api/session",
        content_type="application/json",
        headers={web.CSRF_HEADER: submitted},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"


def test_a_non_ascii_cookie_is_refused_rather_than_raising(client) -> None:
    token = csrf_token(client)
    client.set_cookie(web.CSRF_COOKIE, "støred")
    response = client.post("/api/signup", json={}, headers={web.CSRF_HEADER: token})
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"


def test_the_gate_still_accepts_the_token_it_issued(client) -> None:
    # The encoding fix must not make the ordinary path stop matching.
    token = csrf_token(client)
    response = client.post(
        "/api/signup",
        json={
            "email": "sam@example.com",
            "display_name": "Sam",
            "password": PASSWORD,
        },
        headers={web.CSRF_HEADER: token},
    )
    assert response.status_code == 201


def test_the_csrf_comparison_is_made_over_bytes() -> None:
    # The reason the gate is total: `hmac.compare_digest` accepts any bytes and
    # refuses two `str` objects that are not both ASCII.
    import ast

    tree = ast.parse(web_source())
    gate = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_check_csrf"
    )
    comparison = next(
        node
        for node in ast.walk(gate)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compare_digest"
    )
    for argument in comparison.args:
        assert isinstance(argument, ast.Call), ast.dump(argument)
        assert isinstance(argument.func, ast.Attribute)
        assert argument.func.attr == "encode", ast.dump(argument)


# --- A path the operating system will not look at is a 404, not a 500 ----------


@pytest.mark.parametrize(
    "path",
    [
        "/..%00/x",
        "/%00",
        "/a%00b.js",
        "/index.html%00.txt",
        "/%00../pyproject.toml",
    ],
)
def test_a_null_byte_in_the_path_is_a_404_like_any_other_bad_path(
    client, caplog, path: str
) -> None:
    # `Path.resolve` and `Path.is_file` raise before the containment check can run,
    # so the check being correct is not enough on its own.
    import logging

    with caplog.at_level(logging.ERROR):
        response = client.get(path)
    assert response.status_code == 404, path
    assert response.get_json()["error"]["code"] == "not_found"
    assert b"hatchling" not in response.data
    assert "Traceback" not in caplog.text


def test_a_name_the_filesystem_refuses_is_a_404_not_a_five_hundred(client) -> None:
    # A path far longer than any filesystem accepts. It must be refused the same way
    # a missing file is, rather than by whatever the operating system raises.
    response = client.get("/" + ("a" * 5000) + ".js")
    assert response.status_code in (404, 414)
    if response.status_code == 404:
        assert response.get_json()["error"]["code"] == "not_found"


# --- The debts behind one pair ----------------------------------------------
#
# Task 12a of plans/backlog.md, sharpened in
# plans/tasks/12a-transfer-provenance-api.md. One pair per request, asked for only
# when somebody opens a row: there is no bulk endpoint and no endpoint per transfer.


def debt_path(debtor_id: str, creditor_id: str) -> str:
    """The endpoint's path with both ids encoded, exactly as ``api.debt`` builds it."""
    return f"/api/debts/{quote(debtor_id, safe='')}/{quote(creditor_id, safe='')}"


def read_debt(client, debtor_id: str, creditor_id: str):
    return client.get(debt_path(debtor_id, creditor_id))


def append_settlement(
    path: Path,
    *,
    payer_id: str,
    receiver_id: str,
    amount_cents: int,
    confirm: bool,
    settlement_id: str = "settlement-1",
    hour: int = 12,
) -> str:
    """Append one settlement, plus the receiver's confirmation when ``confirm``.

    Written straight through ``open_store`` rather than through an endpoint, because
    no endpoint creates a settlement until task 14 and a confirmed settlement is the
    only thing besides an expense that moves a pairwise debt. The tests below that need
    one therefore build it here, and this comment is where that is stated.
    """
    from splitwise_lite.events import (
        SettlementDecisionEvent,
        SettlementEvent,
        SettlementId,
        SettlementState,
    )
    from splitwise_lite.groups import resolve_sole_group

    with open_store(path) as store:
        group = resolve_sole_group(store)
        store.append_settlement(
            SettlementEvent(
                id=SettlementId(settlement_id),
                group_id=group.id,
                currency=group.currency,
                from_member_id=payer_id,
                to_member_id=receiver_id,
                amount_cents=amount_cents,
                created_at=at(hour),
                created_by=payer_id,
            )
        )
        if confirm:
            store.append_settlement_decision(
                SettlementDecisionEvent(
                    id=f"decision-{settlement_id}",
                    settlement_id=SettlementId(settlement_id),
                    decision=SettlementState.CONFIRMED,
                    decided_by=receiver_id,
                    created_at=at(hour, 1),
                )
            )
    return settlement_id


def add_member_with_id(path: Path, member_id: str, display_name: str) -> None:
    """Put one member into the group with an id chosen here rather than by ``new_id``.

    Real ids come from ``new_id()`` and are plain UUIDs, so this is the only way to
    reach a member id that has to survive percent-encoding on the way through a path.
    """
    from splitwise_lite.groups import resolve_sole_group
    from splitwise_lite.store import Member

    with open_store(path) as store:
        group = resolve_sole_group(store)
        store.add_member(
            Member(
                id=member_id,
                group_id=group.id,
                display_name=display_name,
                user_id=None,
                created_at=at(),
            )
        )


def seed_two_member_debt(client, members: dict[str, str], monkeypatch) -> None:
    """Sam pays 10.00 for Sam and Ali, so Ali owes Sam 5.00 and nobody else moves."""
    monkeypatch.setattr(web, "_now", lambda: at(9))
    assert (
        add_expense(
            client,
            payer_id=members["Sam"],
            amount="10.00",
            split=equal_split(members["Sam"], members["Ali"]),
        ).status_code
        == 201
    )


def seed_chain(client, members: dict[str, str], monkeypatch) -> None:
    """Task 5's chain fixture, entered through the real endpoint.

    Jo owes Ali 10.00 and Ali owes Sam 4.00, so the plan carries two transfers out of
    Jo, one 10.00 debt is split across both of them, and Jo and Sam share no expense at
    all: exactly the situation issue #14 exists to explain.
    """
    monkeypatch.setattr(web, "_now", lambda: at(9))
    assert (
        add_expense(
            client,
            payer_id=members["Ali"],
            amount="10.00",
            split=equal_split(members["Jo"]),
        ).status_code
        == 201
    )
    monkeypatch.setattr(web, "_now", lambda: at(10))
    assert (
        add_expense(
            client,
            payer_id=members["Sam"],
            amount="4.00",
            split=equal_split(members["Ali"]),
        ).status_code
        == 201
    )


def transfer_to(client, member_id: str) -> dict:
    """The one suggested transfer that pays ``member_id``.

    Looked up rather than indexed: ``simplify_debts`` returns its plan sorted by
    ``(from_member_id, to_member_id)``, and member ids are UUIDs, so which of two
    transfers comes first is not something a test can write down.
    """
    transfers = client.get("/api/balances").get_json()["transfers"]
    found = [row for row in transfers if row["to_member_id"] == member_id]
    assert len(found) == 1, transfers
    return found[0]


def seed_cycle(client, members: dict[str, str], monkeypatch) -> None:
    """A pure cycle: Sam owes Ali, Ali owes Jo and Jo owes Sam, all 10.00.

    Every net position is zero, so the plan is empty while three debts are live.
    """
    for index, (payer, other) in enumerate(
        [("Ali", "Sam"), ("Jo", "Ali"), ("Sam", "Jo")]
    ):
        monkeypatch.setattr(web, "_now", lambda hour=9 + index: at(hour))
        assert (
            add_expense(
                client,
                payer_id=members[payer],
                amount="10.00",
                split=equal_split(members[other]),
            ).status_code
            == 201
        )


def test_the_debt_endpoint_is_in_the_api_endpoint_set_so_the_hooks_run(app) -> None:
    # ``_before_request`` reads this endpoint's policy out of ``_API_ACCESS``, and a
    # rule under ``/api`` with no row there is refused rather than served. Naming the
    # level is stronger than an absence from two exemption tuples: it says which of
    # the three gates run, not merely that some do.
    assert web._API_ACCESS["read_debt"] is web._Access.MEMBER
    response = app.test_client().get("/api/debts/whoever/somebody-else")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "not_authenticated"


def test_two_members_with_no_shared_history_are_settled_at_zero(
    app, seeded: Path
) -> None:
    # An empty list is a real answer, never a 404 and never an error.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = read_debt(signed, members["Jo"], members["Sam"])
    assert response.status_code == 200
    assert response.get_json() == {
        "currency": CURRENCY,
        "debtor_id": members["Jo"],
        "creditor_id": members["Sam"],
        "amount": "0.00",
        "direction": "settled",
        "entries": [],
    }


def test_a_pair_with_expenses_both_ways_lists_both_effects_newest_first(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Jo took 10.00 of Sam's 30.00 and Sam took 4.50 of Jo's 9.00, so the pair holds
    # one entry each way and the signed sum is what the balances payload reports.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    third, _second, first = signed.get("/api/expenses").get_json()["expenses"]

    response = read_debt(signed, members["Jo"], members["Sam"])
    assert response.status_code == 200
    assert response.get_json() == {
        "currency": CURRENCY,
        "debtor_id": members["Jo"],
        "creditor_id": members["Sam"],
        "amount": "5.50",
        "direction": "owes",
        "entries": [
            {
                "kind": "expense",
                "effect": "reduces",
                "id": third["id"],
                "description": "Milk",
                "created_at": third["created_at"],
                "amount": "4.50",
            },
            {
                "kind": "expense",
                "effect": "adds",
                "id": first["id"],
                "description": "Milk",
                "created_at": first["created_at"],
                "amount": "10.00",
            },
        ],
    }


def test_the_pair_read_the_other_way_flips_every_effect_and_the_direction(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)

    forward = read_debt(signed, members["Jo"], members["Sam"]).get_json()
    backward = read_debt(signed, members["Sam"], members["Jo"]).get_json()
    assert backward["amount"] == "5.50"
    assert backward["direction"] == "owed"
    assert [entry["id"] for entry in backward["entries"]] == [
        entry["id"] for entry in forward["entries"]
    ]
    assert [entry["effect"] for entry in backward["entries"]] == ["adds", "reduces"]


def test_a_debt_a_confirmed_settlement_cancelled_still_lists_what_is_behind_it(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This is why no client may add the entries up and call the total the debt.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_two_member_debt(signed, members, monkeypatch)
    append_settlement(
        seeded,
        payer_id=members["Ali"],
        receiver_id=members["Sam"],
        amount_cents=500,
        confirm=True,
    )

    body = read_debt(signed, members["Ali"], members["Sam"]).get_json()
    assert body["amount"] == "0.00"
    assert body["direction"] == "settled"
    assert [(entry["kind"], entry["effect"], entry["amount"]) for entry in body["entries"]] == [
        ("settlement", "reduces", "5.00"),
        ("expense", "adds", "5.00"),
    ]


def test_a_settlement_larger_than_the_debt_flips_the_pair_on_the_wire(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The ids are unchanged and the magnitude is the overshoot, which is exactly the
    # case a path of two ids can be asked about after the ledger moved.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_two_member_debt(signed, members, monkeypatch)
    append_settlement(
        seeded,
        payer_id=members["Ali"],
        receiver_id=members["Sam"],
        amount_cents=800,
        confirm=True,
    )

    body = read_debt(signed, members["Ali"], members["Sam"]).get_json()
    assert body["debtor_id"] == members["Ali"]
    assert body["creditor_id"] == members["Sam"]
    assert body["amount"] == "3.00"
    assert body["direction"] == "owed"


def test_a_pending_settlement_appears_in_no_entries_and_moves_no_figure(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_two_member_debt(signed, members, monkeypatch)
    append_settlement(
        seeded,
        payer_id=members["Ali"],
        receiver_id=members["Sam"],
        amount_cents=500,
        confirm=False,
    )

    body = read_debt(signed, members["Ali"], members["Sam"]).get_json()
    assert body["amount"] == "5.00"
    assert body["direction"] == "owes"
    assert [entry["kind"] for entry in body["entries"]] == ["expense"]
    assert "settlement-1" not in read_debt(
        signed, members["Ali"], members["Sam"]
    ).get_data(as_text=True)


def test_a_transfer_between_two_people_who_share_nothing_is_explained_by_both_arrays(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The whole claim the drill-down makes, asserted in one place: Jo pays Sam because
    # Jo owes Ali and Ali owes Sam, and Jo and Sam have no debt between them at all.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_chain(signed, members, monkeypatch)

    to_sam = transfer_to(signed, members["Sam"])
    assert to_sam["from_member_id"] == members["Jo"]
    assert to_sam["amount"] == "4.00"
    assert [(row["debtor_id"], row["creditor_id"]) for row in to_sam["payer_debts"]] == [
        (members["Jo"], members["Ali"])
    ]
    assert [
        (row["debtor_id"], row["creditor_id"]) for row in to_sam["receiver_credits"]
    ] == [(members["Ali"], members["Sam"])]

    body = read_debt(signed, members["Jo"], members["Sam"]).get_json()
    assert body["entries"] == []
    assert body["amount"] == "0.00"
    assert body["direction"] == "settled"


def test_a_debt_split_across_two_transfers_carries_the_whole_debt_on_both_rows(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_chain(signed, members, monkeypatch)

    # The one 10.00 debt Jo owes Ali pays for both transfers, 6.00 of it through the
    # one to Ali and 4.00 through the one to Sam, and each row carries the whole 10.00.
    assert transfer_to(signed, members["Ali"])["payer_debts"] == [
        {
            "debtor_id": members["Jo"],
            "creditor_id": members["Ali"],
            "amount": "6.00",
            "debt_total": "10.00",
            "covers_whole_debt": False,
        }
    ]
    assert transfer_to(signed, members["Sam"])["payer_debts"] == [
        {
            "debtor_id": members["Jo"],
            "creditor_id": members["Ali"],
            "amount": "4.00",
            "debt_total": "10.00",
            "covers_whole_debt": False,
        }
    ]


def test_a_transfer_covering_a_whole_single_debt_says_so(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_chain(signed, members, monkeypatch)

    assert transfer_to(signed, members["Sam"])["receiver_credits"] == [
        {
            "debtor_id": members["Ali"],
            "creditor_id": members["Sam"],
            "amount": "4.00",
            "debt_total": "4.00",
            "covers_whole_debt": True,
        }
    ]


def test_a_pure_cycle_has_no_transfers_and_every_live_pair_still_reads(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_cycle(signed, members, monkeypatch)

    response = signed.get("/api/balances")
    assert response.get_json()["transfers"] == []
    text = response.get_data(as_text=True)
    for forbidden in ("payer_debts", "receiver_credits", "debt_total", "covers_whole_debt"):
        assert forbidden not in text

    for debtor, creditor in (("Sam", "Ali"), ("Ali", "Jo"), ("Jo", "Sam")):
        body = read_debt(signed, members[debtor], members[creditor]).get_json()
        assert body["amount"] == "10.00", (debtor, creditor)
        assert body["direction"] == "owes", (debtor, creditor)
        assert [entry["effect"] for entry in body["entries"]] == ["adds"]


def test_every_entry_holds_exactly_six_keys(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_two_member_debt(signed, members, monkeypatch)
    append_settlement(
        seeded,
        payer_id=members["Ali"],
        receiver_id=members["Sam"],
        amount_cents=200,
        confirm=True,
    )

    body = read_debt(signed, members["Ali"], members["Sam"]).get_json()
    assert set(body) == {
        "currency",
        "debtor_id",
        "creditor_id",
        "amount",
        "direction",
        "entries",
    }
    assert len(body["entries"]) == 2
    for entry in body["entries"]:
        assert set(entry) == {
            "kind",
            "effect",
            "id",
            "description",
            "created_at",
            "amount",
        }
        assert entry["kind"] in ("expense", "settlement")
        assert entry["effect"] in ("adds", "reduces")
        assert not entry["amount"].startswith("-")


def test_the_wire_vocabulary_is_a_map_that_covers_both_domain_enums() -> None:
    # An explicit map rather than the enum values, so renaming a domain enum member
    # cannot silently rename a JSON value the front end branches on.
    from splitwise_lite.balances import DebtEffect, DebtEntryKind

    assert set(web._ENTRY_KIND_WIRE) == set(DebtEntryKind)
    assert set(web._ENTRY_EFFECT_WIRE) == set(DebtEffect)
    assert sorted(web._ENTRY_KIND_WIRE.values()) == ["expense", "settlement"]
    assert sorted(web._ENTRY_EFFECT_WIRE.values()) == ["adds", "reduces"]


def test_a_settlement_entry_carries_an_empty_description(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_two_member_debt(signed, members, monkeypatch)
    append_settlement(
        seeded,
        payer_id=members["Ali"],
        receiver_id=members["Sam"],
        amount_cents=200,
        confirm=True,
    )

    body = read_debt(signed, members["Ali"], members["Sam"]).get_json()
    settlement_entry = next(
        entry for entry in body["entries"] if entry["kind"] == "settlement"
    )
    assert settlement_entry["description"] == ""
    assert settlement_entry["id"] == "settlement-1"


def test_a_description_reaches_the_entry_verbatim(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    assert (
        add_expense(
            signed,
            payer_id=members["Sam"],
            amount="10.00",
            split=equal_split(members["Sam"], members["Ali"]),
            description="Two bags of flour",
        ).status_code
        == 201
    )
    body = read_debt(signed, members["Ali"], members["Sam"]).get_json()
    assert [entry["description"] for entry in body["entries"]] == ["Two bags of flour"]


def test_created_at_is_spelled_the_way_the_feed_spells_it(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_two_member_debt(signed, members, monkeypatch)

    expense = signed.get("/api/expenses").get_json()["expenses"][0]
    body = read_debt(signed, members["Ali"], members["Sam"]).get_json()
    assert body["entries"][0]["created_at"] == expense["created_at"]
    assert body["entries"][0]["created_at"] == "2026-09-05T09:00:00.000000+00:00"


@pytest.mark.parametrize("position", ["debtor", "creditor"])
def test_an_id_that_is_not_a_member_of_this_group_is_a_four_hundred_naming_it(
    app, seeded: Path, position: str
) -> None:
    # A 404 was considered and rejected: the path names members, not a stored record,
    # and web.py already refuses an out-of-group member id this way when recording an
    # expense.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    stranger = "not-a-member-of-this-group"
    pair = (
        (stranger, members["Sam"])
        if position == "debtor"
        else (members["Sam"], stranger)
    )
    response = read_debt(signed, *pair)
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    assert stranger in body["error"]["message"]
    assert members["Sam"] not in body["error"]["message"]


def test_a_member_may_not_ask_what_they_owe_themselves(app, seeded: Path) -> None:
    # Together with the roster check this keeps InvalidLedger unreachable from any
    # request, so its place in DELIBERATELY_UNMAPPED stays true.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = read_debt(signed, members["Sam"], members["Sam"])
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    assert "themselves" in body["error"]["message"]


def test_an_id_that_needs_percent_encoding_reaches_the_right_member(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    odd = "a member with a space and a % sign"
    add_member_with_id(seeded, odd, "Oddly Named")
    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    assert (
        add_expense(
            signed,
            payer_id=odd,
            amount="10.00",
            split=equal_split(members["Sam"]),
        ).status_code
        == 201
    )

    response = read_debt(signed, members["Sam"], odd)
    assert response.status_code == 200
    body = response.get_json()
    assert body["debtor_id"] == members["Sam"]
    assert body["creditor_id"] == odd
    assert body["amount"] == "10.00"
    assert body["direction"] == "owes"
    assert [entry["effect"] for entry in body["entries"]] == ["adds"]


def test_a_member_id_containing_a_slash_is_unreachable_through_this_path(
    app, seeded: Path
) -> None:
    # A recorded limitation rather than something worked around: ids come from
    # ``new_id()`` and an operator's roster, so none of them holds a slash.
    sliced = "one/two"
    add_member_with_id(seeded, sliced, "Slashed")
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = signed.get(debt_path(sliced, members["Sam"]))
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("path", ["/api/debts//x", "/api/debts/x/"])
def test_an_empty_path_segment_matches_no_route(app, seeded: Path, path: str) -> None:
    signed = linked_client(app, seeded)
    response = signed.get(path)
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_any_linked_member_may_read_a_pair_they_are_not_part_of(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The drill-down exists to explain a payment between two other people, and
    # membership of the group is the only authorisation this product has.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_chain(signed, members, monkeypatch)
    body = read_debt(signed, members["Jo"], members["Ali"]).get_json()
    assert body["amount"] == "10.00"
    assert body["direction"] == "owes"


def test_nothing_is_cached_between_two_reads_of_one_pair(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every figure is derived on read, so two requests against a ledger that changed
    # in between may legitimately differ.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_two_member_debt(signed, members, monkeypatch)
    assert read_debt(signed, members["Ali"], members["Sam"]).get_json()["amount"] == "5.00"

    append_settlement(
        seeded,
        payer_id=members["Ali"],
        receiver_id=members["Sam"],
        amount_cents=200,
        confirm=True,
    )
    assert read_debt(signed, members["Ali"], members["Sam"]).get_json()["amount"] == "3.00"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_the_path_serves_no_second_method(app, seeded: Path, method: str) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = send(signed, method, debt_path(members["Jo"], members["Sam"]))
    assert response.status_code == 405
    assert response.get_json()["error"]["code"] == "method_not_allowed"


def test_no_debt_payload_ever_carries_a_minus_sign(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    for debtor, creditor in itertools.permutations(["Sam", "Ali", "Jo"], 2):
        # ``direction`` carries the sign, exactly as it does on a net row, so no
        # client ever has to parse or render one.
        body = read_debt(signed, members[debtor], members[creditor]).get_json()
        assert not body["amount"].startswith("-"), (debtor, creditor)
        assert body["direction"] in ("owes", "owed", "settled"), (debtor, creditor)
        for entry in body["entries"]:
            assert not entry["amount"].startswith("-"), (debtor, creditor)


# --- Task 14: marking a payment as paid -------------------------------------

SETTLEMENT_KEYS = {
    "id",
    "from_member_id",
    "to_member_id",
    "amount",
    "created_at",
    "created_by",
    "state",
}


def mark_paid(client, *, to_member_id: str, amount: str):
    """One ``POST /api/settlements``, with the three CSRF gates met.

    The payer is never named: the endpoint takes it from the acting member, which is
    the whole of why a settlement needs two people.
    """
    return post(
        client, "/api/settlements", {"to_member_id": to_member_id, "amount": amount}
    )


def stored_settlements(path: Path):
    from splitwise_lite.groups import resolve_sole_group

    with open_store(path) as store:
        return store.list_settlements(resolve_sole_group(store).id)


def test_marking_a_payment_as_paid_answers_the_one_settlement_it_recorded(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    response = mark_paid(signed, to_member_id=members["Ali"], amount="12.50")
    assert response.status_code == 201
    body = response.get_json()
    assert set(body) == {"settlement"}
    view = body["settlement"]
    assert set(view) == SETTLEMENT_KEYS
    assert view["from_member_id"] == members["Sam"]
    assert view["to_member_id"] == members["Ali"]
    assert view["created_by"] == members["Sam"]
    assert view["amount"] == "12.50"
    assert view["state"] == "pending"
    stored = stored_settlements(seeded)
    assert len(stored) == 1
    assert stored[0].id == view["id"]


def test_the_payer_is_the_acting_member_whoever_is_signed_in(
    app, seeded: Path
) -> None:
    # Structural, not a check that could be forgotten: there is no code path by which
    # one member records a payment as coming from another.
    signed = linked_client(app, seeded, display_name="Jo")
    members = by_name(signed)
    view = mark_paid(signed, to_member_id=members["Sam"], amount="1.00").get_json()[
        "settlement"
    ]
    assert view["from_member_id"] == members["Jo"]
    assert view["created_by"] == members["Jo"]


@pytest.mark.parametrize(
    "key",
    ["from_member_id", "created_by", "id", "created_at", "currency", "group_id"],
)
def test_a_settlement_body_may_not_name_a_key_the_endpoint_owns(
    app, seeded: Path, key: str
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = post(
        signed,
        "/api/settlements",
        {"to_member_id": members["Ali"], "amount": "1.00", key: "anything"},
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    assert repr(key) in body["error"]["message"]
    assert stored_settlements(seeded) == ()


def test_the_settlement_state_wire_map_covers_every_state() -> None:
    # An explicit map over the enum, exhaustive, exactly as _ENTRY_KIND_WIRE is:
    # renaming a domain member must not silently rename a JSON value a client
    # branches on. Only "pending" is reachable in task 14, and the other two are here
    # so task 15 adds values rather than adding a field.
    from splitwise_lite.events import SettlementState

    assert set(web._SETTLEMENT_STATE_WIRE) == set(SettlementState)
    assert sorted(web._SETTLEMENT_STATE_WIRE.values()) == [
        "confirmed",
        "pending",
        "rejected",
    ]


@pytest.mark.parametrize("amount", ["12.50", "0.01", "1", "1.5", "1,234.00"])
def test_a_settlement_amount_round_trips_through_the_one_display_edge(
    app, seeded: Path, amount: str
) -> None:
    from splitwise_lite.money import Currency, format_amount, parse_amount

    signed = linked_client(app, seeded)
    members = by_name(signed)
    view = mark_paid(signed, to_member_id=members["Ali"], amount=amount).get_json()[
        "settlement"
    ]
    expected = format_amount(parse_amount(amount, Currency(CURRENCY)))
    assert view["amount"] == expected
    assert not view["amount"].startswith("-")


def test_a_settlement_is_stamped_with_the_servers_own_clock(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Byte-identical in spelling to what _expense_view produces, so feedDate reads one
    # instant one way wherever it appears on the wire.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9, 30))
    expense = add_expense(
        signed,
        payer_id=members["Sam"],
        amount="1.00",
        split=equal_split(members["Sam"], members["Ali"]),
    ).get_json()["expense"]
    settlement = mark_paid(
        signed, to_member_id=members["Ali"], amount="1.00"
    ).get_json()["settlement"]
    assert settlement["created_at"] == expense["created_at"]
    assert settlement["created_at"] == at(9, 30).isoformat(timespec="microseconds")


def test_a_settlement_to_somebody_outside_the_group_is_refused_by_name(
    app, seeded: Path
) -> None:
    signed = linked_client(app, seeded)
    response = mark_paid(signed, to_member_id="mem-nobody", amount="1.00")
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    assert "mem-nobody" in body["error"]["message"]
    assert stored_settlements(seeded) == ()


def test_a_settlement_to_yourself_is_refused_before_the_event_is_built(
    app, seeded: Path
) -> None:
    # SettlementEvent.__post_init__ raises InvalidEvent for a self-pair, and
    # InvalidEvent is in neither ERROR_STATUS nor ERROR_CODE, so letting it escape
    # would answer 500 with the reason in the log only. The view refuses it first.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = mark_paid(signed, to_member_id=members["Sam"], amount="1.00")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "malformed_request"
    assert stored_settlements(seeded) == ()


def test_a_zero_amount_is_refused_before_the_event_is_built(app, seeded: Path) -> None:
    # The other InvalidEvent trap: a non-positive amount. 400 and never 500.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    for amount in ("0", "0.00"):
        response = mark_paid(signed, to_member_id=members["Ali"], amount=amount)
        assert response.status_code == 400, amount
        assert response.get_json()["error"]["code"] == "malformed_request", amount
    assert stored_settlements(seeded) == ()


def test_a_negative_amount_never_reaches_the_event_either(app, seeded: Path) -> None:
    # parse_amount takes no sign at all, so a negative amount is refused at the one
    # input edge, one step earlier than the zero above. 400 and never 500.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = mark_paid(signed, to_member_id=members["Ali"], amount="-5.00")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_amount"
    assert stored_settlements(seeded) == ()


def test_an_amount_above_what_can_be_stored_is_refused_at_the_input_edge(
    app, seeded: Path
) -> None:
    # money.MAX_CENTS is store.MAX_CENTS, and parse_amount enforces it, so the
    # store's own AmountTooLarge is an unreachable backstop on this path.
    from splitwise_lite.money import MAX_CENTS

    signed = linked_client(app, seeded)
    members = by_name(signed)
    over = str((MAX_CENTS + 1) // 100) + "." + f"{(MAX_CENTS + 1) % 100:02d}"
    response = mark_paid(signed, to_member_id=members["Ali"], amount=over)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_amount"
    assert stored_settlements(seeded) == ()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"amount": "1.00"},
        {"to_member_id": "mem-1"},
        {"to_member_id": "mem-1", "amount": "1.00", "note": "thanks"},
        {"to_member_id": "mem-1", "amounts": "1.00"},
    ],
)
def test_a_settlement_body_of_the_wrong_shape_is_refused(
    app, seeded: Path, payload: dict
) -> None:
    signed = linked_client(app, seeded)
    response = post(signed, "/api/settlements", payload)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "malformed_request"
    assert stored_settlements(seeded) == ()


def test_a_receiver_that_is_not_a_json_string_is_refused(app, seeded: Path) -> None:
    signed = linked_client(app, seeded)
    response = post(signed, "/api/settlements", {"to_member_id": 7, "amount": "1.00"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "malformed_request"
    assert stored_settlements(seeded) == ()


def test_a_settlement_amount_that_is_a_json_number_is_refused(
    app, seeded: Path
) -> None:
    # A number is something a client could have done arithmetic on, so money crosses
    # this wire as a string or not at all.
    #
    # Named for its endpoint because the expense path already owns
    # ``test_an_amount_that_is_a_json_number_is_refused``, four parametrised cases near
    # the top of this file. This function carried that name until QA caught it: a
    # second definition rebinds the first at module scope, pytest collects only the
    # later one, and those four cases stopped running with the suite green and no
    # warning from anything.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = post(
        signed, "/api/settlements", {"to_member_id": members["Ali"], "amount": 12.5}
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "malformed_request"
    assert "amounts are strings, never numbers" in body["error"]["message"]
    assert stored_settlements(seeded) == ()


def test_an_unparseable_amount_is_refused_by_the_one_input_edge(
    app, seeded: Path
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = mark_paid(signed, to_member_id=members["Ali"], amount="twelve")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_amount"
    assert stored_settlements(seeded) == ()


def test_marking_a_payment_needs_a_session(client) -> None:
    response = post(
        client, "/api/settlements", {"to_member_id": "mem-1", "amount": "1.00"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "not_authenticated"


def test_marking_a_payment_needs_a_member_row(app) -> None:
    signed = app.test_client()
    signed_in(signed, app)
    response = post(
        signed, "/api/settlements", {"to_member_id": "mem-1", "amount": "1.00"}
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "member_not_linked"


def test_marking_a_payment_needs_the_csrf_header(app, seeded: Path) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    response = signed.post(
        "/api/settlements", json={"to_member_id": members["Ali"], "amount": "1.00"}
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"
    assert stored_settlements(seeded) == ()


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_the_settlements_path_serves_no_second_method(
    app, seeded: Path, method: str
) -> None:
    signed = linked_client(app, seeded)
    response = send(signed, method, "/api/settlements")
    assert response.status_code == 405
    assert response.get_json()["error"]["code"] == "method_not_allowed"


def test_a_get_on_the_settlements_path_is_the_shells_own_404(
    app, seeded: Path
) -> None:
    # Not a 405. ``/<path:filename>`` is registered for GET, so a GET that no API row
    # claims matches the shell catch-all, which serves no such file and answers 404,
    # exactly as ``GET /api/nope`` does. ``_before_request`` already records that the
    # catch-all matches paths under ``/api``. There is no GET here to serve: the
    # pending claims ride on the balances read rather than on a second endpoint.
    signed = linked_client(app, seeded)
    response = signed.get("/api/settlements")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_a_second_claim_to_the_same_receiver_is_refused_as_already_pending(
    app, seeded: Path
) -> None:
    # Two pending claims for one payment become two confirmations in task 15, and the
    # debt clears twice. Refused, and the accepted cost is that the pair is blocked
    # until the receiver answers.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    first = mark_paid(signed, to_member_id=members["Ali"], amount="1.00")
    assert first.status_code == 201
    response = mark_paid(signed, to_member_id=members["Ali"], amount="2.00")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "settlement_already_pending"
    assert len(stored_settlements(seeded)) == 1


def test_the_pending_claim_refusal_is_scoped_to_the_ordered_pair(
    app, seeded: Path
) -> None:
    # Jo claiming a payment to Sam and Sam claiming one to Jo are two claims about
    # two different transfers of money, and both may be true.
    sam = linked_client(app, seeded)
    members = by_name(sam)
    jo = linked_client(app, seeded, display_name="Jo")
    assert mark_paid(sam, to_member_id=members["Jo"], amount="1.00").status_code == 201
    assert mark_paid(jo, to_member_id=members["Sam"], amount="1.00").status_code == 201
    # A third member is a different pair again.
    assert mark_paid(sam, to_member_id=members["Ali"], amount="1.00").status_code == 201
    assert len(stored_settlements(seeded)) == 3


@pytest.mark.parametrize("confirm", [True, False])
def test_an_answered_claim_frees_the_pair_for_a_fresh_one(
    app, seeded: Path, confirm: bool
) -> None:
    # The refusal is scoped to the pending state, not to the pair for all time. A
    # rejected claim frees the pair too, which task 15 has to decide it wants.
    from splitwise_lite.events import (
        SettlementDecisionEvent,
        SettlementId,
        SettlementState,
    )

    signed = linked_client(app, seeded)
    members = by_name(signed)
    first = mark_paid(signed, to_member_id=members["Ali"], amount="1.00").get_json()[
        "settlement"
    ]
    with open_store(seeded) as store:
        store.append_settlement_decision(
            SettlementDecisionEvent(
                id="decision-1",
                settlement_id=SettlementId(first["id"]),
                decision=(
                    SettlementState.CONFIRMED if confirm else SettlementState.REJECTED
                ),
                decided_by=members["Ali"],
                created_at=at(13),
            )
        )
    second = mark_paid(signed, to_member_id=members["Ali"], amount="2.00")
    assert second.status_code == 201
    assert len(stored_settlements(seeded)) == 2


def test_the_settlements_route_must_be_declared_or_the_app_will_not_build(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Criterion 2, half one: delete the row and the audit refuses to hand back an app
    # that serves a rule no row declares. ``app`` was built with the row, so its
    # url_map serves the rule; the table below no longer declares it.
    without = tuple(
        route for route in web._API_ROUTES if route.endpoint != "create_settlement"
    )
    assert len(without) == len(web._API_ROUTES) - 1
    monkeypatch.setattr(web, "_API_ROUTES", without)
    with pytest.raises(web._RouteNotDeclared) as raised:
        web._audit_routes(app)
    assert "/api/settlements" in str(raised.value)


def test_a_settlements_row_that_states_no_access_does_not_construct() -> None:
    # Criterion 2, half two: ``access`` has no default, so a row that does not state
    # what it requires is a TypeError rather than an endpoint that answers anybody.
    with pytest.raises(TypeError):
        web._ApiRoute(
            "/api/settlements",
            "create_settlement",
            web._create_settlement,
            ("POST",),
        )


def test_the_settlements_row_is_the_only_place_the_endpoint_is_registered() -> None:
    rows = [route for route in web._API_ROUTES if route.rule == "/api/settlements"]
    assert len(rows) == 1
    assert rows[0].endpoint == "create_settlement"
    assert rows[0].methods == ("POST",)
    assert rows[0].access is web._Access.MEMBER
    assert web._API_ACCESS["create_settlement"] is web._Access.MEMBER


# --- Task 14: what the balances payload gained ------------------------------


def balances_of(client) -> dict:
    return client.get("/api/balances").get_json()


def test_the_balances_payload_gains_pending_and_nothing_else_at_the_top_level(
    app, seeded: Path
) -> None:
    signed = linked_client(app, seeded)
    body = balances_of(signed)
    assert set(body) == {"currency", "net", "transfers", "pending"}
    assert body["pending"] == []


def test_a_settled_group_reports_an_empty_pending_list(app, seeded: Path) -> None:
    # The empty-ledger payload, pinned exactly, with the new key at its exact value.
    signed = linked_client(app, seeded)
    members = roster(signed)
    assert balances_of(signed) == {
        "currency": CURRENCY,
        "net": [
            {"member_id": member["id"], "amount": "0.00", "direction": "settled"}
            for member in members
        ],
        "transfers": [],
        "pending": [],
    }


def test_a_pending_settlement_appears_in_the_pending_block(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    monkeypatch.setattr(web, "_now", lambda: at(9))
    created = mark_paid(signed, to_member_id=members["Ali"], amount="6.00").get_json()[
        "settlement"
    ]
    body = balances_of(signed)
    assert body["pending"] == [created]
    assert set(body["pending"][0]) == SETTLEMENT_KEYS
    assert body["pending"][0]["state"] == "pending"


def test_pending_holds_no_confirmed_and_no_rejected_settlement(
    app, seeded: Path
) -> None:
    from splitwise_lite.events import (
        SettlementDecisionEvent,
        SettlementId,
        SettlementState,
    )

    signed = linked_client(app, seeded)
    members = by_name(signed)
    kept = mark_paid(signed, to_member_id=members["Ali"], amount="1.00").get_json()[
        "settlement"
    ]
    answered = mark_paid(signed, to_member_id=members["Jo"], amount="2.00").get_json()[
        "settlement"
    ]
    assert {row["id"] for row in balances_of(signed)["pending"]} == {
        kept["id"],
        answered["id"],
    }
    with open_store(seeded) as store:
        store.append_settlement_decision(
            SettlementDecisionEvent(
                id="decision-1",
                settlement_id=SettlementId(answered["id"]),
                decision=SettlementState.CONFIRMED,
                decided_by=members["Jo"],
                created_at=at(13),
            )
        )
    # Appending a decision through the store removes it from pending on the next read.
    assert [row["id"] for row in balances_of(signed)["pending"]] == [kept["id"]]


def test_pending_ascends_by_created_at_then_id_oldest_first(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Oldest first, and not reversed the way the feed is: the claim that has been
    # waiting longest is the one that needs chasing.
    sam = linked_client(app, seeded)
    jo = linked_client(app, seeded, display_name="Jo")
    members = by_name(sam)
    monkeypatch.setattr(web, "_now", lambda: at(11))
    first = mark_paid(sam, to_member_id=members["Ali"], amount="1.00").get_json()[
        "settlement"
    ]
    monkeypatch.setattr(web, "_now", lambda: at(12))
    second = mark_paid(jo, to_member_id=members["Ali"], amount="2.00").get_json()[
        "settlement"
    ]
    monkeypatch.setattr(web, "_now", lambda: at(13))
    third = mark_paid(sam, to_member_id=members["Jo"], amount="3.00").get_json()[
        "settlement"
    ]
    rows = balances_of(sam)["pending"]
    assert [row["id"] for row in rows] == [first["id"], second["id"], third["id"]]
    assert [row["created_at"] for row in rows] == sorted(
        row["created_at"] for row in rows
    )


def test_the_pending_list_rides_on_the_ledger_the_balances_read_already_took() -> None:
    # One request, one read of one ledger, so the transfers and the pending claims
    # come from the same instant and cannot disagree the way two requests against a
    # moving ledger legitimately can.
    import ast

    tree = ast.parse(web_source())
    reader = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_read_balances"
    )
    called = {
        node.func.attr
        for node in ast.walk(reader)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "list_events" in called
    assert "list_settlements" not in called
    assert (
        len(
            [
                node
                for node in ast.walk(reader)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "list_events"
            ]
        )
        == 1
    )


def test_every_transfer_carries_whether_it_is_awaiting_confirmation(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    body = balances_of(signed)
    assert len(body["transfers"]) == 1
    transfer = body["transfers"][0]
    assert set(transfer) == {
        "from_member_id",
        "to_member_id",
        "amount",
        "payer_debts",
        "receiver_credits",
        "awaiting_confirmation",
    }
    assert transfer["awaiting_confirmation"] is False
    # Jo pays Sam, so Jo is the one who can mark it.
    assert transfer["from_member_id"] == members["Jo"]
    jo = linked_client(app, seeded, display_name="Jo")
    assert mark_paid(jo, to_member_id=members["Sam"], amount="1.00").status_code == 201
    marked = balances_of(signed)["transfers"][0]
    assert marked["awaiting_confirmation"] is True
    # Everything else about the row is untouched: the suggestion stays exactly where
    # it was, with the same amount and the same provenance.
    assert {key: marked[key] for key in transfer if key != "awaiting_confirmation"} == {
        key: value for key, value in transfer.items() if key != "awaiting_confirmation"
    }


def test_the_amount_is_no_part_of_the_awaiting_match(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A claim of 5.00 marks a 10.50 row as awaiting. The row's wording says a payment
    # is marked and unconfirmed, never that this figure has been paid, and the exact
    # claimed figure is in the pending block where it can be read against it.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    jo = linked_client(app, seeded, display_name="Jo")
    assert mark_paid(jo, to_member_id=members["Sam"], amount="0.01").status_code == 201
    body = balances_of(signed)
    assert body["transfers"][0]["amount"] == "10.50"
    assert body["transfers"][0]["awaiting_confirmation"] is True
    assert body["pending"][0]["amount"] == "0.01"


def test_a_claim_running_the_other_way_marks_nothing(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Jo pays Sam is the suggestion; Sam claiming a payment to Jo is a different claim
    # about different money, and it marks no transfer.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    assert mark_paid(signed, to_member_id=members["Jo"], amount="1.00").status_code == 201
    body = balances_of(signed)
    assert body["transfers"][0]["awaiting_confirmation"] is False
    assert len(body["pending"]) == 1


def test_a_claim_naming_a_pair_no_transfer_names_marks_nothing(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    assert mark_paid(signed, to_member_id=members["Ali"], amount="1.00").status_code == 201
    body = balances_of(signed)
    assert [transfer["awaiting_confirmation"] for transfer in body["transfers"]] == [
        False
    ]
    assert len(body["pending"]) == 1


# --- Criterion 20: a pending settlement moves no balance --------------------

LEDGER_SEED = 20260907
"""Fixed, so the generated ledgers below are the same on every machine and on every
run: a money invariant checked against a different sample each time is a test that
cannot be bisected."""

GENERATED_LEDGERS = 60
"""More than the fifty the task asks for, and cheap: each one is a fresh store, a
signup at the cheap KDF cost and a handful of appended events."""


def generate_ledger(store, group_id: str, member_ids: list[str], rng, size: int):
    """Append ``size`` entries mixing expenses with settlements in every state.

    In the style ``tests/test_balances.py``'s ``random_ledger`` uses, and written
    through the store rather than through an endpoint, because a confirmed and a
    rejected settlement have no endpoint to come from until task 15. Ids are unique by
    construction, timestamps ascend, and every amount is a whole number of cents, so
    the only thing that varies is the shape of the ledger.
    """
    from splitwise_lite.events import (
        Allocation,
        ExpenseEvent,
        ExpenseId,
        GroupId,
        MemberId,
        SettlementDecisionEvent,
        SettlementEvent,
        SettlementId,
        SettlementState,
    )
    from splitwise_lite.money import Currency

    currency = Currency(CURRENCY)
    for index in range(size):
        when = at(9, index + 1)
        if rng.choice((True, True, False)):
            participants = rng.sample(member_ids, rng.randint(1, len(member_ids)))
            shares = {member_id: rng.randint(0, 500) for member_id in participants}
            if sum(shares.values()) == 0:
                shares[participants[0]] = 1
            store.append_expense(
                ExpenseEvent(
                    id=ExpenseId(f"e{index}"),
                    group_id=GroupId(group_id),
                    currency=currency,
                    payer_id=MemberId(rng.choice(member_ids)),
                    total_cents=sum(shares.values()),
                    allocations=tuple(
                        Allocation(MemberId(member_id), cents)
                        for member_id, cents in shares.items()
                    ),
                    description="",
                    created_at=when,
                    created_by=MemberId(rng.choice(member_ids)),
                )
            )
            continue

        payer, receiver = rng.sample(member_ids, 2)
        store.append_settlement(
            SettlementEvent(
                id=SettlementId(f"s{index}"),
                group_id=GroupId(group_id),
                currency=currency,
                from_member_id=MemberId(payer),
                to_member_id=MemberId(receiver),
                amount_cents=rng.randint(1, 1000),
                created_at=when,
                created_by=MemberId(payer),
            )
        )
        outcome = rng.choice(
            (None, SettlementState.CONFIRMED, SettlementState.REJECTED)
        )
        if outcome is not None:
            store.append_settlement_decision(
                SettlementDecisionEvent(
                    id=f"d{index}",
                    settlement_id=SettlementId(f"s{index}"),
                    decision=outcome,
                    decided_by=MemberId(receiver),
                    created_at=when,
                )
            )


def derived_balances(path: Path, group_id: str):
    from splitwise_lite.balances import derive_balances
    from splitwise_lite.events import GroupId
    from splitwise_lite.money import Currency

    with open_store(path) as store:
        return derive_balances(
            store.list_events(group_id),
            group_id=GroupId(group_id),
            currency=Currency(CURRENCY),
        )


def without_awaiting(transfers: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in transfer.items() if key != "awaiting_confirmation"}
        for transfer in transfers
    ]


def test_a_pending_settlement_moves_no_balance_over_generated_ledgers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim this whole task rests on, over ledgers nobody hand-picked.

    A pending settlement that reached ``derive_balances`` would clear a debt nobody
    has agreed was paid, which is the failure the spec names as making two people see
    two different versions of the truth.

    This is falsifiable and the falsification has been run: deleting the line
    ``if states[settlement.id] is not SettlementState.CONFIRMED: continue`` from
    ``src/splitwise_lite/balances.py`` turns it red. A criterion that still passes with
    that guard gone has not been met.
    """
    import random

    from splitwise_lite.groups import resolve_sole_group

    rng = random.Random(LEDGER_SEED)
    checked = 0
    for index in range(GENERATED_LEDGERS):
        path = tmp_path / f"ledger-{index}.sqlite3"
        seed_group(path, members=("Sam", "Ali", "Jo", "Kit", "Cass"))
        app = web.create_app(
            store_path=path, secure_cookies=False, scrypt_params=CHEAP
        )
        signed = linked_client(app, path)
        with open_store(path) as store:
            group = resolve_sole_group(store)
            member_ids = [member.id for member in store.list_members(group.id)]
            generate_ledger(store, group.id, member_ids, rng, rng.randint(0, 20))
        acting = by_name(signed)["Sam"]

        before = derived_balances(path, group.id)
        payload_before = balances_of(signed)

        # A receiver this payer has no unanswered claim to, so the 409 is not what is
        # under test here.
        blocked = {
            row["to_member_id"]
            for row in payload_before["pending"]
            if row["from_member_id"] == acting
        }
        candidates = [
            member_id
            for member_id in member_ids
            if member_id != acting and member_id not in blocked
        ]
        assert candidates, "every pair from the acting member was already pending"
        monkeypatch.setattr(web, "_now", lambda: at(15, index % 60))
        response = mark_paid(
            signed, to_member_id=candidates[0], amount="7.25"
        )
        assert response.status_code == 201, response.get_json()

        after = derived_balances(path, group.id)
        # Balances has value equality over net and pairwise both, so one == is the
        # whole claim; the two below say which half moved when it fails.
        assert after == before, index
        assert list(after.net.items()) == list(before.net.items()), index
        assert list(after.pairwise.items()) == list(before.pairwise.items()), index

        payload_after = balances_of(signed)
        assert payload_after["currency"] == payload_before["currency"], index
        assert payload_after["net"] == payload_before["net"], index
        assert without_awaiting(payload_after["transfers"]) == without_awaiting(
            payload_before["transfers"]
        ), index
        checked += 1
    assert checked >= 50


def test_the_pending_settlement_those_ledgers_recorded_is_real_and_not_discarded(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The companion to the criterion above: nothing moved, and that is because the
    # fold ignores a pending settlement, not because the settlement was thrown away.
    from splitwise_lite.balances import settlement_states
    from splitwise_lite.events import SettlementState
    from splitwise_lite.groups import resolve_sole_group

    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    before = len(stored_settlements(seeded))
    created = mark_paid(signed, to_member_id=members["Ali"], amount="4.00").get_json()[
        "settlement"
    ]
    stored = stored_settlements(seeded)
    assert len(stored) == before + 1
    with open_store(seeded) as store:
        group = resolve_sole_group(store)
        states = settlement_states(store.list_events(group.id))
    assert states[created["id"]] is SettlementState.PENDING
    assert [row["id"] for row in balances_of(signed)["pending"]] == [created["id"]]


def test_the_feed_says_nothing_at_all_about_a_settlement(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A settlement is not an expense.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    before = signed.get("/api/expenses").get_data(as_text=True)
    created = mark_paid(signed, to_member_id=members["Ali"], amount="4.00").get_json()[
        "settlement"
    ]
    after = signed.get("/api/expenses").get_data(as_text=True)
    assert after == before
    assert created["id"] not in after


def test_no_drill_down_changes_when_a_payment_is_marked_as_paid(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``debt_sources`` lists confirmed settlements only, so a pending one is behind no
    # debt and appears in no entry list, for the pair it names or any other.
    signed = linked_client(app, seeded)
    members = by_name(signed)
    seed_three_expenses(signed, members, monkeypatch)
    pairs = list(itertools.permutations(["Sam", "Ali", "Jo"], 2))
    before = {
        pair: read_debt(signed, members[pair[0]], members[pair[1]]).get_data(
            as_text=True
        )
        for pair in pairs
    }
    assert mark_paid(signed, to_member_id=members["Ali"], amount="4.00").status_code == 201
    for pair in pairs:
        after = read_debt(signed, members[pair[0]], members[pair[1]]).get_data(
            as_text=True
        )
        assert after == before[pair], pair


# --- The one-pending-per-pair rule under two requests at once ---------------
#
# The one test in this file that starts a thread, and the file docstring records it.
# It binds no socket and opens no port, every wait it makes is bounded by
# ``INTERLEAVE_GRACE``, and the request it holds open is held open by an event with a
# timeout rather than by a lock the test itself takes, so it cannot hang the suite
# whatever the endpoint does.


INTERLEAVE_GRACE = 2.0
"""Seconds the first request waits inside the rule for the second one to finish.

It elapses only when the endpoint is doing its job: the second request is then behind
the lock and can never signal, so the first waits out the grace, appends and releases.
With no lock the second request runs straight through in milliseconds and the wait
ends early, which is the failure this test is here to catch.
"""


def two_clients_for_one_member(app, path: Path):
    """Two signed-in clients for the same account, as two devices would be."""
    first = linked_client(app, path)
    second = app.test_client()
    assert log_in(second).status_code == 200
    return first, second


def test_two_marks_at_once_record_one_settlement_and_refuse_the_other(
    app, seeded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The rule reads the ledger and then appends, and ``scripts/serve.py`` runs
    # ``threaded=True``, so without a lock across both halves two requests that
    # interleave in that window each see no pending claim and each append. Two pending
    # claims for one payment are two confirmations in issue #16 and the debt clears
    # twice, which is the whole reason the 409 exists.
    #
    # The interleaving is forced rather than raced for: the first request is stopped
    # inside the rule, at the moment it has read the ledger, and the second is sent
    # while it is stopped there. Nothing here depends on the scheduler.
    import threading

    from splitwise_lite import balances as balances_module

    first, second = two_clients_for_one_member(app, seeded)
    members = by_name(first)
    inside = threading.Event()
    finished = threading.Event()
    reads = 0
    counting = threading.Lock()
    real_states = balances_module.settlement_states

    def stop_the_first_read_inside_the_rule(ledger):
        nonlocal reads
        states = real_states(ledger)
        with counting:
            reads += 1
            stop = reads == 1
        if stop:
            inside.set()
            finished.wait(timeout=INTERLEAVE_GRACE)
        return states

    monkeypatch.setattr(
        balances_module, "settlement_states", stop_the_first_read_inside_the_rule
    )
    answers: dict[str, int] = {}

    def mark(name, client, amount):
        answers[name] = mark_paid(
            client, to_member_id=members["Ali"], amount=amount
        ).status_code

    def second_mark():
        # If the rule never reaches the read this test is about, say so rather than
        # passing on a premise that has gone.
        assert inside.wait(timeout=INTERLEAVE_GRACE * 5), "the rule never read"
        mark("second", second, "2.00")
        finished.set()

    runner = threading.Thread(target=second_mark, name="second-mark")
    runner.start()
    try:
        mark("first", first, "1.00")
    finally:
        finished.set()
        runner.join(timeout=INTERLEAVE_GRACE * 5)
    assert not runner.is_alive()
    assert sorted(answers.values()) == [201, 409], answers
    stored = stored_settlements(seeded)
    assert len(stored) == 1, [settlement.amount_cents for settlement in stored]


def test_the_rule_is_held_by_one_lock_the_whole_module_shares() -> None:
    # Module level, and not per app, per request or per store: two requests racing are
    # two threads of one process, and a lock either of them could take alone guards
    # nothing. ``RateLimiter``'s lock is built per limiter because a limiter is one
    # object the app owns; this one has no such object to live on.
    #
    # ``Lock`` and not ``RLock``, and the second assertion holds that: the docstring
    # tells issue #16 the lock is not reentrant and how to share the counting without
    # nesting an acquire, so the promise and the check belong in the same place.
    import threading

    assert isinstance(web._SETTLEMENT_LOCK, type(threading.Lock()))
    assert not isinstance(web._SETTLEMENT_LOCK, type(threading.RLock()))
    source = web_source()
    assert source.count("_SETTLEMENT_LOCK: Final = threading.Lock()") == 1
    assert "with _SETTLEMENT_LOCK:" in source
