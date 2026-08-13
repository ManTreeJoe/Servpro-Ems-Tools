"""A card must land on the job it already belongs to.

The key comes from the name, so a card titled "Knudsen, Seth - Mercury"
keys to `knudsen, seth` while the run doc and the folder call him
"Seth Knudsen" — `seth knudsen`. Writing the card's key makes a SECOND
job for one person and the audit keeps reading the first, which is how a
job ends up with its carrier on a row nothing looks at.

Measured on the live workspace: without this a full sync created nine
such rows, for jobs open that week.
"""
import pytest

import trello_job_sync as w


def _rec(key, name):
    return {"canon_key": key, "display_name": name}


def test_a_card_redirects_to_the_existing_spelling():
    recs = [_rec("knudsen, seth", "Knudsen, Seth - Mercury")]
    res = w.resolve_against_existing(recs, lambda k: k == "seth knudsen")
    assert res["redirected"] == 1
    assert recs[0]["canon_key"] == "seth knudsen"


def test_the_cards_own_spelling_is_kept_as_an_alias():
    """Redirecting must not make the card title unsearchable."""
    recs = [_rec("knudsen, seth", "Knudsen, Seth - Mercury")]
    w.resolve_against_existing(recs, lambda k: k == "seth knudsen")
    assert "Knudsen, Seth - Mercury" in recs[0]["aliases"]


def test_a_card_whose_own_key_exists_is_left_alone():
    """Already the right identity — nothing to do, and redirecting would
    move a job that was never split."""
    recs = [_rec("seth knudsen", "Seth Knudsen")]
    res = w.resolve_against_existing(recs, lambda k: k == "seth knudsen")
    assert res["redirected"] == 0
    assert recs[0]["canon_key"] == "seth knudsen"


def test_a_genuinely_new_job_is_still_created():
    """The point is to stop DUPLICATES, not to stop new work arriving."""
    recs = [_rec("brand new", "Brand New")]
    res = w.resolve_against_existing(recs, lambda k: False)
    assert res["redirected"] == 0
    assert recs[0]["canon_key"] == "brand new"


def test_it_never_merges_two_jobs_that_both_exist():
    """Both spellings already being real jobs is a MERGE, and a merge
    needs a person — that's what the 🧩 review is for. A sync must not
    quietly fold two rows together."""
    recs = [_rec("knudsen, seth", "Knudsen, Seth")]
    # both exist
    res = w.resolve_against_existing(recs, lambda k: True)
    assert res["redirected"] == 0
    assert recs[0]["canon_key"] == "knudsen, seth"


def test_a_name_with_no_swapped_form_is_left_alone():
    recs = [_rec("athena management property", "Athena Management Property")]
    res = w.resolve_against_existing(recs, lambda k: True)
    assert res["redirected"] == 0


def test_carrier_suffix_does_not_block_the_match():
    """Cards carry "- Mercury"; the index row doesn't."""
    recs = [_rec("ochoa, edward", "Ochoa, Edward- AAA")]
    res = w.resolve_against_existing(recs, lambda k: k == "edward ochoa")
    assert res["redirected"] == 1


def test_several_cards_for_one_person_all_redirect():
    recs = [_rec("knudsen, seth", "Knudsen, Seth - Mercury"),
            _rec("knudsen, seth", "Knudsen, Seth")]
    res = w.resolve_against_existing(recs, lambda k: k == "seth knudsen")
    assert res["redirected"] == 2
    assert all(r["canon_key"] == "seth knudsen" for r in recs)


def test_empty_input_is_safe():
    assert w.resolve_against_existing([], lambda k: True)["redirected"] == 0
    assert w.resolve_against_existing(None, lambda k: True)["redirected"] == 0


def test_pairs_are_reported_for_the_caller_to_log():
    recs = [_rec("knudsen, seth", "Knudsen, Seth")]
    res = w.resolve_against_existing(recs, lambda k: k == "seth knudsen")
    assert res["pairs"] == [("knudsen, seth", "seth knudsen")]
