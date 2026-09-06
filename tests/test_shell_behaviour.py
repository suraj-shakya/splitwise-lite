"""pytest's half of the JavaScript suite: it drives ``tests/shell_harness.mjs``.

The harness runs the shipped ``app/index.html``, ``app/app.js`` and ``app/api.js``
under Node's built-in ``vm`` against a stubbed DOM and a stubbed ``fetch``, and
reports one JSON object on stdout. It runs **once per session**, through the
session-scoped fixture below, and every scenario it reports becomes its own pytest
result, so a failure reads as ``test_scenario[a_refused_sign_in_tells_the_person_why]``
and carries the harness's own message rather than one opaque "node exited 1".

``node`` is a test-time requirement of this repo, named in CLAUDE.md. **A missing or
too old ``node`` is a failure, never a skip**: `.claude/rules/testing.md` forbids
marking a test skipped or expected to fail to make the suite green, and a JavaScript
suite that silently evaporates on a machine without the runtime is that same failure
wearing a hat.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "tests" / "shell_harness.mjs"
APP = REPO / "app"

NODE_MISSING = (
    "node is not on PATH. tests/shell_harness.mjs runs the shipped app/ files under "
    "Node's vm, and CLAUDE.md names node 20 or later as a test-time requirement of "
    "this repo. Install it: this suite fails without it and never skips."
)

# Every scenario the harness runs, in the order it runs them. The harness reports
# exactly this list back, so a scenario deleted from the harness fails pytest and one
# added to the harness without being declared here fails pytest too.
SCENARIOS = [
    # Boot, and what announce() makes of every answer the server can give
    "boot_with_no_session_shows_the_gate",
    "boot_with_a_linked_session_shows_the_app",
    "nothing_from_the_previous_scenario_survives_into_this_one",
    "boot_with_an_unlinked_session_shows_the_not_linked_message",
    "a_403_member_not_linked_shows_the_not_linked_message",
    "a_403_that_is_not_member_not_linked_prints_what_the_server_said",
    "a_network_failure_shows_the_offline_message_and_never_the_gate",
    "a_server_error_prints_what_the_server_said_and_never_the_gate",
    "a_503_naming_the_setup_command_prints_that_sentence",
    "a_503_naming_both_group_ids_prints_both_of_them",
    "a_status_above_five_hundred_nobody_anticipated_is_still_classified",
    "a_status_below_five_hundred_nobody_anticipated_is_not_silently_dropped",
    "a_response_the_client_may_not_read_is_the_same_as_no_answer",
    "a_status_that_is_not_a_number_is_never_taken_for_a_refusal",
    "a_later_failure_does_not_leave_the_earlier_sentence_behind",
    "the_api_client_failing_to_load_shows_the_offline_message",
    # Signing in
    "a_refused_sign_in_tells_the_person_why",
    "a_refused_sign_in_with_an_unreadable_body_still_says_something",
    "a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone",
    "a_successful_sign_in_keeps_the_screen_the_person_was_on",
    "a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate",
    "a_session_that_expires_mid_session_puts_the_server_sentence_on_the_gate",
    "a_sign_in_the_network_interrupted_still_lets_the_gate_come_back",
    "a_session_that_expires_after_a_real_sign_in_still_returns_to_the_gate",
    "a_401_answering_the_sign_in_itself_is_always_the_gate",
    "creating_an_account_signs_in_straight_after",
    "creating_an_account_that_already_exists_says_so_on_the_gate",
    "a_rate_limited_sign_in_reads_on_the_gate_with_no_curtain_over_it",
    "the_submit_control_is_disabled_while_the_sign_in_is_in_flight",
    "the_gate_says_whether_it_is_signing_in_or_creating_an_account",
    "the_gate_switches_the_password_autocomplete_with_the_mode",
    "the_form_never_lets_the_browser_navigate",
    "the_email_is_trimmed_and_the_password_is_not",
    "signing_out_returns_to_the_gate",
    "a_sign_out_the_server_refuses_says_why_rather_than_doing_nothing",
    # Routing
    "routing_shows_one_screen_and_moves_focus",
    "going_back_to_a_screen_reads_it_again",
    "an_unknown_hash_is_replaced_not_pushed",
    # The client
    "every_request_goes_to_the_api_with_credentials",
    "the_csrf_token_is_read_at_request_time_not_cached",
    "a_204_is_not_parsed_as_json",
    "a_refusal_a_screen_asked_for_leaves_the_app_frame_up",
    "the_whole_error_reaches_the_handler_that_registered_for_it",
    "a_rejected_fetch_carries_no_message_of_its_own",
    "a_handler_that_throws_does_not_stop_the_rejection_reaching_the_caller",
    "an_unsupported_selector_is_a_loud_failure_not_a_null",
]

# The three mutants the harness is measured against, as anchored substitutions applied
# to the real source at run time. None is a committed copy of a shipped file, so none
# can rot into a false pass or be served to a browser by accident, and the text lives
# here where a reviewer reads it rather than buried in the harness.
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
# Mutant B: the 401 handler is deferred to a macrotask and blanks the gate when it
# finally runs, so submitted()'s catch writes the message first and the deferred
# showGate() wipes it afterwards. app/app.js is untouched entirely, and this is only
# visible once the timer queue has drained.
#
# Re-expressed by task 32, which changed what the handler is handed. Before it,
# onUnauthenticated always called showGate('') and the bare deferral was enough to
# blank a message the caller had just written. Now the handler is handed error.say and
# prints the server's own sentence, which for a refused sign-in is the same sentence
# submitted() writes, so the two agree and a bare deferral leaves the gate reading
# correctly. Blanking say inside the deferred call restores the pre-task behaviour
# exactly, and the defect it reintroduces is the same one: a message written by the
# caller and wiped by a handler that ran late. The bare deferral is still caught, by
# a_refused_sign_in_with_an_unreadable_body_still_says_something, where there is no
# server sentence for the two writers to agree on.
MUTANT_B = {
    "file": "app/api.js",
    "find": "handlers.unauthenticated(error);",
    "replace": (
        "setTimeout(function () { error.say = ''; "
        "handlers.unauthenticated(error); }, 0);"
    ),
}
# Mutant C: the default arm of the classifier stops classifying. Every status the
# ladder above it did not name comes back as a kind that no handler speaks for, which
# is the fall through task 32 removed: announce() was three ifs and no else, so a 429
# on sign-in and a 409 on signup reached nobody and the screen did not change. This
# mutant is why the default arm has to be a classification and not a shrug.
MUTANT_C = {
    "file": "app/api.js",
    "find": "return 'refused';",
    "replace": "return '';",
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
    """The report, whatever verdict it carries.

    **Exit 1 is not an error here.** It is the harness's normal answer when a scenario
    fails, and it has to flow through to the per-scenario results below: a guard on it
    turns one real defect into an error on every test in this file, all carrying the
    same blob, with the scenario that names the defect indistinguishable from the ones
    that passed. That is worse than no harness at all, and it is the opposite of what
    this file's docstring promises.

    Only a harness error stops the file, and it stops it here because then there is no
    report to read: exit 2, stdout that will not parse, or a timeout, each with its own
    message.
    """
    if harness_run.returncode not in (0, 1):
        pytest.fail(
            f"tests/shell_harness.mjs failed as a harness rather than reporting a "
            f"scenario failure: it exited {harness_run.returncode}.\n"
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


# --- The three mutants -----------------------------------------------------


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


def test_mutant_c_a_classifier_that_drops_what_it_does_not_recognise_is_killed() -> None:
    found = killed(MUTANT_C)
    # The gate is where the fall through was doing its damage: a 429 the server
    # explained reaches nobody, so the person is told nothing and can only try again.
    dropped = "a_rate_limited_sign_in_reads_on_the_gate_with_no_curtain_over_it"
    assert not found[dropped]["passed"]
    messages = " ".join(found[dropped]["failures"])
    assert "gate-error" in messages, messages
    # A working app with one behaviour broken, not a smoking crater: a 401 is claimed
    # by a row above the default, so signing in still works and still says why when it
    # is refused.
    assert found[REFUSED]["passed"], found[REFUSED]["failures"]
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # One file, one line, and app/app.js untouched: the classification lives in the
    # client and nowhere else, so that is the only place a mutation of it can land.
    loaded = loaded_under(MUTANT_C)
    assert loaded["app/app.js"] == (REPO / "app" / "app.js").read_text(encoding="utf-8")


# --- Harness errors, which are exit 2 and not exit 1 -----------------------


def test_an_anchor_that_matches_nothing_refuses_the_run() -> None:
    # An anchor that has rotted must not quietly mutate something else, or fail to
    # mutate anything and report a green run that proved nothing.
    anchor = "gate.hidden = which === 'gate';"
    completed = run_harness(
        {"substitutions": [{"file": "app/app.js", "find": anchor, "replace": "x"}]}
    )
    assert completed.returncode == 2, completed.stderr
    assert completed.stdout == ""
    assert "app/app.js" in completed.stderr
    assert anchor in completed.stderr


def test_an_anchor_that_matches_more_than_once_refuses_the_run() -> None:
    anchor = "document.getElementById("
    completed = run_harness(
        {"substitutions": [{"file": "app/app.js", "find": anchor, "replace": "x("}]}
    )
    assert completed.returncode == 2, completed.stderr
    assert completed.stdout == ""
    assert "app/app.js" in completed.stderr
    assert anchor in completed.stderr


def test_a_run_that_will_not_quiesce_fails_and_names_the_scenario() -> None:
    # settle() is bounded, so a timer that reschedules itself is a harness error with
    # the scenario's name on it rather than a suite that hangs until the pytest run is
    # killed. The provocation is the harness's own, and only when asked for.
    scenario = "boot_with_no_session_shows_the_gate"
    completed = run_harness(
        {"scenarios": [scenario], "provokeRunawayTimer": True}
    )
    assert completed.returncode == 2, completed.stderr
    assert scenario in completed.stderr
    assert "settle" in completed.stderr


# --- api.js is the only place a status is interpreted ----------------------

# A status read in order to be compared, either way round, and a comparison against
# an HTTP status number. `status: 503` in sw.js builds a Response and is neither.
_STATUS_READ = re.compile(
    r"\.\s*status\s*(?:===|!==|==|!=|>=|<=|>|<)"
    r"|(?:===|!==|==|!=|>=|<=|>|<)\s*[A-Za-z_$][\w$]*\.\s*status\b"
    r"|\bswitch\s*\([^)]*\.\s*status\b"
)
_STATUS_NUMBER = re.compile(
    r"(?:===|!==|==|!=|>=|<=|>|<)\s*[1-5][0-9][0-9]\b"
    r"|\b[1-5][0-9][0-9]\s*(?:===|!==|==|!=|>=|<=|>|<)"
)
_JS_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)

# The six kinds classify() answers with. Every one of them is produced there, so a
# classifier cut down to fewer answers is missing some of these.
_KINDS = (
    "offline",
    "signed-out",
    "sign-in-not-kept",
    "not-linked",
    "unavailable",
    "refused",
)


def _without_comments(source: str) -> str:
    return _JS_COMMENTS.sub(" ", source)


def _classifier(source: str) -> str:
    """app/api.js from ``function classify(`` up to the next function after it.

    Sliced rather than searched for whole-file, because the point of the companion
    test below is that the classification is *in the classifier*: a status read in
    `request()` to spot a 204, or in `noted()` to spot a 401, is not classification
    and must not be able to stand in for it.
    """
    start = source.index("function classify(")
    return source[start : source.index("\n  function ", start + 1)]


def test_only_the_api_client_interprets_a_status() -> None:
    """The rule that keeps one error contract instead of two.

    app/api.js classifies a response and puts its answer on the error as ``kind``.
    Every other file under app/ reads that answer and never the status behind it. A
    second file that branches on a status is a second opinion about what a 403 means,
    and two opinions drift the moment either is edited: that is the defect task 32
    removed, in the shape it would come back in.

    A screen genuinely does need to know whether api.js has already raised a curtain
    over it. That question is asked of ``kind``, which states it, rather than
    reconstructed from a status, which only implies it.

    This is a lint, not a proof. It reads both orders of comparison and a ``switch``
    on a status, and it would still miss a status copied into a local first. What
    makes it worth having is that every plausible spelling of the mistake, and the one
    #40 actually makes, is caught at the point somebody merges.
    """
    for path in sorted(APP.rglob("*.js")):
        if path.name == "api.js":
            continue
        source = _without_comments(path.read_text(encoding="utf-8"))
        assert not _STATUS_READ.search(source), path.name
        assert not _STATUS_NUMBER.search(source), path.name


def test_the_narrowed_status_rule_still_bites() -> None:
    """Proof that excusing one file left a rule that still refuses what it must.

    The first version of this test asked only whether ``api.js`` compared against a
    status *anywhere*, which ``response.status === 204`` in ``request()`` and
    ``status !== 401`` in ``noted()`` both satisfy without classifying anything: it
    stayed green with ``classify()`` deleted outright, which is the whole subject of
    the task it was guarding. A guard that passes for a reason unrelated to its claim
    is the defect this repo keeps finding, and this test was one.

    So it asks about the classifier itself, by name and by slice.
    """
    client = _without_comments((APP / "api.js").read_text(encoding="utf-8"))
    assert "function classify(" in client, (
        "app/api.js no longer defines classify(), which is the one place a response "
        "becomes a kind. If it was renamed or moved, move this test with it; do not "
        "delete it, because the rule above goes on passing without it."
    )
    body = _classifier(client)
    # Every kind is answered here, so a classifier cut down to one answer fails.
    for kind in _KINDS:
        assert f"'{kind}'" in body, kind
    # And the statuses it turns into those kinds are read here, in the classifier,
    # rather than anywhere else in the file that happens to mention a number.
    for status in ("401", "403", "500"):
        assert re.search(rf"(?:===|!==|==|!=|>=|<=|>|<)\s*{status}\b", body), status
    assert _STATUS_READ.search(client)
    # And the patterns match the shapes they claim to, so a green run above means the
    # search ran rather than that a regex rotted.
    assert _STATUS_READ.search("if (error.status === 401) {")
    assert _STATUS_READ.search("if (401 === error.status) {")
    assert _STATUS_READ.search("switch (error.status) {")
    assert _STATUS_NUMBER.search("return error.status === 0 || error.status >= 500;")
    assert _STATUS_NUMBER.search("if (401 === error.status) {")
    # A status being written, which is what sw.js does, is not a comparison.
    assert not _STATUS_READ.search("new Response(body, { status: 503 })")
    assert not _STATUS_NUMBER.search("new Response(body, { status: 503 })")


# --- Determinism, isolation and the stub's honesty -------------------------


def test_two_runs_of_the_same_configuration_report_the_same_bytes(
    harness_run: subprocess.CompletedProcess[str],
) -> None:
    # No randomness, no Date.now, no locale-dependent formatting and no network, so a
    # second run of the same configuration is byte-identical.
    again = run_harness({})
    assert again.returncode == harness_run.returncode
    assert again.stdout == harness_run.stdout


def test_every_error_code_the_harness_names_appears_in_web_py(
    report: dict[str, Any],
) -> None:
    web = (REPO / "src" / "splitwise_lite" / "web.py").read_text(encoding="utf-8")
    codes = report["errorCodes"]
    assert codes
    for code in codes:
        assert f'"{code}"' in web, code


def test_the_service_worker_registration_branch_is_never_entered(
    report: dict[str, Any],
) -> None:
    # app.js registers a window 'load' listener only inside
    # `if ('serviceWorker' in navigator)`, and the stub navigator has no such
    # property. A 'load' listener showing up here would mean the branch ran, and the
    # harness would be pretending to cover something it does not. The count of
    # hashchange listeners is not pinned: tasks 11 and 12 each added one of their own,
    # and the screens after them will add more.
    for entry in report["scenarios"]:
        assert set(entry["windowEvents"]) == {"hashchange"}, (
            entry["name"],
            entry["windowEvents"],
        )


def test_each_scenario_starts_from_a_fresh_context(report: dict[str, Any]) -> None:
    # Two scenarios that both boot see two separate fetch recorders: a shared one
    # would show the earlier scenario's call as well. And the second runs straight
    # after a scenario that cached a session view inside api.js, where it asserts the
    # cache is empty, so api.js's state does not survive either.
    order = [entry["name"] for entry in report["scenarios"]]
    linked = "boot_with_a_linked_session_shows_the_app"
    after = "nothing_from_the_previous_scenario_survives_into_this_one"
    assert order.index(linked) + 1 == order.index(after)
    found = results(report)
    for name in (linked, after):
        assert found[name]["passed"], found[name]["failures"]
    # The linked session reaches the app frame, so it reads the two screens as well.
    # The 403 that follows it never gets that far and reads once, and a recorder shared
    # between the two would carry those extra reads into this list.
    assert found[linked]["requests"] == [
        "GET /api/session",
        "GET /api/expenses",
        "GET /api/members",
    ]
    assert found[after]["requests"] == ["GET /api/session"]


# --- Neither half depends on the working directory -------------------------


def test_the_harness_finds_app_from_its_own_location(tmp_path: Path) -> None:
    completed = run_harness({}, cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr


def test_the_suite_passes_when_pytest_runs_from_another_directory(
    tmp_path: Path,
) -> None:
    # One test from this file, so the nested run cannot recurse into this one.
    target = f"{Path(__file__).resolve()}::test_an_anchor_that_matches_nothing_refuses_the_run"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
        cwd=str(tmp_path),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
