# Task 51: route registration carries its access policy

**Depends on:** 9a (complete, on `master`), 12a (complete, on `master`)
**Consumed by:** every later task that adds an endpoint, which today means issues #15, #17
and #18

Closes GitHub issue #51. `plans/backlog.md` has no entry for this and this task does not
add one; the issue is the backlog entry and this file is the implementable version.

## Why this task exists

`_before_request` in `src/splitwise_lite/web.py` decides what a request has to prove by
looking its endpoint up in `_API_ENDPOINTS`, a hand-written literal set, and **returning
early when it is absent**:

```python
endpoint = flask.request.endpoint
if endpoint is None or endpoint not in _API_ENDPOINTS:
    return
```

So a route registered without an entry in that set gets no CSRF gate, no session check and
no member check, and nothing anywhere says so. The failure is not a refusal, it is silence.
The default is open, on the one module that decides who may read a group's money.

It has not bitten. Two existing tests catch it in combination:
`test_the_endpoint_table_names_every_route_the_app_serves` compares `ENDPOINT_ROWS` against
`app.url_map` and forces a row for any new `/api` rule, and
`test_every_endpoint_refuses_an_unauthenticated_caller` then drives that row and expects a
401. PR #50 registered `read_debt` correctly, and
`test_the_debt_endpoint_is_in_the_api_endpoint_set_so_the_hooks_run` was written precisely
because the reviewer knew the trap was there.

That is the problem. Three reviewers on three tasks have flagged it, and
`plans/tasks/12a-transfer-provenance-api.md` had to carry two separate criteria and a
constraint spelling out "add it to `_API_ENDPOINTS`, and to neither exemption tuple",
because the mechanism could not say it. A constraint that must be re-explained to every
implementer is a constraint in the wrong place. It is also guarded only by a suite somebody
has to remember to run, which is the compounding risk in the "Related" section below.

## The decision, and why

**A route is declared in a table with its access policy, `create_app` refuses to build an
app whose `url_map` holds anything the tables do not declare, and `_before_request` refuses
at request time any `/api` rule it does not recognise.**

That is the issue's first option with its hole closed, plus its second option kept as a
second line, plus its third option kept as a test. All three, because each one alone leaves
something open, and the combination costs under a hundred lines confined to two regions of
one file.

### Why the registration helper alone is not enough

"A helper that cannot register a route without stating its policy" only binds the people
who call the helper. `app.add_url_rule` is still there, still public, still one line, and
still the thing every Flask example on the internet shows. A helper is a convention with a
signature, and this repo has already watched a convention fail twice: see
`plans/tasks/46-shell-precache-digest.md` on `VERSION`.

What makes the declaration binding is not the helper, it is the **audit**: at the end of
`create_app`, every rule in `app.url_map` is compared against what the tables declare, and a
mismatch raises. Then it does not matter how a route got registered. Bypassing the table
does not buy a silent endpoint, it buys an application that will not start.

### Why inverting the default alone is not enough

Inverting the default in `_before_request` is genuinely cheap and genuinely better: a
forgotten route becomes a logged 500 instead of an open endpoint. But it fires only when
somebody sends a request to that exact path. A route can ship, sit in the route table, and
never be probed by the suite or by a person until the day it is. And it does nothing about
the thing that keeps costing reviewer time: the policy for an endpoint still lives in three
separate literals that the route table cannot see.

It is kept, as the second line, for the case the audit cannot see: a route registered after
`create_app` has returned.

### Why the exhaustive test alone is not enough

A test that walks `app.url_map` and asserts every `/api` rule is declared is exactly the
right assertion in exactly the wrong place. It runs when somebody runs the suite. Issue #49
is open because nothing runs the suite automatically. A guard that lives inside `create_app`
runs in every process that ever serves this app: the suite, `scripts/serve.py`, and
whatever eventually runs it for real. Same assertion, one line of code away from the thing
it protects, and no dependence on anybody's memory or on CI existing.

It is kept as well, as a test, because a red test names the failure where the fix is read.

### Why a table of rows and not a decorator on each view

A `@api_route("/api/members", access=MEMBER)` decorator on each view is the other shape of
"registration carries the policy". It is rejected here for two reasons. It couples module
import to route registration, so importing `web.py` builds a global registry, and this
module is careful that two apps in one process share no state. And it scatters the route
table across nine hundred lines of view functions, when the value of a table is that one
screen shows every route and what each requires, which is what a reviewer needs to see.

### What this deliberately does not catch, recorded rather than hidden

* A route registered **after** `create_app` returns, at a rule that is **not under** the
  `/api` path segment, is still ungated. The runtime check can only classify by the rule it
  matched, and the audit has already run. Every API route lives under `/api` by construction
  (a row is refused if its rule does not), so reaching this needs somebody to register an
  API route outside the factory and outside the prefix.

  *Restated while implementing.* This first read "at a rule that does not start with `/api`",
  which was the string test the code then made. `/api` is a path segment in all three guards
  now, so `/apiary` is outside the prefix as well, and a rule of that shape registered after
  the factory falls in this same recorded gap rather than being refused as an API rule. The
  gap is the same one; this sentence says where its edge is.
* The three policies are the three that exist today. This mechanism makes the policy for a
  route impossible to forget; it does not invent finer-grained authorisation, and
  membership of the group remains the only authorisation this product has.

## Related

Issue **#49**, no CI, is in review now. These compound: a trap whose only guard is a test,
and a test whose only guard is somebody remembering to run it. Moving the guard into
`create_app` shrinks that overlap, because the guard now runs whenever the app runs rather
than whenever the suite runs. It does not remove it: the tests in this task still need
running. **This task adds no CI, no workflow file and nothing under `.github/`**, and it
does not wait on #49.

## Goal

The access policy of every route is stated where the route is registered and nowhere else,
so an endpoint that does not say what it requires cannot be served: `create_app` refuses to
return an application whose route map holds anything the tables do not declare, and a
`/api` rule that reaches `_before_request` without a declared policy is refused rather than
waved through. The distinction the exemption tuples encode, that signup, sign-in and
sign-out need no session and the session read needs no member row, survives intact as three
named levels, and no request that works today answers differently.

## Acceptance criteria

Each is a yes or no a QA agent can reach by reading a file or running a command. `REPO` is
the worktree root. Every path is relative to it.

### The vocabulary

1. `src/splitwise_lite/web.py` defines `_Access`, an `enum.Enum` with exactly three members,
   `ANONYMOUS`, `SESSION` and `MEMBER`, in that order, each with a value equal to its own
   name, following `SettlementState`'s precedent in `events.py`.
   `[m.name for m in web._Access] == ["ANONYMOUS", "SESSION", "MEMBER"]` and
   `all(m.value == m.name for m in web._Access)`.
2. The class docstring states what each level requires and that `MEMBER` is the level a new
   endpoint gets unless somebody argues otherwise: `ANONYMOUS` needs no session at all,
   `SESSION` needs a valid session and no member row, `MEMBER` needs both a valid session
   and a linked member row in the group. It states that `ANONYMOUS` exists for signup,
   sign-in and sign-out, which cannot require a session they are there to create or destroy,
   and `SESSION` exists for `read_session` alone, so the shell can render "you are signed
   in, ask whoever set the flat up to link you".
3. `_ApiRoute` is a `frozen=True, slots=True` dataclass holding exactly `rule`, `endpoint`,
   `view`, `methods` and `access`, in that order, and **none of the five has a default
   value**. `_ApiRoute("/api/x", "x", some_view, ("GET",))` raises `TypeError`. This is the
   heart of the task: a row that does not state its policy is not a row.
4. `_ApiRoute.__post_init__` refuses, eagerly, in the style of `_Settings.__post_init__`: a
   `rule` that is not a `str` starting with `_API_PREFIX`, an `endpoint` that is not a
   non-empty `str`, a `methods` that is not a non-empty `tuple` of upper-case `str`, and an
   `access` that is not an `_Access`. Each message names the offending field and the value
   it got. Type errors raise `TypeError`, value errors raise `ValueError`.
5. `_API_PREFIX` is a module constant equal to `"/api"`, and it is the only place that
   string is spelled in a decision. Every classification of "is this an API rule", in the
   audit and at request time, compares against it.

### The route table

6. `_API_ROUTES` is a module-level `Final[tuple[_ApiRoute, ...]]` holding exactly these nine
   rows, in this order, which is the order the routes are registered in today:

   | rule | endpoint | methods | access |
   |---|---|---|---|
   | `/api/signup` | `signup` | `("POST",)` | `ANONYMOUS` |
   | `/api/session` | `create_session` | `("POST",)` | `ANONYMOUS` |
   | `/api/session` | `read_session` | `("GET",)` | `SESSION` |
   | `/api/session` | `delete_session` | `("DELETE",)` | `ANONYMOUS` |
   | `/api/members` | `list_members` | `("GET",)` | `MEMBER` |
   | `/api/expenses` | `list_expenses` | `("GET",)` | `MEMBER` |
   | `/api/expenses` | `create_expense` | `("POST",)` | `MEMBER` |
   | `/api/balances` | `read_balances` | `("GET",)` | `MEMBER` |
   | `/api/debts/<debtor_id>/<creditor_id>` | `read_debt` | `("GET",)` | `MEMBER` |

   Three rows share the rule `/api/session` and differ by endpoint and method. That is not
   an edge case to work around; it is what the table has to be able to express.
7. `_SHELL_ROUTES` is a module-level `Final[tuple[...]]` declaring the two routes that are
   deliberately not API routes and deliberately ungated:
   `("/", "shell_document", _shell_document, ("GET",))` and
   `("/<path:filename>", "static_path", _static_path, ("GET",))`. Each row is
   `(rule, endpoint, view, methods)`, mirroring `_ApiRoute`'s fields without `access`. Its
   docstring says these serve files only, that `_static_file` refuses anything outside the
   app directory, and that a route added here is a route with no session check, which is
   why it is a declaration and not an omission.

   *Corrected while implementing.* As first written this criterion listed each row as the
   triple `(rule, endpoint, methods)`, with no view, which contradicts criterion 10: a loop
   over this table cannot call `add_url_rule` for a row that does not name a view, and the
   constraints fix the set of new names, so there is nothing to look one up with. The rule,
   endpoint and methods are unchanged from the original wording; the view is the only
   addition.
8. `_access_map(routes)` is a module-level function returning the `endpoint -> _Access`
   mapping for a tuple of rows, and it raises `ValueError` naming the endpoint when two rows
   share an endpoint name. `_API_ACCESS` is `_access_map(_API_ROUTES)` and is `Final`.
   Nothing writes to it after import.
9. `_API_ENDPOINTS`, `_ANONYMOUS_ENDPOINTS` and `_MEMBER_OPTIONAL_ENDPOINTS` no longer
   exist. `grep -n "_API_ENDPOINTS\|_ANONYMOUS_ENDPOINTS\|_MEMBER_OPTIONAL_ENDPOINTS"` over
   `src/` and `tests/` returns nothing. They are not kept as values derived from the table:
   a constant that nothing reads is the next version of this same trap, and the next person
   to edit one would be editing something with no effect.
10. `create_app` registers every route by iterating `_API_ROUTES` and then `_SHELL_ROUTES`.
    The literal `add_url_rule` appears in `web.py` exactly twice, once inside each loop, and
    no route is registered anywhere else in the package.

### The audit at construction

11. `_audit_routes(app)` compares what the app actually serves against what the tables
    declare. The comparison key is
    `(rule.rule, rule.endpoint, frozenset(rule.methods) - {"HEAD", "OPTIONS"})`, mirroring
    `test_the_endpoint_table_names_every_route_the_app_serves`, and the two sets must be
    equal. It covers **every** rule in `app.url_map`, not only those under `/api`.
12. `create_app` calls `_audit_routes(app)` as its last act, after every hook and error
    handler is registered, and returns the app only if it passes. A failing audit means
    `create_app` raises and no application object escapes.
13. The exception is `_RouteNotDeclared`, a subclass of `RuntimeError`. It is **not** a
    `WebError` and **not** a `DomainError`. Consequently `ERROR_STATUS`, `ERROR_CODE`,
    `ERROR_ROWS` and `DELIBERATELY_UNMAPPED` are all unchanged and
    `test_no_domain_error_becomes_a_five_hundred_without_this_test_seeing_it` and
    `test_the_two_tables_are_keyed_the_same_way_and_hold_exactly_these_rows` pass unedited.
    A one line comment at the class says why it is not part of the `DomainError` family: it
    is a programming error in this repo, not a refusal of a request, and giving it a code
    would put it in a contract clients branch on.
14. Its message, for a route the app serves and the tables do not declare, contains, as
    readable prose rather than a set-difference dump: the offending rule and endpoint; the
    sentence that a route reaches no session check, no CSRF check and no member check until
    it is declared; the path `src/splitwise_lite/web.py`; the name `_API_ROUTES`; the three
    policy names with one clause each on what they mean; and the alternative, that a route
    which is genuinely not part of the API goes in `_SHELL_ROUTES` and is then served with
    no session check at all. Somebody who has never read this file can act on it without
    opening anything else. QA reads this message while performing criterion 29.
15. Its message, for a route the tables declare and the app does not serve, says that
    instead, and names the row. The audit is an equality in both directions, so a table that
    claims a route nobody registered is also a failure.
16. A test builds the shipped app through `create_app`, then calls
    `app.add_url_rule("/api/probe", "probe", view, methods=["GET"])`, then calls
    `web._audit_routes(app)`, and asserts `_RouteNotDeclared` is raised with a message
    containing `/api/probe`, `_API_ROUTES` and `src/splitwise_lite/web.py`.
17. A second test does the same with the rule `/probe`, outside the `/api` prefix, and
    asserts it is refused too. The audit is not `/api` only, so an API route registered at
    some other prefix cannot slip past it at construction.
18. A third test calls `_audit_routes` on a bare `flask.Flask` that is missing one declared
    rule, and asserts `_RouteNotDeclared` naming that row, covering criterion 15.
19. A fourth test calls `_access_map` with two hand-made rows sharing one endpoint name and
    asserts `ValueError` naming it.
20. A fifth test walks the shipped `app.url_map` and asserts every rule starting with
    `_API_PREFIX` has an endpoint present in `_API_ACCESS`. This is the issue's third option
    kept deliberately, because a red test names the failure in the file where the fix is
    read, and it costs four lines.

### The runtime default, which is now closed

21. `_before_request` classifies from `flask.request.url_rule`, never from
    `flask.request.path`, in this order:
    * `flask.request.endpoint is None` or `flask.request.url_rule is None`: return, so an
      unrouted request is still the 404 or 405 it is today and never a CSRF refusal;
    * the endpoint is in `_API_ACCESS`: gate it, as below;
    * the endpoint is not in `_API_ACCESS` and the matched rule starts with `_API_PREFIX`:
      raise `_RouteNotDeclared` **before any other gate runs**;
    * otherwise: return, which is the two declared shell routes and nothing else.
22. The gating itself keeps today's order and today's meaning exactly: CSRF for any method
    in `_STATE_CHANGING_METHODS` first, applied to every API endpoint with no per-endpoint
    exemption including the three `ANONYMOUS` ones; then return for `ANONYMOUS`; then
    `flask.g.session = _authenticate()`; then return for `SESSION`; then
    `flask.g.group = _acting_group()` and `flask.g.member = _acting_member()` for `MEMBER`.
    Authentication is still checked before group resolution.
23. A request to an undeclared `/api` rule is answered `500` with the body
    `{"error": {"code": "internal_error", "message": <_GENERIC_500_MESSAGE>}}`, and the real
    exception reaches the log with its traceback through the existing `_handle_error` path.
    No new status, no new code, no new row in either error map. Nothing from the rule or the
    endpoint name appears in the response body.
24. A test registers a route on an app that `create_app` already returned, with a view that
    would answer `200` with the body `{"leaked": "roster"}`, sends an anonymous `GET` to it,
    and asserts: the status is `500`, the code is `internal_error`, the string `leaked` does
    not appear anywhere in the response body, and `caplog` holds the traceback. This is the
    criterion that proves the second line exists, and it must fail if the
    `_before_request` branch is deleted.
25. A test asserts the classification is by rule and not by path, by entering a request
    context for `/api/nope` and asserting `flask.request.url_rule.rule == "/<path:filename>"`
    while `flask.request.path.startswith("/api")` is true. The naive implementation, which
    tests the path, turns every unknown `/api` path into a 500.
26. Consequently, and asserted by the existing tests passing unedited: `GET /api/nope` is
    still `404` `not_found` in the one JSON shape
    (`test_an_unknown_api_path_is_json_and_not_the_shell`), `PUT /api/session` is still
    `405` with its `Allow` header (`test_a_method_not_allowed_names_the_methods_that_are`),
    `/api/debts//x` and `/api/debts/x/` are still `404`
    (`test_an_empty_path_segment_matches_no_route`), and `/static/anything` is still `404`
    with no `static` endpoint (`test_there_is_no_static_route`).

### The behaviour that must not move

27. Every row of `ENDPOINT_ROWS` and every row of `UNLINKED_ROWS` produces the same status
    it produces today, and both parameterised tests pass with their tables unedited. So do
    `test_authentication_is_checked_before_the_group_is_resolved`,
    `test_a_signed_in_user_against_an_unconfigured_store_is_told_to_run_setup`,
    `test_two_apps_share_no_rate_limiter` and every CSRF, cookie, rate limit, error contract,
    static file, expense, balances and debt test in `tests/test_web_api.py`.
28. `git diff` on `src/splitwise_lite/web.py` touches five regions and no others: the import
    block, the module docstring, the constants region where `_ANONYMOUS_ENDPOINTS` and
    `_MEMBER_OPTIONAL_ENDPOINTS` live today, the region around `_API_ENDPOINTS` and
    `create_app`, and `_before_request`. No view function, no error map, no cookie helper, no
    CSRF gate, no rate limiter, no store helper and no `__all__` entry is edited. `__all__`
    is byte-identical.

    *Corrected while implementing.* As first written this criterion said `git diff` "touches
    four regions and no others", and its list began at "the module docstring". The import
    block is a fifth, and it is an edit this spec requires by name elsewhere: criterion 36
    and the constraints both mandate `import enum`, which can go nowhere else. The
    enumeration omitted the edit its own neighbour orders. Only the count and that one
    entry change; the four regions originally listed, everything the criterion forbids and
    the `__all__` requirement are unchanged.

### The demonstration that the mechanism bites

29. **A route registered without a policy is refused.** QA performs this and records the
    output in the QA note.
    a. On a clean tree, `uv run python -m pytest` reports 0 failed, 0 skipped, 0 xfailed.
       Record the passed count.
    b. Add to `web.py`, temporarily, a view and a registration that a real task might write:

       ```python
       def _probe() -> flask.Response:
           group = _acting_group()
           members = _store().list_members(group.id)
           return _json_response(
               {"members": [member.display_name for member in members]}, 200
           )
       ```

       and, inside `create_app` immediately before the audit call,
       `app.add_url_rule("/api/probe", "probe", _probe, methods=["GET"])`.
    c. `uv run python -m pytest` is red. At least one failure carries the
       `_RouteNotDeclared` message, and that message satisfies criterion 14 verbatim. Record
       it in full.
    d. `uv run python scripts/serve.py --store ledger.sqlite3` exits with that same message,
       binds no port, and `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/`
       fails to connect.
    e. Remove both edits. `uv run python -m pytest` reports 0 failed, 0 skipped, 0 xfailed
       with the same passed count as (a), the server starts, and
       `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/balances` with no
       cookies is `401`.
30. **The same probe on `master` serves the flat's roster to a stranger.** QA repeats step
    29b on a checkout of `master` (before this task), starts the server, and runs
    `curl http://localhost:8000/api/probe` with no cookies and no CSRF header. It answers
    `200` with the group's member names. QA records the body. On `master` the suite is also
    red at step (c), with exactly one failure,
    `test_the_endpoint_table_names_every_route_the_app_serves`, whose message is a set
    inequality; QA records that message too, next to the new one. That pair is the whole
    before-and-after: today the server serves it and a set-difference in one test is the
    only thing that objects, after this task the server will not start.

### The documents

31. The module docstring of `web.py` gains one paragraph in the existing bold-lead style,
    placed next to the CSRF and member-link paragraphs, opening with
    `**A route is registered with its access policy or not at all.**` It states that every
    route lives in `_API_ROUTES` or `_SHELL_ROUTES`, that a row cannot be written without an
    `_Access`, that `create_app` refuses to return an app serving anything the tables do not
    declare, that a `/api` rule with no declared policy is refused at request time rather
    than waved through, and that `MEMBER` is what a new endpoint gets unless somebody argues
    otherwise.
32. `test_the_module_docstring_records_every_decision_it_makes` gains one string to its
    list, `"A route is registered with its access policy"`. Nothing is removed from that
    list.
33. `CLAUDE.md`'s `src/splitwise_lite/web.py` bullet under "Where things live" gains a
    clause: routes are declared in `_API_ROUTES` with the access each one requires, and an
    app whose route map holds anything the tables do not declare fails to build. One
    sentence, inside the existing bullet. The `no build step` paragraph is untouched, so
    `test_the_no_build_step_claim_carries_its_caveat_where_it_is_made` passes unedited, and
    no other document is edited.

### The two tests that change shape, and nothing else

34. `test_the_member_requirement_is_the_default_and_the_exemptions_are_named` is replaced by
    a test of the same name that asserts all three partitions exactly, by value:
    `{e for e, a in web._API_ACCESS.items() if a is web._Access.ANONYMOUS}` equals
    `{"signup", "create_session", "delete_session"}`; the `SESSION` set equals
    `{"read_session"}`; the `MEMBER` set equals
    `{"list_members", "list_expenses", "create_expense", "read_balances", "read_debt"}`; and
    `set(web._API_ACCESS)` equals the union of the three and equals
    `{row.endpoint for row in web._API_ROUTES}`. It asserts strictly more than the test it
    replaces, which pinned one four-tuple and one subset relation. It changes because the
    tuples it named no longer exist, and it must not be rewritten to compare against a
    derived alias of them.
35. `test_the_debt_endpoint_is_in_the_api_endpoint_set_so_the_hooks_run` is replaced by a
    test of the same name asserting `web._API_ACCESS["read_debt"] is web._Access.MEMBER`,
    keeping its existing request assertions verbatim: `GET /api/debts/whoever/somebody-else`
    with no cookies is `401` with code `not_authenticated`. It asserts strictly more, because
    naming the level is stronger than absence from two tuples.
36. `test_the_module_imports_flask_and_the_standard_library_only` gains exactly one name,
    `"enum"`, to its set. It remains an exact equality against a literal set; nothing else in
    it changes.
37. No other test anywhere in `tests/` is edited, renamed, deleted, reordered, loosened or
    parameterised differently. `git diff --stat` over `tests/` shows one file,
    `tests/test_web_api.py`, and its diff contains only the four edits to existing tests
    this spec requires, plus new tests appended at the end of their section.

    *Corrected while implementing.* As first written this said the diff "contains only the
    three changes above", counting criteria 34, 35 and 36. There is a fourth, mandated by
    name in criterion 32: `test_the_module_docstring_records_every_decision_it_makes` gains
    one string. "Three" contradicted it, so the count is the correction and nothing else is.
    Two tests change shape, 34 and 35; two exact literals gain one entry each, 32 and 36;
    and nothing anywhere is removed, renamed, reordered or loosened.

### The suite

38. `uv run python -m pytest` passes with 0 failed, 0 skipped and 0 xfailed. The passed count
    is 2172 plus the number of tests this task adds; the two replacements are replacements
    and add nothing. QA records the exact number.
39. No file under `app/` is touched. `git diff --stat` shows no path beginning `app/`, and
    `VERSION` in `app/sw.js` is unchanged.
40. `pyproject.toml` and `uv.lock` are byte-identical to `master`. No new dependency, in
    either language.
41. The files changed by this task are exactly four:
    `src/splitwise_lite/web.py`, `tests/test_web_api.py`, `CLAUDE.md`, and this spec if it
    needs correcting. No file is created or deleted anywhere in `src/`, `tests/`, `app/` or
    `scripts/`.

## Out of scope

* **Anything under `app/`.** This is a back-end change. No file in `app/` is read, edited,
  added or removed, and `VERSION` in `app/sw.js` is not bumped, because the precache list
  and the shell bytes are unchanged.
* **Any change to the error contract.** No new status, no new code, no new row in
  `ERROR_STATUS` or `ERROR_CODE`, no new entry in `DELIBERATELY_UNMAPPED`, no change to the
  one JSON body shape, and no new member of the `DomainError` family. `_RouteNotDeclared` is
  a `RuntimeError` precisely so none of that moves.
* **Adding, removing, renaming or re-pathing any endpoint**, changing any method, request
  body, response payload, key spelling or status any endpoint answers today. The nine rows
  in criterion 6 are the nine routes that already exist.
* **Changing what a policy means.** No new level, no per-endpoint CSRF exemption, no scopes,
  no roles, no permissions, no "only the two members involved" rule, no per-group
  authorisation. Membership of the group remains the only authorisation this product has.
* **A decorator form.** `@api_route(...)` on the view functions is the rejected alternative
  above. Do not build both.
* **Blueprints, a router module, a second HTTP module, or moving the views out of
  `web.py`.** `test_there_is_no_second_http_module_and_no_web_package` stays true.
* **Cookies, CSRF token issuance and rotation, the security headers, the Content Security
  Policy, rate limiting, the store lifecycle and the clock.** None of them is read or edited
  by this task.
* **CI, a GitHub workflow, a pre-commit hook or anything that runs the suite for you.** That
  is issue #49 and this task neither does it nor waits for it.
* **Static analysis.** No mypy configuration, no linter, no type-checking gate, and no
  runtime assertion added anywhere other than the two named guards.
* **Tidying `web.py`.** No renaming of existing private helpers, no reordering of existing
  functions, no docstring rewrites beyond the one new paragraph, no reformatting of untouched
  lines. The diff is reviewed by three queued tasks that have to merge on top of it.
* **Editing any file under `plans/tasks/` other than this one.**
  `plans/tasks/12a-transfer-provenance-api.md` names `_API_ENDPOINTS` in two criteria and one
  constraint; that task is complete and on `master`, its wording is superseded by this file,
  and it is not edited.
* **`plans/backlog.md`, `plans/spec.md` and `README.md`.** Nothing about what the product is,
  how it is run, installed or tested changes here. `CLAUDE.md` gains one sentence and that is
  the whole of the documentation change.

## Constraints

* **Files edited: exactly four.** `src/splitwise_lite/web.py`, `tests/test_web_api.py`,
  `CLAUDE.md`, and this file if it needs correcting. Nothing else, in either direction.
* **No new dependency of any kind.** `enum` is the standard library and is the only new
  import. `pyproject.toml` is not opened, `uv sync` is not needed, and
  `.claude/hooks/guard-deps.hs.sh` blocks the ad hoc route anyway. Per `CLAUDE.md`, a
  dependency is declared and then installed with `uv sync`, never `pip install` or
  `uv pip install`. If something here genuinely cannot be built without a package, stop and
  get the user's approval first.
* **Flask stays confined to `web.py`.** The domain layer still imports with Flask absent, and
  `test_importing_the_package_does_not_import_the_framework`,
  `test_the_package_root_does_not_re_export_the_http_layer` and
  `test_no_module_in_the_package_imports_the_web_layer` pass untouched. Nothing about routing
  leaks into any other module.
* **Every new name in `web.py` is underscore-prefixed**, so `web.__all__` is unchanged and
  `test_the_public_surface_is_exactly_the_named_names` and
  `test_everything_else_the_module_defines_is_underscored` pass unedited. The new names are
  `_Access`, `_ApiRoute`, `_API_PREFIX`, `_API_ROUTES`, `_SHELL_ROUTES`, `_access_map`,
  `_API_ACCESS`, `_RouteNotDeclared` and `_audit_routes`, and nothing else.
* **Nothing mutable is added at module level.** `_API_ROUTES` and `_SHELL_ROUTES` are tuples
  of frozen dataclasses, `_API_ACCESS` is built once at import and never written to, and no
  per-app state moves into a module global. Two apps in one process still share nothing that
  one can exhaust through the other.
* **Python 3.12 target**, `frozen=True, slots=True` on the new dataclass, eager validation in
  `__post_init__` in the style `_Settings` already uses, and a docstring on every new name
  stating the invariant it enforces.
* **A one line comment where each non-obvious choice is implemented**, so the next person
  does not undo it by tidying: why the classification reads `url_rule` and not `path`; why
  the refusal is a `RuntimeError` and not a `WebError`; why the audit lives in `create_app`
  rather than only in a test; why `_ApiRoute.access` has no default value; why the shell
  routes are declared rather than merely absent; and why the old tuples are deleted rather
  than derived.
* **The exemption distinction is preserved by name, not by omission.** `ANONYMOUS` and
  `SESSION` are declared per route in the same place as everything else about that route, and
  the module docstring keeps saying why each of the four session and signup endpoints is
  where it is.
* **Existing tests are not loosened.** The only pre-existing tests that change are the three
  named in criteria 34, 35 and 36: two replacements that assert strictly more, and one exact
  set that gains one standard library name. Everything else passes unedited.
* Tests run with `uv run python -m pytest`. Plain `uv run pytest` fails on this machine with
  an access-denied spawn error. No test is skipped or marked xfail, and assertions are exact,
  per `.claude/rules/testing.md`.
* No test binds a socket. The demonstrations in criteria 29 and 30 are run by hand, by QA,
  and are not automated.

## Size

Small on purpose, because three queued tasks have to merge on top of it. In `web.py`:
roughly seventy lines added (the enum, the row type, the two tables, `_access_map`, the
exception, `_audit_routes`, the docstring paragraph) and roughly thirty removed (the three
literals and the eleven `add_url_rule` calls, which become two loops). `_before_request`
grows by about four lines and keeps its shape. Nine new tests plus two rewrites in
`tests/test_web_api.py`, one sentence in `CLAUDE.md`.

The nine new tests:

1. `_Access` has exactly three members whose values are their names (criterion 1);
2. a route row cannot be built without an access policy, and its `__post_init__` refusals,
   parameterised (criteria 3 and 4);
3. `_API_ROUTES` holds exactly the nine declared rows (criterion 6);
4. every `/api` rule the app serves has a declared policy (criterion 20);
5. an `/api` route added to a built app is refused by the audit, with the message
   (criterion 16);
6. a non-`/api` route added to a built app is refused by the audit too (criterion 17);
7. a declared row the app does not serve is refused (criterion 18);
8. two rows sharing an endpoint name are refused by `_access_map` (criterion 19);
9. a route registered after construction is refused at request time, leaks nothing, and is
   logged (criterion 24), with the `url_rule` classification assertion of criterion 25
   alongside it.

If this task grows a new module, a registry built at import, a decorator, a second
`before_request` hook or a change to any view, it has gone wrong.

## Notes for the queued `web.py` tasks (#15, #17, #18)

Adding an endpoint after this lands is **one** edit rather than two remembered ones: append
a row to `_API_ROUTES` naming its rule, endpoint, view, methods and `_Access`. There is no
second literal to update and no exemption tuple to remember, and forgetting is not a
possible state, because the app will not build. The two test tables, `ENDPOINT_ROWS` and
`UNLINKED_ROWS`, are unchanged in shape and still need their rows.

Any branch cut before this lands that adds a route will conflict in two places, the
registration block in `create_app` and the `_API_ENDPOINTS` literal. The resolution is
mechanical: delete the `add_url_rule` call and the `_API_ENDPOINTS` entry, and write one
row. It is worth landing this before those tasks start rather than after, because the
conflict is smaller than the review time already spent explaining the trap to each of them
in turn.
