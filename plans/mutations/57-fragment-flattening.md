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

Taken against `86e817e` on 2026-09-07, on branch `task-57`. A record quotes a
measurement, so it carries the tree it was measured on: if the anchor below no longer
matches exactly once, that is the tree to diff against rather than a defect in the
record. The suite deliberately does not re-verify these anchors; see `README.md` in
this directory for that reasoning, and for the format and the recipe.

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
    "an_expense_described_in_markup_reaches_the_screen_as_text",
    "a_feed_with_nothing_recorded_says_so_and_draws_no_row"
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

**Verdict.** Killed, and the survivors are the interesting half. Nine of the eleven new
scenarios render rows and only two of them notice, because `.expense-row`,
`.expense-description`, `.expense-payer`, `.expense-figure`, `.expense-split`,
`.expense-share` and `.expense-share-name` are **all still reachable** through the
phantom fragment: `descendants()` walks into it as if it were an element, so every
class selector matches and every text assertion passes. `expense rows: expected 1, got
0` stayed green in the row scenario. That is finding 2 measured rather than argued, and
it is why criterion 2 asks for node positions and for the absence of the tag rather
than for a selector that matches.

**One nuance the run corrected.** Finding 2 also predicted that the `textContent`
getter would read the leftover node as `node.text` and yield `undefined`. It does not,
and criterion 3's `no undefined in #feed-list's textContent` assertion did **not**
fire. The reason is the decision in criterion 1: the fragment is built by the existing
`element()` factory, so it carries a `tagName` and the getter recurses into it
correctly. The `undefined` reading is what a fragment faked as a bare object would
produce. The assertion stays, because it costs nothing and it is exactly the check that
would catch that other shape, but the evidence that this shape is caught is the two
position assertions and the tag walk, not that one.
