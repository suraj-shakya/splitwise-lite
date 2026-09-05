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
    # Boot
    "boot_with_no_session_shows_the_gate",
    "boot_with_a_linked_session_shows_the_app",
    "nothing_from_the_previous_scenario_survives_into_this_one",
    "boot_with_an_unlinked_session_shows_the_not_linked_message",
    "a_403_member_not_linked_shows_the_not_linked_message",
    "a_network_failure_shows_the_offline_message_and_never_the_gate",
    "a_server_error_is_the_same_screen_as_being_offline",
    "the_api_client_failing_to_load_shows_the_offline_message",
    # Signing in
    "a_refused_sign_in_tells_the_person_why",
    "a_refused_sign_in_with_an_unreadable_body_still_says_something",
    "a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone",
    "a_successful_sign_in_keeps_the_screen_the_person_was_on",
    "a_session_that_dies_between_sign_in_and_session_read_returns_to_the_gate",
    "creating_an_account_signs_in_straight_after",
    "the_gate_switches_the_password_autocomplete_with_the_mode",
    "the_form_never_lets_the_browser_navigate",
    "the_email_is_trimmed_and_the_password_is_not",
    "signing_out_returns_to_the_gate",
    # Routing
    "an_unknown_hash_is_replaced_not_pushed",
]

# The two mutants the harness is measured against, as anchored substitutions applied
# to the real source at run time. Neither is a committed copy of a shipped file, so
# neither can rot into a false pass or be served to a browser by accident, and the
# text lives here where a reviewer reads it rather than buried in the harness.
#
# Mutant A: show() also hides the gate error. A one-line tidy of the kind a later
# screen task makes, and it looks like an improvement, because every other
# curtain-switching concern already lives in show(). submitted() writes the message,
# reveals it, then calls show('gate'), which now hides it again.
MUTANT_A = {
    "file": "app/app.js",
    "find": "gate.hidden = which !== 'gate';",
    "replace": "gate.hidden = which !== 'gate';\n    gateError.hidden = true;",
}
# Mutant B: the 401 handler is deferred to a macrotask, so submitted()'s catch writes
# the message first and the deferred showGate('') blanks it afterwards. app/app.js is
# untouched entirely, and this is only visible once the timer queue has drained.
MUTANT_B = {
    "file": "app/api.js",
    "find": "handlers.unauthenticated(error);",
    "replace": "setTimeout(function () { handlers.unauthenticated(error); }, 0);",
}

REFUSED = "a_refused_sign_in_tells_the_person_why"
# Named, and unrelated to either mutation: a mutant has to leave a working app with
# one specific behaviour broken, not a smoking crater.
UNRELATED = "an_unknown_hash_is_replaced_not_pushed"


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
    if harness_run.returncode != 0:
        pytest.fail(
            f"tests/shell_harness.mjs exited {harness_run.returncode}.\n"
            f"stderr:\n{harness_run.stderr}"
        )
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


# --- The two mutants -------------------------------------------------------


def mutated(mutant: dict[str, str]) -> str:
    """The shipped source with the mutation applied, the way the harness applies it."""
    source = (REPO / mutant["file"]).read_text(encoding="utf-8")
    assert source.count(mutant["find"]) == 1, (
        f"the anchor {mutant['find']!r} no longer matches exactly once in "
        f"{mutant['file']}; re-express the mutant rather than weakening it"
    )
    return source.replace(mutant["find"], mutant["replace"])


def loaded_under(mutant: dict[str, str]) -> dict[str, str]:
    """The two sources as the harness loads them under this mutant: the file the
    mutant names, mutated, and the other one exactly as it ships."""
    return {
        name: mutated(mutant)
        if name == mutant["file"]
        else (REPO / name).read_text(encoding="utf-8")
        for name in ("app/app.js", "app/api.js")
    }


def submitted_body(source: str) -> str:
    """The slice the deleted structural test used to read: app.js from
    ``function submitted(`` up to ``function wire(``."""
    start = source.index("function submitted(")
    return source[start : source.index("function wire(", start)]


def killed(mutant: dict[str, str]) -> dict[str, dict[str, Any]]:
    completed = run_harness({"substitutions": [mutant]})
    # Exactly 1, never merely non-zero: a substitution that broke the file into a
    # syntax error exits 2, and would otherwise be mistaken for a killed mutant.
    assert completed.returncode == 1, (
        f"expected exit 1, got {completed.returncode}.\nstderr:\n{completed.stderr}"
    )
    return results(parse_report(completed))


def test_mutant_a_hiding_the_gate_error_in_show_is_killed() -> None:
    found = killed(MUTANT_A)
    assert not found[REFUSED]["passed"]
    messages = " ".join(found[REFUSED]["failures"])
    # The right failure, not a coincidence: it is the gate error that went missing.
    assert "gate-error" in messages, messages
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # The proof the deleted structural test could not have seen it: the one function
    # it read is byte-identical under the mutation.
    shipped = (REPO / "app" / "app.js").read_text(encoding="utf-8")
    loaded = loaded_under(MUTANT_A)
    assert loaded["app/app.js"] != shipped
    assert submitted_body(loaded["app/app.js"]) == submitted_body(shipped)


def test_mutant_b_deferring_the_401_handler_is_killed() -> None:
    found = killed(MUTANT_B)
    assert not found[REFUSED]["passed"]
    messages = " ".join(found[REFUSED]["failures"])
    assert "gate-error" in messages, messages
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # Mutant B lands in app/api.js and leaves app/app.js alone entirely, which is the
    # point: the structural test read the one file this mutation never touches.
    shipped = (REPO / "app" / "app.js").read_text(encoding="utf-8")
    loaded = loaded_under(MUTANT_B)
    assert loaded["app/api.js"] != (REPO / "app" / "api.js").read_text(encoding="utf-8")
    assert loaded["app/app.js"] == shipped
    assert submitted_body(loaded["app/app.js"]) == submitted_body(shipped)
