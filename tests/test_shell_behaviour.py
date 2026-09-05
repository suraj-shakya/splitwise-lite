"""pytest's half of the JavaScript suite: it drives ``tests/shell_harness.mjs``.

The harness runs the shipped ``app/index.html``, ``app/app.js`` and ``app/api.js``
under Node's built-in ``vm`` against a stubbed DOM and a stubbed ``fetch``, and
reports one JSON object on stdout. It runs **once per session**, through the
session-scoped fixture below, and every scenario it reports becomes its own pytest
result, so a failure reads as ``test_scenario[a_refused_sign_in_tells_the_person_why]``
and carries the harness's own message rather than one opaque "node exited 1".

``node`` is a test-time requirement of this repo, named in CLAUDE.md. **A missing or
too old ``node`` is a failure, never a skip**: `.claude/rules/testing.md` forbids
skipping or xfailing a test to make the suite green, and a JavaScript suite that
silently evaporates on a machine without the runtime is that same failure wearing a
hat.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "tests" / "shell_harness.mjs"

NODE_MISSING = (
    "node is not on PATH. tests/shell_harness.mjs runs the shipped app/ files under "
    "Node's vm, and CLAUDE.md names node 20 or later as a test-time requirement of "
    "this repo. Install it: this suite fails without it and never skips."
)

# Every scenario the harness runs, in the order it runs them. The harness reports
# exactly this list back, so a scenario deleted from the harness fails pytest and one
# added to the harness without being declared here fails pytest too.
SCENARIOS = [
    "boot_with_no_session_shows_the_gate",
]


def node() -> str:
    """The resolved interpreter path, passed as argv[0] so the subprocess does not
    depend on Windows resolving `node` through PATHEXT."""
    found = shutil.which("node")
    assert found is not None, NODE_MISSING
    return found


def run_harness(
    config: dict[str, Any], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """One harness run. The configuration goes in as JSON on stdin, so the mutant text
    lives in this file where a reviewer reads it, not buried in the harness."""
    argv = [node(), str(HARNESS)]
    try:
        return subprocess.run(
            argv,
            input=json.dumps(config),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
            cwd=None if cwd is None else str(cwd),
        )
    except subprocess.TimeoutExpired as expired:
        stderr = expired.stderr or ""
        if isinstance(stderr, bytes):  # pragma: no cover - text=True gives str
            stderr = stderr.decode("utf-8", "replace")
        pytest.fail(
            "tests/shell_harness.mjs did not finish within 60 seconds.\n"
            f"stderr:\n{stderr}"
        )


def parse_report(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """The report, or one readable pytest failure. Never a JSONDecodeError traceback:
    the exit status and stderr are what say what went wrong."""
    if completed.returncode != 0:
        pytest.fail(
            f"tests/shell_harness.mjs exited {completed.returncode}.\n"
            f"stderr:\n{completed.stderr}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"tests/shell_harness.mjs exited {completed.returncode} but its stdout is "
            f"not JSON.\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


@pytest.fixture(scope="session")
def harness_run() -> subprocess.CompletedProcess[str]:
    """One process for the whole session, against the unmodified files."""
    return run_harness({})


@pytest.fixture(scope="session")
def report(harness_run: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return parse_report(harness_run)


def results(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["name"]: entry for entry in report["scenarios"]}


def test_node_is_installed_and_recent_enough() -> None:
    found = shutil.which("node")
    assert found is not None, NODE_MISSING
    completed = subprocess.run(
        [found, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    reported = completed.stdout.strip()
    assert reported.startswith("v"), reported
    major = int(reported[1:].split(".")[0])
    assert major >= 20, (
        f"node {reported} is too old. tests/shell_harness.mjs targets node 20 or "
        "later, which CLAUDE.md names as a test-time requirement of this repo."
    )


def test_the_harness_exits_zero_against_the_shipped_files(
    harness_run: subprocess.CompletedProcess[str],
) -> None:
    assert harness_run.returncode == 0, harness_run.stderr


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario(report: dict[str, Any], name: str) -> None:
    found = results(report)
    assert name in found, f"tests/shell_harness.mjs did not run {name}"
    entry = found[name]
    assert entry["passed"], "\n".join([f"{name} failed:", *entry["failures"]])


def test_the_harness_reports_exactly_the_declared_scenarios(
    report: dict[str, Any],
) -> None:
    assert [entry["name"] for entry in report["scenarios"]] == SCENARIOS
