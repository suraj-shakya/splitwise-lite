"""The HTTP layer: one process serves the shell in ``app/`` and a small JSON API.

This module is the whole of the request layer. Tasks 10, 11 and 12 build screens
against the endpoints and the error contract written down here, so none of them has to
pick a framework, invent a cookie attribute or decide what a 404 means.

**The framework is Flask, and this module is the only one that knows it.** The store is
synchronous ``sqlite3``, every domain function is an ordinary blocking call, and
``EventStore`` owns one connection that is not thread safe while explicitly supporting
two stores on one file. A threaded, synchronous WSGI application is therefore the shape
that matches what already exists. Flask is a dependency of this file and of nothing
else: the domain layer stays framework free and importable with Flask uninstalled,
which is what keeps the decision reversible.

**A store is opened per request and closed in ``teardown_appcontext``.** No
module-level store, no singleton, no pool. That is the "two stores on the same file"
arrangement ``EventStore``'s docstring calls supported, and it is what makes a threaded
server safe against a store that is not thread safe.

**The session cookie** is ``sl_session``: the raw token from ``accounts.log_in``,
unsigned and unencoded, with ``HttpOnly``, ``SameSite=Lax``, ``Path=/``, no ``Domain``
and a ``Max-Age`` derived from the session row rather than from a second constant.
``Secure`` is a required argument to :func:`create_app`, never a default and never
derived from the request scheme: a security control that quietly turns itself off is
worse than one that is off on purpose. The 30 day lifetime lives in the row, not the
cookie, so a cookie that outlives its row authenticates as invalid. There is no sliding
renewal.

**CSRF is three cheap gates in one ``before_request`` hook**, all standard library, on
every state-changing method under ``/api`` with no per-endpoint exemption: the media
type must be exactly ``application/json``, an ``X-CSRF-Token`` header must equal the
non-``HttpOnly`` ``sl_csrf`` cookie (compared with ``hmac.compare_digest``), and an
``Origin`` header, when the browser sent one, must match this origin. A failed gate is
403, not 401: the caller may well be authenticated; the request is not trusted.

**Login rate limiting is an in-process, in-memory fixed-window failure counter** held
on the app object behind a ``threading.Lock``. It refuses *before* the KDF runs, which
is the whole point of it: scrypt at ``DEFAULT_SCRYPT_PARAMS`` costs 64 MiB and hundreds
of milliseconds, so an unlimited login endpoint is a denial-of-service amplifier before
it is a password oracle. The recorded gaps: a restart clears the counters, and two
processes double every allowance. Both are acceptable at flat scale and neither is
acceptable silently.

**Every refusal is one family producing one body.** :data:`ERROR_STATUS` and
:data:`ERROR_CODE` map exception classes to a status and a code, resolved by walking
the raised exception's MRO so a subclass added later cannot fall through to 500 by
accident. Every error response is
``{"error": {"code": ..., "message": ...}}``. Every status except 500 carries
``str(error)``; a 500 carries one fixed generic string and the real exception goes to
the log with its traceback, because a 500 message can carry a file path or a SQL
fragment. The two 503 rows keep their own messages, which name the setup command and
the ambiguous group ids: hiding those would leave a freshly installed server saying
only that something went wrong.

**Reading the ledger requires a member link.** Every endpoint except signup and the
three session endpoints needs both a valid session and a member row in the group, and
answers 403 ``member_not_linked`` otherwise. Signup is unverified and grants nothing at
all; if an unlinked account could read the feed, that sentence would stop being true
and any stranger who signed up could read the flat's spending. Membership of the group
is the only authorisation this product has.

**A route is registered with its access policy or not at all.** Every route this app
serves is a row in :data:`_API_ROUTES` or :data:`_SHELL_ROUTES`, and an ``_ApiRoute``
row has no default for ``access``, so a row that does not state what it requires does
not construct. :func:`create_app` audits ``app.url_map`` against those two tables as
its last act and refuses to return an application that serves anything they do not
declare, so bypassing the table does not buy a silent endpoint, it buys an app that
will not start. A ``/api`` rule that reaches ``_before_request`` with no declared
policy is refused there rather than waved through, which covers the route registered
after the factory returned. ``MEMBER`` is what a new endpoint gets unless somebody
argues otherwise.

Money crosses the wire only as a ``format_amount`` string, never as a number and never
as cents, so the front end is handed nothing it could do arithmetic on. ``parse_amount``
is the only route from a request body back to cents.

This module is also the one place in the package that reads the clock. It reads it once
per request that needs it and passes that single value into every function taking
``now``; no endpoint accepts a client-supplied time.
"""

from __future__ import annotations

import enum
import hmac
import json
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
# ``Callable`` from ``typing``, not from ``collections.abc`` where balances.py,
# simplify.py, split.py and store.py take their ABCs: task 51 adds exactly one module
# name to this file's imports, ``enum``, and
# ``test_the_module_imports_flask_and_the_standard_library_only`` asserts that set
# exactly. Tidying this to ``collections.abc`` is a second name, and a red test.
from typing import Any, Callable, Final

import flask

from . import accounts, balances, events, groups, money, simplify, split, store
from .store import open_store

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "ERROR_CODE",
    "ERROR_STATUS",
    "EXTENSIONS",
    "LOGIN_LIMIT_PER_ADDRESS",
    "LOGIN_LIMIT_PER_EMAIL",
    "LOGIN_WINDOW",
    "MAX_BODY_BYTES",
    "SESSION_COOKIE",
    "CsrfFailed",
    "MalformedRequest",
    "NotAuthenticated",
    "RateLimiter",
    "TooManyAttempts",
    "WebError",
    "create_app",
]


# --- Errors -----------------------------------------------------------------


class WebError(money.DomainError):
    """Base class for every refusal this layer makes on its own.

    It subclasses ``DomainError`` so that a refusal invented here and a refusal raised
    by the domain layer are one family producing one response body, rather than two
    shapes a client has to tell apart.
    """


class NotAuthenticated(WebError):
    """No session cookie was presented at all, on an endpoint that needs one.

    Deliberately distinct from ``accounts.SessionInvalid``: nothing is cleared here,
    because there is nothing in the browser to clear, whereas an invalid token is
    cleared in the same response that refuses it.
    """


class CsrfFailed(WebError):
    """A state-changing request did not prove it came from a page on this origin.

    403 rather than 401: the caller may well be authenticated, and re-typing a
    password would not make the request trustworthy.
    """


class MalformedRequest(WebError):
    """The request body is not the shape this endpoint documents.

    Carries the offending key by name, never its value, so no message can quote a
    password back into a log or a response.
    """


class TooManyAttempts(WebError):
    """The fixed-window failure budget for this address is spent.

    Carries ``retry_after`` in whole seconds. The message names neither the email
    address nor whether an account exists, so the refusal is not an oracle.
    """

    def __init__(self, message: str, *, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# --- Constants --------------------------------------------------------------


SESSION_COOKIE: Final[str] = "sl_session"
"""Name of the session cookie.

Not ``session``, which is Flask's own signed cookie name: nothing here uses
``flask.session``, and a collision would make two unrelated things look like one.
"""

CSRF_COOKIE: Final[str] = "sl_csrf"
"""Name of the double-submit CSRF cookie, which is deliberately not ``HttpOnly``
because the client has to read it back and repeat it in a header."""

CSRF_HEADER: Final[str] = "X-CSRF-Token"
"""Header a state-changing request repeats the CSRF cookie in. A cross-site page
cannot read the cookie, so it cannot produce this header."""

MAX_BODY_BYTES: Final[int] = 65536
"""Largest request body accepted, in bytes. Anything larger is a 413 and the body is
never buffered past the cap: this is the only endpoint family that reads a body, and
none of them has a legitimate use for 64 KiB."""

LOGIN_WINDOW: Final[timedelta] = timedelta(minutes=15)
"""Width of the fixed failure-counting window, for both login buckets and for signup.

A fixed window rather than a lockout: task 7 pointed out that a sticky lockout in a
product with no password reset flow locks a flatmate out permanently.
"""

LOGIN_LIMIT_PER_EMAIL: Final[int] = 10
"""Failed logins allowed per normalised email address per window.

Per-email alone would let one attacker lock a flatmate out, which is why the address
bucket exists alongside it.
"""

LOGIN_LIMIT_PER_ADDRESS: Final[int] = 30
"""Failed logins allowed per client address per window, and the same budget for signup.

Higher than the per-email limit because ``request.remote_addr`` is one address for a
whole flat behind one NAT. A four-person flat never reaches 30 failures in 15 minutes.
"""

EXTENSIONS: Final[dict[str, str]] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
    ".ico": "image/vnd.microsoft.icon",
}
"""Content type per file extension, pinned rather than guessed.

``mimetypes`` reads the Windows registry, where ``.js`` is commonly mapped to
``text/plain``, and a browser enforces a JavaScript type on a worker script strictly.
Guessing would leave the app uninstallable on the machine it is developed on, which is
the exact failure ``scripts/serve.py`` was written to avoid; moving to Flask does not
fix it, so the map moved here with it. An extension not in this map is served as
``application/octet-stream``.
"""

_DEFAULT_CONTENT_TYPE: Final[str] = "application/octet-stream"

_APP_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "app"
"""The shell directory, resolved from this file rather than from the working
directory, so the app serves the same files however it was started."""

_CSRF_TOKEN_BYTES: Final[int] = 32
"""256 bits from ``secrets.token_urlsafe``. The CSRF token is not a credential and is
never stored server side: it is a proof that the request came from a page on this
origin."""

_JSON_MEDIA_TYPE: Final[str] = "application/json"

_STATE_CHANGING_METHODS: Final[frozenset[str]] = frozenset(
    {"POST", "PUT", "PATCH", "DELETE"}
)
"""Every method the CSRF gates apply to. ``GET``, ``HEAD`` and ``OPTIONS`` are never
state-changing and are never gated."""

_CSRF_ISSUING_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD"})
"""Safe methods whose response carries a fresh CSRF cookie when the request arrived
without one, so loading the shell always yields one and the login POST can carry a
header before any session exists."""

_API_PREFIX: Final[str] = "/api"
"""The prefix every API rule lives under, spelled once.

Every decision that asks "is this an API rule" compares against this constant:
:class:`_ApiRoute`, the audit in :func:`_audit_routes` and the refusal in
:func:`_before_request`. One spelling, so the guard that runs at construction and the
guard that runs per request cannot drift apart.

The comparison is ``rule == _API_PREFIX or rule.startswith(_API_PREFIX + "/")``, a
path segment rather than a string prefix, so ``/apiary`` is not under ``/api``. All
three sites ask it that way; a plain ``startswith`` would leave them agreeing on a
boundary one character wide.
"""


class _Access(enum.Enum):
    """What a request has to prove before an endpoint's view runs.

    ``ANONYMOUS`` needs no session at all. ``SESSION`` needs a valid session and no
    member row. ``MEMBER`` needs both a valid session and a linked member row in the
    group, and ``MEMBER`` is the level a new endpoint gets unless somebody argues
    otherwise, so an endpoint added without thought locks the ledger down rather than
    exposing it to any stranger who signed up.

    ``ANONYMOUS`` exists for signup, sign-in and sign-out, which cannot require a
    session they are there to create or destroy: signing up and signing in have none
    yet, and signing out has to work for a person whose session already died. It is
    an exemption from authentication only, never from CSRF: the three gates apply to
    every state-changing method under ``/api`` with no per-endpoint exemption.

    ``SESSION`` exists for ``read_session`` alone, so the shell can render "you are
    signed in, ask whoever set the flat up to link you" instead of a bare error.

    The value of each member is its own name, following ``SettlementState`` in
    ``events.py``: the name is the whole of the meaning, and a separate value would
    be a second thing to keep in step.
    """

    ANONYMOUS = "ANONYMOUS"
    SESSION = "SESSION"
    MEMBER = "MEMBER"


_SECURITY_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}
"""Carried by every response, static and API alike. ``no-store`` because a stale
balance is the "looks authoritative while being wrong" failure the spec names as the
product's largest risk. No Content Security Policy: it needs an inventory of every
inline handler and style plus a nonce mechanism, and half a policy silently breaks the
app, so it is named as a later task's work rather than guessed at here."""

_INTERNAL_ERROR_STATUS: Final[int] = 500
"""The one status whose message is generic and whose exception is logged.

Not "any 5xx": ``NoGroupConfigured`` and ``AmbiguousGroup`` are 503 and their messages
are fixed sentences this repo wrote for an operator to read, naming the setup command
and the ambiguous ids. Hiding those behind the generic string would leave a freshly
installed server saying only that something went wrong.
"""

_GENERIC_500_MESSAGE: Final[str] = (
    "the server could not complete that request; the failure has been logged"
)
"""The only thing a 500 body ever says. The real exception goes to the log with its
traceback, because a 500 message can carry a file path, a SQL fragment or a stored
hash."""

_TOO_MANY_ATTEMPTS_MESSAGE: Final[str] = (
    "too many failed attempts; wait a few minutes and try again"
)
"""One fixed string, naming neither the address nor whether an account exists, so a
registered and an unregistered address are byte-identical in the refusal."""

_HTTP_ERROR_CODES: Final[dict[int, str]] = {
    400: "malformed_request",
    404: "not_found",
    405: "method_not_allowed",
    413: "request_too_large",
}
"""Codes for the refusals routing makes before any handler runs. They are still the
one JSON body shape, so a client never has to parse an HTML error page."""

_HTTP_ERROR_FALLBACK_CODE: Final[str] = "http_error"

ERROR_STATUS: Final[dict[type[BaseException], int]] = {
    NotAuthenticated: 401,
    accounts.SessionInvalid: 401,
    accounts.AuthenticationFailed: 401,
    CsrfFailed: 403,
    groups.MemberNotLinked: 403,
    store.RecordNotFound: 404,
    accounts.EmailAlreadyRegistered: 409,
    store.DuplicateRecord: 409,
    store.ConstraintViolated: 409,
    groups.GroupMismatch: 409,
    groups.MemberAlreadyLinked: 409,
    groups.UserAlreadyLinked: 409,
    TooManyAttempts: 429,
    MalformedRequest: 400,
    accounts.InvalidEmail: 400,
    accounts.InvalidPassword: 400,
    money.InvalidAmount: 400,
    money.InvalidCurrency: 400,
    money.CurrencyMismatch: 400,
    split.InvalidSplit: 400,
    store.InvalidRecord: 400,
    store.AmountTooLarge: 400,
    groups.NoGroupConfigured: 503,
    groups.AmbiguousGroup: 503,
    accounts.PasswordHashInvalid: 500,
}
"""Exception class to HTTP status, in one place because five modules put their errors
under one ``DomainError`` family precisely so this mapping exists once.

Three rows carry their reasoning. ``NoGroupConfigured`` and ``AmbiguousGroup`` are 503
rather than 404 or 500: neither is anything a client can fix by changing its request,
and both are fixed by running ``setup_group.py``. ``PasswordHashInvalid`` is a 500
because a corrupt stored hash is database damage, and reporting it as a wrong password
would hide that behind a support ticket about a forgotten password.
``ConstraintViolated`` is 409 rather than 400 because the request parsed and the write
disagreed with a rule the database enforces.

Anything not listed, ``DomainError`` included, is a 500. Lookup walks the raised
exception's MRO, so a subclass added later inherits its parent's status rather than
falling through to 500 by accident.
"""

ERROR_CODE: Final[dict[type[BaseException], str]] = {
    NotAuthenticated: "not_authenticated",
    accounts.SessionInvalid: "session_invalid",
    accounts.AuthenticationFailed: "authentication_failed",
    CsrfFailed: "csrf_failed",
    groups.MemberNotLinked: "member_not_linked",
    store.RecordNotFound: "record_not_found",
    accounts.EmailAlreadyRegistered: "email_already_registered",
    store.DuplicateRecord: "duplicate_record",
    store.ConstraintViolated: "constraint_violated",
    groups.GroupMismatch: "group_mismatch",
    groups.MemberAlreadyLinked: "member_already_linked",
    groups.UserAlreadyLinked: "user_already_linked",
    TooManyAttempts: "too_many_attempts",
    MalformedRequest: "malformed_request",
    accounts.InvalidEmail: "invalid_email",
    accounts.InvalidPassword: "invalid_password",
    money.InvalidAmount: "invalid_amount",
    money.InvalidCurrency: "invalid_currency",
    money.CurrencyMismatch: "currency_mismatch",
    split.InvalidSplit: "invalid_split",
    store.InvalidRecord: "invalid_record",
    store.AmountTooLarge: "amount_too_large",
    groups.NoGroupConfigured: "no_group_configured",
    groups.AmbiguousGroup: "ambiguous_group",
    accounts.PasswordHashInvalid: "internal_error",
}
"""The stable string every mapped exception is reported as, keyed the same way as
:data:`ERROR_STATUS` and walked the same way.

A client branches on the code, never on the message: the messages are written for a
person to read and may be reworded, while a code is a contract tasks 10, 11 and 12 are
built on. Anything unmapped reports ``internal_error``.
"""

_FALLBACK_CODE: Final[str] = "internal_error"


# --- Rate limiting ----------------------------------------------------------


_LOGIN_EMAIL_BUCKET: Final[str] = "login_email"
_LOGIN_ADDRESS_BUCKET: Final[str] = "login_address"
_SIGNUP_ADDRESS_BUCKET: Final[str] = "signup_address"

_MAX_EMAIL_KEYS: Final[int] = 1024
_MAX_ADDRESS_KEYS: Final[int] = 4096

_DEFAULT_LIMITS: Final[dict[str, int]] = {
    _LOGIN_EMAIL_BUCKET: LOGIN_LIMIT_PER_EMAIL,
    _LOGIN_ADDRESS_BUCKET: LOGIN_LIMIT_PER_ADDRESS,
    _SIGNUP_ADDRESS_BUCKET: LOGIN_LIMIT_PER_ADDRESS,
}

_DEFAULT_CAPACITIES: Final[dict[str, int]] = {
    _LOGIN_EMAIL_BUCKET: _MAX_EMAIL_KEYS,
    _LOGIN_ADDRESS_BUCKET: _MAX_ADDRESS_KEYS,
    _SIGNUP_ADDRESS_BUCKET: _MAX_ADDRESS_KEYS,
}


@dataclass(frozen=True, slots=True)
class _Window:
    """One key's fixed window: when it started and how many failures it holds.

    Frozen like every other value type in this package: a count is bumped by replacing
    the window, never by mutating one another thread may be reading.
    """

    started: datetime
    count: int


class RateLimiter:
    """An in-process, in-memory fixed-window failure counter, one map per bucket.

    Deliberately not a table. A counter in the store means a write on the
    unauthenticated login path, which hands an attacker an unbounded write against the
    one SQLite writer, plus disk growth, plus a lock that honest logins then queue
    behind; and it means a schema version bump for bookkeeping that is not ledger data.
    v1 runs as one process on one small host, so an in-process limiter is complete for
    the deployment that exists.

    The recorded gaps: a restart clears every counter, and two processes double every
    allowance. Both are acceptable at flat scale and neither is acceptable silently.

    Every map is capped and evicts its own oldest window when full, so the limiter
    cannot grow without bound, and the caps are per map so address churn cannot evict
    the email entry for the address being attacked.

    It is guarded by a ``threading.Lock``, because the run command is a threaded
    server, and it never reads the clock: every method takes ``now``, so the whole
    thing is unit testable without a ``sleep``.
    """

    __slots__ = ("_buckets", "_lock", "_limits", "_capacities", "_window")

    def __init__(
        self,
        *,
        window: timedelta = LOGIN_WINDOW,
        limits: dict[str, int] | None = None,
        capacities: dict[str, int] | None = None,
    ) -> None:
        """Build a limiter over the three named buckets, or over the ones given.

        The defaults are the shipped policy: at most
        ``LOGIN_LIMIT_PER_EMAIL`` failures per normalised email address, at most
        ``LOGIN_LIMIT_PER_ADDRESS`` per client address, and a separate signup budget on
        the same terms so exhausting one does not exhaust the other.
        """
        self._window = window
        self._limits = dict(_DEFAULT_LIMITS if limits is None else limits)
        self._capacities = dict(
            _DEFAULT_CAPACITIES if capacities is None else capacities
        )
        self._buckets: dict[str, dict[str, _Window]] = {
            name: {} for name in self._limits
        }
        self._lock = threading.Lock()

    def check(self, bucket: str, key: str, *, now: datetime) -> None:
        """Raise ``TooManyAttempts`` if ``key``'s budget in ``bucket`` is spent.

        Called *before* the KDF runs, which is the whole reason the limiter exists:
        scrypt costs 64 MiB and hundreds of milliseconds per attempt, so an unlimited
        login endpoint is a denial-of-service amplifier before it is a password oracle.
        It counts nothing itself, so a check is free to repeat.
        """
        with self._lock:
            window = self._buckets[bucket].get(key)
            if window is None or self._expired(window, now):
                return
            if window.count < self._limits[bucket]:
                return
            remaining = window.started + self._window - now
        raise TooManyAttempts(
            _TOO_MANY_ATTEMPTS_MESSAGE, retry_after=_whole_seconds(remaining)
        )

    def record_failure(self, bucket: str, key: str, *, now: datetime) -> None:
        """Count one failure for ``key``. Only failures are ever counted."""
        with self._lock:
            entries = self._buckets[bucket]
            window = entries.get(key)
            if window is not None and not self._expired(window, now):
                entries[key] = _Window(window.started, window.count + 1)
                return
            if key not in entries:
                self._make_room(entries, self._capacities[bucket], now)
            entries[key] = _Window(started=now, count=1)

    def clear(self, bucket: str, key: str) -> None:
        """Forget ``key``'s failures. A successful login clears that email's bucket and
        leaves the address bucket alone, so holding one valid account does not reset an
        attacker's budget."""
        with self._lock:
            self._buckets[bucket].pop(key, None)

    def count(self, bucket: str, key: str, *, now: datetime) -> int:
        """Failures currently counted for ``key``, ignoring an expired window."""
        with self._lock:
            window = self._buckets[bucket].get(key)
            if window is None or self._expired(window, now):
                return 0
            return window.count

    def size(self, bucket: str) -> int:
        """How many keys ``bucket`` holds, so the cap can be asserted directly."""
        with self._lock:
            return len(self._buckets[bucket])

    def _expired(self, window: _Window, now: datetime) -> bool:
        """Whether ``window`` has fallen out of the fixed window as of ``now``."""
        return now - window.started >= self._window

    def _make_room(
        self, entries: dict[str, _Window], capacity: int, now: datetime
    ) -> None:
        """Drop entries until ``entries`` can take one more key.

        Expired windows go first, because they are already dead and dropping one costs
        nothing. Only if that is not enough does the oldest live window go, which is
        the eviction the cap promises.
        """
        if len(entries) < capacity:
            return
        for key in [k for k, v in entries.items() if self._expired(v, now)]:
            del entries[key]
        while len(entries) >= capacity:
            oldest = min(entries, key=lambda key: entries[key].started)
            del entries[oldest]


def _whole_seconds(remaining: timedelta) -> int:
    """Round ``remaining`` up to whole seconds, never below 1.

    ``Retry-After`` is defined in whole seconds, and rounding down would tell a client
    to come back at the instant the window is still closed.
    """
    second = timedelta(seconds=1)
    seconds = remaining // second
    if remaining % second:
        seconds += 1
    return max(1, seconds)


# --- Per-app state ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Settings:
    """Everything one application instance was built with.

    Held on the app rather than in a module global, so two apps in one process share
    no state: the rate limiter of one cannot be exhausted through the other.
    """

    store_path: str | Path
    secure_cookies: bool
    app_dir: Path
    scrypt_params: accounts.ScryptParams
    limiter: RateLimiter = field(default_factory=RateLimiter)

    def __post_init__(self) -> None:
        if not isinstance(self.secure_cookies, bool):
            raise TypeError(
                f"secure_cookies must be a bool, got "
                f"{type(self.secure_cookies).__name__}: {self.secure_cookies!r}"
            )
        if not isinstance(self.app_dir, Path):
            raise TypeError(
                f"app_dir must be a Path, got {type(self.app_dir).__name__}"
            )
        if not isinstance(self.scrypt_params, accounts.ScryptParams):
            raise TypeError(
                f"scrypt_params must be a ScryptParams, got "
                f"{type(self.scrypt_params).__name__}"
            )


def _settings() -> _Settings:
    """The current app's settings. There is no module-level store and no singleton."""
    return flask.current_app.extensions["splitwise_lite"]


def _now() -> datetime:
    """The one clock read this request gets, cached on the application context.

    This module is the only one in the package that reads the clock, and it reads it
    once per request that needs it so that a session check, an event's ``created_at``
    and a rate-limit window all agree on when "now" was.
    """
    moment = getattr(flask.g, "_now", None)
    if moment is None:
        moment = datetime.now(timezone.utc)
        flask.g._now = moment
    return moment


def _store() -> store.EventStore:
    """This request's store, opened on first use and closed in teardown.

    One connection per request, never shared between them. Two stores on one file is
    the arrangement ``EventStore`` documents as supported, and WAL plus the busy
    timeout are what make it safe under the threaded run command.
    """
    opened = getattr(flask.g, "_store", None)
    if opened is None:
        opened = open_store(_settings().store_path)
        flask.g._store = opened
    return opened


# --- Request and response plumbing ------------------------------------------


def _json_response(payload: dict[str, Any], status: int) -> flask.Response:
    """A JSON response with the security headers the after-request hook completes.

    ``json.dumps`` rather than ``flask.jsonify`` so the body shape is decided here and
    is identical for a success and for an error.
    """
    return flask.Response(
        json.dumps(payload),
        status=status,
        content_type=_JSON_MEDIA_TYPE,
    )


def _error_body(code: str, message: str) -> dict[str, Any]:
    """The one error body shape, at every status: ``{"error": {"code", "message"}}``."""
    return {"error": {"code": code, "message": message}}


def _status_and_code(error: BaseException) -> tuple[int, str]:
    """Look ``error`` up by walking its MRO, so a subclass inherits its parent's row.

    Falling through to 500 by accident is exactly what the MRO walk prevents: a domain
    error added later that subclasses a mapped one keeps its parent's answer until
    somebody decides otherwise.
    """
    for klass in type(error).__mro__:
        status = ERROR_STATUS.get(klass)
        if status is not None:
            return status, ERROR_CODE[klass]
    return 500, _FALLBACK_CODE


def _media_type(header: str | None) -> str:
    """The media type of a ``Content-Type`` header, with its parameters dropped.

    ``application/json; charset=utf-8`` is the same media type as
    ``application/json``; a parameter is not a different content type.
    """
    if header is None:
        return ""
    return header.partition(";")[0].strip().lower()


def _request_origin() -> str:
    """This origin, as the browser would spell it in an ``Origin`` header."""
    return flask.request.host_url.rstrip("/")


def _check_csrf() -> None:
    """Run the three gates, or raise ``CsrfFailed``.

    1. The media type must be exactly ``application/json``. A cross-site HTML form can
       only send ``application/x-www-form-urlencoded``, ``multipart/form-data`` or
       ``text/plain``; anything else forces a preflight, and this app answers no
       preflight and sends no CORS header, so the browser blocks it.
    2. The ``X-CSRF-Token`` header must equal the ``sl_csrf`` cookie, compared with
       ``hmac.compare_digest``. An attacker's page cannot read the cookie, so it cannot
       produce the header.
    3. ``Origin``, when the browser sent one, must match this origin. Absent is not a
       refusal on its own, because gates 1 and 2 already stand and some same-origin
       requests omit it.

    No library: every alternative is a second dependency for a comparison of two
    random strings, and ``flask-wtf`` drags a form stack this product does not have.
    """
    if _media_type(flask.request.headers.get("Content-Type")) != _JSON_MEDIA_TYPE:
        raise CsrfFailed(
            f"a state-changing request must be sent as {_JSON_MEDIA_TYPE}"
        )
    submitted = flask.request.headers.get(CSRF_HEADER)
    stored = flask.request.cookies.get(CSRF_COOKIE)
    if not submitted or not stored:
        raise CsrfFailed(
            f"a state-changing request must repeat the {CSRF_COOKIE} cookie in the "
            f"{CSRF_HEADER} header"
        )
    # Compared as bytes, not as text. Werkzeug decodes a request header as latin-1,
    # so any byte from 0x80 up arrives as a str with a codepoint above 0x7f, and
    # ``compare_digest`` refuses two such strings outright. Handing it text would turn
    # this refusal into a 500 with a logged traceback, which is a refusal the caller
    # can spend the log on. Encoding first keeps the comparison constant time and
    # makes the gate total over every string a header or a cookie can carry.
    if not hmac.compare_digest(submitted.encode("utf-8"), stored.encode("utf-8")):
        raise CsrfFailed(
            f"the {CSRF_HEADER} header does not match the {CSRF_COOKIE} cookie"
        )
    origin = flask.request.headers.get("Origin")
    if origin is not None and origin != _request_origin():
        raise CsrfFailed("that request came from another origin")


def _set_csrf_cookie(response: flask.Response, token: str) -> None:
    """Write a CSRF cookie the client can read. Not ``HttpOnly``, on purpose."""
    response.set_cookie(
        CSRF_COOKIE,
        token,
        path="/",
        secure=_settings().secure_cookies,
        httponly=False,
        samesite="Lax",
    )


def _clear_csrf_cookie(response: flask.Response) -> None:
    """Delete the CSRF cookie, repeating every attribute it was written with.

    A delete whose attributes do not match the original simply misses, leaving the old
    cookie in place.
    """
    response.set_cookie(
        CSRF_COOKIE,
        "",
        max_age=0,
        path="/",
        secure=_settings().secure_cookies,
        httponly=False,
        samesite="Lax",
    )


def _set_session_cookie(
    response: flask.Response, issued: accounts.IssuedSession
) -> None:
    """Write the session cookie: the raw token, unsigned and unencoded.

    ``Max-Age`` is derived from the session row rather than from a second constant, so
    the cookie and the row cannot drift. ``HttpOnly`` because no script in ``app/``
    ever needs the token; ``SameSite=Lax`` because ``Strict`` would sign the user out
    of the first navigation from any link while ``Lax`` still blocks every cross-site
    POST; no ``Domain``, so the cookie is host-only and no subdomain may write it.
    """
    max_age = int((issued.session.expires_at - _now()).total_seconds())
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        max_age=max_age,
        path="/",
        secure=_settings().secure_cookies,
        httponly=True,
        samesite="Lax",
    )


def _clear_session_cookie(response: flask.Response) -> None:
    """Delete the session cookie, repeating every attribute exactly.

    Without this a stale token sits in the browser producing a 401 on every request
    forever, and the user has no way to get rid of it.
    """
    response.set_cookie(
        SESSION_COOKIE,
        "",
        max_age=0,
        path="/",
        secure=_settings().secure_cookies,
        httponly=True,
        samesite="Lax",
    )


def _json_object() -> dict[str, Any]:
    """This request's body as a JSON object, or raise ``MalformedRequest``.

    No message ever quotes the body: it may hold a password.
    """
    raw = flask.request.get_data(cache=False)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise MalformedRequest("the request body is not valid JSON") from error
    if not isinstance(payload, dict):
        raise MalformedRequest("the request body must be a JSON object")
    return payload


def _require_keys(payload: dict[str, Any], keys: tuple[str, ...], what: str) -> None:
    """Every key in ``keys`` is present and nothing else is, or raise.

    An unrecognised key is refused rather than ignored: that is how the client is
    prevented from naming ``currency``, ``created_by``, ``created_at``, ``id`` or
    ``now`` on an expense.
    """
    for key in keys:
        if key not in payload:
            raise MalformedRequest(f"{what} is missing the key {key!r}")
    for key in payload:
        if key not in keys:
            raise MalformedRequest(f"{what} has an unrecognised key {key!r}")


def _require_str(payload: dict[str, Any], key: str, what: str) -> str:
    """``payload[key]`` as a ``str``, or raise ``MalformedRequest`` naming the key."""
    value = payload[key]
    if not isinstance(value, str):
        raise MalformedRequest(f"{what} key {key!r} must be a JSON string")
    return value


def _require_amount_str(payload: dict[str, Any], key: str, what: str) -> str:
    """``payload[key]`` as an amount string, or raise naming the key.

    Money crosses the wire only as a formatted string, so a JSON number where an
    amount is expected is refused rather than read: a number is something a client
    could have done arithmetic on.
    """
    value = payload[key]
    if not isinstance(value, str):
        raise MalformedRequest(
            f"{what} key {key!r} must be an amount as a JSON string, such as "
            f'"12.50"; amounts are strings, never numbers'
        )
    return value


def _require_object(payload: dict[str, Any], key: str, what: str) -> dict[str, Any]:
    """``payload[key]`` as a JSON object, or raise ``MalformedRequest``."""
    value = payload[key]
    if not isinstance(value, dict):
        raise MalformedRequest(f"{what} key {key!r} must be a JSON object")
    return value


def _require_list(payload: dict[str, Any], key: str, what: str) -> list[Any]:
    """``payload[key]`` as a JSON array, or raise ``MalformedRequest``."""
    value = payload[key]
    if not isinstance(value, list):
        raise MalformedRequest(f"{what} key {key!r} must be a JSON array")
    return value


# --- Views ------------------------------------------------------------------


def _user_view(user: store.User) -> dict[str, Any]:
    """A user, with no password field of any kind."""
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
    }


def _group_view(group: store.Group) -> dict[str, Any]:
    """A group: its id, its name and its currency code."""
    return {
        "id": group.id,
        "name": group.name,
        "currency": group.currency.code,
    }


def _member_view(member: store.Member) -> dict[str, Any]:
    """A member: id and display name only.

    No ``user_id``, no email address and no "is linked" flag. Task 9 decided an
    unlinked member is a full member that nothing filters, greys out or marks pending,
    and leaving the flag out means a screen cannot accidentally start doing it. It also
    means a screenshot of the roster is not an account list.
    """
    return {"id": member.id, "display_name": member.display_name}


def _amount(cents: int, currency: money.Currency) -> str:
    """Cents rendered for the wire, through the one display edge."""
    return money.format_amount(money.Money(cents, currency))


def _expense_view(expense: events.ExpenseEvent) -> dict[str, Any]:
    """One feed entry, with its allocations riding along.

    Allocations are included so a tap-to-open detail needs no second request and no
    per-expense endpoint. Display names are not: one roster call covers every screen,
    and duplicating names into every expense is how two spellings of one member end up
    on one page.
    """
    return {
        "id": expense.id,
        "description": expense.description,
        "amount": _amount(expense.total_cents, expense.currency),
        "payer_id": expense.payer_id,
        "created_by": expense.created_by,
        # The fixed-width 32 character form tasks 6, 7 and 9 store, always with six
        # fractional digits, so the wire and the row spell one instant one way.
        "created_at": expense.created_at.isoformat(timespec="microseconds"),
        "allocations": [
            {
                "member_id": allocation.member_id,
                "amount": _amount(allocation.cents, expense.currency),
            }
            for allocation in expense.allocations
        ],
    }


def _absorbed_view(row: simplify.AbsorbedDebt) -> dict[str, Any]:
    """One pairwise debt a transfer absorbed, and how much of it that transfer covers.

    ``debtor_id`` and ``creditor_id`` are the ``Balances.pairwise`` key unchanged, so
    the two together are exactly what the debts endpoint is then asked about.

    ``covers_whole_debt`` is computed here from cents and never from the two formatted
    strings, for the same reason ``direction`` exists on a net row: a client that had
    to compare two amount strings to decide whether a payment clears a debt would be
    doing money arithmetic, which is the one thing the front end never does.
    """
    return {
        "debtor_id": row.debtor,
        "creditor_id": row.creditor,
        "amount": _amount(row.amount.cents, row.amount.currency),
        "debt_total": _amount(row.debt_total.cents, row.debt_total.currency),
        "covers_whole_debt": row.amount.cents == row.debt_total.cents,
    }


_ENTRY_KIND_WIRE: Final[dict[balances.DebtEntryKind, str]] = {
    balances.DebtEntryKind.EXPENSE: "expense",
    balances.DebtEntryKind.SETTLEMENT: "settlement",
}
"""The wire spelling of every ``DebtEntryKind``, as an explicit map rather than the
enum's own values, so renaming a domain member cannot silently rename a JSON value the
front end branches on. Exhaustive over the enum, and a test says so."""

_ENTRY_EFFECT_WIRE: Final[dict[balances.DebtEffect, str]] = {
    balances.DebtEffect.ADDS: "adds",
    balances.DebtEffect.REDUCES: "reduces",
}
"""The wire spelling of every ``DebtEffect``, on the same terms and for the same
reason. The effect is server-computed for the same reason ``direction`` is: deciding
which way an entry pulls from two formatted strings is arithmetic the client may not
do."""


def _debt_entry_view(entry: balances.DebtEntry) -> dict[str, Any]:
    """One event behind a pairwise debt, with the way it moved that debt.

    ``amount`` is always strictly positive, because ``effect`` carries the direction.
    Display names are not here: one roster call covers every screen, exactly as
    ``_expense_view`` decided.
    """
    return {
        "kind": _ENTRY_KIND_WIRE[entry.kind],
        "effect": _ENTRY_EFFECT_WIRE[entry.effect],
        "id": entry.event_id,
        "description": entry.description,
        # The same spelling ``_expense_view`` uses, so one instant is spelled one way
        # wherever it appears on the wire.
        "created_at": entry.created_at.isoformat(timespec="microseconds"),
        "amount": _amount(entry.amount.cents, entry.amount.currency),
    }


# --- Authentication and the acting member -----------------------------------


def _authenticate() -> store.Session:
    """Turn this request's cookie into a live session, or refuse.

    ``NotAuthenticated`` when there is no cookie at all, so nothing is cleared;
    ``SessionInvalid`` for a token that is unknown, malformed, over-long, expired or
    logged out, which is one refusal because "you were signed out, sign in again" is
    one screen.
    """
    token = flask.request.cookies.get(SESSION_COOKIE)
    if not token:
        raise NotAuthenticated("this endpoint needs a signed-in session")
    return accounts.authenticate(_store(), token, now=_now())


def _acting_group() -> store.Group:
    """The one group this store holds, resolved per request and never cached.

    No group id is held in a module global, cached between requests or read from the
    cookie: exposing several groups later is deleting calls to
    ``groups.resolve_sole_group``, not unpicking a constant that leaked into a dozen
    files.
    """
    return groups.resolve_sole_group(_store())


def _acting_member() -> store.Member:
    """The member the signed-in user acts as, resolved per request."""
    return groups.acting_member(
        _store(), group_id=flask.g.group.id, user_id=flask.g.session.user_id
    )


# --- Endpoints --------------------------------------------------------------


def _signup() -> flask.Response:
    """``POST /api/signup``: create an account and return it, with no session.

    Task 7 decided signup issues no session, and keeping one place that mints one is
    worth the client's second request. It links nothing either: a brand new account can
    see nothing at all until an operator links it, which is what makes an unverified
    signup harmless.

    A losing racer in a concurrent signup surfaces ``DuplicateRecord`` from the store
    rather than ``EmailAlreadyRegistered``; both are 409 and both are answered with the
    same body, because a losing racer and a plain duplicate are the same situation for
    the person typing.
    """
    payload = _json_object()
    _require_keys(payload, ("email", "display_name", "password"), "a signup body")
    email = _require_str(payload, "email", "a signup body")
    display_name = _require_str(payload, "display_name", "a signup body")
    password = _require_str(payload, "password", "a signup body")

    limiter = _settings().limiter
    address = _client_address()
    limiter.check(_SIGNUP_ADDRESS_BUCKET, address, now=_now())
    try:
        user = accounts.sign_up(
            _store(),
            email=email,
            display_name=display_name,
            password=password,
            now=_now(),
            params=_settings().scrypt_params,
        )
    except store.DuplicateRecord as error:
        # The losing racer: the address was free when it was checked and taken by the
        # time the row was written. Same answer as a plain duplicate.
        limiter.record_failure(_SIGNUP_ADDRESS_BUCKET, address, now=_now())
        raise accounts.EmailAlreadyRegistered(
            f"an account already exists for "
            f"{accounts.normalise_email(email)!r}"
        ) from error
    except money.DomainError:
        limiter.record_failure(_SIGNUP_ADDRESS_BUCKET, address, now=_now())
        raise
    return _json_response({"user": _user_view(user)}, 201)


def _create_session() -> flask.Response:
    """``POST /api/session``: check a password and set both cookies.

    The limiter is consulted before ``accounts.log_in`` so a refused request never runs
    the KDF. A success clears that email's bucket and leaves the address bucket alone,
    so holding one valid account does not reset an attacker's budget.
    """
    payload = _json_object()
    _require_keys(payload, ("email", "password"), "a sign-in body")
    email = _require_str(payload, "email", "a sign-in body")
    password = _require_str(payload, "password", "a sign-in body")

    limiter = _settings().limiter
    key = accounts.normalise_email(email)
    address = _client_address()
    limiter.check(_LOGIN_EMAIL_BUCKET, key, now=_now())
    limiter.check(_LOGIN_ADDRESS_BUCKET, address, now=_now())
    try:
        issued = accounts.log_in(
            _store(), email=email, password=password, now=_now()
        )
    except accounts.AuthenticationFailed:
        limiter.record_failure(_LOGIN_EMAIL_BUCKET, key, now=_now())
        limiter.record_failure(_LOGIN_ADDRESS_BUCKET, address, now=_now())
        raise
    limiter.clear(_LOGIN_EMAIL_BUCKET, key)

    flask.g.session = issued.session
    # Recorded rather than written here, so the cookies land on whatever response
    # this request ends with. The session row exists from this point on, and a view
    # that then fails must not leave a live session the browser was never told about.
    flask.g.issue_session = issued
    # Rotated on login, so a token captured before sign-in cannot be replayed after it.
    flask.g.rotate_csrf = secrets.token_urlsafe(_CSRF_TOKEN_BYTES)
    return _json_response(_session_view(), 200)


def _read_session() -> flask.Response:
    """``GET /api/session``: who is signed in, which group, and which member.

    The one endpoint that answers 200 for a user nobody has linked, with ``member``
    null, so the shell can render "you are signed in, ask whoever set the flat up to
    link you" rather than a bare error. It sets no new session cookie and extends
    nothing: there is no sliding renewal.
    """
    return _json_response(_session_view(), 200)


def _session_view() -> dict[str, Any]:
    """The session view both session endpoints answer with."""
    user = _store().get_user(flask.g.session.user_id)
    group = _acting_group()
    flask.g.group = group
    try:
        member = groups.acting_member(
            _store(), group_id=group.id, user_id=user.id
        )
    except groups.MemberNotLinked:
        member = None
    return {
        "user": _user_view(user),
        "group": _group_view(group),
        "member": None if member is None else _member_view(member),
    }


def _delete_session() -> flask.Response:
    """``DELETE /api/session``: 204, both cookies cleared, and it never fails.

    Whether the cookie was valid, expired or absent: ``accounts.log_out`` is already
    idempotent, and a person whose session died still needs the sign-out button to
    work. It deletes exactly that session row, so the user's other sessions keep
    authenticating.
    """
    token = flask.request.cookies.get(SESSION_COOKIE)
    if token:
        accounts.log_out(_store(), token)
    flask.g.clear_session = True
    flask.g.clear_csrf = True
    return flask.Response(status=204)


def _list_members() -> flask.Response:
    """``GET /api/members``: the roster, in ``store.list_members`` order."""
    members = _store().list_members(flask.g.group.id)
    return _json_response(
        {"members": [_member_view(member) for member in members]}, 200
    )


def _list_expenses() -> flask.Response:
    """``GET /api/expenses``: the group's expenses, newest first.

    ``store.list_expenses`` returns ascending ``(created_at, id)``, which is the only
    order the store has, so reversing it here gives newest first with ties broken by id
    descending and keeps one ordering rule in one place. There is no pagination: a flat
    logs a few hundred expenses a year, and paging now would be a second ordering
    contract to keep in step with the first.
    """
    group = flask.g.group
    expenses = _store().list_expenses(group.id)
    return _json_response(
        {
            "currency": group.currency.code,
            "expenses": [_expense_view(expense) for expense in reversed(expenses)],
        },
        200,
    )


def _create_expense() -> flask.Response:
    """``POST /api/expenses``: record one expense authored by the acting member.

    The currency is the group's, ``created_by`` is the acting member, ``id`` comes from
    ``new_id()`` and ``created_at`` from this request's single clock read: none of the
    four can be named in the body. ``payer_id`` may be any member of the group, because
    recording that a flatmate paid is a normal entry, not an impersonation.

    Every id is checked against the roster before anything is written, so a foreign key
    violation is never reached and a rejected request writes nothing at all.
    """
    payload = _json_object()
    what = "an expense body"
    _require_keys(payload, ("description", "amount", "payer_id", "split"), what)
    description = _require_str(payload, "description", what)
    amount_text = _require_amount_str(payload, "amount", what)
    payer_id = _require_str(payload, "payer_id", what)
    split_body = _require_object(payload, "split", what)

    group = flask.g.group
    roster = {member.id for member in _store().list_members(group.id)}
    if payer_id not in roster:
        raise MalformedRequest(
            f"{what} names a payer_id that is not a member of this group: "
            f"{payer_id!r}"
        )
    total = money.parse_amount(amount_text, group.currency)
    allocations = _resolve_split(split_body, total.cents, roster, group.currency)

    expense = events.ExpenseEvent(
        id=events.ExpenseId(events.new_id()),
        group_id=events.GroupId(group.id),
        currency=group.currency,
        payer_id=events.MemberId(payer_id),
        total_cents=total.cents,
        allocations=allocations,
        description=description,
        created_at=_now(),
        created_by=events.MemberId(flask.g.member.id),
    )
    _store().append_expense(expense)
    return _json_response({"expense": _expense_view(expense)}, 201)


def _resolve_split(
    body: dict[str, Any],
    total_cents: int,
    roster: set[str],
    currency: money.Currency,
) -> tuple[events.Allocation, ...]:
    """Turn one of the three split shapes into explicit allocations.

    The three shapes match ``split.py`` exactly: ``equal`` over a member list, which
    covers equal across all and equal across a subset, ``weight`` over integer weights,
    and ``exact`` over amounts that arrive as strings and are parsed with
    ``parse_amount`` before reaching ``split_exact``.

    Every member id is checked against the roster first, so an unknown id is a
    ``malformed_request`` naming it rather than a foreign key violation later.
    """
    what = "a split"
    if "mode" not in body:
        raise MalformedRequest(f"{what} is missing the key 'mode'")
    mode = _require_str(body, "mode", what)
    if mode == "equal":
        _require_keys(body, ("mode", "member_ids"), what)
        raw = _require_list(body, "member_ids", what)
        member_ids = [_require_member_id(value, roster) for value in raw]
        return split.split_equally(total_cents, member_ids)
    if mode == "weight":
        _require_keys(body, ("mode", "weights"), what)
        weights = _require_object(body, "weights", what)
        return split.split_by_weight(
            total_cents,
            {
                _require_member_id(key, roster): _require_weight(key, value)
                for key, value in weights.items()
            },
        )
    if mode == "exact":
        _require_keys(body, ("mode", "amounts"), what)
        amounts = _require_object(body, "amounts", what)
        return split.split_exact(
            total_cents,
            {
                _require_member_id(key, roster): _require_exact_amount(
                    key, value, currency
                )
                for key, value in amounts.items()
            },
        )
    raise MalformedRequest(
        f"{what} mode must be one of 'equal', 'weight' or 'exact', got {mode!r}"
    )


def _require_member_id(value: object, roster: set[str]) -> events.MemberId:
    """A member id that names a member of this group, or raise naming it."""
    if not isinstance(value, str):
        raise MalformedRequest("a split names a member id that is not a JSON string")
    if value not in roster:
        raise MalformedRequest(
            f"a split names a member id that is not a member of this group: {value!r}"
        )
    return events.MemberId(value)


def _require_weight(key: str, value: object) -> int:
    """A weight, which is an integer and never a bool or a float.

    Integers on purpose: a share of one and a half is expressed as weights 3 and 2, so
    no fraction ever enters the money path.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedRequest(f"the weight for {key!r} must be a JSON integer")
    return value


def _require_exact_amount(
    key: str, value: object, currency: money.Currency
) -> int:
    """One exact share, parsed from a string through the one input edge."""
    if not isinstance(value, str):
        raise MalformedRequest(
            f"the exact amount for {key!r} must be an amount as a JSON string, such "
            f'as "8.00"; amounts are strings, never numbers'
        )
    return money.parse_amount(value, currency).cents


def _read_balances() -> flask.Response:
    """``GET /api/balances``: one net entry per member, plus the transfer plan.

    ``net`` covers every member of the group in roster order, including members the
    ledger has never seen, through ``Balances.net_for``, which is total by design.
    ``direction`` carries the sign so ``amount`` is always the non-negative magnitude
    and no client ever has to parse or render a minus sign.

    Every transfer carries both ends of its provenance, ``payer_debts`` and
    ``receiver_credits``, each row naming a ``Balances.pairwise`` key, the part of that
    debt this transfer covers and the debt's whole total. ``covers_whole_debt`` on each
    row is computed from cents here rather than by comparing the two formatted strings,
    for the same reason ``direction`` exists on a net row.
    """
    group = flask.g.group
    ledger = _store().list_events(group.id)
    derived = balances.derive_balances(
        ledger, group_id=events.GroupId(group.id), currency=group.currency
    )
    plan = simplify.simplify_debts(derived)
    net = []
    for member in _store().list_members(group.id):
        position = derived.net_for(events.MemberId(member.id))
        net.append(
            {
                "member_id": member.id,
                "amount": _amount(abs(position.cents), group.currency),
                "direction": _direction(position.cents),
            }
        )
    return _json_response(
        {
            "currency": group.currency.code,
            "net": net,
            "transfers": [
                {
                    "from_member_id": transfer.from_member_id,
                    "to_member_id": transfer.to_member_id,
                    "amount": money.format_amount(transfer.amount),
                    # simplify.py's own order, ascending by (debtor, creditor).
                    # Nothing is re-sorted, merged, filtered or deduplicated here, so a
                    # pair appearing in both lists of one transfer appears in both on
                    # the wire.
                    "payer_debts": [
                        _absorbed_view(row) for row in transfer.payer_debts
                    ],
                    "receiver_credits": [
                        _absorbed_view(row) for row in transfer.receiver_credits
                    ],
                }
                for transfer in plan.transfers
            ],
        },
        200,
    )


def _read_debt(debtor_id: str, creditor_id: str) -> flask.Response:
    """``GET /api/debts/<debtor_id>/<creditor_id>``: what one pairwise debt is made of.

    The expenses and confirmed settlements behind the debt from ``debtor_id`` to
    ``creditor_id``, each carrying a server-computed ``effect`` of ``adds`` or
    ``reduces``. A pairwise debt is a signed fold, so a list of only the events pushing
    one way would not account for the figure it claims to explain.

    ``amount`` is the non-negative magnitude and ``direction`` carries the sign, read
    from the debtor's side so it reads exactly as a net row does: ``owes`` when the
    debt runs the way it was asked about. The domain value is signed, because a value
    that hid which way a debt ran could not be checked against the fold; the wire never
    is, because no client may parse or render a minus sign. The pair can legitimately
    run backwards here, since the ledger may have moved between a balances read and
    this request.

    Both ids are checked against the roster before anything else, so an id from
    another group is a ``malformed_request`` naming it rather than an empty answer that
    looks like a settled pair. Together with the self-pair refusal that keeps
    ``InvalidLedger`` unreachable from any request.

    The whole group's pairs are readable by any linked member: the drill-down exists to
    explain a payment between two other people, and membership of the group is the only
    authorisation this product has.

    Nothing is stored, cached or memoised. Every figure is derived on read from the
    event log, so two requests against a ledger that changed in between may
    legitimately differ.
    """
    group = flask.g.group
    roster = {member.id for member in _store().list_members(group.id)}
    for value in (debtor_id, creditor_id):
        if value not in roster:
            raise MalformedRequest(
                f"a debt path names a member id that is not a member of this group: "
                f"{value!r}"
            )
    if debtor_id == creditor_id:
        raise MalformedRequest(
            f"a member cannot owe themselves: {debtor_id!r} was asked about as both "
            f"the debtor and the creditor"
        )

    ledger = _store().list_events(group.id)
    found = balances.debt_sources(
        ledger,
        debtor=events.MemberId(debtor_id),
        creditor=events.MemberId(creditor_id),
        group_id=events.GroupId(group.id),
        currency=group.currency,
    )
    return _json_response(
        {
            "currency": group.currency.code,
            "debtor_id": debtor_id,
            "creditor_id": creditor_id,
            "amount": _amount(abs(found.amount.cents), group.currency),
            # Read from the debtor's side: a debt they owe is a position in the red,
            # which is what ``_direction`` spells ``owes`` for a net row.
            "direction": _direction(-found.amount.cents),
            # The walk returns ordering key ascending and the feed shows newest first,
            # so this reverses it exactly as ``_list_expenses`` reverses the store's
            # order, and ties break by descending event id the same way.
            "entries": [
                _debt_entry_view(entry) for entry in reversed(found.entries)
            ],
        },
        200,
    )


def _direction(cents: int) -> str:
    """``owed`` when they are owed money, ``owes`` when they owe it, else ``settled``."""
    if cents > 0:
        return "owed"
    if cents < 0:
        return "owes"
    return "settled"


def _client_address() -> str:
    """The client key for the rate limiter: ``request.remote_addr`` and nothing else.

    ``X-Forwarded-For`` is spoofable, and trusting a header a client controls is worse
    than having no per-address bucket at all. Whoever deploys behind a proxy owns
    configuring a trusted-proxy story; that is out of scope here, which is also why the
    address limit is 30 rather than 10.
    """
    return flask.request.remote_addr or ""


# --- Serving the shell ------------------------------------------------------


def _shell_document() -> flask.Response:
    """``GET /``: the shell document itself."""
    return _static_file("index.html")


def _static_path(filename: str) -> flask.Response:
    """Any other path under the app directory, or a 404."""
    return _static_file(filename)


def _static_file(filename: str) -> flask.Response:
    """Read one file out of the app directory, refusing anything outside it.

    The content type comes from :data:`EXTENSIONS` and never from ``mimetypes``. The
    resolved path is checked for containment rather than the requested one, so an
    encoded traversal, a backslash on Windows and a symlink all end at the same 404.
    """
    app_dir = _settings().app_dir.resolve()
    try:
        candidate = (app_dir / filename).resolve()
        inside = candidate == app_dir or app_dir in candidate.parents
        found = inside and candidate.is_file()
    except (ValueError, OSError):
        # A name the operating system will not even look at: an embedded null byte,
        # a character it forbids, a path past its length limit. ``resolve`` and
        # ``is_file`` raise on those *before* the containment check above can run, so
        # a correct containment check is not on its own enough to keep every bad path
        # at 404. It is refused here like any other one rather than becoming a 500.
        found = False
    if not found:
        flask.abort(404)
    content_type = EXTENSIONS.get(candidate.suffix.lower(), _DEFAULT_CONTENT_TYPE)
    return flask.Response(candidate.read_bytes(), content_type=content_type)


# --- The factory ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ApiRoute:
    """One API route, and the access it requires, in one row.

    Invariants, all checked eagerly in ``__post_init__``:

    * ``rule`` is a ``str`` equal to :data:`_API_PREFIX` or beginning with it followed
      by ``/``, so the prefix is a path segment and ``/apiary`` is not under it.
    * ``endpoint`` is a non-empty ``str``, unique across :data:`_API_ROUTES`.
    * ``methods`` is a non-empty ``tuple`` of upper-case ``str``.
    * ``access`` is an :class:`_Access`.

    ``access`` deliberately has no default value, and neither does any other field.
    A row that does not state what it requires is a ``TypeError`` at import rather
    than an endpoint that quietly answers anybody, which is the whole of this
    mechanism: giving ``access`` a default would restore the trap the type exists to
    close.
    """

    rule: str
    endpoint: str
    view: Callable[..., flask.Response]
    methods: tuple[str, ...]
    access: _Access

    def __post_init__(self) -> None:
        if not isinstance(self.rule, str):
            raise TypeError(
                f"rule must be a str, got {type(self.rule).__name__}: {self.rule!r}"
            )
        # A path segment, not a string prefix: ``/apiary`` is not under ``/api``.
        if not (
            self.rule == _API_PREFIX or self.rule.startswith(_API_PREFIX + "/")
        ):
            raise ValueError(
                f"rule must be {_API_PREFIX!r} or start with {_API_PREFIX + '/'!r}, "
                f"got {self.rule!r}"
            )
        if not isinstance(self.endpoint, str):
            raise TypeError(
                f"endpoint must be a str, got "
                f"{type(self.endpoint).__name__}: {self.endpoint!r}"
            )
        if not self.endpoint:
            raise ValueError(f"endpoint must be a non-empty str, got {self.endpoint!r}")
        if not isinstance(self.methods, tuple):
            raise TypeError(
                f"methods must be a tuple, got "
                f"{type(self.methods).__name__}: {self.methods!r}"
            )
        if not self.methods:
            raise ValueError(f"methods must be a non-empty tuple, got {self.methods!r}")
        for method in self.methods:
            if not isinstance(method, str):
                raise TypeError(
                    f"every method must be a str, got "
                    f"{type(method).__name__} in methods={self.methods!r}"
                )
            if method != method.upper():
                raise ValueError(
                    f"every method must be upper case, got methods={self.methods!r}"
                )
        if not isinstance(self.access, _Access):
            raise TypeError(
                f"access must be an _Access, got "
                f"{type(self.access).__name__}: {self.access!r}"
            )


_API_ROUTES: Final[tuple[_ApiRoute, ...]] = (
    _ApiRoute("/api/signup", "signup", _signup, ("POST",), _Access.ANONYMOUS),
    _ApiRoute(
        "/api/session",
        "create_session",
        _create_session,
        ("POST",),
        _Access.ANONYMOUS,
    ),
    _ApiRoute(
        "/api/session", "read_session", _read_session, ("GET",), _Access.SESSION
    ),
    _ApiRoute(
        "/api/session",
        "delete_session",
        _delete_session,
        ("DELETE",),
        _Access.ANONYMOUS,
    ),
    _ApiRoute(
        "/api/members", "list_members", _list_members, ("GET",), _Access.MEMBER
    ),
    _ApiRoute(
        "/api/expenses", "list_expenses", _list_expenses, ("GET",), _Access.MEMBER
    ),
    _ApiRoute(
        "/api/expenses", "create_expense", _create_expense, ("POST",), _Access.MEMBER
    ),
    _ApiRoute(
        "/api/balances", "read_balances", _read_balances, ("GET",), _Access.MEMBER
    ),
    _ApiRoute(
        "/api/debts/<debtor_id>/<creditor_id>",
        "read_debt",
        _read_debt,
        ("GET",),
        _Access.MEMBER,
    ),
)
"""Every route the JSON API answers, each with the access it requires.

Three rows share the rule ``/api/session`` and differ by endpoint and method, which is
why the table is keyed by row rather than by path. The order is the order the routes
are registered in.

There is no second literal to keep in step with this one. The three separate sets of
endpoint names that used to carry this information are deleted outright rather than
derived from here, because a constant nothing reads is the next version of the trap
this table closes, and the next person to edit one would be editing something with no
effect.
"""

_SHELL_ROUTES: Final[
    tuple[tuple[str, str, Callable[..., flask.Response], tuple[str, ...]], ...]
] = (
    ("/", "shell_document", _shell_document, ("GET",)),
    ("/<path:filename>", "static_path", _static_path, ("GET",)),
)
"""The two routes that are deliberately not API routes and deliberately ungated.

They serve files and nothing else: ``_static_file`` refuses anything outside the app
directory, so neither of them can reach the ledger. A route added here is a route with
no session check, no CSRF check and no member check, which is why this is a
declaration rather than an omission. The audit reads it, so a shell route cannot be
registered without appearing here, and a reader of this file sees the ungated routes
listed rather than having to notice their absence from the other table.

Each row is ``(rule, endpoint, view, methods)``, mirroring :class:`_ApiRoute`'s fields
without ``access``: these routes have no access policy, which is the point of them.
"""


def _access_map(routes: tuple[_ApiRoute, ...]) -> dict[str, _Access]:
    """The ``endpoint -> _Access`` mapping for a tuple of rows.

    Refuses two rows sharing an endpoint name, naming it. ``_before_request`` keys off
    the endpoint, so a duplicate would silently hand one of the two rows the other's
    policy, and the quieter of the two failures is the dangerous one.
    """
    mapping: dict[str, _Access] = {}
    for route in routes:
        if route.endpoint in mapping:
            raise ValueError(
                f"two routes share the endpoint name {route.endpoint!r}; the access "
                f"policy is looked up by endpoint, so the name must be unique"
            )
        mapping[route.endpoint] = route.access
    return mapping


_API_ACCESS: Final[dict[str, _Access]] = _access_map(_API_ROUTES)
"""What each API endpoint requires, built once at import and never written to.

``_before_request`` reads this and nothing else: an endpoint absent from it under
:data:`_API_PREFIX` is refused rather than served.
"""


class _RouteNotDeclared(RuntimeError):
    # Not a ``WebError`` and not a ``DomainError``: this is a programming error in
    # this repo, not a refusal of a request, and giving it a code would put it in a
    # contract clients branch on.
    """The route map and the tables disagree, or the tables disagree with themselves.

    Raised by :func:`_audit_routes` for a route the app serves that no row declares,
    for a row no registered rule matches, and for a ``_SHELL_ROUTES`` row claiming a
    rule under :data:`_API_PREFIX`; and by ``_before_request`` for a ``/api`` rule
    that reaches it with no declared policy. It reaches a client as the ordinary
    unmapped 500, generic message and logged traceback, because it is unmapped in
    :data:`ERROR_STATUS` and :data:`ERROR_CODE` like any other bug.
    """


def _audit_routes(app: flask.Flask) -> None:
    """Refuse an app whose route map is not exactly what the two tables declare.

    This lives in :func:`create_app` rather than only in a test on purpose. A test
    runs when somebody runs the suite; this runs in every process that ever serves
    this app, which is the suite, ``scripts/serve.py`` and whatever eventually runs
    it for real. It is also what makes the declaration binding rather than
    conventional: Flask's own rule registration is public and one line away, so a
    registration helper alone would only bind the people who chose to call it.

    The comparison key is ``(rule, endpoint, methods)`` with ``HEAD`` and ``OPTIONS``
    subtracted, because Flask adds both to every rule on its own. It covers every rule
    in ``app.url_map``, not only those under :data:`_API_PREFIX`, so an API route
    registered at some other prefix cannot slip past it.

    It also refuses a ``_SHELL_ROUTES`` row under :data:`_API_PREFIX`. ``_ApiRoute``
    refuses a rule outside the prefix, and this is the converse, so the two tables are
    disjoint by construction rather than by convention: without it an ``/api`` row in
    the ungated table is declared, audits clean, and is served with no gate at all.

    Raises:
        _RouteNotDeclared: if a ``_SHELL_ROUTES`` row claims a rule under
            :data:`_API_PREFIX`, if the app serves a route no row declares, or if a
            row declares a route the app does not serve.
    """
    misfiled = tuple(
        rule
        for rule, _endpoint, _view, _methods in _SHELL_ROUTES
        if rule == _API_PREFIX or rule.startswith(_API_PREFIX + "/")
    )
    if misfiled:
        raise _RouteNotDeclared(
            f"_SHELL_ROUTES in src/splitwise_lite/web.py declares "
            f"{', '.join(misfiled)} under {_API_PREFIX}, and every row in that table "
            "is served with no session check, no CSRF check and no member check, so "
            "it would answer anybody who asks. An API route belongs in _API_ROUTES, "
            "in a row naming the access it requires; _SHELL_ROUTES is for the shell "
            "document and the static files, which reach no ledger."
        )
    declared = {
        (route.rule, route.endpoint, frozenset(route.methods) - {"HEAD", "OPTIONS"})
        for route in _API_ROUTES
    } | {
        (rule, endpoint, frozenset(methods) - {"HEAD", "OPTIONS"})
        for rule, endpoint, _view, methods in _SHELL_ROUTES
    }
    served = {
        (rule.rule, rule.endpoint, frozenset(rule.methods or ()) - {"HEAD", "OPTIONS"})
        for rule in app.url_map.iter_rules()
    }
    undeclared = served - declared
    if undeclared:
        offending = ", ".join(
            f"{' '.join(sorted(methods))} {rule} (endpoint {endpoint!r})"
            for rule, endpoint, methods in sorted(
                undeclared, key=lambda row: (row[0], row[1], sorted(row[2]))
            )
        )
        raise _RouteNotDeclared(
            f"this app serves {offending}, and no row in _API_ROUTES or "
            "_SHELL_ROUTES declares it. Until a route is declared it reaches no "
            "session check, no CSRF check and no member check, so it answers anybody "
            "who asks. Fix it in src/splitwise_lite/web.py by appending a row to "
            "_API_ROUTES naming the rule, the endpoint, the view, the methods and "
            "the access it requires: ANONYMOUS needs no session at all, SESSION "
            "needs a valid session and no member row, MEMBER needs a valid session "
            "and a linked member row in the group. MEMBER is what a new endpoint "
            "gets unless somebody argues otherwise. If the route is genuinely not "
            "part of the API, it goes in _SHELL_ROUTES instead, where it is served "
            "with no session check at all."
        )
    missing = declared - served
    if missing:
        absent = ", ".join(
            f"{' '.join(sorted(methods))} {rule} (endpoint {endpoint!r})"
            for rule, endpoint, methods in sorted(
                missing, key=lambda row: (row[0], row[1], sorted(row[2]))
            )
        )
        raise _RouteNotDeclared(
            f"_API_ROUTES or _SHELL_ROUTES in src/splitwise_lite/web.py declares "
            f"{absent}, and this app does not serve it. The audit is an equality "
            "in both directions, so a table that claims a route nobody "
            "registered is a failure too: either register the row in create_app or "
            "delete it from the table."
        )


def create_app(
    *,
    store_path: str | Path,
    secure_cookies: bool,
    app_dir: Path | None = None,
    scrypt_params: accounts.ScryptParams | None = None,
) -> flask.Flask:
    """Build the WSGI application that serves ``app/`` and the JSON API.

    ``store_path`` is passed to ``open_store`` unchanged: no default path, no
    environment variable and no directory created, matching tasks 6 and 9.

    ``secure_cookies`` is required and has no default, so every caller states it and
    nobody gets it wrong by omission. There is no code path that derives it from the
    request scheme, an environment variable or a debug flag: a security control that
    quietly turns itself off is the class of mistake task 7 forbade when it banned a
    fallback to a weaker KDF.

    ``app_dir`` defaults to the repository's ``app/`` resolved from this file's own
    location, never from the working directory. ``scrypt_params`` defaults to the
    production cost and exists so the suite can drive the hashing endpoints without
    spending 64 MiB per call.

    It binds no socket and starts no server: the return value is a plain WSGI
    application any server can mount. Picking one is a deployment task, and Werkzeug's
    development server is not it.

    Raises:
        ValueError: if ``store_path`` is ``IN_MEMORY``.
        TypeError: if ``secure_cookies`` is not a ``bool``.
    """
    if store_path == store.IN_MEMORY:
        raise ValueError(
            "the app opens one store per request, and a private in-memory database "
            "would be a fresh, empty ledger every request; pass a file path"
        )

    app = flask.Flask(__name__, static_folder=None)  # no /static route at all
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    app.config["STORE_PATH"] = store_path
    app.config["APP_DIR"] = _APP_DIR if app_dir is None else Path(app_dir)
    app.config["SECURE_COOKIES"] = secure_cookies
    app.extensions["splitwise_lite"] = _Settings(
        store_path=store_path,
        secure_cookies=secure_cookies,
        app_dir=app.config["APP_DIR"],
        scrypt_params=(
            accounts.DEFAULT_SCRYPT_PARAMS if scrypt_params is None else scrypt_params
        ),
    )

    for route in _API_ROUTES:
        app.add_url_rule(
            route.rule, route.endpoint, route.view, methods=list(route.methods)
        )
    for rule, endpoint, view, methods in _SHELL_ROUTES:
        app.add_url_rule(rule, endpoint, view, methods=list(methods))

    app.before_request(_before_request)
    app.after_request(_after_request)
    app.teardown_appcontext(_close_store)
    app.register_error_handler(Exception, _handle_error)
    # Last, before the app escapes. _audit_routes says why it is here, not in a test.
    _audit_routes(app)
    return app


def _before_request() -> None:
    """Run the CSRF gates, then authentication, then the member requirement.

    Nothing runs for a request that did not route: an unrouted request reaches no
    handler and changes nothing, so ``PUT /api/session`` is the 405 it should be rather
    than a CSRF refusal.

    Authentication is checked **before** group resolution, so an unauthenticated caller
    against a store with no group gets 401 rather than a 503 that tells them how the
    server is configured.

    An ``/api`` rule with no row in :data:`_API_ACCESS` is refused here rather than
    waved through. :func:`_audit_routes` has already refused to build an app that
    serves one, so this is the second line: it speaks for an app this factory did not
    build, or for a rule added to one after that audit ran.
    """
    endpoint = flask.request.endpoint
    matched = flask.request.url_rule
    if endpoint is None or matched is None:
        return
    access = _API_ACCESS.get(endpoint)
    if access is None:
        # Classified from the rule that matched, never from ``flask.request.path``:
        # the shell's ``/<path:filename>`` catch-all matches ``/api/nope``, so a
        # path-based test would turn today's 404 into a 500. The prefix is a path
        # segment here too, the same question :func:`_audit_routes` asks.
        if matched.rule == _API_PREFIX or matched.rule.startswith(_API_PREFIX + "/"):
            raise _RouteNotDeclared(
                f"the rule {matched.rule} (endpoint {endpoint!r}) is under "
                f"{_API_PREFIX} and no row in _API_ROUTES declares what it requires, "
                "so the request is refused rather than served. Declare it in "
                "src/splitwise_lite/web.py, in a row naming the access it requires. "
                # This hook sees a rule and a policy that is missing, and nothing
                # about how the rule was registered. Naming one cause as a fact sends
                # the reader to the wrong file, so the message says only what
                # _audit_routes guarantees and leaves the rest open.
                "How the rule came to be registered is not something this hook can "
                "see. _audit_routes refuses to build an app that serves an "
                "undeclared rule, so either this app was not built by create_app, or "
                "the rule was added to it after that audit ran."
            )
        return
    if flask.request.method in _STATE_CHANGING_METHODS:
        _check_csrf()
    if access is _Access.ANONYMOUS:
        return
    flask.g.session = _authenticate()
    if access is _Access.SESSION:
        return
    flask.g.group = _acting_group()
    flask.g.member = _acting_member()


def _after_request(response: flask.Response) -> flask.Response:
    """Add the security headers and write whatever cookies this request decided on.

    Every ``Set-Cookie`` this app sends is written here, from a decision a handler or
    the error handler recorded on ``flask.g``. One place, so a cookie cannot be lost
    by a handler whose response was later replaced by an error response, and so the
    attributes of a write and of the matching delete cannot drift apart.
    """
    for name, value in _SECURITY_HEADERS.items():
        response.headers[name] = value

    issued = getattr(flask.g, "issue_session", None)
    if issued is not None:
        _set_session_cookie(response, issued)
    elif getattr(flask.g, "clear_session", False):
        _clear_session_cookie(response)

    rotated = getattr(flask.g, "rotate_csrf", None)
    if rotated is not None:
        _set_csrf_cookie(response, rotated)
    elif getattr(flask.g, "clear_csrf", False):
        _clear_csrf_cookie(response)
    elif (
        flask.request.method in _CSRF_ISSUING_METHODS
        and CSRF_COOKIE not in flask.request.cookies
    ):
        # Issued on the first safe request, so loading the shell always yields one
        # and the login POST can carry a header before any session exists.
        _set_csrf_cookie(response, secrets.token_urlsafe(_CSRF_TOKEN_BYTES))
    return response


def _close_store(exception: BaseException | None) -> None:
    """Close this request's store, on the way out and on an exception alike."""
    opened = flask.g.pop("_store", None)
    if opened is not None:
        opened.close()


def _handle_error(error: Exception) -> flask.Response:
    """Turn any exception into the one JSON error body, at the mapped status.

    Everything except a 500 carries ``str(error)``: those strings were written
    deliberately in this repo for a person to read, and task 7 already guarantees none
    of them contains a password. A 500 carries one fixed generic string and the real
    exception goes to the log with its traceback, because a 500 message can carry a
    file path, a SQL fragment or a stored hash. The two 503 rows keep their own
    messages on purpose, because naming the setup command is the whole value of them.

    Routing's own refusals arrive here too, as exceptions carrying an HTTP status. Their
    response is reused so headers such as ``Allow`` survive, with the body replaced by
    the same JSON shape: a client never has to parse an HTML error page.
    """
    http_status = getattr(error, "code", None)
    if isinstance(http_status, int) and callable(getattr(error, "get_response", None)):
        response = error.get_response()
        code = _HTTP_ERROR_CODES.get(http_status, _HTTP_ERROR_FALLBACK_CODE)
        if http_status >= _INTERNAL_ERROR_STATUS:
            # Nothing here raises one, but if something ever does it is a 500 like
            # any other: generic message, real exception in the log.
            flask.current_app.logger.exception(
                "%s %s failed with %s",
                flask.request.method,
                flask.request.path,
                type(error).__name__,
            )
            message = _GENERIC_500_MESSAGE
            code = _FALLBACK_CODE
        else:
            message = str(error)
        response.set_data(json.dumps(_error_body(code, message)))
        response.content_type = _JSON_MEDIA_TYPE
        return response

    status, code = _status_and_code(error)
    if status == _INTERNAL_ERROR_STATUS:
        # The generic message and the logged traceback are for exactly this status:
        # a 500 is either an unmapped failure or database damage, and its message can
        # carry a file path, a SQL fragment or a stored hash. Every other status,
        # 503 included, carries ``str(error)``: those strings were written
        # deliberately in this repo for a person to read, which is why
        # ``NoGroupConfigured`` can name the command that fixes it and
        # ``AmbiguousGroup`` can name both group ids.
        flask.current_app.logger.exception(
            "%s %s failed with %s",
            flask.request.method,
            flask.request.path,
            type(error).__name__,
        )
        response = _json_response(_error_body(code, _GENERIC_500_MESSAGE), status)
    else:
        response = _json_response(_error_body(code, str(error)), status)
    retry_after = getattr(error, "retry_after", None)
    if isinstance(retry_after, int):
        response.headers["Retry-After"] = str(retry_after)
    if isinstance(error, accounts.SessionInvalid):
        # Without this a stale token sits in the browser producing a 401 on every
        # request forever, and the user has no way to get rid of it. NotAuthenticated
        # clears nothing, because there was nothing there to clear.
        flask.g.clear_session = True
    return response
