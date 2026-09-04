"""Serve the static shell in `app/` for development.

    uv run python scripts/serve.py [port]

Standard library only, and nothing here imports `splitwise_lite`. It exists because
Python's `mimetypes` consults the Windows registry, where `.js` is commonly mapped
to `text/plain`; browsers enforce a JavaScript MIME type on service worker scripts
strictly, so a bare `python -m http.server` can leave the worker unregistered and
the app uninstallable on exactly the machine this project is developed on. The map
below pins the types instead of guessing them.

`uv run python -m http.server -d app 8000` serves the same directory and is fine for
layout work; it just cannot be relied on to register the worker.
"""

from __future__ import annotations

import functools
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"  # relative to this file
HOST = "127.0.0.1"  # loopback is a secure context; a LAN address is not, and a
# service worker would silently refuse to register there
DEFAULT_PORT = 8000

EXTENSIONS = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
    ".ico": "image/vnd.microsoft.icon",
}


class ShellHandler(SimpleHTTPRequestHandler):
    """Static files with pinned content types and no caching at all."""

    extensions_map = EXTENSIONS

    def end_headers(self) -> None:
        # No caching, so a stale browser cache never masks an edit.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def make_server(port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Build the server without starting it, so a test can drive it."""
    handler = functools.partial(ShellHandler, directory=str(APP_DIR))
    return ThreadingHTTPServer((HOST, port), handler)


def main(argv: list[str] | None = None) -> None:
    arguments = sys.argv[1:] if argv is None else argv
    port = int(arguments[0]) if arguments else DEFAULT_PORT
    server = make_server(port)
    # Flushed, so the URL appears even when the output is piped to a log.
    print(f"Serving {APP_DIR} on http://localhost:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":  # binding happens here, never at import time
    main()
