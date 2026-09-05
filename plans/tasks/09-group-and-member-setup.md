# Task 9: Group and member setup

**Depends on:** 6 (complete, landed on `master`), 7 (complete, landed on `master`)
**Consumed by:** 10 (expense entry), 11 (expense feed) and 12 (balances screen) directly,
and through those three every remaining task in the backlog.

Sharpened from `plans/backlog.md` task 9. The backlog entry stays as written; this file is
the implementable version.

The backlog says the graph narrows hard here, "because every screen needs real members to
render". Nine of the ten remaining tasks sit behind this one, so every decision that a
screen task would otherwise have to invent is made here, on the record.

## Goal

One real group exists in a real store, with its currency fixed at creation and a real
person behind every member row, seeded from a manual list an operator wrote. Re-running
setup with the same list changes nothing. A flatmate who has signed up can be linked to
their member record afterwards, and a member who has not signed up yet is a normal,
fully functional member of the ledger. Tasks 10, 11 and 12 get "the" group and its roster
through two named functions and never hardcode an id.

## What this task delivers: a library, plus one operator command

**Decided here: a pure Python module, `src/splitwise_lite/groups.py`, in the same shape as
`accounts.py` and `balances.py`, plus one standard library CLI at
`scripts/setup_group.py`.** No HTTP surface of any kind, no framework, no route, no
request object.

The split matters, because the mechanism and the shape are two different questions:

* **The shape is the library.** Tasks 10, 11 and 12 call functions. That is the part this
  file specifies down to the argument.
* **The mechanism is a file plus a command.** A human has to be able to say "the flat is
  Sam, Ali, Jo and Kit" once, and to run it. That is the CLI's job, and no screen ever
  calls it.

Everything in `groups.py` takes the `EventStore` as its first positional argument, exactly
like `derive_balances` in `balances.py` and `sign_up` in `accounts.py`. There is no
module-level store, no singleton and no ambient "current group".

## The manual member list: a TOML file, one value type, one function

**Decided here: the roster is a TOML document with exactly three keys, parsed into a
frozen `GroupDefinition` value, and applied by one function.** The engineer implements
this; they do not re-open it.

    # group.toml
    name = "Flat 3"
    currency = "AUD"
    members = ["Sam", "Ali", "Jo", "Kit"]

The reasoning, so nobody reopens it mid-build:

* **Why a file rather than only a function taking a list of names.** The list is reference
  data that gets re-applied, reviewed and edited by a person who is not editing Python at
  the time. A file makes the roster diffable, makes "run setup twice" a well defined thing
  (apply the same file twice), and keeps the list out of shell history where a
  `--member Sam --member Ali` command line would put it.
* **Why TOML and not JSON.** `tomllib` is in the standard library at Python 3.12, so this
  adds nothing to `pyproject.toml`. TOML takes comments, which a roster wants ("Kit moved
  in April"), and it is forgiving about trailing commas, which hand-edited JSON is not.
  The repo already carries a TOML file that people edit by hand.
* **Why a value type in between.** `GroupDefinition` is what `apply_group_definition`
  takes, so tests build one in three lines with no temporary file, and a future caller
  that gets a roster from somewhere else needs no new entry point. Parsing and applying
  are separate functions, and only the CLI calls both.
* **Why not a seed script with the names in it.** A script with names in its source is a
  file edit and a commit every time someone moves in, and it cannot be run twice safely
  without the reconcile logic that this task is mostly about anyway.
* **Why nothing is read at startup.** No module reads a file at import time, there is no
  default path, no environment variable and no search of the working directory. This
  mirrors task 6's rule that "the store never chooses a path". A path is always passed.

**The file carries display names and nothing else.** No email address, no id, no password,
no join date, no role. Emails are excluded deliberately: see the link section below.

## Idempotency: what a second run does

**Decided here: applying a definition is idempotent for the names already present, and
additive for names that are new. Removing a name is refused.**

| The second run finds | What happens |
|---|---|
| The same group, the same names | Nothing is written. `SetupResult` reports nothing created and nothing added. |
| A name in the file that is not in the store | That member is added. Existing rows keep their ids and timestamps. |
| A name in the store that is not in the file | `GroupMismatch`, naming the missing names. Nothing is written, including the additions in the same run. |
| A different currency | `GroupMismatch`, naming both codes. Nothing is written. |
| A different group name | `GroupMismatch`, naming both names. Nothing is written. |
| More than one group, and no explicit `--group-id` | `AmbiguousGroup`, naming every group id. Nothing is written. |

The reasoning:

* **Additive, because arrival is not departure.** A flatmate moving in adds a row to a flat
  list, which costs nothing and breaks nothing. A flatmate moving out is member departure:
  open question 1 in the spec, cut from v1, and the decision this task is forbidden from
  pre-empting. Deleting a member row is also impossible in practice once they appear in an
  expense, because the event tables hold foreign keys to it.
* **A refused run is refused whole.** If one file both adds Kit and drops Jo, the run
  writes nothing at all, rather than adding Kit and then complaining. A half-applied
  refusal is the state an operator cannot reason about.
* **Matching is by display name**, normalised with `unicodedata.normalize("NFC", name)`
  then `casefold()`, because the name is the only natural key the roster has. Member ids
  are random UUIDs by design (`new_id()` in `events.py`: "Ids are random, never derived
  from a name"), so they cannot be the key, and the schema has nowhere to put a separate
  slug. To make that key unambiguous, `GroupDefinition` rejects two names that normalise
  equal. "Two flatmates called Sam" is a real situation and the answer is that the file
  says "Sam K" and "Sam T"; the error message says so.

## Identifying "the" group without hardcoding an id

**Decided here: one function, `resolve_sole_group(store)`, which returns the group when the
store holds exactly one and raises otherwise.**

Task 6's acceptance criteria forbid a `get_the_group()` on the store, and that stands: no
store method, no hardcoded id, no default group id, no singleton table, no column that
assumes one group. `resolve_sole_group` is a different thing from the one task 6 refused,
in the way that matters:

* It does not assume a group exists. Zero groups raises `NoGroupConfigured`, with a message
  naming the setup command. More than one raises `AmbiguousGroup`, naming every id.
* It returns a `Group`, and every read a caller makes afterwards is still scoped by
  `group.id`, exactly as it would be with two groups.
* It lives in `groups.py`, not in `store.py`, so the store keeps no knowledge that v1
  exposes one group.

Exposing multiple groups later is then deleting the uses of one function and passing an id
that came from somewhere else. It is not unpicking a constant that leaked into twelve
files.

## The user-to-member link, and the gap before it exists

Members exist before those people have accounts. That is why `members.user_id` is
nullable, and it is the normal state of a fresh flat: four member rows, zero users.

**How a user gets linked: a deliberate operator action.**
`link_user_to_member(store, *, group_id, member_id, user_id)` sets a NULL `user_id` to a
real one. It is called by `scripts/setup_group.py link`, and by nothing else in v1.

**Nothing links automatically, and email matching stays forbidden.** Task 7 decided this
and it is restated here because this is the task that would be tempted: "Matching a new
account to a member row by email would let anyone who knows a flatmate's address take over
their position in the ledger." Putting the addresses in the roster file does not fix it,
because signup email is unverified and the spec cuts email verification, so whoever signs
up with `sam@example.com` first would become Sam. The roster file therefore carries no
email addresses at all, and no code path in this task compares a user to a member by email,
by display name or by any other similarity.

**Before anyone has signed up**, `store.get_member_for_user` finds nothing for every user,
because it matches on `user_id` and never returns a NULL row. That is a legitimate state,
not a bug, and it is the state of the app on the day it is installed.

**What a screen does with a member who has no user.** Stated here so tasks 10 to 12 do not
each invent an answer:

* A member with `user_id` NULL is a full member of the ledger. They can be a payer, a
  participant in an allocation and a party to a settlement, and every screen renders them
  exactly like any other member. Nothing filters them out, greys them out, marks them
  "pending" or offers to invite them. Their debts are real money, and hiding them would
  make the balances screen wrong.
* A signed-in user with no member row cannot author anything, because every event field
  that names a person is a `MemberId` and there is none for them. Tasks 10, 14 and 15 call
  `acting_member` first and render the `MemberNotLinked` case rather than crashing.
* Whether an unlinked user may *read* the ledger is not decided here. It is a request layer
  question, and the request layer does not exist yet. Recorded so someone decides it rather
  than inheriting it.

## Flat membership is locked

**Members are a flat list. No `joined_at`, no `left_at`, no `is_active`, no dated
intervals, no membership history table and no event scoped to who was present at the time.
This is a constraint, not a preference.**

It is assumption 2 in the backlog and open question 1 in the spec, both of which say the
same thing: retrofitting dated membership onto a live ledger is expensive, and the answer
is not decided yet. Task 6 already froze it in the schema and in `Member`'s docstring.

Concretely, this task must not add any of them "while we are in here", must not add a
`left_at` column with a comment saying it is unused, and must not encode departure as a
member row with a NULL user or a name prefix. If a criterion here seems to need dated
membership, stop and raise it: it changes every read in tasks 4, 5, 11 and 12.

## The schema needs nothing new

`groups` and `members` already hold everything this task writes. Linking is
`members.user_id` moving from NULL to a value, which is an `UPDATE` of a reference table,
not of an event table.

So: **`_SCHEMA_SQL` is not edited, `SCHEMA_VERSION` stays 2, and there is no version 3.**
That is how this squares with task 6 owning the schema and task 7 having already taken it
to version 2. The one store change is a new method, `set_member_user`, issuing one
`UPDATE members ... WHERE id = ? AND user_id IS NULL`.

That `UPDATE` is allowed, and it is worth being precise about why:

* Task 6 banned `UPDATE` and `DELETE` against the four event tables and enforced it with
  triggers and with a test that greps every SQL literal in `store.py`. `members` is
  reference data and carries no such trigger.
* Task 7 already narrowed that test to the four event tables by name, for `set_password_hash`
  and the session deletes. An `UPDATE members` does not match any of the forbidden patterns,
  so `test_the_module_issues_no_statement_that_could_rewrite_history` passes unchanged.
* `ON CONFLICT`, `INSERT OR REPLACE` and `REPLACE INTO` stay banned everywhere, so the link
  is a plain `UPDATE` guarded by `WHERE user_id IS NULL`, never an upsert.

## The bridge to the screens does not exist, and this task does not build it

Stated plainly, because it is the largest open risk around this task and it must not be
absorbed here quietly.

There is no HTTP layer anywhere in this repo. Task 8 shipped `app/` as static files whose
acceptance criteria forbid `fetch`, `XMLHttpRequest` and any `/api` path outright. Task 7
declined to add one and handed cookies, CSRF and rate limiting to "task 10" by name. Task 9
is a library and a CLI. Tasks 10, 11 and 12 are screens that need real data, and no backlog
task creates the thing in between.

**Task 9 owns none of it.** No web framework is chosen here, no server is written, no
endpoint is defined, no cookie is set, and nothing under `app/` is edited.

**The assumption every screen-facing criterion in this file makes, made explicit:** some
later task provides a process that imports `splitwise_lite` and calls these functions. This
task adds no such process, and no criterion below depends on one existing. Everything here
is verified by calling Python functions and by running `scripts/setup_group.py`.

Whoever picks up that gap gets these two inherited notes for the exception mapping:

* A losing racer in a concurrent signup surfaces `DuplicateRecord` from the store rather
  than `EmailAlreadyRegistered` from `accounts.py`. No duplicate account results either
  way, but the mapper needs to know that both types reach it.
* The same shape applies here. Two operators linking at once are serialised by the store's
  `BEGIN IMMEDIATE`, so the loser normally gets `MemberAlreadyLinked` or `UserAlreadyLinked`
  from `groups.py`. A caller that writes the row another way can still surface
  `DuplicateRecord`. Map both.

## What is deliberately not defended against in v1

Each of these is a recorded decision, not an oversight.

* **Two applies racing on an empty store.** The check for "zero groups" and the create are
  two store transactions, so two operators starting at the same second can create two
  groups. It is an operator command run once by one person, the loud `AmbiguousGroup` on
  every later call is the detection, and the fix is passing `--group-id`. Do not add a lock
  file, a singleton table or an advisory lock to prevent it.
* **A stray group is permanent.** There is no delete anywhere in the store, so a group
  created by mistake stays. Removing one is a hand-written SQL statement against a database
  nobody has used yet, and that is the recorded cost of the point above.
* **Renaming a group or a member.** Neither is supported. A misspelled name in the roster
  file becomes a misspelled member row, and correcting the file afterwards raises
  `GroupMismatch` rather than renaming anything. Adding a rename is a later task's decision,
  and it needs an answer about what happens to a name already rendered in a feed.
* **Unlinking, and account handover.** Nothing clears `members.user_id`. If the wrong person
  is linked, v1 has no route back through the API.
* **Authorisation of who may run setup.** There is none, because there is no privileged user
  in a flat (task 7) and no request layer to check one in. Possession of the database file
  is the authority, which is what a CLI on a server means.
* **A dishonest `now`.** Every function that needs the current time takes it as an argument,
  matching tasks 6 and 7, so a caller can pass anything. The same is true of any clock the
  process can read.

## Acceptance criteria

**Module shape and the public surface**

- `src/splitwise_lite/groups.py` exists and contains no SQL, no table name, no `sqlite3`
  import, no `argparse`, no `print`, and no `import http`, framework, cookie or route of
  any kind.
- Every function that touches storage takes the `EventStore` as its first positional
  argument. There is no module-level store, no singleton, no global connection, no ambient
  "current group" and no cached group id.
- Public names are exactly: `GroupSetupError`, `InvalidGroupDefinition`, `NoGroupConfigured`,
  `AmbiguousGroup`, `GroupMismatch`, `MemberAlreadyLinked`, `UserAlreadyLinked`,
  `MemberNotLinked`, `GroupDefinition`, `SetupResult`, `MAX_MEMBERS`,
  `parse_group_definition`, `load_group_definition`, `apply_group_definition`,
  `resolve_sole_group`, `link_user_to_member` and `acting_member`. Everything else in the
  module is underscore-prefixed.
- `GroupSetupError` subclasses `DomainError` from `money.py`, and every other error in the
  module subclasses `GroupSetupError`, so one exception family still maps to one response.
- Every public name has a docstring stating the invariant it enforces or the decision it
  implements. Tasks 10, 11, 12, 14 and 15 are written against those docstrings.
- The module reads no clock: its source contains none of `now(`, `utcnow(`, `time.time` or
  `today(`, mirroring the rule task 6 tests on `store.py` and task 7 tests on `accounts.py`.
  `apply_group_definition` takes `now` as a required keyword-only argument.
- A `now` that is not a `datetime` raises `TypeError`; a naive `now` raises `InvalidRecord`,
  matching `accounts.py`. Whatever is passed is converted with `astimezone(timezone.utc)`.
- `groups.py` imports from `store.py`, `events.py` and `money.py`. It does not import
  `accounts.py`, and none of the four learns that `groups.py` exists. A test asserts the
  import direction.
- `src/splitwise_lite/__init__.py` re-exports every public name above and names `groups` in
  its module list. `__version__` keeps its current value, because `tests/test_smoke.py`
  asserts it.

**The definition value**

- `GroupDefinition` is a frozen slotted dataclass with fields `name: str`,
  `currency: Currency` and `members: tuple[str, ...]`, validated in `__post_init__`, and it
  compares by value.
- `name` is 1 to 100 characters once stripped, matching `Group`. Blank or longer raises
  `InvalidGroupDefinition`.
- Each member name is stripped and must be 1 to 100 characters, matching `Member`. `" Sam "`
  and `"Sam"` are the same entry and the stored name is `"Sam"`.
- A definition with no members raises `InvalidGroupDefinition`. An empty roster is a file
  someone forgot to finish, and it would create a group nobody can use.
- A definition with more than `MAX_MEMBERS` members raises. `MAX_MEMBERS` is 50: the spec
  says small groups, the balances screen renders every member, and a pasted address book is
  a mistake rather than a flat.
- Two member names that are equal after `unicodedata.normalize("NFC", name)` then
  `casefold()` raise `InvalidGroupDefinition` naming the collision, and the message says to
  distinguish them, for example "Sam K" and "Sam T". `"Sam"` against `"sam"` collides, and
  a name typed in NFD collides with the same name typed in NFC. Both are tested.
- `GroupDefinition` holds no id, no email address, no password, no date, no role and no
  flag. A test asserts its field names exactly.
- A wrong Python type raises `TypeError`; a rejected value raises `InvalidGroupDefinition`.
  This follows the convention tasks 2, 3, 4, 6 and 7 set.

**Reading a definition file**

- `parse_group_definition(text)` takes a `str` of TOML. `load_group_definition(path)` takes
  a `str` or `Path`, reads the file and returns the same value. Both return a
  `GroupDefinition`.
- The document has exactly the keys `name`, `currency` and `members`. A missing key and an
  unknown key both raise `InvalidGroupDefinition` naming the key, so `currancy = "AUD"` is
  an error rather than a silent default.
- `currency` must be three uppercase letters. `"aud"` raises `InvalidGroupDefinition` with a
  message naming `"AUD"`, because `money.Currency` rejects lowercase rather than coercing it
  and the operator needs to be told what to type.
- `members` must be an array of strings. A bare string, a number, a nested table or an array
  containing a non-string raises `InvalidGroupDefinition` naming the key.
- Malformed TOML raises `InvalidGroupDefinition` naming the path and carrying
  `tomllib.TOMLDecodeError` as `__cause__`. No `tomllib` exception escapes.
- A path that does not exist, or is a directory, raises `InvalidGroupDefinition` naming the
  path. No bare `OSError` escapes.
- A leading UTF-8 byte order mark is tolerated rather than failing as a parse error. This
  repo is developed on Windows, where a plain editor writes one, and the resulting
  `tomllib` message names neither the cause nor the fix.
- Nothing is read at import time. Neither function has a default path, reads an environment
  variable or searches the working directory.
- `group.example.toml` in the repo root parses through `load_group_definition` and yields a
  definition with at least two members. A test asserts it, so the documented example cannot
  rot.

**Applying a definition to an empty store**

- `apply_group_definition(store, definition, *, now, group_id=None)` returns a
  `SetupResult`.
- On a store with no groups it creates exactly one group, with the definition's name and
  currency and `created_at` equal to `now`, and one member per name.
- The group id and every member id come from `new_id()`. No id is derived from a display
  name, from the file, from a position or from a hash of any of them, per `new_id()`'s
  docstring in `events.py`. A test asserts every id parses as a UUID and that no id contains
  any member's name.
- Every member is created with `user_id=None`. Apply never links a user.
- Apply writes nothing to `users`, `user_credentials`, `sessions`, `expense_events`,
  `expense_allocations`, `settlement_events` or `settlement_decision_events`. A test asserts
  the row count of all seven is zero afterwards.
- `store.list_members(group.id)` returns the members in the order the definition lists them.
  Members are written with `created_at` equal to `now` plus one microsecond per position, so
  `(created_at, id)` ordering equals file order; without it, ordering would fall back to
  random ids and the roster would render in an order the operator did not choose. A test
  applies a four-name roster and asserts the exact tuple of display names in order.
- No ordering is achieved by adding a column, a `position`, a `sort_order` or anything else
  to the schema.
- `SetupResult` is a frozen slotted dataclass with fields `group: Group`,
  `group_created: bool`, `members_added: tuple[Member, ...]` and
  `members_existing: tuple[Member, ...]`. `members_added` is in file order.
- After a first apply, `SetupResult.group_created` is `True`, `members_added` holds every
  member in order, and `members_existing` is empty.
- Every refusal listed in the next section is decided before the first write. A refused
  apply leaves the database exactly as it was, and a test asserts the group row, every
  member row and every id and timestamp are unchanged.

**Applying twice: idempotency**

- Applying the identical definition a second time writes nothing and returns
  `group_created=False`, `members_added=()` and `members_existing` equal to the full roster.
  The group row and every member row, ids and `created_at` included, are byte for byte
  unchanged. This is the criterion that fails if apply is a plain insert.
- Applying a definition with one extra name adds exactly that one member, returns it as the
  only entry in `members_added`, leaves every existing id and timestamp untouched, and
  places the new member last in `list_members` order.
- Applying a definition that omits a name the store holds raises `GroupMismatch` naming the
  omitted names and writes nothing, including any additions in the same run. Removing a
  member is member departure, which is cut from v1.
- Applying a definition whose currency differs from the stored group's raises `GroupMismatch`
  naming both codes, writes nothing, and the stored currency reads back unchanged. The
  database trigger is the backstop; this check means no statement is ever issued.
- Applying a definition whose group name differs raises `GroupMismatch` naming both names
  and writes nothing. Renaming is out of scope, and quietly reconciling against a
  differently named group is how an operator seeds the wrong flat.
- A name that differs only by case or only by Unicode normalisation from a stored member is
  the same member: nothing is added, nothing is renamed, and the store keeps its original
  spelling. A test covers `"sam"` against a stored `"Sam"`.
- Reordering the names in the file adds nothing, raises nothing and does not change stored
  order. Stored order is creation order.
- If the store holds two members of that group whose names match after normalisation, apply
  raises `GroupMismatch` naming the name rather than guessing which row the file means. The
  store permits that state (task 6 allows two members called Sam) and this task will not
  resolve it silently.
- Apply is not one transaction across rows: the group and each member are separate store
  calls. A failure part way leaves a partial roster and re-running completes it, which is
  what idempotency buys. No criterion asserts atomicity across rows, and no store method is
  added to provide it.

**Identifying the group**

- `resolve_sole_group(store)` returns the group when the store holds exactly one.
- It raises `NoGroupConfigured` when the store holds none, with a message naming the setup
  command, and `AmbiguousGroup` when it holds more than one, with a message naming every
  group id.
- It writes nothing and creates nothing. A test asserts that calling it on an empty store
  leaves `groups` empty.
- `store.py` gains no singleton read, no `get_the_group`, no default group id and no
  hardcoded id, and the four event tables keep their `group_id` columns and their
  group-scoped reads. Task 6's criterion still holds verbatim.
- No file in `src/`, `scripts/` or `tests/` contains a literal group id. The only routes to
  one are `resolve_sole_group` and an id the caller was handed.
- `apply_group_definition` with `group_id=None` creates when the store holds no group,
  reconciles when it holds exactly one, and raises `AmbiguousGroup` when it holds more than
  one, naming every id.
- `apply_group_definition` with an explicit `group_id` reconciles that group and raises
  `RecordNotFound` if no group has that id. It never creates a group under a caller-supplied
  id, because a group id written into a config file or a command line is exactly the
  hardcoded id this rule exists to prevent.
- A test creates two groups, applies a definition to each by explicit id, and asserts each
  reconcile touched only its own group's members.

**The user-to-member link**

- `link_user_to_member(store, *, group_id, member_id, user_id)` sets a NULL `user_id` on
  that member and returns the updated `Member`.
- Linking the member to the user it already points at is a no-op: it writes nothing and
  returns the member unchanged.
- `MemberAlreadyLinked` if the member already points at a different user. Nothing is
  written and the existing link is unchanged. Taking over a member row is account handover,
  which is out of scope.
- `UserAlreadyLinked` if another member of that group already points at that user. The
  partial unique index on `(group_id, user_id)` is the backstop.
- `RecordNotFound` if the member id or the user id names nothing, naming the id.
- `GroupMismatch` if the member exists but belongs to another group, naming both group ids.
  Passing the group is what makes a cross-group link impossible rather than unlikely.
- The same user may act for one member in each of several groups. A test with two groups
  links the same user in both and asserts each group resolves to its own member.
- Linking changes `user_id` and nothing else. `display_name`, `id` and `created_at` are
  unchanged afterwards, and there is no `linked_at` anywhere.
- Nothing unlinks. `groups.py` contains no function that clears `members.user_id`, and
  `store.py` gains no method that can.
- Signing up links nothing. A test signs up a user whose email local part and display name
  both equal a member's display name, and asserts `members` is unchanged and
  `acting_member` still raises `MemberNotLinked`.
- No code path in `groups.py` compares a `User` to a `Member` by email, by display name or
  by any other similarity, and `GroupDefinition` cannot carry an email address.

**Resolving who is acting**

- `acting_member(store, *, group_id, user_id)` returns the `Member` in that group linked to
  that user.
- It raises `MemberNotLinked` when no member of that group points at that user, and lets
  `RecordNotFound` through for a group id that does not exist. The two cases are
  distinguishable by exception type, because they are two different screens: "nobody has
  linked you yet" against a bug. A test asserts both types.
- It never returns a member whose `user_id` is NULL, whatever else matches.
- It writes nothing.
- A test walks the whole gap: apply a roster, assert every member has `user_id` NULL, sign a
  user up, assert `acting_member` raises `MemberNotLinked`, link them, assert
  `acting_member` returns the right member, and assert every other member is still unlinked.

**The store's new method**

- `EventStore.set_member_user(member_id, user_id)` is added, and it is the only method in
  the store that writes to `members` after creation.
- It issues one `UPDATE members SET user_id = ? WHERE id = ? AND user_id IS NULL` inside
  `_writing`, from a module-level statement constant, with parameters bound through
  `_params`. Nothing is interpolated.
- `RecordNotFound` for an unknown member id or an unknown user id, naming the id.
- `DuplicateRecord` if that member already points at any user, naming both users, and
  `DuplicateRecord` if another member of that group already points at that user, naming both
  ids. Nothing is overwritten in either case, matching the store's existing rule that
  nothing upserts.
- It has no upsert form: `_SCHEMA_SQL` is untouched and `store.py` still contains no
  `ON CONFLICT`, `INSERT OR REPLACE` or `REPLACE INTO`. The existing parametrized test that
  greps every SQL literal passes unchanged, because the new `UPDATE` names `members`, which
  is not one of the four append-only tables.
- It routes through `_writing`, so no `sqlite3` exception escapes, raises `StoreClosed` on a
  closed store, and has a docstring.
- `store.py` still reads no clock and the new method takes no timestamp.
- `SCHEMA_VERSION` is still 2, `_SCHEMA_SQL` is not edited, a fresh store still reports
  `PRAGMA user_version = 2`, and the table set and every column list are unchanged.
  `EXPECTED_COLUMNS` and `test_membership_is_a_flat_list_with_no_dates` in
  `tests/test_store.py` do not change.
- `tests/test_store.py` changes only by adding `set_member_user` to `WRITES`, adding its
  arguments to `test_every_public_method_refuses_a_closed_store`, and adding tests for the
  behaviour above. No other pre-existing test in that file changes, and no test in
  `tests/test_events.py`, `test_money.py`, `test_split.py`, `test_balances.py`,
  `test_simplify.py`, `test_accounts.py`, `test_smoke.py`, `test_web_shell.py` or
  `test_dev_server.py` changes at all.

**The operator command**

- `scripts/setup_group.py` exists, uses the standard library plus `splitwise_lite`, and has
  three subcommands: `apply`, `link` and `show`.
- `uv run python scripts/setup_group.py apply --store PATH --definition PATH [--group-id ID]`
  applies the definition and prints what it did: whether the group was created, the group
  id, and each member added. When nothing changed it says so and exits 0.
- `uv run python scripts/setup_group.py link --store PATH --email ADDRESS (--member-id ID |
  --member-name NAME) [--group-id ID]` resolves the user through
  `store.get_user_by_email`, resolves the member, links them and prints the pair.
- `--member-id` and `--member-name` are mutually exclusive and exactly one is required.
  `--member-name` must match exactly one member of the group after NFC normalisation and
  casefolding; zero matches and more than one match are both errors, and the message for
  more than one names every candidate id.
- `uv run python scripts/setup_group.py show --store PATH [--group-id ID]` prints the group
  name, currency and creation time, then one line per member in `list_members` order giving
  the display name, the member id and whether an account is linked. It writes nothing.
- `show` prints no email address and no user id, so a screenshot of the roster is not an
  address list. No subcommand prints a password, a password hash or a session token.
- No subcommand has a default `--store` path, reads an environment variable or creates a
  directory. The path goes to `open_store` unchanged.
- Every `DomainError` is caught at the top level: the message goes to stderr and the process
  exits 1, with no traceback. Success exits 0, including a no-op apply. argparse handles
  usage errors with its own exit status 2.
- The script binds no socket, starts no server, serves nothing and imports nothing from
  `app/`.
- It defines `main(argv: Sequence[str] | None = None) -> int` and does nothing at import
  time beyond definitions, so a test can import it and call `main` directly, mirroring how
  `tests/test_dev_server.py` loads `scripts/serve.py`.
- The store is opened and closed around each invocation, through the context manager, so a
  failed run leaves no open handle on the database file. This matters on Windows, where an
  open handle blocks the next run's rename or delete.

**Docs**

- `group.example.toml` exists in the repo root, carries obviously fictional names, uses
  `AUD`, and includes a comment saying the real file is not committed.
- `.gitignore` gains `group.toml` and `*.sqlite3*`, so a real roster and a real ledger, WAL
  sidecars included, are never committed.
- README gains a "Set up the group" section with the exact `apply` command, the example
  file, and one sentence saying re-running it is safe.
- CLAUDE.md's Commands section gains the setup command, and its "Where things live" list
  gains `group.example.toml`.
- No document claims a screen shows real data, and no document says setup sends an invite,
  an email or a notification.

**Suite**

- New tests live in `tests/test_groups.py` and `tests/test_setup_group_cli.py`, and cover
  every criterion above that is about `groups.py` and the script. Criteria about
  `set_member_user` are tested in `tests/test_store.py`, next to the task 6 and 7 tests they
  extend.
- The reconcile and link tests run against both an in-memory store and a file-backed store
  under `tmp_path`, from one parametrized fixture and one test body, matching task 6.
- Tests that need a signed-up user call `accounts.sign_up` with cheap scrypt parameters,
  through the same style of fixture task 7 uses. No test in this task runs the KDF at
  production parameters.
- Assertions are exact: exact exception types, exact tuples of display names in order, exact
  row counts, exact `SetupResult` field values, exact process exit codes. No approximate
  comparison, no assertion on elapsed time, and no substring guess at prose beyond the
  identifiers the criteria above name.
- Tests locate repo files from `Path(__file__).resolve().parents[1]`, never from the current
  working directory.
- No test is skipped or xfailed, per `.claude/rules/testing.md`.
- `uv run python -m pytest` passes. Plain `uv run pytest` fails on this machine with an
  access-denied spawn error. Every test already on `master` keeps passing, apart from the
  widened store surface tests named above, and each of those changes is a widening rather
  than a weakening.

## Out of scope

- **Any HTTP or API layer.** No web framework, no server, no endpoint, no route, no JSON
  response, no cookie, no CSRF token, no rate limiting. The gap is real and it is flagged
  above; this task does not fill it, and an engineer who finds themselves choosing a
  framework has left the task.
- **Any change under `app/`.** No JavaScript, no `fetch`, no screen, no member list in the
  shell. Task 8's criteria forbidding all of that still hold.
- Rendering anything. Tasks 10, 11 and 12 own their screens; this task decides only what is
  true about the data they render.
- Invite links, email invites, join requests, onboarding flows and anything that sends a
  message to a person. The spec cuts them by name.
- Creating user accounts, hashing passwords, issuing sessions and reading a token. Task 7
  owns all of it, and `groups.py` does not import `accounts.py`.
- Automatically linking a signup to a member row by email or by name. Forbidden, with
  reasoning, above.
- Unlinking, transferring a member row to another user, deleting a member, deleting a user
  and deleting a group. Deleting a person from an append-only ledger is a real question and
  it is not this task's.
- Renaming a group or a member, and any member editing surface.
- Member departure in any form: `joined_at`, `left_at`, `is_active`, membership intervals, a
  history table, an archived flag, or scoping historical expenses to who was present. Locked
  above.
- Creating a second group. `apply_group_definition` reconciles the one group a v1 store
  holds; whoever exposes multiple groups adds an explicit creation function then, rather
  than a flag on this one.
- A group switcher, cross-group totals, and any multi-group navigation. The spec cuts them.
- Roles, permissions, admins, owners and anyone privileged. There is no privileged user in a
  flat.
- Per-member settings: an avatar, a colour, a nickname, a phone number, a payment handle, a
  timezone or a preferred currency.
- Any change to the schema, `SCHEMA_VERSION`, `_SCHEMA_SQL` or the four event tables, and
  any migration. Version 2 is what this task runs on.
- Any change to how money, splits, balances, simplification or events work. `groups.py`
  never touches a cent.
- Seeding expenses, settlements or demo data of any kind. Task 18 builds the end-to-end
  fixture, and fake amounts in a money app are indistinguishable from wrong real ones.
- A `conftest.py` fixture that seeds a group for the whole suite. Each test builds what it
  needs, so no test can depend on another test's roster.
- Any new dependency, in either language.

## Constraints

- Files to create: `src/splitwise_lite/groups.py`, `scripts/setup_group.py`,
  `group.example.toml`, `tests/test_groups.py` and `tests/test_setup_group_cli.py`. Nothing
  else.
- Files to modify: `src/splitwise_lite/store.py` (one statement constant, the
  `set_member_user` method, and its docstring), `tests/test_store.py` (only the changes
  listed in the criteria), `src/splitwise_lite/__init__.py` (re-export the new public names
  and add `groups` to the module list in its docstring; `__version__` must keep its current
  value because `tests/test_smoke.py` asserts it), `.gitignore`, `README.md` and `CLAUDE.md`.
- **`src/splitwise_lite/events.py`, `money.py`, `split.py`, `balances.py`, `simplify.py` and
  `accounts.py` must not be modified.** Nothing here needs a new field, a relaxed validation
  or an exported private helper from any of them. If a criterion seems to need one, stop and
  raise it. The same goes for everything under `app/`, `scripts/serve.py`,
  `scripts/make_icons.py`, `plans/backlog.md`, `plans/spec.md`, this file, anything else
  under `plans/`, and anything under `.claude/`.
- **No new dependency.** `tomllib`, `unicodedata`, `dataclasses`, `datetime`, `pathlib`,
  `argparse`, `sys`, `typing` and, in the tests, `pytest` cover everything described here.
  Do not add `tomli-w`, `pydantic`, `click`, `typer`, `pyyaml` or a web framework. Per
  CLAUDE.md, a dependency is declared in `pyproject.toml` and installed with `uv sync`, never
  with `pip install` or `uv pip install`, and `.claude/hooks/guard-deps.hs.sh` blocks the ad
  hoc route. If implementation genuinely needs one, stop and get the user's approval first.
- `pyproject.toml` and `uv.lock` are not touched.
- Python 3.12 target. Frozen slotted dataclasses for `GroupDefinition` and `SetupResult`,
  validating in `__post_init__`, matching the shape tasks 2, 6 and 7 set.
- `groups.py` writes no SQL and names no table. All storage goes through `EventStore`, which
  is task 6's rule for every consumer.
- Dependency direction stays one way: `groups.py` imports from `store.py`, `events.py` and
  `money.py`, and none of them imports it. It does not import `accounts.py` either, so the
  two sibling modules can be read independently.
- All DDL stays in the single `_SCHEMA_SQL` string in `store.py`, and this task adds none.
  No `.sql` file, no second schema string, no `ALTER TABLE`.
- Ids come from `new_id()` in `events.py`. No id is derived from a name, an email, a
  position or a hash, and no id is written by hand into any committed file.
- Membership stays flat, per the locked constraint above.
- The roster file carries display names only: no email address, no id, no date, no role and
  no flag.
- Timestamps follow tasks 6 and 7 exactly: timezone-aware, normalised to UTC, and stored in
  the fixed-width form the schema's `CHECK` enforces.
- Every public class and function gets a docstring stating the invariant it enforces or the
  decision it implements, because tasks 10, 11, 12, 14 and 15 are written against them. The
  module docstring states the TOML shape, the idempotency rule, the sole-group rule and the
  "nothing links automatically" rule.
- Tests run with `uv run python -m pytest`. Plain `uv run pytest` fails on this machine with
  an access-denied spawn error. No test is skipped or xfailed, and assertions are exact.
