# Splitwise Lite

Shared expense ledger for small groups. Python back end; the mobile web front end is
not built yet.

## Commands

- Install deps: `uv sync` (project-local `.venv`, host Python stays untouched)
- Run tests: `uv run python -m pytest`
- Run the app: nothing to run yet. Task 8 adds the web shell; update this line then.

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
- `tests/`: the pytest suite

Read the spec before changing behaviour. Read the backlog before starting a task.
