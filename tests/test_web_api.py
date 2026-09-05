"""Tests for the application server and the JSON API.

Task 9a of plans/backlog.md, sharpened in
plans/tasks/09a-application-server-and-http-api.md.

Everything here drives the app through ``app.test_client()``. **No test binds a
socket, starts a thread or opens a port**, so nothing in this file can hang the suite
or collide with a port already in use.

Every account is made with cheap scrypt parameters, injected into ``create_app`` the
same way tasks 7 and 9 inject them into ``sign_up``: no test runs the memory-hard KDF
at production cost.

Paths are resolved from this file, never from the current working directory.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

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
    assert web._MEMBER_OPTIONAL_ENDPOINTS == (
        "signup",
        "create_session",
        "read_session",
        "delete_session",
    )
    assert set(web._MEMBER_OPTIONAL_ENDPOINTS) < web._API_ENDPOINTS


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
