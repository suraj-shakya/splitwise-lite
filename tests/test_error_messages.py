"""No message this repo sends with a 4xx status carries an internal identifier.

Issue #61, sharpened in
plans/tasks/61-no-4xx-body-carries-an-identifier.md.

The rule is scoped by status: no 4xx body names a member id, a user id, a group id, an
expense id, a settlement id or an event id. The two 503 rows of ``web.ERROR_STATUS``
sit outside it by status rather than by exemption. ``groups.AmbiguousGroup`` names
every group id and ``groups.NoGroupConfigured`` names the setup command on purpose:
a 503 there means the deployment cannot express what it holds, no change to any request
fixes it, and the only reader who can act is an operator telling two groups apart.

**Why this is a check and not an audit.** Two screens are built on a premise about what
these messages can contain: ``app/app.js``'s add screen prints every server sentence
verbatim, and its balances screen prints none of them, in three regions whose comments
each name a member id as the reason. That premise had been re-derived by hand four
times, by four readers, in four files, and produced four different answers to "how many
sites are there": two, three, six and twelve. The reasoning lived in a comment in
``app/`` about code in ``src/``, and nothing went red when the two diverged.

**Two checks, two jobs.** A purely static leak detector cannot avoid false positives
here, because the thing it would have to distinguish is a payload key **name** from a
member id **value**, and in the source both are a bare name interpolated into an
f-string: ``{key!r}`` is a literal at every call site of ``_require_str`` and was a
member id in ``_require_weight``. That is a fact about runtime values, not about
syntax, so a denylist of variable names has false positives on the first kind and false
negatives on the second. So:

* :func:`test_every_four_hundred_raise_site_is_declared` is an **enumeration
  equality**, not a scan. It compares two sets rather than judging a value, so it has
  no false positives at all. It is the shape ``web._audit_routes`` already runs against
  ``_API_ROUTES`` and ``test_the_harness_reports_exactly_the_declared_scenarios``
  already runs against ``SCENARIOS``. It is also what would have found all twelve
  sites, because it enumerates ``raise`` sites rather than messages: six of the twelve
  were found while writing the spec, and every one of them has a ``raise`` in a
  4xx-mapped class and would have demanded a row here.
* :func:`test_no_four_hundred_body_names_an_identifier` is the **property**. It drives
  each reachable row and asserts no identifier the store holds occurs in
  ``body["error"]["message"]``, with the identifier set gathered from the store rather
  than written down, so it is complete by construction.

Because every id-bearing site is genuinely unreachable by request, the driven half
needs no allowlist, no exemption set and no marker comment. There is nothing in it to
rot.

**Retracted 2026-09-08, issue #82.** This passage read:

    What is **not** covered, stated plainly: a row marked
    :data:`NO_REQUEST_REACHES_IT` is a claim this module records rather than verifies

That is no longer so. ``tests/conftest.py`` watches what ``web._handle_error`` turns
into a response and reds when the exception raised at a marked row's site is the one
answered, so the marker is checked on every run rather than recorded. What that check
does not cover is stated where the predicate is, in ``tests/conftest.py``, and is
deliberately not restated here.

The identifier set excludes email addresses deliberately.
``accounts.EmailAlreadyRegistered`` names a normalised address at 409, that address is
the person's own typed input, the sign-up screen shows it back, and echoing typed input
is ``parse_amount``'s already-accepted precedent.

Everything below drives the app through ``app.test_client()``. No test binds a socket,
opens a port, starts a thread or spawns a subprocess.

The scaffolding is spelled out here rather than imported from ``tests/test_web_api.py``
the way ``tests/test_end_to_end.py`` imports it, because this module imports only the
standard library, ``pytest`` and the package under test. It is much less than that
module needs: one seed, one link and one CSRF token.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import functools
import importlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, NamedTuple

import pytest

from splitwise_lite import accounts, money, web
from splitwise_lite.events import GroupId, MemberId, SettlementEvent, SettlementId
from splitwise_lite.groups import (
    GroupDefinition,
    apply_group_definition,
    link_user_to_member,
    resolve_sole_group,
)
from splitwise_lite.store import DuplicateRecord, open_store

REPO: Final = Path(__file__).resolve().parents[1]
PACKAGE: Final = REPO / "src" / "splitwise_lite"

CHEAP: Final = accounts.ScryptParams(n=16, r=1, p=1)
"""scrypt at 16 KiB and one round, the shape the rest of the suite injects: every row
here signs one account up and in, and none of them is about the KDF's cost."""

PASSWORD: Final = "correct horse battery staple"
ROSTER: Final = ("Sam", "Ali", "Jo")
CURRENCY: Final = "AUD"

NOT_IN_THE_ROSTER: Final = "{group}"
"""What a row sends where it means "an id this group's roster does not hold".

It is the **group's own id**, and that is not incidental. A driver that sent a made-up
string would reach the same refusal and prove nothing: :func:`identifiers_in` searches
for the ids the store holds, so a made-up string cannot be seen leaking, and restoring
one of the interpolations this task removed would leave the driven row green. A group
id is stored, is at least eight characters, is refused by exactly the same branch as
any other non-member, and **is** in the identifier set. Do not tidy this back into a
literal: the mutation records in plans/mutations/61-identifiers-in-4xx-bodies.md are
the evidence that these rows bite, and they bite because of this.
"""

MIN_REASON: Final = 30
"""How long an unreachability reason has to be, the way ``tests/test_suite_integrity``
puts a floor on an ``# unanchored:`` reason. A reason short enough to be a shrug is the
thing the floor is for."""

MIN_IDENTIFIER: Final = 8
"""No id shorter than this is believed. A two-character id would match a common
substring of an innocent sentence and the driven half would flake instead of failing."""


# --- The seeded application -------------------------------------------------


def at(hour: int = 9, minute: int = 0) -> datetime:
    """A fixed, timezone-aware instant, so nothing here reads the wall clock."""
    return datetime(2026, 9, 5, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
def seeded(tmp_path: Path) -> Path:
    """A file-backed store holding exactly one group and its roster.

    Never in-memory: the app opens one store per request, so a private in-memory
    database would be empty by the time a request arrived.
    """
    path = tmp_path / "ledger.sqlite3"
    with open_store(path) as store:
        apply_group_definition(
            store, GroupDefinition("Flat 3", money.Currency(CURRENCY), ROSTER), now=at()
        )
    return path


@pytest.fixture
def app(seeded: Path):
    """The application under test, with cookies sent without ``Secure``."""
    return web.create_app(
        store_path=seeded, secure_cookies=False, scrypt_params=CHEAP
    )


def csrf_token(client) -> str:
    """Load the shell once, the way a browser does, and read the issued token."""
    client.get("/")
    cookie = client.get_cookie(web.CSRF_COOKIE)
    assert cookie is not None, "the shell issued no CSRF cookie"
    return cookie.value


def post(client, path: str, payload: dict | None = None):
    """A state-changing request with the three CSRF gates met."""
    return client.open(
        path,
        method="POST",
        json={} if payload is None else payload,
        headers={web.CSRF_HEADER: csrf_token(client)},
    )


def email_for(display_name: str) -> str:
    """The address this module signs ``display_name`` up with."""
    return f"{display_name.lower()}@example.com"


def linked_client(app, path: Path, display_name: str):
    """A client signed in as an account linked to ``display_name``.

    Linking goes through ``groups.link_user_to_member``, which is what
    ``setup_group.py link`` calls and the only thing in the repository that links a
    user to a member.
    """
    client = app.test_client()
    address = email_for(display_name)
    signed_up = post(
        client,
        "/api/signup",
        {"email": address, "display_name": display_name, "password": PASSWORD},
    )
    # A row whose setup already signed this person up asks for them again: the rows
    # about a settlement need Sam to mark it and then to be the one refused. One
    # account per person, so a second call signs in on a fresh client rather than
    # making a second account or linking the member twice.
    if signed_up.status_code != 409:
        assert signed_up.status_code == 201, signed_up.get_json()
        with open_store(path) as store:
            group = resolve_sole_group(store)
            member = next(
                found
                for found in store.list_members(group.id)
                if found.display_name == display_name
            )
            user = store.get_user_by_email(address)
            link_user_to_member(
                store, group_id=group.id, member_id=member.id, user_id=user.id
            )
    assert (
        post(
            client, "/api/session", {"email": address, "password": PASSWORD}
        ).status_code
        == 200
    )
    return client


def unlinked_client(app):
    """A client signed in as an account no member row points at.

    The one ordinary sequence that reaches ``groups.acting_member``'s refusal: sign up,
    do not get linked, open the app.
    """
    client = app.test_client()
    assert (
        post(
            client,
            "/api/signup",
            {
                "email": "nobody@example.com",
                "display_name": "Nobody",
                "password": PASSWORD,
            },
        ).status_code
        == 201
    )
    assert (
        post(
            client,
            "/api/session",
            {"email": "nobody@example.com", "password": PASSWORD},
        ).status_code
        == 200
    )
    return client


def roster_names(path: Path) -> dict[str, str]:
    """Every placeholder a row can write, read from the store and not from a response.

    Each member's display name maps to that member's id, and ``group`` maps to the
    group's own id, which is what :data:`NOT_IN_THE_ROSTER` is.
    """
    with open_store(path) as store:
        group = resolve_sole_group(store)
        names = {
            member.display_name: member.id
            for member in store.list_members(group.id)
        }
    assert "group" not in names, (
        "a member is called Group, which collides with the {group} placeholder. "
        "Rename the member in ROSTER."
    )
    names["group"] = group.id
    return names


# --- The identifier set -----------------------------------------------------


def identifiers_in(message: str, identifiers: tuple[str, ...]) -> list[str]:
    """Every identifier of ``identifiers`` that occurs anywhere in ``message``.

    A plain substring search, deliberately: an id in a 4xx body is a leak however it is
    punctuated, quoted or embedded, and a word-boundary search would miss
    ``...group: 'mem-9'`` on the quote. The answer is a list rather than a bool so a
    failure names what leaked, and it is ordered by ``identifiers`` so two runs of the
    same case report the same thing.
    """
    return [found for found in identifiers if found in message]


def stored_identifiers(path: Path) -> tuple[str, ...]:
    """Every internal identifier the store at ``path`` holds.

    Gathered from the store rather than written down, because any id the server could
    interpolate came from the store: the group id, every member id, every user id, and
    the id of every event ``list_events`` returns. That is complete by construction and
    stays complete when a new event type lands.

    The user ids come out of ``users`` with SQL, because ``EventStore`` has no
    ``list_users`` and the alternative -- reading ``user_id`` off the member rows --
    would miss exactly the account this module most needs: the signed-up-but-unlinked
    user whose id ``groups.acting_member``'s 403 used to name. A row of ids gathered
    from the linked members only would have let that leak through green.

    Reads the store directly and reads no response body.
    """
    found: list[str] = []
    with open_store(path) as store:
        group = resolve_sole_group(store)
        found.append(group.id)
        found.extend(member.id for member in store.list_members(group.id))
        found.extend(event.id for event in store.list_events(group.id))
    with sqlite3.connect(path) as connection:
        found.extend(
            row[0] for row in connection.execute("SELECT id FROM users").fetchall()
        )
    connection.close()

    for identifier in found:
        assert isinstance(identifier, str) and len(identifier) >= MIN_IDENTIFIER, (
            f"the store holds {identifier!r}, which is shorter than "
            f"{MIN_IDENTIFIER} characters. An id that short matches a common "
            "substring of an innocent sentence, so the check below would flake "
            "rather than fail. Lengthen the id or narrow the search, and do not "
            "lower this floor."
        )
    # Longest first, so a failure reports the whole id rather than a prefix of it if
    # one id is ever a prefix of another.
    return tuple(sorted(set(found), key=lambda value: (-len(value), value)))


# --- The enumeration --------------------------------------------------------
#
# Deliberately an equality against a declared table rather than a scan for suspicious
# names. A scan has to judge a value from a name and cannot; an equality compares two
# sets and cannot be wrong about either. The price is that a new 4xx raise site fails
# this module until somebody writes its row, which is the point: that is the moment the
# question "can this one carry an id" gets asked.

Key = tuple[str, str, str | None]


def message_skeleton(node: ast.expr | None, module: Any) -> str | None:
    """The literal fragments of a raised message, with the interpolations removed.

    ``f"{what} names a payer_id that is not a member of this group"`` skeletonises to
    ``" names a payer_id that is not a member of this group"``, so the key is stable
    under reflowing a message across different line breaks and changes exactly when the
    wording changes.

    A message that is a module-level constant is resolved through ``module``, so
    ``raise TooManyAttempts(_TOO_MANY_ATTEMPTS_MESSAGE)`` keys on the sentence rather
    than on the name. Anything else -- a parameter, a call -- is ``None``: the message
    is composed by whoever calls that function, and this walk cannot see where.
    """
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    if isinstance(node, ast.Name):
        resolved = getattr(module, node.id, None)
        if isinstance(resolved, str):
            return resolved
    return None


def dotted_name(node: ast.expr) -> str | None:
    """``store.RecordNotFound`` from the tree, or ``None`` if it is not a plain name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def four_hundred_status(klass: type[BaseException]) -> int | None:
    """``klass``'s status if it is a 4xx, walking the MRO the way ``web.py`` does.

    The walk mirrors ``web._status_and_code``, which looks each raised exception up by
    ``type(error).__mro__`` so a subclass inherits its parent's row rather than falling
    through to 500. Anything unmapped, and anything mapped outside ``range(400, 500)``,
    is not this module's business: a 500 is already generic by
    ``web._GENERIC_500_MESSAGE``, and the two 503 rows are operator-facing on purpose.
    """
    for base in klass.__mro__:
        status = web.ERROR_STATUS.get(base)
        if status is not None:
            return status if 400 <= status < 500 else None
    return None


def raised_class(node: ast.expr, module: Any) -> type[BaseException] | None:
    """The exception class a ``raise`` names, resolved through ``module``.

    ``None`` for a re-raise of an already-constructed exception (``raise error``),
    whose message was composed at a ``raise`` site this walk sees anyway, and for
    anything that does not resolve to an exception class.
    """
    name = dotted_name(node.func if isinstance(node, ast.Call) else node)
    if name is None:
        return None
    parts = name.split(".")
    found = getattr(module, parts[0], None)
    if found is None:
        found = getattr(builtins, parts[0], None)
    for part in parts[1:]:
        found = getattr(found, part, None) if found is not None else None
    if isinstance(found, type) and issubclass(found, BaseException):
        return found
    return None


class RaiseSpan(NamedTuple):
    """One ``raise`` statement: the row it belongs to, and the lines it occupies.

    ``file`` is the resolved absolute path, so it compares equal to the path a
    traceback frame reports for the same module. Three statements that share a ``key``
    are three spans, because a key identifies a message and a position identifies a
    statement.
    """

    key: Key
    file: Path
    lineno: int
    end_lineno: int


@functools.cache
def four_hundred_raise_spans() -> tuple[RaiseSpan, ...]:
    """Every ``raise`` in the package whose class maps to a 4xx, with its line span.

    This is **the** walk. :func:`four_hundred_raise_sites` and
    :func:`raise_site_index` are two views of this one result rather than two walks
    over the same files, so the enumeration equality and the index cannot come to
    disagree about what the package holds.

    One key per ``(module file name, enclosing def name, message skeleton)``. Two
    raises that agree on all three collapse to one key, which is what
    ``accounts.authenticate``'s three identical ``SessionInvalid`` refusals are: one
    site as far as a message is concerned, and three spans as far as a position is.
    """
    found: list[RaiseSpan] = []
    for path in sorted(PACKAGE.glob("*.py")):
        module = importlib.import_module(f"splitwise_lite.{path.stem}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        absolute = path.resolve()
        stack: list[str] = []

        def walk(node: ast.AST) -> None:
            named = isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            if named:
                stack.append(node.name)  # type: ignore[attr-defined]
            if isinstance(node, ast.Raise) and node.exc is not None:
                klass = raised_class(node.exc, module)
                if klass is not None and four_hundred_status(klass) is not None:
                    arguments = node.exc.args if isinstance(node.exc, ast.Call) else []
                    found.append(
                        RaiseSpan(
                            (
                                path.name,
                                stack[-1] if stack else "<module>",
                                message_skeleton(
                                    arguments[0] if arguments else None, module
                                ),
                            ),
                            absolute,
                            node.lineno,
                            node.end_lineno or node.lineno,
                        )
                    )
            for child in ast.iter_child_nodes(node):
                walk(child)
            if named:
                stack.pop()

        walk(tree)
    return tuple(found)


def four_hundred_raise_sites() -> set[Key]:
    """The keys the walk found, which is what the enumeration equality compares."""
    return {span.key for span in four_hundred_raise_spans()}


# --- The raise-site index ---------------------------------------------------
#
# The table records which rows no request reaches. tests/conftest.py watches what
# web._handle_error turns into a response, and to say which row an answer came from it
# has to turn the (file, line) of a traceback frame back into a key. That is this
# index, and it is built from the spans above rather than from a walk of its own.


@functools.cache
def raise_site_index() -> dict[tuple[Path, int], Key]:
    """Every line of every 4xx ``raise`` statement, mapped to that statement's key.

    Every line of the span rather than only the first: Python reports the line of the
    instruction that raised, and a ``raise`` wrapped across four lines can be reported
    at any of them.
    """
    index: dict[tuple[Path, int], Key] = {}
    for span in four_hundred_raise_spans():
        for lineno in range(span.lineno, span.end_lineno + 1):
            index[(span.file, lineno)] = span.key
    return index


@functools.cache
def indexed_path(filename: str) -> Path:
    """``filename`` spelled the way :func:`raise_site_index` spells it.

    Both sides go through ``Path.resolve``, because the index is built from
    ``PACKAGE.glob`` and a traceback reports the path the import system used. On
    Windows those two can differ in case or in a short name while naming one file, and
    a comparison that silently never matches is how this kind of instrument passes
    over nothing forever.
    """
    return Path(filename).resolve()


def key_for_raise_site(filename: str, lineno: int) -> Key | None:
    """The row whose ``raise`` statement occupies ``filename`` line ``lineno``.

    ``None`` for everything else, and that one answer is the whole of the filtering: a
    line with no 4xx ``raise`` on it, a ``raise`` whose class maps outside 4xx, an
    implicit ``TypeError``, a werkzeug ``HTTPException``, and every file outside
    ``src/splitwise_lite/``.
    """
    return raise_site_index().get((indexed_path(filename), lineno))


# --- The table --------------------------------------------------------------

NO_REQUEST_REACHES_IT: Final = "NO_REQUEST_REACHES_IT"
"""A site no request is ever answered from, with a reason saying what would have to be
true for one to be.

**Escape, not execution, and the difference decides rows.** A marked raise may be
executed by a request and the row still be correct, so long as the exception is caught
inside ``src/splitwise_lite/`` and something else is what the client is answered with.
``store.get_user_by_email``'s refusal runs on every successful signup and is marked,
correctly. The predicate is stated in ``tests/conftest.py``; this is a pointer to it
and not a second version of it.

**Retracted 2026-09-08, issue #82.** This docstring read:

    A site no HTTP request can reach, with a reason saying what would have to be true.

    A claim this module records rather than verifies.

Both halves were wrong by then. HTTP requests do reach several of these rows without
ever being answered from them, and the marker is now checked rather than recorded.

Every one of them is a refusal whose inputs the server produced itself, a refusal only
``scripts/setup_group.py`` reaches, or a refusal another layer catches and re-raises as
something else.
"""


class Drive(NamedTuple):
    """One request that reaches a site, and the code it must report.

    ``path`` and ``payload`` are filled from the seeded roster at run time, so a row
    writes ``{Sam}`` where it means Sam's member id and stays readable as data. ``raw``
    replaces the JSON body with exact bytes, for the two rows about a body that is not
    a JSON object at all.
    """

    method: str
    path: str
    code: str
    payload: Any = None
    raw: str | None = None
    content_type: str | None = None
    who: str = "linked"
    csrf: str = "correct"
    origin: str | None = None
    setup: str = "none"


class Site(NamedTuple):
    """One row: where the message is raised, what it says, and how it is covered."""

    module: str
    function: str
    skeleton: str | None
    drive: Drive | str
    reason: str = ""

    @property
    def key(self) -> Key:
        return (self.module, self.function, self.skeleton)


def unreachable(module: str, function: str, skeleton: str | None, reason: str) -> Site:
    """A row no request reaches, with the reason it does not."""
    return Site(module, function, skeleton, NO_REQUEST_REACHES_IT, reason)


SIGNUP: Final = "/api/signup"
SESSION: Final = "/api/session"
EXPENSES: Final = "/api/expenses"
SETTLEMENTS: Final = "/api/settlements"

STORED_VALUE: Final = (
    "reaching it needs a caller inside the process handing the store a value no route "
    "can produce: every id the app passes in came from new_id() or from the store "
    "itself, every amount came through money.parse_amount, and every address came "
    "through accounts.normalise_email"
)

FOUR_HUNDRED_SITES: Final[tuple[Site, ...]] = (
    # --- accounts.py -------------------------------------------------------
    unreachable(
        "accounts.py",
        "_require_utc",
        " must be timezone-aware, got naive ",
        "every instant the app hands accounts.py is web._now(), which is "
        "datetime.now(timezone.utc); a naive one needs a caller inside the process",
    ),
    unreachable(
        "accounts.py",
        "__post_init__",
        "IssuedSession token must not be empty",
        "the token is generated by secrets.token_urlsafe inside log_in, so an empty "
        "one is not something a request can ask for",
    ),
    Site(
        "accounts.py",
        "_require_password_policy",
        "a password must be at least  characters, got ",
        Drive(
            "POST",
            SIGNUP,
            "invalid_password",
            {"email": "new@example.com", "display_name": "New", "password": "short"},
            who="anonymous",
        ),
    ),
    Site(
        "accounts.py",
        "_require_password_policy",
        "a password must be at most  characters, got ",
        Drive(
            "POST",
            SIGNUP,
            "invalid_password",
            {
                "email": "new@example.com",
                "display_name": "New",
                "password": "x" * (accounts.MAX_PASSWORD_LENGTH + 1),
            },
            who="anonymous",
        ),
    ),
    Site(
        "accounts.py",
        "_require_password_policy",
        "a password must not be whitespace alone",
        Drive(
            "POST",
            SIGNUP,
            "invalid_password",
            {
                "email": "new@example.com",
                "display_name": "New",
                "password": " " * accounts.MIN_PASSWORD_LENGTH,
            },
            who="anonymous",
        ),
    ),
    Site(
        "accounts.py",
        "_fail_login",
        "that email address and password do not match an account",
        Drive(
            "POST",
            SESSION,
            "authentication_failed",
            {"email": "nobody@example.com", "password": PASSWORD},
            who="anonymous",
        ),
    ),
    Site(
        "accounts.py",
        "_require_email",
        "an email address must be at most  characters, got ",
        Drive(
            "POST",
            SIGNUP,
            "invalid_email",
            {
                "email": "a" * accounts.MAX_EMAIL_LENGTH + "@example.com",
                "display_name": "New",
                "password": PASSWORD,
            },
            who="anonymous",
        ),
    ),
    Site(
        "accounts.py",
        "_require_email",
        "an email address must be printable ASCII, got ",
        Drive(
            "POST",
            SIGNUP,
            "invalid_email",
            {
                "email": "samé@example.com",
                "display_name": "New",
                "password": PASSWORD,
            },
            who="anonymous",
        ),
    ),
    Site(
        "accounts.py",
        "_require_email",
        "an email address must have no spaces, got ",
        Drive(
            "POST",
            SIGNUP,
            "invalid_email",
            {
                "email": "sam here@example.com",
                "display_name": "New",
                "password": PASSWORD,
            },
            who="anonymous",
        ),
    ),
    Site(
        "accounts.py",
        "_require_email",
        "an email address must have exactly one @, got ",
        Drive(
            "POST",
            SIGNUP,
            "invalid_email",
            {
                "email": "sam@@example.com",
                "display_name": "New",
                "password": PASSWORD,
            },
            who="anonymous",
        ),
    ),
    Site(
        "accounts.py",
        "_require_email",
        "an email address must have a local part, got ",
        Drive(
            "POST",
            SIGNUP,
            "invalid_email",
            {"email": "@example.com", "display_name": "New", "password": PASSWORD},
            who="anonymous",
        ),
    ),
    Site(
        "accounts.py",
        "_require_email",
        "an email address must have a dotted domain, got ",
        Drive(
            "POST",
            SIGNUP,
            "invalid_email",
            {"email": "sam@example", "display_name": "New", "password": PASSWORD},
            who="anonymous",
        ),
    ),
    Site(
        # The one 4xx that names an address on purpose. An address is the person's own
        # typed input, the sign-up screen shows it back, and it is not in the
        # identifier set, so this row asserts what it should: no store id.
        "accounts.py",
        "sign_up",
        "an account already exists for ",
        Drive(
            "POST",
            SIGNUP,
            "email_already_registered",
            {
                "email": email_for("Sam"),
                "display_name": "Sam",
                "password": PASSWORD,
            },
        ),
    ),
    Site(
        "accounts.py",
        "log_in",
        "that email address and password do not match an account",
        Drive(
            "POST",
            SESSION,
            "authentication_failed",
            {"email": email_for("Sam"), "password": "not the password at all"},
        ),
    ),
    Site(
        "accounts.py",
        "authenticate",
        "that token does not name a live session",
        Drive("GET", SESSION, "session_invalid", who="stale"),
    ),
    unreachable(
        "accounts.py",
        "change_password",
        "the current password is not correct",
        "no route calls change_password: _API_ROUTES holds no password-change row, so "
        "the only caller is a test or a future task",
    ),
    unreachable(
        "accounts.py",
        "change_password",
        "the new password must differ from the current one",
        "same as the row above it: change_password has no route, so no request of any "
        "shape reaches either of its refusals",
    ),
    # --- balances.py -------------------------------------------------------
    unreachable(
        "balances.py",
        "_require_currency_match",
        "cannot combine  and :   is in  and the ledger is in ",
        "it needs a ledger holding two currencies, and spec.md freezes a group's "
        "currency at creation: store._require_group_currency refuses an event in any "
        "other one, so no request can build that ledger",
    ),
    # --- groups.py ---------------------------------------------------------
    unreachable(
        "groups.py",
        "_require_utc",
        " must be timezone-aware, got naive ",
        "the only instant groups.py validates is the one setup_group.py passes to "
        "apply_group_definition, and no HTTP route calls that function",
    ),
    unreachable(
        "groups.py",
        "_require_reconcilable",
        "group  is named , but the definition names it ; renaming a group is out of "
        "scope in v1",
        "raised only by apply_group_definition, which is setup_group.py's refusal read "
        "by an operator at a terminal; web.py never calls it and the ids are how that "
        "operator tells two groups apart",
    ),
    unreachable(
        "groups.py",
        "_require_reconcilable",
        "group  is in , but the definition says ; a group's currency is fixed at "
        "creation",
        "raised only by apply_group_definition, which no route calls; it is an "
        "operator's refusal at a terminal and not an HTTP body",
    ),
    unreachable(
        "groups.py",
        "_require_reconcilable",
        "group  holds more than one member whose name matches after normalisation "
        "(), so which row the definition means cannot be decided here; the ids tell "
        "them apart",
        "raised only by apply_group_definition, which no route calls; the ids are the "
        "whole content of this refusal and its reader is the operator running the "
        "setup command",
    ),
    unreachable(
        "groups.py",
        "_require_reconcilable",
        "group  holds the member(s) , which the definition does not list; removing a "
        "member is member departure, which v1 cuts, so nothing was written",
        "raised only by apply_group_definition, which no route calls. It is also the "
        "guard that makes rows 3, 4, 7 and 10 of the spec unreachable: there is no "
        "member-deletion path anywhere in src/ or scripts/",
    ),
    unreachable(
        "groups.py",
        "link_user_to_member",
        "member  belongs to group , not to group , so it cannot be linked through it",
        "raised only by link_user_to_member, which is what setup_group.py link calls "
        "and the only thing in the repository that links a user to a member; no route "
        "calls it",
    ),
    unreachable(
        "groups.py",
        "link_user_to_member",
        "member  is already linked to user , so it cannot be linked to user ; v1 has "
        "no account handover",
        "raised only by link_user_to_member, which has no route; an operator at a "
        "terminal needs both ids to see which link already exists",
    ),
    unreachable(
        "groups.py",
        "link_user_to_member",
        "member  of group  is already linked to user , so member  cannot be",
        "raised only by link_user_to_member, which has no route; it is the same "
        "operator-facing refusal one field over",
    ),
    Site(
        # The one of the twelve whose sentence reaches no screen today: app/api.js
        # classifies 403 member_not_linked as not-linked and speaks() returns false
        # for that kind, so `say` is ''. It reaches the wire and the network panel.
        "groups.py",
        "acting_member",
        "no member of this group is linked to your account; an operator links a "
        "member with 'setup_group.py link'",
        Drive("GET", "/api/members", "member_not_linked", who="unlinked"),
    ),
    # --- money.py ----------------------------------------------------------
    unreachable(
        "money.py",
        "__post_init__",
        "currency code must be three uppercase A-Z letters: ",
        "no request names a currency: the only Currency the app builds comes from the "
        "group row, which store.Group validated when setup_group.py wrote it",
    ),
    unreachable(
        "money.py",
        "_require_same_currency",
        "cannot combine  and ",
        "it needs arithmetic between two Money values in different currencies, and "
        "every amount in a request is parsed in the group's own currency",
    ),
    Site(
        "money.py",
        "parse_amount",
        "not a valid amount: ",
        Drive(
            "POST",
            EXPENSES,
            "invalid_amount",
            {
                "description": "Milk",
                "amount": "twelve fifty",
                "payer_id": "{Sam}",
                "split": {"mode": "equal", "member_ids": ["{Sam}"]},
            },
        ),
    ),
    Site(
        "money.py",
        "parse_amount",
        "amount has no digits: ",
        Drive(
            "POST",
            EXPENSES,
            "invalid_amount",
            {
                "description": "Milk",
                "amount": "$",
                "payer_id": "{Sam}",
                "split": {"mode": "equal", "member_ids": ["{Sam}"]},
            },
        ),
    ),
    Site(
        "money.py",
        "parse_amount",
        "amount has more than  fractional digits and would have to be rounded: ",
        Drive(
            "POST",
            EXPENSES,
            "invalid_amount",
            {
                "description": "Milk",
                "amount": "12.505",
                "payer_id": "{Sam}",
                "split": {"mode": "equal", "member_ids": ["{Sam}"]},
            },
        ),
    ),
    Site(
        "money.py",
        "parse_amount",
        "amount is too large to store: ",
        Drive(
            "POST",
            EXPENSES,
            "invalid_amount",
            {
                "description": "Milk",
                "amount": str(money.MAX_CENTS),
                "payer_id": "{Sam}",
                "split": {"mode": "equal", "member_ids": ["{Sam}"]},
            },
        ),
    ),
    unreachable(
        "money.py",
        "_to_cents",
        "amount is not a whole number of cents: ",
        "parse_amount is _to_cents' only caller and refuses a fraction longer than "
        "MINOR_UNITS digits two lines earlier, so scaling by MINOR_UNITS is always "
        "exact and this branch needs a caller inside money.py",
    ),
    # --- simplify.py -------------------------------------------------------
    unreachable(
        "simplify.py",
        "_cents",
        "cannot combine  and :  is in  and the balances are in ",
        "it needs balances holding two currencies, which spec.md's frozen group "
        "currency and store._require_group_currency together make impossible to store",
    ),
    # --- split.py ----------------------------------------------------------
    Site(
        "split.py",
        "split_exact",
        "the shares add up to , but the total is ",
        Drive(
            "POST",
            EXPENSES,
            "invalid_split",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "exact", "amounts": {"{Sam}": "8.00"}},
            },
        ),
    ),
    Site(
        "split.py",
        "_allocate",
        "weights sum to zero, so there is no share to divide the total into",
        Drive(
            "POST",
            EXPENSES,
            "invalid_split",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "weight", "weights": {"{Sam}": 0, "{Ali}": 0}},
            },
        ),
    ),
    Site(
        "split.py",
        "_require_total",
        "the amount must be more than zero, but it is ",
        Drive(
            "POST",
            EXPENSES,
            "invalid_split",
            {
                "description": "Milk",
                "amount": "0.00",
                "payer_id": "{Sam}",
                "split": {"mode": "equal", "member_ids": ["{Sam}"]},
            },
        ),
    ),
    unreachable(
        "split.py",
        "_require_total",
        "the amount is too large to record: ",
        "money.parse_amount enforces the same MAX_CENTS bound and _create_expense "
        "parses the amount before the resolver sees it, so a total above the bound is "
        "an invalid_amount and never reaches this guard",
    ),
    unreachable(
        "split.py",
        "_require_member_id",
        "member id must be a non-empty id",
        "web._require_member_id checks every id against the roster first and no roster "
        "holds the empty string, so an empty id is a malformed_request before the "
        "resolver is called",
    ),
    Site(
        "split.py",
        "_ordered_from_iterable",
        "a split needs at least one member",
        Drive(
            "POST",
            EXPENSES,
            "invalid_split",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "equal", "member_ids": []},
            },
        ),
    ),
    Site(
        # Spec row 1. It spelled the whole member_ids list into a 400 body.
        "split.py",
        "_ordered_from_iterable",
        "member_ids names a member more than once",
        Drive(
            "POST",
            EXPENSES,
            "invalid_split",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "equal", "member_ids": ["{Sam}", "{Sam}"]},
            },
        ),
    ),
    Site(
        "split.py",
        "_ordered_from_mapping",
        "a split needs at least one member",
        Drive(
            "POST",
            EXPENSES,
            "invalid_split",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "exact", "amounts": {}},
            },
        ),
    ),
    Site(
        # Spec row 2, driven through weight mode. Exact mode cannot reach it:
        # money.parse_amount refuses every signed string before split_exact sees one.
        # The wire accepts weights even though no screen sends them, which is what
        # makes this row driven rather than declared unreachable.
        "split.py",
        "_ordered_from_mapping",
        "every  must be zero or positive",
        Drive(
            "POST",
            EXPENSES,
            "invalid_split",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "weight", "weights": {"{Sam}": -1, "{Ali}": 2}},
            },
        ),
    ),
    # --- store.py ----------------------------------------------------------
    unreachable("store.py", "_require_id", " must be a non-empty id", STORED_VALUE),
    Site(
        # Driven since 2026-09-08. This row was marked NO_REQUEST_REACHES_IT with
        # STORED_VALUE as its reason, and the guard in tests/conftest.py reached it on
        # its first run against real requests: STORED_VALUE enumerates ids, amounts
        # and addresses, and a display name is none of those and arrives in the
        # request body. The message names the field and no identifier, so nothing
        # shipped was ever wrong; the mark was.
        "store.py",
        "_require_name",
        " must not be blank",
        Drive(
            "POST",
            SIGNUP,
            "invalid_record",
            {
                "email": "new@example.com",
                "display_name": "   ",
                "password": PASSWORD,
            },
            who="anonymous",
        ),
    ),
    unreachable(
        "store.py", "_require_name", " must be at most  characters, got ", STORED_VALUE
    ),
    unreachable("store.py", "_require_email", " must not be empty", STORED_VALUE),
    unreachable(
        "store.py",
        "_require_email",
        " must be lowercase, got ",
        "accounts.normalise_email lower-cases every address before the store sees it, "
        "so a mixed-case one cannot arrive through signup or sign-in",
    ),
    unreachable(
        "store.py",
        "_require_token_hash",
        " must be  lowercase hex characters, got  characters",
        "every token hash the store is given is accounts._hash_token's own sha256 "
        "hexdigest, so its shape is decided in the process and not by a request",
    ),
    unreachable(
        "store.py",
        "_require_utc",
        " must be timezone-aware, got naive ",
        "every instant the store is given is web._now(), which is "
        "datetime.now(timezone.utc); a naive one needs a caller inside the process",
    ),
    unreachable(
        "store.py",
        "_require_storable_cents",
        " is , above MAX_CENTS (), the largest value the cents column can hold",
        "money.parse_amount refuses anything above MAX_CENTS at the input edge, so no "
        "request reaches the column's own bound. This is #39's recorded leftover: a "
        "400 naming raw cents, unreachable and left recorded rather than reworded",
    ),
    unreachable(
        "store.py",
        "__post_init__",
        "Session expires_at must be later than created_at, got  against ",
        "both instants come from accounts.log_in, which builds expires_at as the "
        "created_at it was given plus SESSION_LIFETIME",
    ),
    unreachable(
        "store.py",
        "_reading",
        " failed: ",
        "it wraps a real sqlite3.Error on a read, which needs a damaged or locked "
        "database file rather than any shape of request",
    ),
    unreachable(
        "store.py",
        "_writing",
        " failed: ",
        "it wraps a real sqlite3.Error on a write, and every foreign key a route "
        "supplies is checked against the roster or the ledger before the write",
    ),
    unreachable(
        "store.py",
        "_require_free",
        None,
        "the message is composed by whoever calls it, and the only way past the "
        "existence check above each call is the losing racer of two concurrent "
        "signups for one address, which web._signup catches and re-raises",
    ),
    unreachable(
        "store.py",
        "_require_group",
        "no group with id ",
        "every append_* call passes flask.g.group.id, which groups.resolve_sole_group "
        "read out of the same store moments earlier",
    ),
    unreachable(
        "store.py",
        "_require_group_currency",
        "no group with id ",
        "same as _require_group: the group id an append_* call carries is one the "
        "store itself just handed the request",
    ),
    unreachable(
        "store.py",
        "_require_group_currency",
        "group  is denominated in , so it cannot hold an event in ",
        "every event a route builds carries flask.g.group.currency, so a mismatch "
        "needs a second currency spec.md does not allow a group to have",
    ),
    unreachable(
        "store.py",
        "set_member_user",
        "no member with id ",
        "set_member_user is called only by groups.link_user_to_member, which has no "
        "route: setup_group.py link is its one caller",
    ),
    unreachable(
        "store.py",
        "set_member_user",
        "no user with id ",
        "same as the row above: no route calls set_member_user, so neither of its two "
        "existence checks is reachable over HTTP",
    ),
    unreachable(
        "store.py",
        "set_member_user",
        "member  is already linked to user , so it cannot be linked to user ",
        "no route calls set_member_user; groups.link_user_to_member refuses this first "
        "anyway, and its reader is the operator running the setup command",
    ),
    unreachable(
        "store.py",
        "set_member_user",
        "member  of group  is already linked to user , so member  cannot be",
        "no route calls set_member_user; this is the same operator-facing refusal one "
        "field over, and setup_group.py is its only reader",
    ),
    unreachable(
        "store.py",
        "delete_sessions_for_user",
        "no user with id ",
        "its only caller is accounts.log_out_everywhere, which no row of _API_ROUTES "
        "serves; DELETE /api/session calls log_out instead",
    ),
    unreachable(
        "store.py",
        "get_user",
        "no user with id ",
        "web._read_session passes flask.g.session.user_id, and a live session row "
        "points at a live user because nothing in the product deletes a user",
    ),
    unreachable(
        "store.py",
        "get_group",
        "no group with id ",
        "groups.acting_member passes the id groups.resolve_sole_group just read out of "
        "the same store, so the group is there by construction",
    ),
    unreachable(
        "store.py",
        "get_member",
        "no member with id ",
        "no route calls get_member: the roster arrives through list_members, and "
        "link_user_to_member is the only other caller and has no route",
    ),
    unreachable(
        "store.py",
        "get_user_by_email",
        "no user with email ",
        "accounts.log_in catches RecordNotFound and answers through _fail_login, and "
        "accounts.sign_up expects it, so this message never becomes a body",
    ),
    unreachable(
        "store.py",
        "get_password_hash",
        "no password hash for user with id ",
        "accounts.log_in catches RecordNotFound from it and answers through "
        "_fail_login; its other caller, change_password, has no route",
    ),
    unreachable(
        "store.py",
        "get_session",
        "no session with token hash ",
        "accounts.authenticate catches RecordNotFound and raises SessionInvalid "
        "instead, so what reaches the wire is that token does not name a live session",
    ),
    unreachable(
        "store.py",
        "get_member_for_user",
        "no member of group  is linked to user ",
        "groups.acting_member catches RecordNotFound from it and raises "
        "MemberNotLinked instead, which is the row this task reworded",
    ),
    unreachable(
        "store.py",
        "get_expense",
        "no expense with id ",
        "no route reads one expense by id: _API_ROUTES has no /api/expenses/<id> row "
        "and the feed arrives through list_expenses",
    ),
    unreachable(
        "store.py",
        "list_settlement_decisions",
        "no settlement with id ",
        "nothing in src/ calls list_settlement_decisions at all: web.py derives every "
        "settlement state from the whole ledger through list_events",
    ),
    # --- web.py ------------------------------------------------------------
    Site(
        "web.py",
        "check",
        "too many failed attempts; wait a few minutes and try again",
        Drive(
            "POST",
            SESSION,
            "too_many_attempts",
            {"email": "nobody@example.com", "password": PASSWORD},
            who="anonymous",
            setup="budget",
        ),
    ),
    Site(
        "web.py",
        "_check_csrf",
        "a state-changing request must be sent as ",
        Drive(
            "POST",
            SIGNUP,
            "csrf_failed",
            raw="{}",
            content_type="text/plain",
            who="anonymous",
        ),
    ),
    Site(
        "web.py",
        "_check_csrf",
        "a state-changing request must repeat the  cookie in the  header",
        Drive("POST", SIGNUP, "csrf_failed", {}, who="anonymous", csrf="absent"),
    ),
    Site(
        "web.py",
        "_check_csrf",
        "the  header does not match the  cookie",
        Drive("POST", SIGNUP, "csrf_failed", {}, who="anonymous", csrf="mismatched"),
    ),
    Site(
        "web.py",
        "_check_csrf",
        "that request came from another origin",
        Drive(
            "POST",
            SIGNUP,
            "csrf_failed",
            {},
            who="anonymous",
            origin="https://not-this-origin.example",
        ),
    ),
    Site(
        "web.py",
        "_json_object",
        "the request body is not valid JSON",
        Drive("POST", SIGNUP, "malformed_request", raw="{not json", who="anonymous"),
    ),
    Site(
        "web.py",
        "_json_object",
        "the request body must be a JSON object",
        Drive("POST", SIGNUP, "malformed_request", raw="[]", who="anonymous"),
    ),
    Site(
        "web.py",
        "_require_keys",
        " is missing the key ",
        Drive(
            "POST",
            SIGNUP,
            "malformed_request",
            {"email": "new@example.com", "display_name": "New"},
            who="anonymous",
        ),
    ),
    Site(
        "web.py",
        "_require_keys",
        " has an unrecognised key ",
        Drive(
            "POST",
            SIGNUP,
            "malformed_request",
            {
                "email": "new@example.com",
                "display_name": "New",
                "password": PASSWORD,
                "id": "chosen-by-the-client",
            },
            who="anonymous",
        ),
    ),
    Site(
        "web.py",
        "_require_str",
        " key  must be a JSON string",
        Drive(
            "POST",
            SIGNUP,
            "malformed_request",
            {"email": 12, "display_name": "New", "password": PASSWORD},
            who="anonymous",
        ),
    ),
    Site(
        "web.py",
        "_require_amount_str",
        " key  must be an amount as a JSON string, such as \"12.50\"; amounts are "
        "strings, never numbers",
        Drive(
            "POST",
            EXPENSES,
            "malformed_request",
            {
                "description": "Milk",
                "amount": 1250,
                "payer_id": "{Sam}",
                "split": {"mode": "equal", "member_ids": ["{Sam}"]},
            },
        ),
    ),
    Site(
        "web.py",
        "_require_object",
        " key  must be a JSON object",
        Drive(
            "POST",
            EXPENSES,
            "malformed_request",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": ["equal"],
            },
        ),
    ),
    Site(
        "web.py",
        "_require_list",
        " key  must be a JSON array",
        Drive(
            "POST",
            EXPENSES,
            "malformed_request",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "equal", "member_ids": "{Sam}"},
            },
        ),
    ),
    Site(
        "web.py",
        "_authenticate",
        "this endpoint needs a signed-in session",
        Drive("GET", "/api/members", "not_authenticated", who="anonymous"),
    ),
    Site(
        # Driven since 2026-09-08. Marked NO_REQUEST_REACHES_IT until the guard in
        # tests/conftest.py reached it. The old reason was right that no single
        # request produces the state and wrong about what the marker claims: the
        # marker says no client can ever be shown this message, and given the state a
        # request does produce exactly this response. The message names an address,
        # which is the person's own typed input and not in the identifier set.
        "web.py",
        "_signup",
        "an account already exists for ",
        Drive(
            "POST",
            SIGNUP,
            "email_already_registered",
            {
                "email": "racer@example.com",
                "display_name": "Racer",
                "password": PASSWORD,
            },
            who="anonymous",
            setup="racing_signup",
        ),
    ),
    Site(
        # Spec row 3.
        "web.py",
        "_create_expense",
        " names a payer_id that is not a member of this group",
        Drive(
            "POST",
            EXPENSES,
            "malformed_request",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": NOT_IN_THE_ROSTER,
                "split": {"mode": "equal", "member_ids": ["{Sam}"]},
            },
        ),
    ),
    Site(
        "web.py",
        "_resolve_split",
        " is missing the key 'mode'",
        Drive(
            "POST",
            EXPENSES,
            "malformed_request",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"member_ids": ["{Sam}"]},
            },
        ),
    ),
    Site(
        "web.py",
        "_resolve_split",
        " mode must be one of 'equal', 'weight' or 'exact', got ",
        Drive(
            "POST",
            EXPENSES,
            "malformed_request",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "percentage"},
            },
        ),
    ),
    Site(
        "web.py",
        "_require_member_id",
        "a split names a member id that is not a JSON string",
        Drive(
            "POST",
            EXPENSES,
            "malformed_request",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "equal", "member_ids": [12]},
            },
        ),
    ),
    Site(
        # Spec row 4, the one the PR #62 reviewer found.
        "web.py",
        "_require_member_id",
        "a split names a member id that is not a member of this group",
        Drive(
            "POST",
            EXPENSES,
            "malformed_request",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "equal", "member_ids": [NOT_IN_THE_ROSTER]},
            },
        ),
    ),
    Site(
        # Spec row 5: its key was a member id of the current roster, so unlike rows 3,
        # 4, 7 and 10 it did not need the roster to have moved.
        "web.py",
        "_require_weight",
        "every weight in a split must be a JSON integer",
        Drive(
            "POST",
            EXPENSES,
            "malformed_request",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "weight", "weights": {"{Sam}": 1.5}},
            },
        ),
    ),
    Site(
        # Spec row 6, the other half of the same finding.
        "web.py",
        "_require_exact_amount",
        "every exact amount in a split must be an amount as a JSON string, such as "
        "\"8.00\"; amounts are strings, never numbers",
        Drive(
            "POST",
            EXPENSES,
            "malformed_request",
            {
                "description": "Milk",
                "amount": "10.00",
                "payer_id": "{Sam}",
                "split": {"mode": "exact", "amounts": {"{Sam}": 1000}},
            },
        ),
    ),
    Site(
        # Spec row 7.
        "web.py",
        "_create_settlement",
        " names a to_member_id that is not a member of this group",
        Drive(
            "POST",
            SETTLEMENTS,
            "malformed_request",
            {"to_member_id": NOT_IN_THE_ROSTER, "amount": "1.00"},
        ),
    ),
    Site(
        # Spec row 8: the caller never sent a payer, so the sentence now says where
        # the payer comes from instead of naming the member it resolved to.
        "web.py",
        "_create_settlement",
        "a member cannot record a payment to themselves; the payer is whoever is "
        "signed in",
        Drive(
            "POST",
            SETTLEMENTS,
            "malformed_request",
            {"to_member_id": "{Sam}", "amount": "1.00"},
        ),
    ),
    Site(
        "web.py",
        "_create_settlement",
        " amount must be more than zero, got ",
        Drive(
            "POST",
            SETTLEMENTS,
            "malformed_request",
            {"to_member_id": "{Ali}", "amount": "0.00"},
        ),
    ),
    Site(
        "web.py",
        "_create_settlement",
        "a payment to that person is already marked as paid and is waiting for them "
        "to confirm it; there can be only one at a time",
        Drive(
            "POST",
            SETTLEMENTS,
            "settlement_already_pending",
            {"to_member_id": "{Ali}", "amount": "1.00"},
            setup="pending",
        ),
    ),
    Site(
        "web.py",
        "_decide_settlement",
        " key 'decision' must be one of , and 'pending' is not a decision",
        Drive(
            "POST",
            "/api/settlements/{settlement}/decision",
            "malformed_request",
            {"decision": "pending"},
            setup="pending",
        ),
    ),
    Site(
        # Spec row 9. It named the settlement id the caller had just asked about.
        "web.py",
        "_decide_settlement",
        "no settlement in this group with that id",
        Drive(
            # The group's own id again: no settlement has it, and if the settlement id
            # ever comes back into this message the identifier set can see it.
            "POST",
            "/api/settlements/{group}/decision",
            "record_not_found",
            {"decision": "confirmed"},
        ),
    ),
    Site(
        "web.py",
        "_decide_settlement",
        "only the person the payment was made to can answer it; a payment cannot be "
        "confirmed or rejected by whoever marked it as paid",
        Drive(
            "POST",
            "/api/settlements/{settlement}/decision",
            "not_the_receiver",
            {"decision": "confirmed"},
            setup="pending",
        ),
    ),
    Site(
        "web.py",
        "_decide_settlement",
        "that payment has already been answered, and an answer cannot be taken back",
        Drive(
            "POST",
            "/api/settlements/{settlement}/decision",
            "settlement_already_decided",
            {"decision": "confirmed"},
            who="receiver",
            setup="decided",
        ),
    ),
    Site(
        # Driven since 2026-09-08. Marked NO_REQUEST_REACHES_IT until the guard in
        # tests/conftest.py reached it. _SETTLEMENT_LOCK is honestly scoped to one
        # process, so the two-claim state is the state this defensive raise exists
        # for rather than a test artefact, and a mark claiming nothing reaches it is
        # the wrong description of a guard that exists because something might. The
        # message names nobody and no identifier.
        "web.py",
        "_decide_settlement",
        "there is more than one payment from that person waiting for an answer, so "
        "confirming one of them would be a guess; reject the one that is not real and "
        "then confirm the one that is",
        Drive(
            "POST",
            "/api/settlements/{settlement}/decision",
            "settlement_already_pending",
            {"decision": "confirmed"},
            who="receiver",
            setup="two_pending",
        ),
    ),
    Site(
        # Spec row 10, the one row where the position is worth naming: the path has
        # two segments and a constant sentence would not say which was refused.
        "web.py",
        "_read_debt",
        "a debt path names a  that is not a member of this group",
        Drive("GET", "/api/debts/{group}/{Sam}", "malformed_request"),
    ),
    Site(
        # Spec row 11.
        "web.py",
        "_read_debt",
        "a member cannot owe themselves; the debtor and the creditor in the path are "
        "the same member",
        Drive("GET", "/api/debts/{Sam}/{Sam}", "malformed_request"),
    ),
)


DRIVEN: Final = tuple(
    site for site in FOUR_HUNDRED_SITES if isinstance(site.drive, Drive)
)
MARKED: Final = tuple(
    site for site in FOUR_HUNDRED_SITES if not isinstance(site.drive, Drive)
)


def site_id(site: Site) -> str:
    """A parametrisation id that names the site, so a failure says which one leaked."""
    words = re.sub(r"[^a-z0-9]+", "_", (site.skeleton or "composed").lower())
    return f"{site.module}::{site.function}::{words.strip('_')[:48]}"


# --- Driving one row --------------------------------------------------------


def filled(value: Any, names: dict[str, str]) -> Any:
    """``value`` with every ``{Name}`` placeholder replaced by the id it stands for.

    Recursive over dicts and lists, and over dict keys as well as values, because a
    weight or an exact amount is keyed by member id. Non-strings pass through
    untouched, so a row can send the JSON number a guard is about.
    """
    if isinstance(value, str):
        return value.format_map(names)
    if isinstance(value, dict):
        return {filled(key, names): filled(item, names) for key, item in value.items()}
    if isinstance(value, list):
        return [filled(item, names) for item in value]
    return value


def spend_the_login_budget(app) -> None:
    """Spend one client address's failure budget, spread over enough addresses that no
    single email bucket fills first."""
    client = app.test_client()
    for index in range(web.LOGIN_LIMIT_PER_ADDRESS):
        refused = post(
            client,
            SESSION,
            {"email": f"nobody{index // 5}@example.com", "password": PASSWORD},
        )
        assert refused.status_code == 401, refused.get_json()


def mark_one_payment(app, path: Path) -> str:
    """Sam marks a payment to Ali, and the settlement's id comes back."""
    sam = linked_client(app, path, "Sam")
    names = roster_names(path)
    recorded = post(
        sam, SETTLEMENTS, {"to_member_id": names["Ali"], "amount": "1.00"}
    )
    assert recorded.status_code == 201, recorded.get_json()
    return recorded.get_json()["settlement"]["id"]


def mark_two_payments(app, path: Path) -> str:
    """Sam marks a payment to Ali, and a second unanswered claim for that pair exists.

    The second one goes straight through the store, because one process cannot make
    it through the endpoint: task 14's 409 refuses a second claim and
    ``web._SETTLEMENT_LOCK`` makes that refusal exact **within one process**. Two
    processes hold two locks and the window reopens, which is the state the
    confirm-side count exists for. So the state is the product's, not the test's, and
    what this helper fabricates is only the second process.
    """
    settlement = mark_one_payment(app, path)
    names = roster_names(path)
    with open_store(path) as store:
        group = resolve_sole_group(store)
        store.append_settlement(
            SettlementEvent(
                id=SettlementId("a-second-unanswered-claim"),
                group_id=GroupId(group.id),
                currency=money.Currency(CURRENCY),
                from_member_id=MemberId(names["Sam"]),
                to_member_id=MemberId(names["Ali"]),
                amount_cents=100,
                created_at=at(13),
                created_by=MemberId(names["Sam"]),
            )
        )
    return settlement


def racing_sign_up(*arguments: Any, **keywords: Any) -> None:
    """``accounts.sign_up`` losing a race for one address.

    The address was free when it was checked and taken by the time the row was
    written, which is a second process's signup landing in between. ``web._signup``
    answers that with the same 409 a plain duplicate gets, and that answer is the row
    this stands in for. Installed only for the one request that needs it.
    """
    raise DuplicateRecord("a user with that email already exists")


def answer_one_payment(app, path: Path) -> str:
    """Sam marks a payment to Ali and Ali confirms it, so it is already answered."""
    settlement = mark_one_payment(app, path)
    ali = linked_client(app, path, "Ali")
    answered = post(
        ali, f"/api/settlements/{settlement}/decision", {"decision": "confirmed"}
    )
    assert answered.status_code == 200, answered.get_json()
    return settlement


SETUPS: Final = (
    "none",
    "budget",
    "pending",
    "decided",
    "two_pending",
    "racing_signup",
)
"""Every state a row can ask for before its request, and the whole of the vocabulary.

It grew by two on 2026-09-08, when the guard in tests/conftest.py found three rows
marked NO_REQUEST_REACHES_IT that a request reaches. Two of those three need a state
no sequence of requests builds in one process: a second unanswered claim for one
ordered pair, and a signup that loses a race for its address. Neither is expressible
as a request, so the vocabulary grew rather than the rows staying unchecked. A value
not listed here is refused in :func:`drive`, so the vocabulary stays closed.
"""


def client_for(who: str, app, path: Path):
    """The client a row's ``who`` names."""
    if who == "anonymous":
        return app.test_client()
    if who == "stale":
        # A session cookie naming no live session, which is what a signed-in browser
        # holds after the row behind it expired or was deleted.
        client = app.test_client()
        client.set_cookie(web.SESSION_COOKIE, "this-token-names-no-live-session")
        return client
    if who == "unlinked":
        return unlinked_client(app)
    if who == "receiver":
        return linked_client(app, path, "Ali")
    assert who == "linked", f"no client kind named {who!r}"
    return linked_client(app, path, "Sam")


def drive(site: Site, app, path: Path, before: Any = None):
    """Make the one request ``site`` declares, and return the response.

    ``before`` runs immediately before that one request and after everything the
    row's ``who`` and ``setup`` do. A caller watching what a request is answered with
    clears its record there, so the refusals a row's own setup produces are not
    attributed to the row.
    """
    drive_row = site.drive
    assert isinstance(drive_row, Drive)

    names = dict(roster_names(path))
    assert drive_row.setup in SETUPS, f"no setup named {drive_row.setup!r}"
    if drive_row.setup == "budget":
        spend_the_login_budget(app)
    elif drive_row.setup == "pending":
        names["settlement"] = mark_one_payment(app, path)
    elif drive_row.setup == "decided":
        names["settlement"] = answer_one_payment(app, path)
    elif drive_row.setup == "two_pending":
        names["settlement"] = mark_two_payments(app, path)

    client = client_for(drive_row.who, app, path)
    headers: dict[str, str] = {}
    if drive_row.csrf == "correct":
        headers[web.CSRF_HEADER] = csrf_token(client)
    elif drive_row.csrf == "mismatched":
        csrf_token(client)
        headers[web.CSRF_HEADER] = "not-the-token-in-the-cookie"
    else:
        assert drive_row.csrf == "absent", f"no csrf kind named {drive_row.csrf!r}"
        csrf_token(client)
    if drive_row.origin is not None:
        headers["Origin"] = drive_row.origin

    target = drive_row.path.format_map(names)
    request: dict[str, Any] = {"method": drive_row.method, "headers": headers}
    if drive_row.raw is not None:
        request["data"] = drive_row.raw
        request["content_type"] = drive_row.content_type or "application/json"
    elif drive_row.payload is not None:
        request["json"] = filled(drive_row.payload, names)
    with contextlib.ExitStack() as during:
        if drive_row.setup == "racing_signup":
            # The one setup that has to be in place *while* the request runs rather
            # than before it, because what it stands in for is a second process
            # landing between the check and the write.
            patched = during.enter_context(pytest.MonkeyPatch.context())
            patched.setattr(web.accounts, "sign_up", racing_sign_up)
        # Everything above is setup, and some of it is refused. The row's own request
        # is the next line, and it is the only one a caller watching answers wants.
        if before is not None:
            before()
        return client.open(target, **request)


# --- Check A: the enumeration is complete in both directions ----------------


def missing_rows_message(undeclared: set[Key], stale: set[Key]) -> str:
    """What went wrong, with the offending keys named."""
    parts = []
    if undeclared:
        parts.append(
            "These 4xx raise sites are in src/splitwise_lite/ and have no row in "
            "FOUR_HUNDRED_SITES:\n"
            + "\n".join(f"  {key!r}" for key in sorted(map(str, undeclared)))
            + "\n\nAdd one row each. If the message can carry a member id, a user id, "
            "a group id, an expense id, a settlement id or an event id, reword it "
            "first: no 4xx body this repo sends names one (issue #61). Then either "
            "drive it or mark it NO_REQUEST_REACHES_IT with a reason of at least "
            f"{MIN_REASON} characters saying what would have to be true for a request "
            "to reach it."
        )
    if stale:
        parts.append(
            "These rows of FOUR_HUNDRED_SITES name a site that is no longer there:\n"
            + "\n".join(f"  {key!r}" for key in sorted(map(str, stale)))
            + "\n\nA reworded message changes its skeleton, which is the point: the "
            "row is the record of somebody having decided what that sentence may "
            "contain. Update the skeleton to the new wording, or delete the row if "
            "the raise is gone."
        )
    return "\n\n".join(parts)


def test_every_four_hundred_raise_site_is_declared() -> None:
    """An equality, in both directions, over every 4xx raise site in the package.

    Not a scan for suspicious names: an equality between two sets, which is the shape
    ``web._audit_routes`` and ``test_the_harness_reports_exactly_the_declared_scenarios``
    already use in this repo. It has no false positives, because it judges no value. A
    new 4xx raise anywhere in ``src/splitwise_lite/`` fails until somebody adds a row,
    and a row for a site that no longer exists fails too.
    """
    walked = four_hundred_raise_sites()
    declared = {site.key for site in FOUR_HUNDRED_SITES}
    assert walked, "the ast walk found no 4xx raise site at all, so this checks nothing"
    assert len(declared) == len(FOUR_HUNDRED_SITES), (
        "two rows of FOUR_HUNDRED_SITES share a key, so one of them is dead weight "
        "and the equality below would pass with a site uncovered."
    )
    assert walked == declared, missing_rows_message(walked - declared, declared - walked)


def test_the_skeleton_of_a_message_drops_its_interpolations() -> None:
    """The key is stable under reflowing and changes only when the wording changes."""
    one_line = ast.parse(
        'raise MalformedRequest(f"{what} names a payer_id that is not a member of '
        'this group")'
    )
    wrapped = ast.parse(
        "raise MalformedRequest(\n"
        '    f"{what} names a payer_id that is not "\n'
        '    f"a member of this group"\n'
        ")"
    )
    expected = " names a payer_id that is not a member of this group"
    for tree in (one_line, wrapped):
        raised = tree.body[0]
        assert isinstance(raised, ast.Raise)
        assert isinstance(raised.exc, ast.Call)
        assert message_skeleton(raised.exc.args[0], web) == expected

    # A plain string is its own skeleton, and a message composed elsewhere has none.
    plain = ast.parse('raise MalformedRequest("a split needs at least one member")')
    assert isinstance(plain.body[0], ast.Raise)
    assert message_skeleton(plain.body[0].exc.args[0], web) == (
        "a split needs at least one member"
    )
    composed = ast.parse("raise DuplicateRecord(message)")
    assert isinstance(composed.body[0], ast.Raise)
    assert message_skeleton(composed.body[0].exc.args[0], web) is None
    # And a module-level constant resolves to the sentence it holds.
    constant = ast.parse("raise TooManyAttempts(_TOO_MANY_ATTEMPTS_MESSAGE)")
    assert isinstance(constant.body[0], ast.Raise)
    assert message_skeleton(constant.body[0].exc.args[0], web) == (
        "too many failed attempts; wait a few minutes and try again"
    )


# --- Check B, part one: the pure function bites -----------------------------
#
# Four unit tests over identifiers_in, in the style of test_suite_integrity.py's own
# self-tests. This is what shows the property half can fail: a function that returned
# [] for everything would pass every driven row below and prove nothing at all.


def test_identifiers_in_finds_an_identifier_that_is_present() -> None:
    """The whole point: an id in the message is reported."""
    assert identifiers_in(
        "no member of group 'grp-12345678' is linked", ("grp-12345678",)
    ) == ["grp-12345678"]


def test_identifiers_in_finds_nothing_in_an_id_free_message() -> None:
    """And an id-free sentence reports nothing, so the check is not simply total."""
    assert (
        identifiers_in(
            "an expense body names a payer_id that is not a member of this group",
            ("mem-12345678", "grp-12345678"),
        )
        == []
    )


def test_identifiers_in_finds_an_identifier_wrapped_in_punctuation() -> None:
    """A quoted id mid-sentence is still an id.

    This is the case a word-boundary or whitespace-split search gets wrong, and every
    one of the twelve sites spelled its id with ``!r``, so every one of them arrived
    exactly like this.
    """
    assert identifiers_in(
        "a split names a member id that is not a member of this group: "
        "'mem-12345678'.",
        ("mem-12345678",),
    ) == ["mem-12345678"]


def test_identifiers_in_reports_both_identifiers_when_two_are_present() -> None:
    """Two leaks are two findings, so a failure does not hide one behind the other."""
    assert identifiers_in(
        "no member of group 'grp-12345678' is linked to user 'usr-87654321'",
        ("grp-12345678", "usr-87654321", "mem-11111111"),
    ) == ["grp-12345678", "usr-87654321"]


# --- Check B, part two: the property, driven -------------------------------


@pytest.mark.parametrize("site", DRIVEN, ids=[site_id(s) for s in DRIVEN])
def test_no_four_hundred_body_names_an_identifier(site: Site, app, seeded: Path) -> None:
    """One request per reachable site: a 4xx, the row's code, and no identifier.

    The identifier set is gathered after the request, from the store, so it holds every
    id the server could possibly have interpolated, including the ids of anything the
    row's own setup created.
    """
    response = drive(site, app, seeded)
    body = response.get_json()
    assert response.status_code in range(400, 500), (site_id(site), body)
    assert body["error"]["code"] == site.drive.code, (site_id(site), body)
    message = body["error"]["message"]
    leaked = identifiers_in(message, stored_identifiers(seeded))
    assert leaked == [], (
        f"{site_id(site)} answered {response.status_code} with a message naming "
        f"{leaked}:\n\n  {message}\n\n"
        "No message this repo sends with a 4xx status carries an internal identifier "
        "(issue #61). Name the field the caller wrote, not the value it sent: the "
        "caller holds its own request body, so the field name is what tells it where "
        "to look. Two screens' rendering policies rest on this holding for the whole "
        "4xx surface."
    )


def test_stored_identifiers_gathers_every_id_the_store_holds(
    app, seeded: Path
) -> None:
    """The identifier set is complete by construction, not by anybody's list.

    Drives one whole shape of the product -- a group, a linked member, an unlinked
    account, an expense and a settlement -- and then asserts every id those wrote is
    in the set. An id the gatherer misses is a leak the driven rows above cannot see,
    which is why this is asserted rather than assumed.
    """
    sam = linked_client(app, seeded, "Sam")
    unlinked_client(app)
    names = roster_names(seeded)
    expense = post(
        sam,
        EXPENSES,
        {
            "description": "Milk",
            "amount": "10.00",
            "payer_id": names["Sam"],
            "split": {"mode": "equal", "member_ids": [names["Sam"], names["Ali"]]},
        },
    )
    assert expense.status_code == 201, expense.get_json()
    settlement = post(
        sam, SETTLEMENTS, {"to_member_id": names["Ali"], "amount": "1.00"}
    )
    assert settlement.status_code == 201, settlement.get_json()

    gathered = stored_identifiers(seeded)
    with open_store(seeded) as store:
        group = resolve_sole_group(store)
        members = store.list_members(group.id)
        events = store.list_events(group.id)
    with sqlite3.connect(seeded) as connection:
        users = [row[0] for row in connection.execute("SELECT id FROM users")]
    connection.close()

    assert group.id in gathered
    assert {member.id for member in members} <= set(gathered)
    assert {event.id for event in events} <= set(gathered)
    assert set(users) <= set(gathered)
    # The unlinked account is the one this has to hold for: no member row points at
    # it, so a set built from the roster alone would not contain it, and the
    # member_not_linked row above would pass while naming that user's id.
    assert len(users) == 2, users
    assert expense.get_json()["expense"]["id"] in gathered
    assert settlement.get_json()["settlement"]["id"] in gathered
    # No id is short enough to match an innocent substring, and none repeats.
    assert all(len(found) >= MIN_IDENTIFIER for found in gathered)
    assert len(set(gathered)) == len(gathered)


def test_every_site_no_request_reaches_says_what_would_have_to_be_true() -> None:
    """A marked row is a claim this module records, so the claim has to be legible.

    The same floor ``tests/test_suite_integrity.py`` puts under an ``# unanchored:``
    reason, and for the same reason: a marker with a shrug behind it is how a premise
    stops being checked without anybody noticing.
    """
    assert MARKED, (
        "no row is marked NO_REQUEST_REACHES_IT, so this check passes over nothing. "
        "If every site really is driven now, delete this test and the marker with it."
    )
    assert DRIVEN, "no row is driven, so the property half checks nothing."
    for site in MARKED:
        assert site.drive == NO_REQUEST_REACHES_IT, (
            f"{site_id(site)} carries neither a Drive nor the marker; a row is one or "
            "the other."
        )
        assert len(site.reason) >= MIN_REASON, (
            f"{site_id(site)} is marked NO_REQUEST_REACHES_IT with a reason of "
            f"{len(site.reason)} characters: {site.reason!r}. Say what would have to "
            f"be true for a request to be answered from it, in at least {MIN_REASON} "
            "characters. tests/conftest.py reds if one ever is, so this reason is what "
            "a reader compares that failure against."
        )
    for site in DRIVEN:
        assert site.reason == "", (
            f"{site_id(site)} is driven and also carries a reason. A driven row's "
            "evidence is the request, so the reason field stays empty and nobody has "
            "to wonder which one is true."
        )


# --- Check C, part one: the index the observer reads ------------------------
#
# tests/conftest.py states the predicate all of this serves, and states it once.
# Nothing here restates it; these check the machinery it reads.


def test_the_key_set_and_the_raise_site_index_come_from_one_walk() -> None:
    """Two views of one walk, so neither can drift from the other.

    Every key the enumeration equality compares has at least one span in the index,
    and every key the index yields is one of those. A second walk over the same files
    is the thing this refuses: two walks are two things to keep in step, and the whole
    value of the index is that it agrees with the table by construction.
    """
    spans = four_hundred_raise_spans()
    assert spans, (
        "the ast walk found no 4xx raise span at all, so the index is empty and every "
        "check that reads it passes over nothing"
    )
    assert {span.key for span in spans} == four_hundred_raise_sites()
    assert set(raise_site_index().values()) == four_hundred_raise_sites()
    for span in spans:
        assert raise_site_index()[(span.file, span.lineno)] == span.key


def test_the_index_finds_a_site_by_the_path_the_import_system_reports() -> None:
    """The path a traceback carries, not the one the walk happened to build.

    ``PACKAGE.glob`` and ``splitwise_lite.store.__file__`` are two spellings of one
    file, and on Windows two spellings of one file can differ in case or in a short
    name. If they ever stop comparing equal, the observer maps every frame to nothing,
    records nothing, and passes over an empty set forever. That is this instrument's
    characteristic silent failure, so the comparison is asserted rather than assumed.
    """
    store_module = importlib.import_module("splitwise_lite.store")
    spans = [span for span in four_hundred_raise_spans() if span.key[0] == "store.py"]
    assert spans, "no 4xx raise site in store.py, so this checks nothing"
    for span in spans:
        assert key_for_raise_site(store_module.__file__, span.lineno) == span.key


def test_the_index_maps_every_line_of_a_raise_spread_over_several_lines() -> None:
    """A raise reported at its last line is found as readily as one at its first.

    Python reports the line of the instruction that raised, which for a ``raise``
    wrapped across four lines is not reliably the ``raise`` keyword's own line.
    """
    wrapped = [
        span for span in four_hundred_raise_spans() if span.end_lineno > span.lineno
    ]
    assert wrapped, (
        "no 4xx raise in the package spans more than one line, so this checks "
        "nothing. If that is really so this test can go; until then an empty answer "
        "means the walk has stopped carrying end_lineno."
    )
    for span in wrapped:
        for lineno in range(span.lineno, span.end_lineno + 1):
            assert key_for_raise_site(str(span.file), lineno) == span.key


def test_three_raises_that_share_one_key_are_three_spans() -> None:
    """``accounts.authenticate`` refuses in three places with one sentence.

    One row in the table, because a key is a message. Three spans in the index,
    because a position is a statement. There is no special case for it in either.
    """
    key: Key = (
        "accounts.py",
        "authenticate",
        "that token does not name a live session",
    )
    assert key in four_hundred_raise_sites()
    spans = [span for span in four_hundred_raise_spans() if span.key == key]
    assert len(spans) == 3, [span.lineno for span in spans]
    assert len({span.lineno for span in spans}) == 3


def test_a_row_with_no_message_skeleton_is_indexed_by_position() -> None:
    """``store._require_free`` composes its message elsewhere, so its skeleton is None.

    The index is keyed by position rather than by message, so a row with no skeleton
    needs no special case. That is asserted here rather than left to be re-derived.
    """
    keys = [key for key in four_hundred_raise_sites() if key[2] is None]
    assert keys, "no row has a None skeleton, so this checks nothing"
    for key in keys:
        spans = [span for span in four_hundred_raise_spans() if span.key == key]
        assert spans, key
        for span in spans:
            assert key_for_raise_site(str(span.file), span.lineno) == key


def test_a_line_with_no_four_hundred_raise_on_it_names_no_row() -> None:
    """The index answers ``None`` rather than guessing, which is what makes it quiet.

    An implicit ``TypeError``, a werkzeug ``HTTPException`` and anything raised
    outside ``src/splitwise_lite/`` all arrive as a frame the index does not hold, and
    all three are ignored by the same one answer.
    """
    store_module = importlib.import_module("splitwise_lite.store")
    assert key_for_raise_site(store_module.__file__, 1) is None
    assert key_for_raise_site(__file__, 1) is None
    assert key_for_raise_site(str(REPO / "no" / "such" / "file.py"), 1) is None


def test_every_error_body_is_composed_inside_the_one_error_handler() -> None:
    """Every error body this application sends is composed in ``_handle_error``.

    That is what makes the observer in tests/conftest.py complete rather than
    partial: it wraps one function, and a body composed anywhere else would be an
    answer it never sees. A second error-body path is the one change that would blind
    the observer while leaving every other check in this module green, so it is
    refused here rather than assumed.

    This opens ``src/splitwise_lite/web.py`` and walks it, rather than asserting
    against an imported symbol or against a literal copied out of it. A check about a
    module that never opens that module is not a check about that module.

    Measured on this branch with ``rg -n "_error_body\\(" src/splitwise_lite/web.py``:
    one definition, at line 778, and three calls, at 2704, 2723 and 2725. Neither the
    count nor the lines are pinned, because moving a call within ``_handle_error`` is
    not a defect and taking one outside it is.
    """
    web_source = PACKAGE / "web.py"
    tree = ast.parse(web_source.read_text(encoding="utf-8"), filename=str(web_source))
    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_handle_error"
    ]
    assert len(handlers) == 1, (
        "src/splitwise_lite/web.py defines _handle_error "
        f"{len(handlers)} times, at lines {[node.lineno for node in handlers]}. The "
        "observer wraps one function by that name, so it can only be watching one of "
        "them."
    )
    definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_error_body"
    ]
    assert len(definitions) == 1, [node.lineno for node in definitions]

    inside = {id(node) for node in ast.walk(handlers[0]) if isinstance(node, ast.Call)}
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_error_body"
    ]
    assert calls, (
        "src/splitwise_lite/web.py holds no call to _error_body at all, so this "
        "check passes over nothing. Either an error body is composed some other way "
        "now, in which case tests/conftest.py's observer watches the wrong function, "
        "or this walk has stopped finding calls."
    )
    outside = [node for node in calls if id(node) not in inside]
    assert not outside, (
        "src/splitwise_lite/web.py calls _error_body outside _handle_error, at lines "
        f"{[node.lineno for node in outside]}.\n\n"
        "tests/conftest.py observes what a request is answered with by wrapping "
        "_handle_error, on the strength of every error body being composed there. A "
        "second path composes a body the observer never sees, so every row of "
        "FOUR_HUNDRED_SITES marked NO_REQUEST_REACHES_IT goes back to being a claim "
        "nothing checks, with the suite still green. Compose the body in "
        "_handle_error, or move the observer to whatever the new one place is."
    )


# --- Check C, part two: the observer is proved to work, on every run --------


@pytest.mark.parametrize("site", DRIVEN, ids=[site_id(s) for s in DRIVEN])
def test_each_driven_row_answers_from_the_site_it_declares(
    site: Site, app, seeded: Path, answered_requests: list[Any]
) -> None:
    """The 4xx a driven row gets back was raised at the site that row names.

    This is what makes the observer in tests/conftest.py believable, because it runs
    on every run rather than only when something is wrong. If the wrapper is not
    installed, or records nothing, or maps every frame to no row -- which is what a
    path that stops comparing equal does -- this reds for all of the driven rows
    instead of passing quietly over an empty set. An observer that records nothing is
    the likely outcome of a rushed implementation and it looks exactly like success,
    so it gets a proof rather than a reading.

    It is also a guarantee this module did not have. A driven row asserted its status,
    its error ``code`` and that no identifier the store holds is in the message, and
    nothing asserted where the answer came from. Several rows share a ``code``,
    ``malformed_request`` most of all, so rows that nothing could previously tell
    apart are now told apart, the two ``authentication_failed`` rows of
    ``accounts._fail_login`` and ``accounts.log_in`` among them.

    The record is cleared immediately before the row's own request and after
    everything its ``who`` and ``setup`` do, so the refusals that
    ``spend_the_login_budget``, ``mark_one_payment`` and ``answer_one_payment`` each
    produce are not attributed to the row.
    """
    response = drive(site, app, seeded, before=answered_requests.clear)
    assert response.status_code in range(400, 500), (site_id(site), response.get_json())
    assert answered_requests, (
        f"{site_id(site)} answered {response.status_code} and the observer recorded "
        "nothing at all. Every error body this application sends is composed in "
        "web._handle_error, which tests/conftest.py wraps, so an empty record means "
        "the wrapper is not installed rather than that nothing was refused. Until "
        "this holds, every row marked NO_REQUEST_REACHES_IT is an unchecked claim "
        "again and the per-test guard passes over nothing."
    )
    answered = answered_requests[-1]
    assert answered.status == response.status_code, (site_id(site), answered)
    found = key_for_raise_site(answered.file, answered.lineno)
    assert found == site.key, (
        f"{site_id(site)} answered {response.status_code} from "
        f"{answered.file}:{answered.lineno}, which is "
        + ("no 4xx raise site this walk knows" if found is None else repr(found))
        + f", and not the site the row declares, {site.key!r}.\n\n"
        "A row names where its refusal is raised. Either the row names the wrong "
        "site, or the request now reaches a different refusal that happens to carry "
        "the same status and the same code, which is exactly what this check exists "
        "to tell apart. Correct the row or correct the drive."
    )
