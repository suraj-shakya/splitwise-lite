# Task 61: no 4xx body carries an internal identifier

**Depends on:** 2, 3, 9a, 10, 12, 12a, 13, 14, 15, 39, 51, 60/65/67 (all complete, on
`master`). Assume every one of them has landed: `split.py`'s three resolvers take a
keyword-only `currency`, `web.py` holds both error tables and the route audit,
`tests/test_suite_integrity.py` refuses duplicate definitions and unanchored pins, and
`plans/mutations/` exists with its README and record format.
**Consumed by:** the follow-up this task files against the balances screen (see
"What follows for the two screens"). Nothing blocks on it.

Closes GitHub issue **#61**. `plans/backlog.md` has no entry for it and this task does
not add one; the issue is the backlog entry and this file is the implementable version.

---

## What was measured, and where the issue is wrong

The issue names two `split.py` refusals. A reviewer on PR #62 added a third in `web.py`.
The brief that commissioned this spec named six. **There are twelve**, and the severity
ordering in the issue and in the reviewer's comment is wrong in both directions: there
are four times as many sites as anybody had counted, and **none of them is reachable
from the shipped shell**.

### The twelve sites

Every row is a message this repo puts into a mapped **4xx** JSON body, and every row
interpolates an internal identifier. Line numbers are against `master` at the time of
writing and will drift; the function name and the sentence are the stable handles.

| # | site | status / code | what it leaks |
|---|---|---|---|
| 1 | `split.py::_ordered_from_iterable` `member_ids names a member more than once: {list(ordered)}` | 400 `invalid_split` | a **whole list** of member ids |
| 2 | `split.py::_ordered_from_mapping` `{field} for {member_id!r} must be zero or positive, got {value}` | 400 `invalid_split` | a member id, plus a bare integer that is a **weight** in weight mode and an **amount in cents** in exact mode |
| 3 | `web.py::_create_expense` `{what} names a payer_id that is not a member of this group: {payer_id!r}` | 400 `malformed_request` | a member id |
| 4 | `web.py::_require_member_id` `a split names a member id that is not a member of this group: {value!r}` | 400 `malformed_request` | a member id |
| 5 | `web.py::_require_weight` `the weight for {key!r} must be a JSON integer` | 400 `malformed_request` | a member id, and a **current roster** one |
| 6 | `web.py::_require_exact_amount` `the exact amount for {key!r} must be an amount as a JSON string, ...` | 400 `malformed_request` | a member id, and a **current roster** one |
| 7 | `web.py::_create_settlement` `{what} names a to_member_id that is not a member of this group: {to_member_id!r}` | 400 `malformed_request` | a member id |
| 8 | `web.py::_create_settlement` `a member cannot record a payment to themselves: {to_member_id!r} is both the payer and the receiver` | 400 `malformed_request` | a member id, and a **current roster** one |
| 9 | `web.py::_decide_settlement` `no settlement in this group with that id: {settlement_id!r}` | 404 `record_not_found` | a **settlement** id |
| 10 | `web.py::_read_debt` `a debt path names a member id that is not a member of this group: {value!r}` | 400 `malformed_request` | a member id |
| 11 | `web.py::_read_debt` `a member cannot owe themselves: {debtor_id!r} was asked about as both the debtor and the creditor` | 400 `malformed_request` | a member id, and a **current roster** one |
| 12 | `groups.py::resolve_member` `no member of group {group_id!r} is linked to user {user_id!r}; ...` | 403 `member_not_linked` | a **group** id and a **user** id |

Rows 5, 6, 8, 9, 11 and 12 were found while writing this spec. Rows 5 and 6 matter more
than they look: their `{key!r}` is a member id that **is** in the roster, so unlike rows
3, 4, 7 and 10 they do not need the roster to have moved.

### Reachability from the shipped shell: none of the twelve

The brief asked for this to be derived from `app/` rather than taken from the issue.
Derived, and the answer is not what either the issue or the PR #62 comment says.

**What the add screen can send.** `addSplit()` in `app/app.js` builds `member_ids` from
`addRoster` (equal) or from the checked rows (some), one entry per roster member, so it
cannot repeat an id; it builds `amounts` keyed by `addRows[i].member.id` with values
`String(field.value).trim()`, so every share is a JSON string; and it never emits
`mode: 'weight'`, which the screen offers no control for. `payer_id` is
`addPayer.value`, an option value filled from the roster. So rows 1, 5 and 6 are
unreachable by construction, and row 2 is unreachable in exact mode because
`money.parse_amount` refuses every signed string before `split_exact` sees it and in
weight mode because no screen sends weights.

**What the balances screen can send.** `api.debt(row.debtor_id, row.creditor_id)` takes
both ids from an absorbed-debt row of `GET /api/balances`, and `simplify.py` guarantees
no self-pair, so row 11 is unreachable. `api.addSettlement(transfer.to_member_id, ...)`
is only wired to a row where `transfer.from_member_id === actingId`
(`balancesActionRegion` returns `null` otherwise), and the payer is taken from the
session, so the payer and the receiver can never be the same person and row 8 is
unreachable. `api.decideSettlement(view.id, ...)` sends a settlement id the same read
just returned, so row 9 needs that settlement to have vanished, and nothing deletes one.

**Rows 3, 4, 7, 10 and 12 need the roster to have moved under an open screen.** The PR
#62 reviewer's story for row 4 is "someone has the Add screen open, an operator removes
a member, they save". **That story is false as written.** `setup_group.py apply` refuses
to remove a member: `groups.py` raises
`GroupMismatch("group ... holds the member(s) ..., which the definition does not list;
removing a member is member departure, which v1 cuts, so nothing was written")`. And
there is no other removal path: `grep` for `DELETE FROM members`, `_DELETE_MEMBER`,
`delete_member` and `remove_member` across `src/` returns nothing. `spec.md` cuts member
departure for v1 and lists it as open question 1. So a roster shrinking under an open
screen requires **direct SQLite surgery on the ledger file**, not an operator command.

Row 12 is the one an ordinary sequence reaches, and only just: sign up, do not get
linked, open the app. But `app/api.js` classifies 403 `member_not_linked` as
`not-linked`, and `speaks()` returns false for that kind, so `say` is `''` and the
sentence never reaches a screen. It reaches the wire and the browser's network panel.

**So: twelve sites, zero reachable from the shipped shell through any sequence of
ordinary use.** Reaching any of them takes a hand-written request or a hand-edited
database, and in both cases the requester supplied or already holds the id.

### Why the task is still worth doing, given that

Because the deliverable is not the twelve sentences. It is the **premise** two screens
are built on.

* The **add screen** prints every server sentence verbatim (`addRefused` writes
  `error.message` into `#add-error-server`, and the comment there says "no rewording, no
  truncation, no added punctuation and no per-code substitution"). #39 justified keeping
  that by auditing `invalid_split` and finding every reachable one id-free. The PR #62
  reviewer re-derived it and confirmed it, and then pointed out that the justification
  covers one code and the screen shows all of them.
* The **balances screen** prints no server sentence at all, in three separate regions,
  each with a comment naming a member id as the reason: `BALANCES_FAILED` ("the sentence
  this route composes for its own 400 names a member id, which this screen may never
  show as text"), `BALANCES_NOT_RECORDED` ("Every refusal this endpoint can produce names
  a member id, ...") and `BALANCES_NOT_ANSWERED` ("... this screen renders no member id
  and no settlement id as visible text").

Both policies rest on somebody having read `web.py`'s and `split.py`'s prose and
concluded what the reachable messages can contain. That reading has now been done four
times, by four people, in four different files, and produced four different answers: two
sites, three sites, six sites, twelve sites. A premise that has to be re-derived by hand
whenever a message is edited, from a file other than the one being edited, is not a
premise. It is a debt, and it comes due silently.

There are two smaller reasons. `split.py`'s row 2 still spells raw cents in exact mode:
#39's criterion 8 excused its integer as "a weight", which covers only one of that
function's two callers, so `CLAUDE.md`'s money rule is still broken there. And the
issue's own severity claim needs correcting in writing, in both directions, so nobody
re-litigates it from the issue text.

---

## The decision: may a 4xx body carry an internal identifier?

**No. A message this repo sends with a 4xx status contains no internal identifier: no
member id, no user id, no group id, no expense id, no settlement id, no event id.**

The 500 case is already settled the same way and for a stronger reason
(`_GENERIC_500_MESSAGE`, "a 500 message can carry a file path, a SQL fragment or a
stored hash"). This task settles the 4xx case.

### Why not the alternative

The alternative on the table is the status quo: a 4xx may carry an id, and each screen
decides per endpoint whether that endpoint's sentences are safe to render. Rejected for
three reasons.

1. **It has already failed four times, silently.** See above. The failure mode is not
   that somebody renders an id; it is that the reasoning lives in a comment in `app/`
   about code in `src/`, and nothing goes red when the two diverge.
2. **"The requester already knows the id" is true and irrelevant.** It is the defence the
   issue offers for rows 1 and 2, and it is sound about confidentiality: every one of the
   twelve requires a session and group membership, none of them tells a stranger
   anything, and in every case the id came in on the request. But the requester is the
   shell, and the reader is a person. The shell knowing an id is not a reason to put it
   in front of somebody who never typed it, in a product that shows no identifier
   anywhere else: task 12 decided "a UUID on screen is noise that helps nobody" and task
   13 held the same one level down.
3. **The information a diagnostic needs is the field, not the value.** A caller refused
   for `payer_id` holds its own request body. Naming `payer_id` tells it where to look;
   naming the value tells it something it already has. This is the whole content of the
   distinction the brief asked for, and it is worked through case by case below.

### The distinction the brief asked for, worked through

The brief is right that "a refusal naming which member has a bad weight may be worth
having for a programmer; a refusal dumping a list of ids to a person is not", and that
one rule should not be applied blindly to both. Working it through, there are three
shapes, not two.

* **Cardinality one.** The request named exactly one thing and it was wrong: rows 3, 7,
  8, 9, 11, 12. The field name is a complete locator, because there is one candidate.
  The value adds nothing. **Drop the value, keep the field name.**
* **Cardinality two, positional.** Rows 10: the path has two segments and the caller
  cannot tell from a constant sentence which of them was refused. **Name the position**
  (`debtor`, `creditor`), which is a path-parameter name and not an identifier. This
  also keeps the discriminating power of the existing parametrised test.
* **Cardinality many, keyed by the id itself.** Rows 1, 2, 4, 5, 6: the request named a
  set (a `member_ids` array, or a `weights`/`amounts` object keyed by member id) and one
  element was wrong. Here the id genuinely carries information no field name does, and
  this is the case the brief flags. **Drop it anyway**, and do not replace it with a
  count or an ordinal:
  * a count is a third figure that has to stay true, which is exactly the objection #39
    made to "you are out by";
  * an ordinal into a JSON object is an ordering claim the wire format does not make;
  * and the caller holds both halves of the diff already. The set it sent minus the
    roster it read from `GET /api/members` is a one-line comparison in whatever wrote
    the request. The message saves that caller one lookup, and costs the property that
    makes both screens' policies safe. The trade is not close.

### Payload key names are not identifiers, and stay

`payer_id`, `to_member_id`, `member_ids`, `weight`, `amount`, `debtor` and `creditor`
stay in the messages. They are names in this repo's own published wire contract, the
caller wrote them, and `web.py` already names payload keys in a dozen refusals
(`_require_keys`, `_require_str`, `_require_object`, `_require_list`,
`_require_amount_str`). #39's criterion 5 objected to `total_cents` for a different
reason: that was a **Python parameter name** shown where a public one (`amount`) existed.

Say this plainly, because it bounds what this task claims: **an id-free 4xx message is
guaranteed safe, not guaranteed good.** `an expense body names a payer_id that is not a
member of this group` is machine prose in front of a flatmate. Safety is what this task
delivers and what a check can enforce. Whether a given sentence is worth showing to a
person is a separate, per-route design question, and it is the follow-up.

### One named exemption, and why the check needs none

Two rows of `ERROR_STATUS` are **503**, and both deliberately carry identifiers:
`groups.AmbiguousGroup` names every group id and `groups.NoGroupConfigured` names the
setup command. `web.py`'s own docstring defends this in so many words, and the defence
holds: a 503 here means the deployment cannot express what it holds, no change to any
request fixes it, the only reader who can act is an operator, and the ids are how that
operator tells two groups apart. `app/api.js` classifies 503 as `unavailable`, `speaks()`
returns true, and `app/app.js` shows it on the notice curtain, which is correct: it is
the one message in this repo written for an operator and shown to whoever is holding the
phone, because there is nobody else to tell.

**The rule is therefore scoped to 4xx, and 503 is outside it by status rather than by
exemption.** Three further rows (`groups.GroupMismatch`, `groups.MemberAlreadyLinked`,
`groups.UserAlreadyLinked`, all 409) name ids and are raised only by
`apply_group_definition` and `link_user_to_member`, which `web.py` never calls: they are
`scripts/setup_group.py`'s refusals, read by an operator at a terminal, and no HTTP
request reaches them. `store.py`'s `RecordNotFound`, `DuplicateRecord` and
`CurrencyMismatch` messages name ids and are likewise unreachable from any route (every
id `web.py` passes into the store is one the store just gave it). `balances.CurrencyMismatch`
names an event id at 400 and is unreachable because `spec.md` freezes a group's currency.
`store.AmountTooLarge` names raw cents at 400 and is unreachable because `parse_amount`
refuses above `MAX_CENTS` first; it is #39's recorded leftover and stays recorded.

The consequence is the good part: because every one of those is unreachable by request,
**the dynamic half of the check needs no allowlist, no exemption set and no marker
comment.** There is nothing in it to rot.

### `InvalidSplit` stays. The class is not the defect

The issue asks whether row 1 should be a `MalformedRequest` rather than an
`InvalidSplit`. **No.** Four reasons, stated so nobody re-opens it:

1. `MalformedRequest` is a `WebError` defined in `web.py`. The domain layer may not
   import the web layer, and a test asserts it. "Reclassify" therefore means either
   moving the check into `_resolve_split` or moving the class into the domain layer.
2. Moving the check means **two checks for one situation**, because `split.py`'s guard
   has to stay regardless: its docstring's reason ("`ExpenseEvent` rejects duplicate
   allocations, and the resolver must not manufacture what the event will refuse") is
   about the resolver's contract with the event, not about the wire, and a non-HTTP
   caller needs it. `app/api.js`'s header names that failure mode: "two sentences for one
   situation drift the moment either one is edited".
3. The precedent that looks like it argues the other way argues this way.
   `_create_settlement` refuses the self-pair in `web.py` rather than leaving it to
   `SettlementEvent.__post_init__` **because `InvalidEvent` is unmapped and would be a
   500**. Here the domain exception is already a mapped 400 with its own code, so there
   is no defect a pre-check would fix.
4. A client branches on `code`, and both codes are 400 that `app/api.js` classifies as
   `refused` and routes to the same place on the same screen. Changing the code buys no
   client anything and costs a row in `ERROR_STATUS`, a row in `ERROR_CODE`, a row in
   `ERROR_ROWS`, and an edit to `api.js`'s documented classification table.

`InvalidSplit`'s docstring already claims to be "one named type for every value rejection
in this module", which a repeated member is.

### Weight mode: a resolver capability with no product behind it, and it stays

`spec.md` locks the split rules as "Equal, equal across a subset, and uneven shares" and
ships "All three split modes". `split.py` provides four modes' worth of capability for
those three rules: `split_equally` covers equal and subset, `split_exact` covers uneven
shares (the add screen's **Uneven amounts**), and `split_by_weight` covers nothing the
spec asks for. No screen offers it, `app/index.html` has no control for it, and
`addSplit()` cannot emit it. **So yes: weight is a resolver capability with no product
behind it, and `spec.md` does not require it.**

It nevertheless **stays**, unchanged in signature and behaviour. Removing it means
deleting a name from `split.__all__` and from the package root's re-exports, deleting the
`weight` arm of `_resolve_split` and its wire mode, and deleting or rewriting a
substantial block of `tests/test_split.py` and `tests/test_web_api.py`, including the
three-mode parametrisation this task edits. That is a scope-and-API decision with its own
blast radius, and it is not a prerequisite for anything here: rows 2 and 5 are fixed by
rewording, not by deletion. **File it as its own issue** (see criterion 44) so the
question is recorded rather than re-asked.

What weight mode's existence does decide is a smaller thing, and it decides it against
the id: row 2's integer is a weight for one caller and cents for the other. Formatting it
would need a `currency` on `_ordered_from_mapping`, which #39's criterion 9 froze and its
out-of-scope list forbids, and would still leave one function rendering one branch as
money and the other as a count. **Drop the integer**, which fixes both halves of #39's
half-covered criterion 8 in one edit.

---

## What each message becomes

Exact target text. Lower case opening, no trailing full stop, matching every other
message in `money.py`, `split.py`, `web.py` and `groups.py`.

### `src/splitwise_lite/split.py`

**1.** `_ordered_from_iterable`, the duplicate guard. The `f` prefix goes with the
interpolation.

```python
raise InvalidSplit("member_ids names a member more than once")
```

**2.** `_ordered_from_mapping`, the negative guard.

```python
raise InvalidSplit(f"every {field} must be zero or positive")
```

`field` is `"weight"` or `"amount"`, so this reads `every weight must be zero or
positive` and `every amount must be zero or positive`. The **`TypeError` two lines above
keeps `{member_id!r}` and `{value!r}`**: a wrong Python type is a programming error, it
becomes a generic 500 with a logged traceback, and its reader is a programmer reading
that traceback. That is `_require_total`'s existing rule and it is not being changed.

### `src/splitwise_lite/web.py`

**3.** `_create_expense`:

```python
raise MalformedRequest(
    f"{what} names a payer_id that is not a member of this group"
)
```

**4.** `_require_member_id`, which becomes a constant string parallel to the branch
above it:

```python
raise MalformedRequest(
    "a split names a member id that is not a member of this group"
)
```

**5.** `_require_weight` **loses the parameter that carried the id**:

```python
def _require_weight(value: object) -> int:
    ...
    raise MalformedRequest("every weight in a split must be a JSON integer")
```

**6.** `_require_exact_amount` likewise:

```python
def _require_exact_amount(value: object, currency: money.Currency) -> int:
    ...
    raise MalformedRequest(
        'every exact amount in a split must be an amount as a JSON string, such '
        'as "8.00"; amounts are strings, never numbers'
    )
```

Dropping the parameter rather than merely dropping the interpolation is deliberate:
after it, no future edit can reintroduce the leak without adding an argument, which is a
change a reviewer sees. The two call sites in `_resolve_split` lose one argument each and
nothing else; the dict comprehensions keep their shape and their evaluation order.

**7.** `_create_settlement`, the roster check:

```python
raise MalformedRequest(
    f"{what} names a to_member_id that is not a member of this group"
)
```

**8.** `_create_settlement`, the self-pair. The clause that named the id is replaced by
one that says something the caller cannot otherwise know, since it never sent a payer:

```python
raise MalformedRequest(
    "a member cannot record a payment to themselves; the payer is whoever is "
    "signed in"
)
```

**9.** `_decide_settlement`:

```python
raise store.RecordNotFound("no settlement in this group with that id")
```

**10.** `_read_debt`, the roster loop, which gains the position and loses the value:

```python
for position, value in (("debtor", debtor_id), ("creditor", creditor_id)):
    if value not in roster:
        raise MalformedRequest(
            f"a debt path names a {position} that is not a member of this group"
        )
```

**11.** `_read_debt`, the self-pair:

```python
raise MalformedRequest(
    "a member cannot owe themselves; the debtor and the creditor in the path "
    "are the same member"
)
```

### `src/splitwise_lite/groups.py`

**12.** `resolve_member`:

```python
raise MemberNotLinked(
    "no member of this group is linked to your account; an operator links a "
    "member with 'setup_group.py link'"
) from error
```

The `group_id` and `user_id` parameters stay: the function still uses them for the store
call. This is the one of the twelve whose sentence reaches no screen today, so its whole
value is that the check has no hole in it.

---

## The mechanical check, and whether it can avoid false positives

The brief asks what such a check looks like and whether it can avoid false positives.
The honest answer has two parts, and pretending one check does the job is the mistake to
avoid.

**A purely static check cannot avoid false positives here.** The thing it has to
distinguish is a payload key **name** from a member id **value**, and in the source both
are a bare name interpolated into an f-string: `{key!r}` in `_require_str` is a literal
at every call site, and `{key!r}` in `_require_weight` is a member id. That is a fact
about runtime values, not about syntax. A denylist of variable names has false positives
on the first kind and false negatives the moment somebody renames or reaches an id
through an attribute. It is also exactly the shape issue #42 is about: a premise living
outside the check.

**A purely dynamic check cannot avoid false negatives.** It proves the property for the
request shapes it drives, and a leak on an undriven branch survives.

So the check is two checks with two different jobs, and the static one's job is **not**
finding leaks. It is an enumeration equality, of the kind this repo already runs twice
(`web._audit_routes` holds `_API_ROUTES` against the registered routes, and
`test_the_harness_reports_exactly_the_declared_scenarios` holds `SCENARIOS` against the
harness). An enumeration equality has no false positives at all, because it compares two
sets rather than judging a value.

**Check A, the enumeration.** An `ast` walk over every module in `src/splitwise_lite/`
collects one entry per `raise` whose exception class resolves, through `web.ERROR_STATUS`
walked by MRO exactly as `web._status_and_code` walks it, to a status in
`range(400, 500)`. Each entry is keyed by `(module file name, enclosing `def` name,
message skeleton)`, where the **skeleton** is the concatenation of the literal fragments
of the message with the interpolations removed, so it is stable under reformatting and
changes precisely when the wording does. The test asserts that set equals the key set of
a hand-declared table, in both directions: a new 4xx raise anywhere in the package fails
until somebody adds a row, and a row for a site that no longer exists fails too.

**Check B, the property.** Each row of that table is either a driven request or the
marker `NO_REQUEST_REACHES_IT` with a one-line reason, whose minimum length the test
enforces the same way `test_suite_integrity.py` enforces a reason on an `# unanchored:`
marker. For each driven row the test makes the request against the seeded app and
asserts the status is 4xx, the code is the row's code, and **no identifier the store
holds occurs in `body["error"]["message"]`**.

The identifier set is gathered from the store rather than written down: the group id,
every member id, every user id, and the id of every event `list_events` returns
(expenses, settlements, settlement decisions). That is complete by construction, because
any id the server could interpolate came from the store, and it stays complete when a new
event type lands. The gatherer asserts every id it collects is at least eight characters
long, so an unusually short id fails the check loudly instead of matching a common
substring and flaking.

**Why this pair would have found all twelve.** Check A enumerates raise sites, not
messages, so it does not care what anybody thought was reachable: rows 5, 6, 8, 9, 11 and
12 all have a `raise` in a 4xx-mapped class and all would have demanded a table row.
Check B then forces each row to be either driven or declared unreachable with a reason.
Three readers finding three sites one at a time is what an audit does; enumeration is
what a check does.

**What is still not covered, stated.** A row marked `NO_REQUEST_REACHES_IT` is a claim
the check cannot verify, only record. And Check B's identifier set does not include an
email address, deliberately: `accounts.EmailAlreadyRegistered` names a normalised email
at 409, that address is the person's own typed input, the sign-up screen shows it, and
echoing typed input is `parse_amount`'s already-accepted precedent.

---

## What follows for the two screens

**The add screen keeps showing the server's sentence, and nothing under `app/` changes.**
Its behaviour was already right; what changes is that its justification stops being a
per-code audit ("every reachable `invalid_split` is id-free") and becomes a property of
the whole 4xx surface, enforced on every run. That is the upgrade the PR #62 reviewer's
finding asked for: `malformed_request` is a different code on the same screen and it
could carry an id, and after this task no code on that screen can.

**The three fixed sentences on the balances screen stay, and their conversion to
`error.say` is a follow-up this task files.** The id half of their justification is
discharged by this task. The other half is not, and this task does not touch it:
`BALANCES_NOT_ANSWERED`'s comment also cites refusals that "describe a body the person did
not type" or "a rule about who they are", and the harness's `NOT_THE_RECEIVER` constant is
already id-free prose that a scenario asserts absent for that second reason. So the
question "which of the remaining id-free sentences are good prose for a flatmate" is a
per-route design judgement across three regions and six kinds, and some of the answers are
clearly yes (`that payment has already been answered, and an answer cannot be taken back`)
and some clearly no (`a settlement body key 'amount' must be an amount as a JSON string`).

Keeping it out of this task also keeps this task's diff Python-only, which is worth
stating: touching `app/app.js` costs a `VERSION` bump and a `SHELL_DIGEST` recompute for
a change of zero rendered bytes, and it would mean writing a comment about a decision not
yet made.

**The cost of deferring, stated.** Three comments in shipped `app/app.js` will carry a
premise this task falsifies. They are named verbatim in criterion 43 and go in the PR body
and in the follow-up issue, so the fourth reader inherits a record instead of a discovery.

---

## Goal

No message this repo sends with a 4xx status contains an internal identifier, and that is
a checked property of the whole error surface rather than a claim somebody re-derives by
reading `web.py`. Twelve messages are reworded to name the field rather than the value;
`split.py`'s one remaining raw-cent integer goes with them; and a two-part check
enumerates every 4xx raise site in the package and drives every reachable one, so a
reintroduced leak fails the suite instead of waiting for a fourth audit.

---

## Acceptance criteria

Each is a yes or no a QA agent can reach by reading a file or running a command. `REPO`
is the worktree root and every path is relative to it. A quoted string is quoted exactly,
including case and the absence of a trailing full stop.

### The twelve messages

1. `src/splitwise_lite/split.py`'s duplicate guard raises `InvalidSplit` whose `str()` is
   exactly `member_ids names a member more than once`. The call is a plain string with no
   `f` prefix, and `list(ordered)` appears nowhere in the module.
2. `src/splitwise_lite/split.py`'s negative guard in `_ordered_from_mapping` raises
   `InvalidSplit` whose `str()` is exactly `every weight must be zero or positive` for
   `split_by_weight` and exactly `every amount must be zero or positive` for
   `split_exact`. Neither message contains a member id, and neither contains a bare
   integer of any kind.
3. The `TypeError` immediately above it still reads
   `f"{field} for {member_id!r} must be an int, got {type(value).__name__}: {value!r}"`,
   byte for byte. A comment on it says why: a wrong Python type is a programming error,
   becomes a generic 500 with a logged traceback, and its reader is a programmer.
4. `_ordered_from_mapping` and `_ordered_from_iterable` are unchanged in signature.
   Neither takes a `currency`, and `split.py` gains no second display helper: `_formatted`
   is still the only one and `format_amount` is still the only display edge.
5. `web.py::_create_expense` raises `MalformedRequest` whose message is exactly
   `an expense body names a payer_id that is not a member of this group`.
6. `web.py::_require_member_id`'s roster branch raises `MalformedRequest` whose message is
   exactly `a split names a member id that is not a member of this group`, as a constant
   string. Its type branch, `a split names a member id that is not a JSON string`, is
   unchanged.
7. `web.py::_require_weight`'s signature is `def _require_weight(value: object) -> int:`
   and its message is exactly `every weight in a split must be a JSON integer`. The name
   `key` does not appear in the function.
8. `web.py::_require_exact_amount`'s signature is
   `def _require_exact_amount(value: object, currency: money.Currency) -> int:` and its
   message is exactly
   `every exact amount in a split must be an amount as a JSON string, such as "8.00"; amounts are strings, never numbers`.
   The name `key` does not appear in the function.
9. `_resolve_split`'s two dict comprehensions pass one argument fewer to each helper and
   are otherwise unchanged: `_require_member_id(key, roster)` is still the key expression
   in both, both still iterate `.items()`, and no third mode arm is added or removed.
10. `web.py::_create_settlement`'s roster check raises `MalformedRequest` whose message is
    exactly `a settlement body names a to_member_id that is not a member of this group`.
11. `web.py::_create_settlement`'s self-pair check raises `MalformedRequest` whose message
    is exactly
    `a member cannot record a payment to themselves; the payer is whoever is signed in`.
12. `web.py::_decide_settlement`'s missing-settlement check raises `store.RecordNotFound`
    whose message is exactly `no settlement in this group with that id`.
13. `web.py::_read_debt`'s roster loop iterates
    `(("debtor", debtor_id), ("creditor", creditor_id))` and raises `MalformedRequest`
    whose message is exactly `a debt path names a debtor that is not a member of this group`
    for the first position and
    `a debt path names a creditor that is not a member of this group` for the second.
14. `web.py::_read_debt`'s self-pair check raises `MalformedRequest` whose message is
    exactly
    `a member cannot owe themselves; the debtor and the creditor in the path are the same member`.
15. `groups.py::resolve_member` raises `MemberNotLinked` whose message is exactly
    `no member of this group is linked to your account; an operator links a member with 'setup_group.py link'`.
    Its signature and its store call are unchanged, and the `from error` chaining stays.
16. Every one of the twelve is lower case at the start and has no trailing full stop.
17. No message in `split.py`, `web.py` or `groups.py` that reaches a 4xx body interpolates
    a name or attribute ending in `_id`, nor a bare `key`, `value`, `debtor` or
    `creditor`. Checked by reading, and enforced by criteria 27 to 31.

### The error contract does not move

18. `ERROR_STATUS`, `ERROR_CODE`, `_HTTP_ERROR_CODES`, `_GENERIC_500_MESSAGE`,
    `_handle_error`, `_status_and_code`, `_API_ROUTES`, `_Access`, `_audit_routes` and
    `web.__all__` are byte-identical to `master`. No new exception class, no new status,
    no new code, no change to the one JSON body shape.
    `test_the_two_tables_are_keyed_the_same_way_and_hold_exactly_these_rows`,
    `test_every_mapped_error_carries_its_status_and_its_code` and
    `test_the_module_imports_flask_and_the_standard_library_only` pass unedited.
19. `split.InvalidSplit` is still 400 `invalid_split`; `MalformedRequest` is still 400
    `malformed_request`; `store.RecordNotFound` is still 404 `record_not_found`;
    `groups.MemberNotLinked` is still 403 `member_not_linked`. Every code every one of the
    twelve reports is the code it reported on `master`.
20. `groups.AmbiguousGroup` and `groups.NoGroupConfigured` are untouched, and still name
    the group ids and the setup command respectively. `web.py`'s docstring paragraph
    defending them is unchanged.
21. `src/splitwise_lite/split.py` and `src/splitwise_lite/groups.py` import nothing new,
    and neither imports the web layer.
    `test_importing_the_package_does_not_import_the_framework`,
    `test_no_module_in_the_package_imports_the_web_layer` and
    `test_split_imports_only_money_and_events_from_the_package` pass unedited. The domain
    layer still imports with Flask absent.
22. `split.__all__`, `groups.__all__` and `src/splitwise_lite/__init__.py` are
    byte-identical. `test_the_resolver_is_re_exported_from_the_package_root` passes
    unedited.
23. `events.py`, `balances.py`, `simplify.py`, `store.py`, `money.py` and
    `accounts.py` are not edited.

### Nothing under `app/` changes

24. **`SHELL_DIGEST` does not move, and nobody should go looking.** No file under `app/`
    is read for editing, edited, added or removed. `git diff --stat` shows no path
    beginning `app/`, `VERSION` and `SHELL_DIGEST` in `app/sw.js` are unchanged, and
    `test_the_recorded_digest_matches_the_files_it_covers` passes unedited. The digest
    covers files under `app/` only; `tests/shell_harness.mjs` is a test fixture and is not
    in it.
25. `app/api.js`'s six kinds, three handlers and two fields are untouched: `classify()`,
    `speaks()` and `announce()` stay as they are, and `say` is still either exactly
    `error.message` or exactly `''`.
26. `app/app.js`'s `addRefused` still writes `error.message` into `#add-error-server`
    untouched, and `BALANCES_FAILED`, `BALANCES_NOT_RECORDED` and `BALANCES_NOT_ANSWERED`
    are still the fixed sentences their three regions show for every kind. This task
    changes neither policy.

### The mechanical check

27. A new module `tests/test_error_messages.py` holds one hand-declared table,
    `FOUR_HUNDRED_SITES`, with one row per `raise` site in `src/splitwise_lite/` whose
    exception class maps to a 4xx status. Each row carries the module file name, the
    enclosing `def` name, the message skeleton, and either a driver or the marker
    `NO_REQUEST_REACHES_IT` with a reason.
28. `test_every_four_hundred_raise_site_is_declared` walks `src/splitwise_lite/*.py` with
    `ast`, resolves each `raise`'s class through `web.ERROR_STATUS` **by MRO, the way
    `web._status_and_code` resolves it**, keeps the ones whose status is in
    `range(400, 500)`, and asserts the resulting key set equals `FOUR_HUNDRED_SITES`'
    key set. The assertion is an equality, so both a new undeclared site and a stale
    declared row fail it, and the failure message names the offending keys.
29. The **skeleton** of a message is the concatenation of the literal fragments of the
    f-string or string, interpolations removed. A criterion-30 test proves the skeleton of
    `f"{what} names a payer_id that is not a member of this group"` is
    ` names a payer_id that is not a member of this group`, so the key is stable under
    reflowing a message across different line breaks and changes only when the wording
    changes.
30. `identifiers_in(message, identifiers)` is a pure function returning every identifier
    that occurs in `message`, and it is unit-tested four ways, in the style of
    `test_suite_integrity.py`'s own self-tests: it finds an id that is present, it finds
    nothing in an id-free message, it finds an id embedded mid-sentence with surrounding
    punctuation, and it reports two ids when two are present. **This is the criterion that
    proves the check bites without needing a mutation run.**
31. `test_no_four_hundred_body_names_an_identifier` is parametrised over the driven rows
    of `FOUR_HUNDRED_SITES`. For each, it makes the request against the seeded app and
    asserts: the status is in `range(400, 500)`; `body["error"]["code"]` equals the row's
    code; and `identifiers_in(body["error"]["message"], stored_identifiers(seeded)) == []`.
    The parametrisation ids name the site, so a failure says which one leaked.
32. `stored_identifiers(path)` gathers the group id, every member id, every user id and
    the id of every event `list_events` returns, and asserts each is at least eight
    characters. It reads the store directly and reads no response body.
33. Every row of `FOUR_HUNDRED_SITES` that carries `NO_REQUEST_REACHES_IT` carries a
    reason of at least thirty characters, and a test asserts that minimum, the way
    `tests/test_suite_integrity.py` asserts a minimum on an `# unanchored:` reason. The
    rows for `groups.GroupMismatch`, `groups.MemberAlreadyLinked`,
    `groups.UserAlreadyLinked`, `store.AmountTooLarge`, `balances.CurrencyMismatch` and
    `store.py`'s `RecordNotFound`/`DuplicateRecord`/`CurrencyMismatch` sites are among
    them, each reason naming what would have to be true for a request to reach it.
34. All twelve sites of the table above are **driven** rows, not marked rows. Each is
    reached by a request the test makes, which is the demonstration that the check covers
    the thing it was written for.
35. **The check catches a reintroduced leak, end to end.**
    `plans/mutations/61-identifiers-in-4xx-bodies.md` records at least three mutations in
    the `plans/mutations/README.md` format, one per source file, each restoring the
    interpolation this task removes, each with `find` and `replace` as exact source text,
    each listing the node ids it kills, and each with `result: "killed"`. One of them is
    `web.py::_create_expense`, restoring `: {payer_id!r}`, and its `kills` list includes
    the criterion-31 case for that site. Every run sets `PYTHONDONTWRITEBYTECODE=1` and
    reverts with `git checkout --` before the next.
36. `tests/test_error_messages.py` imports only the standard library, `pytest`, and the
    package. No new dependency, and `pyproject.toml` and `uv.lock` are byte-identical to
    `master`.

### A message reaching a person, end to end

37. **In front of a person, through the shipped shell.** `tests/shell_harness.mjs` gains
    one scenario, `a_save_refused_as_malformed_shows_the_servers_sentence_with_no_id`,
    which stubs `POST /api/expenses` with a 400 `malformed_request` whose message is the
    criterion-6 sentence, presses Save on the add screen, and asserts that
    `#add-error-server`'s `textContent` equals that sentence character for character and
    that the rendered screen contains no member id. This is the new sentence rendered by
    the shipped `app/app.js` and `app/api.js` into the shipped `app/index.html`, under
    Node, with nothing in between reformatting it. It also covers the code the PR #62
    reviewer flagged: `malformed_request` on the one screen that prints every sentence.
38. That scenario is declared in `tests/test_shell_behaviour.py`'s `SCENARIOS`, in the
    order the harness runs it, so `test_the_harness_reports_exactly_the_declared_scenarios`
    passes. A harness scenario costs exactly two files, always, per the amended criterion
    27 of `plans/tasks/39-split-refusals-in-the-money-that-was-typed.md`.
39. **The cross-language fixtures are pinned to their producer.** `tests/test_web_api.py`
    gains one shared extraction helper and three pins, each asserting that a constant
    declared in `tests/shell_harness.mjs` equals `body["error"]["message"]` from a live
    request made in the same test:
    * the criterion-37 scenario's new constant, against a `POST /api/expenses` naming a
      member id that is not in the roster;
    * `MALFORMED_DEBT`, against a `GET /api/debts/<stranger>/<member>`;
    * `MALFORMED_SETTLEMENT`, against a `POST /api/settlements` naming a
      `to_member_id` that is not in the roster.

    The helper tolerates the constant being declared on the same line as `const NAME =`
    or on the next, in single or double quotes, so one helper covers all three and the
    existing `ADD_SUM_REFUSED` pin's form. **This is the criterion that closes a live
    instance of `.claude/rules/testing.md` rule (d):** `MALFORMED_DEBT` and
    `MALFORMED_SETTLEMENT` are today both the stubbed response and the expected value,
    with nothing checking them against a live body, so without this the two scenarios
    that assert those sentences are absent from the screen would stay green while
    asserting the absence of a sentence the server no longer sends.
40. `MALFORMED_DEBT` becomes
    `a debt path names a debtor that is not a member of this group` and
    `MALFORMED_SETTLEMENT` becomes
    `a settlement body names a to_member_id that is not a member of this group`, and both
    comments above them are rewritten: the sentence is no longer withheld because it names
    a member id, it is withheld because this screen shows one sentence for all six kinds,
    and criterion 43 records that the reason has moved. The two scenarios that use them,
    `a_debt_whose_expenses_do_not_arrive_says_so_and_can_be_asked_again` and the
    settlement one at `shell_harness.mjs:5360`, keep their names, their bodies and their
    assertions.
41. **By hand, and recorded in the QA note.** Because none of the twelve is reachable from
    the shipped shell, the hand check is a request rather than a click-through.
    `uv run python scripts/serve.py --store <a scratch ledger>`, sign in through the
    browser, then from the same session issue a `POST /api/expenses` whose `payer_id` is
    not in the roster, carrying the CSRF header. Transcribe the body. It reads exactly
    `{"error": {"code": "malformed_request", "message": "an expense body names a payer_id that is not a member of this group"}}`
    modulo key order, and contains no id. QA also transcribes the criterion-37 scenario's
    rendered sentence from the harness output. QA records that the browser click-through
    variant is **not** available and why: it would need a member row deleted from the
    ledger by hand, since `setup_group.py apply` refuses to remove one.

### The existing tests, strengthened and never loosened

42. These pre-existing tests change. Every one of them keeps its subject, keeps its
    `expense_count` / `stored_settlements` assertion where it had one, and **gains** an
    assertion that no id is present. Five are renamed because their current names assert
    the defect; each rename is recorded in the PR body, and
    `tests/test_suite_integrity.py`'s duplicate check catches any collision.

    | test | today | must become |
    |---|---|---|
    | `test_web_api.py::test_a_payer_who_is_not_a_member_is_refused_by_name` | `assert "'a-stranger'" in message` | renamed `..._is_refused_without_naming_them`; asserts 400, `malformed_request`, `"payer_id" in message`, `"a-stranger" not in message` |
    | `test_web_api.py::test_a_split_naming_someone_outside_the_group_is_refused_by_name` (3 cases) | `assert "'a-stranger'" in message` | renamed `..._is_refused_without_naming_them`; keeps all three modes; asserts `"member id" in message`, `"a-stranger" not in message` |
    | `test_web_api.py::test_a_split_naming_a_member_twice_is_refused_by_the_resolver` | `assert "more than once" in message` | keeps its name and both assertions; **gains** `assert members["Sam"] not in message` |
    | `test_web_api.py::test_an_id_that_is_not_a_member_of_this_group_is_a_four_hundred_naming_it` (2 cases) | `assert stranger in message` | renamed `..._is_a_four_hundred_naming_the_position`; keeps both positions; asserts the position word is in the message, `stranger not in message`, and keeps `members["Sam"] not in message` |
    | `test_web_api.py::test_a_member_may_not_ask_what_they_owe_themselves` | `assert "themselves" in message` | keeps its name and that assertion; **gains** `assert members["Sam"] not in message` |
    | `test_web_api.py::test_a_settlement_to_somebody_outside_the_group_is_refused_by_name` | `assert "mem-nobody" in message` | renamed `..._is_refused_without_naming_them`; asserts `"to_member_id" in message`, `"mem-nobody" not in message` |
    | `test_web_api.py::test_a_settlement_to_yourself_is_refused_before_the_event_is_built` | no message assertion | keeps its name and its assertions; **gains** `assert members["Sam"] not in message` |
    | `test_split.py::test_split_equally_rejects_a_repeated_member` | `match=r"^member_ids names a member more than once"` | keeps its name and that anchored pattern **unchanged**; takes the `as raised` form and gains `assert ALI not in str(raised.value)` |
    | `test_split.py::test_split_by_weight_rejects_a_negative_weight` | bare `pytest.raises(InvalidSplit)` | gains `match=r"^every weight must be zero or positive$"` and `assert ALI not in str(raised.value)` |
    | `test_split.py::test_split_exact_rejects_a_negative_amount` | bare `pytest.raises(InvalidSplit)` | gains `match=r"^every amount must be zero or positive$"`, `assert ALI not in str(raised.value)` and `assert "100" not in str(raised.value)` |

    Nothing else in the suite is renamed, removed, reordered, skipped or xfailed, and no
    parameter list loses a case.
43. **The three stale premises in `app/app.js` are recorded, not edited.** The PR body
    quotes all three comments verbatim, by their constant name, and states that this task
    discharges the member-id half of each and not the rest:
    * `BALANCES_FAILED`: "the sentence this route composes for its own 400 names a member
      id, which this screen may never show as text";
    * `BALANCES_NOT_RECORDED`: "Every refusal this endpoint can produce names a member id,
      describes a body the person did not type, or describes a claim they cannot see from
      here";
    * `BALANCES_NOT_ANSWERED`: "Every refusal this endpoint can produce describes a body
      the person did not type, a settlement they cannot see from here, or a rule about who
      they are, and this screen renders no member id and no settlement id as visible
      text".

    The same three go in the follow-up issue of criterion 44, which is what edits them.
44. **Three issues are filed by this task, with their numbers in the PR body**, so nothing
    found here is left to a fifth reader:
    a. **The balances screen's three fixed sentences**, now that no 4xx carries an id:
    whether each region shows `error.say` and, if so, which of the remaining id-free
    sentences are good prose for a flatmate. Carries criterion 43's three quotes, and
    notes that it is the task that edits `app/app.js`, bumps `VERSION` and recomputes
    `SHELL_DIGEST`.
    b. **`split_by_weight` is a resolver capability with no product behind it.**
    `spec.md` locks three split rules and ships three modes; weight is a fourth and no
    screen offers it. Whether it and the `weight` wire mode are removed.
    c. **`store.AmountTooLarge` and `balances.CurrencyMismatch`** are 400s carrying raw
    cents and an event id respectively, both unreachable today. Records #39's leftover and
    the reason each is unreachable, so backlog 14 and 15 see it.
45. `plans/spec.md`, `plans/backlog.md`, `README.md`, `CLAUDE.md` and
    `.claude/rules/testing.md` are not edited. Nothing about what the product is, or how it
    is run, installed or tested, changes.

### The suite

46. The files changed by this task are exactly **ten**, and no other path in `src/`,
    `tests/`, `app/`, `scripts/` or `plans/` is touched:
    `src/splitwise_lite/split.py`, `src/splitwise_lite/web.py`,
    `src/splitwise_lite/groups.py`, `tests/test_split.py`, `tests/test_web_api.py`,
    `tests/test_shell_behaviour.py`, `tests/shell_harness.mjs`,
    `tests/test_error_messages.py` (new), `plans/mutations/61-identifiers-in-4xx-bodies.md`
    (new), and this spec if it needs correcting. Two files are created; none is deleted.
47. **Do not run the whole suite in one command.** `master` collects 2484, nothing skipped
    and nothing xfailed, and at that size under contention a single run exceeds the agent
    watchdog; it has killed nine agents in one day. Run it in chunks by module
    (`uv run python -m pytest tests/test_error_messages.py`, then `tests/test_split.py`,
    then `tests/test_web_api.py`, then `tests/test_shell_behaviour.py`,
    then `tests/test_suite_integrity.py`, then the rest), and let
    `.github/workflows/tests.yml` be the one place a full green run is claimed. The PR body
    links that run.
48. Across the chunked runs plus CI: **0 failed, 0 skipped, 0 xfailed.** The collected
    count is `2484 + N`, and the PR body states `N` **and reconciles it arithmetically**:
    the criterion-31 cases, the criterion-30 unit tests, criteria 28, 29, 32 and 33, the
    three criterion-39 pins, the one criterion-37 scenario, and **plus two for the new test
    module**, because `tests/test_suite_integrity.py` derives `TEST_SOURCES` from the
    filesystem and parametrises two checks over it. The ten rewritten tests of criterion 42
    are rewrites and add nothing except where a case count is stated as unchanged. Nothing
    is skipped or xfailed to reach it.
49. `node` 20 or later is on `PATH`, so the JavaScript half runs and is never skipped. The
    harness still imports only `node:vm`, `node:fs`, `node:path` and `node:url`.
50. `tests/test_suite_integrity.py` passes unedited: no test module defines a name twice,
    every new `pytest.raises(match=)` in this diff is anchored with `^` from the start, and
    the new mutation record parses and is complete. Every anchored pattern this task adds
    was checked against the message the guard really prints, not guessed.

---

## Out of scope

* **Anything under `app/`.** No file is edited, added or removed; `VERSION` is not bumped
  and `SHELL_DIGEST` is not recomputed. The three stale comments are recorded (criterion
  43) and fixed by the follow-up (criterion 44a), not here.
* **Whether the balances screen shows `error.say`.** Criterion 44a. It is a per-route
  design judgement across three regions and six kinds, and it is the change that costs
  `app/` bytes.
* **Removing `split_by_weight` or the `weight` wire mode.** Criterion 44b. Rows 2 and 5
  are fixed by rewording; deletion is an API decision with its own blast radius.
* **Any change to the error contract.** No new status, no new code, no new exception class,
  no new row in `ERROR_STATUS` or `ERROR_CODE`, no change to the JSON body shape. A
  reworded message is not a contract change; `web.py` says so itself.
* **Reclassifying the duplicate-member refusal as a `MalformedRequest`**, or adding a
  duplicate check to `_resolve_split`. Refused above, on four grounds.
* **Composing, prefixing, truncating or substituting a message in `web.py` or in
  `app/app.js`.** `_handle_error` keeps carrying `str(error)` for every non-500.
* **Formatting row 2's integer.** No `currency` on `_ordered_from_mapping`, no second
  display helper in `split.py`, no cents-only variant of `format_amount`. The integer is
  dropped, not rendered.
* **`groups.AmbiguousGroup` and `groups.NoGroupConfigured`.** 503, operator-facing, and
  deliberately id-bearing. Outside the rule by status.
* **`GroupMismatch`, `MemberAlreadyLinked` and `UserAlreadyLinked`.** Declared in the
  table with reasons, not edited: they are `setup_group.py`'s refusals, no HTTP request
  reaches them, and an operator at a terminal needs the ids.
* **`scripts/setup_group.py`'s own terminal output.** Not an HTTP body, and its reader
  needs the ids.
* **`store.AmountTooLarge` and `balances.CurrencyMismatch`.** Criterion 44c. Declared with
  reasons, not edited.
* **Email addresses.** `accounts.EmailAlreadyRegistered` names a normalised address at
  409. That is the person's own typed input, the sign-up screen shows it, and echoing typed
  input is `parse_amount`'s accepted precedent. Not an internal identifier and not in the
  check's identifier set.
* **500 messages.** `events.py`, `balances.py` and `simplify.py` carry cents and ids in
  unmapped exceptions, which become `_GENERIC_500_MESSAGE` with the real exception in the
  log. None reaches a person. Not edited, and not added to the error maps.
* **A count, an ordinal or a "which one" figure** in any of the twelve. Refused above: a
  count is a third figure to keep true, and an ordinal into a JSON object is an ordering
  claim the wire does not make.
* **Tidying.** No renaming of existing helpers beyond the two signature changes in
  criteria 7 and 8, no reordering of functions, no reflowing of untouched lines, no
  rewrite of the remainder rule or its docstring.
* **A static leak detector over `src/`.** Refused above: it cannot tell a payload key name
  from an id value without a denylist, and a denylist is the premise-outside-the-check
  shape issue #42 is about. The static half of the check is an enumeration equality only.
* **An autouse hook that inspects every 400 in the whole suite.** Considered and refused:
  it would couple every test's `app` fixture to this property, and a failure would point
  at whichever unrelated test happened to make the request. The table names its sites.
* **Multi-currency, partial settlements, member departure** and everything else `spec.md`
  cuts from v1.

---

## Constraints

* **Files edited: exactly ten**, per criterion 46. Two are new. Nothing else, in either
  direction.
* **The domain layer stays framework free.** `split.py` and `groups.py` import no web
  framework and no web-layer module, and the package imports with Flask absent. A test
  asserts it and it passes unedited. `MalformedRequest` cannot be raised from the domain
  layer and this task does not try.
* **Money is integer cents; `format_amount` is the only display edge.** No float, no
  `round`, no true division and no `Decimal` in this diff. `split.py`'s three AST tests
  pass unedited. Row 2's integer is dropped rather than divided, formatted or rendered
  anywhere.
* **No new dependency, in either language.** Nothing new in `pyproject.toml`,
  `uv.lock` byte-identical, the harness still importing four `node:` modules. Per
  `CLAUDE.md`, a dependency is declared then installed with `uv sync`, never
  `pip install` or `uv pip install`. If something here genuinely cannot be built without a
  package, stop and get the user's approval first.
* **The test command is exactly `uv run python -m pytest`.** Plain `uv run pytest` fails
  on this machine with an access-denied spawn error. **Run it in chunks**, per criterion
  47, and claim the full green run from CI. Do not ask anyone to run the whole suite
  locally.
* **Anchored pins from the start.** Every `pytest.raises(match=)` this task adds leads with
  `^` and spells enough of the message that no other exception the same call can raise
  would match, per `.claude/rules/testing.md` rule (a). Check the message a guard really
  prints before writing the pattern: `money.py` prefixes several `TypeError`s with a type
  name, which is how the #65 scar happened.
* **Check names before using them.** Every test name this task adds is grepped for first,
  and `tests/test_suite_integrity.py`'s duplicate check is run over `tests/` before the PR
  goes up.
* **A mutation claimed as evidence is recorded as an anchor and a replacement**, in
  `plans/mutations/61-identifiers-in-4xx-bodies.md`, in the README's seven-key format,
  never as a sentence. Every run sets `PYTHONDONTWRITEBYTECODE=1`. Per rule (e).
* **Existing tests are not loosened.** Only the ten in criterion 42 change, every one of
  them keeps its subject and gains a negative assertion, and the five renames are only of
  names that assert the defect. Nothing is deleted, reordered, skipped or xfailed.
* **Punctuation matches the family:** lower-case opening, no trailing full stop. `app/app.js`
  adds none, so the punctuation is the server's to get right.
* **Python 3.12 target.** A docstring on every new function, and a one-line comment where a
  non-obvious choice is implemented, so the next person does not undo it by tidying: why
  `_require_weight` and `_require_exact_amount` no longer take the key, why row 2's integer
  is dropped rather than formatted, and why the enumeration half of the check is an
  equality rather than a scan.
* **No test binds a socket.** Every driven row of `FOUR_HUNDRED_SITES` goes through Flask's
  test client. The criterion-41 hand check is QA's and is not automated.

---

## Size

Small in `src/`: twelve message edits, two private signatures each losing one parameter,
two call sites losing one argument each, and one loop gaining a position. Perhaps thirty
lines replaced across three files, none of them adding a function.

The bulk is `tests/test_error_messages.py`, which is one table of about twenty rows, one
`ast` walk, one pure function, and five tests over them. Then ten strengthened tests, one
harness scenario with its `SCENARIOS` row, three cross-language pins behind one shared
helper, two harness constants, and one mutation record.

If this task grows a new module in `src/`, a new exception class, a new error code, a
second display helper, an edit under `app/`, an allowlist inside the check, or a
`try`/`except` around anything in `web.py`, it has gone wrong.
