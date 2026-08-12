"""A job's name changes once the claim details land — keep the old one.

Intake often has only a surname or an address; the full
"Last, First - Carrier" arrives later. `upsert_job` overwrites
display_name, so without a record the earlier name is gone — and with it
the answer to "what was this job called when I filed those photos?".
"""

import pytest

import ems_db_sqlite as db
from ems_db_common import is_material_rename


# ── what counts as a rename ─────────────────────────────────────────

@pytest.mark.parametrize("old,new", [
    ("Smith", "Smith, John"),
    # Same canon_key (the carrier suffix is stripped) but a real change —
    # this is the "once all info is in" case and MUST be recorded.
    ("Smith, John", "Smith, John - State Farm"),
    ("10882 Cochran Ave", "Alvarez, Ana"),
])
def test_a_real_name_change_is_material(old, new):
    assert is_material_rename(old, new)


@pytest.mark.parametrize("old,new", [
    ("Smith, John", "smith, john"),        # casing fix
    ("Smith,  John", "Smith, John"),       # whitespace fix
    ("Smith, John", "Smith, John"),        # no change
    ("Smith, John", ""),                   # partial-update upsert
    ("", "Smith, John"),                   # first insert
])
def test_noise_is_not_a_rename(old, new):
    assert not is_material_rename(old, new)


# ── the record itself ───────────────────────────────────────────────

def test_renaming_a_job_records_the_old_name():
    key = db.upsert_job(display_name="Tester, Ann")
    assert db.name_history(key) == []

    db.upsert_job(display_name="Tester, Ann - Mercury")

    hist = db.name_history(key)
    assert len(hist) == 1
    assert hist[0]["from"] == "Tester, Ann"
    assert hist[0]["to"] == "Tester, Ann - Mercury"
    assert hist[0]["at"]


def test_the_old_name_still_finds_the_job():
    # Adding the carrier keeps the same canon_key (it strips " - Carrier"),
    # so the old spelling resolves on its own — no alias needed.
    key = db.upsert_job(display_name="Oldname, Bob")
    db.upsert_job(display_name="Oldname, Bob - Allstate")
    assert db.find_job_by_name("Oldname, Bob")["canon_key"] == key


def test_successive_renames_accumulate_oldest_first():
    key = db.upsert_job(display_name="Chainy, Cara")
    db.upsert_job(display_name="Chainy, Cara - USAA")
    db.upsert_job(display_name="Chainy, Cara - USAA General")

    hist = db.name_history(key)
    assert [h["from"] for h in hist] == ["Chainy, Cara", "Chainy, Cara - USAA"]
    assert hist[-1]["to"] == "Chainy, Cara - USAA General"


# ── the key-changing rename: "Smith" becomes "Smith, John" ──────────
#
# This is the case the office actually hits — intake files a surname,
# then the full name arrives. It canonicalizes to a DIFFERENT key, so
# upsert_job cannot see it as a rename: it writes a second job row, and
# the fold that reconciles them is where the rename really happens.

def test_folding_a_partial_name_into_the_full_one_records_the_rename():
    partial = db.upsert_job(display_name="Partialton")
    full = db.upsert_job(display_name="Partialton, Pete - Farmers")
    assert partial != full

    db.merge_jobs(full, [partial])

    hist = db.name_history(full)
    assert [(h["from"], h["to"]) for h in hist] == [
        ("Partialton", "Partialton, Pete - Farmers")]


def test_the_partial_name_still_finds_the_job_after_the_fold():
    partial = db.upsert_job(display_name="Findme")
    full = db.upsert_job(display_name="Findme, Fran - AAA")
    db.merge_jobs(full, [partial])
    assert db.find_job_by_name("Findme")["canon_key"] == full


def test_a_fold_keeps_the_history_the_loser_already_had():
    # The loser was renamed once before being folded; that earlier rename
    # must survive the merge rather than be deleted with its row.
    partial = db.upsert_job(display_name="Keeper, Kim")
    db.upsert_job(display_name="Keeper, Kim - Mercury")
    assert len(db.name_history(partial)) == 1

    full = db.upsert_job(display_name="Keeper, Kimberly - Mercury")
    db.merge_jobs(full, [partial])

    froms = [h["from"] for h in db.name_history(full)]
    assert "Keeper, Kim" in froms          # survived the fold
    assert "Keeper, Kim - Mercury" in froms  # the fold itself


def test_folding_a_mere_respelling_is_not_a_rename():
    a = db.upsert_job(display_name="Samey, Sam")
    b = db.upsert_job(display_name="samey,  sam ")
    if a != b:                       # only if they really are two rows
        db.merge_jobs(a, [b])
    assert db.name_history(a) == []


def test_a_casing_fix_is_not_recorded():
    key = db.upsert_job(display_name="Casing, Carl")
    db.upsert_job(display_name="casing,  carl")
    assert db.name_history(key) == []


def test_an_unrelated_field_update_is_not_a_rename():
    key = db.upsert_job(display_name="Fields, Fay")
    db.upsert_job(display_name="Fields, Fay", claim_number="123",
                  carrier="Farmers")
    assert db.name_history(key) == []


def test_history_is_per_job():
    a = db.upsert_job(display_name="Alpha, Ann")
    b = db.upsert_job(display_name="Beta, Ben")
    db.upsert_job(display_name="Alpha, Ann - AAA")
    assert len(db.name_history(a)) == 1
    assert db.name_history(b) == []


def test_unknown_or_blank_key_is_empty():
    assert db.name_history("") == []
    assert db.name_history("nobody at all") == []
