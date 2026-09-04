# Splitwise Lite

A shared expense ledger for small groups. See `plans/spec.md` for scope and
`plans/backlog.md` for the build order.

Status: the domain layer is under way and the mobile web shell runs. The shell's
three screens are placeholders: it shows no expenses, no members and no balances,
because nothing is wired to the domain layer yet.

## Setup

Requires [uv](https://docs.astral.sh/uv/). Dependencies install into a project-local
`.venv`, so the host Python is never touched.

    uv sync

## Run the app

    uv run python scripts/serve.py

Then open `http://localhost:8000`. The optional first argument is a port. There is no
build step and no npm: `scripts/serve.py` serves the plain files in `app/`. An edit to
one of the eight shell files will not show on reload, though, because `app/sw.js`
precaches them and serves them from its cache: bump `VERSION` in `app/sw.js` and reload
to pick the change up.

To clear a worker that is stuck entirely, open DevTools, Application, Service Workers,
and press Unregister, then reload.

Use `localhost` or `127.0.0.1`, not a LAN address. Only those two are secure contexts,
and without one the service worker will not register and the app will not offer to
install.

## Test

    uv run python -m pytest
