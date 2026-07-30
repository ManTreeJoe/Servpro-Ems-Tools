"""`job_children` — claims, units and sub-jobs of a client.

Replaces jobs.parent_canon / jobs.unit_number, which inferred the hierarchy
from NAME STRINGS. On live data every one of the 21 rows that inference had
populated pointed at a parent that does not exist ('store', 'stater bros',
'monterey apartments ga'). Rows here exist because a child FOLDER exists.

The table's real job is `trello_card`: a client with several claims or units
has several cards (live data has jobs with 7, 8 and 12) and the flat
job_links list cannot say which card belongs to which child.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ems_db


@pytest.fixture(autouse=True)
def _db(tmp_path):
    ems_db.reset_db_path(str(tmp_path / "jobs.db"))
    ems_db.invalidate_department_cache()
    yield


# ── classification ──────────────────────────────────────────────────────

@pytest.mark.parametrize("name,kind,ordinal", [
    ("1st Claim",            "claim",  1),
    ("2nd Claim (KItchen)",  "claim",  2),
    ("3rd Claim 7-29-2026",  "claim",  3),
    ("2nd claim",            "claim",  2),
    ("Unit 182",             "unit",   None),
    ("Unit 147 - 3.4.26",    "unit",   None),
    ("Unit 561-I",           "unit",   None),
    ("Apt 12B",              "unit",   None),
    ("Coreland Company unit 121", "unit", None),
    ("Seley Plaza 99 cent store", "subjob", None),
    ("Garage Door",          "subjob", None),
    ("",                     "subjob", None),
])
def test_classify_child(name, kind, ordinal):
    assert ems_db.classify_child(name) == (kind, ordinal)


# ── round trip ──────────────────────────────────────────────────────────

def test_set_and_read_children():
    ems_db.upsert_job(display_name="Mansolino Sayra")
    for n in ("1st Claim", "2nd Claim (KItchen)", "3rd Claim 7-29-2026"):
        ems_db.set_child("mansolino sayra", n)
    kids = ems_db.children_of("mansolino sayra")
    assert [k["name"] for k in kids] == [
        "1st Claim", "2nd Claim (KItchen)", "3rd Claim 7-29-2026"]
    assert [k["ordinal"] for k in kids] == [1, 2, 3]


def test_children_sort_claims_by_ordinal_not_alphabetically():
    """'10th Claim' must not sort before '2nd Claim'."""
    ems_db.upsert_job(display_name="Many Claims")
    for n in ("10th Claim", "2nd Claim", "1st Claim"):
        ems_db.set_child("many claims", n)
    assert [k["ordinal"] for k in ems_db.children_of("many claims")] == [1, 2, 10]


def test_set_child_is_idempotent():
    ems_db.upsert_job(display_name="Metro at Main")
    ems_db.set_child("metro at main", "Unit 182")
    ems_db.set_child("metro at main", "Unit 182")
    assert len(ems_db.children_of("metro at main")) == 1


def test_blank_values_do_not_overwrite():
    ems_db.upsert_job(display_name="Metro at Main")
    ems_db.set_child("metro at main", "Unit 182", trello_card="card1")
    ems_db.set_child("metro at main", "Unit 182", department="IE")
    ch = ems_db.children_of("metro at main")[0]
    assert ch["trello_card"] == "card1" and ch["department"] == "IE"


def test_filter_by_kind():
    ems_db.upsert_job(display_name="Mixed")
    ems_db.set_child("mixed", "Unit 5")
    ems_db.set_child("mixed", "2nd Claim")
    assert len(ems_db.children_of("mixed", kind=ems_db.CHILD_UNIT)) == 1
    assert len(ems_db.children_of("mixed", kind=ems_db.CHILD_CLAIM)) == 1


def test_remove_child():
    ems_db.upsert_job(display_name="Metro at Main")
    ems_db.set_child("metro at main", "Unit 182")
    assert ems_db.remove_child("metro at main", "Unit 182")
    assert ems_db.children_of("metro at main") == []


def test_blank_args_are_rejected():
    assert ems_db.set_child("", "Unit 1") == {}
    assert ems_db.set_child("parent", "") == {}
    assert ems_db.children_of("") == []


# ── the point of the table: per-child cards ─────────────────────────────

def test_which_card_belongs_to_which_child():
    """Unanswerable with the flat job_links list."""
    ems_db.upsert_job(display_name="Metro at Main")
    ems_db.set_child("metro at main", "Unit 182", trello_card="cardA")
    ems_db.set_child("metro at main", "Unit 188", trello_card="cardB")
    assert ems_db.find_child_by_card("cardB")["name"] == "Unit 188"
    assert ems_db.find_child_by_card("cardA")["name"] == "Unit 182"


def test_card_lookup_normalizes_a_full_url():
    ems_db.upsert_job(display_name="Metro at Main")
    ems_db.set_child("metro at main", "Unit 182",
                     trello_card="https://trello.com/c/AbCd1234/x")
    assert ems_db.find_child_by_card("abcd1234")["name"] == "Unit 182"


def test_find_child_by_folder(tmp_path):
    ems_db.upsert_job(display_name="Metro at Main")
    p = str(tmp_path / "Metro at Main" / "Unit 182")
    ems_db.set_child("metro at main", "Unit 182", folder_path=p)
    got = ems_db.find_child_by_folder(p.upper())    # case-insensitive
    assert got and got["parent_canon"] == "metro at main"


def test_unknown_lookups_return_none():
    assert ems_db.find_child_by_card("nope") is None
    assert ems_db.find_child_by_folder("") is None


# ── the deprecated inference is gone ────────────────────────────────────

def test_upsert_no_longer_infers_a_parent_from_the_name():
    """'Store 115 2601-24038oth-la sierra' used to yield parent 'store'."""
    key = ems_db.upsert_job(display_name="Store 115 2601-24038oth-la sierra")
    job = ems_db.get_job(key)
    assert not job["parent_canon"], "name inference must not write a parent"
    assert not job["unit_number"]


def test_find_units_of_reads_children():
    ems_db.upsert_job(display_name="Avana Springs Greystar")
    ems_db.set_child("avana springs greystar", "Unit 561-I")
    ems_db.set_child("avana springs greystar", "Unit 565-E")
    got = ems_db.find_units_of("avana springs greystar")
    assert sorted(g["name"] for g in got) == ["Unit 561-I", "Unit 565-E"]


def test_find_units_of_falls_back_for_an_unbackfilled_db():
    """A database that hasn't been backfilled still answers, so callers
    don't break mid-migration."""
    ems_db.upsert_job(display_name="Legacy Parent")
    key = ems_db.upsert_job(display_name="Legacy Child")
    with ems_db._LOCK, ems_db._connect() as c:
        c.execute("UPDATE jobs SET parent_canon=?, unit_number=? "
                  "WHERE canon_key=?", ("legacy parent", "5", key))
        c.commit()
    assert [j["canon_key"] for j in ems_db.find_units_of("legacy parent")] \
        == [key]


def test_find_property_of_uses_the_child_folder(tmp_path):
    parent = ems_db.upsert_job(display_name="Metro at Main")
    child = ems_db.upsert_job(display_name="Metro at Main Unit 182")
    p = str(tmp_path / "Metro at Main" / "Unit 182")
    ems_db.set_link(child, ems_db.LINK_FOLDER, p)
    ems_db.set_child("metro at main", "Unit 182", folder_path=p)
    got = ems_db.find_property_of(child)
    assert got and got["canon_key"] == parent


def test_find_property_of_none_when_unrelated():
    key = ems_db.upsert_job(display_name="Standalone Job")
    assert ems_db.find_property_of(key) is None
