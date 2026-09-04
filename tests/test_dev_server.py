"""Real responses from `scripts/serve.py`.

The server is started on port 0 on 127.0.0.1 in a daemon thread and shut down in
fixture teardown, so a failure here cannot hang the suite. Nothing in this file
imports `splitwise_lite`: the shell is independent of the domain layer.
"""

from __future__ import annotations

import importlib.util
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.client import HTTPResponse
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


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    # Importing the script must not bind anything: the bind happens here, on a
    # port the operating system picks.
    serve = load_script("serve")
    server = serve.make_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get(url: str) -> HTTPResponse:
    return urllib.request.urlopen(url, timeout=5)


def test_the_server_binds_loopback_only() -> None:
    # A LAN address is not a secure context, so a service worker and installability
    # would silently fail there. Exposing one would only invite that confusion.
    serve = load_script("serve")
    assert serve.HOST == "127.0.0.1"
    assert serve.DEFAULT_PORT == 8000


def test_the_app_directory_is_found_from_the_script_not_the_working_directory() -> None:
    serve = load_script("serve")
    assert serve.APP_DIR == REPO / "app"
    assert (serve.APP_DIR / "index.html").is_file()


def test_the_root_serves_the_shell_document(base_url: str) -> None:
    response = get(base_url + "/")
    assert response.status == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert b"<!doctype html>" in response.read()


def test_the_router_is_served_as_javascript(base_url: str) -> None:
    # Python's mimetypes reads the Windows registry, where .js is commonly mapped to
    # text/plain. Browsers enforce a JavaScript type on a worker script strictly, so
    # guessing here would leave the app uninstallable on this very machine.
    response = get(base_url + "/app.js")
    assert response.status == 200
    assert response.headers["Content-Type"] == "text/javascript; charset=utf-8"


def test_the_worker_is_served_as_javascript(base_url: str) -> None:
    response = get(base_url + "/sw.js")
    assert response.status == 200
    assert response.headers["Content-Type"] == "text/javascript; charset=utf-8"


def test_the_manifest_is_served_as_json(base_url: str) -> None:
    response = get(base_url + "/manifest.json")
    assert response.status == 200
    assert response.headers["Content-Type"] == "application/json"


def test_a_webmanifest_extension_would_also_be_served_correctly() -> None:
    # The file is named .json, and the map covers .webmanifest anyway, so the
    # directory stays servable by anything.
    serve = load_script("serve")
    assert serve.EXTENSIONS[".webmanifest"] == "application/manifest+json"
    assert set(serve.EXTENSIONS) >= {
        ".html",
        ".css",
        ".js",
        ".json",
        ".webmanifest",
        ".png",
        ".ico",
    }


def test_an_icon_is_served_as_a_png(base_url: str) -> None:
    response = get(base_url + "/icons/icon-192.png")
    assert response.status == 200
    assert response.headers["Content-Type"] == "image/png"
    assert response.read()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize(
    "path",
    ["/", "/app.js", "/sw.js", "/manifest.json", "/icons/icon-192.png", "/styles.css"],
)
def test_nothing_is_cached_during_development(base_url: str, path: str) -> None:
    # A stale browser cache must never mask an edit while the shell is being built.
    assert get(base_url + path).headers["Cache-Control"] == "no-store"


def test_a_missing_path_is_a_404(base_url: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as raised:
        get(base_url + "/nothing-here.txt")
    assert raised.value.code == 404
    assert raised.value.headers["Cache-Control"] == "no-store"
