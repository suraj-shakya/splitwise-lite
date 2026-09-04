# Splitwise Lite

Shared expense ledger for small groups. A Python back end, plus an installable mobile
web shell in `app/` whose three screens are still placeholders.

## Commands

- Install deps: `uv sync` (project-local `.venv`, host Python stays untouched)
- Run tests: `uv run python -m pytest`
- Run the app: `uv run python scripts/serve.py`, then open `http://localhost:8000`

There is no build step and no npm: the files in `app/` are what the browser runs. An
edit to one of the eight shell files will not show on reload, though, because
`app/sw.js` precaches them and serves them from its cache: bump `VERSION` in
`app/sw.js` and reload, or unregister the worker (DevTools, Application, Service
Workers, Unregister).

Reach the app on `localhost` or `127.0.0.1` only. A LAN address is not a secure context,
so the service worker will not register there and the app will not offer to install.

`uv run pytest` fails on this machine with an access-denied spawn error, so use
`uv run python -m pytest`.

## Money

Money is always integer cents, never floats. Amounts are parsed to cents at the input
edge and formatted back only for display. Split remainders are assigned by a
deterministic rule so allocations always sum exactly to the total.

## Dependencies

Dependencies are added to `pyproject.toml` deliberately, then installed with `uv sync`.
Never run `pip install` or `uv pip install` ad hoc: it puts the lockfile and the venv
out of step with the declared project. Dev-only tools go in the `dev` group.

## Where things live

- `plans/spec.md`: what the product is, what is in and out of scope, open questions
- `plans/backlog.md`: numbered tasks, dependencies, build order
- `src/splitwise_lite/`: the package
- `app/`: the static front end shell, served as plain files and never imported by
  the package
- `scripts/`: the dev server and the icon generator, standard library only
- `tests/`: the pytest suite

Read the spec before changing behaviour. Read the backlog before starting a task.
