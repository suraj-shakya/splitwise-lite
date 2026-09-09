"""What a request is answered with, watched, so a marked row's claim gets checked.

GitHub issue #82, sharpened in plans/tasks/82-the-unreachability-claim.md.

``tests/test_error_messages.py`` declares every refusal ``src/splitwise_lite/`` raises
with a 4xx status. Of its rows, 49 carry the marker ``NO_REQUEST_REACHES_IT``
(``grep -c '^    unreachable(' tests/test_error_messages.py``, run 2026-09-09; it was
50, then 47 when three of those marks turned out to be false and their rows were
driven, and 49 again when issue #78 removed the weight wire mode and the two
``split.py`` guards it was the only route to stopped being reachable), which is a claim
about reachability, and it was the one claim in that module nothing verified. The falsifying event is a new route reaching an existing raise: the set of
raise sites does not change, no message skeleton changes, the enumeration equality
still holds, and a message interpolating a stored value has silently become something a
client can be shown.

**The predicate.** A marked row is reached by a request when the exception raised at
one of that row's raise sites is the exception ``web._handle_error`` turns into the
response.

**The negative half.** Executing a marked raise and being caught inside
``src/splitwise_lite/`` is not reaching. Only the deepest frame of an exception's own
traceback is consulted, and the ``__cause__`` and ``__context__`` chains are not
consulted at all, so a refusal that is raised, swallowed, and answered with a different
exception belongs to the second raise and not to the first.

That is not a fine distinction; it is the whole design. Execution is not the harm. The
harm, and the premise two screens in ``app/app.js`` are built on, is a message carrying
a stored value being shown to a client, and a refusal swallowed inside the package
never becomes a body and never reaches anybody. Three marked rows are raised, caught
and answered with something else inside the package, and every one of them executes on
requests this suite already drives, so a check on execution would go red today on marks
that are correct. Each is checkable by opening the line named:

* ``store.get_user_by_email`` is caught at ``src/splitwise_lite/accounts.py:659``,
  where ``except RecordNotFound: pass`` is ``sign_up``'s success path, so it executes
  on every successful signup; and again at ``src/splitwise_lite/accounts.py:701``,
  where ``log_in`` answers with ``AuthenticationFailed`` instead.
* ``store.get_session`` is caught at ``src/splitwise_lite/accounts.py:735``, where
  ``authenticate`` answers with ``SessionInvalid`` instead. The driven row whose
  client carries a cookie naming no live session executes it.
* ``store.get_member_for_user`` is caught at ``src/splitwise_lite/groups.py:774``,
  where ``acting_member`` answers with ``MemberNotLinked`` instead. The driven row for
  an account no member row points at executes it.

Excluding those three costs nothing here, because the predicate excludes them by
construction. There is no allowlist, no exemption set and no per-row marker, which is
what ``tests/test_error_messages.py``'s driven half is already proud of not having.

**Why this needs no window and no scope.** ``web._handle_error`` runs only inside a
WSGI call: ``create_app`` registers it as the handler for ``Exception``, so every
exception raised in ``before_request``, in a view or in ``after_request`` reaches it,
and nothing else does. A unit test in ``tests/test_store.py`` that calls
``store.get_expense("nope")`` and asserts it raises can never be seen here, because it
never routes through the handler. There is no window to open, no thread to bind, and no
tracer whose installation could be mistimed. Nothing here traces a line, and
``sys.settrace`` and ``sys.monitoring`` are not called.

**What this does not claim.** It is not a proof of unreachability, and nothing here or
in the documents calls it one. It covers the requests this suite actually makes, which
includes the route surface ``tests/test_web_api.py`` drives. A partial run of the suite
makes fewer requests than a full run, so a partial run can produce a false pass; it can
never produce a false failure, because a row is reported only when a request really was
answered from its raise.

**The observer is proved to work on every run,** rather than only when something is
wrong: ``test_each_driven_row_answers_from_the_site_it_declares`` in
``tests/test_error_messages.py`` asserts that each driven row was answered from the
site its row names, and reds if this file records nothing.

This is a conftest for two reasons. The wrapper has to be in place before the first
test builds an app, because ``create_app`` reads ``web._handle_error`` when it
registers the handler and a wrapper installed afterwards would watch a function that
app never calls, record nothing, and look exactly like success. And the guard has to
run after every test in the suite. ``tests/test_end_to_end.py`` records this repo's
reason for not introducing a conftest, and that reason is about sharing fixture
scaffolding between two modules, which this is not.

**What importing the package here costs, measured.** This file imports
``splitwise_lite.web`` at module scope, so the session imports the package before any
test runs. ``tests/test_suite_integrity.py``'s docstring says its checks "still run on
a checkout where the package will not import", and at the session level that is now
weaker than it was. Importing lazily inside the fixture does not fix it, measured on
2026-09-08 with ``PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest
tests/test_suite_integrity.py -q``, which reports **92 errors**. That is one error per
test in that one module, which collects 92, and not a count over the whole suite. The
cause is the autouse session scope criterion B1 mandates rather than where the import
is written. A
``try``/``except ImportError`` here would be a hatch that could mask the observer not
being installed, which is the one failure the group C proof exists to catch, so there
is none. The only repair that would actually hold touches
``tests/test_suite_integrity.py``, which this task may not edit because PR #70a owns
it, so this is recorded rather than fixed.

Standard library, pytest and the package under test only, which is the limit
``tests/test_error_messages.py`` already holds to.
"""

from __future__ import annotations

import json
from types import ModuleType
from typing import Any, Final, NamedTuple

import pytest

from splitwise_lite import web


class Answered(NamedTuple):
    """One exception ``web._handle_error`` turned into a response.

    ``file`` and ``lineno`` are the deepest frame of that exception's own traceback,
    which is where it was raised, recorded raw exactly as Python reports them. Turning
    a position into a row of the table is ``tests/test_error_messages.py``'s job,
    because that module owns the table and the index built from it.
    """

    file: str
    lineno: int
    method: str
    path: str
    status: int
    message: str


ANSWERED: Final[list[Answered]] = []
"""Every exception ``web._handle_error`` has answered since this was last cleared."""

OBSERVER_FAILURES: Final[list[str]] = []
"""Whatever went wrong inside the observer itself.

The wrapper records and does not raise: a bug in this file must not be able to change
what the application under test returns. So a failure in its own bookkeeping is put
here and reported by the guard as a violation carrying its own message, rather than
propagated into the response, and rather than swallowed.
"""


def _deepest_frame(error: BaseException) -> tuple[str, int] | None:
    """Where ``error`` was raised: the deepest frame of its own traceback.

    Its own, and only its own. ``__cause__`` and ``__context__`` are not followed, so
    an exception raised inside the package to answer one that was caught there belongs
    to the second raise. That is what excludes the three rows named in the module
    docstring, by construction rather than by an exemption somebody maintains.
    """
    traceback = error.__traceback__
    if traceback is None:
        return None
    while traceback.tb_next is not None:
        traceback = traceback.tb_next
    return traceback.tb_frame.f_code.co_filename, traceback.tb_lineno


def _message_of(response: Any) -> str:
    """The sentence a client reads, out of the one error body shape.

    Falls back to the first of the raw body rather than raising, because the guard's
    message is more useful with something in it than the observer is with an
    exception in it.
    """
    body = response.get_data(as_text=True)
    try:
        return str(json.loads(body)["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return body[:200]


def _observing(original: Any) -> Any:
    """``original``, with a record of what it answers and nothing else changed.

    The response is the original's own object, returned unchanged: no status, no
    header, no ``Set-Cookie`` and no body byte differs from an unwrapped run. The
    evidence for that is the rest of the suite staying green under it.
    """

    def handle_error(error: Exception) -> Any:
        response = original(error)
        try:
            raised = _deepest_frame(error)
            if raised is not None:
                ANSWERED.append(
                    Answered(
                        raised[0],
                        raised[1],
                        # ``web.flask`` rather than a second import of the
                        # framework into this file, which is the preference
                        # tests/test_web_api.py records.
                        web.flask.request.method,
                        web.flask.request.path,
                        response.status_code,
                        _message_of(response),
                    )
                )
        except BaseException as failure:  # noqa - the observer never breaks the app
            OBSERVER_FAILURES.append(
                "the observer in tests/conftest.py failed while recording a "
                f"{type(error).__name__}: {type(failure).__name__}: {failure}"
            )
        return response

    return handle_error


@pytest.fixture(scope="session", autouse=True)
def observe_what_requests_are_answered_with():
    """Wrap ``web._handle_error`` for the session, and put the original back after.

    Session-scoped and autouse because ``create_app`` reads ``web._handle_error`` when
    it registers the handler: a wrapper installed after the first app was built would
    be watching a function that app never calls. Restored in a ``finally``, so after
    the session ``web._handle_error`` is the same object it was before.
    """
    original = web._handle_error
    web._handle_error = _observing(original)
    ANSWERED.clear()
    OBSERVER_FAILURES.clear()
    try:
        yield
    finally:
        web._handle_error = original


def _table() -> ModuleType:
    """``tests/test_error_messages.py``, which owns the table and the raise-site index.

    Imported by name, the way ``tests/test_end_to_end.py`` imports its scaffolding
    from ``tests/test_web_api.py``, and imported here rather than at module scope so a
    run that makes no request at all never pays for the ``ast`` walk.
    """
    import test_error_messages

    return test_error_messages


def _reached_message(key: tuple[Any, ...], answered: Answered) -> str:
    """What the guard says when a marked row was answered to a client."""
    module, function, skeleton = key
    return (
        "A row of FOUR_HUNDRED_SITES marked NO_REQUEST_REACHES_IT answered a request "
        "this test made.\n"
        f"  row:     {module}::{function}::{skeleton!r}\n"
        f"  raised:  {answered.file}:{answered.lineno}\n"
        f"  request: {answered.method} {answered.path}\n"
        f"  answer:  {answered.status} {answered.message!r}\n"
        "\n"
        "The marker is a claim that no request is ever answered from that raise. "
        "This one was: the exception raised there is the exception web._handle_error "
        "turned into the response, so that message was shown to a client. Either a "
        "route now reaches the raise, in which case the row moves from "
        "unreachable(...) to a Drive and has to carry no identifier the store holds "
        "(issue #61), or the request is wrong. The predicate is stated at the top of "
        "tests/conftest.py."
    )


@pytest.fixture(autouse=True)
def no_marked_row_answers_a_request():
    """After every test in the suite: no marked row was answered to a client.

    Attributed to the test that made the request, with no session-end summary and no
    separate reporting test, so a failure names the test that has to change. A row is
    reported once however many requests reached it, carrying the first request that
    did, because a wall of repeats is harder to act on than one line.
    """
    yield
    if not ANSWERED and not OBSERVER_FAILURES:
        return
    table = _table()
    marked = {site.key for site in table.MARKED}
    reported: dict[tuple[Any, ...], str] = {}
    for answered in ANSWERED:
        key = table.key_for_raise_site(answered.file, answered.lineno)
        if key is None or key not in marked or key in reported:
            continue
        reported[key] = _reached_message(key, answered)
    problems = list(OBSERVER_FAILURES) + list(reported.values())
    ANSWERED.clear()
    OBSERVER_FAILURES.clear()
    assert not problems, "\n\n".join(problems)


@pytest.fixture
def answered_requests() -> list[Answered]:
    """The observer's record, live, for a test that reads or clears it.

    ``tests/test_error_messages.py`` clears it immediately before a driven row's one
    request and then asserts that row was answered from the site it declares, which is
    what proves this file works on every run.
    """
    return ANSWERED
