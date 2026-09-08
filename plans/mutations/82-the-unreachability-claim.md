# Issue #82: the unreachability claim gets checked

Three mutations, all against the check this task adds: the observer in
`tests/conftest.py` and the always-on proof of it in `tests/test_error_messages.py`.

Every run set `PYTHONDONTWRITEBYTECODE=1`, applied its own `find` and `replace` with
the recipe in `README.md` after asserting the anchor matched exactly once, and reverted
with `git checkout -- <file>` against the single named file before the next. The
working tree was committed before the first one. Each run was the whole of
`tests/test_error_messages.py`, unfiltered, rather than only the node ids listed, so
the figures below are the complete outcome inside that module rather than a
confirmation of what was expected. Unmutated, that module reports **133 passed**, and
every figure quoted counts pytest test outcomes in that one module.

The risk this task was told to budget for is an observer that records nothing, because
it looks exactly like success. Mutation 2 is the answer to it and mutation 3 is what
shows the new check does not simply red at everything.

## 1. Mark a row that a request reaches

The positive control the issue asked for as a criterion rather than a suggestion. It
converts a driven row into an `unreachable(...)` row carrying a reason well over
`MIN_REASON` characters, and the reason is false: a second signup for one address is
answered by that raise on requests this suite already makes, because `linked_client`
signs one person up twice whenever a row's setup has already signed them up.

Measured: **131 passed, 4 errors**. The two node ids the row itself contributed stop
existing, which is why the pass count falls by two rather than rising. The four are
reported as teardown errors rather than failures, because the guard asserts after the
test it is attributed to.

Two things worth reading off this run. `test_every_four_hundred_raise_site_is_declared`
stays green, which is the whole reason this task exists: the enumeration equality
cannot see a mark go false, because no raise site and no message skeleton moved. And
the four killed cases are all in `test_no_four_hundred_body_names_an_identifier` rather
than in the new provenance test, because that test clears the record immediately before
the row's own request and so never sees what a row's setup was refused.

```json
{
  "id": "mark-a-row-a-request-reaches",
  "file": "tests/test_error_messages.py",
  "find": "    Site(\n        # The one 4xx that names an address on purpose. An address is the person's own\n        # typed input, the sign-up screen shows it back, and it is not in the\n        # identifier set, so this row asserts what it should: no store id.\n        \"accounts.py\",\n        \"sign_up\",\n        \"an account already exists for \",\n        Drive(\n            \"POST\",\n            SIGNUP,\n            \"email_already_registered\",\n            {\n                \"email\": email_for(\"Sam\"),\n                \"display_name\": \"Sam\",\n                \"password\": PASSWORD,\n            },\n        ),\n    ),",
  "replace": "    unreachable(\n        \"accounts.py\",\n        \"sign_up\",\n        \"an account already exists for \",\n        \"a second signup for one address is refused by web._signup before accounts \"\n        \"ever sees it, so this raise cannot be the answer to any request\",\n    ),",
  "kills": [
    "tests/test_error_messages.py::test_no_four_hundred_body_names_an_identifier[web.py::_create_settlement::a_payment_to_that_person_is_already_marked_as_pa]",
    "tests/test_error_messages.py::test_no_four_hundred_body_names_an_identifier[web.py::_decide_settlement::key_decision_must_be_one_of_and_pending_is_not_a]",
    "tests/test_error_messages.py::test_no_four_hundred_body_names_an_identifier[web.py::_decide_settlement::only_the_person_the_payment_was_made_to_can_answ]",
    "tests/test_error_messages.py::test_no_four_hundred_body_names_an_identifier[web.py::_decide_settlement::that_payment_has_already_been_answered_and_an_an]"
  ],
  "survives": [
    "tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared",
    "tests/test_error_messages.py::test_every_site_no_request_reaches_says_what_would_have_to_be_true"
  ],
  "result": "killed"
}
```

## 2. Make the observer record nothing

The mutation that matters most, and the one this repo's record says is the likely
outcome of a rushed implementation. The wrapper still runs, still returns the response
unchanged, and appends nothing.

Measured: **59 failed, 74 passed**. The 59 are every case of the provenance test, one
per driven row, each failing on the assertion that the record is non-empty before
anything is compared, which is the criterion that stops this passing vacuously over an
empty set.

The other half of that figure is the point of the mutation: all 59 cases of
`test_no_four_hundred_body_names_an_identifier` passed, so the property half of this
module cannot see the observer being switched off. Nothing but the new proof catches
it.

```json
{
  "id": "record-nothing",
  "file": "tests/conftest.py",
  "find": "            raised = _deepest_frame(error)\n            if raised is not None:",
  "replace": "            raised = None\n            if raised is not None:",
  "kills": [
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::_require_password_policy::a_password_must_be_at_least_characters_got]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::_require_password_policy::a_password_must_be_at_most_characters_got]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::_require_password_policy::a_password_must_not_be_whitespace_alone]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::_fail_login::that_email_address_and_password_do_not_match_an_]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::_require_email::an_email_address_must_be_at_most_characters_got]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::_require_email::an_email_address_must_be_printable_ascii_got]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::_require_email::an_email_address_must_have_no_spaces_got]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::_require_email::an_email_address_must_have_exactly_one_got]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::_require_email::an_email_address_must_have_a_local_part_got]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::_require_email::an_email_address_must_have_a_dotted_domain_got]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::sign_up::an_account_already_exists_for]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::log_in::that_email_address_and_password_do_not_match_an_]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[accounts.py::authenticate::that_token_does_not_name_a_live_session]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[groups.py::acting_member::no_member_of_this_group_is_linked_to_your_accoun]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[money.py::parse_amount::not_a_valid_amount]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[money.py::parse_amount::amount_has_no_digits]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[money.py::parse_amount::amount_has_more_than_fractional_digits_and_would]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[money.py::parse_amount::amount_is_too_large_to_store]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[split.py::split_exact::the_shares_add_up_to_but_the_total_is]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[split.py::_allocate::weights_sum_to_zero_so_there_is_no_share_to_divi]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[split.py::_require_total::the_amount_must_be_more_than_zero_but_it_is]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[split.py::_ordered_from_iterable::a_split_needs_at_least_one_member]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[split.py::_ordered_from_iterable::member_ids_names_a_member_more_than_once]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[split.py::_ordered_from_mapping::a_split_needs_at_least_one_member]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[split.py::_ordered_from_mapping::every_must_be_zero_or_positive]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[store.py::_require_name::must_not_be_blank]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::check::too_many_failed_attempts_wait_a_few_minutes_and_]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_check_csrf::a_state_changing_request_must_be_sent_as]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_check_csrf::a_state_changing_request_must_repeat_the_cookie_]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_check_csrf::the_header_does_not_match_the_cookie]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_check_csrf::that_request_came_from_another_origin]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_json_object::the_request_body_is_not_valid_json]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_json_object::the_request_body_must_be_a_json_object]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_require_keys::is_missing_the_key]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_require_keys::has_an_unrecognised_key]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_require_str::key_must_be_a_json_string]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_require_amount_str::key_must_be_an_amount_as_a_json_string_such_as_1]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_require_object::key_must_be_a_json_object]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_require_list::key_must_be_a_json_array]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_authenticate::this_endpoint_needs_a_signed_in_session]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_signup::an_account_already_exists_for]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_create_expense::names_a_payer_id_that_is_not_a_member_of_this_gr]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_resolve_split::is_missing_the_key_mode]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_resolve_split::mode_must_be_one_of_equal_weight_or_exact_got]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_require_member_id::a_split_names_a_member_id_that_is_not_a_json_str]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_require_member_id::a_split_names_a_member_id_that_is_not_a_member_o]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_require_weight::every_weight_in_a_split_must_be_a_json_integer]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_require_exact_amount::every_exact_amount_in_a_split_must_be_an_amount_]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_create_settlement::names_a_to_member_id_that_is_not_a_member_of_thi]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_create_settlement::a_member_cannot_record_a_payment_to_themselves_t]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_create_settlement::amount_must_be_more_than_zero_got]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_create_settlement::a_payment_to_that_person_is_already_marked_as_pa]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_decide_settlement::key_decision_must_be_one_of_and_pending_is_not_a]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_decide_settlement::no_settlement_in_this_group_with_that_id]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_decide_settlement::only_the_person_the_payment_was_made_to_can_answ]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_decide_settlement::that_payment_has_already_been_answered_and_an_an]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_decide_settlement::there_is_more_than_one_payment_from_that_person_]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_read_debt::a_debt_path_names_a_that_is_not_a_member_of_this]",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[web.py::_read_debt::a_member_cannot_owe_themselves_the_debtor_and_th]"
  ],
  "survives": [
    "tests/test_error_messages.py::test_no_four_hundred_body_names_an_identifier[accounts.py::_require_password_policy::a_password_must_be_at_least_characters_got]",
    "tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared",
    "tests/test_error_messages.py::test_every_error_body_is_composed_inside_the_one_error_handler",
    "tests/test_error_messages.py::test_the_key_set_and_the_raise_site_index_come_from_one_walk"
  ],
  "result": "killed"
}
```

## 3. Reword a marked row's reason, the named surviving control

The control that shows the new check is not simply total. It rewords the reason on the
marked `_require_email` row in `store.py`, which changes no behaviour: the row stays
marked, the reason stays over `MIN_REASON` characters, and no raise site, skeleton or
drive moves.

Measured: **133 passed**, which is exactly the unmutated figure. Nothing red, including
the reason-floor check and the enumeration equality, both of which read that row.

```json
{
  "id": "reword-a-marked-reason",
  "file": "tests/test_error_messages.py",
  "find": "        \"accounts.normalise_email lower-cases every address before the store sees it, \"\n        \"so a mixed-case one cannot arrive through signup or sign-in\",",
  "replace": "        \"every address is lower-cased by accounts.normalise_email before the store \"\n        \"sees it, so no mixed-case address can arrive through signup or sign-in\",",
  "kills": [],
  "survives": [
    "tests/test_error_messages.py::test_every_site_no_request_reaches_says_what_would_have_to_be_true",
    "tests/test_error_messages.py::test_every_four_hundred_raise_site_is_declared",
    "tests/test_error_messages.py::test_each_driven_row_answers_from_the_site_it_declares[store.py::_require_name::must_not_be_blank]"
  ],
  "result": "survived"
}
```
