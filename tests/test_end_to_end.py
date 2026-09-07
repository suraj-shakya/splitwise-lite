"""One walk of the whole product, from an empty store to a cleared balance.

Task 18 of plans/backlog.md, sharpened in
plans/tasks/18-end-to-end-smoke-test.md. It is the last numbered backlog entry.

The module is ``test_end_to_end.py`` and **not** ``test_smoke.py``, because
``tests/test_smoke.py`` is already task 1's file and holds
``test_package_exposes_its_version``; writing this walk there would have deleted that
test while leaving the suite green.

It imports the helpers it needs from ``tests/test_web_api.py`` by name rather than
restating them or introducing a ``conftest.py``, because a restated setup is ~150 lines
of signup, linking and CSRF scaffolding that nothing would force to stay in step,
whereas a rename over there is an ``ImportError`` here at collection: loud, immediate,
and impossible to miss.

Everything below drives the app through ``app.test_client()``. No socket is bound, no
port is opened, no thread is started and no subprocess is spawned. Every figure comes
back through the JSON API, so there is one code path and one opinion about each; the
only exception is the seed, which has no endpoint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from splitwise_lite import web

# --- The one import from another test module --------------------------------
#
# Exactly ten names, in one explicit statement. No ``import *``, no bare
# ``import test_web_api``, and no conditional import, so a rename over there fails at
# collection rather than silently drifting.
#
# No pytest fixture is imported: ``store_path``, ``seeded``, ``app`` and ``secure_app``
# stay in the module that defines them, and this one builds its own store and
# application below. Importing a fixture function into a second module does work and is
# obscure enough to be a trap.
#
# No imported name begins with ``test_`` either: such a name lands in this module's
# namespace, is collected a second time under a second node id, and moves the suite
# count for a reason nobody can find.
from test_web_api import (
    CHEAP,
    add_expense,
    at,
    by_name,
    claim,
    debt_path,
    decide,
    equal_split,
    linked_client,
    seed_group,
)


@pytest.fixture
def flat(tmp_path: Path):
    """The seeded group and the application over it, built here rather than borrowed."""
    ledger = tmp_path / "ledger.sqlite3"
    # Named explicitly rather than left to ``test_web_api``'s GROUP_NAME, CURRENCY and
    # ROSTER defaults, so a change to those constants cannot quietly change the ledger
    # this test does arithmetic over.
    seed_group(ledger, name="Flat 3", currency="AUD", members=("Sam", "Ali", "Jo"))
    application = web.create_app(
        store_path=ledger, secure_cookies=False, scrypt_params=CHEAP
    )
    return application, ledger


# The reader ``test_web_api``'s ``balances_of`` deliberately is not: it throws the
# response away and so cannot assert the status. At the end of a long walk, a 500 body
# read as a balances payload reports the wrong failure in the wrong place.
def read_balances(client) -> dict:
    response = client.get("/api/balances")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_the_whole_product_walks_from_seeding_to_a_cleared_balance(
    flat, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, ledger = flat

    sam = linked_client(application, ledger, display_name="Sam")
    jo = linked_client(application, ledger, display_name="Jo")
    # Ali is deliberately left unlinked: task 9 decided an unlinked member is a full
    # member that nothing filters or greys out, and every figure about Ali below
    # renders exactly as if Ali had signed up. Two linked accounts is also the minimum
    # a settlement needs, because one person cannot both claim and answer a payment.

    # Every id in this module comes from a response body. None is ever written down:
    # tests/test_groups.py::test_no_source_or_test_file_carries_a_literal_group_id
    # fails on a UUID in any .py file under tests/.
    ids = by_name(sam)
    names = {member_id: name for name, member_id in ids.items()}

    # --- Step 0: the seeded, empty group ------------------------------------

    assert list(by_name(sam)) == ["Sam", "Ali", "Jo"]

    body = read_balances(jo)
    assert set(body) == {"currency", "net", "transfers", "pending", "rejected"}
    assert body["currency"] == "AUD"
    # ``net`` is compared positionally because it is ``store.list_members`` order, which
    # is roster insertion order and is pinned by test_web_api.py's
    # test_the_roster_is_the_group_in_store_order_with_two_keys_each. Contrast
    # ``transfers`` at step 2, which is id-ordered and so is compared name-keyed.
    assert [
        (names[row["member_id"]], row["amount"], row["direction"])
        for row in body["net"]
    ] == [
        ("Sam", "0.00", "settled"),
        ("Ali", "0.00", "settled"),
        ("Jo", "0.00", "settled"),
    ]
    assert body["transfers"] == []
    assert body["pending"] == []
    assert body["rejected"] == []

    # --- Step 1: three expenses, one per split mode -------------------------
    #
    # All three are entered by Sam's client, so ``created_by`` is Sam throughout, while
    # ``payer_id`` names Ali, Sam and Ali in turn: recording that a flatmate paid is a
    # normal entry rather than an impersonation.
    #
    # Every division below is exact -- 3000/3, 8000x1/4 and 8000x3/4, and an exact split
    # has no remainder by construction -- so ``split._allocate``'s leftover rotation is
    # never consulted and no figure in this test depends on a random member id.

    monkeypatch.setattr(web, "_now", lambda: at(9))
    response = add_expense(
        sam,
        payer_id=ids["Ali"],
        amount="30.00",
        split=equal_split(ids["Sam"], ids["Ali"], ids["Jo"]),
        description="Groceries",
    )
    assert response.status_code == 201, response.get_json()
    groceries = response.get_json()["expense"]
    assert groceries["amount"] == "30.00"
    assert groceries["payer_id"] == ids["Ali"]
    assert groceries["created_by"] == ids["Sam"]
    assert {
        names[allocation["member_id"]]: allocation["amount"]
        for allocation in groceries["allocations"]
    } == {"Sam": "10.00", "Ali": "10.00", "Jo": "10.00"}

    monkeypatch.setattr(web, "_now", lambda: at(10))
    response = add_expense(
        sam,
        payer_id=ids["Sam"],
        amount="80.00",
        split={"mode": "weight", "weights": {ids["Sam"]: 1, ids["Ali"]: 3}},
        description="Power bill",
    )
    assert response.status_code == 201, response.get_json()
    power = response.get_json()["expense"]
    assert power["amount"] == "80.00"
    assert power["payer_id"] == ids["Sam"]
    assert power["created_by"] == ids["Sam"]
    assert {
        names[allocation["member_id"]]: allocation["amount"]
        for allocation in power["allocations"]
    } == {"Sam": "20.00", "Ali": "60.00"}

    monkeypatch.setattr(web, "_now", lambda: at(11))
    response = add_expense(
        sam,
        payer_id=ids["Ali"],
        amount="40.00",
        split={"mode": "exact", "amounts": {ids["Ali"]: "10.00", ids["Jo"]: "30.00"}},
        description="Takeaway",
    )
    assert response.status_code == 201, response.get_json()
    takeaway = response.get_json()["expense"]
    assert takeaway["amount"] == "40.00"
    assert takeaway["payer_id"] == ids["Ali"]
    assert takeaway["created_by"] == ids["Sam"]
    assert {
        names[allocation["member_id"]]: allocation["amount"]
        for allocation in takeaway["allocations"]
    } == {"Ali": "10.00", "Jo": "30.00"}

    # Every read from here on is made by Jo's client, because Jo is the person the
    # product exists to answer.
    feed = jo.get("/api/expenses")
    assert feed.status_code == 200, feed.get_json()
    entries = feed.get_json()["expenses"]
    assert len(entries) == 3
    assert [entry["description"] for entry in entries] == [
        "Takeaway",
        "Power bill",
        "Groceries",
    ]

    # --- Step 2: the plan before any payment --------------------------------
    #
    # Sam +50.00, Ali -10.00, Jo -40.00, by addition: Sam is -10.00 on the groceries and
    # +80.00 -20.00 on the power bill; Ali is +30.00 -10.00, -60.00 and +40.00 -10.00;
    # Jo is -10.00 and -30.00.

    body = read_balances(jo)
    assert [
        (names[row["member_id"]], row["amount"], row["direction"])
        for row in body["net"]
    ] == [("Sam", "50.00", "owed"), ("Ali", "10.00", "owes"), ("Jo", "40.00", "owes")]
    # ``transfers`` is sorted by (from_member_id, to_member_id), which is random UUID
    # order, so it is compared as a name-keyed sorted list and never by index. The plan
    # itself is forced by the magnitudes -- one creditor, two debtors of different
    # sizes, no tie anywhere -- so only the row order on the wire depends on an id.
    #
    # Jo pays Sam 40.00 while Jo and Sam share no pairwise debt at all: that is the
    # "why am I paying someone I never bought anything with" case plans/spec.md names,
    # and it is why these amounts were chosen over rounder ones. A plan whose every row
    # mirrored a direct debt would prove simplification ran, not that it simplified.
    assert sorted(
        (
            names[transfer["from_member_id"]],
            names[transfer["to_member_id"]],
            transfer["amount"],
            transfer["awaiting_confirmation"],
        )
        for transfer in body["transfers"]
    ) == [("Ali", "Sam", "10.00", False), ("Jo", "Sam", "40.00", False)]
    assert body["pending"] == []
    assert body["rejected"] == []

    # --- Step 3: Jo marks 40.00 as paid to Sam ------------------------------
    #
    # The claimed amount equals the suggested transfer because that is what a person
    # would do, and **not** because the server checks it: ``web._create_settlement``
    # records what happened in the world and is never compared against the plan.

    monkeypatch.setattr(web, "_now", lambda: at(12))
    settlement_id = claim(jo, to_member_id=ids["Sam"], amount="40.00")

    # --- Step 4: the claim is unanswered, so nothing has moved --------------

    body = read_balances(jo)
    # Written out a second time rather than captured from step 2 into a variable, so
    # "a pending claim moves no figure" is a claim this test makes rather than a
    # tautology about one value compared with itself. Do not fold these into a constant.
    assert [
        (names[row["member_id"]], row["amount"], row["direction"])
        for row in body["net"]
    ] == [("Sam", "50.00", "owed"), ("Ali", "10.00", "owes"), ("Jo", "40.00", "owes")]
    assert sorted(
        (
            names[transfer["from_member_id"]],
            names[transfer["to_member_id"]],
            transfer["amount"],
            transfer["awaiting_confirmation"],
        )
        for transfer in body["transfers"]
    ) == [("Ali", "Sam", "10.00", False), ("Jo", "Sam", "40.00", True)]
    assert len(body["pending"]) == 1
    claimed = body["pending"][0]
    assert claimed["id"] == settlement_id
    assert claimed["from_member_id"] == ids["Jo"]
    assert claimed["to_member_id"] == ids["Sam"]
    assert claimed["amount"] == "40.00"
    assert claimed["state"] == "pending"
    assert claimed["created_by"] == ids["Jo"]
    assert claimed["created_at"] == at(12).isoformat(timespec="microseconds")
    assert body["rejected"] == []

    # --- Step 5: Sam confirms -----------------------------------------------

    monkeypatch.setattr(web, "_now", lambda: at(13))
    response = decide(sam, settlement_id, "confirmed")
    assert response.status_code == 200, response.get_json()
    settlement = response.get_json()["settlement"]
    assert settlement["id"] == settlement_id
    assert settlement["state"] == "confirmed"

    # --- Step 6: the balance has cleared ------------------------------------
    #
    # The confirmed settlement credits Jo 40.00 and debits Sam 40.00: Sam +10.00, Ali
    # unchanged at -10.00, Jo exactly zero. One transfer is left, and Jo is in none.

    body = read_balances(jo)
    assert [
        (names[row["member_id"]], row["amount"], row["direction"])
        for row in body["net"]
    ] == [("Sam", "10.00", "owed"), ("Ali", "10.00", "owes"), ("Jo", "0.00", "settled")]
    assert sorted(
        (
            names[transfer["from_member_id"]],
            names[transfer["to_member_id"]],
            transfer["amount"],
            transfer["awaiting_confirmation"],
        )
        for transfer in body["transfers"]
    ) == [("Ali", "Sam", "10.00", False)]
    assert body["pending"] == []
    assert body["rejected"] == []

    # --- Step 7: the debt that netting did not delete -----------------------
    #
    # simplify.py states it outright: settling every transfer the plan returns gives a
    # ``net`` of exactly zero for every member, and "It does not empty ``pairwise``:
    # simplification converts a chain into a residual cycle, and those live debts
    # cancelling to zero in ``net`` are the visible price of netting." Jo is square with
    # the group and still owes Ali forty dollars. Anyone who reads Jo's "0.00" row and
    # then "fixes" this drill-down has broken the product.
    #
    # Nothing is asserted about ``entries``: task 13 and tests/test_simplify.py own
    # provenance, which can be attributed differently on a tie.
    response = jo.get(debt_path(ids["Jo"], ids["Ali"]))
    assert response.status_code == 200, response.get_json()
    debt = response.get_json()
    assert debt["amount"] == "40.00"
    assert debt["direction"] == "owes"
