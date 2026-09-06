# Splitwise Lite

Shared expense ledger for small groups. A Python back end, plus an installable mobile
web shell in `app/` whose three screens read the ledger from the JSON API, behind a
sign-in gate.

## What works today

All of it needs a group applied with `scripts/setup_group.py apply` and an account
linked to a member row with `setup_group.py link`. Signing up on its own grants
nothing: the app shows the "nobody has linked you" notice and no ledger.

- **Sign in**: create an account, sign in, sign out. An account that no member row is
  linked to is told so and shown no ledger.
- **The expense feed**: every expense the group has recorded, newest first, with payer,
  amount, description and who shared it. A row expands in place to each person's share,
  the total, who recorded it and when. Read only.
- **Adding an expense**: an amount, an optional description, a payer from the roster and
  one of the spec's three split modes, equally, some people or uneven amounts. The
  resolver's weight mode is reachable through the API and no screen offers it.
- **Balances**: each member's net position and the shortest list of payments that
  clears the group, worked out on every read and never stored. The net figures are read
  only; the payments are not, see below.
- **Transfer drill-down**: a suggested payment opens on the debts it absorbs, from both
  ends, and each of those debts opens in turn on the expenses and settlements behind it.
  The debts arrive with the balances read; what sits behind a debt is fetched on that
  row's first expansion, over `GET /api/debts/{debtor}/{creditor}`. A payment whose
  payload carries no usable provenance is drawn inert rather than as a control that
  answers nothing.
- **Install and open offline**: it installs to the home screen and the shell opens
  offline, on `localhost` or `127.0.0.1` only. The API is never cached, so offline the
  app opens and then reports that it cannot reach the server, and an expense cannot be
  recorded until it can.

## What does not exist yet

These are planned in `plans/backlog.md` and absent from the app. Both lists here are
pinned to a literal in `tests/test_web_shell.py`, so a capability claimed in one of them
and not recorded there turns the suite red, and so does editing this file and leaving
`README.md` alone. What the suite notices when one of these is actually *built* varies by
capability and is recorded entry by entry in that literal. Read your entry's reason there
before trusting the suite to catch you; none of it moves the bullet for you.

- **Mark as paid** (backlog task 14): nothing records that a payment happened.
- **Receiver confirmation** (backlog task 15): and so nothing confirms one, which means
  a debt that has been settled in real life stays on the list until somebody records the
  expense side of it. The two go together, because a balance moves only when the
  receiver confirms.
- **The incompleteness signal** (backlog task 16): nothing says how stale the ledger is
  or who has logged nothing. The balances screen's standing note, that the figures come
  only from what was recorded, is the whole of what the app says about it.
- **Expense correction** (backlog task 17): an expense cannot be edited or voided from
  any screen.

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
- `scripts/`: the dev server, the icon generator and the group setup command, none of
  them needing more than the standard library and the package itself, plus
  `watch-issues.sh`, a bash loop that hands new bug issues to `claude` and wants `gh`
- `group.example.toml`: the shape of the roster `setup_group.py` applies. The real
  `group.toml` and the ledger file are not committed
- `tests/`: the pytest suite

Read the spec before changing behaviour. Read the backlog before starting a task.
