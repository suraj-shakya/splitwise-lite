# Mutations behind the sign-in gate's re-raise (issue #88)

Four mutations, all applied through the harness's own `substitutions` list, which is why
no `PYTHONDONTWRITEBYTECODE` guard applies to any of them: the JavaScript harness
substitutes into source text at run time and caches nothing. Run each with
`node tests/shell_harness.mjs < config.json`, where the config is one block below
wrapped as `{"substitutions": [ ... ]}`, and nothing on disk is touched.

Taken on 2026-09-08, on branch `task-88`. A record quotes a measurement, so it carries
the tree it was measured on: if an anchor below no longer matches exactly once, that is
the tree to diff against rather than a defect in the record. Every anchor was verified to
match exactly once in `app/app.js` before every run.

Every **before**-run below is against `87b7b7f`, which is `app/app.js` as it ships on
master. Every **after**-run is against this branch's changed `app/app.js`. Each
replacement is one line standing in for one line, so a stack's line number is the
committed file's own: `app/app.js:1501` is `        return refresh();` on this branch and
`app/app.js:1533` is the `.catch` body's write to `#gate-error`, both verified by grep
after the last run rather than assumed.

**Every `find` here is one line.** `MUTANT_F`, `MUTANT_H` and `MUTANT_I` in
`tests/test_shell_behaviour.py` each record that a multi-line anchor rots on a CRLF
checkout, and this working tree is CRLF.

**One anchor cannot carry two replacements**, because `readSource` in
`tests/shell_harness.mjs` refuses an anchor that does not match exactly once and the
first replacement consumes it. That is a limit on one anchor and **not** a limit on one
config: a change with a different anchor rides in the same `substitutions` list, which
is how the positive control below is one run rather than a hand edit. Two blocks that
share an anchor, `j1` and `j2` here, are the ones that cannot be combined.

**Nothing here is duplicated into `tests/test_shell_behaviour.py`.** A mutation gets two
homes, recorded here and re-runnable, or committed as a mutant the suite re-runs and
which clears the three conditions in `README.md`. `j1` is the only one the suite reads,
through `THE_GATE_SUCCESS_THROW`, because a test asserts it. The other three live here
alone: a constant no test references is a second copy of an anchor with nothing keeping
it in step, which is the drift this task refuses one file away when it declines to copy
api.js's six kinds into `app/app.js`.

The suite deliberately does not re-verify these anchors; see `README.md` in this
directory for that reasoning, and for the format and the recipe.

## A programming error on the gate's success path

```json
{
  "id": "j1-a-missing-key-on-the-cached-session-view",
  "file": "app/app.js",
  "find": "        return refresh();",
  "replace": "        return refresh().then(function () { return api.cachedSession().nope.alsoNope; });",
  "kills": [
    "a_successful_sign_in_keeps_the_screen_the_person_was_on",
    "a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate",
    "a_sign_in_the_network_interrupted_still_lets_the_gate_come_back",
    "a_session_that_expires_after_a_real_sign_in_still_returns_to_the_gate",
    "creating_an_account_signs_in_straight_after",
    "an_interrupted_save_keeps_what_was_typed_through_signing_back_in",
    "an_interrupted_save_keeps_the_split_mode_and_rebuilds_the_person_rows",
    "signing_out_clears_the_draft_before_the_next_person_signs_in",
    "a_401_on_save_then_a_different_person_signs_in_starts_a_fresh_entry",
    "a_401_on_save_then_a_different_person_signs_in_returns_the_split_to_equally",
    "everyone_sees_the_same_payment_awaiting_confirmation",
    "an_unlinked_account_is_offered_no_way_to_mark_anything_paid",
    "everyone_sees_the_same_rejected_payment",
    "an_unlinked_account_is_offered_no_way_to_answer_anything"
  ],
  "survives": [
    "a_refused_sign_in_tells_the_person_why",
    "a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone",
    "boot_with_no_session_shows_the_gate"
  ],
  "result": "killed"
}
```

`kills` is the complete list of scenarios this mutation reds **after** the change,
measured over the whole scenario list unfiltered: **14 scenarios red out of the 160 the
harness runs**. Before the change it reds **none of them**, which is the whole of this
record and is the block two headings down. `survives` is a named-control list and not
the complement: the other 146 are not enumerated here.

The 14 are every scenario that reaches the gate's fulfilled handler, and they are more
than the four the gate's own section of the harness declares, because signing in is how
the add-screen draft scenarios and the settlement scenarios get a person onto a screen
at all.

### Why the cached session view and not a DOM member

The anchor dereferences a missing key on the view the client caches, which is a plain
object parsed out of a stubbed response. Reaching instead for something the DOM stub
does not define would route through `refusedProperty()` in `tests/shell_harness.mjs`,
which records a failure line against the running scenario at the moment it refuses,
**whatever the app then does with the exception**. The check would then be satisfied by
the guard's own line under either promise shape and would prove nothing about the
change. No guard is wrapped round `window.SplitwiseApi`, so the `TypeError` is disposed
of entirely by the shipped chain.

The two `kills` blocks quoted below show both shapes the replacement can take, and
neither involves a guard. Where the sign-in cached a view, `.nope` is `undefined` and
reading `.alsoNope` off it throws. Where a 401 behind the sign-in dropped that copy,
`cachedSession()` is `null` and reading `.nope` off that throws. Same class of error,
different sentence, and the run prints which.

### Why this anchor and not one inside `refresh()` or `showApp()`

Because the fate of the throw has to be the gate's chain's decision alone. `refresh()`
is also called bare when the client finishes loading, where a rejection reaches nobody
and escapes already, so a substitution inside `refresh()` or `showApp()` would put an
`unhandled rejection` line in the report before the change as well and could prove
nothing. This anchor also throws **after** `refresh()` has settled, so every request
each scenario declares still goes out and every assertion it makes still holds. That is
what makes the before-run green, and the before-run being green is the reproduction.

### The before-run, which is the bug stated as a measurement

The mutation applied to `app/app.js` exactly as it ships at `87b7b7f`, over the whole
scenario list unfiltered:

    exit=0
    FAIL lines: 0
    ok lines: 160
    unhandled rejection: 0 report lines, and 0 raw occurrences in either stream

**Exit 0, 160 of 160 scenarios green, and the string `unhandled rejection` appearing 0
times anywhere in the run.** A programming error on the sign-in success path, and a
green suite. The gate's `.catch` returned early for any reason whose `kind` was neither
`signed-out` nor `refused`, a `TypeError` has no `kind`, and the trailing `.then` then
re-enabled the submit control, so the rejection was consumed and the DOM was left
valid. Nothing was recorded anywhere and nothing was left on screen to notice.

That is worse than the feed's version of the same defect rather than different in kind.
On the feed, `feedState('list')` is the last statement of `feedRender`, so a throw left
`#feed-loading` up and the in-flight invariant reddened 14 scenarios with a symptom.
Here there was no symptom at all.

### The after-run

The same mutation, the same configuration, against the changed `app/app.js`:

    exit=1
    FAIL count: 14
    unhandled rejection: 16 report lines
    gate-submit lines: 0

    FAIL a_successful_sign_in_keeps_the_screen_the_person_was_on
           unhandled rejection: TypeError: Cannot read properties of undefined (reading 'alsoNope')
        at ...\app\app.js:1501:76
    FAIL a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate
           unhandled rejection: TypeError: Cannot read properties of null (reading 'nope')
        at ...\app\app.js:1501:71

The absolute paths in those stacks are this working tree's and are elided here; the run
prints them in full.

**Count report lines, not raw occurrences, and the two differ by exactly a factor of
two.** The harness prints each failure once in the human report on stderr and once inside
the JSON report on stdout, so `grep -o 'unhandled rejection'` over both streams of this
run returns **32** where the report holds **16** lines. Both numbers were measured. Every
count in this record is of report lines; the before-run's 0 is the one place the two
readings cannot disagree, and stating the unit is what stops a re-runner reading 32
against 16 and concluding the record is wrong.

**16 lines across 14 scenarios**, because `everyone_sees_the_same_payment_awaiting_confirmation`
and `everyone_sees_the_same_rejected_payment` each sign two people in, so the throw
fires twice in each.

**No frame name is pinned anywhere.** The throw is inside an anonymous function and V8
named that frame by position alone in every one of the 16 lines, which is the second of
the two shapes issue #72's record shows. The test asserts `app.js` and the real lines
are pasted above.

**`gate-submit lines: 0` is the other half of the change.** The trailing handler is
`.finally`, so the submit control comes back on the re-raising path too, and neither the
new invariant clause nor the hand assertion inside
`a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate` has
anything to report. That is how "the submit button still comes back" is checked rather
than claimed in prose.

### The positive control for the new invariant clause

`finish()` in `tests/shell_harness.mjs` gained one clause with this change: a scenario
that returns with `#gate-submit` disabled fails, in all 160 scenarios and every future
one. Against unmodified `app/` it reds **0** of the 160, which is the state it is meant
to sit in, so on its own it is a check nobody has seen fail.

This is the run that makes it one: `j1` applied, and the trailing handler put back to
`.then` — the naive fix the issue warns is worse than the bug, because a rejected promise
skips a fulfilled handler and the gate stays disabled for good. That second change has
its own anchor, so it is a block and not a sentence:

```json
{
  "id": "j1b-the-naive-fix-run-together-with-j1",
  "file": "app/app.js",
  "find": "      .finally(function () {",
  "replace": "      .then(function () {",
  "kills": [
    "a_successful_sign_in_keeps_the_screen_the_person_was_on",
    "a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate",
    "a_sign_in_the_network_interrupted_still_lets_the_gate_come_back",
    "a_session_that_expires_after_a_real_sign_in_still_returns_to_the_gate",
    "creating_an_account_signs_in_straight_after",
    "an_interrupted_save_keeps_what_was_typed_through_signing_back_in",
    "an_interrupted_save_keeps_the_split_mode_and_rebuilds_the_person_rows",
    "signing_out_clears_the_draft_before_the_next_person_signs_in",
    "a_401_on_save_then_a_different_person_signs_in_starts_a_fresh_entry",
    "a_401_on_save_then_a_different_person_signs_in_returns_the_split_to_equally",
    "everyone_sees_the_same_payment_awaiting_confirmation",
    "an_unlinked_account_is_offered_no_way_to_mark_anything_paid",
    "everyone_sees_the_same_rejected_payment",
    "an_unlinked_account_is_offered_no_way_to_answer_anything"
  ],
  "survives": [
    "a_refused_sign_in_tells_the_person_why",
    "a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone"
  ],
  "result": "killed"
}
```

**This block is never run alone, and its `kills` is the pair's rather than its own.** The
anchor matches once, at `app/app.js:1543`, the other `.finally` being
`    ).finally(done);` at 713. Applied by itself it only puts the chain back to a shape
where nothing throws, which reds nothing at all. Both blocks go in one `substitutions`
list:

    {"substitutions": [
      {"file": "app/app.js", "find": "        return refresh();",
       "replace": "        return refresh().then(function () { return api.cachedSession().nope.alsoNope; });"},
      {"file": "app/app.js", "find": "      .finally(function () {",
       "replace": "      .then(function () {"}
    ]}

That config, run against this branch:

    exit=1
    FAIL count: 14
    unhandled rejection: 16 report lines
    gate-submit lines: 15

    FAIL a_successful_sign_in_keeps_the_screen_the_person_was_on
           unhandled rejection: TypeError: Cannot read properties of undefined (reading 'alsoNope')
        at ...\app\app.js:1501:76
           #gate-submit is still disabled after settle: this scenario left the gate unusable, which is what a sign-in chain that skipped its re-enabling handler looks like from outside
    FAIL a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate
           unhandled rejection: TypeError: Cannot read properties of null (reading 'nope')
        at ...\app\app.js:1501:71
           #gate-submit disabled: expected false, got true
           #gate-submit is still disabled after settle: this scenario left the gate unusable, which is what a sign-in chain that skipped its re-enabling handler looks like from outside

**14 clause lines plus the one hand assertion that already existed, in the one scenario
that thought to look.** That ratio is the argument for the clause: the same defect was
visible in 1 scenario before and is visible in 14 now, and would be visible in any
future scenario that signs a person in.

This run was first taken as a hand edit and written up as a sentence, which was wrong.
Rule (e) of `.claude/rules/testing.md` is that a mutation is an anchor and a replacement,
never a sentence, and the reason first given for the exception, that one config cannot
carry two replacements, is true only of two changes sharing one anchor. These two do not
share one. The pair above was re-run from the config as written here, and the numbers
are that run's rather than the hand edit's.

### Why this is not a tenth committed mutant

`MUTANT_A` through `MUTANT_I` in `tests/test_shell_behaviour.py` each assert that a
mutation turns named scenarios red. A `MUTANT_J` on this anchor cannot be added in the
first commit at all, because before the change the mutation **survives** and there are
no red scenarios for it to name. After the change it could be added, and it would then
assert that some scenarios went red — a weaker version of what
`test_a_throw_on_the_gates_success_path_arrives_as_an_unhandled_rejection in
tests/test_shell_behaviour.py` already asserts precisely, on the failure line itself.
So the reason it is refused here is **duplication**, and deliberately not issue #72's
reason, which was that a redness check on its anchor could not have failed either side
of the change. Here redness would bite. It would just be saying less than the test that
already exists, in a place that costs a run every time the suite is run.

### Why the assertion is on the failure line and not on redness

Redness alone would distinguish these two runs, unlike #72's, where the same 14
scenarios reddened either side of the change. It is still the wrong assertion: a
scenario that reds for an unrelated reason would satisfy it, and what the test exists to
say is that the rejection hook fired with a diagnosis in it.

### The named survivors

`a_refused_sign_in_tells_the_person_why` never reaches the gate's fulfilled handler, so
the substitution is inert in it: the sign-in is refused, `announce()` classifies it, and
the `.catch` writes the server's sentence on the gate exactly as before. It could not
have caught the original defect and it cannot prove this fix either, which is why it is
written down rather than left to be noticed.

`a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone` is the control for the
half that must not change, and it is what makes a bare re-raise wrong. A sign-in that
got no answer arrives at the same `.catch`, it is an error the client raised, of kind
`offline`, and it must stay a silent early return with the offline notice already up.
Had the change been made by re-raising anything without a recognised `kind`, that
scenario would carry an `unhandled rejection` line of its own and be red.

`boot_with_no_session_shows_the_gate` says the app is otherwise working: one path is
broken, not the whole shell.

## A rejection with no reason at all

```json
{
  "id": "j2-a-rejection-with-no-reason",
  "file": "app/app.js",
  "find": "        return refresh();",
  "replace": "        return refresh().then(function () { return Promise.reject(); });",
  "kills": [
    "a_successful_sign_in_keeps_the_screen_the_person_was_on",
    "a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate",
    "a_sign_in_the_network_interrupted_still_lets_the_gate_come_back",
    "a_session_that_expires_after_a_real_sign_in_still_returns_to_the_gate",
    "creating_an_account_signs_in_straight_after",
    "an_interrupted_save_keeps_what_was_typed_through_signing_back_in",
    "an_interrupted_save_keeps_the_split_mode_and_rebuilds_the_person_rows",
    "signing_out_clears_the_draft_before_the_next_person_signs_in",
    "a_401_on_save_then_a_different_person_signs_in_starts_a_fresh_entry",
    "a_401_on_save_then_a_different_person_signs_in_returns_the_split_to_equally",
    "everyone_sees_the_same_payment_awaiting_confirmation",
    "an_unlinked_account_is_offered_no_way_to_mark_anything_paid",
    "everyone_sees_the_same_rejected_payment",
    "an_unlinked_account_is_offered_no_way_to_answer_anything"
  ],
  "survives": [
    "a_refused_sign_in_tells_the_person_why",
    "a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone"
  ],
  "result": "killed"
}
```

**This mutation is asserted by no test, and that is deliberate.** It is the case the
deleted `!error ||` half of the gate's `.catch` used to swallow: a rejection with no
reason at all, which has no `kind` to read and would have thrown on the read if the test
had been spelled the other way round. Asserting it would be a second, weaker spelling of
what the test on the first mutation already asserts, on a reason that carries no stack
and so delivers no diagnosis.

Against the changed `app/app.js`:

    exit=1
    FAIL count: 14
    unhandled rejection: 16 report lines
    gate-submit lines: 0

    FAIL a_successful_sign_in_keeps_the_screen_the_person_was_on
           unhandled rejection: undefined
    FAIL a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate
           unhandled rejection: undefined

`undefined` and no stack, because `escaped()` stringifies a reason that has no `.stack`.
The same 14 scenarios, and `gate-submit lines: 0` again, so `.finally` re-enables the
control for a falsy reason too.

Against `app/app.js` as it ships at `87b7b7f`, the same configuration:

    exit=0
    FAIL count: 0
    unhandled rejection: 0 report lines

Which is the point of recording it. The recogniser answers `false` for a reason that is
not an object at all, rather than reading `kind` off it, and what used to answer that
question was `!error ||`.

## A throw inside the catch's own body

```json
{
  "id": "j4-the-catch-throws-while-writing-the-gate-message",
  "file": "app/app.js",
  "find": "        gateError.textContent = error.say || 'That did not work.';",
  "replace": "        gateError.textContent = error.say.nope.alsoNope;",
  "kills": [
    "a_refused_sign_in_tells_the_person_why",
    "a_refused_sign_in_with_an_unreadable_body_still_says_something",
    "creating_an_account_that_already_exists_says_so_on_the_gate",
    "a_rate_limited_sign_in_reads_on_the_gate_with_no_curtain_over_it",
    "the_submit_control_is_disabled_while_the_sign_in_is_in_flight",
    "the_form_never_lets_the_browser_navigate",
    "the_email_is_trimmed_and_the_password_is_not",
    "every_request_goes_to_the_api_with_credentials",
    "the_csrf_token_is_read_at_request_time_not_cached",
    "a_route_change_behind_the_gate_asks_for_nothing_and_leaves_the_gate_alone"
  ],
  "survives": [
    "a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone",
    "a_successful_sign_in_keeps_the_screen_the_person_was_on"
  ],
  "result": "killed"
}
```

**Criterion 10 measured rather than inferred.** The task states that a throw inside the
`.catch` handler's own body, while writing `#gate-error`, now also re-enables the submit
control where before it did not, and deliberately asserts it nowhere, since it is the
same property criterion 9 pins. That left it the one claim in this change resting on
inference, and this block closes it for the cost of one run. Recorded, asserted by no
test, for the same reason as `j2`.

    exit=1
    FAIL count: 10
    unhandled rejection: 11 report lines
    gate-submit lines: 0

    FAIL a_refused_sign_in_tells_the_person_why
           unhandled rejection: TypeError: Cannot read properties of undefined (reading 'alsoNope')
        at ...\app\app.js:1533:48

**`gate-submit lines: 0`, and that is the whole finding.** Ten scenarios take the arm
that writes on the gate, the write throws out of the `.catch` itself rather than out of
the fulfilled handler, and the control still comes back: nothing reds on the new clause,
and `the_submit_control_is_disabled_while_the_sign_in_is_in_flight`, which asserts
`#gate-submit disabled === false` by hand after settling, carries the rejection line and
nothing else. Under the trailing `.then` this path had no re-enabling handler at all,
because a throw inside a `.catch` rejects the promise that handler returns.

The two survivors are the arms that never reach that line: an offline sign-in returns
early above it, and a successful one never enters the `.catch`.

## The control on the anchor itself

```json
{
  "id": "j3-a-property-the-dom-stub-refuses",
  "file": "app/app.js",
  "find": "        return refresh();",
  "replace": "        return refresh().then(function () { return document.notAThingTheStubHas; });",
  "kills": [
    "a_successful_sign_in_keeps_the_screen_the_person_was_on",
    "a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate",
    "a_sign_in_the_network_interrupted_still_lets_the_gate_come_back",
    "a_session_that_expires_after_a_real_sign_in_still_returns_to_the_gate",
    "creating_an_account_signs_in_straight_after",
    "an_interrupted_save_keeps_what_was_typed_through_signing_back_in",
    "an_interrupted_save_keeps_the_split_mode_and_rebuilds_the_person_rows",
    "signing_out_clears_the_draft_before_the_next_person_signs_in",
    "a_401_on_save_then_a_different_person_signs_in_starts_a_fresh_entry",
    "a_401_on_save_then_a_different_person_signs_in_returns_the_split_to_equally",
    "everyone_sees_the_same_payment_awaiting_confirmation",
    "an_unlinked_account_is_offered_no_way_to_mark_anything_paid",
    "everyone_sees_the_same_rejected_payment",
    "an_unlinked_account_is_offered_no_way_to_answer_anything"
  ],
  "survives": [
    "a_refused_sign_in_tells_the_person_why",
    "a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone"
  ],
  "result": "killed"
}
```

**Run once, against `87b7b7f` with `app/` unmodified, and it is not a mutation this
change is about.** It exists because a green before-run has two possible explanations,
and only one of them is the bug. Either the throw happened and the chain swallowed it,
or the substituted line never ran at all, and a record that cannot tell those apart is
a measurement of nothing.

This replacement reaches for a property the DOM stub does not define, so
`refusedProperty()` records a failure line **whatever the app then does with the
exception** — which is exactly why the first mutation must not be spelled this way, and
exactly what makes it the right control on the anchor:

    exit=1
    FAIL count: 14

**The same 14 scenarios, against unmodified `app/`.** So the anchored line executes, in
those 14 and only those 14, before any change to `app/app.js`. The first mutation's
green before-run is a swallowed error and not an unreachable line.
