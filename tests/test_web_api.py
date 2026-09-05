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
