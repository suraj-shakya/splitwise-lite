# Splitwise Lite

A shared expense ledger for small groups. See `plans/spec.md` for scope and
`plans/backlog.md` for the build order.

Status: task 1 of the backlog. Skeleton only, no product code yet.

## Setup

Requires [uv](https://docs.astral.sh/uv/). Dependencies install into a project-local
`.venv`, so the host Python is never touched.

    uv sync

## Test

    uv run python -m pytest
