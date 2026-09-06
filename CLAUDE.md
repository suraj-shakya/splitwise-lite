# Splitwise Lite

Shared expense ledger for small groups. A Python back end, plus an installable mobile
web shell in `app/` whose three screens are still placeholders.

## Commands

- Install deps: `uv sync` (project-local `.venv`, host Python stays untouched)
- Run tests: `uv run python -m pytest`
- Run the app: `uv run python scripts/serve.py --store ledger.sqlite3`, then open `http://localhost:8000`. `--store` is required and has no default. It serves `app/` and the JSON API from one process, binds `127.0.0.1` only, and is a development server, not a production one
- Set up the group: `uv run python scripts/setup_group.py apply --store PATH --definition group.toml`; safe to re-run. `link` connects a signed-up account to a
  member row, `show` prints the roster

There is no build step and no npm: the files in `app/` are what the browser runs. An
edit to one of the nine shell files will not show on reload, though, because
`app/sw.js` precaches them and serves them from its cache: to see your edit locally,
bump `VERSION` in `app/sw.js` and reload, or unregister the worker (DevTools,
Application, Service Workers, Unregister). Committing is a different matter, and
`VERSION` is not what you bump. `app/sw.js` also records `SHELL_DIGEST`, a digest of
those nine files, and names its cache after `VERSION` and that digest together, so a
shipped edit that would have sat behind a cache nobody retired is a failing test
rather than a silent regression, and the test prints the one line to paste back into
`app/sw.js`. That pasted line is the whole fix; `VERSION` is left for a change to how
the worker itself behaves. The worker never caches `/api`, so data is never stale
behind it.

Reach the app on `localhost` or `127.0.0.1` only. A LAN address is not a secure context,
so the service worker will not register there and the app will not offer to install.

`uv run pytest` fails on this machine with an access-denied spawn error, so use
`uv run python -m pytest`.

`.github/workflows/tests.yml` runs `uv sync --locked` and then that same command on
`ubuntu-latest` and on `windows-latest` for every push to `master` and every pull
request. Both legs must be green before a merge. A pull request whose base has moved
has to be brought up to date and re-run, because a result computed against an older
`master` says nothing about the merge commit, and the merge commit is where a stale
shell digest surfaces.

The suite has a JavaScript half, so `node` 20 or later on `PATH` is a test-time
requirement of this repo. `tests/shell_harness.mjs` runs the real `app/index.html`,
`app/app.js` and `app/api.js` under Node's built-in `vm`, against a stubbed DOM and a
stubbed `fetch`, and pytest drives it, so `uv run python -m pytest` is still the one
test command and one failure list covers both languages. There is still no npm, no
`package.json` and no `node_modules`: the harness imports `node:vm`, `node:fs`,
`node:path` and `node:url` and nothing else. A missing `node` fails the suite, loudly,
and is never skipped.

## Money

Money is always integer cents, never floats. Amounts are parsed to cents at the input
edge and formatted back only for display. Split remainders are assigned by a
deterministic rule so allocations always sum exactly to the total.

## Dependencies

Dependencies are added to `pyproject.toml` deliberately, then installed with `uv sync`.
Never run `pip install` or `uv pip install` ad hoc: it puts the lockfile and the venv
out of step with the declared project. Dev-only tools go in the `dev` group.

Flask is the one runtime dependency, and it is a dependency of
`src/splitwise_lite/web.py` and of nothing else. The store is synchronous `sqlite3`
and every domain function is a blocking call, so a threaded, synchronous WSGI app is
the shape that matches what already exists. The domain layer stays framework free and
imports with Flask absent, which is what keeps that choice reversible; a test asserts
it.

## Where things live

- `plans/spec.md`: what the product is, what is in and out of scope, open questions
- `plans/backlog.md`: numbered tasks, dependencies, build order
- `src/splitwise_lite/`: the package
- `src/splitwise_lite/web.py`: the HTTP layer. The one module that imports a web
  framework, and the one place that decides cookies, CSRF, rate limiting and what a
  `DomainError` becomes on the wire. Routes are declared in `_API_ROUTES` with the
  access each one requires, and an app whose route map holds anything the tables do
  not declare fails to build
- `app/`: the front end shell, served as plain files and never imported by the
  package. `app/api.js` is the only file in it that calls the back end
- `scripts/`: the dev server, the icon generator and the group setup command; no
  dependency beyond the standard library and the package itself
- `group.example.toml`: the shape of the roster `setup_group.py` applies. The real
  `group.toml` and the ledger file are not committed
- `tests/`: the pytest suite

Read the spec before changing behaviour. Read the backlog before starting a task.
