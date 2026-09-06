# Splitwise Lite

A shared expense ledger for small groups. See `plans/spec.md` for scope and
`plans/backlog.md` for the build order.

Status: the domain layer is under way, and one process now serves the mobile web
shell and a JSON API on the same origin. You can sign up, sign in and be told who you
are. The three screens are still placeholders: they show no expenses, no members and
no balances, because tasks 10, 11 and 12 fill them.

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

    uv run python scripts/serve.py --store ledger.sqlite3

Then open `http://localhost:8000`. `--store` is required and has no default; the
optional second argument is a port. One process serves both halves: the shell in
`app/` and the JSON API under `/api`, on the same origin.

It is a development server bound to `127.0.0.1`, not a production one. There is no
TLS, so the session cookie is sent without `Secure`, and loopback is the whole of what
makes that safe.

Sign up on the gate the app shows, then ask whoever set the flat up to link your
account to your name with `setup_group.py link`. Until they do, the app says so and
shows no ledger: signing up on its own grants nothing.

There is no build step and no npm: `scripts/serve.py` serves the plain files in
`app/`. An edit to one of the nine shell files will not show on reload, though,
because `app/sw.js` precaches them and serves them from its cache: to pick the change
up locally, bump `VERSION` in `app/sw.js` and reload. Committing is a different
matter, and `VERSION` is not what you bump. `app/sw.js` also records `SHELL_DIGEST`,
a digest of those nine files, and its cache is named after `VERSION` and that digest
together, so a change that would have shipped behind a stale cache fails a test
instead, and the test prints the one line to paste back into `app/sw.js`. That pasted
line is the whole fix; `VERSION` is left for a change to how the worker itself
behaves. The worker never caches `/api`.

To clear a worker that is stuck entirely, open DevTools, Application, Service Workers,
and press Unregister, then reload.

Use `localhost` or `127.0.0.1`, not a LAN address. Only those two are secure contexts,
and without one the service worker will not register and the app will not offer to
install.

## Test

    uv run python -m pytest

That one command runs both halves. The JavaScript half needs `node` 20 or later on
`PATH`: `tests/shell_harness.mjs` runs the files in `app/` under Node's built-in `vm`
and asserts what a person would see on the screen. There is still no npm and no
`node_modules`. Without `node` the suite fails and says so, rather than quietly
skipping the half it cannot run.

`.github/workflows/tests.yml` runs `uv sync --locked` and then that same command on
`ubuntu-latest` and on `windows-latest` for every push to `master` and every pull
request; both legs must be green before a merge, and a pull request whose base has
moved must be brought up to date so the checks re-run against the new merge commit
rather than reporting a result computed against an older one.
