"""What `scripts/serve.py` is, rather than what it serves.

Task 9a rewrote the script to start the Flask application, so the response-level
tests that used to live here moved into `tests/test_web_api.py` and are restated
there through `app.test_client()`. Nothing was dropped: the content types, the
no-store header, the PNG signature and the 404 are all asserted there, against the
same application this script runs.

**Nothing here binds a socket, starts a thread or opens a port.** The old fixture
started a real server on port 0 in a daemon thread; it does not need to, because the
one thing that needed a real server was the response, and the test client exercises
the whole request path without one.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def load_script(name: str) -> ModuleType:
    """Import a file from `scripts/`, which is not a package."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def serve() -> ModuleType:
    # Importing the script must bind nothing and open nothing: every side effect this
    # file has happens inside main().
    return load_script("serve")


def test_the_server_binds_loopback_only(serve: ModuleType) -> None:
    # A LAN address is not a secure context, so a service worker and installability
    # would silently fail there. It is also the only thing containing a session
    # cookie that travels over plain HTTP.
    assert serve.HOST == "127.0.0.1"
    assert serve.DEFAULT_PORT == 8000


def test_the_app_directory_is_found_from_the_script_not_the_working_directory(
    serve: ModuleType,
) -> None:
    assert serve.APP_DIR == REPO / "app"
    assert (serve.APP_DIR / "index.html").is_file()


def test_importing_the_script_binds_nothing_and_opens_nothing(
    serve: ModuleType, tmp_path: Path
) -> None:
    # The module holds definitions and constants, and no live object at all.
    assert not any(name in {"server", "connection", "store"} for name in vars(serve))
    assert callable(serve.make_app)
    assert callable(serve.main)
    assert not (tmp_path / "ledger.sqlite3").exists()


def test_make_app_returns_a_flask_app_pointed_at_the_shell(
    serve: ModuleType, tmp_path: Path
) -> None:
    import flask

    app = serve.make_app(tmp_path / "ledger.sqlite3")
    assert isinstance(app, flask.Flask)
    assert app.config["APP_DIR"] == serve.APP_DIR
    assert app.config["STORE_PATH"] == tmp_path / "ledger.sqlite3"


def test_the_development_server_never_sets_the_secure_flag(
    serve: ModuleType, tmp_path: Path
) -> None:
    # Safe only because it binds loopback. A deployment behind TLS passes True, and
    # nothing derives this from the request scheme or an environment variable.
    app = serve.make_app(tmp_path / "ledger.sqlite3")
    assert app.config["SECURE_COOKIES"] is False


def test_the_store_argument_is_required_and_has_no_default(serve: ModuleType) -> None:
    parsed = serve.build_parser().parse_args(["--store", "ledger.sqlite3"])
    assert parsed.store == "ledger.sqlite3"
    with pytest.raises(SystemExit):
        serve.build_parser().parse_args([])


def test_a_missing_store_is_argparses_own_usage_error(
    serve: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        serve.main([])
    assert raised.value.code == 2
    assert "--store" in capsys.readouterr().err


def test_the_port_is_optional_and_defaults_to_the_constant(serve: ModuleType) -> None:
    parsed = serve.build_parser().parse_args(["--store", "ledger.sqlite3"])
    assert parsed.port == serve.DEFAULT_PORT
    chosen = serve.build_parser().parse_args(["--store", "ledger.sqlite3", "9001"])
    assert chosen.port == 9001


def test_no_path_is_read_from_the_environment_and_no_directory_is_created(
    serve: ModuleType,
) -> None:
    # Read as code, so the docstring may say the script reads no environment
    # variable without that sentence being mistaken for one that does.
    import ast

    source = (SCRIPTS / "serve.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported |= {
        node.module.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
    }
    assert "os" not in imported
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & {"mkdir", "makedirs", "getenv", "environ"}


def test_a_store_that_cannot_be_opened_is_one_sentence_and_exit_one(
    serve: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # No traceback: a stack trace tells an operator nothing a sentence could not.
    missing = tmp_path / "no-such-directory" / "ledger.sqlite3"
    assert serve.main(["--store", str(missing)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("serve.py: error: ")
    assert "Traceback" not in captured.err
    assert not missing.exists()


def test_the_debugger_and_the_reloader_are_switched_off_explicitly(
    serve: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Werkzeug debugger is a remote code execution console. This asserts the
    # arguments the script actually passes, not the text of the file.
    seen: dict[str, object] = {}
    store_path = tmp_path / "ledger.sqlite3"
    app = serve.make_app(store_path)

    monkeypatch.setattr(serve, "make_app", lambda _: app)
    monkeypatch.setattr(
        type(app), "run", lambda self, **keywords: seen.update(keywords)
    )
    assert serve.main(["--store", str(store_path)]) == 0
    assert seen == {
        "host": "127.0.0.1",
        "port": serve.DEFAULT_PORT,
        "debug": False,
        "use_reloader": False,
        "threaded": True,
    }


def test_it_says_it_is_a_development_server_and_names_the_url(
    serve: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_path = tmp_path / "ledger.sqlite3"
    app = serve.make_app(store_path)
    monkeypatch.setattr(serve, "make_app", lambda _: app)
    monkeypatch.setattr(type(app), "run", lambda self, **keywords: None)
    assert serve.main(["--store", str(store_path)]) == 0
    printed = capsys.readouterr().out
    assert "http://localhost:8000" in printed
    assert "development server" in printed
    assert "not for production" in printed
    # One line saying the cookie is sent without Secure, because loopback is the
    # whole of what makes that safe.
    assert "without Secure" in printed


def test_argparse_is_the_only_argument_parser(serve: ModuleType) -> None:
    assert isinstance(serve.build_parser(), argparse.ArgumentParser)
