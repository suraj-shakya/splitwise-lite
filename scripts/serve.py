"""Run Splitwise Lite: the shell in `app/` and the JSON API, from one process.

    uv run python scripts/serve.py --store ledger.sqlite3

This is the one way to run the product. There is no second, static-only server: the
shell calls the API now, so a server that could not answer it would serve a broken app
while its own tests passed.

**A development server, and not for production.** Werkzeug's server is what runs here,
it binds `127.0.0.1` and nothing else, and it sends the session cookie without
`Secure` because there is no TLS in front of it. `create_app` returns a plain WSGI
application any server can mount, and choosing one is a deployment task.

**No path is guessed.** `--store` is required, has no default, reads no environment
variable and is handed to `open_store` exactly as typed. No directory is created,
matching `scripts/setup_group.py`.

**`app/` is resolved from this file**, never from the working directory, so the same
files are served however the command was invoked.

Every `DomainError` raised on the way up, such as a store that cannot be opened, is
caught here: the message goes to standard error and the process exits 1, with no
traceback, because a stack trace tells an operator nothing a sentence could not.
argparse reports a usage error itself and exits 2.

Nothing runs at import time beyond these definitions: no socket is bound and no store
is opened until `main` runs.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from flask import Flask

from splitwise_lite import DomainError, open_store
from splitwise_lite.web import create_app

PROGRAM = "serve.py"
"""The name argparse reports, so usage text is the same however the file is invoked."""

APP_DIR = Path(__file__).resolve().parent.parent / "app"  # relative to this file

HOST = "127.0.0.1"  # loopback is a secure context; a LAN address is not, and a
# service worker would silently refuse to register there. It is also the only thing
# containing a session cookie that travels over plain HTTP.

DEFAULT_PORT = 8000


def build_parser() -> argparse.ArgumentParser:
    """The whole command line. Built here so a test can read it without running it.

    `--store` has no default and reads no environment variable: an operator who has to
    type the path cannot serve the wrong database by inheriting one.
    """
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Serve the shell and the JSON API on http://localhost:8000. A "
            "development server bound to loopback, not a production one."
        ),
    )
    parser.add_argument(
        "--store",
        required=True,
        help="path to the SQLite ledger, passed to open_store unchanged",
    )
    parser.add_argument(
        "port",
        nargs="?",
        type=int,
        default=DEFAULT_PORT,
        help=f"port to serve on (default {DEFAULT_PORT})",
    )
    return parser


def make_app(store_path: str | Path) -> Flask:
    """Build the application this script serves, without starting anything.

    `secure_cookies=False` is stated rather than defaulted, because there is no
    default: a deployment behind TLS passes `True`, and a control that quietly turns
    itself off is worse than one that is off on purpose. It is safe here only because
    `main` binds loopback.
    """
    return create_app(store_path=store_path, secure_cookies=False, app_dir=APP_DIR)


def main(argv: Sequence[str] | None = None) -> int:
    """Serve until interrupted and return the process exit status.

    0 on a clean stop, 1 for any `DomainError`, whose message goes to standard error
    with no traceback. argparse exits 2 itself on a usage error, before this ever sees
    the arguments.
    """
    arguments = build_parser().parse_args(argv)
    try:
        # Opened and closed once, so an unusable path is a sentence now rather than a
        # 500 on the first request. The app opens its own store per request.
        with open_store(arguments.store):
            pass
        app = make_app(arguments.store)
    except DomainError as error:
        print(f"{PROGRAM}: error: {error}", file=sys.stderr)
        return 1

    print(f"Serving {APP_DIR} and the API on http://localhost:{arguments.port}")
    print(f"Ledger: {arguments.store}")
    # Flushed, so the URL appears even when the output is piped to a log.
    print(
        "This is a development server bound to 127.0.0.1 and is not for production: "
        "there is no TLS, so cookies are sent without Secure.",
        flush=True,
    )
    try:
        # Every one of these is passed on purpose. The Werkzeug debugger is a remote
        # code execution console, and the reloader would run this file twice.
        app.run(
            host=HOST,
            port=arguments.port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":  # binding happens here, never at import time
    raise SystemExit(main())
