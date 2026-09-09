# Mutations behind the feed render path (issue #57)

One mutation, to the harness's own DOM stub rather than to shipped code. Issue #57's
finding 2 is that the obvious way to fake `document.createDocumentFragment` is
silently wrong: this stub's `replaceChildren` is `own.childNodes = nodes.slice()` and
its `appendChild` is a push, so a fragment accepted as it stands becomes **one child
node** rather than its children, where a browser inserts the children and empties the
fragment. That is a wrong tree with no error attached to it, which is the one
behaviour a stub must never have, so criterion 2 makes the flattening a guarantee and
this mutation is what shows the guarantee is pinned rather than assumed.

The mutation switches the flattening off while leaving `inserted()` and both its call
sites in place, so the effect is exactly a stub that accepts a fragment without
expanding it. The JavaScript harness needs no `PYTHONDONTWRITEBYTECODE`, because it
substitutes into source text at run time and caches nothing; this one is applied to
the file directly rather than through the harness's `substitutions` list, which only
loads `app/app.js` and `app/api.js`. Applied with the README's recipe, run with
`node tests/shell_harness.mjs < /dev/null`, reverted with `git checkout -- <file>`.

Taken against `8d0a8f7` on 2026-09-07, on branch `task-57`, and re-measured there after
the rebase onto `38ebc1e`. A record quotes a
measurement, so it carries the tree it was measured on: if the anchor below no longer
matches exactly once, that is the tree to diff against rather than a defect in the
record. The anchor below is swept by the suite, which counts its `find` in the file
this record's `file` key names and requires exactly one match or a declaration; see
`README.md` in this directory for what that check does and does not promise, and for
the format and the recipe.

> **Corrected 2026-09-09 for issue #96**, per
> `plans/tasks/96-record-files-still-say-the-suite-does-not-re-verify.md`. This paragraph
> used to end: "The suite deliberately does not re-verify these anchors; see `README.md`
> in this directory for that reasoning". That is no longer true of this repo. PR #93
> landed `test_every_recorded_anchor_matches_once_or_is_carried` in
> `tests/test_suite_integrity.py`, which counts every recorded `find` in the file that
> record's own `file` key names and refuses anything but exactly one match, unless the
> record is declared in `CARRIED_STALE_ANCHORS` with a reason naming the change that
> broke it. What is still true, and is what that sentence was protecting, is narrower: no
> recorded mutation is re-run and no `result` is verified, so a matching anchor proves a
> record **appliable** and not correct.

## Insertion stops flattening a document fragment

```json
{
  "id": "g1-insertion-does-not-flatten",
  "file": "tests/shell_harness.mjs",
  "find": "  if (node.tagName !== '#DOCUMENT-FRAGMENT') {",
  "replace": "  if (true) {",
  "kills": [
    "a_feed_row_names_the_payer_the_amount_and_what_it_was_for",
    "the_rows_stay_in_the_order_the_server_sent_them"
  ],
  "survives": [
    "a_feed_with_nothing_recorded_says_so_and_draws_no_row",
    "an_expense_described_in_markup_reaches_the_screen_as_text",
    "an_expense_with_no_description_still_names_everything_else",
    "opening_a_row_shows_every_share_and_the_total_they_are_shares_of",
    "a_payer_who_is_not_sharing_is_said_so_rather_than_added_to_the_split",
    "a_member_the_roster_does_not_know_reads_as_words_not_as_an_id",
    "four_people_sharing_one_expense_read_as_two_names_and_a_count",
    "leaving_the_feed_and_coming_back_draws_each_row_once",
    "a_created_at_that_is_not_a_date_never_reads_as_nan"
  ],
  "result": "killed"
}
```

**What the run printed with the flattening switched off:**

    FAIL a_feed_row_names_the_payer_the_amount_and_what_it_was_for
           the first child of #feed-list: expected <li>, got <#document-fragment>
           the firstChild of #feed-list: expected <li>, got <#document-fragment>
           a document fragment was left in the rendered tree
    FAIL the_rows_stay_in_the_order_the_server_sent_them
           children of #feed-list: expected 3, got 1
           their tags: expected ["LI","LI","LI"], got ["#DOCUMENT-FRAGMENT"]
           their classes: expected ["expense-row","expense-row","expense-row"], got [""]
           a document fragment was left in the rendered tree

Exit 1, two scenarios red of 149.

**Both arrays above are complete, not a sample.** `kills` is every scenario the
mutation reds, in the whole suite and not only among this task's; `survives` is every
one of the other scenarios this task added. Nothing else in the suite renders a feed
row, so no scenario outside this task's eleven can be affected either way. A partial
list would be indistinguishable from a complete one to somebody re-running this, which
is this record's own subject.

**Verdict.** Killed, and the survivors are the interesting half. Every scenario in
`survives` that renders a row passes straight through the phantom fragment, because
`.expense-row`, `.expense-description`, `.expense-payer`, `.expense-figure`,
`.expense-split`, `.expense-share` and `.expense-share-name` are **all still
reachable**: `descendants()` walks into the fragment as if it were an element, so every
class selector matches and every text assertion passes. `expense rows: expected 1, got
0` stayed green even in the row scenario that did red. Only the two in `kills` notice,
and they notice through position rather than through content: the row scenario pins
`firstChild` and the first child of `#feed-list`, and the order scenario's whole subject
is the direct-children sequence, which three collapsing to one destroys. That is finding
2 measured rather than argued, and it is why criterion 2 asks for node positions and for
the absence of the tag rather than for a selector that matches.

The count that carries the argument is the ratio, and it is in the arrays rather than in
this sentence: an earlier draft of this paragraph said "nine of the eleven render rows",
conflating the ten that render a row with the nine that survive. Both verifiers caught
it. A miscounted sentence about a mutation, in the document whose purpose is that
sentences about mutations are not to be trusted, is worth leaving a note about rather
than silently correcting.

**One nuance the run corrected.** Finding 2 also predicted that the `textContent`
getter would read the leftover node as `node.text` and yield `undefined`. It does not,
and criterion 3's `no undefined in #feed-list's textContent` assertion did **not**
fire. The reason is the decision in criterion 1: the fragment is built by the existing
`element()` factory, so it carries a `tagName` and the getter recurses into it
correctly. The `undefined` reading is what a fragment faked as a bare object would
produce. The assertion stays, because it costs nothing and it is exactly the check that
would catch that other shape, but the evidence that this shape is caught is the two
position assertions and the tag walk, not that one.
