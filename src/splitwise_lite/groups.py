"""Group and member setup: one real group, one member row per real person.

The screens in tasks 10, 11 and 12 need a roster before they can render anything, and
this module is the whole of how one comes to exist. It is a library: every function
takes the ``EventStore`` as its first positional argument, there is no module-level
store, no singleton and no ambient "current group". The operator command that wraps
these functions lives in ``scripts/setup_group.py`` and no screen calls it.

**The roster is a TOML document with exactly three keys.** ``tomllib`` is in the
standard library, so this costs no dependency, and a file takes comments, diffs
cleanly and keeps the flat's names out of shell history::

    # group.toml
    name = "Flat 3"
    currency = "AUD"
    members = ["Sam", "Ali", "Jo", "Kit"]

It carries display names and nothing else: no address, no id, no date, no role and no
flag. ``parse_group_definition`` and ``load_group_definition`` turn it into a frozen
``GroupDefinition``; ``apply_group_definition`` is what writes. Nothing is read at
import time, there is no default path, nothing is read from the process env, and no
directory is searched. A path is always passed.

**Applying is idempotent for the names already there, and additive for new ones.** A
second run over an unchanged file writes nothing at all. A name the file gained is
added. A name the file lost is refused with ``GroupMismatch``, and so is a changed
currency or a changed group name, because a flatmate leaving is member departure,
which v1 cuts, and renaming is out of scope. A refused run is refused whole: every
check happens before the first write, so one file that both adds Max and drops Jo
writes nothing rather than half of it. Names match on
``unicodedata.normalize("NFC", name)`` then ``casefold()``, because the display name is
the only natural key a roster has; ids are random and carry no name.

**Finding the group without hardcoding an id** is ``resolve_sole_group``, which returns
the group when the store holds exactly one group and raises otherwise. It is not the
``get_the_group`` the store refused: it assumes nothing exists, it returns a ``Group``
whose id still scopes every later read, and it lives here rather than in the store, so
the store keeps no knowledge that v1 exposes one group.

**Signing up links nothing automatically.** A ``user_id`` reaches a member row only
through ``link_user_to_member``, called by the operator command. No code path here
compares a user to a member by address, by display name or by any other similarity:
sign-up details are unverified, so whoever claimed a flatmate's address first would
otherwise take over their position in the ledger. A member whose ``user_id`` is NULL is
a full member of the ledger, renders like any other and is nobody's pending invite;
a signed-in user with no member row calls ``acting_member`` and gets
``MemberNotLinked``.

Membership is flat. There is no ``joined_at``, ``left_at``, ``is_active``, membership
interval or history table here, and this module adds no column: the roster's order
comes from writing each new member one microsecond after the last.

Dependency direction: this module imports from ``store``, ``events`` and ``money``, and
none of the three knows it exists. It writes no SQL and names no table; all storage
goes through ``EventStore``.
"""

from __future__ import annotations

import tomllib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, NoReturn

from .events import GroupId, MemberId, new_id
from .money import Currency, DomainError
from .store import (
    EventStore,
    Group,
    InvalidRecord,
    Member,
    RecordNotFound,
    UserId,
)

__all__ = [
    "MAX_MEMBERS",
    "AmbiguousGroup",
    "GroupDefinition",
    "GroupMismatch",
    "GroupSetupError",
    "InvalidGroupDefinition",
    "MemberAlreadyLinked",
    "MemberNotLinked",
    "NoGroupConfigured",
    "SetupResult",
    "UserAlreadyLinked",
    "acting_member",
    "apply_group_definition",
    "link_user_to_member",
    "load_group_definition",
    "parse_group_definition",
    "resolve_sole_group",
]

MAX_MEMBERS: Final[int] = 50
"""Most names one definition may carry.

The spec says small groups, the balances screen renders every member on one page, and
a roster of a few hundred is a pasted address book rather than a flat. Fifty leaves
room for a share house nobody would call small and still refuses the mistake loudly.
"""

_MAX_NAME_LENGTH: Final[int] = 100
"""Cap on a group name and a member name, matching ``Group`` and ``Member``."""

_DEFINITION_KEYS: Final[tuple[str, ...]] = ("name", "currency", "members")
"""Every key a definition document may carry, and every key it must.

Exactly these, so ``currancy = "AUD"`` is an error rather than a silent default.
"""

_SETUP_COMMAND: Final[str] = (
    "uv run python scripts/setup_group.py apply --store PATH --definition group.toml"
)
"""What to tell an operator who has no group yet. Named in ``NoGroupConfigured``."""

_ONE_MICROSECOND: Final[timedelta] = timedelta(microseconds=1)
"""The gap between two members written in one run.

``list_members`` orders by ``(created_at, id)`` and ids are random, so members written
at the same instant would come back in an order the operator did not choose. One
microsecond per position makes stored order equal file order without a ``position``
column, a ``sort_order`` or any other change to the schema.
"""

_BOM: Final[str] = "﻿"
"""The character a plain Windows editor puts at the front of a UTF-8 file."""


# --- Errors ------------------------------------------------------------------


class GroupSetupError(DomainError):
    """Base for everything this module refuses.

    One family under ``DomainError``, so whoever builds the layer between these
    functions and a screen maps one exception type to one response rather than seven.
    """


class InvalidGroupDefinition(GroupSetupError):
    """The roster itself is unusable: bad TOML, a bad key, or a bad name.

    Raised before any store is touched. A wrong Python type raises ``TypeError``
    instead, following the convention tasks 2, 3, 4, 6 and 7 set: a rejected value is
    a domain error, a wrong type is a programming mistake.
    """


class NoGroupConfigured(GroupSetupError):
    """The store holds no group at all, so there is nothing to resolve.

    The message names the setup command, because the state is what a freshly installed
    app looks like and the fix is running it, not filing a bug.
    """


class AmbiguousGroup(GroupSetupError):
    """The store holds more than one group and no id said which one.

    Raised rather than picking the first or the newest. The message names every group
    id, so the operator can pass one back as ``--group-id``.
    """


class GroupMismatch(GroupSetupError):
    """The stored group and the thing asked of it disagree, and nothing is written.

    A definition that drops a name, changes the currency or changes the group name,
    and a link that crosses a group boundary. Removing a member is member departure
    and renaming is out of scope, so reconciling either quietly is how an operator
    seeds the wrong flat.
    """


class MemberAlreadyLinked(GroupSetupError):
    """That member already points at a different user, and is left as it is.

    Taking over a member row is account handover, which v1 does not do. Linking a
    member to the user it already points at is a no-op instead, not this.
    """


class UserAlreadyLinked(GroupSetupError):
    """Another member of that group already points at that user.

    One person is at most one member of one group. The partial unique index on
    ``(group_id, user_id)`` is the backstop; this is the readable refusal.
    """


class MemberNotLinked(GroupSetupError):
    """Nobody has linked this signed-in user to a member of this group.

    A legitimate state, not a bug: it is what every brand new sign-up looks like until
    an operator links it, and it is what the app looks like on the day it is installed.
    Screens render this case rather than crashing, because a user with no member row
    cannot author an event: every event field that names a person is a ``MemberId``.
    """


# --- Helpers -----------------------------------------------------------------


def _key(name: str) -> str:
    """The matching key for a display name: NFC, then casefolded.

    The display name is the only natural key a roster has, because ids are random by
    design and the schema has nowhere to put a slug. Normalising first means a name
    typed in NFD on a Mac matches the same name typed in NFC on Windows.
    """
    return unicodedata.normalize("NFC", name).casefold()


def _require_display_name(value: object, field: str) -> str:
    """Return ``value`` stripped, or raise. 1 to 100 characters, matching the store."""
    if not isinstance(value, str):
        raise TypeError(
            f"{field} must be a str, got {type(value).__name__}: {value!r}"
        )
    stripped = value.strip()
    if not stripped:
        raise InvalidGroupDefinition(f"{field} must not be blank, got {value!r}")
    if len(stripped) > _MAX_NAME_LENGTH:
        raise InvalidGroupDefinition(
            f"{field} must be at most {_MAX_NAME_LENGTH} characters, got "
            f"{len(stripped)}: {stripped!r}"
        )
    return stripped


def _require_utc(value: object, field: str) -> datetime:
    """Return ``value`` converted to UTC, or raise, matching tasks 6 and 7.

    A wrong type is a ``TypeError`` and a naive datetime is an ``InvalidRecord``: a
    datetime with no zone is rejected rather than assumed to be local or UTC, because
    guessing silently reorders a roster for anyone in another timezone.
    """
    if not isinstance(value, datetime):
        raise TypeError(
            f"{field} must be a datetime, got {type(value).__name__}: {value!r}"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidRecord(f"{field} must be timezone-aware, got naive {value!r}")
    return value.astimezone(timezone.utc)


def _spell(values: object) -> str:
    """Render a sequence for an error message, quoted and comma separated."""
    return ", ".join(repr(value) for value in values)  # type: ignore[union-attr]


# --- The definition value ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class GroupDefinition:
    """A roster an operator wrote: a group name, one currency and display names.

    Invariants:

    * ``name`` is 1 to 100 characters once stripped, matching ``Group``.
    * ``currency`` is a ``Currency``, not a code string, so it compares directly
      against a stored group's currency with neither side reaching for a code.
    * ``members`` is a non-empty tuple of at most ``MAX_MEMBERS`` display names, each
      1 to 100 characters once stripped, in the order the file listed them.
    * No two names are equal after ``unicodedata.normalize("NFC", name)`` then
      ``casefold()``. Matching is by display name, so a roster that cannot tell two
      entries apart is refused at the file rather than guessed at in the store.

    It holds no id, no address, no password, no date, no role and no flag. Addresses
    are excluded deliberately: putting them here would invite matching a sign-up to a
    member row by address, and a sign-up address is unverified.

    Value type, so a test builds one in three lines with no temporary file and a caller
    whose roster came from somewhere else needs no new entry point.
    """

    name: str
    currency: Currency
    members: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "name", _require_display_name(self.name, "GroupDefinition name")
        )
        if not isinstance(self.currency, Currency):
            raise TypeError(
                f"GroupDefinition currency must be a Currency, got "
                f"{type(self.currency).__name__}: {self.currency!r}"
            )
        if not isinstance(self.members, tuple):
            raise TypeError(
                f"GroupDefinition members must be a tuple, got "
                f"{type(self.members).__name__}: {self.members!r}"
            )
        cleaned = tuple(
            _require_display_name(name, f"GroupDefinition member {position}")
            for position, name in enumerate(self.members)
        )
        if not cleaned:
            raise InvalidGroupDefinition(
                "a group definition must list at least one name in 'members'; an "
                "empty roster would create a group nobody can use"
            )
        if len(cleaned) > MAX_MEMBERS:
            raise InvalidGroupDefinition(
                f"a group definition lists at most {MAX_MEMBERS} names in 'members', "
                f"got {len(cleaned)}"
            )
        seen: dict[str, str] = {}
        for name in cleaned:
            key = _key(name)
            if key in seen:
                raise InvalidGroupDefinition(
                    f"the names {seen[key]!r} and {name!r} are the same name once "
                    f"normalised and casefolded, so the roster cannot tell them "
                    f"apart; distinguish them in the file, for example 'Sam K' and "
                    f"'Sam T'"
                )
            seen[key] = name
        object.__setattr__(self, "members", cleaned)


@dataclass(frozen=True, slots=True)
class SetupResult:
    """What one ``apply_group_definition`` did, in enough detail to say it out loud.

    * ``group`` is the group the definition was applied to, created or found.
    * ``group_created`` is ``True`` only when this call wrote the group row.
    * ``members_added`` are the members this call wrote, in file order. Empty on a
      second run over an unchanged roster, which is the whole point of the type.
    * ``members_existing`` are the members that were already there, in stored order.

    Reporting the two lists apart is what lets the operator command say "nothing
    changed" honestly rather than reprinting the roster and leaving the reader to
    compare.
    """

    group: Group
    group_created: bool
    members_added: tuple[Member, ...]
    members_existing: tuple[Member, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.group, Group):
            raise TypeError(
                f"SetupResult group must be a Group, got {type(self.group).__name__}"
            )
        if not isinstance(self.group_created, bool):
            raise TypeError(
                f"SetupResult group_created must be a bool, got "
                f"{type(self.group_created).__name__}"
            )
        for field, value in (
            ("members_added", self.members_added),
            ("members_existing", self.members_existing),
        ):
            if not isinstance(value, tuple):
                raise TypeError(
                    f"SetupResult {field} must be a tuple, got "
                    f"{type(value).__name__}"
                )
            for member in value:
                if not isinstance(member, Member):
                    raise TypeError(
                        f"SetupResult {field} must hold Member values, got "
                        f"{type(member).__name__}"
                    )


# --- Reading a definition ----------------------------------------------------


def parse_group_definition(text: str) -> GroupDefinition:
    """Parse a TOML definition held in memory and return a ``GroupDefinition``.

    The counterpart to ``load_group_definition``: same document, same value, no
    filesystem. A leading byte order mark is tolerated, malformed TOML becomes an
    ``InvalidGroupDefinition`` carrying ``tomllib.TOMLDecodeError`` as its ``__cause__``
    and no ``tomllib`` exception escapes, so one caught type covers every bad roster.

    Raises:
        TypeError: if ``text`` is not a ``str``.
        InvalidGroupDefinition: if the document is malformed, carries a key that is not
            one of ``name``, ``currency`` and ``members``, is missing one of them, or
            holds a value the definition refuses.
    """
    if not isinstance(text, str):
        raise TypeError(
            f"parse_group_definition takes a str of TOML, got {type(text).__name__}"
        )
    return _definition_from(_document(text, "the group definition"), "the group definition")


def load_group_definition(path: str | Path) -> GroupDefinition:
    """Read the TOML definition at ``path`` and return a ``GroupDefinition``.

    There is no default path, nothing is read from the process env, and no directory
    is searched: the path is always passed, mirroring task 6's rule that the store
    never chooses one. Nothing is read at import time.

    The file is decoded as ``utf-8-sig``, so a byte order mark from a plain Windows
    editor is tolerated rather than surfacing as a parse error whose message names
    neither the cause nor the fix. A missing file, a directory and a file that is not
    UTF-8 all become an ``InvalidGroupDefinition`` naming the path: no bare ``OSError``
    and no ``UnicodeDecodeError`` escapes.

    Raises:
        TypeError: if ``path`` is not a ``str`` or a ``Path``.
        InvalidGroupDefinition: if the path cannot be read, or the document is one
            ``parse_group_definition`` refuses.
    """
    if not isinstance(path, (str, Path)):
        raise TypeError(
            f"load_group_definition takes a str or Path, got {type(path).__name__}"
        )
    where = str(path)
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise InvalidGroupDefinition(
            f"the group definition at {where} is not valid UTF-8 text: {error}"
        ) from error
    except OSError as error:
        raise InvalidGroupDefinition(
            f"the group definition at {where} cannot be read: {error}"
        ) from error
    return _definition_from(_document(text, where), where)


def _document(text: str, where: str) -> dict[str, object]:
    """Parse TOML text into a mapping, or raise ``InvalidGroupDefinition`` naming it."""
    try:
        return tomllib.loads(text.lstrip(_BOM))
    except tomllib.TOMLDecodeError as error:
        raise InvalidGroupDefinition(
            f"{where} is not valid TOML: {error}"
        ) from error


def _definition_from(document: dict[str, object], where: str) -> GroupDefinition:
    """Turn a parsed document into a ``GroupDefinition``, refusing anything else.

    Unknown keys are reported before missing ones, so ``currancy = "AUD"`` names the
    typo the operator made rather than the key it happens to have displaced.
    """
    present = set(document)
    unknown = sorted(present.difference(_DEFINITION_KEYS))
    if unknown:
        raise InvalidGroupDefinition(
            f"{where} carries the unrecognised key(s) {_spell(unknown)}; a group "
            f"definition has exactly the keys {_spell(_DEFINITION_KEYS)}"
        )
    missing = [key for key in _DEFINITION_KEYS if key not in present]
    if missing:
        raise InvalidGroupDefinition(
            f"{where} is missing the key(s) {_spell(missing)}; a group definition has "
            f"exactly the keys {_spell(_DEFINITION_KEYS)}"
        )

    name = document["name"]
    if not isinstance(name, str):
        raise InvalidGroupDefinition(
            f"{where}: 'name' must be a string, got "
            f"{type(name).__name__}: {name!r}"
        )

    code = document["currency"]
    if not isinstance(code, str) or not _is_currency_code(code):
        hint = ""
        if isinstance(code, str) and _is_currency_code(code.upper()):
            hint = f"; write {code.upper()!r}"
        raise InvalidGroupDefinition(
            f"{where}: 'currency' must be three uppercase letters such as 'AUD', got "
            f"{code!r}{hint}"
        )

    listed = document["members"]
    if not isinstance(listed, list) or not all(
        isinstance(entry, str) for entry in listed
    ):
        raise InvalidGroupDefinition(
            f"{where}: 'members' must be an array of display name strings, got "
            f"{listed!r}"
        )

    return GroupDefinition(name, Currency(code), tuple(listed))


def _is_currency_code(code: str) -> bool:
    """Whether ``code`` is three uppercase A-Z letters, as ``Currency`` demands."""
    return len(code) == 3 and code.isascii() and code.isalpha() and code.isupper()


# --- Identifying the group ---------------------------------------------------


def resolve_sole_group(store: EventStore) -> Group:
    """Return the one group this store holds, or refuse to guess.

    Not the ``get_the_group`` task 6 declined: it assumes nothing exists, it lives here
    rather than in the store so the store keeps no knowledge that v1 exposes one group,
    and it hands back a ``Group`` whose id still scopes every read a caller makes next,
    exactly as it would with two groups. Exposing several groups later is deleting the
    calls to this function, not unpicking a constant that leaked into twelve files.

    It writes nothing and creates nothing.

    Raises:
        NoGroupConfigured: if the store holds no group, naming the setup command.
        AmbiguousGroup: if it holds more than one, naming every group id.
    """
    groups = store.list_groups()
    if not groups:
        raise NoGroupConfigured(
            f"this store holds no group yet; create one with: {_SETUP_COMMAND}"
        )
    if len(groups) > 1:
        _refuse_ambiguous(groups)
    return groups[0]


def _refuse_ambiguous(groups: tuple[Group, ...]) -> NoReturn:
    """Raise ``AmbiguousGroup`` naming every group id, rather than picking one."""
    raise AmbiguousGroup(
        f"this store holds {len(groups)} groups, so which one is meant is ambiguous: "
        f"{_spell(group.id for group in groups)}; pass the group id explicitly"
    )


# --- Applying a definition ---------------------------------------------------


def apply_group_definition(
    store: EventStore,
    definition: GroupDefinition,
    *,
    now: datetime,
    group_id: str | None = None,
) -> SetupResult:
    """Create the group and its members, or reconcile the ones already there.

    Idempotent for the names already present and additive for names that are new. A
    second call with an unchanged definition writes nothing and reports everything as
    existing. A name the definition gained is written as a new member. A name the
    definition lost, a changed currency and a changed group name are all
    ``GroupMismatch``, because departure is cut from v1 and renaming is out of scope.

    Every refusal is decided before the first write, so one definition that both adds a
    name and drops another writes nothing at all rather than adding half of it. Writing
    itself is not one transaction across rows: the group and each member are separate
    store calls, and a failure part way leaves a partial roster that re-running
    completes. That is what idempotency buys, and no store method exists to do better.

    New members are written one microsecond apart in file order, and after every member
    already stored, so ``list_members`` returns file order with no ``position`` column
    and a member added by a later run sorts last however the two runs' clocks compare.

    With ``group_id`` left as ``None`` this creates when the store holds no group,
    reconciles when it holds exactly one, and raises ``AmbiguousGroup`` when it holds
    more. With an explicit ``group_id`` it reconciles that group and never creates one:
    a group id in a config file or on a command line is exactly the hardcoded id that
    ``resolve_sole_group`` exists to prevent.

    Every member is written with ``user_id=None``. Apply links nobody, ever.

    Raises:
        TypeError: if ``definition`` is not a ``GroupDefinition``, or ``now`` is not a
            ``datetime``.
        InvalidRecord: if ``now`` is naive.
        AmbiguousGroup: if the store holds more than one group and none was named.
        RecordNotFound: if ``group_id`` names no group.
        GroupMismatch: if the stored group disagrees with the definition, or holds two
            members whose names match after normalisation.
    """
    if not isinstance(definition, GroupDefinition):
        raise TypeError(
            f"apply_group_definition takes a GroupDefinition, got "
            f"{type(definition).__name__}"
        )
    moment = _require_utc(now, "now")

    if group_id is not None:
        group = store.get_group(group_id)
        created = False
    else:
        groups = store.list_groups()
        if len(groups) > 1:
            _refuse_ambiguous(groups)
        if groups:
            group = groups[0]
            created = False
        else:
            group = Group(
                GroupId(new_id()), definition.name, definition.currency, moment
            )
            store.add_group(group)
            created = True

    stored = () if created else store.list_members(group.id)
    if not created:
        _require_reconcilable(group, definition, stored)

    by_key = {_key(member.display_name): member for member in stored}
    to_add = [name for name in definition.members if _key(name) not in by_key]

    base = moment
    for member in stored:
        if member.created_at >= base:
            base = member.created_at + _ONE_MICROSECOND

    added: list[Member] = []
    for position, name in enumerate(to_add):
        member = Member(
            MemberId(new_id()),
            group.id,
            name,
            None,
            base + position * _ONE_MICROSECOND,
        )
        store.add_member(member)
        added.append(member)

    return SetupResult(group, created, tuple(added), tuple(stored))


def _require_reconcilable(
    group: Group, definition: GroupDefinition, stored: tuple[Member, ...]
) -> None:
    """Refuse every disagreement between a stored group and a definition.

    Called before the first write, so a refused apply leaves the database exactly as it
    was: same rows, same ids, same timestamps.
    """
    if group.name != definition.name:
        raise GroupMismatch(
            f"group {group.id!r} is named {group.name!r}, but the definition names it "
            f"{definition.name!r}; renaming a group is out of scope in v1"
        )
    if group.currency != definition.currency:
        raise GroupMismatch(
            f"group {group.id!r} is in {group.currency.code}, but the definition says "
            f"{definition.currency.code}; a group's currency is fixed at creation"
        )

    duplicates: dict[str, list[str]] = {}
    for member in stored:
        duplicates.setdefault(_key(member.display_name), []).append(
            member.display_name
        )
    collided = sorted(
        spellings for spellings in duplicates.values() if len(spellings) > 1
    )
    if collided:
        raise GroupMismatch(
            f"group {group.id!r} holds more than one member whose name matches after "
            f"normalisation ({_spell(collided[0])}), so which row the definition "
            f"means cannot be decided here; the ids tell them apart"
        )

    wanted = {_key(name) for name in definition.members}
    dropped = [
        member.display_name for member in stored if _key(member.display_name) not in wanted
    ]
    if dropped:
        raise GroupMismatch(
            f"group {group.id!r} holds the member(s) {_spell(dropped)}, which the "
            f"definition does not list; removing a member is member departure, which "
            f"v1 cuts, so nothing was written"
        )


# --- Linking a user to a member ----------------------------------------------


def link_user_to_member(
    store: EventStore, *, group_id: str, member_id: str, user_id: str
) -> Member:
    """Point a member of ``group_id`` with no user at ``user_id`` and return it.

    The only way a ``user_id`` ever reaches a member row, and a deliberate operator
    action: ``scripts/setup_group.py link`` calls it and nothing else in v1 does.
    Nothing links automatically. No comparison of address, display name or any other
    similarity happens here, because a sign-up address is unverified and matching on
    one would let whoever claimed a flatmate's address take over their position in the
    ledger.

    Linking a member to the user it already points at is a no-op: nothing is written
    and the member comes back unchanged. Linking changes ``user_id`` and nothing else:
    ``id``, ``display_name`` and ``created_at`` are untouched, and there is no
    ``linked_at`` anywhere.

    Nothing here unlinks. There is no function in this module that clears a
    ``user_id``, and the store has no method that could.

    The same person may act for one member in each of several groups; what is refused
    is two members of *one* group pointing at one user.

    Raises:
        RecordNotFound: if no member has ``member_id``, or no user has ``user_id``.
        GroupMismatch: if the member exists but belongs to another group, naming both
            group ids. Passing the group is what makes a cross-group link impossible
            rather than unlikely.
        MemberAlreadyLinked: if the member already points at a different user.
        UserAlreadyLinked: if another member of that group already points at that user.
        DuplicateRecord: if a concurrent writer took either position between the check
            and the write. A caller mapping these to responses maps both it and the two
            above.
    """
    member = store.get_member(member_id)
    if member.group_id != group_id:
        raise GroupMismatch(
            f"member {member_id!r} belongs to group {member.group_id!r}, not to group "
            f"{group_id!r}, so it cannot be linked through it"
        )
    store.get_user(user_id)

    if member.user_id is not None:
        if member.user_id == user_id:
            return member
        raise MemberAlreadyLinked(
            f"member {member_id!r} is already linked to user {member.user_id!r}, so "
            f"it cannot be linked to user {user_id!r}; v1 has no account handover"
        )

    try:
        holder = store.get_member_for_user(group_id, user_id)
    except RecordNotFound:
        holder = None
    if holder is not None:
        raise UserAlreadyLinked(
            f"member {holder.id!r} of group {group_id!r} is already linked to user "
            f"{user_id!r}, so member {member_id!r} cannot be"
        )

    store.set_member_user(member_id, UserId(user_id))
    return store.get_member(member_id)


def acting_member(store: EventStore, *, group_id: str, user_id: str) -> Member:
    """Return the member of ``group_id`` that ``user_id`` acts as.

    What turns "who is signed in" into the ``MemberId`` an event can name. Tasks 10, 14
    and 15 call it first and render the ``MemberNotLinked`` case rather than crashing,
    because a signed-in user with no member row cannot author anything: every event
    field that names a person is a ``MemberId`` and there is none for them.

    It never returns a member whose ``user_id`` is NULL, whatever else matches: an
    unclaimed member row is a flatmate who has not signed up, not this user. It writes
    nothing.

    ``MemberNotLinked`` and ``RecordNotFound`` are deliberately different types,
    because they are two different screens: "nobody has linked you yet", which is what
    every new sign-up looks like, against a group id that does not exist, which is a
    bug.

    Raises:
        RecordNotFound: if no group has ``group_id``.
        MemberNotLinked: if no member of that group points at that user.
    """
    store.get_group(group_id)
    try:
        return store.get_member_for_user(group_id, user_id)
    except RecordNotFound as error:
        raise MemberNotLinked(
            f"no member of group {group_id!r} is linked to user {user_id!r}; an "
            f"operator links a member with 'setup_group.py link'"
        ) from error
