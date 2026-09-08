# Mutations behind the feed's re-raise (issue #72)

One mutation, applied through the harness's own `substitutions` list, which is why no
`PYTHONDONTWRITEBYTECODE` guard applies to it: the JavaScript harness substitutes into
source text at run time and caches nothing. Run with
`node tests/shell_harness.mjs < config.json`, where the config is the block below
wrapped as `{"substitutions": [ ... ]}`, and nothing on disk is touched.

Taken against `6c5e144` on 2026-09-08, on branch `task-72`. A record quotes a
measurement, so it carries the tree it was measured on: if the anchor below no longer
matches exactly once, that is the tree to diff against rather than a defect in the
record. The anchor was verified to match exactly once in `app/app.js` before the run.
The suite deliberately does not re-verify these anchors; see `README.md` in this
directory for that reasoning, and for the format and the recipe.

## A programming error inside `feedRender`

```json
{
  "id": "j1-a-missing-key-on-the-payload",
  "file": "app/app.js",
  "find": "    var names = feedNames(members);",
  "replace": "    var names = feedNames(members);\n    payload.thisKeyIsNotInTheJson.norIsThisOne;",
  "kills": [
    "a_feed_row_names_the_payer_the_amount_and_what_it_was_for",
    "the_rows_stay_in_the_order_the_server_sent_them",
    "an_expense_described_in_markup_reaches_the_screen_as_text",
    "an_expense_with_no_description_still_names_everything_else",
    "opening_a_row_shows_every_share_and_the_total_they_are_shares_of",
    "a_payer_who_is_not_sharing_is_said_so_rather_than_added_to_the_split",
    "a_member_the_roster_does_not_know_reads_as_words_not_as_an_id",
    "four_people_sharing_one_expense_read_as_two_names_and_a_count",
    "leaving_the_feed_and_coming_back_draws_each_row_once",
    "a_created_at_that_is_not_a_date_never_reads_as_nan",
    "a_stale_feed_shows_how_old_the_newest_expense_is",
    "a_fresh_feed_says_nothing_about_its_age",
    "the_feed_obeys_the_state_and_not_the_day_count",
    "a_payload_with_no_staleness_at_all_draws_neither_signal"
  ],
  "survives": [
    "a_feed_with_nothing_recorded_says_so_and_draws_no_row",
    "a_refusal_a_screen_asked_for_leaves_the_app_frame_up",
    "boot_with_no_session_shows_the_gate"
  ],
  "result": "killed"
}
```

`kills` is the complete list of scenarios this mutation reds, measured over the whole
scenario list unfiltered: **14 scenarios red out of the 160 the harness runs**, the same
14 before the fix and after it. `survives` is a named-control list and not the
complement: the other 146 are not enumerated here.

### Why `payload` and not a DOM member

The anchor dereferences a key on `payload`, which is parsed JSON. Reaching instead for
something the DOM stub does not define would route through `refusedProperty()` in
`tests/shell_harness.mjs`, which records a failure line against the running scenario at
the moment it refuses, **whatever the app then does with the exception**. The check
would then be satisfied by the guard's own line under either promise shape, and would
prove nothing about the change. No guard is wrapped round `payload`, so the `TypeError`
below is decided entirely by the shipped chain.

### The two runs, which is the whole point of this record

The failing set is **identical** either side of the change: 14 scenarios, the same 14.
The in-flight invariant reds them under both promise shapes, because `feedState('list')`
is the last statement of `feedRender` and this mutation throws before it. So the
difference is not which scenarios go red. It is what the red says.

**Before, with `loadFeed` ending `.then(done, done)`** — the mutation applied to
`6c5e144`, `unhandled rejection` appearing **0 times** across the whole run:

    FAIL a_feed_row_names_the_payer_the_amount_and_what_it_was_for
           expense rows: expected 1, got 0
           #feed-loading is still showing after settle: this scenario left a screen mid-flight, which is what a render that threw looks like from outside

A symptom with no cause. Nothing in that says a `TypeError` was thrown, and nothing says
where.

**After, with `loadFeed` ending `.finally(done)`** — the same mutation, the same
config, `unhandled rejection` appearing **14 times**, once per red scenario:

    FAIL a_feed_row_names_the_payer_the_amount_and_what_it_was_for
           unhandled rejection: TypeError: Cannot read properties of undefined (reading 'norIsThisOne')
        at feedRender (...\app\app.js:600:35)
        at ...\app\app.js:658:11
           expense rows: expected 1, got 0
           #feed-loading is still showing after settle: this scenario left a screen mid-flight, which is what a render that threw looks like from outside

The absolute paths in that stack are this working tree's and are elided here; the run
prints them in full.

### Why this is not a tenth committed mutant

`MUTANT_A` through `MUTANT_I` all assert that a mutation turns named scenarios red. A
`MUTANT_J` in that family, built on the anchor above, **could not fail**: the two runs
quoted here red the same 14 scenarios, so the assertion would hold against the code
before the change as firmly as after it. It would be a check about a thing that never
opens that thing, which is the defect this repo keeps finding, and adding it would leave
the impression the change is measured when it is not.

What measures the change is an assertion on the failure line itself, and that is what
`test_a_throw_inside_the_feed_render_arrives_as_an_unhandled_rejection`
in `tests/test_shell_behaviour.py` does. Its red run, taken before any edit under `app/`,
is the "before" block above. The precedent for a targeted test of this shape rather
than a table entry is `test_hiding_the_fragment_maker_shows_what_the_feed_was_hiding`
in `tests/test_shell_behaviour.py`, which asserts on the named property and the stuck
screen rather than on redness alone.

### The named survivors

`a_feed_with_nothing_recorded_says_so_and_draws_no_row` never reaches `feedRender`, so
it stays green: it could not have caught the original defect and it cannot prove this
fix either, which is why it is written down rather than left to be noticed.

`a_refusal_a_screen_asked_for_leaves_the_app_frame_up` is the control for the half that
must not change. It refuses `GET /expenses`, so the rejection handler runs,
`feedState('error')` shows `#feed-error`, and the chain settles fulfilled. An ordinary
server refusal is not a programming error and does not reach the hook. Had the change
been made by deleting the rejection handler instead, that scenario would be red.

`boot_with_no_session_shows_the_gate` says the app is otherwise working: one screen is
broken, not the whole shell.
