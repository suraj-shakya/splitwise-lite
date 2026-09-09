"""pytest's half of the JavaScript suite: it drives ``tests/shell_harness.mjs``.

The harness runs the shipped ``app/index.html``, ``app/app.js`` and ``app/api.js``
under Node's built-in ``vm`` against a stubbed DOM and a stubbed ``fetch``, and
reports one JSON object on stdout. It runs **once per session**, through the
session-scoped fixture below, and every scenario it reports becomes its own pytest
result, so a failure reads as ``test_scenario[a_refused_sign_in_tells_the_person_why]``
and carries the harness's own message rather than one opaque "node exited 1".

``node`` is a test-time requirement of this repo, named in CLAUDE.md. **A missing or
too old ``node`` is a failure, never a skip**: `.claude/rules/testing.md` forbids
marking a test skipped or expected to fail to make the suite green, and a JavaScript
suite that silently evaporates on a machine without the runtime is that same failure
wearing a hat.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "tests" / "shell_harness.mjs"
APP = REPO / "app"

NODE_MISSING = (
    "node is not on PATH. tests/shell_harness.mjs runs the shipped app/ files under "
    "Node's vm, and CLAUDE.md names node 20 or later as a test-time requirement of "
    "this repo. Install it: this suite fails without it and never skips."
)

# Every scenario the harness runs, in the order it runs them. The harness reports
# exactly this list back, so a scenario deleted from the harness fails pytest and one
# added to the harness without being declared here fails pytest too.
SCENARIOS = [
    # Boot, and what announce() makes of every answer the server can give
    "boot_with_no_session_shows_the_gate",
    "boot_with_a_linked_session_shows_the_app",
    "nothing_from_the_previous_scenario_survives_into_this_one",
    "boot_with_an_unlinked_session_shows_the_not_linked_message",
    "a_403_member_not_linked_shows_the_not_linked_message",
    "a_403_that_is_not_member_not_linked_prints_what_the_server_said",
    "a_network_failure_shows_the_offline_message_and_never_the_gate",
    "a_server_error_prints_what_the_server_said_and_never_the_gate",
    "a_503_naming_the_setup_command_prints_that_sentence",
    "a_503_naming_both_group_ids_prints_both_of_them",
    "a_status_above_five_hundred_nobody_anticipated_is_still_classified",
    "a_status_below_five_hundred_nobody_anticipated_is_not_silently_dropped",
    "a_response_the_client_may_not_read_is_the_same_as_no_answer",
    "a_status_that_is_not_a_number_is_never_taken_for_a_refusal",
    "a_later_failure_does_not_leave_the_earlier_sentence_behind",
    "the_api_client_failing_to_load_shows_the_offline_message",
    # Signing in
    "a_refused_sign_in_tells_the_person_why",
    "a_refused_sign_in_with_an_unreadable_body_still_says_something",
    "a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone",
    "a_successful_sign_in_keeps_the_screen_the_person_was_on",
    "a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate",
    "a_session_that_expires_mid_session_puts_the_server_sentence_on_the_gate",
    "a_sign_in_the_network_interrupted_still_lets_the_gate_come_back",
    "a_session_that_expires_after_a_real_sign_in_still_returns_to_the_gate",
    "a_401_answering_the_sign_in_itself_is_always_the_gate",
    "creating_an_account_signs_in_straight_after",
    "creating_an_account_that_already_exists_says_so_on_the_gate",
    "a_rate_limited_sign_in_reads_on_the_gate_with_no_curtain_over_it",
    "the_submit_control_is_disabled_while_the_sign_in_is_in_flight",
    "the_gate_says_whether_it_is_signing_in_or_creating_an_account",
    "the_gate_switches_the_password_autocomplete_with_the_mode",
    "the_form_never_lets_the_browser_navigate",
    "the_email_is_trimmed_and_the_password_is_not",
    "signing_out_returns_to_the_gate",
    "a_sign_out_the_server_refuses_says_why_rather_than_doing_nothing",
    # Routing
    "routing_shows_one_screen_and_moves_focus",
    "going_back_to_a_screen_reads_it_again",
    "an_unknown_hash_is_replaced_not_pushed",
    # The client
    "every_request_goes_to_the_api_with_credentials",
    "the_csrf_token_is_read_at_request_time_not_cached",
    "a_204_is_not_parsed_as_json",
    "a_refusal_a_screen_asked_for_leaves_the_app_frame_up",
    "the_whole_error_reaches_the_handler_that_registered_for_it",
    "a_rejected_fetch_carries_no_message_of_its_own",
    "a_handler_that_throws_does_not_stop_the_rejection_reaching_the_caller",
    "an_unsupported_selector_is_a_loud_failure_not_a_null",
    # The add screen
    "opening_add_focuses_the_amount_field_and_reads_the_roster",
    "the_add_screen_takes_focus_only_while_it_is_the_current_screen",
    "an_amount_and_one_tap_records_an_equal_split_across_everyone",
    "unticking_someone_sends_an_equal_split_over_the_rest",
    "uneven_amounts_are_sent_as_strings_and_the_blanks_are_left_out",
    "shares_that_do_not_add_up_show_the_resolvers_own_message_and_keep_the_draft",
    "a_save_refused_as_malformed_shows_the_servers_sentence_with_no_id",
    "saving_with_no_amount_typed_asks_for_one_and_sends_nothing",
    "a_successful_save_clears_the_form_and_confirms_from_the_response",
    "a_stale_form_refused_by_the_server_says_so_on_the_screen",
    "the_save_control_is_disabled_while_the_save_is_in_flight",
    "a_second_submit_while_the_first_is_in_flight_sends_one_request",
    "a_roster_that_does_not_arrive_offers_a_retry_and_keeps_what_was_typed",
    "a_group_with_one_member_still_records_an_expense",
    "a_group_with_no_members_says_so_and_saves_nothing",
    "a_save_that_gets_no_answer_never_says_it_saved",
    "the_payer_defaults_to_whoever_is_entering_not_to_the_top_of_the_roster",
    "choosing_a_different_payer_sends_that_member_as_the_payer",
    "the_add_form_never_lets_the_browser_navigate",
    "a_roster_that_arrives_in_the_wrong_shape_is_a_failure_not_an_empty_group",
    "a_second_save_clears_the_first_confirmation_before_it_goes_out",
    "a_refused_save_followed_by_a_good_one_leaves_no_stale_message",
    "leaving_add_and_coming_back_starts_a_fresh_entry",
    "a_roster_without_the_acting_member_defaults_to_the_first_one",
    "switching_modes_twice_still_names_every_member_once",
    "a_save_refused_while_the_roster_loads_stops_saying_so_once_it_arrives",
    "a_save_refused_while_the_roster_loads_still_reads_true_when_the_roster_is_empty",
    "a_zero_amount_is_refused_in_the_resolvers_own_words_and_keeps_the_draft",
    # A screen that waits for a session, and a draft that survives signing back in
    "a_route_change_behind_the_gate_asks_for_nothing_and_leaves_the_gate_alone",
    "a_route_change_behind_the_not_linked_notice_asks_for_nothing",
    "a_route_change_under_a_curtain_a_live_session_raised_asks_for_nothing",
    "a_route_change_with_no_api_client_loaded_asks_for_nothing",
    "the_retry_controls_behind_the_gate_ask_for_nothing",
    "an_interrupted_save_keeps_what_was_typed_through_signing_back_in",
    "an_interrupted_save_keeps_the_split_mode_and_rebuilds_the_person_rows",
    "signing_out_clears_the_draft_before_the_next_person_signs_in",
    "a_sign_out_the_server_refuses_leaves_the_draft_alone",
    "a_401_on_save_then_a_different_person_signs_in_starts_a_fresh_entry",
    "a_401_on_save_then_a_different_person_signs_in_returns_the_split_to_equally",
    # The debts path
    "the_api_client_builds_a_debt_path_from_two_ids",
    # The transfer drill-down
    "opening_a_suggested_payment_shows_both_ends_of_it",
    "a_payment_to_someone_you_never_shared_an_expense_with_says_why",
    "a_payment_that_settles_one_debt_directly_shows_it_once",
    "a_debt_split_across_two_payments_shows_each_share_of_the_whole",
    "a_payment_that_covers_a_whole_debt_does_not_say_of_itself",
    "a_transfer_row_without_provenance_is_not_tappable",
    "a_second_payment_opens_without_closing_the_first",
    "opening_a_debt_lists_the_expenses_behind_it",
    "the_waiting_line_is_on_screen_before_the_request_goes_out",
    "the_expenses_behind_a_debt_are_asked_for_once",
    "a_debt_whose_expenses_do_not_arrive_says_so_and_can_be_asked_again",
    "a_debt_with_nothing_behind_it_says_so_rather_than_failing",
    "a_debt_that_answers_with_the_wrong_shape_is_a_failure_not_an_empty_debt",
    "a_member_missing_from_the_roster_still_shows_the_debt",
    "a_drill_down_behind_a_curtain_asks_for_nothing",
    "a_401_on_a_drill_down_is_the_gate_and_not_this_screens_message",
    "opening_a_payment_changes_no_route_and_no_history",
    "leaving_the_balances_screen_and_returning_closes_every_drill_down",
    # The four states the drill-down hint has to be gone in
    "the_hint_goes_while_the_next_read_is_in_flight",
    "a_failed_read_leaves_no_hint_beside_the_failure",
    "a_group_with_no_member_rows_shows_no_hint",
    "a_group_with_nothing_left_to_settle_shows_no_hint",
    # Marking a payment as paid
    "the_payer_can_mark_a_suggested_payment_as_paid",
    "marking_a_payment_paid_announces_it_before_and_after_the_request",
    "tapping_mark_as_paid_twice_records_one_settlement",
    "a_payment_that_will_not_record_says_so_and_can_be_tried_again",
    "a_payment_someone_else_owes_offers_no_way_to_mark_it_paid",
    "a_payment_already_marked_as_paid_says_so_instead_of_offering_the_button",
    "a_transfer_row_without_provenance_offers_no_way_to_mark_it_paid",
    "everyone_sees_the_same_payment_awaiting_confirmation",
    "a_pending_payment_leaves_the_suggested_payment_where_it_was",
    "a_pending_row_the_screen_cannot_read_is_left_out_rather_than_guessed_at",
    "marking_a_payment_paid_behind_a_curtain_asks_for_nothing",
    "an_unlinked_account_is_offered_no_way_to_mark_anything_paid",
    "leaving_the_balances_screen_and_returning_clears_the_pending_list",
    "a_group_with_nothing_left_to_settle_still_shows_a_pending_payment",
    # The receiver answers a claim
    "the_receiver_can_confirm_a_payment_that_was_marked_as_paid",
    "the_receiver_can_reject_a_payment_that_was_marked_as_paid",
    "confirming_a_payment_announces_it_before_and_after_the_request",
    "confirming_a_payment_reads_the_figures_again_and_says_what_changed",
    "an_answer_whose_refresh_fails_still_says_the_answer_was_recorded",
    "tapping_confirm_twice_answers_one_settlement",
    "tapping_reject_after_confirm_sends_one_answer",
    "an_answer_that_will_not_record_says_so_and_can_be_tried_again",
    "the_payer_is_offered_no_way_to_answer_their_own_claim",
    "a_third_member_is_offered_no_way_to_answer_someone_elses_claim",
    "everyone_sees_the_same_rejected_payment",
    "a_rejected_payment_can_be_marked_as_paid_again",
    "a_rejected_row_the_screen_cannot_read_is_left_out_rather_than_guessed_at",
    "answering_a_payment_behind_a_curtain_asks_for_nothing",
    "an_unlinked_account_is_offered_no_way_to_answer_anything",
    "leaving_the_balances_screen_and_returning_clears_the_rejected_list",
    "confirming_the_last_claim_in_a_settled_group_reads_the_figures_again",
    "the_api_client_builds_a_decision_path_from_a_settlement_id",
    # What a feed row shows. The first scenarios in this repo to render one.
    "a_feed_row_names_the_payer_the_amount_and_what_it_was_for",
    "a_feed_with_nothing_recorded_says_so_and_draws_no_row",
    "the_rows_stay_in_the_order_the_server_sent_them",
    "an_expense_described_in_markup_reaches_the_screen_as_text",
    "an_expense_with_no_description_still_names_everything_else",
    "opening_a_row_shows_every_share_and_the_total_they_are_shares_of",
    "a_payer_who_is_not_sharing_is_said_so_rather_than_added_to_the_split",
    "a_member_the_roster_does_not_know_reads_as_words_not_as_an_id",
    "four_people_sharing_one_expense_read_as_two_names_and_a_count",
    "leaving_the_feed_and_coming_back_draws_each_row_once",
    "a_created_at_that_is_not_a_date_never_reads_as_nan",
    # Task 16: the incompleteness signal. The feed carries the age signal only.
    "a_stale_feed_shows_how_old_the_newest_expense_is",
    "a_fresh_feed_says_nothing_about_its_age",
    "the_feed_obeys_the_state_and_not_the_day_count",
    # And the balances screen carries both halves of it.
    "a_group_with_nothing_recorded_says_so_beside_the_figures",
    "a_stale_balance_names_who_has_entered_nothing",
    "a_quiet_member_the_roster_does_not_know_reads_as_words_not_as_an_id",
    "a_payload_with_no_staleness_at_all_draws_neither_signal",
    "a_staleness_state_the_client_does_not_recognise_draws_nothing",
    "one_quiet_member_reads_grammatically",
]

# The committed mutants the harness is measured against: anchored substitutions applied
# to the real source at run time. None is a committed copy of a shipped file, so none
# can rot into a false pass or be served to a browser by accident, and the text lives
# here where a reviewer reads it rather than buried in the harness.
#
# Mutant A: show() also hides the gate error. A one-line tidy of the kind a later
# screen task makes, and it looks like an improvement, because every other
# curtain-switching concern already lives in show(). submitted() writes the message,
# reveals it, then calls show('gate'), which now hides it again.
MUTANT_A = {
    "file": "app/app.js",
    "find": "gate.hidden = which !== 'gate';",
    "replace": "gate.hidden = which !== 'gate';\n    gateError.hidden = true;",
}
# Mutant B: the 401 handler is deferred to a macrotask and blanks the gate when it
# finally runs, so submitted()'s catch writes the message first and the deferred
# showGate() wipes it afterwards. app/app.js is untouched entirely, and this is only
# visible once the timer queue has drained.
#
# Re-expressed by task 32, which changed what the handler is handed. Before it,
# onUnauthenticated always called showGate('') and the bare deferral was enough to
# blank a message the caller had just written. Now the handler is handed error.say and
# prints the server's own sentence, which for a refused sign-in is the same sentence
# submitted() writes, so the two agree and a bare deferral leaves the gate reading
# correctly. Blanking say inside the deferred call restores the pre-task behaviour
# exactly, and the defect it reintroduces is the same one: a message written by the
# caller and wiped by a handler that ran late. The bare deferral is still caught, by
# a_refused_sign_in_with_an_unreadable_body_still_says_something, where there is no
# server sentence for the two writers to agree on.
MUTANT_B = {
    "file": "app/api.js",
    "find": "handlers.unauthenticated(error);",
    "replace": (
        "setTimeout(function () { error.say = ''; "
        "handlers.unauthenticated(error); }, 0);"
    ),
}
# Mutant C: the default arm of the classifier stops classifying. Every status the
# ladder above it did not name comes back as a kind that no handler speaks for, which
# is the fall through task 32 removed: announce() was three ifs and no else, so a 429
# on sign-in and a 409 on signup reached nobody and the screen did not change. This
# mutant is why the default arm has to be a classification and not a shrug.
MUTANT_C = {
    "file": "app/api.js",
    "find": "return 'refused';",
    "replace": "return '';",
}
# Mutant D: the feed goes back to asking only whether the client has loaded, which is
# what all three screens asked before there was a session guard, and is defect 1 in
# the shape it shipped in. The app still works for somebody signed in; what comes back
# is one screen reading the ledger while a curtain is over it, and a request certain to
# be refused going out on every route change made by somebody who is signed out.
MUTANT_D = {
    "file": "app/app.js",
    "find": "if (!ledgerIsUp() || window.location.hash !== FEED_ROUTE || feedBusy) {",
    "replace": "if (!api || window.location.hash !== FEED_ROUTE || feedBusy) {",
}
# Mutant E: showApp() clears the add form again, which is defect 2 exactly. A curtain
# coming down is treated as a visit to the screen, so the draft the 401 correctly
# preserved is thrown away by the person doing the one thing the gate is telling them
# to do. Every other screen behaves, and so does the add screen on a real navigation:
# only the resume is wrong, which is why a scenario that navigates cannot see it.
MUTANT_E = {
    "file": "app/app.js",
    "find": "addResumed();",
    "replace": "addEntered();",
}
# Mutant F: the resume keeps the draft for whoever signs in next, which is the shape
# this branch itself first shipped and the defect review found in it. The identity
# check is switched off rather than the lines deleted, so the anchor stays on one line
# and cannot rot on a checkout whose line endings differ; the effect is the same, which
# is a draft cleared on a confirmed sign out and nowhere else, on a path where nobody
# signs out. Sam types an expense, takes a 401 on save, hands the phone to Ali, Ali
# signs in, and Sam's amount and description are on screen with Ali named as the payer
# of them. The screen still works for one person, which is what makes this a
# shared-phone defect rather than a resume that stopped resuming.
MUTANT_F = {
    "file": "app/app.js",
    "find": "if (addActingId() !== addDraftMember) {",
    "replace": "if (false) {",
}

# Mutant G: the row names whoever recorded the expense instead of whoever paid for
# it. On a shared ledger the payer is who is owed the money, so this is the wrong
# person being owed, said out loud on the screen everybody opens the app on. It is one
# token, of the kind a later task makes while tidying two nearby field reads, and it
# survived everything in this repo until now: tests/test_feed_screen.py reads the
# static committed document and cannot see a rendered row, and no scenario rendered
# one, because feedRender's document.createDocumentFragment threw and loadFeed's
# .then(done, done) absorbed the throw. The row fixture therefore has payer_id
# different from created_by, and this mutant is what proves the new scenarios kill
# something in code that was dead before this task.
MUTANT_G = {
    "file": "app/app.js",
    "find": "'Paid by ' + feedNameFor(names, entry.payer_id)",
    "replace": "'Paid by ' + feedNameFor(names, entry.created_by)",
}

# Mutant H: the `never` arm is removed and every state that is not `fresh` takes the
# age arm. This is the #44 defect in this feature's own shape, and #44 is the reason
# the wire carries a three-valued state at all: a roster known to be empty was rendered
# with the words for a roster that had not arrived. Here a ledger known to hold nothing
# is rendered with the words for a ledger of known age, and because there is no age the
# number printed into the sentence is the word `null`.
#
# It is one line of tidying, of exactly the kind a later task makes: three states, so
# "not fresh" reads as "old", and the two branches collapse into one. It qualifies
# under all three of plans/mutations/README.md's tests. It is the only evidence the
# `never` scenario bites, because that scenario passed the moment it was written and a
# scenario that passes proves nothing on its own. It survives against the code as it
# was before that scenario existed, because nothing in this repository rendered a
# staleness state until this task. And it leaves a working app with one sentence wrong
# rather than a smoking crater: every figure still draws, the quiet list still draws,
# the feed is untouched, and only the balances screen's own account of what it does not
# know is false.
# The anchor is one line, and that is not incidental: MUTANT_F records that a
# multi-line anchor rots on a checkout whose line endings differ, and this one was
# first written across three lines and matched zero times on this working tree, which
# is CRLF. The two arms of the toggler are ordered stale-then-never so that one line
# carries the whole mutation.
MUTANT_H = {
    "file": "app/app.js",
    "find": "    if (state === 'stale') {",
    "replace": "    if (state !== 'fresh') {",
}


# Mutant I: the empty path withdraws the refusal, which is the fix issue #44 analysed
# and rejected. addRosterArrived() is called before addRosterState('empty'), so a Save
# tapped while the roster was in the air is answered, and then the empty roster that
# lands a moment later silently un-answers it. The screen goes quiet in the one state
# where a screen reader has just been told something: #add-error carries role="alert"
# and #add-empty-roster is a plain note, so the tap ends up answered by nothing at all.
#
# It qualifies under all three of plans/mutations/README.md's tests. It is the only
# evidence that the new scenario's "still refused" assertion bites, because that
# assertion passed the moment it was written and a scenario that passes proves nothing
# on its own. It survives against the code as it was before this task, being the exact
# repair the issue proposed and then rejected, so it names a defect that could really
# have shipped rather than one invented to be killed. And it leaves a working app with
# one behaviour broken: a_group_with_no_members_says_so_and_saves_nothing taps Save
# after the roster has already landed, so nothing withdraws its refusal and it stays
# green, which is asserted below beside the named control.
#
# The anchor is one line, and that is not incidental: MUTANT_F and MUTANT_H both record
# that a multi-line anchor rots on a checkout whose line endings differ, and this
# working tree is CRLF. One line carries the whole mutation because the insertion goes
# in front of it.
MUTANT_I = {
    "file": "app/app.js",
    "find": "          addRosterState('empty');",
    "replace": "          addRosterArrived();\n          addRosterState('empty');",
}

REFUSED = "a_refused_sign_in_tells_the_person_why"
# Named, and unrelated to either mutation: a mutant has to leave a working app with
# one specific behaviour broken, not a smoking crater.
UNRELATED = "an_unknown_hash_is_replaced_not_pushed"
# The two feed scenarios named from more than one place below. THE_EMPTY_FEED is the
# one that never reaches feedRender, so it is the named survivor of anything that
# breaks the render path.
THE_ROW = "a_feed_row_names_the_payer_the_amount_and_what_it_was_for"
THE_EMPTY_FEED = "a_feed_with_nothing_recorded_says_so_and_draws_no_row"


def node() -> str:
    """The resolved interpreter path, passed as argv[0] so the subprocess does not
    depend on Windows resolving `node` through PATHEXT."""
    found = shutil.which("node")
    assert found is not None, NODE_MISSING
    return found


def run_harness(
    config: dict[str, Any], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """One harness run. The configuration goes in as JSON on stdin, so the mutant text
    lives in this file where a reviewer reads it, not buried in the harness."""
    argv = [node(), str(HARNESS)]
    try:
        return subprocess.run(
            argv,
            input=json.dumps(config),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
            cwd=None if cwd is None else str(cwd),
        )
    except subprocess.TimeoutExpired as expired:
        stderr = expired.stderr or ""
        if isinstance(stderr, bytes):  # pragma: no cover - text=True gives str
            stderr = stderr.decode("utf-8", "replace")
        pytest.fail(
            "tests/shell_harness.mjs did not finish within 60 seconds.\n"
            f"stderr:\n{stderr}"
        )


def parse_report(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """The report, or one readable pytest failure. Never a JSONDecodeError traceback:
    the exit status and stderr are what say what went wrong."""
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"tests/shell_harness.mjs exited {completed.returncode} but its stdout is "
            f"not JSON.\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


@pytest.fixture(scope="session")
def harness_run() -> subprocess.CompletedProcess[str]:
    """One process for the whole session, against the unmodified files."""
    return run_harness({})


@pytest.fixture(scope="session")
def report(harness_run: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """The report, whatever verdict it carries.

    **Exit 1 is not an error here.** It is the harness's normal answer when a scenario
    fails, and it has to flow through to the per-scenario results below: a guard on it
    turns one real defect into an error on every test in this file, all carrying the
    same blob, with the scenario that names the defect indistinguishable from the ones
    that passed. That is worse than no harness at all, and it is the opposite of what
    this file's docstring promises.

    Only a harness error stops the file, and it stops it here because then there is no
    report to read: exit 2, stdout that will not parse, or a timeout, each with its own
    message.
    """
    if harness_run.returncode not in (0, 1):
        pytest.fail(
            f"tests/shell_harness.mjs failed as a harness rather than reporting a "
            f"scenario failure: it exited {harness_run.returncode}.\n"
            f"stderr:\n{harness_run.stderr}"
        )
    return parse_report(harness_run)


def results(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["name"]: entry for entry in report["scenarios"]}


def test_node_is_installed_and_recent_enough() -> None:
    found = shutil.which("node")
    assert found is not None, NODE_MISSING
    completed = subprocess.run(
        [found, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    reported = completed.stdout.strip()
    assert reported.startswith("v"), reported
    major = int(reported[1:].split(".")[0])
    assert major >= 20, (
        f"node {reported} is too old. tests/shell_harness.mjs targets node 20 or "
        "later, which CLAUDE.md names as a test-time requirement of this repo."
    )


def test_the_harness_exits_zero_against_the_shipped_files(
    harness_run: subprocess.CompletedProcess[str],
) -> None:
    assert harness_run.returncode == 0, harness_run.stderr


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario(report: dict[str, Any], name: str) -> None:
    found = results(report)
    assert name in found, f"tests/shell_harness.mjs did not run {name}"
    entry = found[name]
    assert entry["passed"], "\n".join([f"{name} failed:", *entry["failures"]])


def test_the_harness_reports_exactly_the_declared_scenarios(
    report: dict[str, Any],
) -> None:
    assert [entry["name"] for entry in report["scenarios"]] == SCENARIOS


# --- The committed mutants, each one permanently red ------------------------


def mutated(mutant: dict[str, str]) -> str:
    """The shipped source with the mutation applied, the way the harness applies it."""
    source = (REPO / mutant["file"]).read_text(encoding="utf-8")
    assert source.count(mutant["find"]) == 1, (
        f"the anchor {mutant['find']!r} no longer matches exactly once in "
        f"{mutant['file']}; re-express the mutant rather than weakening it"
    )
    return source.replace(mutant["find"], mutant["replace"])


def loaded_under(mutant: dict[str, str]) -> dict[str, str]:
    """The two sources as the harness loads them under this mutant: the file the
    mutant names, mutated, and the other one exactly as it ships."""
    return {
        name: mutated(mutant)
        if name == mutant["file"]
        else (REPO / name).read_text(encoding="utf-8")
        for name in ("app/app.js", "app/api.js")
    }


def submitted_body(source: str) -> str:
    """The slice the deleted structural test used to read: app.js from
    ``function submitted(`` up to ``function wire(``."""
    start = source.index("function submitted(")
    return source[start : source.index("function wire(", start)]


def killed(mutant: dict[str, str]) -> dict[str, dict[str, Any]]:
    completed = run_harness({"substitutions": [mutant]})
    # Exactly 1, never merely non-zero: a substitution that broke the file into a
    # syntax error exits 2, and would otherwise be mistaken for a killed mutant.
    assert completed.returncode == 1, (
        f"expected exit 1, got {completed.returncode}.\nstderr:\n{completed.stderr}"
    )
    return results(parse_report(completed))


def test_mutant_a_hiding_the_gate_error_in_show_is_killed() -> None:
    found = killed(MUTANT_A)
    assert not found[REFUSED]["passed"]
    messages = " ".join(found[REFUSED]["failures"])
    # The right failure, not a coincidence: it is the gate error that went missing.
    assert "gate-error" in messages, messages
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # The proof the deleted structural test could not have seen it: the one function
    # it read is byte-identical under the mutation.
    shipped = (REPO / "app" / "app.js").read_text(encoding="utf-8")
    loaded = loaded_under(MUTANT_A)
    assert loaded["app/app.js"] != shipped
    assert submitted_body(loaded["app/app.js"]) == submitted_body(shipped)


def test_mutant_b_deferring_the_401_handler_is_killed() -> None:
    found = killed(MUTANT_B)
    assert not found[REFUSED]["passed"]
    messages = " ".join(found[REFUSED]["failures"])
    assert "gate-error" in messages, messages
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # Mutant B lands in app/api.js and leaves app/app.js alone entirely, which is the
    # point: the structural test read the one file this mutation never touches.
    shipped = (REPO / "app" / "app.js").read_text(encoding="utf-8")
    loaded = loaded_under(MUTANT_B)
    assert loaded["app/api.js"] != (REPO / "app" / "api.js").read_text(encoding="utf-8")
    assert loaded["app/app.js"] == shipped
    assert submitted_body(loaded["app/app.js"]) == submitted_body(shipped)


def test_mutant_c_a_classifier_that_drops_what_it_does_not_recognise_is_killed() -> None:
    found = killed(MUTANT_C)
    # The gate is where the fall through was doing its damage: a 429 the server
    # explained reaches nobody, so the person is told nothing and can only try again.
    dropped = "a_rate_limited_sign_in_reads_on_the_gate_with_no_curtain_over_it"
    assert not found[dropped]["passed"]
    messages = " ".join(found[dropped]["failures"])
    assert "gate-error" in messages, messages
    # A working app with one behaviour broken, not a smoking crater: a 401 is claimed
    # by a row above the default, so signing in still works and still says why when it
    # is refused.
    assert found[REFUSED]["passed"], found[REFUSED]["failures"]
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # One file, one line, and app/app.js untouched: the classification lives in the
    # client and nowhere else, so that is the only place a mutation of it can land.
    loaded = loaded_under(MUTANT_C)
    assert loaded["app/app.js"] == (REPO / "app" / "app.js").read_text(encoding="utf-8")


# The three scenarios that stand or fall with the mutants below. None turns red on
# master, because no defect here was pinned by anything before them: a new scenario
# that passes proves nothing on its own, and these mutants are what prove it bites.
BEHIND_THE_GATE = "a_route_change_behind_the_gate_asks_for_nothing_and_leaves_the_gate_alone"
THE_DRAFT = "an_interrupted_save_keeps_what_was_typed_through_signing_back_in"
SHARED_PHONE = "a_401_on_save_then_a_different_person_signs_in_starts_a_fresh_entry"


def test_mutant_d_a_screen_that_only_checks_the_client_loaded_is_killed() -> None:
    found = killed(MUTANT_D)
    assert not found[BEHIND_THE_GATE]["passed"]
    messages = " ".join(found[BEHIND_THE_GATE]["failures"])
    # The right failure, not a coincidence: the feed asked the server for the ledger
    # on a route change made by somebody who is looking at the sign-in gate.
    assert "GET /api/expenses" in messages, messages
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # One screen broken, not the app: the other two still wait for a session, and
    # somebody signed in still gets their feed.
    assert found["boot_with_a_linked_session_shows_the_app"]["passed"]


def test_mutant_e_clearing_the_draft_when_the_curtain_lifts_is_killed() -> None:
    found = killed(MUTANT_E)
    assert not found[THE_DRAFT]["passed"]
    messages = " ".join(found[THE_DRAFT]["failures"])
    # The right failure: the amount that was typed is gone from the field.
    assert "#add-amount" in messages, messages
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # A navigation still clears, which is what makes this a resume defect rather than
    # a clearing that stopped happening altogether.
    assert found["leaving_add_and_coming_back_starts_a_fresh_entry"]["passed"]


def test_mutant_f_a_resume_that_hands_one_persons_draft_to_another_is_killed() -> None:
    found = killed(MUTANT_F)
    assert not found[SHARED_PHONE]["passed"]
    messages = " ".join(found[SHARED_PHONE]["failures"])
    # The right failure, and it is the money one: the amount Sam typed is on screen in
    # front of Ali, whom the rebuilt picker has already named as its payer.
    assert "12.50" in messages, messages
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # The same person coming back still keeps their draft. That is what makes this an
    # identity defect rather than a resume that stopped keeping anything, and it is
    # why a scenario in which the same person signs back in cannot see it. Every
    # scenario written before this one had one person in it.
    assert found[THE_DRAFT]["passed"], found[THE_DRAFT]["failures"]


def test_mutant_g_a_row_that_names_the_recorder_rather_than_the_payer_is_killed() -> None:
    found = killed(MUTANT_G)
    assert not found[THE_ROW]["passed"]
    messages = " ".join(found[THE_ROW]["failures"])
    # The right failure, and it is the money one: the row names Sam, who typed the
    # expense in, where it must name Cass, who paid for it and is owed for it.
    assert "Paid by Cass" in messages, messages
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # A working app with one line of one screen wrong, not a crater: the empty feed,
    # which never reaches feedRender, is untouched.
    assert found[THE_EMPTY_FEED]["passed"], found[THE_EMPTY_FEED]["failures"]
    # And app/api.js is not where a display name is chosen, so the mutation lands in
    # one file and leaves the client exactly as it ships.
    loaded = loaded_under(MUTANT_G)
    assert loaded["app/api.js"] == (REPO / "app" / "api.js").read_text(encoding="utf-8")


NOTHING_RECORDED_SCENARIO = "a_group_with_nothing_recorded_says_so_beside_the_figures"
THE_STALE_BALANCE = "a_stale_balance_names_who_has_entered_nothing"


def test_mutant_h_a_ledger_with_no_expense_rendered_as_one_of_known_age_is_killed() -> None:
    found = killed(MUTANT_H)
    assert not found[NOTHING_RECORDED_SCENARIO]["passed"]
    messages = " ".join(found[NOTHING_RECORDED_SCENARIO]["failures"])
    # The right failure, and it is the #44 one: the sentence that states an age is on
    # screen for a ledger that has no age, with the word `null` where the number goes.
    assert "null" in messages, messages
    assert "balances-stale" in messages or '"stale":true' in messages, messages
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # A working app with one sentence wrong, not a crater: a ledger that does have an
    # age still reads correctly, which is what makes this the `never` arm's defect
    # rather than the toggler having stopped working.
    assert found[THE_STALE_BALANCE]["passed"], found[THE_STALE_BALANCE]["failures"]
    # And app/api.js is not where a sentence is chosen, so the mutation lands in one
    # file and leaves the client exactly as it ships.
    loaded = loaded_under(MUTANT_H)
    assert loaded["app/api.js"] == (REPO / "app" / "api.js").read_text(encoding="utf-8")


THE_EMPTY_ROSTER_REFUSAL = (
    "a_save_refused_while_the_roster_loads_still_reads_true_when_the_roster_is_empty"
)
THE_SETTLED_EMPTY_ROSTER = "a_group_with_no_members_says_so_and_saves_nothing"


def test_mutant_i_an_empty_roster_withdrawing_a_refusal_that_is_still_true_is_killed() -> None:
    found = killed(MUTANT_I)
    assert not found[THE_EMPTY_ROSTER_REFUSAL]["passed"]
    messages = " ".join(found[THE_EMPTY_ROSTER_REFUSAL]["failures"])
    # The right failure, not a coincidence, and the substring is the failing
    # assertion's own label taken from the run rather than invented ahead of it: the
    # alert that answered the tap is down again once the empty roster lands, so all
    # three error children read false where the middle one must still read true.
    assert "the three error children once the empty roster landed" in messages, messages
    assert "[false,false,false]" in messages, messages
    assert found[UNRELATED]["passed"], found[UNRELATED]["failures"]
    # A working app with one behaviour broken rather than a crater: a Save tapped after
    # an empty roster has already landed is still refused, because nothing on that path
    # withdraws anything. That is what makes this the in-flight defect and not a refusal
    # that stopped working, and it is why a scenario tapping Save in one settled state
    # cannot see it.
    assert found[THE_SETTLED_EMPTY_ROSTER]["passed"], found[THE_SETTLED_EMPTY_ROSTER][
        "failures"
    ]
    # And app/api.js is not where a refusal is raised, so the mutation lands in one file
    # and leaves the client exactly as it ships.
    loaded = loaded_under(MUTANT_I)
    assert loaded["app/api.js"] == (REPO / "app" / "api.js").read_text(encoding="utf-8")


# --- Task 16: the harness fixtures cannot drift from the contract ----------

# The four keys and the three state values the harness stubs. Rule (d) of
# .claude/rules/testing.md is exactly this defect: a fixture that is both the stubbed
# response and the expected value cannot detect its own drift, and a harness constant
# set to nonsense once stayed green across three scenarios. So each of these is
# asserted against src/splitwise_lite/web.py as text, in the shape
# test_every_error_code_the_harness_names_appears_in_web_py already uses.
STALENESS_KEYS = (
    "state",
    "days_since_last_expense",
    "quiet_after_days",
    "quiet_member_ids",
)
STALENESS_STATES = ("never", "fresh", "stale")


def web_py() -> str:
    return (REPO / "src" / "splitwise_lite" / "web.py").read_text(encoding="utf-8")


def test_every_staleness_key_the_harness_stubs_appears_in_web_py() -> None:
    web = web_py()
    harness = HARNESS.read_text(encoding="utf-8")
    for key in STALENESS_KEYS:
        assert f'"{key}"' in web, key
        assert f"{key}:" in harness, key


def test_every_staleness_state_the_harness_stubs_appears_in_web_py() -> None:
    # The three the wire can carry. `ancient`, which one scenario stubs on purpose, is
    # deliberately absent from both: that scenario is about a state no server sends.
    web = web_py()
    harness = HARNESS.read_text(encoding="utf-8")
    for state in STALENESS_STATES:
        assert f'"{state}"' in web, state
        assert f"'{state}'" in harness, state
    assert '"ancient"' not in web
    assert "'ancient'" in harness


def test_the_shipped_client_reads_the_same_three_states_the_server_sends() -> None:
    # The other end of the same pin. app/app.js branches on these strings, so a wire
    # value renamed in web.py alone would leave the screen drawing nothing at all,
    # silently, which is the one failure this signal must not have.
    app_js = (APP / "app.js").read_text(encoding="utf-8")
    web = web_py()
    for state in STALENESS_STATES:
        assert f"'{state}'" in app_js, state
        assert f'"{state}"' in web, state


# --- Harness errors, which are exit 2 and not exit 1 -----------------------


def test_an_anchor_that_matches_nothing_refuses_the_run() -> None:
    # An anchor that has rotted must not quietly mutate something else, or fail to
    # mutate anything and report a green run that proved nothing.
    anchor = "gate.hidden = which === 'gate';"
    completed = run_harness(
        {"substitutions": [{"file": "app/app.js", "find": anchor, "replace": "x"}]}
    )
    assert completed.returncode == 2, completed.stderr
    assert completed.stdout == ""
    assert "app/app.js" in completed.stderr
    assert anchor in completed.stderr


def test_an_anchor_that_matches_more_than_once_refuses_the_run() -> None:
    anchor = "document.getElementById("
    completed = run_harness(
        {"substitutions": [{"file": "app/app.js", "find": anchor, "replace": "x("}]}
    )
    assert completed.returncode == 2, completed.stderr
    assert completed.stdout == ""
    assert "app/app.js" in completed.stderr
    assert anchor in completed.stderr


def test_a_run_that_will_not_quiesce_fails_and_names_the_scenario() -> None:
    # settle() is bounded, so a timer that reschedules itself is a harness error with
    # the scenario's name on it rather than a suite that hangs until the pytest run is
    # killed. The provocation is the harness's own, and only when asked for.
    scenario = "boot_with_no_session_shows_the_gate"
    completed = run_harness(
        {"scenarios": [scenario], "provokeRunawayTimer": True}
    )
    assert completed.returncode == 2, completed.stderr
    assert scenario in completed.stderr
    assert "settle" in completed.stderr


def test_hiding_a_document_member_the_stub_does_not_define_refuses_the_run() -> None:
    # hideDocumentMembers exists so the createDocumentFragment gap can be reproduced
    # without editing the harness or committing a second copy of it. A name the stub
    # never defined would hide nothing: every scenario would pass and the run would
    # read as a caught defect that was in fact never provoked. So a misspelling is a
    # harness error naming the name, exit 2, and never a vacuous green.
    typo = "createDocumentFragmnet"
    completed = run_harness({"hideDocumentMembers": [typo]})
    assert completed.returncode == 2, completed.stderr
    assert completed.stdout == ""
    assert typo in completed.stderr
    assert "hideDocumentMembers" in completed.stderr


def test_hiding_the_fragment_maker_shows_what_the_feed_was_hiding() -> None:
    """The defect this task exists to close, reproduced and caught.

    ``feedRender`` calls ``document.createDocumentFragment`` three lines in. The stub
    did not fake it, the guarded proxy refuses a property it does not define, and
    ``loadFeed`` ends ``.then(done, done)``, which absorbs a throw out of
    ``feedRender`` exactly as it absorbs a refused request. A broken render and a
    failed read reached the same place and looked identical from outside, and no
    scenario asserted row content, so nothing observed it.

    Hiding the member puts the harness back in that state, and two things now say so
    that said nothing before: the guard records the refusal against the running
    scenario at the moment it refuses, whatever the app then does with the exception,
    and ``finish()`` refuses a scenario left with a screen in its in-flight state.
    Neither depends on the scenario having thought to look.
    """
    completed = run_harness({"hideDocumentMembers": ["createDocumentFragment"]})
    # Exactly 1, never merely non-zero: a broken configuration exits 2 and must not
    # be mistaken for a caught defect.
    assert completed.returncode == 1, (
        f"expected exit 1, got {completed.returncode}.\nstderr:\n{completed.stderr}"
    )
    found = results(parse_report(completed))
    assert not found[THE_ROW]["passed"]
    messages = " ".join(found[THE_ROW]["failures"])
    # The refused property is named, which is the guard recording as well as throwing.
    assert "createDocumentFragment" in messages, messages
    # And the screen is visibly stuck, which is the invariant catching a dead render
    # without any assertion about rows at all.
    assert "#feed-loading" in messages, messages
    # A working app with one screen broken, not a crater.
    assert found["boot_with_no_session_shows_the_gate"]["passed"]
    # Criterion 17, written down where it cannot be forgotten: the empty feed never
    # reaches feedRender, so it stays green with the member hidden. It could not have
    # caught this defect on its own and it cannot prove the fix either.
    assert found[THE_EMPTY_FEED]["passed"], found[THE_EMPTY_FEED]["failures"]


# --- A programming error in the render carries its own stack ---------------

# The substitution task 72 is built on. One line, anchored inside feedRender, that
# dereferences a key the payload does not have.
#
# Why the payload and not a DOM member. A substitution reaching for something the
# stub does not define routes through refusedProperty(), which records a failure line
# against the running scenario at the moment it refuses, whatever the app then does
# with the exception. The check below would then pass with or without loadFeed's
# promise shape, because the line it looks for would be the guard's and not the
# hook's. payload is parsed JSON, no guard is wrapped round it, and a missing key on
# it throws a plain TypeError that only the shipped chain decides the fate of.
THE_FEED_RENDER_THROW = {
    "file": "app/app.js",
    "find": "    var names = feedNames(members);",
    "replace": (
        "    var names = feedNames(members);\n"
        "    payload.thisKeyIsNotInTheJson.norIsThisOne;"
    ),
}

# The feed's refusal path: /expenses is refused, feedState('error') runs and the
# screen shows #feed-error. It never reaches feedRender, so it is the control for
# the half of this change that must not happen.
THE_FEED_REFUSAL = "a_refusal_a_screen_asked_for_leaves_the_app_frame_up"


def test_a_throw_inside_the_feed_render_arrives_as_an_unhandled_rejection() -> None:
    """A broken render reaches the rejection hook carrying its own stack.

    This is diagnosis, not correctness, and the distinction is the reason the check
    is shaped the way it is. Nothing a person using the app sees changes: the throw
    happens before feedState('list'), so the screen sits on its loading paragraph
    under either promise shape, and feedBusy is cleared under either one too.

    **The check this test is deliberately not.** A tenth entry in the MUTANT_A to
    MUTANT_I family, asserting that this substitution turns the feed scenarios red,
    would pass before the fix and after it and could therefore prove nothing. The
    in-flight invariant reds them either way: feedState('list') is the last statement
    of feedRender, so any throw inside it leaves #feed-loading up. Measured on this
    substitution over the whole scenario list, the failing set is the same 14
    scenarios with .then(done, done) and with .finally(done), and the only difference
    between the two runs is that the second carries the line asserted below. So the
    assertion is on that line and not on the redness, and the mutation record holds
    both runs.
    """
    completed = run_harness({"substitutions": [THE_FEED_RENDER_THROW]})
    # Exactly 1, never merely non-zero: a substitution that broke the file into a
    # syntax error exits 2, and would otherwise be mistaken for a caught defect.
    assert completed.returncode == 1, (
        f"expected exit 1, got {completed.returncode}.\nstderr:\n{completed.stderr}"
    )
    found = results(parse_report(completed))
    assert not found[THE_ROW]["passed"]
    messages = " ".join(found[THE_ROW]["failures"])
    # The hook fired at all, which is the whole change.
    assert "unhandled rejection" in messages, messages
    # And it carries what the invariant's line cannot: the error's own type and the
    # frame it was thrown from. That is what makes it a diagnosis rather than a
    # symptom, and it is why the fix is worth a line of shipped source.
    assert "TypeError" in messages, messages
    assert "feedRender" in messages, messages
    # The named survivor, already designated for this role above: the empty feed
    # never reaches feedRender, so it cannot show this and cannot prove the fix.
    assert found[THE_EMPTY_FEED]["passed"], found[THE_EMPTY_FEED]["failures"]
    # The half that must not change. A refused request is not a programming error:
    # it still reaches feedState('error') and it must not start arriving at the hook.
    # This scenario asserts #feed-error is up, so it is red either if the refusal
    # stopped being handled or if handling it stopped showing the notice.
    assert found[THE_FEED_REFUSAL]["passed"], found[THE_FEED_REFUSAL]["failures"]


# --- A programming error on the gate's success path carries its own stack ---

# The substitution task 88 is built on, and it is task 72's THE_FEED_RENDER_THROW
# transplanted onto the gate. One line, anchored on the last statement of the gate's
# fulfilled handler, that appends a `.then` to the promise that handler returns and
# dereferences a missing key inside it.
#
# Why the cached session view and not a DOM member, which is task 72's reason in this
# task's shape. A substitution reaching for something the stub does not define routes
# through refusedProperty(), which records a failure line against the running scenario
# at the moment it refuses, whatever the shipped code then does with the exception. The
# check below would then be satisfied by the guard's own line under either promise
# shape and would prove nothing. The client's own global is not guarded, and the view
# it caches is a plain object parsed out of a stubbed response, so a missing key on it
# throws a plain TypeError whose fate only the gate's chain decides. If the cached view
# is null on some path that reaches this line, that is a plain TypeError too, so no
# guard is involved either way.
#
# Why this anchor and not one inside refresh() or showApp(). refresh() is also called
# bare when the client finishes loading, where a rejection reaches nobody and escapes
# already. A substitution inside either of those would put an `unhandled rejection`
# line in the report before the fix as well, and the before-run being green is the
# whole reproduction. This anchor throws after refresh() has settled, so every request
# each scenario declares still goes out and every assertion it makes still holds, and
# only the gate's chain decides what happens to the throw.
THE_GATE_SUCCESS_THROW = {
    "file": "app/app.js",
    "find": "        return refresh();",
    "replace": (
        "        return refresh().then(function () "
        "{ return api.cachedSession().nope.alsoNope; });"
    ),
}

# Task 88's other two mutations, a rejection with no reason at all and the control that
# proves this anchor executes, live in
# plans/mutations/88-the-sign-in-gate-discards-a-programming-error.md and nowhere else.
# They were carried here as constants at first, and that was wrong: a mutation gets two
# homes, recorded in plans/mutations/, or committed as a mutant the suite re-runs, and a
# constant no test reads is neither. It is a second copy of one anchor with nothing
# keeping it in step with the first, which is the drift this task refuses one file away
# when it declines to copy api.js's six kinds into app/app.js.

# The scenario the throw is asserted against: the sign-in succeeds, so the gate's
# fulfilled handler runs and the substitution fires inside it.
THE_SUCCESSFUL_SIGN_IN = "a_successful_sign_in_keeps_the_screen_the_person_was_on"

# The two controls for the half that must not change, both of them refusals api.js
# classified. The first never reaches the fulfilled handler at all, so the
# substitution is inert in it. The second is the one that makes the naive fix wrong: a
# sign-in that got no answer arrives at the same catch, it is an ApiError of kind
# 'offline', and it must stay a silent early return with the offline notice already up.
THE_GATE_REFUSAL = "a_refused_sign_in_tells_the_person_why"
THE_OFFLINE_SIGN_IN = "a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone"

# The scenario that signs in successfully *and* asserts #gate-submit is enabled
# afterwards, which is how "the submit control still comes back" is checked rather than
# claimed in prose: the substitution fires in it, so the chain takes the re-raising
# path, and its own assertion on the control is what says the trailing handler still
# ran.
THE_DEAD_SESSION = (
    "a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate"
)


def test_a_throw_on_the_gates_success_path_arrives_as_an_unhandled_rejection() -> None:
    """A programming error during sign-in reaches the hook carrying its own stack.

    This is diagnosis, not correctness, and nothing a person sees changes. The gate's
    catch used to return early for any reason without a recognised `kind`, and a
    TypeError has none, so the rejection was consumed, the trailing handler tidied the
    control away, and the screen looked entirely normal. That is worse than the feed's
    version of the same defect rather than different in kind: on the feed a throw left
    #feed-loading up and the in-flight invariant could see it, and here there was
    nothing at all to see.

    **The assertion is on the failure line, not on redness.** Redness alone would
    distinguish the two runs here, because the before-run of this substitution is
    entirely green: 160 of 160 scenarios pass with the throw in place, which is the bug
    stated as a measurement. A redness assertion would therefore bite. It is still
    wrong, because a scenario that reds for an unrelated reason would satisfy it, and
    what this test exists to say is that the hook fired.

    **The check this test is deliberately not.** A tenth entry in the MUTANT_A to
    MUTANT_I family cannot be added on this anchor at all. Before the fix the mutation
    *survives*, so there are no named scenarios for it to assert red; after the fix it
    would assert that some scenarios went red, which is a weaker version of what is
    asserted below and would duplicate it. That is a judgement about duplication, and
    not task 72's reason, which was that its redness check could not have failed.

    **No stack frame name is pinned.** The throw is inside an anonymous function, so
    V8 may name that frame by position alone. `app.js` is asserted, the real lines are
    pasted into the record, and a frame name is pinned nowhere.
    """
    completed = run_harness({"substitutions": [THE_GATE_SUCCESS_THROW]})
    # Exactly 1, never merely non-zero: a substitution that broke the file into a
    # syntax error exits 2, and would otherwise be mistaken for a caught defect.
    assert completed.returncode == 1, (
        f"expected exit 1, got {completed.returncode}.\nstderr:\n{completed.stderr}"
    )
    found = results(parse_report(completed))
    assert not found[THE_SUCCESSFUL_SIGN_IN]["passed"]
    messages = " ".join(found[THE_SUCCESSFUL_SIGN_IN]["failures"])
    # The hook fired at all, which is the whole change.
    assert "unhandled rejection" in messages, messages
    # And it carries what no id-and-hidden invariant could: the error's own type and
    # the file and line it was thrown from. That is what makes it a diagnosis rather
    # than a symptom, and it is why the fix is worth a line of shipped source.
    assert "TypeError" in messages, messages
    assert "app.js" in messages, messages
    # The half that must not change, control one: a refused sign-in never reaches the
    # fulfilled handler, so the substitution is inert and the scenario still reads its
    # message on the gate.
    assert found[THE_GATE_REFUSAL]["passed"], found[THE_GATE_REFUSAL]["failures"]
    # Control two, and the one that makes a bare re-raise wrong. A sign-in that got no
    # answer is an ApiError, it arrives at the same catch, and it must stay a silent
    # early return rather than becoming an unhandled rejection of its own.
    assert found[THE_OFFLINE_SIGN_IN]["passed"], found[THE_OFFLINE_SIGN_IN]["failures"]
    # And the control that comes back. This scenario signs in successfully, so the
    # substitution fires and the chain re-raises; it also asserts #gate-submit is
    # enabled after settling. So the hook's line appears and the invariant's does not,
    # which is the trailing handler running on the re-raising path.
    dead = " ".join(found[THE_DEAD_SESSION]["failures"])
    assert "unhandled rejection" in dead, dead
    assert "#gate-submit" not in dead, dead


# --- api.js is the only place a status is interpreted ----------------------

# A status read in order to be compared, either way round, and a comparison against
# an HTTP status number. `status: 503` in sw.js builds a Response and is neither.
_STATUS_READ = re.compile(
    r"\.\s*status\s*(?:===|!==|==|!=|>=|<=|>|<)"
    r"|(?:===|!==|==|!=|>=|<=|>|<)\s*[A-Za-z_$][\w$]*\.\s*status\b"
    r"|\bswitch\s*\([^)]*\.\s*status\b"
)
_STATUS_NUMBER = re.compile(
    r"(?:===|!==|==|!=|>=|<=|>|<)\s*[1-5][0-9][0-9]\b"
    r"|\b[1-5][0-9][0-9]\s*(?:===|!==|==|!=|>=|<=|>|<)"
)
_JS_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)

# The six kinds classify() answers with. Every one of them is produced there, so a
# classifier cut down to fewer answers is missing some of these.
_KINDS = (
    "offline",
    "signed-out",
    "sign-in-not-kept",
    "not-linked",
    "unavailable",
    "refused",
)


def _without_comments(source: str) -> str:
    return _JS_COMMENTS.sub(" ", source)


def _classifier(source: str) -> str:
    """app/api.js from ``function classify(`` up to the next function after it.

    Sliced rather than searched for whole-file, because the point of the companion
    test below is that the classification is *in the classifier*: a status read in
    `request()` to spot a 204, or in `noted()` to spot a 401, is not classification
    and must not be able to stand in for it.
    """
    start = source.index("function classify(")
    return source[start : source.index("\n  function ", start + 1)]


def test_only_the_api_client_interprets_a_status() -> None:
    """The rule that keeps one error contract instead of two.

    app/api.js classifies a response and puts its answer on the error as ``kind``.
    Every other file under app/ reads that answer and never the status behind it. A
    second file that branches on a status is a second opinion about what a 403 means,
    and two opinions drift the moment either is edited: that is the defect task 32
    removed, in the shape it would come back in.

    A screen genuinely does need to know whether api.js has already raised a curtain
    over it. That question is asked of ``kind``, which states it, rather than
    reconstructed from a status, which only implies it.

    This is a lint, not a proof. It reads both orders of comparison and a ``switch``
    on a status, and it would still miss a status copied into a local first. What
    makes it worth having is that every plausible spelling of the mistake, and the one
    #40 actually makes, is caught at the point somebody merges.
    """
    for path in sorted(APP.rglob("*.js")):
        if path.name == "api.js":
            continue
        source = _without_comments(path.read_text(encoding="utf-8"))
        assert not _STATUS_READ.search(source), path.name
        assert not _STATUS_NUMBER.search(source), path.name


def test_the_narrowed_status_rule_still_bites() -> None:
    """Proof that excusing one file left a rule that still refuses what it must.

    The first version of this test asked only whether ``api.js`` compared against a
    status *anywhere*, which ``response.status === 204`` in ``request()`` and
    ``status !== 401`` in ``noted()`` both satisfy without classifying anything: it
    stayed green with ``classify()`` deleted outright, which is the whole subject of
    the task it was guarding. A guard that passes for a reason unrelated to its claim
    is the defect this repo keeps finding, and this test was one.

    So it asks about the classifier itself, by name and by slice.
    """
    client = _without_comments((APP / "api.js").read_text(encoding="utf-8"))
    assert "function classify(" in client, (
        "app/api.js no longer defines classify(), which is the one place a response "
        "becomes a kind. If it was renamed or moved, move this test with it; do not "
        "delete it, because the rule above goes on passing without it."
    )
    body = _classifier(client)
    # Every kind is answered here, so a classifier cut down to one answer fails.
    for kind in _KINDS:
        assert f"'{kind}'" in body, kind
    # And the statuses it turns into those kinds are read here, in the classifier,
    # rather than anywhere else in the file that happens to mention a number.
    for status in ("401", "403", "500"):
        assert re.search(rf"(?:===|!==|==|!=|>=|<=|>|<)\s*{status}\b", body), status
    assert _STATUS_READ.search(client)
    # And the patterns match the shapes they claim to, so a green run above means the
    # search ran rather than that a regex rotted.
    assert _STATUS_READ.search("if (error.status === 401) {")
    assert _STATUS_READ.search("if (401 === error.status) {")
    assert _STATUS_READ.search("switch (error.status) {")
    assert _STATUS_NUMBER.search("return error.status === 0 || error.status >= 500;")
    assert _STATUS_NUMBER.search("if (401 === error.status) {")
    # A status being written, which is what sw.js does, is not a comparison.
    assert not _STATUS_READ.search("new Response(body, { status: 503 })")
    assert not _STATUS_NUMBER.search("new Response(body, { status: 503 })")


# --- Determinism, isolation and the stub's honesty -------------------------


def test_two_runs_of_the_same_configuration_report_the_same_bytes(
    harness_run: subprocess.CompletedProcess[str],
) -> None:
    # No randomness, no Date.now, no locale-dependent formatting and no network, so a
    # second run of the same configuration is byte-identical.
    again = run_harness({})
    assert again.returncode == harness_run.returncode
    assert again.stdout == harness_run.stdout


def test_every_error_code_the_harness_names_appears_in_web_py(
    report: dict[str, Any],
) -> None:
    web = (REPO / "src" / "splitwise_lite" / "web.py").read_text(encoding="utf-8")
    codes = report["errorCodes"]
    assert codes
    for code in codes:
        assert f'"{code}"' in web, code


def test_the_service_worker_registration_branch_is_never_entered(
    report: dict[str, Any],
) -> None:
    # app.js registers a window 'load' listener only inside
    # `if ('serviceWorker' in navigator)`, and the stub navigator has no such
    # property. A 'load' listener showing up here would mean the branch ran, and the
    # harness would be pretending to cover something it does not. The count of
    # hashchange listeners is not pinned: tasks 11 and 12 each added one of their own,
    # and the screens after them will add more.
    for entry in report["scenarios"]:
        assert set(entry["windowEvents"]) == {"hashchange"}, (
            entry["name"],
            entry["windowEvents"],
        )


def test_each_scenario_starts_from_a_fresh_context(report: dict[str, Any]) -> None:
    # Two scenarios that both boot see two separate fetch recorders: a shared one
    # would show the earlier scenario's call as well. And the second runs straight
    # after a scenario that cached a session view inside api.js, where it asserts the
    # cache is empty, so api.js's state does not survive either.
    order = [entry["name"] for entry in report["scenarios"]]
    linked = "boot_with_a_linked_session_shows_the_app"
    after = "nothing_from_the_previous_scenario_survives_into_this_one"
    assert order.index(linked) + 1 == order.index(after)
    found = results(report)
    for name in (linked, after):
        assert found[name]["passed"], found[name]["failures"]
    # The linked session reaches the app frame, so it reads the two screens as well.
    # The 403 that follows it never gets that far and reads once, and a recorder shared
    # between the two would carry those extra reads into this list.
    assert found[linked]["requests"] == [
        "GET /api/session",
        "GET /api/expenses",
        "GET /api/members",
    ]
    assert found[after]["requests"] == ["GET /api/session"]


# --- Neither half depends on the working directory -------------------------


def test_the_harness_finds_app_from_its_own_location(tmp_path: Path) -> None:
    completed = run_harness({}, cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr


def test_the_suite_passes_when_pytest_runs_from_another_directory(
    tmp_path: Path,
) -> None:
    # One test from this file, so the nested run cannot recurse into this one.
    target = f"{Path(__file__).resolve()}::test_an_anchor_that_matches_nothing_refuses_the_run"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
        cwd=str(tmp_path),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
