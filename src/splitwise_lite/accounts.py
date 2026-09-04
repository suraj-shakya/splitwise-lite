"""Accounts and sign-in: making an account, holding a session, knowing who acts.

A library, not a web server. Nothing here is a framework, a form, a redirect or a
header, and no function takes or returns anything from a network: tasks 9, 10, 11, 14
and 15 call these functions directly. Everything about carrying a token between a
browser and the app is task 10's, and this module makes none of those decisions. What
it provides is the values they need.

**A password is stored as an scrypt hash at n = 65536, r = 8, p = 2**, with a 16-byte
salt drawn fresh for every hash and a 32-byte derived key. scrypt is memory-hard, so
every guess an attacker makes costs the same 64 MiB the honest login cost, which is
what a rented GPU cannot parallelise away cheaply. The alternative in the standard
library, PBKDF2, is CPU-hard only. There is no second algorithm, no negotiation and no
fallback: a silent downgrade to a weaker one is the failure this decision exists to
prevent.

**The stored form is self-describing**, four ``$``-separated fields::

    scrypt$n=65536,r=8,p=2$<salt base64>$<derived key base64>

so the cost travels with the hash and can be raised later without invalidating a
single row already written. Verification reads the parameters out of the string it is
checking, never out of today's defaults.

**A session is a row keyed by the SHA-256 of a 256-bit token.** The token comes from
``secrets.token_urlsafe``, is handed to the caller exactly once, at login, and is never
stored anywhere: a stolen database file then holds no credential anyone can present.
The fast hash is right here for the same reason the slow one is right for a password.
A token is 256 bits of uniform entropy with nothing to guess, so there is no work
factor to add, and running a memory-hard function on every authenticated call would be
a denial of service the app inflicts on itself.

**A session lasts 30 days, absolutely.** No sliding renewal, which would mean a write
on every call and an eviction policy to go with it, and no idle timeout. Logging out
deletes the row, because a session is operational state rather than ledger history.
Changing a password deletes every session that user holds, including the one that asked
for the change: leaving a session alive after a credential change is the exact hole
that makes changing a leaked password pointless.

**Signing up links nothing.** A new account gets no group and no member record.
Matching a new account to a seeded member record by address would let anyone who knows
a flatmate's address take over their position in the ledger, and there is no verified
channel in this product that could make such a match trustworthy. Task 9 owns writing
that link; this module never writes it, and reading it is one call on the store.

**Every function that needs the time takes it as an argument.** This module reads no
clock, so the same inputs produce the same rows, and a test does not have to freeze
anything. A caller who passes a dishonest timestamp can revive an expired session,
which is true of any clock an in-process caller could read.

Dependency direction: this module imports from ``store``, ``events`` and ``money``, and
none of those three knows it exists. It writes no statement and names no table: all
storage goes through ``EventStore``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cache
from typing import Final, NoReturn

from .events import new_id
from .money import DomainError
from .store import EventStore, InvalidRecord, RecordNotFound, Session, User, UserId

__all__ = [
    "DEFAULT_SCRYPT_PARAMS",
    "HASH_ALGORITHM",
    "MAX_EMAIL_LENGTH",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "SALT_BYTES",
    "SESSION_LIFETIME",
    "TOKEN_BYTES",
    "AccountError",
    "AuthenticationFailed",
    "EmailAlreadyRegistered",
    "InvalidEmail",
    "InvalidPassword",
    "IssuedSession",
    "PasswordHashInvalid",
    "ScryptParams",
    "SessionInvalid",
    "authenticate",
    "change_password",
    "hash_password",
    "log_in",
    "log_out",
    "log_out_everywhere",
    "normalise_email",
    "sign_up",
    "verify_password",
]


class AccountError(DomainError):
    """Base class for every error this module raises.

    A subclass of ``DomainError``, so task 10 still maps one exception family to one
    response. A wrong Python type raises ``TypeError`` instead and is deliberately not
    part of this family: rejected input is a domain error, a wrong type is a bug.
    """


class InvalidEmail(AccountError):
    """Raised when an address cannot be used as an account name.

    Shape only. Nothing here asks whether the address exists, accepts mail or resolves:
    there is no lookup of any kind, and delivery is not this product's business.
    """


class InvalidPassword(AccountError):
    """Raised when a password fails the policy, at signup or at a password change.

    Length and "not only whitespace" are the whole policy. Never raised by ``log_in``,
    which asks the stored hash rather than the policy, so a password that was legal
    under an earlier minimum keeps working after it is raised.
    """


class EmailAlreadyRegistered(AccountError):
    """Raised when signing up with an address that already has an account.

    This tells an attacker that an address is registered here, and that is an accepted
    v1 gap: hiding it needs the "we have sent you an email" flow that the backlog cuts,
    and what it reveals is that someone in a flat share uses this app.
    """


class AuthenticationFailed(AccountError):
    """Raised when a login, or a password change, is not entitled to proceed.

    Every login failure raises this with one message that names neither which field was
    wrong nor whether the address exists, because an error that distinguishes them is
    an account enumeration oracle.
    """


class SessionInvalid(AccountError):
    """Raised when a token does not name a live session.

    One error for an unknown token, an expired one, a malformed one and an over-long
    one, carrying no detail about which it was: "you were signed out, sign in again" is
    the same screen either way.
    """


class PasswordHashInvalid(AccountError):
    """Raised when a stored hash is not one this module could have written.

    A corrupt or hand-edited row is a bug report. Reporting it as a wrong password
    would hide database damage behind a support ticket about a forgotten one. It is
    also what a set of parameters outside the bounds below raises, so a row claiming
    n = 2**40 is refused rather than asked to allocate a terabyte.
    """


HASH_ALGORITHM: Final[str] = "scrypt"
"""The label in the first field of every stored hash.

A label rather than a version number, so the string says what made it. Nothing reads
any other value: there is no legacy format and no negotiation.
"""

SALT_BYTES: Final[int] = 16
"""Bytes of salt per hash, drawn from ``secrets.token_bytes`` for every single call.

A salt is what makes two people with the same password store two different hashes, so
one cracked hash stays one cracked account and a precomputed table is worthless.
"""

TOKEN_BYTES: Final[int] = 32
"""Bytes of entropy in a session token: 256 bits, rendered as 43 URL-safe characters.

Enough that guessing is not a strategy, so the token needs no work factor of its own.
"""

MIN_PASSWORD_LENGTH: Final[int] = 12
"""The whole strength policy, along with the maximum: length, measured after
normalisation. No required digit, no required symbol, no case mix, no dictionary and no
breach list. Length is the property that actually resists an offline attack, and the
composition rules are what push people towards ``Passw0rd!``."""

MAX_PASSWORD_LENGTH: Final[int] = 1024
"""The cap that keeps unbounded input away from a memory-hard function.

Feeding a megabyte to scrypt is a denial of service a caller should not be able to
ask for, and no real password is 1025 characters.
"""

MAX_EMAIL_LENGTH: Final[int] = 254
"""The longest address accepted, which is the longest an SMTP path may carry."""

SESSION_LIFETIME: Final[timedelta] = timedelta(days=30)
"""How long a session lives, from creation, absolutely.

Written into the row at login and never extended. A flatmate signs in again once a
month; the alternative is a write on every authenticated call.
"""

# The bounds every set of scrypt parameters is held to, whether it was written by a
# caller or read back out of a stored hash. They are what stands between a hand-edited
# row and an allocation nothing in this process could survive.
_MIN_N: Final[int] = 2
_MAX_N: Final[int] = 2**20
_MIN_R: Final[int] = 1
_MAX_R: Final[int] = 32
_MIN_P: Final[int] = 1
_MAX_P: Final[int] = 16
_MIN_DKLEN: Final[int] = 16
_MAX_DKLEN: Final[int] = 64

_MAX_TOKEN_LENGTH: Final[int] = 4096
"""Longest string accepted as a token before it is refused unread. A token is 43
characters; anything of this size is somebody probing, not a session."""

_TOKEN_CHARACTERS: Final[frozenset[str]] = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)
"""The URL-safe base64 alphabet ``secrets.token_urlsafe`` draws from. A string with
anything else in it cannot be a token this module issued, so it is refused without a
read."""

_PARAMETER_PATTERN: Final[re.Pattern[str]] = re.compile(r"\An=(\d+),r=(\d+),p=(\d+)\Z")
"""The second field of a stored hash, in exactly that key order and integers only.

Anchored and exact, so a reordered, spaced or non-integer field is a corrupt hash
rather than something to interpret generously.
"""

_LOGIN_FAILED: Final[str] = "that email address and password do not match an account"
"""The one message every login failure carries.

One string for the unknown address, the wrong password, the account with no password
set and the address that is not an address, so the error cannot be read as an answer
to "does this account exist".
"""

_CURRENT_PASSWORD_WRONG: Final[str] = "the current password is not correct"
"""What a password change says when the current password does not verify. Naming the
field is safe here and nowhere else: the caller has already claimed to be this user,
and nothing about whether the account exists is revealed by it."""

_DUMMY_PASSWORD: Final[str] = "the password of the account that does not exist"
"""What the equalising hash is built from, so a login for an unknown address costs the
same work as one for a known address with the wrong password."""


# --- Internals: validation ---------------------------------------------------


def _require_bounded(value: object, name: str, low: int, high: int) -> int:
    """Return ``value`` if it is an ``int`` within the inclusive bounds, else raise."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}: {value!r}")
    if not low <= value <= high:
        raise PasswordHashInvalid(f"{name} must be {low} to {high}, got {value}")
    return value


def _require_utc(value: object, name: str) -> datetime:
    """Return ``value`` converted to UTC, else raise.

    The rule task 6 already applies to every stored timestamp: a wrong type is a
    programming error and raises ``TypeError``, a naive datetime is rejected rather
    than assumed to be UTC, and whatever arrives is converted before it is compared or
    stored.
    """
    if not isinstance(value, datetime):
        raise TypeError(
            f"{name} must be a datetime, got {type(value).__name__}: {value!r}"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidRecord(f"{name} must be timezone-aware, got naive {value!r}")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ScryptParams:
    """The cost of one password hash: scrypt's ``n``, ``r`` and ``p``, and the key size.

    Invariants, enforced here so that a bad set cannot be constructed at all, whether
    it came from a caller or out of a stored hash:

    * ``n`` is a power of two between 2 and 2**20. scrypt itself requires a power of
      two; the ceiling is what stops a hand-edited row claiming 2**40 from asking for a
      terabyte of memory before anything else gets a say.
    * ``r`` is between 1 and 32, ``p`` between 1 and 16, ``dklen`` between 16 and 64.
    * All four are ``int`` and never ``bool``.

    Frozen and compared by value, like every other value type in this package, so two
    sets that say the same thing are the same set.
    """

    n: int
    r: int
    p: int
    dklen: int = 32

    def __post_init__(self) -> None:
        _require_bounded(self.n, "scrypt n", _MIN_N, _MAX_N)
        if self.n & (self.n - 1):
            raise PasswordHashInvalid(f"scrypt n must be a power of two, got {self.n}")
        _require_bounded(self.r, "scrypt r", _MIN_R, _MAX_R)
        _require_bounded(self.p, "scrypt p", _MIN_P, _MAX_P)
        _require_bounded(self.dklen, "scrypt dklen", _MIN_DKLEN, _MAX_DKLEN)


DEFAULT_SCRYPT_PARAMS: Final[ScryptParams] = ScryptParams(n=65536, r=8, p=2)
"""The cost every hash this module writes is made at: 64 MiB and a few hundred
milliseconds per attempt on a development laptop.

One of the configurations OWASP lists as equivalent work to its scrypt minimum. The
alternative with the same work, n = 131072 with p = 1, costs 128 MiB per concurrent
login for no extra resistance, and this app runs on a small host. A test asserts these
exact numbers, so raising the cost is a visible edit rather than a drift.
"""


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A new session, with the one copy of its token the caller will ever be given.

    ``token`` is deliberately absent from the ``repr``. A credential reaches a log
    through a repr far more often than through a deliberate print, and this object is
    exactly the kind that gets logged on the way through a handler.

    ``session`` is the row as it was stored, holding the hash of the token rather than
    the token, so it can be passed on and printed freely.
    """

    token: str = field(repr=False)
    session: Session

    def __post_init__(self) -> None:
        if not isinstance(self.token, str):
            raise TypeError(
                f"IssuedSession token must be a str, got {type(self.token).__name__}"
            )
        if not self.token:
            raise InvalidRecord("IssuedSession token must not be empty")
        if not isinstance(self.session, Session):
            raise TypeError(
                f"IssuedSession session must be a Session, got "
                f"{type(self.session).__name__}"
            )


# --- Internals: the KDF ------------------------------------------------------


def _maxmem(params: ScryptParams) -> int:
    """Return the memory limit scrypt needs for ``params``: ``128 * r * (n + p + 2)``.

    Computed rather than hardcoded, and this is load-bearing. OpenSSL's default limit
    is 32 MiB, which is less than the recommended parameters need, so a call that
    leaves this out fails outright rather than running more cheaply. Deriving it from
    the parameters in hand also means verifying a hash stored with larger parameters
    than today's defaults still works.
    """
    return 128 * params.r * (params.n + params.p + 2)


def _derive(password: str, salt: bytes, params: ScryptParams) -> bytes:
    """Return the derived key for an already-normalised password.

    The only place this module calls a key derivation function, so the cost of a login
    is one call to this and the count of them is what a test can assert against.
    """
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=params.n,
        r=params.r,
        p=params.p,
        maxmem=_maxmem(params),
        dklen=params.dklen,
    )


def _normalise_password(password: object) -> str:
    """Return ``password`` in NFKC, so one typed secret has one spelling.

    The same characters entered on a keyboard that composes and one that decomposes
    are the same password. Nothing is stripped: a leading space is part of the secret.
    """
    if not isinstance(password, str):
        raise TypeError(
            f"a password must be a str, got {type(password).__name__}"
        )
    return unicodedata.normalize("NFKC", password)


def _require_password_policy(password: object) -> str:
    """Return the normalised password if it satisfies the policy, else raise.

    Applied at signup and at a password change, and never at login. Length is measured
    after normalisation, because that is the string that gets hashed. The whitespace
    check rejects a held-down space bar, which is long enough and is not something
    anybody could retype; it inspects a stripped copy and stores the original.
    """
    normalised = _normalise_password(password)
    if len(normalised) < MIN_PASSWORD_LENGTH:
        raise InvalidPassword(
            f"a password must be at least {MIN_PASSWORD_LENGTH} characters, got "
            f"{len(normalised)}"
        )
    if len(normalised) > MAX_PASSWORD_LENGTH:
        raise InvalidPassword(
            f"a password must be at most {MAX_PASSWORD_LENGTH} characters, got "
            f"{len(normalised)}"
        )
    if not normalised.strip():
        raise InvalidPassword("a password must not be whitespace alone")
    return normalised


def _decode_field(text: str, name: str) -> bytes:
    """Return the bytes ``text`` encodes, or raise ``PasswordHashInvalid``.

    Strict base64: ``validate=True`` refuses anything outside the alphabet instead of
    quietly discarding it, so a mangled field is a reported fault rather than a hash
    that will never match.
    """
    try:
        return base64.b64decode(text, validate=True)
    except ValueError as error:
        raise PasswordHashInvalid(
            f"the {name} in a stored hash is not base64"
        ) from error


def _decode(encoded: object) -> tuple[ScryptParams, bytes, bytes]:
    """Split a stored hash into its parameters, its salt and its derived key.

    Every way the string can be wrong raises ``PasswordHashInvalid``: the wrong number
    of fields, an algorithm this module never wrote, parameters out of order or not
    integers, a field that is not base64, an empty salt, or a set of parameters outside
    the bounds ``ScryptParams`` enforces.
    """
    if not isinstance(encoded, str):
        raise TypeError(
            f"a stored hash must be a str, got {type(encoded).__name__}"
        )
    fields = encoded.split("$")
    if len(fields) != 4:
        raise PasswordHashInvalid(
            f"a stored hash has four $-separated fields, got {len(fields)}"
        )
    algorithm, parameters, salt_field, key_field = fields
    if algorithm != HASH_ALGORITHM:
        raise PasswordHashInvalid(
            f"a stored hash must name {HASH_ALGORITHM}, got {algorithm!r}"
        )
    matched = _PARAMETER_PATTERN.match(parameters)
    if matched is None:
        raise PasswordHashInvalid(
            f"a stored hash names its parameters as n=<int>,r=<int>,p=<int>, got "
            f"{parameters!r}"
        )
    salt = _decode_field(salt_field, "salt")
    if not salt:
        raise PasswordHashInvalid("a stored hash carries an empty salt")
    key = _decode_field(key_field, "derived key")
    params = ScryptParams(
        int(matched[1]), int(matched[2]), int(matched[3]), len(key)
    )
    return params, salt, key


@cache
def _dummy_hash() -> str:
    """Return the hash a failed login is checked against, built once per process.

    Built lazily from a module constant at whatever ``DEFAULT_SCRYPT_PARAMS`` says
    today, so it can never go stale against a change to the cost, and cached, so the
    equalising work costs one hash per login rather than two.
    """
    return hash_password(_DUMMY_PASSWORD)


def _fail_login(password: str) -> NoReturn:
    """Spend one hash against the dummy, then raise the one generic login failure.

    Called for every failure that would otherwise skip the key derivation entirely: an
    address nobody has registered, an account with no password set, and a string that
    is not an address at all. Without this, the response time answers the question the
    error message refuses to.
    """
    verify_password(password, _dummy_hash())
    raise AuthenticationFailed(_LOGIN_FAILED) from None


def _hash_token(token: str) -> str:
    """Return the SHA-256 of ``token`` as 64 lowercase hex characters."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_token_shaped(token: str) -> bool:
    """Whether ``token`` could be a token this module issued.

    Length and alphabet only. A string that fails this is refused before anything is
    hashed or read, which keeps a probe from costing a lookup.
    """
    return (
        0 < len(token) <= _MAX_TOKEN_LENGTH and _TOKEN_CHARACTERS.issuperset(token)
    )


# --- Passwords ---------------------------------------------------------------


def hash_password(
    password: str, *, params: ScryptParams = DEFAULT_SCRYPT_PARAMS
) -> str:
    """Return a self-describing scrypt hash of ``password``, with a fresh salt.

    The shape is ``scrypt$n=<int>,r=<int>,p=<int>$<salt>$<key>``, four ``$``-separated
    fields with the parameter keys in that order, both binary fields standard base64.
    The parameters travel with the hash, so raising the cost later invalidates nothing
    already stored.

    No policy is applied here. Length and content are ``sign_up``'s and
    ``change_password``'s business, and enforcing them here would make an old, short
    password unverifiable the day the minimum is raised.

    Raises:
        TypeError: if ``password`` is not a ``str``.
    """
    normalised = _normalise_password(password)
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(normalised, salt, params)
    return (
        f"{HASH_ALGORITHM}$n={params.n},r={params.r},p={params.p}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(key).decode('ascii')}"
    )


def verify_password(password: str, encoded: str) -> bool:
    """Whether ``password`` is the one that produced ``encoded``.

    The parameters and the salt come out of ``encoded`` itself, never out of
    ``DEFAULT_SCRYPT_PARAMS``, so a hash written before the cost changed still verifies
    in either direction. The comparison is ``hmac.compare_digest`` on the two ``bytes``
    objects rather than ``==``, which returns as soon as it finds a difference and so
    tells an attacker how much of a guess was right.

    Raises:
        TypeError: if either argument is not a ``str``.
        PasswordHashInvalid: if ``encoded`` is not a hash this module could have
            written. It never returns ``False`` for that: a corrupt row is a bug
            report, not a forgotten password.
    """
    normalised = _normalise_password(password)
    params, salt, expected = _decode(encoded)
    return hmac.compare_digest(_derive(normalised, salt, params), expected)


# --- Addresses ---------------------------------------------------------------


def normalise_email(value: str) -> str:
    """Return ``value`` with surrounding whitespace removed and lowercased.

    The one place an address is canonicalised, called by ``sign_up`` and by ``log_in``
    so that both agree. Lowercasing the local part is not what RFC 5321 says and is
    what every provider does; one canonical spelling is what makes the unique index on
    the stored address mean "one account per address" rather than "one account per
    spelling of an address".

    Raises:
        TypeError: if ``value`` is not a ``str``.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"an email address must be a str, got {type(value).__name__}"
        )
    return value.strip().lower()


def _require_email(value: str) -> str:
    """Return the normalised address if it is usable, else raise ``InvalidEmail``.

    Exactly one ``@``, a non-empty local part, a domain with at least one dot and no
    empty label, no whitespace inside, printable ASCII only, and at most
    ``MAX_EMAIL_LENGTH`` characters. An internationalised address is a documented v1
    limitation, in the same way zero-decimal currencies are in ``money.py``. Nothing
    here looks anything up.
    """
    address = normalise_email(value)
    if len(address) > MAX_EMAIL_LENGTH:
        raise InvalidEmail(
            f"an email address must be at most {MAX_EMAIL_LENGTH} characters, got "
            f"{len(address)}"
        )
    if not address.isascii() or not address.isprintable():
        raise InvalidEmail(f"an email address must be printable ASCII, got {address!r}")
    if any(character.isspace() for character in address):
        raise InvalidEmail(f"an email address must have no spaces, got {address!r}")
    if address.count("@") != 1:
        raise InvalidEmail(f"an email address must have exactly one @, got {address!r}")
    local, _, domain = address.partition("@")
    if not local:
        raise InvalidEmail(f"an email address must have a local part, got {address!r}")
    labels = domain.split(".")
    if len(labels) < 2 or not all(labels):
        raise InvalidEmail(
            f"an email address must have a dotted domain, got {address!r}"
        )
    return address


# --- Signing up, in and out --------------------------------------------------


def sign_up(
    store: EventStore,
    *,
    email: str,
    display_name: str,
    password: str,
    now: datetime,
    params: ScryptParams = DEFAULT_SCRYPT_PARAMS,
) -> User:
    """Create an account and return the stored ``User``.

    Validates the address and the password, mints an id with ``new_id()``, and writes
    the account and its hash in one store call, so a failure part way through leaves
    neither and the address stays free for the next attempt.

    It creates no session: signing in is a separate call, so this owns no session
    policy and task 10 makes its own decision about whether to sign a new account in.
    It links nothing either. A brand new account can see nothing at all until task 9
    connects it to the member record that acts for it, which is what makes an
    unverified signup harmless.

    Raises:
        TypeError: if an argument is of the wrong type.
        InvalidRecord: if ``now`` is naive, or ``display_name`` is blank or too long.
            Task 6's validation is not re-wrapped here.
        InvalidEmail: if the address is unusable.
        InvalidPassword: if the password fails the policy.
        EmailAlreadyRegistered: if an account already holds that address.
    """
    moment = _require_utc(now, "now")
    address = _require_email(email)
    secret = _require_password_policy(password)
    try:
        store.get_user_by_email(address)
    except RecordNotFound:
        pass
    else:
        raise EmailAlreadyRegistered(f"an account already exists for {address!r}")
    user = User(UserId(new_id()), address, display_name, moment)
    store.add_user_with_credential(user, hash_password(secret, params=params), moment)
    return user


def log_in(
    store: EventStore, *, email: str, password: str, now: datetime
) -> IssuedSession:
    """Check a password and issue a session, returning it with its one token.

    Every failure raises ``AuthenticationFailed`` with the same message and costs the
    same one key derivation, whether or not the address names an account, so neither
    the error nor the wait answers "does this account exist". The two exceptions cost
    nothing on purpose: an empty password and one over ``MAX_PASSWORD_LENGTH`` are
    refused before the derivation, because feeding unbounded input to a memory-hard
    function is the denial of service that cap exists to prevent.

    No policy beyond those two checks is applied. A password that was legal under an
    earlier, shorter minimum keeps working after the minimum is raised.

    Raises:
        TypeError: if an argument is of the wrong type.
        InvalidRecord: if ``now`` is naive.
        AuthenticationFailed: for every failure, with one message.
        DuplicateRecord: if the new token's hash is already stored, which at 256 bits
            means the source of entropy is broken. There is no retry.
    """
    moment = _require_utc(now, "now")
    secret = _normalise_password(password)
    if not secret or len(secret) > MAX_PASSWORD_LENGTH:
        raise AuthenticationFailed(_LOGIN_FAILED)
    try:
        address = _require_email(email)
    except InvalidEmail:
        _fail_login(secret)
    try:
        user = store.get_user_by_email(address)
        stored = store.get_password_hash(user.id)
    except RecordNotFound:
        _fail_login(secret)
    if not verify_password(secret, stored):
        raise AuthenticationFailed(_LOGIN_FAILED)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    session = Session(_hash_token(token), user.id, moment, moment + SESSION_LIFETIME)
    store.add_session(session)
    return IssuedSession(token, session)


def authenticate(store: EventStore, token: str, *, now: datetime) -> Session:
    """Return the live session ``token`` names, or raise ``SessionInvalid``.

    This is the call that turns a bearer token back into "who is acting". Expiry is
    exclusive: a session is live while ``now`` is before its ``expires_at``, so one
    expiring at exactly this instant is already gone.

    It never writes. An expired row is left where it is rather than cleaned up here,
    because a read that writes is lock contention waiting for the first two people to
    open the app at once, and the row is never honoured while it sits there.

    Raises:
        TypeError: if ``token`` is not a ``str``, or ``now`` is not a ``datetime``.
        InvalidRecord: if ``now`` is naive.
        SessionInvalid: if the token is unknown, expired, malformed or over-long. One
            error for all four, carrying no detail about which it was.
    """
    if not isinstance(token, str):
        raise TypeError(f"a token must be a str, got {type(token).__name__}")
    moment = _require_utc(now, "now")
    if not _is_token_shaped(token):
        raise SessionInvalid("that token does not name a live session")
    try:
        session = store.get_session(_hash_token(token))
    except RecordNotFound:
        raise SessionInvalid("that token does not name a live session") from None
    if session.expires_at <= moment:
        raise SessionInvalid("that token does not name a live session")
    return session


def log_out(store: EventStore, token: str) -> None:
    """Delete the session ``token`` names, if there is one.

    Idempotent: calling it twice, with a token that never existed, or with one that has
    already expired, deletes nothing and raises nothing. No ownership is checked,
    because possession of the token is the authority, which is what a bearer token
    means. A deleted session cannot be un-revoked, and there is nothing worth keeping:
    a session is operational state, not part of the ledger.

    Raises:
        TypeError: if ``token`` is not a ``str``.
    """
    if not isinstance(token, str):
        raise TypeError(f"a token must be a str, got {type(token).__name__}")
    if not _is_token_shaped(token):
        return
    store.delete_session(_hash_token(token))


def log_out_everywhere(store: EventStore, user_id: str) -> int:
    """Delete every session that user holds and return how many went.

    The function behind "sign me out of everything", and the one a password change
    performs for itself. No screen calls it in v1. A user holding none returns 0; an
    unknown id raises, so a typo is not reported as "you had none".

    Raises:
        TypeError: if ``user_id`` is not a ``str``.
        RecordNotFound: if no account has that id.
    """
    return store.delete_sessions_for_user(user_id)


def change_password(
    store: EventStore,
    *,
    user_id: str,
    current_password: str,
    new_password: str,
    now: datetime,
    params: ScryptParams = DEFAULT_SCRYPT_PARAMS,
) -> None:
    """Replace a password, revoking every session that user holds along with it.

    The current password is checked first, then the new one against the full policy,
    then the two writes happen in a single transaction inside the store: the hash
    cannot change while a session survives on the old secret, and a failed write
    revokes nothing. The session that asked for the change goes with the others; there
    is no "keep me signed in on this device" to honour.

    A new password equal to the current one is refused. Rewriting the same secret buys
    nothing and costs the user every session they hold.

    Raises:
        TypeError: if an argument is of the wrong type.
        InvalidRecord: if ``now`` is naive.
        RecordNotFound: if the account does not exist or has no password set.
        AuthenticationFailed: if the current password is wrong. Nothing changes.
        InvalidPassword: if the new password fails the policy or repeats the current
            one. Nothing changes.
    """
    moment = _require_utc(now, "now")
    current = _normalise_password(current_password)
    stored = store.get_password_hash(user_id)
    if not verify_password(current, stored):
        raise AuthenticationFailed(_CURRENT_PASSWORD_WRONG)
    replacement = _require_password_policy(new_password)
    if replacement == current:
        raise InvalidPassword("the new password must differ from the current one")
    store.set_password_hash(
        user_id, hash_password(replacement, params=params), moment
    )
