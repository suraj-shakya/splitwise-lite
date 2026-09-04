# Task 7: Accounts and sessions

**Depends on:** 6 (complete, landed on `master`)
**Consumed by:** 9 (group and member setup), 10 (expense entry), 11 (expense feed),
14 (mark as paid), 15 (receiver confirmation)

Sharpened from `plans/backlog.md` task 7. The backlog entry stays as written; this file
is the implementable version.

## Goal

A flatmate can create an account with an email address and a password, sign in, hold a
session that later code can turn back into "this is who is acting", and sign out. The
password is stored only as a salted, memory-hard hash that no code path can reverse, the
session token is unguessable and never stored in a form that could be replayed, and a
signed-in user can be resolved to their member record in a group when task 9 has linked
one. It is a library, not a web server: tasks 9, 10, 11, 14 and 15 call these functions.

## What this task delivers: a library, not an HTTP surface

**Decided here: a pure Python module, `src/splitwise_lite/accounts.py`, with no HTTP
surface of any kind.** No framework, no route, no request object, no cookie, no
`Set-Cookie`, no middleware, no WSGI or ASGI callable.

The reasoning, so nobody reopens it mid-build:

* There is no web framework in this repo. Task 8 shipped `app/` as static files plus a
  standard library dev server, and its acceptance criteria forbid the shell from calling
  `fetch` at all. There is no back end for this task to attach to.
* Task 10 is the first task that needs one, and choosing it is a dependency decision that
  belongs to whoever makes it, with the user's approval. If task 7 picked a framework
  now, task 10 would inherit a choice made without the requirement that justifies it.
* The backlog says "enough that the app knows who is acting". A function that turns a
  token into a user id is exactly that much and no more.

So the deliverable is `sign_up`, `log_in`, `authenticate`, `log_out`,
`log_out_everywhere` and `change_password` as module-level functions taking the
`EventStore` as their first argument, in the same shape as `derive_balances` in
`balances.py`. Task 10 wraps them.

**Handover to task 10, recorded here so it is not lost.** Everything about carrying the
token over HTTP is task 10's, and all of it is required before this is safe on a network:
the cookie name, `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, a `Max-Age` derived from
the session's `expires_at`, TLS, CSRF protection on every state-changing request, and
rate limiting on the login endpoint. This task provides the values those decisions need
and makes none of them.

## The password hashing decision

**Decided here: `hashlib.scrypt`, with n = 65536, r = 8, p = 2, a 16-byte salt from
`secrets.token_bytes`, and a 32-byte derived key. No new dependency, and no approval
needed before starting.** The engineer implements this; they do not re-open it.

The reasoning:

* The choice is between the two password KDFs in the standard library, `hashlib.scrypt`
  and `hashlib.pbkdf2_hmac`, and scrypt is strictly the better of them. PBKDF2 is
  CPU-hard only, so a GPU or an ASIC cracks it at a rate a defender cannot match by
  raising the iteration count. scrypt is memory-hard: every guess needs the same 64 MiB
  of memory the honest login needed, which is the cost attackers cannot parallelise away
  cheaply. OWASP's password storage guidance ranks argon2id first, then scrypt, and puts
  PBKDF2 last, for use where a certification regime demands it. Nothing here demands it.
* n = 65536, r = 8, p = 2 is one of the configurations OWASP lists as equivalent work to
  its scrypt minimum. It costs 64 MiB and roughly a fifth to half a second per hash on a
  development laptop. The alternative with the same work, n = 131072, r = 8, p = 1, costs
  128 MiB per concurrent login for no extra resistance, and this app will run on a small
  host.
* bcrypt and argon2 are not in the standard library. Every module in this repo is
  standard library only, `pyproject.toml` still has `dependencies = []`, CLAUDE.md makes
  a dependency a deliberate declared act, and `.claude/hooks/guard-deps.hs.sh` blocks the
  ad hoc route. argon2id would be a genuine improvement over scrypt, but it is a marginal
  one against a stdlib option that is already in the recommended tier, and it is not
  worth a first runtime dependency in a project that has none.
* This is **not** the weaker stdlib option being picked quietly to dodge a dependency
  conversation. If the choice were between PBKDF2 and bcrypt, this file would say "stop
  and get the user's approval for a dependency" in bold. It is not: scrypt is a
  recommended algorithm at recommended parameters.

**The one condition that changes this answer.** `hashlib.scrypt` exists only when the
interpreter's OpenSSL provides scrypt. Before writing any code, run:

    uv run python -c "import hashlib; print(hasattr(hashlib, 'scrypt'))"

If that prints `False`, **stop and raise it with the user**. The fix is a dependency
(`argon2-cffi` or `bcrypt`), that is the user's decision to approve, and it must be
declared in `pyproject.toml` and installed with `uv sync`, never with `pip install`.
Falling back to `pbkdf2_hmac` in a `try/except ImportError` is forbidden: a silent
downgrade to a weaker KDF is exactly the failure this decision exists to prevent.

**The `maxmem` trap, which will otherwise cost an hour.** `hashlib.scrypt` passes
`maxmem` through to OpenSSL, and its default of 32 MiB is smaller than what these
parameters need, so a call without an explicit `maxmem` raises `ValueError`. The
requirement is `128 * r * (n + p + 2)` bytes, which is 64 MiB plus a few kilobytes here.
Compute `maxmem` from the parameters rather than hardcoding a number, so raising `n`
later cannot silently break, and so verifying a hash stored with larger parameters than
today's defaults still works.

**The stored form.** One text column holding a self-describing string, so the parameters
travel with the hash and can be raised later without invalidating what is already stored:

    scrypt$n=65536,r=8,p=2$<salt base64>$<derived key base64>

Four `$`-separated fields, the algorithm label first, the parameters in that exact key
order, both binary fields standard base64 with padding. Roughly 92 characters.

**Verification is `hmac.compare_digest` on the derived key bytes, never `==`.**
`secrets.compare_digest` is the same function under another name; either import is fine.

## The session decision

**A session is a row in a `sessions` table, keyed by the SHA-256 hash of a 256-bit
random token. The token itself is returned to the caller exactly once, at login, and is
never stored anywhere.**

* **Generation:** `secrets.token_urlsafe(32)`, which is 32 random bytes from the OS CSPRNG
  rendered as 43 URL-safe characters. Never `random`, which is a Mersenne Twister whose
  output is predictable from previous output. Never `uuid4()`, which is the right tool for
  an id and the wrong one for a secret. Never anything derived from the user id, the email
  or the clock.
* **Storage:** the row holds `sha256(token)` as 64 lowercase hex characters, not the token.
  A stolen database file, or a backup, then contains no credential anyone can present.
* **Why SHA-256 and not scrypt for the token:** the token is 256 bits of uniform
  randomness with nothing to guess, so there is no work factor to add, and running a
  memory-hard KDF on every authenticated request would be a denial of service the app
  inflicts on itself. The fast hash is correct here for exactly the reason the slow one is
  correct for passwords.
* **Lifetime:** an absolute expiry of 30 days, written into the row at creation as
  `expires_at`. No sliding renewal and no idle timeout: a sliding window means a database
  write on every request and an eviction policy to go with it, and this is a flat's ledger.
  A user signs in again once a month.
* **Logout** deletes the row. Sessions are operational state, not ledger history, so the
  append-only rule does not reach them and there is nothing to keep. A deleted session
  cannot be un-revoked, and an attacker who copied the row learns nothing from its absence.
* **A password change deletes every session that user holds**, including the one that made
  the change. There is no "keep me signed in on this device" screen to honour, and leaving
  a session alive after a credential change is the exact hole that makes changing a leaked
  password pointless.
* Several concurrent sessions per user are normal and supported: a phone and a laptop.
  There is no cap and no device list.
* The session records the **user**, not a member and not a group. A user can be a member of
  more than one group, so "which member is acting" is a lookup against a group, not a
  property of the session.

## The user-to-member link

The backlog says a user maps to one member within a group. Three tasks own three parts of
that, and this file draws the lines:

* **Task 6 owns the constraint,** and it is already built. `members.user_id` is nullable
  and references `users(id)`, and a partial unique index on `(group_id, user_id)` makes it
  impossible for two members of one group to point at the same user.
* **Task 9 owns writing the link.** It creates the group, seeds members from a manual
  list, and links member rows to user rows. **Task 7 never writes to `members`**, never
  creates a group, and never claims an unlinked member row.
* **Task 7 owns reading the link:** one store method, `get_member_for_user(group_id,
  user_id)`, which is what turns "who is acting" into a member id that events can name.

The awkward states this has to survive, all of them normal:

* A member row with `user_id` NULL is a flatmate who has no account yet. Task 9 puts those
  rows there before anybody signs up.
* **Signing up never links anything.** Matching a new account to a member row by email
  would let anyone who knows a flatmate's address take over their position in the ledger,
  and the spec cuts invites and onboarding, so there is no verified path that could make
  such a match trustworthy. A new account sees nothing until task 9 links it, which is
  also what makes an unverified signup harmless.
* A signed-in user with no member row in the group is a legitimate state, not a bug. The
  read raises `RecordNotFound` and the caller renders "you are not a member of this group".

## The schema, and how it squares with task 6 owning it

Task 6 already answered this. `SCHEMA_VERSION` in `store.py` carries the docstring "Task 7
raises it to 2 when it adds credentials and sessions", and task 6's out-of-scope list
assigns password hashing, sessions and `get_user_by_email` to task 7 as "schema version 2".

So: **the schema stays in `store.py`, in the one `_SCHEMA_SQL` string, and this task
extends it and bumps `SCHEMA_VERSION` to 2.** There is no second schema, no separate
database file and no DDL in `accounts.py`. Task 6's rule that callers "read and append
through this module and never write SQL of their own" applies to this task like every
other: `accounts.py` contains no SQL.

The split of responsibilities between the two modules is storage against policy.
`store.py` learns how to hold a password hash and a session row and nothing about what
either means. `accounts.py` owns hashing, token generation, expiry, normalisation and the
login flow, and owns no statement.

**The upgrade path is already built too.** Every statement in `_SCHEMA_SQL` is
`IF NOT EXISTS` and `open_store` re-runs the whole script whenever the stored
`user_version` is below `SCHEMA_VERSION`. Changing the trailing `PRAGMA user_version = 1`
to `= 2` therefore turns the existing script into a working migration: a database written
by task 6 gains the two new tables on open and keeps every row it had. No migration
framework, no versioned directory, no `ALTER TABLE`.

**`user_credentials`** (one row per user with a password set)

| column | type | notes |
|---|---|---|
| `user_id` | TEXT | primary key, references `users(id)` |
| `password_hash` | TEXT | not null, the encoded string above |
| `updated_at` | TEXT | not null, the same fixed-width UTC text as every other timestamp |

Separate from `users` rather than a column on it, for two reasons that both matter: task
6's `User` dataclass and its `repr` are re-exported from the package root and used all
over the later tasks, so a hash must not be able to ride along into a log line or a
template; and `SELECT * FROM users` stays safe for anything that runs it.

Constraints: `CHECK (length(password_hash) >= 60 AND instr(password_hash, '$') > 0)`. A
plaintext password cannot satisfy both, so the column is a tripwire as well as a store.
The check names no algorithm, so raising the cost or changing algorithm later needs no
schema change.

**`sessions`**

| column | type | notes |
|---|---|---|
| `token_hash` | TEXT | primary key, `CHECK (length(token_hash) = 64)` |
| `user_id` | TEXT | not null, references `users(id)` |
| `created_at` | TEXT | not null, fixed-width UTC |
| `expires_at` | TEXT | not null, fixed-width UTC, `CHECK (expires_at > created_at)` |

Plus `idx_sessions_user` on `sessions(user_id)` and `idx_sessions_expires_at` on
`sessions(expires_at)`.

Both tables are `STRICT`, both timestamp columns carry the same 32-character `+00:00`
`CHECK` as every other timestamp in the schema, and neither column has a `DEFAULT`. Task
6 has tests that enforce all three across every table in the database.

## What is deliberately not defended against in v1

Each of these is a recorded decision, not an oversight. If any of them is unacceptable,
that is a conversation to have before an engineer starts, not after.

* **Brute force and credential stuffing.** No lockout, no attempt counter, no backoff, no
  CAPTCHA. Two reasons: there is no HTTP layer to attach a rate limiter to, and an account
  lockout in a product with no password reset flow (the backlog cuts it) locks a flatmate
  out permanently. Rate limiting belongs at task 10's login endpoint, per the handover
  above. scrypt at these parameters is the only brake in v1, and it is a real one: a few
  hundred milliseconds a guess.
* **Signup email enumeration.** Signing up with an address that is already registered
  fails with a message that says so. Hiding it requires the "we have sent you an email"
  flow, and the backlog cuts email verification outright. The damage is bounded: knowing
  an address has an account here reveals only that someone in a flat share uses this app.
* **Unverified email addresses.** Anyone can sign up as anyone's address. This is safe only
  because signup grants nothing at all: no group, no member link, no data. See the link
  section above.
* **Login timing as a whole.** Failed logins are equalised with a dummy hash so an attacker
  cannot tell a registered address from an unregistered one, but no claim is made that the
  path is constant-time end to end. A database read for a row that exists differs from one
  that does not by microseconds under a KDF that takes hundreds of milliseconds.
* **Weak but long passwords.** A 12-character minimum, no breach-list check, no strength
  meter, no dictionary check. `password1234` is accepted.
* **The database file itself.** No encryption at rest, no key management. A stolen file
  exposes every hash to offline cracking at scrypt's cost, and every expense in the ledger
  in plaintext. That is already true after task 6.
* **Plaintext in memory.** Python strings are immutable and cannot be wiped, so a password
  may sit in memory until the garbage collector gets to it. Nothing in the standard library
  fixes this.
* **A caller passing a dishonest `now`.** Every function takes the current time as an
  argument, so a caller could revive an expired session by passing a past timestamp. This
  is an in-process Python API, the caller is application code, and the same is true of any
  clock the process can read.
* **Any audit trail of authentication.** No login history, no failed attempt log, no record
  of a password change beyond `updated_at`. The append-only rule in this repo is about
  money, not about auth.
* **Multi-factor, device management, "sign out everywhere" as a screen, and session
  fixation defence at the transport layer.** The function to revoke every session exists;
  no screen calls it, and nothing about cookies exists here to fixate.

## Acceptance criteria

**Module shape and the public surface**

- `src/splitwise_lite/accounts.py` exists and contains no SQL, no table name, no
  `sqlite3` import, and no `import http`, framework, cookie or route of any kind.
- Every function that touches storage takes the `EventStore` as its first positional
  argument. There is no module-level store, no singleton, no global connection and no
  ambient "current user".
- Public names are exactly: `AccountError`, `AuthenticationFailed`, `EmailAlreadyRegistered`,
  `InvalidEmail`, `InvalidPassword`, `PasswordHashInvalid`, `SessionInvalid`,
  `IssuedSession`, `ScryptParams`, `DEFAULT_SCRYPT_PARAMS`, `HASH_ALGORITHM`,
  `MAX_EMAIL_LENGTH`, `MAX_PASSWORD_LENGTH`, `MIN_PASSWORD_LENGTH`, `SALT_BYTES`,
  `SESSION_LIFETIME`, `TOKEN_BYTES`, `authenticate`, `change_password`, `hash_password`,
  `log_in`, `log_out`, `log_out_everywhere`, `normalise_email`, `sign_up` and
  `verify_password`. Everything else in the module is underscore-prefixed.
- `AccountError` subclasses `DomainError` from `money.py`, and every other error in the
  module subclasses `AccountError`, so task 10 still maps one exception family to one
  response.
- Every public name has a docstring stating the invariant it enforces or the decision it
  implements. Tasks 9, 10, 14 and 15 are written against those docstrings.
- The module reads no clock: its source contains none of `now(`, `utcnow(`, `time.time` or
  `today(`, mirroring the rule task 6 already tests on `store.py`. Every function needing
  the current time takes `now` as a required keyword-only argument.
- A `now` that is not a `datetime` raises `TypeError`; a naive `now` raises `InvalidRecord`
  or the module's own error, never a silent assumption of UTC. Whatever is passed is
  converted with `astimezone(timezone.utc)` before it is stored or compared.
- The module imports `secrets` and never `random`. The source contains no `import random`,
  no `random.` call and no use of `uuid` for a salt or a token. User ids come from
  `new_id()` in `events.py`, which is the repo's id factory and not a secret.
- `accounts.py` imports from `store.py`, `events.py` and `money.py`; none of those three
  learns that `accounts.py` exists.

**Password hashing**

- `hash_password(password, *, params=DEFAULT_SCRYPT_PARAMS)` returns a string of the form
  `scrypt$n=<int>,r=<int>,p=<int>$<salt b64>$<key b64>`, with exactly four `$`-separated
  fields and the parameter keys in the order `n`, `r`, `p`.
- `DEFAULT_SCRYPT_PARAMS` is `ScryptParams(n=65536, r=8, p=2)` with a 32-byte derived key
  and a 16-byte salt. A test asserts those exact numbers, so raising the cost is a visible,
  deliberate edit rather than a drift.
- The salt is 16 fresh bytes from `secrets.token_bytes` per call. Hashing the same password
  twice returns two different strings, and both verify.
- `maxmem` is passed to `hashlib.scrypt` on every call and is computed as
  `128 * r * (n + p + 2)`, never hardcoded. A test asserts hashing with the defaults
  succeeds, which fails outright if `maxmem` was left at its default.
- `verify_password(password, encoded)` parses the parameters out of `encoded` and computes
  `maxmem` from those, not from `DEFAULT_SCRYPT_PARAMS`. A hash written with n = 131072
  still verifies after the defaults are lowered, and a hash written with the old defaults
  still verifies after they are raised. Both directions are tested.
- Verification compares with `hmac.compare_digest` on the two `bytes` objects. The source
  contains no `==` or `!=` between a derived key and a stored one.
- `verify_password` returns `True` for the right password, `False` for a wrong one, `False`
  for the right password against a different account's hash, and `False` for a password
  that differs only by a trailing space.
- An `encoded` value that is not four fields, names an algorithm other than `scrypt`, has
  parameters out of order or non-integer, or whose base64 does not decode with
  `validate=True`, raises `PasswordHashInvalid`. It never returns `False`: a corrupt stored
  hash is a bug report, and reporting it as a wrong password would hide database damage
  behind a support ticket about a forgotten password.
- Parameters parsed out of a stored hash are bounded before they reach `hashlib.scrypt`:
  `n` must be a power of two in `[2, 2**20]`, `r` in `[1, 32]`, `p` in `[1, 16]` and the
  key length in `[16, 64]`. A hand-edited row claiming `n=2**40` raises
  `PasswordHashInvalid` rather than allocating a terabyte. `ScryptParams` enforces the same
  bounds in `__post_init__`, so a bad set cannot be constructed either.
- `ScryptParams` is a frozen slotted dataclass and compares by value, matching every other
  value type in the repo.
- Passing a non-`str` password or a non-`str` encoded hash raises `TypeError`, following
  the convention tasks 2, 3, 4 and 6 set: rejected input is a domain error, a wrong Python
  type is a programming error.
- The module never writes, returns or logs a plaintext password. No exception message
  contains the password, no dataclass holds one as a field, and a test asserts that the
  message of every error raised by a failed signup, login and password change is free of
  the password it was given.

**Password policy and normalisation**

- A password is normalised with `unicodedata.normalize("NFKC", password)` before it is
  hashed and before it is verified, so a password typed in NFD on one keyboard verifies
  against a hash made from its NFC form. A test covers a round trip through both forms.
- Length is measured after normalisation. `MIN_PASSWORD_LENGTH` is 12 and
  `MAX_PASSWORD_LENGTH` is 1024. A shorter or longer password raises `InvalidPassword` at
  signup and at password change.
- Passwords are never stripped or trimmed. `" secret phrase"` and `"secret phrase"` are
  different passwords, and a test proves the leading space is preserved.
- A password with no non-whitespace character is rejected even when it is long enough. A
  held-down space bar is not a password anybody can retype.
- There are no composition rules: no required digit, no required symbol, no required case
  mix, no forbidden character. Every Unicode character is accepted, emoji included, and a
  test covers a passphrase with spaces and a password with astral-plane characters.
- **`log_in` applies no password policy at all.** It checks the type, rejects an empty
  string and rejects anything over `MAX_PASSWORD_LENGTH`, then asks the KDF. A password
  that was legal under an earlier, shorter minimum must keep working after the minimum is
  raised, and a test creates a hash from a 4-character password directly with
  `hash_password` and asserts it still logs in.
- An empty password or one over the cap fails login as a plain `AuthenticationFailed`
  without running the KDF at all. Feeding unbounded input to a memory-hard function is the
  denial of service the cap exists to prevent, and no real password is 1025 characters.

**Email normalisation and signup**

- `normalise_email(value)` strips surrounding whitespace and lowercases. It is the only
  place that canonicalises an address, and `sign_up` and `log_in` both call it.
- Lowercasing the local part is technically not what RFC 5321 says, and it is what every
  provider does. One canonical spelling is what makes `users.email UNIQUE` mean "one
  account per address". This is stated in the function's docstring as a decision.
- An address is rejected with `InvalidEmail` unless it has exactly one `@`, a non-empty
  local part, a domain containing at least one dot with no empty label, no whitespace
  anywhere inside it, only printable ASCII, and a total length of at most
  `MAX_EMAIL_LENGTH` (254). Internationalised addresses are a documented v1 limitation in
  the same way zero-decimal currencies are in `money.py`.
- `""`, `"   "`, `"\t"`, `"sam"`, `"sam@"`, `"@example.com"`, `"sam@@example.com"`,
  `"sam@example"`, `"sam @example.com"`, `"sam@exa mple.com"` and a 300-character address
  are each rejected. A non-`str` raises `TypeError`.
- No DNS lookup, no MX check and no deliverability check happens anywhere.
- `sign_up(store, *, email, display_name, password, now, params=DEFAULT_SCRYPT_PARAMS)`
  validates the email and the password, mints a user id with `new_id()`, and returns the
  stored `User`.
- The user row and the credential row are written in **one** store call and therefore one
  transaction. A failure part way through leaves neither, and a test asserts that a signup
  that fails on the credential write leaves no user row and no taken email address.
- Signing up twice with the same address raises `EmailAlreadyRegistered`, and the second
  attempt leaves the first user's row and password hash byte-identical.
- `"Sam@Example.COM "` and `"sam@example.com"` collide, because normalisation runs before
  the uniqueness check. A test covers it.
- `sign_up` does not create a session. Logging in is a separate call, so signup owns no
  session policy. Task 10 calls both if it wants to sign a new user straight in.
- `sign_up` writes nothing to `groups` or `members`, and a test asserts both tables are
  still empty after a signup.
- A blank or over-long display name is rejected by `User` itself, as `InvalidRecord`.
  `accounts.py` does not re-wrap task 6's validation errors.

**Login**

- `log_in(store, *, email, password, now)` returns an `IssuedSession` on success.
- Every failure raises `AuthenticationFailed` with one message that names neither which
  field was wrong nor whether the address exists. The unknown-address case, the
  wrong-password case, the no-credential-row case and the malformed-address case all raise
  the same type with the same message. A test asserts the messages are identical strings.
- A failed login for an unknown address runs the KDF against a dummy hash before failing,
  so the response time does not reveal whether the account exists. The dummy hash is
  derived once per process from a module constant using the current default parameters and
  cached, so it can never go stale against a parameter change.
- This is tested without wall-clock timing: a test counts calls to the module's internal
  derive helper and asserts an unknown address and a known address with a wrong password
  produce the same number of calls. No test asserts an elapsed duration, because a timing
  assertion on a shared machine is a flaky test.
- A user created by `add_user` with no credential row cannot log in, fails with the same
  generic error, and still costs a dummy hash. Task 6's `add_user` remains on the surface,
  so this state is reachable.
- A successful login creates exactly one session row. Logging in twice gives two distinct
  tokens and two live sessions, and both authenticate.
- `IssuedSession` holds `token: str` and `session: Session`. Its `repr` does not contain
  the token: a test asserts the token string does not appear in `repr(issued)`. Credentials
  end up in logs through reprs more often than through any deliberate print.
- The token is 43 characters from `secrets.token_urlsafe(32)`. A test asserts the length
  and that 100 tokens are all distinct.
- The stored row holds `sha256(token)` as 64 lowercase hex characters. A test asserts the
  raw token string appears nowhere in the database file, by scanning the bytes of a
  file-backed store after a login.
- `expires_at` equals `created_at + SESSION_LIFETIME`, and `SESSION_LIFETIME` is
  `timedelta(days=30)`.
- `created_at` is the `now` that was passed, converted to UTC, and the store rejects it if
  it is not the fixed-width shape every other timestamp uses.
- If the token hash collides with an existing row, `DuplicateRecord` comes out and no row
  is overwritten. There is no retry loop and no upsert: at 256 bits a collision means the
  random source is broken, and minting a second token would hide that.

**Sessions and logout**

- `authenticate(store, token, *, now)` returns the `Session` for a live token.
- It raises `SessionInvalid` for an unknown token, for an expired one, for a malformed one
  and for one longer than 4096 characters. One error type covers all four, because "you
  were signed out, sign in again" is the same screen either way, and the error carries no
  detail about which case it was.
- A token that is not a `str` raises `TypeError`, following the repo's convention that a
  wrong Python type is a programming error rather than rejected input.
- Expiry is exclusive: a session is valid while `now < expires_at`, so a session whose
  `expires_at` is exactly `now` is invalid. Tests cover one microsecond either side of the
  boundary.
- `authenticate` never writes. It is called on every request, and a read that writes is a
  lock contention bug waiting for the first two people to open the app at once.
- An expired row is left in place by `authenticate` rather than cleaned up, and is never
  honoured on any later call that passes an honest `now`. A caller who passes a past
  timestamp can revive it, which is the recorded gap above.
- `log_out(store, token)` deletes the session and is idempotent: calling it twice, or with
  a token that never existed, or with an expired one, raises nothing and leaves the rest of
  the table untouched.
- `log_out` performs no ownership check. Possession of the token is the authority, which is
  what a bearer token means.
- After `log_out`, `authenticate` on the same token raises `SessionInvalid`, and the user's
  other sessions still authenticate.
- `log_out_everywhere(store, user_id)` deletes every session that user holds and returns
  the count. It raises `RecordNotFound` for a user id that does not exist, and returns 0
  for a user with no sessions.
- One user's sessions are never touched by another user's logout. A test with two users
  and two sessions each proves it.
- `EventStore.delete_expired_sessions(now)` removes every row whose `expires_at` is at or
  before `now` and returns the count. Nothing calls it on a schedule in v1; it exists so
  task 10 can, and an unpurged row is never honoured in the meantime.

**Password change**

- `change_password(store, *, user_id, current_password, new_password, now,
  params=DEFAULT_SCRYPT_PARAMS)` verifies the current password, applies the full password
  policy to the new one, and replaces the stored hash.
- A wrong current password raises `AuthenticationFailed` and changes nothing: the stored
  hash is byte-identical afterwards and every session is still live.
- A new password that fails the policy raises `InvalidPassword` and changes nothing.
- A new password equal to the current one is rejected with `InvalidPassword`. Rewriting the
  same secret buys nothing and costs the user every session they hold.
- The new hash uses a fresh salt, so the stored string differs even when the parameters are
  the same.
- **Every session for that user is deleted in the same transaction as the hash update.**
  Setting the hash and revoking the sessions cannot half-happen: a test that forces a
  failure between them asserts the old hash and the old sessions are both still there.
- The session that made the change is deleted too. A test authenticates with a token, calls
  `change_password`, and asserts the token no longer authenticates.
- Another user's sessions and hash are untouched.
- Logging in with the new password succeeds and with the old one fails.

**The user-to-member link**

- `EventStore.get_member_for_user(group_id, user_id)` returns the `Member` in that group
  linked to that user, and raises `RecordNotFound` naming both ids when there is none.
- It never returns a member from another group. A test links one user in two groups and
  asserts each call returns that group's member.
- It never returns a member whose `user_id` is NULL, whatever else matches.
- An unknown group id raises `RecordNotFound`, matching every other group-scoped read in
  the store, so a typo is not read as "not a member".
- `accounts.py` contains no function that writes to `members` and no function that links a
  user to a member. A test asserts the module source names neither `add_member` nor
  `members`.
- A signup followed by a login leaves `members` untouched, and `get_member_for_user` for
  that brand new user raises `RecordNotFound`. This is the normal state until task 9 runs.

**The schema at version 2**

- `SCHEMA_VERSION` is 2, the trailing statement in `_SCHEMA_SQL` is
  `PRAGMA user_version = 2`, and a freshly created store reports 2.
- The database created by task 6's code at `user_version = 1` opens under this code without
  error, reports `user_version = 2` afterwards, holds the two new tables, and every user,
  group, member and event row in it reads back exactly as before. A test builds a v1
  database by executing task 6's schema text directly, then opens it with `open_store`, and
  asserts all of that. This is the criterion that fails if the upgrade was written as a
  fresh-database-only path.
- Opening a database at `user_version = 3` still raises `UnsupportedSchemaVersion`.
- `user_credentials` and `sessions` are both `STRICT`, carry no `DEFAULT` on any column,
  and use the same 32-character `+00:00` timestamp `CHECK` as every other timestamp in the
  schema. Task 6's existing whole-database tests cover all three once the tables exist.
- `sessions.token_hash` is the primary key with `CHECK (length(token_hash) = 64)`, and
  `sessions.expires_at` carries `CHECK (expires_at > created_at)`. A raw insert violating
  either is rejected.
- `user_credentials.password_hash` carries
  `CHECK (length(password_hash) >= 60 AND instr(password_hash, '$') > 0)`. A test issues a
  raw insert of a plausible plaintext password and asserts it is rejected, so the column is
  a tripwire against the worst possible bug in this task.
- Both new tables reference `users(id)`, and with `PRAGMA foreign_keys = ON` a credential
  or a session for a user id that does not exist is refused by the database, not only by
  Python. A test proves it with raw SQL.
- The indexes `idx_sessions_user` and `idx_sessions_expires_at` exist.
- The four event tables gain no column, no trigger change and no index change. A raw
  `UPDATE` and a raw `DELETE` against each of them still raises, and task 6's tests for
  that keep passing unmodified.
- No new table stores a balance, a net position, a member's role, a permission or a flag.

**The store's new methods**

- Writes added to `EventStore`: `add_user_with_credential`, `set_password_hash`,
  `add_session`, `delete_session`, `delete_sessions_for_user`, `delete_expired_sessions`.
- Reads added: `get_user_by_email`, `get_password_hash`, `get_session`,
  `get_member_for_user`.
- `Session` is a frozen slotted dataclass in `store.py` holding `token_hash: str`,
  `user_id: UserId`, `created_at: datetime` and `expires_at: datetime`, validated in
  `__post_init__` like `User`, `Group` and `Member`. It never holds the raw token.
- `get_password_hash` returns a `str`. Task 6's rule that reads return domain objects is
  about not leaking rows, dicts and `sqlite3.Row` objects; a single scalar value is not a
  row, and wrapping one hash in a dataclass would buy nothing.
- Every new read raises `RecordNotFound` naming the id it was given rather than returning
  `None`, matching the store's existing convention.
- `set_password_hash(user_id, password_hash, updated_at)` inserts on first use and updates
  thereafter, and deletes every session for that user, all inside one `BEGIN IMMEDIATE`
  transaction. Its docstring says so in its first line, because a method that silently
  deletes rows in another table is otherwise a trap.
- The insert-or-update is written as a check followed by an `INSERT` or an `UPDATE` inside
  the transaction, not as `INSERT OR REPLACE` or `ON CONFLICT DO UPDATE`. The lock is
  already held, so the check is sound, and task 6's ban on those statement forms stays
  literally true in the source.
- Every new statement is a module-level constant with bound parameters passed through
  `_params`, exactly like the existing ones. Nothing is interpolated, and only `str`, `int`
  and `None` are ever bound.
- Every new method routes through `_reading` or `_writing`, so no `sqlite3` exception
  escapes and every failure arrives as a `StoreError` subclass with `__cause__` attached.
- Every new method raises `StoreClosed` on a closed store, and every new public method has
  a docstring.
- `store.py` still reads no clock. `delete_expired_sessions` takes `now` as an argument. Be
  careful not to write `now()` inside a docstring: task 6 has a test that greps the whole
  source for that substring.

**Task 6 tests that must change, and how**

These are the only pre-existing tests this task is allowed to touch. Every change is
mechanical, and the reasoning for each belongs in the test's own name or comment.

- `test_a_fresh_store_is_at_schema_version_1` becomes `..._version_2` and asserts
  `SCHEMA_VERSION == 2`.
- `test_opening_one_fresh_file_from_two_stores_leaves_one_valid_schema` expects 9 tables
  rather than 7.
- `test_membership_is_a_flat_list_with_no_dates` expects `user_credentials` and `sessions`
  in its exact table set. Its assertions about the `members` columns do not change: the
  membership list stays flat, with no `joined_at`, `left_at` or `is_active`.
- `EXPECTED_COLUMNS` gains both new tables with their exact columns in order, which
  automatically extends the parametrized column test to them.
- `WRITES` and `READS` gain the ten new methods, which extends
  `test_the_public_surface_is_exactly_the_named_methods`,
  `test_every_public_method_has_a_docstring` and
  `test_every_public_method_refuses_a_closed_store`. That last one currently passes `"g1"`
  to every read and one record to every write, so it needs per-method arguments; keep it
  exhaustive rather than narrowing it to the old methods.
- `test_every_public_class_has_a_docstring` gains `Session`.
- `test_the_module_issues_no_statement_that_could_rewrite_history` currently forbids
  `\bDELETE\s+FROM\b` anywhere in `store.py`. Narrow that one pattern to the four
  append-only tables. Sessions are not history, and deleting a logged-out session is the
  correct behaviour, not a rewrite. `ON CONFLICT`, `INSERT OR REPLACE`, `REPLACE INTO` and
  `UPDATE` of an event table stay banned unchanged.
- Add a test alongside it asserting the narrowed rule still bites: no statement in
  `store.py` deletes from, replaces or upserts into any of the four event tables, and the
  only table named by a `DELETE FROM` in the whole module is `sessions`.
- No other test in `tests/test_store.py` changes, and no test in `tests/test_events.py`,
  `tests/test_money.py`, `tests/test_split.py`, `tests/test_balances.py`,
  `tests/test_smoke.py`, `tests/test_web_shell.py` or `tests/test_dev_server.py` changes at
  all.

**Suite**

- New tests live in `tests/test_accounts.py` and cover every criterion above that is about
  `accounts.py`. Criteria about the schema and the store's new methods are tested in
  `tests/test_store.py`, next to the task 6 tests they extend.
- Tests that do not exercise the KDF itself pass deliberately cheap parameters, for example
  `ScryptParams(n=16, r=1, p=1)`, through one fixture. Running the whole suite at production
  parameters would add minutes for no coverage.
- A small, named set of tests does run at `DEFAULT_SCRYPT_PARAMS`: one signup and login
  round trip, one wrong-password rejection, one assertion that the defaults are the exact
  documented numbers, and one that the lazily built dummy hash carries those same
  parameters. Those four are what stop the cheap fixture from hiding a broken default.
- No test is skipped and none is xfailed, per `.claude/rules/testing.md`. If
  `hashlib.scrypt` turns out to be missing, stop and raise it; do not skip the tests that
  need it.
- Assertions are exact: exact error types, exact string equality on the two generic login
  messages, exact integer counts of rows and of KDF calls. No approximate comparison and no
  assertion on elapsed time.
- `uv run python -m pytest` passes. Plain `uv run pytest` fails on this machine with an
  access-denied spawn error.
- Every test already on `master` keeps passing, apart from the ones named in the section
  above, and each of those changes is a widening rather than a weakening.

## Out of scope

- Password reset, "forgot my password", recovery codes and security questions. The backlog
  cuts the reset flow, and every version of it needs the email channel the spec cuts too. A
  user who forgets their password has no route back in v1, and `change_password` for a user
  who still knows their password is the whole of the recovery story.
- Email verification, confirmation links, and any outbound email at all. No SMTP, no
  templates, no queue.
- Invites, invite links, join requests and onboarding of any kind. The spec cuts them by
  name.
- Creating groups, creating members, and linking a user to a member. Task 9 owns all three,
  and this task must not write to `members` even once "while we are in here".
- Authorisation. This task answers "who is this", never "may they do this". The rule that
  only a settlement's receiver may confirm it belongs to task 15, which can load both
  records through `get_member_for_user`.
- Roles, permissions, admins and group owners. There is no privileged user in a flat.
- Any HTTP surface: cookies, headers, CSRF tokens, login forms, redirects, a sign-in
  screen, or serving anything. Task 10 owns all of it, per the handover above.
- Rate limiting, lockout, backoff and CAPTCHA. Recorded above as a gap and assigned to task
  10's endpoint.
- OAuth, single sign-on, magic links, passkeys, WebAuthn and multi-factor authentication.
- Remember-me, sliding session renewal, refresh tokens, JWTs and any client-side session
  state. A random opaque token in a server-side table is the entire design.
- A device list, a "sessions you have open" screen, or per-session naming.
- Changing an email address, changing a display name, deleting an account, and any
  right-to-erasure story. Deleting a person from an append-only ledger is a real question
  and it is not this task's.
- A user profile, an avatar, a timezone or a locale preference.
- Any change to how balances, splits, money or events work. `accounts.py` never touches a
  cent.
- A migration framework, a versioned migration directory or an `ALTER TABLE`. Bumping
  `PRAGMA user_version` and re-running the idempotent script is the mechanism, and it is
  task 6's mechanism, not a new one.
- Any new dependency, in either language. See the constraints.
- Async, threading and a connection pool. Task 6's store is one connection per store and
  says so; nothing here changes that.

## Constraints

- Files to create: `src/splitwise_lite/accounts.py` and `tests/test_accounts.py`.
- Files to modify: `src/splitwise_lite/store.py` (the two new tables in `_SCHEMA_SQL`,
  `SCHEMA_VERSION`, the `Session` record, the ten new methods, `__all__`),
  `tests/test_store.py` (only the changes listed above) and
  `src/splitwise_lite/__init__.py` (re-export the new public names and add `accounts` to
  the module list in its docstring; `__version__` must keep its current value because
  `tests/test_smoke.py` asserts it).
- **`src/splitwise_lite/events.py`, `src/splitwise_lite/money.py`,
  `src/splitwise_lite/split.py` and `src/splitwise_lite/balances.py` must not be modified.**
  Nothing in this task needs a new field, a relaxed validation or an exported private
  helper from any of them. If a criterion here seems to need one, stop and raise it. The
  same goes for `plans/backlog.md`, `plans/spec.md`, this file, anything under `.claude/`,
  and anything under `app/` or `scripts/`.
- `CLAUDE.md` and `README.md` need no change: this task adds no command and no directory.
- **No new dependency.** `hashlib`, `hmac`, `secrets`, `base64`, `unicodedata`,
  `dataclasses`, `datetime`, `typing` and, in the tests, `pytest` cover everything
  described here. Do not add `passlib`, `bcrypt`, `argon2-cffi`, `pyjwt`, `itsdangerous`,
  `email-validator`, `pydantic` or a web framework. If `hashlib.scrypt` is unavailable, or
  implementation genuinely needs a package for another reason, **stop and get the user's
  approval first**, then declare it in `pyproject.toml` and run `uv sync`, never
  `pip install` or `uv pip install`.
- Python 3.12 target. Frozen slotted dataclasses for `ScryptParams`, `IssuedSession` and
  `Session`, validating in `__post_init__`, matching the shape tasks 2 and 6 set.
- `accounts.py` writes no SQL and names no table. All storage goes through `EventStore`,
  which is task 6's rule for every consumer.
- Dependency direction stays one way: `accounts.py` imports from `store.py`, `events.py`
  and `money.py`, and none of them imports it.
- All DDL stays in the single `_SCHEMA_SQL` string in `store.py`. No `.sql` file, no second
  schema string, no DDL in a function.
- The only randomness is `secrets`. The only password hash is `hashlib.scrypt` at
  `DEFAULT_SCRYPT_PARAMS`. There is no second code path, no legacy format to read and no
  algorithm negotiation beyond the label in the stored string.
- No plaintext password and no raw session token is ever written to the database, a log, an
  exception message, a `repr`, a test fixture file or a comment.
- Timestamps follow task 6 exactly: timezone-aware, normalised to UTC, stored as
  `isoformat(timespec="microseconds")`, 32 characters ending `+00:00`. The store's existing
  `CHECK` rejects anything else, and the two new tables carry the same one.
- Every public class and function gets a docstring stating the invariant it enforces or the
  decision it implements, because tasks 9, 10, 14 and 15 are written against them. The
  module docstring states the hashing choice with its parameters, the session model, the
  30-day lifetime, and the "signup links nothing" rule.
- Tests run with `uv run python -m pytest`. Plain `uv run pytest` fails on this machine
  with an access-denied spawn error. No test is skipped or xfailed, and no test asserts on
  elapsed time.
