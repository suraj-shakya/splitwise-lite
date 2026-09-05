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

## Set up the group

The roster is a file a person edits, not a screen. Copy the committed example, put your
flat's real names in it, and apply it:

    cp group.example.toml group.toml
    uv run python scripts/setup_group.py apply --store ledger.sqlite3 --definition group.toml

Re-running that command is safe: it writes nothing when nothing changed, adds a name the
file gained, and refuses a name the file lost rather than deleting a member.

`group.toml` and the ledger file are not committed. `group.example.toml` is, so the
shape of the file cannot rot.

A member exists before that person has an account, and that is the normal state of a
fresh flat. Nothing connects the two on its own, because a signup address is unverified;
when someone has signed up, connect them by hand:

    uv run python scripts/setup_group.py link --store ledger.sqlite3 --email sam@example.com --member-name Sam

`show` prints the group and its roster, with no addresses in the output:

    uv run python scripts/setup_group.py show --store ledger.sqlite3

Setup sends nothing. There is no invite, no email and no notification: it writes to the
database and prints what it did.

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
