"""Contents paperwork, derived from what the folders actually hold.

Across the 99 live CONTENTS folders: invoice 74%, estimate 63%, photo
inventory report 48-61%, pack-out photos 56%. Those are the requirements.
Material Info and Job Diary are TWO forms that happen to get scanned into
one file, so each is checked on its own.

Specialty moves (PODs 7 jobs, safe 1, piano 1, vault 2) are far too rare
to require — they are flagged only when the folder mentions one and no
invoice names it.
"""
import os

import pytest

from audit_logic import check_contents, CONTENTS_FORMS_REQUIRED_FROM


def _mk(tmp_path, files=(), rooms=None):
    """A CONTENTS folder holding `files`, plus room subfolders."""
    c = tmp_path / "CONTENTS"
    c.mkdir()
    for n in files:
        (c / n).write_bytes(b"x")
    for room, shots in (rooms or {}).items():
        d = c / room
        d.mkdir()
        for s in shots:
            (d / s).write_bytes(b"x")
    return str(c)


FULL = (
    "Kathleen Oscar Contents Estimate.pdf",
    "Photo Inventory Report.pdf",
    "Invoice 5030557 CNT MANIP.pdf",
    "Material Info.pdf",
    "Job Diary.pdf",
)
ROOMS = {"Kitchen": ["a.jpg"], "Master Bedroom": ["b.jpg"]}


def test_a_complete_folder_is_clean(tmp_path):
    assert check_contents(_mk(tmp_path, FULL, ROOMS)) == []


def test_no_contents_folder_is_not_a_finding(tmp_path):
    """Only 99 of 623 jobs have contents work. Flagging the other 524
    would bury the ones that matter — unlike EMS, absence means 'not
    this division', not 'incomplete'."""
    assert check_contents(str(tmp_path / "nope")) == []


def test_an_empty_contents_folder_is_not_a_finding(tmp_path):
    assert check_contents(_mk(tmp_path)) == []


@pytest.mark.parametrize("drop,label", [
    ("Kathleen Oscar Contents Estimate.pdf", "Contents Estimate"),
    ("Photo Inventory Report.pdf", "Photo Inventory Report"),
    ("Invoice 5030557 CNT MANIP.pdf", "Contents Invoice"),
    ("Material Info.pdf", "Material Info"),
    ("Job Diary.pdf", "Job Diary"),
])
def test_each_required_document_is_checked(tmp_path, drop, label):
    files = [f for f in FULL if f != drop]
    # Dated: Material Info and Job Diary only apply from the cutoff on.
    assert label in check_contents(_mk(tmp_path, files, ROOMS),
                                   job_date=CONTENTS_FORMS_REQUIRED_FROM)


def test_material_info_and_job_diary_are_separate_forms(tmp_path):
    """They are usually scanned into one file, but they are two forms:
    having one says nothing about the other."""
    files = [f for f in FULL
             if f not in ("Material Info.pdf", "Job Diary.pdf")]
    got = check_contents(_mk(tmp_path, files + ["Material Info.pdf"], ROOMS),
                         job_date=CONTENTS_FORMS_REQUIRED_FROM)
    assert "Job Diary" in got
    assert "Material Info" not in got


def test_the_combined_scan_satisfies_both(tmp_path):
    """'Material Info-Job Diary.pdf' is how they usually arrive."""
    files = [f for f in FULL
             if f not in ("Material Info.pdf", "Job Diary.pdf")]
    got = check_contents(
        _mk(tmp_path, files + ["Material Info-Job Diary.pdf"], ROOMS))
    assert "Material Info" not in got and "Job Diary" not in got


def test_documents_filed_in_a_subfolder_still_count(tmp_path):
    """Some jobs keep the paperwork loose, others in a subfolder."""
    c = tmp_path / "CONTENTS"
    (c / "DOCS").mkdir(parents=True)
    for n in FULL:
        (c / "DOCS" / n).write_bytes(b"x")
    (c / "Kitchen").mkdir()
    (c / "Kitchen" / "a.jpg").write_bytes(b"x")
    assert check_contents(str(c)) == []


def test_room_photos_are_required(tmp_path):
    assert "Room photos" in check_contents(_mk(tmp_path, FULL))


def test_thumbs_db_does_not_count_as_a_photo(tmp_path):
    """Thumbs.db is in 61% of contents folders and is not evidence of
    anything."""
    got = check_contents(_mk(tmp_path, FULL, {"Kitchen": ["Thumbs.db"]}))
    assert "Room photos" in got


# ── specialty moves ────────────────────────────────────────────────────

def test_a_mentioned_specialty_wants_its_invoice(tmp_path):
    got = check_contents(_mk(tmp_path, FULL + ("POD delivery.jpg",), ROOMS))
    assert "POD invoice" in got


def test_a_specialty_invoice_satisfies_it(tmp_path):
    got = check_contents(
        _mk(tmp_path, FULL + ("POD delivery.jpg", "POD Invoice 221.pdf"),
            ROOMS))
    assert "POD invoice" not in got


def test_an_unmentioned_specialty_is_never_asked_for(tmp_path):
    """Requiring a piano invoice on every contents job would flag 98 of
    99 jobs for something that never happened."""
    got = check_contents(_mk(tmp_path, FULL, ROOMS))
    assert not [m for m in got if m.endswith("invoice")]


def test_a_surname_is_not_a_fish_tank(tmp_path):
    """The bug this rule exists for: a substring test matched 'fish'
    inside the client 'Fisher Joel' and reported an aquarium on a job
    that never had one."""
    got = check_contents(
        _mk(tmp_path, FULL + ("Fisher Joel signed.pdf",), ROOMS),
        client_name="Fisher Joel")
    assert "Aquarium invoice" not in got


def test_a_client_named_for_an_item_is_not_a_specialty_move(tmp_path):
    """Some businesses really are called Safe or Vault."""
    got = check_contents(
        _mk(tmp_path, FULL + ("Vault Storage LLC agreement.pdf",), ROOMS),
        client_name="Vault Storage LLC")
    assert "Vault invoice" not in got


def test_a_real_fish_tank_is_still_caught(tmp_path):
    """The guard must not swallow genuine mentions."""
    got = check_contents(_mk(tmp_path, FULL + ("fish tank move.jpg",), ROOMS),
                         client_name="Fisher Joel")
    assert "Aquarium invoice" in got


# ── the dated forms ────────────────────────────────────────────────────


def _without_the_dated_forms():
    return [f for f in FULL
            if f not in ("Material Info.pdf", "Job Diary.pdf")]


def test_older_jobs_are_not_flagged_for_the_dated_forms(tmp_path):
    """These two are on ~22% of live folders. Requiring them everywhere
    flagged 95 of 99 jobs, and a queue that size is one nobody opens."""
    got = check_contents(_mk(tmp_path, _without_the_dated_forms(), ROOMS),
                         job_date="2026-05-01")
    assert "Material Info" not in got and "Job Diary" not in got


def test_jobs_from_the_cutoff_onward_are_flagged(tmp_path):
    got = check_contents(_mk(tmp_path, _without_the_dated_forms(), ROOMS),
                         job_date=CONTENTS_FORMS_REQUIRED_FROM)
    assert "Material Info" in got and "Job Diary" in got


def test_an_unknown_date_is_left_alone(tmp_path):
    """Guessing would put the noise straight back."""
    got = check_contents(_mk(tmp_path, _without_the_dated_forms(), ROOMS))
    assert "Material Info" not in got and "Job Diary" not in got


def test_the_other_requirements_ignore_the_date(tmp_path):
    """Only the two dated forms are gated; the rest apply to everything."""
    files = [f for f in FULL if f != "Invoice 5030557 CNT MANIP.pdf"]
    got = check_contents(_mk(tmp_path, files, ROOMS), job_date="2020-01-01")
    assert "Contents Invoice" in got
