# Task 58: the overflow check that measured the wrong element

**Depends on:** nothing unlanded. Everything this task touches is on `master`: PR #56's
per-class `overflow-wrap` declarations and its `CARRIES_A_NAME` list, task 15's balances
block, and `tests/test_suite_integrity.py` from task 60/65/67.
**Runs beside:** the worktrees for issues #19 and #57. Both may touch
`tests/test_web_shell.py`; #57 is a render path in `app/app.js`, which moves
`SHELL_DIGEST` the same way this task does. See "Two branches, one digest" below.
**Consumed by:** every later task that thinks about small screens, which is the whole
point: the wrong measurement was going to be copied into the next one.

Closes GitHub issue **#58**. `plans/backlog.md` has no entry for it and this task adds
none; the issue is the backlog entry and this file is the implementable version.

---

## What is actually true today

Read this before deciding anything. Every claim here was checked against the tree, not
inferred.

### The measurement is blind in a real browser

`app/styles.css:42` sets `body { overflow: hidden; }`. `app/styles.css:73-78` sets
`.content { flex: 1 1 auto; overflow-y: auto; }`, and per CSS Overflow, when one axis is
`visible` and the other is not, the `visible` one computes to `auto`, so `.content` has a
computed `overflow-x: auto`. The viewport's scrolling area is propagated from the root
element, and `body` clips, so nothing inside `.content` can extend the root's scrollable
area. **`document.documentElement.scrollWidth === document.documentElement.clientWidth`
therefore holds whether or not content overflows.** The equality is not weak; it is
constant.

Four task specs ask an implementer to confirm exactly that equality, in a browser, as the
test for horizontal overflow. It would have gone green on the #56 defect. There is no
record of anybody ever running it, in this or any other form, so the false assurance is so
far potential rather than realised — which is itself the more important fact, and it is
handled below.

### The per-class list is wrong in both directions

`CARRIES_A_NAME` at `tests/test_web_shell.py:1941` holds nine `.balances-*` selectors and
its header comment reads "Every class on this screen that a display name is interpolated
into". Audited against `app/app.js` and `app/index.html`:

| class | what it actually carries | bound | own `overflow-wrap` today | in the list |
|---|---|---|---|---|
| `.balances-line` | display name(s) | 100 chars | `break-word` | yes |
| `.balances-shape-note` | display names | 100 chars | `break-word` | yes |
| `.balances-debt-label` | display name | 100 chars | `break-word` | yes |
| `.balances-entry-description` | **an expense description**, or `A settlement` | 500 chars | `break-word` | yes, **mislabelled** |
| `.balances-entry-effect` | display names | 100 chars | `break-word` | yes |
| `.balances-pending-line` | display names | 100 chars | `break-word` | yes |
| `.balances-action-status` | display name (`… until <receiver> confirms.`) | 100 chars | `break-word` | yes |
| `.balances-rejected-line` | display names | 100 chars | `break-word` | yes |
| `.balances-decision` | display names | 100 chars | `break-word` | yes |
| `.balances-awaiting` | **a fixed literal only** (`BALANCES_AWAITING`) | — | `break-word` | no |
| `.balances-answer-status` | **fixed literals only** (`BALANCES_ANSWERING`, `BALANCES_NOT_ANSWERED`) | — | `break-word` | no |
| `.expense-description` | expense description | 500 chars | `anywhere` (shared rule) | n/a, other screen |
| `.expense-payer`, `.expense-split`, `.expense-share-name`, `.expense-note` | display names | 100 chars | `anywhere` (shared rule) | n/a, other screen |
| `.add-person-name` | display name | 100 chars | `break-word` | n/a, other screen |
| `.add-panel-text` (`#add-saved-description`) | expense description | 500 chars | `break-word` | n/a, other screen |
| `.add-error-text` (`#add-error-server`) | the server's own refusal sentence | unbounded | `break-word` | n/a, other screen |
| **`.curtain-error`** (`#gate-error`) | **the server's `error.say`** | unbounded | **none** | **no, and it is a real gap** |
| **`.curtain-text`** (`#notice-problem`) | **the server's own sentence** | unbounded | **none** | **no, and it is a real gap** |
| `.feed-currency`, `.add-note` (`#add-currency-code`), `.balances-note` (`#balances-currency-code`) | a currency code | exactly 3 A-Z, by schema `CHECK` | none | no, and correctly not: bounded |
| `.balances-figure`, `.expense-figure` | a server-formatted amount | 20 chars at `MAX_CENTS` | `nowrap` / none | no, deliberately |

So the hand-maintained list, on the day it shipped:

* names two classes (`.balances-entry-description`, and by implication its comment) as
  carrying a display name when one carries a description,
* protects two classes (`.balances-awaiting`, `.balances-answer-status`) that carry no
  server string at all, so two of the fifteen declarations in the file guard nothing,
* misses two classes that carry an **unbounded** server string (`.curtain-error` and
  `#notice-problem`'s `.curtain-text`) because they are on neither of the three screens
  and not inside `.content` at all.

That last row is the one that decides where the inherited declaration goes. The #56
reviewer proposed `.balances-list`; `.content` is the next obvious candidate. Both miss
the gate and the notice, which are flex siblings of `.content`, not descendants.

### `app/styles.css` carries fifteen separate `overflow-wrap` declarations

Lines 265, 609, 644, 706, 814, 904, 911, 963, 980, 1007, 1060, 1069, 1082, 1101, 1169.
Fourteen say `break-word`; one, the feed's shared rule at 258-266, says `anywhere`, with a
comment explaining why: "`anywhere` so a single unbroken 100 character display name breaks
instead of pushing the layout wide."

That comment is the important technical finding of this task. **`break-word` and
`anywhere` differ only in intrinsic sizing**, and that difference is the whole hazard:
under `break-word` the soft wrap opportunities the property introduces are *not* counted
when computing min-content, so a flex item still takes an unbroken 100-character word as
its width floor and pushes its container wide; under `anywhere` they are counted, so it
does not. Under `break-word` the fix only works when it is paired with `min-width: 0`, and
`min-width: 0` is a second thing to remember — which is exactly the failure mode being
removed. The feed block already depends on `anywhere`, so choosing it introduces no
browser-support requirement this repo does not already have.

### The JavaScript half cannot help

`tests/shell_harness.mjs` reads only `app/index.html`, `app/app.js` and `app/api.js`. It
never reads `app/styles.css`, and its stubbed DOM has no `style`, no `getComputedStyle`,
no `clientWidth`, no `scrollWidth` and no `getBoundingClientRect`. It has no layout engine
and no cascade. **No scenario in the harness can measure or infer anything about
overflow**, now or after any amount of work short of adding a headless browser, which
would be a dependency and an npm install. That is settled, not open.

### Nothing in this project has ever been verified in a browser

Not once, in fifteen task specs, each of which carries a browser checklist. There is no
recorded run, no screenshot, no console transcript. **A criterion that needs a browser is
a criterion that will not be run**, and writing one and counting it as verification is the
same defect as the wrong measurement, one level up. This task treats browser lines as
documentation and puts the entire verification weight on the static half.

---

## The decisions, and why

### 1. One declaration, on `body`, and `anywhere` rather than `break-word`

`overflow-wrap` is inherited. One declaration on `body` covers every element the shell
renders: all three screens, the gate, the notice, the header and the tab bar, including
any class added later by anybody. `.balances-list` covers one list on one screen.
`.content` covers the three screens and misses `#gate-error` and `#notice-problem`, both
of which carry an unbounded server string today. `body` is the only selector in this
document that covers everything, and it costs one line.

`anywhere`, for the intrinsic-sizing reason above: it is the only value that makes the
declaration sufficient on its own. Existing `min-width: 0` declarations stay where they
are; they are still correct and they cost nothing.

The two things that can defeat an inherited break rule are `white-space: nowrap`, which
suppresses every soft wrap opportunity in a box, and `overflow-wrap: normal`, which takes
the rule back. Both are enumerable in the stylesheet, so both are checkable. Clipping
(`text-overflow`, `overflow: hidden`, `-webkit-line-clamp`) hides an overflow rather than
causing one, which is worse on a money screen, and is likewise checkable.

### 2. The per-class list goes

Fifteen declarations become one. `CARRIES_A_NAME` and
`test_every_line_that_carries_a_name_can_break_a_long_one` are deleted.

Deleting a check needs a better reason than "it is annoying to maintain", so here is the
reason: the list **cannot be right**. It derives nothing from `app/app.js`, it was wrong
in three ways on the day it landed (two dead entries, one mislabelled entry, two missing
classes on other screens), and its correctness depends on every future author of every
future screen remembering a Python constant on line 1941 of a 2100-line test module. The
#56 branch is the proof: three classes shipped without the declaration, on a branch whose
author had read task 12's comment naming the hazard.

What replaces it is three property-oriented checks over the whole of `app/styles.css`,
which derive from the file rather than from a list of class names, and which cover the two
screens and two curtains the list never reached. The class of failure the list was written
to catch — a new text-bearing class shipping unprotected — stops being possible rather
than being caught: under an inherited declaration the new class is already covered, and
the only ways to break it are the ones the new checks enumerate.

The mislabelling the #56 reviewer found is resolved by deletion. The replacement comment
must say **"a server-provided string of unbounded length"** and not "a display name",
because the set includes 500-character descriptions and the server's own refusal prose.

### 3. Why the demonstration cannot take the shape the issue asks for

The natural demonstration is "add a name-bearing class with no `overflow-wrap`, watch the
suite go red". Under an inherited declaration that class is **correct**, and a suite that
went red on it would be asserting a requirement that no longer exists. So the
demonstration is three parts instead of one, and criterion 27 spells them out: the #56
defect in the only form it can still take goes red; the #56 defect as literally written
stays green, recorded as green-and-correct with the reason, so nobody later reads that
green as the old blindness; and deleting the one declaration that makes it correct goes
red. The third part is the honest version of the demand: the check that protects those
three classes is the root declaration, and the suite notices when it goes.

### 4. The corrected measurement, and the positive control

`el.scrollWidth > el.clientWidth`, over `.content` and every element inside it, and over
whichever `.curtain` is visible and every element inside that, at 320, 360 and 390 CSS px
and in landscape at 844x390, with a single unbroken token in every field that interpolates
a server-provided string. `document.documentElement` is never measured.

Two caveats that must be written into the checklist, or the corrected measurement is
merely a better-aimed blind check:

* `scrollWidth` and `clientWidth` are integer-rounded, so a sub-pixel overflow reads as no
  overflow.
* A hidden element reports `0` for both, so `0 > 0` is false and every collapsed region
  silently passes. Each region must be opened before the sweep, and the sweep must report
  how many elements it actually examined.

And the thing no manual check in this repo has ever had: **a positive control.** Setting
`document.body.style.overflowWrap = 'normal'` in the console and re-running the sweep must
make the result non-empty. A measurement that cannot be made to fail on demand is not
evidence, which is the entire content of issue #58.

### 5. What is checkable without a browser, and what is not

**Tier 1, checkable in pytest, and now checked.** The cascade facts, statically, over
`app/styles.css`: that exactly one `overflow-wrap` declaration exists, that it is on
`body`, that its value is `anywhere`, that nothing takes it back, that the only two
selectors refusing a wrap are the two that hold fixed-shape text, that nothing clips text,
and that `body` still clips while `.content` still scrolls. This tier would have caught
#56 in the suite. It is where all the weight goes.

Plus one document check: the wrong measurement cannot be written into a task spec again
without the suite going red. That is the durable half of this issue, because #58's own
scope line says the measurement "will be copied into the next task spec that thinks about
small screens".

**Tier 2, checkable in principle, not here.** Whether a given class's *computed*
`overflow-wrap` is `anywhere` needs a cascade; whether its box overflows needs layout.
Both need a browser engine, therefore a dependency and an npm install, both of which this
repo refuses. Not deferred, refused, with the reason recorded.

**Tier 3, genuinely needs a browser, and will not be run.** Real line breaking, real box
widths, whether a 100-character `<option>` in `#add-payer` extends the picker popup past
the viewport (no `overflow-wrap` of any kind can wrap an `<option>`; that case is held by
`.add-field { width: 100%; min-width: 0; max-width: 100% }` and by nothing else), and
whether the iOS keyboard covers Save. These stay as a checklist, marked
`(browser check, unrun)`, and **no acceptance criterion in this task depends on one for
its verdict.** Criterion 40 says so explicitly, so that a QA agent that cannot open a
browser can still return a complete verdict.

### 6. The four places in `plans/tasks/`, and five more that go stale

Task files are records of how a task was specified, so every edit is a dated note in a
blockquote beneath the line, in the shape already used at
`plans/tasks/13-transfer-drill-down.md:907` and `plans/tasks/12a-transfer-provenance-api.md:393`.
Nothing is renumbered and no criterion is silently rewritten.

**The wrong measurement, four places in four files.** `08-mobile-web-shell.md:214-215`,
`10-expense-entry-screen.md:505`, `11-expense-feed.md:339`,
`12-balances-screen.md:372-373`. `13-transfer-drill-down.md:901-919` was already corrected
on 2026-09-06 and is not re-edited beyond one pointer sentence, because its existing note
ends "the general case ... is filed as issue #58 and is not fixed here" and a reader
following that trail should land on this file.

**Mechanisms this task deletes, five more places in five files.**
`10-expense-entry-screen.md:513` and `11-expense-feed.md:68` name per-class
`overflow-wrap` declarations that no longer exist; `14-mark-as-paid.md:874-877` and
`15-receiver-confirmation.md:1000-1003` name `CARRIES_A_NAME`, which no longer exists; and
`13-transfer-drill-down.md:907-919` gets the pointer. A criterion naming a deleted
constant sends the next reader looking for something that is not there, which is the
defect `plans/tasks/42-what-the-documents-claim.md` exists about. One line each.

**Nine places, eight files, no criterion renumbered.**

Deliberately left alone: the vaguer manual-checklist lines that say "no horizontal scroll"
without naming an element (`08:393-394`, `10:698-701`, `11:486-487`, `12:475-476`,
`13:1059-1060`). They are imprecise, not false, and tasks 14 and 15 already say "no
horizontal scroll on `.content`". Sweeping five more files to reword prose that is not
wrong inflates the diff; the rule and the check in criteria 20-22 are what stop the next
author reaching for the document element.

### 7. The seventh rule, and the check that keeps it

`.claude/rules/testing.md` holds six rules, each carrying the defect that produced it.
This is a seventh of exactly that kind: **a manual check names the element it measures,
and comes with a way to make it fail.** Its scar is this issue.

The rule needs a mechanism or it lasts until the next author who has not read it, which is
the failure mode `plans/tasks/46-shell-precache-digest.md` records for `VERSION`. The
mechanism is a single test that refuses the literal `documentElement` in any document under
`plans/`, in `README.md` or in `CLAUDE.md`, except inside a blockquote. Blockquotes are
where dated correction notes live, so the historical record stays legal and the next
criterion cannot be written. It also forces this task's own corrections into the right
shape: the old wording must move into a `>` note rather than being left in place.

That check lives in `tests/test_suite_integrity.py`, not in `tests/test_web_shell.py`.
That module is the suite's check on itself, its subject is checks that report success
without exercising what they name, and it already reads two paths outside `tests/`
(`.claude/rules/testing.md` and `plans/mutations/`). A wrong measurement written into a
criterion is precisely a check that cannot fail. The scan does **not** cover `tests/`, and
that is not laziness: the check's own source and message contain the banned literal, so a
scan over `tests/` would flag itself. A comment must say so, or somebody will widen it.

### Two branches, one digest

`app/styles.css` is precached, so this task moves `SHELL_DIGEST`. So does #57, if it edits
`app/app.js`. Whichever merges second will find its recorded digest stale on the merge
commit, which is exactly the case `CLAUDE.md` warns about: a result computed against an
older `master` says nothing about the merge commit, and the merge commit is where a stale
digest surfaces. The fix, both times, is to bring the branch up to date, re-run
`tests/test_web_shell.py` and paste the line the failing test prints. `VERSION` stays
`v4`; it is not what a shipped edit bumps.

---

## Goal

The shell breaks a long unbroken server-provided string everywhere it renders one, from a
single inherited declaration rather than from a hand-maintained list of classes that was
wrong in three ways on the day it shipped. The check that a text-bearing class is
protected runs in `uv run python -m pytest` instead of on somebody's phone, and covers all
three screens plus the gate and the notice. The measurement that reported success in
exactly the case it was written to catch is corrected wherever it appears, with the reason
recorded beside it, and cannot be written into a task spec again without the suite going
red.

## Acceptance criteria

Each is a yes or no a QA agent can reach by reading a file or running a command. `REPO` is
the worktree root and every path is relative to it. Criteria 33-39 are the browser
checklist and are marked `(browser check, unrun)`; criterion 40 states what that means for
the verdict.

### The stylesheet

1. `app/styles.css`'s `body` rule carries exactly `overflow-wrap: anywhere;`, and that is
   the only `overflow-wrap` declaration in the file:
   `re.findall(r"overflow-wrap:\s*([a-z-]+)", styles())` returns exactly `["anywhere"]`.
2. All fifteen existing `overflow-wrap` declarations are deleted, at lines 265, 609, 644,
   706, 814, 904, 911, 963, 980, 1007, 1060, 1069, 1082, 1101 and 1169 of `master`'s
   `app/styles.css`. No other declaration is removed from any of those rules: every
   `min-width: 0`, `display`, `font-size`, `color`, `margin` and `padding` in them
   survives byte-for-byte.
3. `.balances-entry-effect`'s second rule, whose only declaration was
   `overflow-wrap: break-word`, is deleted entirely rather than left empty. The class
   keeps the shared rule it appears in with `.balances-entry-date`. No other rule in the
   file becomes empty.
4. The comment on `body` records, in prose a reader can act on: that this is one
   declaration inherited by everything the shell renders, so a class added later is
   covered without anybody remembering; that `anywhere` and not `break-word`, because only
   `anywhere` counts the break opportunities when computing min-content, which is what
   stops a flex item taking an unbroken word as its width floor; that the two ways to
   defeat it are `white-space: nowrap` and `overflow-wrap: normal`, and where each is
   allowed; and that `document.documentElement.scrollWidth` is the wrong thing to measure
   in this shell, because of the `overflow: hidden` two lines above it and `.content`'s
   `overflow-y: auto`.
5. That comment says **"a server-provided string of unbounded length"** and not "a display
   name". A reader must not conclude that a 500-character description or the server's own
   refusal sentence is out of scope of the rule.
6. Every comment whose only subject was a deleted declaration is deleted with it. A
   comment carrying anything else — the `min-width: 0` reasoning, the `:empty` reasoning,
   the reason a date is not shared with an effect line, the reason a figure refuses to
   wrap — keeps that part and loses only the `overflow-wrap` sentence. In particular the
   comment at `master`'s `app/styles.css:895-899`, which states the `body`/`.content`
   finding correctly, is not simply deleted: its content is what criterion 4 moves on to
   `body`, next to the `overflow: hidden` that causes it.
7. The two content-box measurements those comments carry — 258px at the second level of
   nesting and 228px at the third, at a 320px viewport — are preserved in criterion 35 of
   this file rather than lost. They are the numbers the manual sweep uses.
8. No rule is added to `app/styles.css` and no selector is added. The diff is deletions,
   one added declaration on `body`, and comments.
9. `app/index.html`, `app/app.js`, `app/api.js`, `app/manifest.json` and the icons are not
   touched. `git diff --stat` shows exactly two paths under `app/`: `app/styles.css` and
   `app/sw.js`.

### The new checks in `tests/test_web_shell.py`

Names are new; the duplicate-definition check in `tests/test_suite_integrity.py` will
refuse a collision, so run that module before settling on one.

10. `test_one_declaration_lets_every_long_word_in_the_shell_break` asserts, over
    `styles()`: that `overflow-wrap` is declared exactly once in the file, that its value
    is `anywhere`, and that the declaration is inside the `body` rule. Its comment states
    that inheritance is what makes this cover a class nobody has written yet, and names
    #56 as the case a per-class list did not cover.
11. `test_nothing_in_the_shell_takes_the_break_rule_back` asserts, over `styles()`:
    * `white-space` is declared exactly twice in the file, both values are `nowrap`, and
      the selectors carrying them are exactly `.balances-figure` and `.tab`, as a sorted
      equality and not a membership;
    * `overflow-wrap: normal` appears nowhere (implied by criterion 10, asserted anyway,
      because this is the test whose name says it);
    * `text-overflow`, `-webkit-line-clamp` and `word-break` appear nowhere;
    * `overflow: hidden` appears exactly once and is inside the `body` rule.

    Its comment says why each of those five defeats an inherited break rule, and that
    `.balances-figure` and `.tab` are allowed because both hold text of fixed shape: a
    server-formatted amount that must never break mid-number, and three literal tab
    labels.

    > **Clarified 2026-09-07, after the QA verification of this PR.** This criterion says
    > the assertions run "over `styles()`", and four of the five run over
    > `without_comments(styles())` instead. The distinction is load-bearing rather than
    > incidental, so it is recorded rather than glossed: `overflow: hidden` appears
    > **twice** in the raw file, once as the declaration on `body` and once as prose about
    > it inside the comment criterion 4 requires, so a count over the raw text would see
    > two and this criterion asks for exactly one. Comment-stripped is the correct text to
    > count over, because a commented declaration is not applied. Criterion 1 is the
    > exception and deliberately runs over the raw file including comments, which is what
    > forces the comment on `body` to spell its two counter-examples as "`white-space` set
    > to `nowrap`" and "`overflow-wrap` set back to `normal`" rather than with colons; the
    > Findings section records that trade. Nothing about the assertions changes.
12. `test_the_scroll_container_is_the_content_area_and_not_the_document` asserts that
    `body` carries `overflow: hidden`, that `.content` carries `overflow-y: auto`, and
    that no rule in the file declares `overflow-x`. Its comment states the consequence:
    the document element's scrollable area cannot grow, so measuring it says nothing, and
    if either of those two declarations is ever removed the correction notes in
    `plans/tasks/` become stale and this test is what says so.
13. All three read `styles()` and use `re.findall` / `re.search` over the file text, in the
    shape of `test_no_rule_sets_a_hit_area_below_forty_four_pixels`. **No new stylesheet
    parser is written**, `balances_declarations()` is not modified, and nothing tries to
    split the whole file on braces, which the `@media` block would break.
14. Each of the three has a failure message that names the selector or the value it found,
    so a failure is actionable without opening the file.

### The tests that change shape

15. `CARRIES_A_NAME` (`tests/test_web_shell.py:1941`) and
    `test_every_line_that_carries_a_name_can_break_a_long_one` (line 1958) are **deleted**.
    Nothing is left behind naming either.
16. `test_a_long_display_name_wraps_rather_than_being_cut_off` (line 1904) is **replaced**
    by `test_no_balances_rule_declares_a_break_of_its_own`, which asserts that no rule in
    the balances block declares `overflow-wrap` at all, because the root declares it once
    and a per-class copy is a second place to update. Its comment records that the test it
    replaces asserted the opposite, and why.
17. The three things the replaced test asserted are accounted for, one by one, with nothing
    lost:
    * "`overflow-wrap: break-word` appears somewhere in the balances block" is **inverted**
      by criterion 16 and replaced, strictly wider, by criterion 10 over the whole file;
    * "no `text-overflow` and no `overflow: hidden` in the balances block" **widens** from
      the block to the whole file, in criterion 11;
    * "`.balances-figure` is the only nowrap in the balances block" **widens** from the
      block to the whole file, in criterion 11.
18. `test_the_figure_is_still_the_only_thing_that_refuses_to_wrap` (line 2100) passes
    **unchanged** and is not edited. It is now a subset of criterion 11's file-wide
    equality, and keeping it costs nothing.
19. No other test in `tests/test_web_shell.py` is edited, renamed, weakened or deleted. In
    particular `test_every_balances_selector_is_namespaced_to_this_screen`,
    `test_every_transfer_row_clears_the_hit_area_floor`,
    `test_only_the_five_controls_that_really_do_something_look_tappable`,
    `test_all_five_controls_show_a_keyboard_user_where_they_are`,
    `test_the_action_region_never_takes_space_while_it_is_empty`,
    `test_the_balances_block_adds_no_animation`,
    `test_no_rule_sets_a_font_size_below_sixteen_pixels`,
    `test_no_rule_sets_a_hit_area_below_forty_four_pixels` and
    `test_the_layout_survives_a_collapsing_url_bar_and_a_notch` all pass unchanged.

### The document check in `tests/test_suite_integrity.py`

20. One new test — not parametrised, so the suite's pass-count arithmetic stays exact —
    scans every `*.md` under `plans/` plus `README.md` and `CLAUDE.md`, and collects every
    line containing the literal `documentElement` whose stripped form does not start with
    `>`. It asserts the collected list is empty, in the shape
    `assert not failures, "\n\n".join(failures)` the module already uses.

    > **Tightened 2026-09-07, after the senior review of this PR.** This criterion asked
    > for the exemption to be "every line containing the literal `documentElement` whose
    > stripped form does not start with `>`", and it shipped that way first. The review
    > found it enforced less than its own comment claimed: the comment said the exemption
    > was for dated correction notes and argued that "an exemption a criterion could claim
    > by writing a magic word next to itself is how a check stops being one", while the
    > predicate was one character a criterion can write next to itself. A future author
    > facing the red test could prefix `>` and go green with no date and no reason, and
    > the failure message advertised that route in its closing paragraph.
    >
    > The predicate is now the **enclosing blockquote run**, meaning the contiguous run of
    > `>` lines containing the finding, carrying a **date**. It is strictly tightening and
    > turned nothing red, because all five surviving blockquoted occurrences already open
    > `**Corrected 2026-09-07 for issue #58**`, `**Stale ...**` or
    > `**Followed up 2026-09-07.**`. Shown both ways before landing: a bare `>` with no
    > date is refused, and a dated note with the literal three lines below its marker is
    > accepted.
    >
    > **What the predicate costs, stated exactly, because an earlier draft of this note
    > overclaimed it.** That draft said the new bar "is the bar the `# unanchored:` hatch
    > in this module already sets: an exemption costs a written, reviewable claim". It
    > does not. That hatch enforces **twenty characters of real reason**; `DATED_NOTE` is
    > `\d{4}-\d{2}-\d{2}`, shape only, with no calendar validation and no minimum prose,
    > so `> per 1234-56-78` is exempt with no reason at all. The tightening is genuine —
    > one character to ten, plus a claim that shows in a diff — and the deterrent is real
    > but different: the escape route costs writing your new criterion **physically inside
    > somebody else's dated correction note**, where it renders as part of that note and
    > reads as one. That is a placement cost, not a written justification, and it is
    > enough. A sentence claiming parity with a stricter mechanism is the register defect
    > this task spent its whole length on, and it had got inside the amendment written to
    > fix an instance of it.
    >
    > **The run and not the line, measured 2026-09-07 rather than assumed.** The five
    > surviving occurrences sit in runs of **10, 10, 12, 14 and 21 lines**. In all five the
    > date is on the run's opening line and the literal is **one or two lines below it**,
    > so the date is never on the line carrying the literal and a line-local predicate
    > would have reddened all five. The run walk is load-bearing, not defensive. Stated
    > that precisely because the distance, not the run length, is what makes it necessary:
    > an earlier draft of this note said the date sits "several lines" away, which the
    > measurement does not support and which would have been the same register error one
    > more time.
    >
    > **The residual, named rather than left to be found.** A blank line breaks the run,
    > which is Markdown's own rule for where a blockquote ends, so an undated `>` line
    > glued directly onto a dated note with no blank line between them is exempt, as is an
    > indented list-level quote glued to a top-level dated one, which Markdown renders as
    > two containers while the walk sees one. Left as it is: a blank line anywhere between
    > restores the refusal, and the shape every real note in this repo takes is safe.
    > Likewise there is no fence awareness, which fails toward red for an undated `>`
    > inside a fenced block; no scanned document contains the literal inside a fence
    > today.
21. Each finding names the file in POSIX form, the line number, and the line, and the
    message says what to write instead: `el.scrollWidth > el.clientWidth` on `.content`
    and on each rendered row container, because `body` sets `overflow: hidden` and
    `.content` is what scrolls, so the document element's scrollable area cannot grow. The
    message is built by a named helper and asserted directly by a second test, following
    `stale_digest_message` in `tests/test_web_shell.py`.
22. The scan covers neither `tests/` nor `app/`, and a comment says why: the check's own
    source and message contain the banned literal, so a scan over `tests/` would flag
    itself. `app/` contains no occurrence today and the shell is code, not a
    specification.

    > **Corrected 2026-09-07, after the QA verification of this PR.** This criterion used
    > to say "`app/` contains no occurrence today". That is no longer true, and it was
    > made untrue by criterion 4 of this same task: `app/styles.css:67` now carries
    > `document.documentElement.scrollWidth` inside the comment on `body`, because
    > criterion 4 requires that comment to say what the wrong thing to measure is. The
    > true rationale for omitting `app/` is the second half of the sentence and not the
    > first: the shell is code rather than a specification, and the occurrence it now has
    > is the instruction being asked for rather than the defect being refused. No
    > behaviour changes, because `app/` is out of scope either way, and the
    > implementation's own comment already states the corrected reason.
    >
    > **Also recorded, 2026-09-07:** `.claude/rules/testing.md` names the literal on an
    > ordinary non-blockquote line, in the seventh rule this task adds, and it is the one
    > file the mechanism cannot reach, since criterion 20 fixes the scope at `plans/`,
    > `README.md` and `CLAUDE.md`. **It should stay out of scope**, for the same reason
    > `tests/` and this spec are out of scope: a rule has to name the thing it forbids in
    > order to forbid it, and a scan that flags the statement of its own rule is the
    > self-flagging shape this module exists to refuse. Widening the scan to reach it
    > would force the rule to describe the measurement without naming it, which is how a
    > rule stops being followed. The asymmetry is worth knowing rather than fixing: the
    > file that carries the rule is the file the mechanism trusts.
23. The blockquote exemption is deliberate and its comment says so: dated correction notes
    live in blockquotes, so the historical record stays legal while the next criterion
    cannot be written. There is no allowlist, no per-file skip and no marker comment.

    > **Amended 2026-09-07 by PM ruling, after QA returned FAIL on this criterion and the
    > senior review reached the same conclusion from the other direction.** This criterion
    > used to end: "There is no allowlist, no per-file skip and no marker comment." **The
    > implementation has one per-file skip, `SPECIFIES_THE_SCAN` in
    > `tests/test_suite_integrity.py`, holding this file's path and nothing else. The
    > code stays and this claim changes.**
    >
    > Criteria 20, 23 and 41 cannot all hold, because the document that *specifies* a scan
    > necessarily contains the literal the scan forbids. QA measured the collision rather
    > than accepting it, by running the scan's own logic with the exclusion removed: **12
    > non-blockquote findings, all 12 in this file, and zero in every other document.** At
    > head `c10a0f5`, where that was measured, the lines were 29, 180, 263, 327, 421, 447,
    > 481, 538, 603, 798, 802 and 905; these amendments have since shifted the numbers
    > below 327, so the count is what to read and the lines are quoted as at that commit.
    > Three of them
    > name the bare identifier with no `document.` prefix and no old wording to quote, so
    > no blockquote can legitimately hold them and no narrower pattern misses them.
    > Blockquoting this file's own criteria would rewrite criteria 20 and 46 into
    > something that cannot state its own rule; shipping the scan red fails criterion 32.
    >
    > Why this is not the hatch the sentence was written to forbid: it is **one path, in
    > the code rather than in a document**, so a second entry is a reviewable diff and not
    > a magic word a criterion can claim for itself; it holds the specification of the
    > scan and nothing else; and it fails **loud** rather than silent, because a rename
    > stops the path matching and the renamed file gets scanned and reddens naming itself,
    > while a deletion trips an `assert SPECIFIES_THE_SCAN.exists()` added for that case
    > after the review. What the sentence was written to forbid — a per-document opt-out a
    > future criterion can award itself — is still forbidden, and the exemption a document
    > *can* claim is now stricter than when this criterion was written: a dated note, per
    > criterion 20's own amendment above.
    >
    > The reason this is amended rather than left standing: a committed spec asserting a
    > property the committed code knowingly violates is the exact drift this repo dates
    > and annotates everywhere else, and this task adds eleven such notes to other
    > people's files. It would be the one document in the change that does to its reader
    > what `plans/tasks/42-what-the-documents-claim.md` exists about.
24. The module docstring gains one sentence naming issue #58 and stating this third
    refusal, so the module still describes what it does.
25. `test_the_testing_rules_keep_the_three_they_had` and
    `test_the_testing_rules_name_the_mechanisms_that_enforce_them` pass unchanged.

### The rules file

26. `.claude/rules/testing.md` gains a seventh bullet, in the established shape of a rule
    plus the defect that produced it: **a manual check names the element it measures, and
    comes with a way to make it fail.** Scar: this shell's `body` clips and `.content`
    scrolls, so `document.documentElement.scrollWidth === clientWidth` is constant, and
    four task specs asked for exactly that comparison as the test for horizontal overflow;
    the #56 branch shipped three unprotected classes and the criterion's own check would
    have gone green. It names its mechanism, the test in criterion 20, by the file it lives
    in. The heading `## Six rules, each with the defect that produced it` becomes
    `## Seven rules, ...`. The front-matter `paths` list gains `plans/tasks/**` and
    `plans/*.md`, because the rule is for whoever writes a task spec and a rule that is not
    loaded when the spec is being written is not a rule.

### The demonstrations, which are the point

27. **The #56 case, in the three forms it now has.** QA performs all three and records
    every command and every output in the QA note.
    a. Append to the balances block in `app/styles.css` a class in the #56 shape that
       defeats the inherited rule:
       `.balances-fake-line { display: block; font-size: 17px; white-space: nowrap; }`.
       `uv run python -m pytest tests/test_web_shell.py` is **red**, on
       `test_nothing_in_the_shell_takes_the_break_rule_back` and on
       `test_the_figure_is_still_the_only_thing_that_refuses_to_wrap`, and the first
       failure message names `.balances-fake-line`. Remove it; green.
    b. Reproduce the #56 defect as it was literally written: delete the whole
       `.balances-fake-line` rule and instead append three name-bearing classes with no
       `overflow-wrap` of their own. `uv run python -m pytest tests/test_web_shell.py` is
       **green**, and that is the correct answer, because all three inherit
       `overflow-wrap: anywhere` from `body`. Record it as green-and-correct with that
       reason, in the QA note, so nobody later reads this green as the old blindness.
       Remove the three classes.
    c. With the tree clean, delete `overflow-wrap: anywhere` from the `body` rule.
       `uv run python -m pytest tests/test_web_shell.py` is **red** on
       `test_one_declaration_lets_every_long_word_in_the_shell_break`, and the message says
       no `overflow-wrap` declaration was found. Restore it; green. This is the honest
       version of "the check catches #56": the thing protecting those three classes is the
       root declaration, and the suite notices when it goes.
28. **The document check bites.** Add
    `document.documentElement.scrollWidth === clientWidth` to an ordinary criterion line —
    not inside a blockquote — in any file under `plans/tasks/`. The new test in
    `tests/test_suite_integrity.py` is **red**, and the message names the file in POSIX
    form, the line number and the substitute to use. Remove it; green. Then confirm the
    exemption works as designed: the existing note at
    `plans/tasks/13-transfer-drill-down.md:908`, which contains the same literal inside a
    `>` blockquote, does **not** trip it.
29. **The positive control for the manual sweep is written down and reproducible.**
    Criterion 39 states it; the QA note records that it was read and understood even if the
    sweep itself was not run. A manual check with no way to make it fail is what this whole
    task is about, so shipping the corrected sweep without its control would repeat the
    defect in a new place.

### The worker and the suite

30. `app/sw.js` is edited on exactly one line: `SHELL_DIGEST` becomes the twelve hex
    characters `test_the_recorded_digest_matches_the_files_it_covers` prints when it fails.
    That pasted line is the whole fix. The test is never skipped, loosened or worked
    around, and `VERSION` stays `'v4'`.
31. `app/sw.js`'s `SHELL` list, install handler, activate handler, fetch handler and `/api`
    bypass are unchanged, so `test_the_worker_precaches_exactly_the_shell`,
    `test_every_precache_entry_resolves_to_a_file` and
    `test_the_worker_refuses_to_cache_the_api` pass unchanged.
32. Local runs are **chunked**, and the full suite is not run locally: at this size, under
    contention, `uv run python -m pytest` exceeds the agent watchdog. The chunks are
    `uv run python -m pytest tests/test_web_shell.py`,
    `uv run python -m pytest tests/test_suite_integrity.py` and
    `uv run python -m pytest tests/test_shell_behaviour.py`, each green with 0 failed, 0
    skipped and 0 xfailed. The full count is CI's job, on both legs. The PR states the
    arithmetic: `master` is 2481 passing; this task removes one test (criterion 15),
    replaces one with one (criterion 16, net zero), and adds three stylesheet tests plus
    two in `tests/test_suite_integrity.py` (the scan and its message test), for **2485
    passing, 0 skipped, 0 xfailed**. If the number CI reports is not 2485, the arithmetic
    is reconciled before the PR is called ready, because reconciling a count arithmetically
    is the only thing that has ever caught a silently deleted test in this repo.

    > **Corrected 2026-09-07 with the measured figures.** This criterion used to say
    > "`master` is 2481 passing ... for **2485 passing**". Both numbers were stale, and the
    > second was stale twice over, because `master` moved twice while this task was in
    > flight: `889399a` collected 2481, `38ebc1e` (issue #19) took it to 2484, and
    > `c685cee` (issue #57) took it to **2498**. The correct figure for this branch is
    > **2502 passing, 0 skipped, 0 xfailed**, and the clause about reconciling before the
    > PR is called ready is what produced this note rather than a quiet mismatch.
    >
    > It closes against two independent readings, which is the point of reconciling at
    > all. **The absolute**, from `--collect-only -q`: `master` at `c685cee` collects
    > 2498, the branch collects 2502, both measured rather than assumed, and QA measured
    > `master` again in its own worktree and got 2498. **The delta**, read off the diff of
    > the two collected id sets rather than off the composition claimed here: two ids out
    > (`test_a_long_display_name_wraps_rather_than_being_cut_off` and
    > `test_every_line_that_carries_a_name_can_break_a_long_one`) and six in
    > (`test_one_declaration_lets_every_long_word_in_the_shell_break`,
    > `test_nothing_in_the_shell_takes_the_break_rule_back`,
    > `test_the_scroll_container_is_the_content_area_and_not_the_document`,
    > `test_no_balances_rule_declares_a_break_of_its_own`,
    > `test_no_document_asks_for_the_measurement_that_cannot_fail` and
    > `test_the_wrong_measurement_message_says_what_to_write_instead`), so net **+4** and
    > nothing hidden. 2498 − 1 + 0 + 3 + 2 = 2502 = 2498 + 4. **CI is the oracle and
    > agreed on both legs at head `c005194`:** 2502 collected and 2502 passed on
    > `ubuntu-latest` and on `windows-latest`, no skips, no xfails. First measured at
    > `c10a0f5`, one commit earlier, at 2502 passed in 91.53s and 235.01s; every commit
    > after `c005194` changes documentation and comment text only, so the count is
    > unchanged and CI re-runs on each to confirm rather than to discover.

### The browser checklist `(browser check, unrun)`

33. The fixture, so the sweep is reproducible: a group of six members, one whose
    `display_name` is 100 unbroken `W` characters (the schema's cap), one whose name is 40
    unbroken characters, four ordinary; one expense whose description is 500 unbroken
    characters; one expense with an empty description; one suggested payment from the
    signed-in member with usable provenance; one pending claim addressed to the signed-in
    member, so Confirm and Reject are drawn; one rejected claim.
34. The sweep, at 320x568, 360x640, 390x844 and landscape 844x390, with the feed's row
    expanded, the transfer row open and a debt open inside it:

    ```js
    const scope = [...document.querySelectorAll(
      'main.content, main.content *, .curtain:not([hidden]), .curtain:not([hidden]) *'
    )];
    const over = scope.filter(el => el.scrollWidth > el.clientWidth);
    console.log(scope.length, over.map(el => el.className || el.tagName));
    ```

    `over` is empty at every width and in every state, and `scope.length` is recorded, so a
    sweep that examined nothing is distinguishable from one that found nothing.
35. `document.documentElement` is never measured, and the checklist says why in one
    sentence. The boxes to watch are the narrow ones: 258px of content box at the second
    level of nesting and 228px at the third, at a 320px viewport, where an unbroken
    40-character name at 16px runs 300 to 330px.
36. The states outside `.content` are swept too, each on its own: `#gate-error` carrying a
    failed sign-in, `#notice-unlinked`, and `#notice-problem` carrying a server sentence.
    These are the two classes the per-class list never covered.
37. `#add-payer` is opened with the 100-character member in the roster. The `<option>` does
    not wrap, in any engine, and nothing in this task changes that: the record states that
    the closed select is held at the viewport width by
    `.add-field { width: 100%; min-width: 0; max-width: 100% }`, and that the open picker
    popup is browser chrome and outside the page's layout.
38. The two caveats are recorded with the result: `scrollWidth` and `clientWidth` are
    integer-rounded, so a sub-pixel overflow reads as none; and a hidden element reports
    `0` for both, so every collapsed region passes trivially and each one must be opened
    before the sweep.
39. **The positive control.** `document.body.style.overflowWrap = 'normal'` in the console,
    then re-run the sweep from criterion 34: `over` must become non-empty and must name at
    least one class carrying a display name. Reload to clear it. A sweep that cannot be
    made to fail on demand is recorded as no evidence, whatever it returned.
40. **No verdict depends on criteria 33 to 39.** Nothing in this project has ever been
    verified in a browser, and a criterion that needs one is a criterion that will not be
    run. If QA cannot open a browser it records criteria 33 to 39 as **not run**, by that
    name, and the task still passes or fails on criteria 1 to 32. Recording them as "pass"
    without running them is the exact defect this task exists to remove, and is a FAIL
    against #58 whatever else is green.

### The files

41. The files this task creates or edits are exactly these thirteen, and no others in
    either direction:
    * `app/styles.css`
    * `app/sw.js` (one line, `SHELL_DIGEST`)
    * `tests/test_web_shell.py`
    * `tests/test_suite_integrity.py`
    * `.claude/rules/testing.md`
    * `plans/tasks/08-mobile-web-shell.md`
    * `plans/tasks/10-expense-entry-screen.md`
    * `plans/tasks/11-expense-feed.md`
    * `plans/tasks/12-balances-screen.md`
    * `plans/tasks/13-transfer-drill-down.md` (one pointer sentence)
    * `plans/tasks/14-mark-as-paid.md`
    * `plans/tasks/15-receiver-confirmation.md`
    * this spec, with its Findings section filled in

    > **Corrected 2026-09-07.** The entry for `plans/tasks/13-transfer-drill-down.md` used
    > to read "(one pointer sentence)". That was exactly right until criterion 47's
    > amendment added the two stale references QA found in that file, so it is **three
    > notes** now: the pointer added to the existing 2026-09-06 note, plus one on criterion
    > 64 and one on criterion 73. **The list of thirteen files is unchanged** — both
    > additions are in a file it already names, and the count is still exactly thirteen in
    > either direction — so only the description of one entry moved. Recorded because a
    > parenthetical that quietly stops describing the diff is the same defect as a
    > criterion that quietly stops describing the code, in the one document that has no
    > standing to make it.
42. `git diff --stat` shows no path under `src/` or `scripts/`, and does not show
    `app/app.js`, `app/index.html`, `plans/spec.md`, `plans/backlog.md`, `README.md` or
    `CLAUDE.md`.
43. `pyproject.toml` and `uv.lock` are byte-identical to `master`.
44. The nine dated notes required by criteria 45 to 47 are present, in the blockquote shape
    used at `plans/tasks/13-transfer-drill-down.md:907`, dated `2026-09-07`, each naming
    issue #58 and this file. No criterion is renumbered and no criterion body is rewritten
    without its old wording appearing in the note.

    > **Corrected 2026-09-07:** **eleven** notes, not nine. Criterion 47's own amendment
    > records the two QA found that its enumeration missed, both in
    > `plans/tasks/13-transfer-drill-down.md`. Everything else in this criterion is
    > unchanged and holds: the blockquote shape, the date, the naming of issue #58 and this
    > file, no criterion renumbered, and no criterion body rewritten without its old
    > wording appearing in the note. The dated notes added to **this** file by the review
    > of this PR follow the same shape and the same rule, which is why criterion 23's
    > amendment quotes the sentence it replaces rather than editing it away.

### `plans/tasks/`

45. The four wrong-measurement places are corrected, and each note states three things:
    what the line used to say, why the comparison is constant in this shell (`body` clips,
    `.content` scrolls, the root's scrollable area cannot grow), and that there is no
    record of anybody ever running it, so the false assurance was potential rather than
    realised. The corrected line names `.content` and each rendered row container, and the
    property `el.scrollWidth > el.clientWidth`.
    * `plans/tasks/08-mobile-web-shell.md:214-215`
    * `plans/tasks/10-expense-entry-screen.md:505`
    * `plans/tasks/11-expense-feed.md:339`
    * `plans/tasks/12-balances-screen.md:372-373`
46. After criterion 45, no line in any of those four files contains `documentElement`
    outside a blockquote, so criterion 20's check is green on them. This is the test of
    whether the corrections were made in the right shape.
47. The five stale-mechanism places each get a one-line dated note:
    * `plans/tasks/10-expense-entry-screen.md:513` — the people rows no longer set
      `overflow-wrap` themselves; one declaration on `body` covers them.
    * `plans/tasks/11-expense-feed.md:68` — likewise for the feed's shared rule, which is
      where `anywhere` was first chosen and why `anywhere` is what `body` now carries.
    * `plans/tasks/13-transfer-drill-down.md:907-919` — one sentence added to the existing
      note, pointing at this file as where the general case was fixed.
    * `plans/tasks/14-mark-as-paid.md:874-877` — criterion 62's `CARRIES_A_NAME` no longer
      exists; what replaces it, by test name.
    * `plans/tasks/15-receiver-confirmation.md:1000-1003` — the same for criterion 84.

    > **Extended 2026-09-07, after QA reported two the enumeration missed.** This criterion
    > said "The five stale-mechanism places", and there are **seven**. QA found two more
    > references to `test_a_long_display_name_wraps_rather_than_being_cut_off`, which this
    > task deletes:
    >
    > * `plans/tasks/13-transfer-drill-down.md:890-892` — criterion 64 says the test
    >   "passes unchanged". All three properties it names are now asserted file-wide by
    >   `test_nothing_in_the_shell_takes_the_break_rule_back`, and the `nowrap` half is
    >   still asserted block-locally by
    >   `test_the_figure_is_still_the_only_thing_that_refuses_to_wrap`.
    > * `plans/tasks/13-transfer-drill-down.md:966` — the same name inside **criterion
    >   73**'s list of tests that must pass unchanged, at `:957` ("Every other task 12 test
    >   in `tests/test_web_shell.py` passes untouched, by name:"); it was replaced by
    >   `test_no_balances_rule_declares_a_break_of_its_own`. An earlier draft of this note
    >   said criterion 71, which is the deletion of
    >   `test_nothing_asks_for_provenance_that_is_not_in_the_payload` and a different
    >   criterion entirely. The note itself was placed correctly; only this
    >   cross-reference was wrong, which is the failure mode of citing a number from
    >   memory in a document about documents that misname things.
    >
    > Both get a one-line dated note in the same shape, so the total for criteria 45 to 47
    > is **eleven** notes rather than nine.
    >
    > They land in **seven** task files, and decision 6's "Nine places, eight files" was
    > already off by one before these two: the nine places it enumerates fall in tasks 08,
    > 10, 11, 12, 13, 14 and 15, which is seven files, because tasks 10 and 11 each carry
    > two of them. Counted mechanically after landing: 08 one, 10 two, 11 two, 12 one, 13
    > three, 14 one, 15 one. Eleven notes, seven files.
    >
    > **Criterion 41 is affected after all, and an earlier draft of this note said it was
    > not.** That draft concluded criterion 41 was "unaffected, since it counts files
    > edited rather than notes added", which is true of the file count and misses the
    > parenthetical it had just falsified: criterion 41 lists
    > `plans/tasks/13-transfer-drill-down.md` as **"(one pointer sentence)"**, which was
    > exactly right when that file carried one note and eight lines, and is wrong now that
    > it carries three notes. Criterion 41 carries its own dated correction. The
    > thirteen-file list is genuinely unchanged; the description of one entry was not.
    >
    > **Nothing in this task could have caught these, and that is the finding.** The new
    > scan refuses one literal, `documentElement`; it has no opinion about a document
    > naming a test that no longer exists. That is the same class of defect
    > `plans/tasks/42-what-the-documents-claim.md` exists about, and the argument criterion
    > 47 already makes for tasks 14 and 15 applies to these two word for word. A check that
    > refuses a reference to a deleted test name is a real follow-up candidate and is not
    > built here: it needs a definition of "name that should exist", which is a different
    > and larger design than a banned literal.
48. The Findings section of this file is filled in before the PR is opened: the outcome of
    each part of criterion 27, the digest line pasted, the CI count and the arithmetic that
    reaches it, and any place the audit table above turned out to be wrong. An audit table
    written by a PM and never re-checked by the implementer is a description standing in
    for the thing itself.

    > **Corrected 2026-09-07.** This criterion asks for the CI count "before the PR is
    > opened", which is not obtainable in that order: the workflow triggers on
    > `pull_request`, so no CI run exists until the PR does, and the available token cannot
    > dispatch a `workflow_dispatch` run. The Findings were filled in first with the
    > measured local figures and the arithmetic, the PR was opened, and the CI count was
    > pasted in on the first head that both legs reported, `c10a0f5`, at 2502 collected
    > and 2502 passed. The figure recorded here is **2502 collected and 2502 passed on
    > `ubuntu-latest` and on `windows-latest` at `c005194`**, the head the senior review
    > approved, matching the arithmetic exactly. QA scored this criterion PARTIAL for the
    > placeholder that stood in the meantime, which was the right call, and the review then
    > caught the recorded figures naming a head one commit behind the one being reviewed,
    > which is the same staleness one level down; both are fixed.

## Out of scope

* **Any change to `app/app.js` or `app/index.html`.** No class is renamed, no element is
  added, no text moves. The classes that carry a server string are the ones the audit table
  lists; this task changes how they are protected, not what they hold.
* **Adding `white-space: nowrap` to `.expense-figure`.** Named as a real consequence and
  deliberately not done. Under the root declaration a feed amount *could* break mid-number
  where today it cannot, because `overflow-wrap` there was `normal`. It cannot happen in
  practice: `format_amount` at `MAX_CENTS` is 20 characters, roughly 190px at 17px, against
  a 252px content box at 320px, and a break only happens when the word cannot fit its line.
  Making it a third allowed `nowrap` selector would widen criterion 11's equality, and every
  allowance is a place a fourth gets added. Recorded as a follow-up issue candidate instead.
* **`min-width: 0`, and any change to a flex or fieldset sizing declaration.** They stay
  exactly where they are. `anywhere` makes them belt-and-braces rather than load-bearing,
  and removing them is a separate argument with a separate risk.
* **Making the `<option>` in `#add-payer` wrap.** It cannot be made to, by any value of
  `overflow-wrap`. Recorded in criterion 37 as a different mechanism, not fixed here.
* **A headless browser, a CSS parser, a layout engine, jsdom, or any npm anything.** Tier 2
  is refused, not deferred. This is the constraint that makes the static half worth
  building.
* **Teaching `tests/shell_harness.mjs` about styles.** It has no cascade and no layout and
  is not given one. It does not read `app/styles.css` today and must not start.
* **Rewording the vaguer "no horizontal scroll" checklist lines** at `08:393-394`,
  `10:698-701`, `11:486-487`, `12:475-476` and `13:1059-1060`. Imprecise, not false, and
  named here so nobody wonders whether they were missed.
* **Re-verifying, in a browser, that any of the shell actually lays out correctly.** That
  has never been done in this project and this task does not start; it makes the checklist
  correct and honest about being unrun.
* **`CLAUDE.md`, `README.md`, `plans/spec.md` and `plans/backlog.md`.** Nothing about what
  the product is or what works changes. `CLAUDE.md`'s two capability lists are pinned to a
  literal in `tests/test_web_shell.py` and editing it forces a `README.md` edit; there is
  no reason to enter that machinery for a stylesheet declaration.
* **`VERSION` in `app/sw.js`.** Stays `'v4'`. It is reserved for a change to how the worker
  itself behaves; a shipped shell edit moves `SHELL_DIGEST` and nothing else.
* **Any new test module.** The three stylesheet checks go in `tests/test_web_shell.py`
  beside the ones they replace; the document scan goes in `tests/test_suite_integrity.py`
  for the reason given in decision 7.
* **Widening the document scan to `src/`, `app/` or `tests/`.** Decided against, with the
  self-flagging reason, in criterion 22.

## Constraints

* **Files edited: exactly the thirteen in criterion 41.** Nothing else, in either
  direction.
* **`app/styles.css` is precached, so this task moves `SHELL_DIGEST`.** The fix is to paste
  the line `test_the_recorded_digest_matches_the_files_it_covers` prints. Never skip it,
  never loosen it, never delete the file from `SHELL` to make it quiet. `VERSION` stays
  `v4`.
* **No new dependency, no CSS preprocessor, no npm, no `package.json`, no `node_modules`.**
  `pyproject.toml` is not opened and `uv sync` is not needed. Per `CLAUDE.md`, never
  `pip install` or `uv pip install`; `.claude/hooks/guard-deps.hs.sh` blocks the ad hoc
  route anyway. If something here genuinely cannot be built without a package, stop and get
  the user's approval first.
* **The test command is exactly `uv run python -m pytest`.** Plain `uv run pytest` fails on
  this machine with an access-denied spawn error. `node` 20 or later stays a test-time
  requirement and the JavaScript half still runs.
* **Do not run the full suite locally.** At 2481 tests under contention it exceeds the agent
  watchdog. Chunked runs plus CI, per criterion 32. Both CI legs, `ubuntu-latest` and
  `windows-latest`, must be green before a merge, and a branch whose base has moved is
  brought up to date and re-run, because the merge commit is where a stale digest surfaces.
* **`tests/test_suite_integrity.py` scans every module under `tests/` for duplicate
  module-level definitions and for unanchored `pytest.raises(match=)` pins.** Check every
  new test name against the module before settling on it, and run that module first.
* **Existing stylesheet tests are not loosened.** Exactly one changes shape,
  `test_a_long_display_name_wraps_rather_than_being_cut_off`, and criterion 17 accounts for
  all three of its assertions: one is inverted by criterion 16, two are widened from the
  balances block to the whole file by criterion 11. Nothing is skipped, xfailed, renamed to
  claim less, or deleted to keep the suite green.
* **Every new check must be shown to bite**, per criterion 27, following
  `test_the_narrowed_rule_still_bites` and `test_the_narrowed_status_rule_still_bites`. A
  green lint proves nothing on its own; what makes it worth having is a demonstration that
  it still refuses what it names. This task exists because a check nobody made fail was
  believed.
* **Paths in failure messages are POSIX**, via `Path.relative_to(REPO).as_posix()`, and
  files are read with `encoding="utf-8"`, so a message reads identically on Windows and on
  Linux. `tests/test_suite_integrity.py` already has `posix()` and `read()` for this.
* **Every failure message is built by a named helper and asserted directly by its own
  test**, following `stale_digest_message` and `unlisted_shell_file_message` in
  `tests/test_web_shell.py`, so the message cannot rot without a test noticing.
* **Comments carry the reason, not just the rule.** Every decision in criteria 4, 11, 12,
  16, 22 and 23 gets a comment at the point a future author would undo it while tidying.
  The whole reason #56 nearly shipped is that the hazard was written in one comment on one
  screen.
* **Money display is untouched.** No amount is reformatted, no symbol appears, and
  `.balances-figure` keeps its `white-space: nowrap`, so a figure never breaks mid-number.
* **Python 3.12 target.** Type annotations on every new function and a docstring on every
  new name stating the invariant it enforces.
* No test binds a socket, spawns a shell, or writes anywhere but `tmp_path`. Criteria 27 to
  29 are performed by hand, by QA, and are not automated.

## Findings

Filled in on 2026-09-07. Branch `task-58`, rebased twice: first onto `38ebc1e` (issue #19's
end-to-end walk), then onto `c685cee` (issue #57's feed render path), which is what the
"Two branches, one digest" section said would happen. #57 landed first and changed nothing
under `app/`, so its merge did not move `SHELL_DIGEST` and this branch's recorded value
survived the rebase unchanged.

### Criterion 27a: the #56 defect in the form it can still take

Appended to the balances block in `app/styles.css`:

```css
.balances-fake-line {
  display: block;
  font-size: 17px;
  white-space: nowrap;
}
```

`uv run python -m pytest tests/test_web_shell.py` → **3 failed, 143 passed**:

* `test_nothing_in_the_shell_takes_the_break_rule_back`, first, with
  `The selectors in app/styles.css refusing a wrap are ['.balances-fake-line', '.balances-figure', '.tab']. Exactly two are allowed, .balances-figure and .tab, because both hold text of fixed shape. Anything else carrying `white-space: nowrap` cannot use the inherited `overflow-wrap: anywhere`, because nowrap leaves it no soft wrap opportunity to take, which is the form the PR #56 defect can still take.`
* `test_the_figure_is_still_the_only_thing_that_refuses_to_wrap`, with
  `assert ['.balances-figure', '.balances-fake-line'] == ['.balances-figure']`
* `test_the_recorded_digest_matches_the_files_it_covers`, which is not part of the
  demonstration: it fires on **any** edit to a precached file and says nothing about
  wrapping. It is listed here rather than filtered out, because a demonstration that
  hides part of its own output is the thing this task is about.

Removed; `146 passed`.

One correction to the criterion was needed to get this result, and it is a real one. On the
first run the message that fired named no selector: the `white-space` **count** assertion
was written before the selector **equality**, so the reader got
`declares white-space 3 times, with values ['nowrap', 'nowrap', 'nowrap']`, which does not
say where to look. Both assertions fire on the same edit, so the equality now goes first
and the count second, with a comment saying why. Criterion 27a is what caught that, which
is the argument for demonstrating a check rather than reading it.

### Criterion 27b: the #56 defect as literally written — **green, and correct**

`.balances-fake-line` deleted, and three name-bearing classes in the #56 shape appended
with no `overflow-wrap` of their own:

```css
.balances-fake-pending-line { display: block; font-size: 17px; }
.balances-fake-decision     { margin: 0; font-size: 16px; }
.balances-fake-rejected-line { display: block; font-size: 17px; }
```

`uv run python -m pytest tests/test_web_shell.py` → **1 failed, 145 passed**, and the one
failure is `test_the_recorded_digest_matches_the_files_it_covers`, for the mechanical reason
above. To leave no room for doubt that the module is otherwise green, the digest the test
printed was pasted (`03cf37d5a0d4`, temporary) and the module re-run: **146 passed**. Both
runs are recorded; the second is the answer to the criterion.

**This green is correct, and it is not the old blindness.** All three classes inherit
`overflow-wrap: anywhere` from `body`, so all three are protected, so there is nothing for
a check to refuse. A suite that went red here would be asserting a requirement that no
longer exists: that each text-bearing class carry its own copy of a declaration the root
already provides. The requirement that replaced it is that the root declaration exists and
that nothing takes it back, which is what 27a and 27c exercise. Anybody reading this green
later should read it as *the class of defect is gone*, not as *the check cannot see it*.

Both the three classes and the temporary digest were reverted with
`git checkout app/styles.css app/sw.js`; `146 passed`.

### Criterion 27c: deleting the declaration that makes 27b correct

`overflow-wrap: anywhere` deleted from the `body` rule.
`uv run python -m pytest tests/test_web_shell.py` → **2 failed, 144 passed**:

* `test_one_declaration_lets_every_long_word_in_the_shell_break`, with
  `Failed: no overflow-wrap declaration was found in app/styles.css.` followed by the
  prose saying it must be declared exactly once, in the `body` rule, with the value
  `anywhere`, and why each of those three is the requirement.
* the digest test, again mechanically.

Restored; `146 passed`. This is the honest version of "the check catches #56": the thing
protecting those three classes is the root declaration, and the suite notices when it goes.

### Criterion 28: the document check bites

Added to `plans/tasks/12-balances-screen.md` as an ordinary criterion line, not a
blockquote: ``- Demonstration for issue #58: `document.documentElement.scrollWidth === clientWidth`.``

`uv run python -m pytest tests/test_suite_integrity.py` → **1 failed, 53 passed**, on
`test_no_document_asks_for_the_measurement_that_cannot_fail`, with the finding opening
`plans/tasks/12-balances-screen.md:394 names `documentElement`:`, the offending line quoted
beneath it, the reason the comparison is constant in this shell, and the substitute
`el.scrollWidth > el.clientWidth, over `.content` and every element inside it, and over each rendered row container`
plus both caveats. The path is POSIX on Windows, via `posix()`.

Exactly **one** finding, which is the confirmation the criterion asks for: task 13's
existing note at `plans/tasks/13-transfer-drill-down.md:908` contains the same literal
inside a `>` blockquote and does not trip the scan. Removed; `54 passed`.

### `SHELL_DIGEST`

Before: `var SHELL_DIGEST = '00e523e1e797';`
After: `var SHELL_DIGEST = '0b63ef842fcc';`

Pasted verbatim from `test_the_recorded_digest_matches_the_files_it_covers`. `VERSION` stays
`'v4'`. It moved twice on this branch, and both are recorded because the intermediate value
is what the demonstrations below were run against: `97ceadab5f07` once the fifteen
declarations became one, then `0b63ef842fcc` after one sentence of the comment on `body` was
reworded. The second edit is the reason a shipped shell change re-runs this test rather than
trusting the first paste. The value was also re-checked after the rebase onto `c685cee`,
which did not move it, since #57 touched nothing under `app/`.

### The count, and the arithmetic

**The spec's 2485 is stale, and so is the 2481 it was computed from.** `master` moved twice
while this task was in flight:

| | count | why |
|---|---|---|
| `889399a`, the base the spec was written against | 2481 | |
| `38ebc1e`, issue #19 | 2484 | +3: one end-to-end test, plus two suite-integrity ids, because that module derives its module list from the filesystem and a new test module arrives already covered |
| `c685cee`, issue #57 | 2498 | +14 in the JavaScript half |

So the arithmetic reaching this branch's number is **2498 − 1 + 3 + 2 = 2502**:

* **−1** `test_every_line_that_carries_a_name_can_break_a_long_one`, deleted with
  `CARRIES_A_NAME` (criterion 15).
* **±0** `test_a_long_display_name_wraps_rather_than_being_cut_off` replaced by
  `test_no_balances_rule_declares_a_break_of_its_own` (criterion 16). One out, one in.
* **+3** the stylesheet checks (criteria 10 to 12).
* **+2** the document scan and its message test (criteria 20 and 21). Not parametrised, on
  purpose, so this arithmetic stays exact.

`uv run python -m pytest --collect-only -q` on this branch: **2502**. Chunked runs, all with
0 failed, 0 skipped, 0 xfailed:

* `tests/test_web_shell.py` — 146 passed (144 + 3 − 1)
* `tests/test_suite_integrity.py` — 54 passed (52 + 2)
* `tests/test_shell_behaviour.py` — 172 passed, unchanged by this task

**CI, both legs, agreed at head `c005194`:** 2502 collected and 2502 passed on
`ubuntu-latest` and on `windows-latest`, no skips, no xfails. First measured one commit
earlier at `c10a0f5`, at `2502 passed in 91.53s` and `2502 passed in 235.01s`; the review
caught the recorded figures naming that earlier head rather than the head under review,
and every commit after `c005194` changes documentation and comment text only, so the count
is unchanged and CI re-runs to confirm rather than to discover.
QA measured `master` independently in its own worktree and also got 2498, and diffed the
two `--collect-only` id sets to confirm the composition: two ids out, six in, net +4, with
nothing hidden. So the count closes against two independent readings, the absolute and the
delta, rather than against this section's assumption.

The workflow triggers on `pull_request` and the available token cannot dispatch a
`workflow_dispatch` run, so the CI number was not obtainable before the PR existed;
criterion 48 asked for it in that order and now carries a dated note saying so.

### The audit table, re-checked against the tree

Every load-bearing row holds. Confirmed: `app/styles.css` carried exactly fifteen
`overflow-wrap` declarations, at the fifteen lines listed, fourteen `break-word` and one
`anywhere`; `.curtain-text` and `.curtain-error` had none; `display_name` is capped at
**100** by `CHECK (length(display_name) BETWEEN 1 AND 100)` at `store.py:551` and `:578`,
not 40, and `description` at **500** by `store.py:619`; `#gate-error` carries
`class="curtain-error"` and `#notice-problem` carries `class="curtain-text"`; and the gate
is `<div class="curtain gate" id="gate">`, a flex sibling of `<main>`, so neither
`.balances-list` nor `.content` could ever have reached it.

Three refinements, none of which changes a decision:

1. **`.expense-when` is in the shared `anywhere` rule and the table omits it.** The rule at
   `master`'s `app/styles.css:258-266` has six selectors, not the five the table lists. It
   carries a formatted date, so it was bounded and correctly protected either way.
2. **`.curtain-text` is on three elements, not one.** `#gate-lede`, `#notice-unlinked` and
   `#notice-problem`. The table names only `#notice-problem`, which is the one that carries
   the server's own sentence; the other two are fixed literals in the markup. The row's
   conclusion, that the class renders unbounded server prose with no protection, is right.
3. **Exactly one rule became empty**, `.balances-entry-effect`'s second rule, as criterion 3
   predicted. Checked mechanically over the comment-stripped file rather than by eye.

### Two forced wording choices, recorded

1. **Criterion 4's comment cannot spell its two counter-examples with colons.** Criterion 1
   asserts `re.findall(r"overflow-wrap:\s*([a-z-]+)", styles())` is exactly `["anywhere"]`
   over the file *including comments*, and criterion 11 counts `white-space:` the same way.
   A comment containing the literal `overflow-wrap: normal` or `white-space: nowrap` would
   therefore fail the checks it is explaining. The comment names both mechanisms as
   "`white-space` set to `nowrap`" and "`overflow-wrap` set back to `normal`", which carries
   the substance criterion 4 asks for in the only spelling criterion 1 permits.
2. **Criterion 6 and the `.balances-entry-effect` comment.** Criterion 3 deletes that rule
   entirely, so the comment whose subject it was goes with it, while criterion 6 requires
   "the reason a date is not shared with an effect line" to survive. Both are honoured by
   folding the surviving content — that the effect sentence is the one of the two carrying a
   name, that its box is 228px three levels in, and that the date is a fixed spelling with
   nothing to break — into the comment on the rule the two now share, with the one clause
   the deletion made false ("which is why the rule is not shared") replaced by why one rule
   now covers both. The 258px and 228px measurements are preserved in criterion 35 as
   criterion 7 requires, so neither is lost even if that comment is later trimmed.

### Criterion 23's "no per-file skip": flagged, ruled on, and amended

**Criteria 20, 23 and 41 cannot all hold at once, and the collision is in this file.**

Criterion 20 scans every `*.md` under `plans/` for the literal `documentElement` outside a
blockquote. Criterion 41 requires this spec to be committed, under `plans/tasks/`. This
spec names that literal on **nine** ordinary, non-blockquote lines above this section,
because its criteria have to write out what is banned in order to ban it, and this section
adds three more, for **twelve** in the file. At head `c10a0f5`, where QA measured them, they
were lines 29, 180, 263, 327, 421, 447, 481, 538 and 603 plus 798, 802 and 905; the dated
amendments added by the review of this PR have shifted every number after 327, so the counts
are the durable half and the line numbers are quoted as at that commit. Three of the nine
name the bare identifier with no `document.` prefix and no old wording to quote, so no
blockquote can hold them and no narrower pattern can miss them. Criterion 23 then forbids
the one remaining resolution: "There is no allowlist, no per-file skip and no marker
comment."

The three ways out and why two are worse:

* **Blockquote this file's own criteria.** Rewrites criteria 20 and 46 into something that
  cannot state its own rule. Rejected: the criteria are not mine to change.
* **Ship the scan red.** Fails criterion 32, and a red suite is not a mechanism.
* **One scope exclusion, for the document that specifies the check.** Taken. It is
  `SPECIFIES_THE_SCAN` in `tests/test_suite_integrity.py`, holding this file's path and
  nothing else, and its comment states in full that it is a deviation from criterion 23,
  why the three criteria collide, and that it is not a licence for a second entry.

This is exactly the reason criterion 22 already gives for not scanning `tests/`: the check's
own source and message must name the literal to work. The spec that *specifies* the check is
in the same position, and the criteria did not anticipate it. The failure mode of the
exclusion is loud rather than quiet: rename the file and the path stops matching, so the
scan goes red naming the renamed file.

**Ruled on 2026-09-07, and criterion 23 is amended rather than the code changed.** QA
returned FAIL on criterion 23 and the senior review reached the same conclusion from the
other direction, that the deviation is correct and should not be undone. QA proved the
collision instead of accepting it, by running the scan's own logic with the exclusion
removed: 12 non-blockquote findings, all 12 in this file, at exactly the lines named above
plus the three this section adds, and **zero in every other document**. The PM ruling is
that the code stays and the claim changes, because a committed spec asserting a property
the committed code knowingly violates is the drift this repo dates and annotates
everywhere else — and this task adds eleven such notes to other people's files. Criterion
23 now carries a dated amendment quoting the sentence it replaces. Two things were
tightened at the same time, both from the review: the exemption a document can claim is
now a **dated** note rather than a bare `>` (criterion 20's amendment), and
`scanned_documents()` asserts the excluded file still exists, so a deletion cannot leave
the exclusion silently dead the way a rename already could not.

### What the review round changed, and what it did not

QA returned FAIL on criterion 23 and PARTIAL on 48, PASS on everything else in 1 to 32,
and the senior review returned REQUEST CHANGES on one blocking finding. Both are answered
above and in the dated amendments to criteria 11, 20, 22, 23, 32, 44, 47 and 48. Three
things are worth separating out.

**The blocking finding was real and was in the new check, not in the stylesheet.** The
exemption predicate was `text.strip().startswith(">")`, one character, sitting directly
beneath a comment arguing that "an exemption a criterion could claim by writing a magic
word next to itself is how a check stops being one". The comment refuted the code it
introduced, and the failure message advertised the route in its closing paragraph, so a
future author hitting the red test did not even have to find it. In the one module whose
subject is checks that do not exercise what they name, the new check was exempting itself
from its own thesis. It is now the enclosing blockquote run carrying a date, and it turned
nothing red.

**And then the fix overclaimed itself, which is the same defect once more.** The amendment
said the new bar "is the bar the `# unanchored:` hatch already sets: an exemption costs a
written, reviewable claim". It is not: that hatch enforces twenty characters of real
reason, and `DATED_NOTE` is shape only, so `> per 1234-56-78` is exempt with no reason at
all. The deterrent is a **placement** cost — writing your criterion physically inside
somebody else's dated note — which is weaker than a written justification and still
enough. Corrected in criterion 20's amendment, in the code comment, and in the seventh
rule, all three of which now say what the predicate does rather than what it resembles.
Three rounds on one change, each finding the previous round's claim a notch stronger than
its code, is the most useful thing in this task's record.

**Criterion 27a paid for itself twice.** It caught the message that named no selector on
the first run, and QA confirmed the reorder holds and that `['nowrap', 'nowrap', 'nowrap']`
appears nowhere in the output now. The review then found that the count assertion is not
redundant for a better reason than the comment gave: the selector regex only matches rules
containing `white-space: nowrap`, so `white-space: pre` on a new class passes the selector
equality and only the count catches it. Verified by probe before landing —
`['nowrap', 'nowrap', 'pre']` — and the comment now says so, because a reader who believed
the old wording would have deleted the line as a duplicate.

**Two things were reported and deliberately not built.** A check that refuses a document
reference to a deleted test name would have caught the two stale references QA found in
task 13, and nothing here does: this scan refuses one literal and has no notion of a name
that ought to exist. That is a follow-up, and so is the review's larger point, which is
worth recording plainly: **the harness proves the stylesheet says the right thing and
cannot prove the shell lays out.** `overflow-wrap: anywhere` on `body` is necessary and not
sufficient — a fixed-width child, a padding sum over 320px, or a `flex-shrink: 0` item
wider than its container would each produce the exact user-visible defect these criteria
were written to catch, and no check in this task or in the suite sees any of them.
Criterion 40 does not create that gap, it inherits it, but it does convert it from an
embarrassment into a policy. The resolution named is not a headless browser: it is one
dated manual sweep, executed once against criterion 33's fixture and recorded under
`plans/`, so criterion 40's status becomes "last swept, result, scope.length" instead of
"never run, by design" — a staleness measure rather than a blind spot, which is the move
this repo already made for `SHELL_DIGEST`.

### Criteria 33 to 39: **not run**

Recorded as **not run**, by that name, per criterion 40. Nothing in this project has ever
been verified in a browser, no browser was opened for this task, and no verdict here rests
on any of them. Criterion 39's positive control,
`document.body.style.overflowWrap = 'normal'` in the console followed by a re-run of
criterion 34's sweep, is written down and was read and understood, and it is also now
recorded in `.claude/rules/testing.md`'s seventh rule so the next manual check inherits the
habit rather than the blind spot. It was **not executed**. Recording any of 33 to 39 as
"pass" would be the exact defect this task exists to remove.

## Size

Small, and mostly deletion. `app/styles.css` loses fifteen declarations, one rule and
several comment sentences, and gains one declaration and one substantial comment on `body`.
`tests/test_web_shell.py` loses a nine-entry constant and one test, replaces one, and gains
three of roughly fifteen lines each. `tests/test_suite_integrity.py` gains a scan, a message
helper and two tests, perhaps fifty lines. `.claude/rules/testing.md` gains a bullet and two
front-matter lines. The eight task files gain nine short blockquotes.

The expensive part is criterion 27, which is three demonstrations with real runs, and
criterion 45, which is four corrections that have to say why the old line was wrong rather
than just replacing it. Budget for those rather than for the code, and do not shorten
criterion 27b by reasoning about it: the point of that part is that a green result gets
recorded as green with its reason, which is the discipline whose absence is this whole
issue.

If this task grows a headless browser, an npm dependency, a CSS parser, a change to
`app/app.js`, a new test module, or a second per-class list of any kind, it has gone wrong.
