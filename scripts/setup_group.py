"""The operator command behind task 9: seed a group, link an account, read the roster.

    uv run python scripts/setup_group.py apply --store PATH --definition PATH
    uv run python scripts/setup_group.py link --store PATH --email ADDR --member-id ID
    uv run python scripts/setup_group.py show --store PATH

Standard library plus ``splitwise_lite``. Every decision this makes lives in
``splitwise_lite.groups``; this file parses arguments, opens a store, calls one
function and prints what happened. No screen calls it, and it is the only thing in the
repository that links a user to a member.

**It serves nothing.** No socket is bound, no server is started, nothing under ``app/``
is imported, and there is no HTTP layer in this repository for it to be part of.
Possession of the database file is the whole authority: there is no privileged user in
a flat, and this is what a command on a server means.

**No path is guessed.** ``--store`` is required, has no default, reads no environment
variable and is handed to ``open_store`` exactly as typed. No directory is created. The
store is opened and closed around each invocation through its context manager, so a
failed run leaves no handle on the file, which on Windows would block the next run from
renaming or deleting it.

**Re-running ``apply`` is safe.** It writes nothing when nothing changed, adds a name
the file gained, and refuses a name the file lost rather than deleting a member.

Every ``DomainError`` is caught here: the message goes to standard error and the
process exits 1, with no traceback, because a stack trace tells an operator nothing a
sentence could not. Success exits 0, a run that changed nothing included. argparse
reports a usage error itself and exits 2.

Nothing runs at import time beyond these definitions, so a test imports this file and
calls ``main`` directly.
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from collections.abc import Sequence
from datetime import datetime, timezone

from splitwise_lite import (
    DomainError,
    DuplicateRecord,
    EventStore,
    Group,
    Member,
    RecordNotFound,
    apply_group_definition,
    link_user_to_member,
    load_group_definition,
    normalise_email,
    open_store,
    resolve_sole_group,
)

PROGRAM = "setup_group.py"
"""The name argparse reports, so usage text is the same however the file is invoked."""


def _fold(name: str) -> str:
    """The member-name matching key, exactly the one ``groups.py`` uses."""
    return unicodedata.normalize("NFC", name).casefold()


def build_parser() -> argparse.ArgumentParser:
    """The whole command line. Built here so a test can read it without running it.

    No argument has a default path and none is read from an environment variable: an
    operator who has to type the store path cannot seed the wrong database by
    inheriting one.
    """
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Set up the group and its members, and link accounts to them.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    apply_command = commands.add_parser(
        "apply",
        help="create or reconcile the group and its members from a definition file",
        description=(
            "Apply a TOML roster. Safe to re-run: nothing changes when nothing "
            "changed, a new name is added, and a dropped name is refused."
        ),
    )
    _add_store(apply_command)
    apply_command.add_argument(
        "--definition",
        required=True,
        help="path to the TOML roster, for example group.toml",
    )
    _add_group_id(apply_command)
    apply_command.set_defaults(run=_run_apply)

    link_command = commands.add_parser(
        "link",
        help="link a signed-up account to the member row that acts for it",
        description=(
            "A deliberate operator action. Nothing links automatically, because a "
            "signup email address is unverified."
        ),
    )
    _add_store(link_command)
    link_command.add_argument(
        "--email", required=True, help="the address the account signed up with"
    )
    chosen = link_command.add_mutually_exclusive_group(required=True)
    chosen.add_argument("--member-id", help="the member row to link, by id")
    chosen.add_argument(
        "--member-name",
        help="the member row to link, by display name; must match exactly one",
    )
    _add_group_id(link_command)
    link_command.set_defaults(run=_run_link)

    show_command = commands.add_parser(
        "show",
        help="print the group and its roster",
        description=(
            "Read only. Prints no email address and no user id, so a screenshot of "
            "the roster is not an address list."
        ),
    )
    _add_store(show_command)
    _add_group_id(show_command)
    show_command.set_defaults(run=_run_show)

    return parser


def _add_store(parser: argparse.ArgumentParser) -> None:
    """Add the required ``--store``. No default, and no directory is created."""
    parser.add_argument(
        "--store",
        required=True,
        help="path to the SQLite ledger, passed to open_store unchanged",
    )


def _add_group_id(parser: argparse.ArgumentParser) -> None:
    """Add the optional ``--group-id``, the way out of an ambiguous store."""
    parser.add_argument(
        "--group-id",
        default=None,
        help="the group to act on; omit it while the store holds exactly one",
    )


def _group_for(store: EventStore, group_id: str | None) -> Group:
    """The group named by ``--group-id``, or the only one the store holds."""
    if group_id is None:
        return resolve_sole_group(store)
    return store.get_group(group_id)


def _member_named(store: EventStore, group: Group, wanted: str) -> Member:
    """The one member of ``group`` whose display name matches ``wanted``.

    Matching is NFC then casefold, the same key ``apply_group_definition`` uses, so a
    name that reconciles is a name that links. Zero matches and more than one are both
    refused: two flatmates called Sam is a real situation, and guessing which row an
    operator meant is how the wrong person ends up owning a debt.
    """
    key = _fold(wanted)
    matches = [
        member
        for member in store.list_members(group.id)
        if _fold(member.display_name) == key
    ]
    if not matches:
        raise RecordNotFound(
            f"no member of group {group.id!r} is named {wanted!r}; run "
            f"'{PROGRAM} show' to see the roster"
        )
    if len(matches) > 1:
        candidates = ", ".join(repr(member.id) for member in matches)
        raise DuplicateRecord(
            f"{len(matches)} members of group {group.id!r} are named {wanted!r}: "
            f"{candidates}; pass --member-id to say which one"
        )
    return matches[0]


def _run_apply(store: EventStore, arguments: argparse.Namespace) -> None:
    """Apply a roster file and say what it did, including when it did nothing."""
    definition = load_group_definition(arguments.definition)
    result = apply_group_definition(
        store,
        definition,
        now=datetime.now(timezone.utc),
        group_id=arguments.group_id,
    )
    if result.group_created:
        print(f"Created group {result.group.name!r} ({result.group.currency.code}).")
    else:
        print(f"Found group {result.group.name!r} ({result.group.currency.code}).")
    print(f"Group id: {result.group.id}")
    if result.members_added:
        print(f"Added {len(result.members_added)} member(s):")
        for member in result.members_added:
            print(f"  {member.display_name}  {member.id}")
    else:
        print(
            f"Added no members: all {len(result.members_existing)} name(s) in the "
            f"definition were already there. Nothing changed."
        )


def _run_link(store: EventStore, arguments: argparse.Namespace) -> None:
    """Link one signed-up account to one member row, and print the pair."""
    group = _group_for(store, arguments.group_id)
    user = store.get_user_by_email(normalise_email(arguments.email))
    if arguments.member_id is not None:
        member = store.get_member(arguments.member_id)
    else:
        member = _member_named(store, group, arguments.member_name)
    linked = link_user_to_member(
        store, group_id=group.id, member_id=member.id, user_id=user.id
    )
    print(f"Group: {group.name} ({group.id})")
    print(f"Member: {linked.display_name} ({linked.id})")
    print(f"Account: {user.display_name} <{user.email}> ({user.id})")


def _run_show(store: EventStore, arguments: argparse.Namespace) -> None:
    """Print the group and its roster. Reads only, and writes nothing.

    No email address and no user id appear here, only whether an account is linked at
    all, so this output can be pasted into a chat without becoming an address list.
    """
    group = _group_for(store, arguments.group_id)
    members = store.list_members(group.id)
    print(f"Group: {group.name}")
    print(f"Group id: {group.id}")
    print(f"Currency: {group.currency.code}")
    print(f"Created: {group.created_at.isoformat()}")
    print(f"Members ({len(members)}), in roster order:")
    for member in members:
        linked = "linked" if member.user_id is not None else "no account yet"
        print(f"  {member.display_name}  {member.id}  {linked}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return the process exit status.

    0 for success, a run that changed nothing included. 1 for any ``DomainError``,
    whose message goes to standard error with no traceback. argparse exits 2 itself on
    a usage error, before this ever sees the arguments.
    """
    arguments = build_parser().parse_args(argv)
    try:
        with open_store(arguments.store) as store:
            arguments.run(store, arguments)
    except DomainError as error:
        print(f"{PROGRAM}: error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # nothing above this line touches a store or a clock
    raise SystemExit(main())
